#!/usr/bin/env python3
"""
Saída para Google Sheets — Monitor do Diário Oficial
====================================================

Helpers de Google Sheets/OAuth, portados de `respostas-executivo/index.py`
(convenção do projeto = ferramentas autocontidas, sem lib compartilhada).

Autenticação: OAuth como o próprio usuário. Reusa o mesmo `GOOGLE_OAUTH_TOKEN`
(secret) / `token.json` do respostas-executivo — o token já tem escopo Sheets.
A planilha de destino é uma **nova**, dedicada ao DOM, em `DOM_SHEET_ID`.

Estrutura: **uma única aba** com todos os atos; a coluna "Categoria" (logo no
início) permite filtrar/ordenar por tipo de ato. Só a coluna "Edição" vira
hyperlink. Anexa apenas linhas novas (a dedup acontece no monitor, via SQLite).
"""

import os
import sys

SCOPES_GOOGLE = [
    "https://www.googleapis.com/auth/spreadsheets",
]
# token.json fica em respostas-executivo/ (mesmo token, escopo Sheets já incluso)
TOKEN_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "respostas-executivo", "token.json",
)

ABA = "Atos do DOM"
# Formato da planilha da skill dom-santos (decisão 2026-07-13): mesmas colunas e
# ordem que a skill monta no Claude web. "Data DO" leva o hyperlink da edição;
# "Status" é coluna de trabalho da equipe (o publicador grava "Novo" e nunca reescreve).
COLUNAS = [
    "Nº", "Data DO", "Categoria", "Tipo de Ato", "Órgão/Secretaria",
    "Objeto/Resumo", "Valor (R$)", "Partes Envolvidas", "Base Legal",
    "Nível Atenção", "Observações/Irregularidades", "Ação Sugerida",
    "Status", "Página DO",
]


def conectar_sheets():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    import json
    raw = os.environ.get("GOOGLE_OAUTH_TOKEN")
    if raw:
        creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES_GOOGLE)
    elif os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES_GOOGLE)
    else:
        raise EnvironmentError(
            "Token OAuth não encontrado. Use o token.json do respostas-executivo "
            "(setup_oauth.py) ou defina o secret GOOGLE_OAUTH_TOKEN."
        )
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def separador_formula(sheets, sheet_id: str) -> str:
    """';' em planilhas pt-BR, ',' caso contrário (para a fórmula HYPERLINK)."""
    try:
        meta = sheets.spreadsheets().get(
            spreadsheetId=sheet_id, fields="properties.locale").execute()
        locale = meta.get("properties", {}).get("locale", "")
        return ";" if locale.startswith("pt") else ","
    except Exception:
        return ","


ABA_ANTIGA = "Atos do DOM (formato antigo)"


def garantir_aba(sheets, sheet_id: str) -> None:
    """Cria a aba única (com cabeçalho) se não existir. Se existir com cabeçalho de
    FORMATO diferente (migração p/ o formato da skill, 2026-07), a aba é ARQUIVADA
    (renomeada p/ ABA_ANTIGA, preservando o histórico) e uma nova é criada — reescrever
    só a linha 1 deixaria os dados antigos desalinhados sob rótulos errados."""
    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties").execute()
    props = {s["properties"]["title"]: s["properties"] for s in meta.get("sheets", [])}

    if ABA in props:
        atual = sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{ABA}'!1:1").execute().get("values", [[]])
        if atual and atual[0] == COLUNAS:
            return  # já no formato novo
        if atual and atual[0] and ABA_ANTIGA not in props:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": [{"updateSheetProperties": {
                    "properties": {"sheetId": props[ABA]["sheetId"], "title": ABA_ANTIGA},
                    "fields": "title",
                }}]},
            ).execute()
            print(f"  Aba '{ABA}' arquivada como '{ABA_ANTIGA}' (formato antigo).",
                  file=sys.stderr)
        elif atual and atual[0]:
            raise RuntimeError(
                f"A aba '{ABA}' tem formato antigo e '{ABA_ANTIGA}' já existe — "
                "resolver manualmente antes de gravar.")

    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties").execute()
    existentes = {s["properties"]["title"] for s in meta.get("sheets", [])}
    if ABA not in existentes:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": ABA}}}]},
        ).execute()
        print(f"  Aba criada: {ABA}", file=sys.stderr)
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id, range=f"'{ABA}'!A1",
        valueInputOption="RAW", body={"values": [COLUNAS]},
    ).execute()


def hyperlink(url: str, texto: str, sep: str) -> str:
    return f'=HYPERLINK("{url}"{sep}"{texto}")'


def anexar_linhas(sheets, sheet_id: str, linhas: list[list]) -> None:
    """Anexa linhas (lista de listas, na ordem de COLUNAS) ao fim da aba única."""
    if not linhas:
        return
    sheets.spreadsheets().values().append(
        spreadsheetId=sheet_id, range=f"'{ABA}'!A1",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": linhas},
    ).execute(num_retries=4)


def _sheet_gid(sheets, sheet_id: str) -> int:
    """gid numérico da aba única (necessário p/ insertDimension)."""
    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties").execute()
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == ABA:
            return s["properties"]["sheetId"]
    raise LookupError(f"Aba '{ABA}' não encontrada.")


def inserir_no_topo(sheets, sheet_id: str, linhas: list[list]) -> None:
    """Insere linhas logo ABAIXO do cabeçalho (linha 2), empurrando o histórico
    para baixo — as inserções mais novas ficam sempre no topo da planilha.
    `inheritFromBefore=False` faz as linhas novas herdarem a formatação das de
    baixo (dados), não do cabeçalho."""
    if not linhas:
        return
    gid = _sheet_gid(sheets, sheet_id)
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [{"insertDimension": {
            "range": {"sheetId": gid, "dimension": "ROWS",
                      "startIndex": 1, "endIndex": 1 + len(linhas)},
            "inheritFromBefore": False,
        }}]},
    ).execute(num_retries=4)
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id, range=f"'{ABA}'!A2",
        valueInputOption="USER_ENTERED", body={"values": linhas},
    ).execute(num_retries=4)


def ler_existentes(sheets, sheet_id: str) -> list[dict]:
    """Lê todas as linhas de dados da aba e devolve dicts {coluna: valor} —
    insumo da dedup do publicar.py (a planilha é a fonte da verdade)."""
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{ABA}'!A1:Z",
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute(num_retries=4)
    valores = resp.get("values", [])
    if len(valores) < 2:
        return []
    cab = [str(c) for c in valores[0]]
    return [
        {cab[i]: (str(l[i]) if i < len(l) and l[i] is not None else "")
         for i in range(len(cab))}
        for l in valores[1:]
    ]
