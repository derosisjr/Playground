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
import smtplib
import sys
import unicodedata
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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

# Aba de log diário (criada automaticamente se não existir)
LOG_ABA = "Log diário"
LOG_COLUNAS = [
    "Data processamento", "Tipo", "Número", "Assunto",
    "Data da resposta", "Link",
]


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


def _col_letra(idx: int) -> str:
    """Índice 0-based → letra de coluna A1 (suficiente para até 26 colunas)."""
    return chr(ord("A") + idx)


def _idx_header(cabecalhos: list[str], alvo: str) -> int:
    alvo = _sem_acento(alvo)
    for i, h in enumerate(cabecalhos):
        if _sem_acento(h) == alvo:
            return i
    return -1


def carregar_planilha(sheets, sheet_id: str) -> dict[str, dict]:
    """Lê cada aba e devolve, por aba, os índices de coluna e um mapa
    número→{linha, resp} (resp = se a coluna Resposta já está preenchida)."""
    indice: dict[str, dict] = {}
    for aba in ABAS:
        info = {"col_resp": -1, "col_dataresp": -1, "mapa": {}}
        indice[aba] = info
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
        cab = valores[0]
        idx_num = _idx_coluna_numero(cab)
        info["col_resp"] = _idx_header(cab, "Resposta")
        info["col_dataresp"] = _idx_header(cab, "Data da resposta")
        if idx_num < 0:
            continue
        for n, linha in enumerate(valores[1:], start=2):  # nº da linha (1-based)
            if len(linha) > idx_num and linha[idx_num].strip():
                resp_ok = (
                    info["col_resp"] >= 0
                    and len(linha) > info["col_resp"]
                    and linha[info["col_resp"]].strip() != ""
                )
                info["mapa"][_norm_num(linha[idx_num])] = {"linha": n, "resp": resp_ok}
    return indice


def atualizar_resposta(sheets, sheet_id: str, aba: str, info: dict, linha: int,
                       resposta: str, data_resposta: str) -> None:
    """Preenche as colunas Resposta e Data da resposta de uma linha existente."""
    cr, cd = info["col_resp"], info["col_dataresp"]
    if cr >= 0 and cd == cr + 1:  # colunas contíguas (caso das duas abas)
        sheets.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"'{aba}'!{_col_letra(cr)}{linha}:{_col_letra(cd)}{linha}",
            valueInputOption="USER_ENTERED",
            body={"values": [[resposta, data_resposta]]},
        ).execute()
        return
    for col, val in ((cr, resposta), (cd, data_resposta)):
        if col >= 0:
            sheets.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"'{aba}'!{_col_letra(col)}{linha}",
                valueInputOption="USER_ENTERED",
                body={"values": [[val]]},
            ).execute()


def anexar_linha(sheets, sheet_id: str, aba: str, valores: dict) -> None:
    linha = [valores.get(col, "") for col in ABAS[aba]["colunas"]]
    sheets.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"'{aba}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [linha]},
    ).execute()


def _hyperlink(url: str, texto: str, sep: str) -> str:
    return f'=HYPERLINK("{url}"{sep}"{texto}")'


# ── Log diário ────────────────────────────────────────────────────────────────
def garantir_aba_log(sheets, sheet_id: str) -> None:
    """Cria a aba de log (com cabeçalho) se ela ainda não existir."""
    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties.title").execute()
    titulos = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if LOG_ABA in titulos:
        return
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": LOG_ABA}}}]},
    ).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{LOG_ABA}'!A1",
        valueInputOption="RAW",
        body={"values": [LOG_COLUNAS]},
    ).execute()


def registrar_log(sheets, sheet_id: str, entradas: list[dict]) -> None:
    if not entradas:
        return
    garantir_aba_log(sheets, sheet_id)
    linhas = [[e.get(c, "") for c in LOG_COLUNAS] for e in entradas]
    sheets.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"'{LOG_ABA}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": linhas},
    ).execute()


# ── E-mail resumo ─────────────────────────────────────────────────────────────
def montar_email_html(entradas: list[dict], data: str) -> str:
    linhas = ""
    for e in entradas:
        linhas += (
            "<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{e['Tipo']}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{e['Número']}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{e['Assunto']}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{e['Data da resposta']}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>"
            f"<a href='{e['LinkUrl']}'>abrir pasta</a></td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0A1628">
<div style="max-width:760px;margin:0 auto">
  <div style="border-top:3px solid #C9A84C;padding:16px 0">
    <h2 style="margin:0;color:#07111F">Respostas do Executivo</h2>
    <p style="color:#555;margin:4px 0 0">{len(entradas)} nova(s) resposta(s) — {data}</p>
  </div>
  <table style="border-collapse:collapse;width:100%;font-size:14px">
    <thead><tr style="background:#07111F;color:#fff">
      <th style="padding:8px 10px;text-align:left">Tipo</th>
      <th style="padding:8px 10px;text-align:left">Número</th>
      <th style="padding:8px 10px;text-align:left">Assunto</th>
      <th style="padding:8px 10px;text-align:left">Data resposta</th>
      <th style="padding:8px 10px;text-align:left">Pasta</th>
    </tr></thead>
    <tbody>{linhas}</tbody>
  </table>
  <p style="color:#888;font-size:12px;margin-top:16px">
    Gerado automaticamente pela rotina Respostas do Executivo — Câmara de Santos.
  </p>
</div></body></html>"""


def enviar_email(entradas: list[dict], data: str) -> None:
    user = os.environ.get("GMAIL_USER")
    senha = os.environ.get("GMAIL_APP_PASSWORD")
    para = os.environ.get("GMAIL_TO")
    if not all([user, senha, para]):
        print("Aviso: GMAIL_USER/GMAIL_APP_PASSWORD/GMAIL_TO não definidos; "
              "e-mail não enviado.", file=sys.stderr)
        return
    destinatarios = [d.strip() for d in para.split(",") if d.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Respostas do Executivo — {len(entradas)} nova(s) em {data}"
    msg["From"] = f"Respostas do Executivo <{user}>"
    msg["To"] = ", ".join(destinatarios)
    resumo = "\n".join(
        f"- {e['Tipo']} {e['Número']}: {e['Assunto']} (resposta {e['Data da resposta']})"
        for e in entradas
    )
    msg.attach(MIMEText(resumo, "plain", "utf-8"))
    msg.attach(MIMEText(montar_email_html(entradas, data), "html", "utf-8"))
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(user, senha)
        server.sendmail(user, destinatarios, msg.as_string())
    print(f"E-mail enviado para {', '.join(destinatarios)}.", file=sys.stderr)


# ── Processamento ─────────────────────────────────────────────────────────────
def processar_item(item: dict, drive, pasta_raiz: str, dry_run: bool,
                   sep: str = ",") -> tuple[str, dict, str]:
    """Baixa PDFs, sobe ao Drive e devolve (aba, valores, pasta_url)."""
    aba = aba_do_item(item["tipo"])
    numero = item["numero"] or item["cod"]
    categoria = "REQUERIMENTO" if aba == ABA_REQUERIMENTOS else "INDICACAO"
    nome_pasta = _slug(f"{categoria}_{numero}")

    links_resposta = []
    pasta_id = None
    pasta_url = ""
    if not dry_run:
        pasta_id = obter_ou_criar_subpasta(drive, pasta_raiz, nome_pasta)
        pasta_url = f"https://drive.google.com/drive/folders/{pasta_id}"

    # Pedido (arquivado no Drive; a planilha não tem coluna própria p/ ele)
    if item["pedidoPdf"]:
        dados = baixar_pdf_bytes(item["pedidoPdf"]["url"])
        if dados and not dry_run:
            subir_pdf(drive, pasta_id, _slug(f"PEDIDO {numero} {item['pedidoPdf']['nome']}"), dados)

    # Respostas (arquivadas na subpasta)
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

    # Coluna "Resposta": hyperlink clicável para a subpasta com os PDFs
    if dry_run:
        resposta_cell = "\n".join(links_resposta)
    else:
        resposta_cell = _hyperlink(pasta_url, "Resposta", sep)

    col_numero = "Número" if aba == ABA_INDICACOES else "Nùmero"
    valores = {
        "Assunto": item["ementa"],
        "Data da Sessão": item["dataPropositura"],
        col_numero: numero,
        "Resposta": resposta_cell,
        "Data da resposta": item["dataResposta"],
    }
    return aba, valores, pasta_url


def main():
    parser = argparse.ArgumentParser(description="Respostas do Executivo — Câmara de Santos")
    parser.add_argument("--ano", default=str(datetime.now().year),
                        help="Ano da busca. Padrão: ano corrente.")
    parser.add_argument("--autor", default=AUTOR_PADRAO,
                        help=f"Código do autor. Padrão: {AUTOR_PADRAO}.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Não escreve no Drive nem na planilha.")
    parser.add_argument("--limite", type=int, default=0,
                        help="Processa no máximo N itens (0 = todos).")
    parser.add_argument("--forcar", action="store_true",
                        help="Reprocessa mesmo itens cuja Resposta já está preenchida.")
    parser.add_argument("--email", action="store_true",
                        help="Envia e-mail resumo das respostas processadas (se houver).")
    args = parser.parse_args()

    print(f"Buscando respostas do Executivo — ano {args.ano}, autor {args.autor}...",
          file=sys.stderr)
    itens = coletar_cods(args.ano, args.autor)
    print(f"  {len(itens)} itens encontrados na busca.", file=sys.stderr)

    drive = sheets = None
    sheet_id = os.environ.get("SHEET_ID", "")
    pasta_raiz = os.environ.get("DRIVE_FOLDER_ID", "")
    indice: dict[str, dict] = {aba: {"mapa": {}} for aba in ABAS}
    sep = ","

    if not args.dry_run:
        if not sheet_id or not pasta_raiz:
            raise EnvironmentError("Defina SHEET_ID e DRIVE_FOLDER_ID.")
        drive, sheets = _google_services()
        indice = carregar_planilha(sheets, sheet_id)
        # separador de argumentos de fórmula conforme o locale da planilha
        try:
            meta = sheets.spreadsheets().get(
                spreadsheetId=sheet_id, fields="properties.locale").execute()
            locale = meta.get("properties", {}).get("locale", "")
            sep = ";" if locale.startswith("pt") else ","
        except Exception:
            sep = ","
        total = sum(len(v["mapa"]) for v in indice.values())
        print(f"  {total} linhas já na planilha (sep fórmula '{sep}').", file=sys.stderr)

    hoje = datetime.now().strftime("%d/%m/%Y")
    processados = 0
    log_entradas: list[dict] = []
    for item in itens:
        if args.limite and processados >= args.limite:
            break
        detalhes = detalhar_item(item["cod"])
        detalhes["dataResposta"] = detalhes["dataResposta"] or item["recebimentoBusca"]
        aba = aba_do_item(detalhes["tipo"])
        num = _norm_num(detalhes["numero"])
        if not num:
            continue
        info = indice.get(aba, {"mapa": {}})
        existente = info["mapa"].get(num)
        if existente and existente.get("resp") and not args.forcar:
            continue  # resposta já preenchida — pula (use --forcar para reprocessar)

        rotulo = f"{detalhes['tipo']} {detalhes['numero']} (cod={item['cod']}) → {aba}"
        acao = "atualiza" if existente else "nova linha"
        print(f"Processando ({acao}): {rotulo}", file=sys.stderr)
        aba, valores, pasta_url = processar_item(
            detalhes, drive, pasta_raiz, args.dry_run, sep)

        if args.dry_run:
            print(json.dumps({"aba": aba, "acao": acao, **valores}, ensure_ascii=False, indent=2))
        else:
            if existente:
                atualizar_resposta(sheets, sheet_id, aba, info, existente["linha"],
                                   valores["Resposta"], valores["Data da resposta"])
                existente["resp"] = True
            else:
                anexar_linha(sheets, sheet_id, aba, valores)
                info["mapa"][num] = {"linha": -1, "resp": True}
            log_entradas.append({
                "Data processamento": hoje,
                "Tipo": detalhes["tipo"],
                "Número": detalhes["numero"],
                "Assunto": detalhes["ementa"],
                "Data da resposta": detalhes["dataResposta"],
                "Link": _hyperlink(pasta_url, "Abrir", sep),
                "LinkUrl": pasta_url,
            })
        processados += 1

    print(f"Concluído: {processados} itens processados.", file=sys.stderr)

    if not args.dry_run and log_entradas:
        registrar_log(sheets, sheet_id, log_entradas)
        print(f"Log diário: {len(log_entradas)} linha(s) registrada(s).", file=sys.stderr)
        if args.email:
            enviar_email(log_entradas, hoje)


if __name__ == "__main__":
    main()
