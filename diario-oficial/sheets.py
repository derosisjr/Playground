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
# Ordem pensada para leitura/filtro: Categoria e Tipo na frente; identificação e
# conteúdo no meio; página/edição/carimbo no fim.
COLUNAS = [
    "Edição", "Página", "Categoria", "Tipo", "Secretaria", "Objeto", "Valor",
    "Favorecido/Contratada", "Processo", "Modalidade", "Vigência",
    "Risco", "Motivo do risco",
    # "Trecho" = ~200 caracteres do ato como saiu no DOM, p/ a equipe conferir cada
    # linha contra o diário sem abrir o PDF (auditoria).
    "Trecho",
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


def garantir_aba(sheets, sheet_id: str) -> None:
    """Cria a aba única (com cabeçalho) se não existir; se existir, garante que o
    cabeçalho está atualizado (ex.: acréscimo da coluna 'Trecho') sem mexer nos dados."""
    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties").execute()
    existentes = {s["properties"]["title"] for s in meta.get("sheets", [])}
    if ABA not in existentes:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": ABA}}}]},
        ).execute()
        print(f"  Aba criada: {ABA}", file=sys.stderr)
    # (re)escreve o cabeçalho se estiver ausente/desatualizado — só a linha 1.
    atual = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{ABA}'!1:1").execute().get("values", [[]])
    if not atual or atual[0] != COLUNAS:
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
