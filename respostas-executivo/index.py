#!/usr/bin/env python3
"""
Respostas do Executivo — Câmara de Santos
==========================================

Varre a busca pública de "Respostas do Executivo" endereçadas ao vereador,
baixa os PDFs (pedido original + resposta do prefeito), organiza-os no Google
Drive (uma subpasta por item) e registra cada item na planilha de controle —
roteando para a aba "indicações" ou "requerimentos" conforme o tipo.

Fonte (sem e-mail):
    https://administrativo.camarasantos.sp.gov.br/dispositivo/customizado_publico/
    legislativo/busca_documento_pub/filtro_resultado.php
        ?pesquisa_resposta_executivo[ano]=2026
        &pesquisa_resposta_executivo[autor]=282
        &pesquisa_resposta_executivo[assunto]=

Cada resultado aponta para a página "Mais detalhes" (detalhes.php?cod=...) do
PEDIDO original, fonte canônica com tipo, número, processo, data, ementa, o PDF
do pedido e a seção "Resposta anexada" com os PDFs do prefeito.

Variáveis de ambiente (secrets):
    GOOGLE_OAUTH_TOKEN   conteúdo JSON do token OAuth (gerado por setup_oauth.py)
    SHEET_ID             ID da planilha de controle
    DRIVE_FOLDER_ID      ID da pasta-raiz no Drive

Autenticação: OAuth como o próprio usuário (sem e-mail) — os arquivos ficam no
seu Drive sem problema de cota. Rode `python respostas-executivo/setup_oauth.py`
uma única vez para gerar o token; localmente ele é lido de `token.json`, no
GitHub Actions do secret GOOGLE_OAUTH_TOKEN.

Uso:
    python respostas-executivo/index.py                 # ano corrente
    python respostas-executivo/index.py --ano 2026
    python respostas-executivo/index.py --autor 282
    python respostas-executivo/index.py --dry-run       # não escreve em lugar nenhum
    python respostas-executivo/index.py --limite 3      # processa no máx N itens novos
"""

import argparse
import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Garante UTF-8 na saída mesmo em consoles Windows (cp1252)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# ── Configuração ──────────────────────────────────────────────────────────────
BASE_URL = "https://administrativo.camarasantos.sp.gov.br"
BUSCA_URL = (
    f"{BASE_URL}/dispositivo/customizado_publico/legislativo/busca_documento_pub/"
    "filtro_resultado.php"
)
DETALHES_URL = (
    f"{BASE_URL}/dispositivo/customizado_publico/legislativo/busca_documento_pub/"
    "detalhes.php"
)
AUTOR_PADRAO = "282"  # Rui Sergio Gomes de Rosis Junior
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RespostasExecutivoBot/1.0)"}
PAGINA_TAMANHO = 20

# Estrutura das abas da planilha. A ordem de "colunas" deve casar exatamente com
# a ordem das colunas na aba real. As colunas não preenchidas automaticamente
# (julgamento manual) ficam em branco. A dedup é feita pela coluna de número.
ABA_INDICACOES = "indicações"
ABA_REQUERIMENTOS = "requerimentos"
ABAS = {
    ABA_INDICACOES: {
        "colunas": [
            "sta", "Assunto", "Data da Sessão", "Número",
            "Data do Protocolo na PMS", "Prazo", "Resposta",
            "Data da resposta", "A contento", "Bairro",
        ],
    },
    ABA_REQUERIMENTOS: {
        "colunas": [
            "Ordem", "Assunto", "Secretaria", "Data da Sessão", "Nùmero",
            "Data do Protocolo na PMS", "Prazo", "Resposta",
            "Data da resposta", "Status atual",
        ],
    },
}


# ── HTTP ──────────────────────────────────────────────────────────────────────
def fetch_html(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.content


def baixar_pdf_bytes(url: str) -> bytes | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"  Aviso: não foi possível baixar PDF {url}: {e}", file=sys.stderr)
        return None


def _text(tag) -> str:
    return tag.get_text(separator=" ", strip=True) if tag else ""


def _sem_acento(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower().strip()


def _norm_num(s: str) -> str:
    """Normaliza um número de propositura para comparação (apenas dígitos)."""
    return re.sub(r"\D", "", s or "")


def aba_do_item(tipo: str) -> str:
    return ABA_INDICACOES if "indica" in _sem_acento(tipo) else ABA_REQUERIMENTOS


def _idx_coluna_numero(cabecalhos: list[str]) -> int:
    for i, h in enumerate(cabecalhos):
        if _sem_acento(h) == "numero":
            return i
    return -1


# ── Scraping da busca ─────────────────────────────────────────────────────────
def coletar_cods(ano: str, autor: str) -> list[dict]:
    """Varre todas as páginas da busca e retorna os itens (cod do pedido original)."""
    itens: list[dict] = []
    vistos: set[str] = set()
    limite = 0
    while True:
        params = {
            "pesquisa_resposta_executivo[ano]": ano,
            "pesquisa_resposta_executivo[autor]": autor,
            "pesquisa_resposta_executivo[assunto]": "",
        }
        if limite:
            params["limite"] = str(limite)
        resp = requests.get(BUSCA_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding="iso-8859-1")
        tabelas = soup.select("table.table-bordered")
        if not tabelas:
            break
        novos_na_pagina = 0
        for tab in tabelas:
            # 2º link do cabeçalho = "Mais detalhes" → cod do pedido original
            link_detalhes = tab.select_one("thead a.btn-info[href*='detalhes.php']")
            if not link_detalhes:
                continue
            m = re.search(r"cod=(\d+)", link_detalhes.get("href", ""))
            if not m:
                continue
            cod = m.group(1)
            if cod in vistos:
                continue
            vistos.add(cod)
            novos_na_pagina += 1
            recebimento = ""
            for row in tab.select("tbody tr"):
                th = row.find("th")
                if th and "Recebimento" in th.get_text():
                    recebimento = _text(row.find("td"))
                    break
            itens.append({"cod": cod, "recebimentoBusca": recebimento})
        if novos_na_pagina == 0:
            break
        limite += PAGINA_TAMANHO
    return itens


# ── Scraping dos detalhes ─────────────────────────────────────────────────────
def detalhar_item(cod: str) -> dict:
    """Faz scraping da página de detalhes do pedido original (Mais detalhes)."""
    url = f"{DETALHES_URL}?cod={cod}"
    soup = BeautifulSoup(fetch_html(url), "html.parser", from_encoding="iso-8859-1")

    tabela_info = soup.select_one("table.table-bordered")
    titulo = _text(tabela_info.select_one("thead th strong")) if tabela_info else ""

    # "Requerimento - Nº 1729/2026 [Processo Nº 4674/2026]"
    tipo, numero, processo = "", "", ""
    m = re.match(r"\s*(.+?)\s*-\s*N[ºo°]\s*([\d./-]+)", titulo)
    if m:
        tipo = m.group(1).strip()
        numero = m.group(2).strip()
    mp = re.search(r"Processo\s*N[ºo°]\s*([\d./-]+)", titulo)
    if mp:
        processo = mp.group(1).strip()

    # Campos Número / Data / Autor / Local + Ementa
    campos: dict[str, str] = {}
    ementa = ""
    if tabela_info:
        for row in tabela_info.select("tbody tr"):
            th = row.find("th")
            tds = row.find_all("td")
            if th and tds:
                chave = th.get_text(strip=True).rstrip(":")
                if chave:
                    campos[chave] = tds[0].get_text(separator=" ", strip=True)
            span = row.find("span")
            if span and "Ementa" in span.get_text():
                texto = row.find("td").get_text(separator=" ", strip=True)
                ementa = re.sub(r"^Ementa:\s*", "", texto).strip()

    numero = numero or campos.get("Número", "")
    data_propositura = campos.get("Data", "")
    autor = campos.get("Autor", "")

    # PDF do pedido: único link .pdf dentro da tabela de informações principal
    pedido_pdf = None
    if tabela_info:
        a = tabela_info.find("a", href=re.compile(r"\.pdf", re.I))
        if a:
            pedido_pdf = {"url": urljoin(url, a["href"]), "nome": _nome_arquivo(a["href"])}

    # Resposta anexada: tabela após o <h4>Resposta anexada</h4>
    respostas: list[dict] = []
    data_resposta = ""
    h4 = soup.find("h4", string=re.compile(r"Resposta anexada", re.I))
    if h4:
        tab_resp = h4.find_next("table")
        if tab_resp:
            for a in tab_resp.find_all("a", href=re.compile(r"\.pdf", re.I)):
                respostas.append({"url": urljoin(url, a["href"]), "nome": _nome_arquivo(a["href"])})
            for row in tab_resp.select("tr"):
                th = row.find("th")
                if th and "recebimento" in th.get_text().lower():
                    data_resposta = _text(row.find("td"))
                    break

    return {
        "cod": cod,
        "tipo": tipo,
        "numero": numero,
        "processo": processo,
        "dataPropositura": data_propositura,
        "dataResposta": data_resposta,
        "autor": autor,
        "ementa": ementa,
        "detalhesUrl": url,
        "pedidoPdf": pedido_pdf,
        "respostasPdf": respostas,
    }


def _nome_arquivo(href: str) -> str:
    return href.rstrip("/").split("/")[-1]


def _slug(texto: str) -> str:
    return re.sub(r"[^\w./-]", "_", texto.replace("/", "-")).strip("_")


# ── Google Drive / Sheets ─────────────────────────────────────────────────────
SCOPES_GOOGLE = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")


def _google_services():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    raw = os.environ.get("GOOGLE_OAUTH_TOKEN")
    if raw:
        creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES_GOOGLE)
    elif os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES_GOOGLE)
    else:
        raise EnvironmentError(
            "Token OAuth não encontrado. Rode setup_oauth.py para gerar token.json "
            "ou defina o secret GOOGLE_OAUTH_TOKEN."
        )
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return drive, sheets


def obter_ou_criar_subpasta(drive, pasta_raiz: str, nome: str) -> str:
    nome_escapado = nome.replace("'", "\\'")
    q = (
        f"name = '{nome_escapado}' and '{pasta_raiz}' in parents "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    res = drive.files().list(
        q=q, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    arquivos = res.get("files", [])
    if arquivos:
        return arquivos[0]["id"]
    meta = {
        "name": nome,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [pasta_raiz],
    }
    pasta = drive.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    return pasta["id"]


def subir_pdf(drive, pasta_id: str, nome: str, dados: bytes) -> str:
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(io.BytesIO(dados), mimetype="application/pdf")
    meta = {"name": nome, "parents": [pasta_id]}
    arquivo = drive.files().create(
        body=meta, media_body=media, fields="webViewLink", supportsAllDrives=True,
    ).execute()
    return arquivo.get("webViewLink", "")


def numeros_registrados(sheets, sheet_id: str) -> dict[str, set[str]]:
    """Lê o número de cada aba e devolve {aba: {números normalizados}} p/ dedup."""
    registrados: dict[str, set[str]] = {}
    for aba in ABAS:
        registrados[aba] = set()
        try:
            res = sheets.spreadsheets().values().get(
                spreadsheetId=sheet_id, range=f"'{aba}'!A1:Z",
            ).execute()
        except Exception as e:
            print(f"Aviso: não consegui ler a aba '{aba}': {e}", file=sys.stderr)
            continue
        valores = res.get("values", [])
        if not valores:
            continue
        idx = _idx_coluna_numero(valores[0])
        if idx < 0:
            continue
        for linha in valores[1:]:
            if len(linha) > idx and linha[idx].strip():
                registrados[aba].add(_norm_num(linha[idx]))
    return registrados


def anexar_linha(sheets, sheet_id: str, aba: str, valores: dict) -> None:
    linha = [valores.get(col, "") for col in ABAS[aba]["colunas"]]
    sheets.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"'{aba}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [linha]},
    ).execute()


# ── Processamento ─────────────────────────────────────────────────────────────
def processar_item(item: dict, drive, sheet_id: str, pasta_raiz: str,
                   dry_run: bool) -> tuple[str, dict]:
    """Baixa PDFs, sobe ao Drive e devolve (aba, valores) p/ a planilha."""
    aba = aba_do_item(item["tipo"])
    tipo = item["tipo"] or "Documento"
    numero = item["numero"] or item["cod"]
    nome_pasta = _slug(f"{tipo} {numero}")

    links_resposta = []
    pasta_id = None
    if not dry_run:
        pasta_id = obter_ou_criar_subpasta(drive, pasta_raiz, nome_pasta)

    # Pedido (arquivado no Drive; a planilha não tem coluna própria p/ ele)
    if item["pedidoPdf"]:
        dados = baixar_pdf_bytes(item["pedidoPdf"]["url"])
        if dados and not dry_run:
            subir_pdf(drive, pasta_id, _slug(f"PEDIDO {numero} {item['pedidoPdf']['nome']}"), dados)

    # Respostas (link entra na coluna "Resposta")
    for i, pdf in enumerate(item["respostasPdf"], 1):
        dados = baixar_pdf_bytes(pdf["url"])
        if not dados:
            continue
        if dry_run:
            links_resposta.append(pdf["url"])
        else:
            links_resposta.append(
                subir_pdf(drive, pasta_id, _slug(f"RESPOSTA {i} {numero} {pdf['nome']}"), dados)
            )

    col_numero = "Número" if aba == ABA_INDICACOES else "Nùmero"
    valores = {
        "Assunto": item["ementa"],
        "Data da Sessão": item["dataPropositura"],
        col_numero: numero,
        "Resposta": "\n".join(links_resposta),
        "Data da resposta": item["dataResposta"],
    }
    return aba, valores


def main():
    parser = argparse.ArgumentParser(description="Respostas do Executivo — Câmara de Santos")
    parser.add_argument("--ano", default=str(datetime.now().year),
                        help="Ano da busca. Padrão: ano corrente.")
    parser.add_argument("--autor", default=AUTOR_PADRAO,
                        help=f"Código do autor. Padrão: {AUTOR_PADRAO}.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Não escreve no Drive nem na planilha.")
    parser.add_argument("--limite", type=int, default=0,
                        help="Processa no máximo N itens novos (0 = todos).")
    args = parser.parse_args()

    print(f"Buscando respostas do Executivo — ano {args.ano}, autor {args.autor}...",
          file=sys.stderr)
    itens = coletar_cods(args.ano, args.autor)
    print(f"  {len(itens)} itens encontrados na busca.", file=sys.stderr)

    drive = sheets = None
    sheet_id = os.environ.get("SHEET_ID", "")
    pasta_raiz = os.environ.get("DRIVE_FOLDER_ID", "")
    registrados: dict[str, set[str]] = {aba: set() for aba in ABAS}

    if not args.dry_run:
        if not sheet_id or not pasta_raiz:
            raise EnvironmentError("Defina SHEET_ID e DRIVE_FOLDER_ID.")
        drive, sheets = _google_services()
        registrados = numeros_registrados(sheets, sheet_id)
        total = sum(len(v) for v in registrados.values())
        print(f"  {total} números já registrados na planilha.", file=sys.stderr)

    processados = 0
    for item in itens:
        if args.limite and processados >= args.limite:
            break
        detalhes = detalhar_item(item["cod"])
        detalhes["dataResposta"] = detalhes["dataResposta"] or item["recebimentoBusca"]
        aba = aba_do_item(detalhes["tipo"])
        if _norm_num(detalhes["numero"]) in registrados.get(aba, set()):
            continue
        rotulo = f"{detalhes['tipo']} {detalhes['numero']} (cod={item['cod']}) → {aba}"
        print(f"Processando: {rotulo}", file=sys.stderr)
        aba, valores = processar_item(detalhes, drive, sheet_id, pasta_raiz, args.dry_run)
        if args.dry_run:
            print(json.dumps({"aba": aba, **valores}, ensure_ascii=False, indent=2))
        else:
            anexar_linha(sheets, sheet_id, aba, valores)
            registrados.setdefault(aba, set()).add(_norm_num(detalhes["numero"]))
        processados += 1

    print(f"Concluído: {processados} itens processados.", file=sys.stderr)


if __name__ == "__main__":
    main()
