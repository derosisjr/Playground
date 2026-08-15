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
import time
import unicodedata
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classificar as cls  # noqa: E402  (mesmo diretório; ver bloco sys.path acima)

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
ANO_INICIAL = 2025  # 1º ano do mandato; varredura padrão vai daqui até o ano corrente
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RespostasExecutivoBot/1.0)"}
PAGINA_TAMANHO = 20

# Estrutura das abas da planilha. A ordem de "colunas" deve casar exatamente com
# a ordem das colunas na aba real. As colunas não preenchidas automaticamente
# (julgamento manual) ficam em branco. A dedup é feita pela coluna de número.
ABA_INDICACOES = "indicações"
ABA_REQUERIMENTOS = "requerimentos"
#
# `Situação da resposta` e `Data da resposta de mérito` são preenchidas pela
# classificação dos PDFs (ver classificar.py): nem todo anexo é resposta — pedido
# de prorrogação de prazo e ofício de encaminhamento chegam pelo mesmo canal.
# `Data da resposta` continua sendo a data mais recente de QUALQUER anexo, para
# não quebrar a conferência manual da assessoria.
COL_SITUACAO = "Situação da resposta"
COL_DATA_MERITO = "Data da resposta de mérito"
COLUNAS_CLASSIFICACAO = [COL_SITUACAO, COL_DATA_MERITO]
ABAS = {
    ABA_INDICACOES: {
        "colunas": [
            "sta", "Assunto", "Data da Sessão", "Número",
            "Data do Protocolo na PMS", "Prazo", "Resposta",
            "Data da resposta", "A contento", "Bairro",
            *COLUNAS_CLASSIFICACAO,
        ],
    },
    ABA_REQUERIMENTOS: {
        "colunas": [
            "Ordem", "Assunto", "Secretaria", "Data da Sessão", "Nùmero",
            "Data do Protocolo na PMS", "Prazo", "Resposta",
            "Data da resposta", "Status atual",
            *COLUNAS_CLASSIFICACAO,
        ],
    },
}

# Aba de log diário (criada automaticamente se não existir)
LOG_ABA = "Log diário"
# "Situação" vai no fim de propósito: a aba já existe em produção e as linhas
# antigas foram gravadas na ordem anterior.
LOG_COLUNAS = [
    "Data processamento", "Tipo", "Número", "Assunto",
    "Data da resposta", "Link", "Situação",
]


# ── HTTP ──────────────────────────────────────────────────────────────────────
def _http_get(url: str, params: dict | None = None, timeout: int = 30,
              tentativas: int = 4) -> requests.Response:
    """GET com retry/backoff para tolerar timeouts transitórios do site."""
    ultimo_erro = None
    for i in range(tentativas):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            ultimo_erro = e
            if i < tentativas - 1:
                espera = 4 * (i + 1)
                print(f"  Aviso: falha HTTP ({e}); tentativa {i + 1}/{tentativas}, "
                      f"aguardando {espera}s...", file=sys.stderr)
                time.sleep(espera)
    raise ultimo_erro


def fetch_html(url: str) -> bytes:
    return _http_get(url, timeout=30).content


def baixar_pdf_bytes(url: str) -> bytes | None:
    try:
        return _http_get(url, timeout=60).content
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


def _chave_data(d: str) -> tuple | None:
    """'dd/mm/aaaa' → chave ordenável (aaaa, mm, dd); None se não fizer parse."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", d or "")
    return (m.group(3), m.group(2), m.group(1)) if m else None


def _data_mais_recente(datas: list[str]) -> str:
    """Dada uma lista de datas 'dd/mm/aaaa', devolve a mais recente (string original).
    Se nenhuma fizer parse, devolve a última da lista (ou '' se vazia)."""
    melhor, melhor_chave = "", None
    for d in datas:
        chave = _chave_data(d)
        if chave is None:
            continue
        if melhor_chave is None or chave > melhor_chave:
            melhor_chave, melhor = chave, d.strip()
    if melhor:
        return melhor
    return datas[-1].strip() if datas else ""


def _data_mais_antiga(datas: list[str]) -> str:
    """A primeira data da lista em ordem cronológica ('' se nenhuma fizer parse).

    Usada para a data da resposta DE MÉRITO: o que interessa é quando o conteúdo
    chegou pela primeira vez, não a última movimentação do processo."""
    melhor, melhor_chave = "", None
    for d in datas:
        chave = _chave_data(d)
        if chave is None:
            continue
        if melhor_chave is None or chave < melhor_chave:
            melhor_chave, melhor = chave, d.strip()
    return melhor


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
        resp = _http_get(BUSCA_URL, params=params, timeout=30)
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

    # Resposta anexada: pode haver VÁRIOS blocos <h4>Resposta anexada</h4>, um por
    # resposta do prefeito (ex.: 1º pedido de dilação de prazo, 2º a resposta de fato).
    # Coletamos os PDFs de todos os blocos e usamos como dataResposta a MAIS RECENTE.
    # Cada PDF carrega a data do SEU bloco: sem isso não dá para saber quando chegou
    # a resposta de mérito, já que os blocos misturam trâmite e conteúdo.
    respostas: list[dict] = []
    urls_vistas: set[str] = set()
    datas_resposta: list[str] = []
    for h4 in soup.find_all("h4", string=re.compile(r"Resposta anexada", re.I)):
        tab_resp = h4.find_next("table")
        if not tab_resp:
            continue
        data_bloco = ""
        for row in tab_resp.select("tr"):
            th = row.find("th")
            if th and "recebimento" in th.get_text().lower():
                data_bloco = _text(row.find("td"))
                break
        if data_bloco:
            datas_resposta.append(data_bloco)
        for a in tab_resp.find_all("a", href=re.compile(r"\.pdf", re.I)):
            href = urljoin(url, a["href"])
            if href in urls_vistas:
                continue
            urls_vistas.add(href)
            respostas.append({
                "url": href, "nome": _nome_arquivo(a["href"]), "data": data_bloco,
            })
    data_resposta = _data_mais_recente(datas_resposta)

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


def listar_arquivos_pasta(drive, pasta_id: str) -> list[dict]:
    """Lista os arquivos (não-pasta) de uma pasta, com id/nome/link/criação."""
    arquivos: list[dict] = []
    token = None
    while True:
        res = drive.files().list(
            q=f"'{pasta_id}' in parents and trashed = false "
              "and mimeType != 'application/vnd.google-apps.folder'",
            fields="nextPageToken, files(id, name, webViewLink, createdTime, size)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            pageToken=token,
        ).execute()
        arquivos.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            break
    return arquivos


def limpar_duplicatas(drive, arquivos: list[dict]) -> list[dict]:
    """Remove cópias redundantes (mesmo nome) de uma pasta, mantendo a mais antiga.
    Devolve a lista de arquivos remanescentes (1 por nome)."""
    por_nome: dict[str, list[dict]] = {}
    for a in arquivos:
        por_nome.setdefault(a["name"], []).append(a)
    remanescentes: list[dict] = []
    for nome, grupo in por_nome.items():
        if len(grupo) > 1:
            grupo.sort(key=lambda x: x.get("createdTime", ""))  # mantém a mais antiga
            for extra in grupo[1:]:
                try:
                    drive.files().delete(
                        fileId=extra["id"], supportsAllDrives=True).execute()
                    print(f"  Duplicata removida: {nome} (id={extra['id']})",
                          file=sys.stderr)
                except Exception as e:
                    print(f"  Aviso: falha ao remover duplicata {nome}: {e}",
                          file=sys.stderr)
        remanescentes.append(grupo[0])
    return remanescentes


def subir_pdf(drive, pasta_id: str, nome: str, dados: bytes,
              existentes: dict[str, str] | None = None) -> str:
    """Sobe um PDF, evitando re-upload se já houver arquivo com esse nome na pasta.
    `existentes` (nome→webViewLink) evita uma consulta por arquivo; se não vier,
    consulta a pasta pelo nome."""
    from googleapiclient.http import MediaIoBaseUpload

    if existentes is not None:
        if nome in existentes:
            return existentes[nome]
    else:
        nome_escapado = nome.replace("'", "\\'")
        achados = drive.files().list(
            q=f"name = '{nome_escapado}' and '{pasta_id}' in parents and trashed = false",
            fields="files(webViewLink)", supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute().get("files", [])
        if achados:
            return achados[0].get("webViewLink", "")

    media = MediaIoBaseUpload(io.BytesIO(dados), mimetype="application/pdf")
    meta = {"name": nome, "parents": [pasta_id]}
    arquivo = drive.files().create(
        body=meta, media_body=media, fields="webViewLink", supportsAllDrives=True,
    ).execute()
    link = arquivo.get("webViewLink", "")
    if existentes is not None:
        existentes[nome] = link
    return link


def _col_letra(idx: int) -> str:
    """Índice 0-based → letra de coluna A1 (suficiente para até 26 colunas)."""
    return chr(ord("A") + idx)


def _idx_header(cabecalhos: list[str], alvo: str) -> int:
    alvo = _sem_acento(alvo)
    for i, h in enumerate(cabecalhos):
        if _sem_acento(h) == alvo:
            return i
    return -1


def garantir_colunas(sheets, sheet_id: str, aba: str) -> list[str]:
    """Garante que o cabeçalho da aba contenha as colunas declaradas em ABAS,
    acrescentando ao fim as que faltarem. Devolve o cabeçalho resultante.

    Necessário porque `anexar_linha` monta a linha pela ordem de ABAS: se a
    planilha real não tiver as colunas novas, os valores entrariam deslocados."""
    res = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{aba}'!1:1",
    ).execute()
    cab = (res.get("values") or [[]])[0]
    faltantes = [c for c in ABAS[aba]["colunas"] if _idx_header(cab, c) < 0]
    if not faltantes:
        return cab
    novo = cab + faltantes
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{aba}'!A1",
        valueInputOption="RAW",
        body={"values": [novo]},
    ).execute()
    print(f"  Aba '{aba}': coluna(s) criada(s) — {', '.join(faltantes)}.", file=sys.stderr)
    return novo


def listar_subpastas(drive, pasta_raiz: str) -> list[dict]:
    """Lista as subpastas de uma pasta do Drive (id/nome)."""
    pastas: list[dict] = []
    token = None
    while True:
        res = drive.files().list(
            q=f"'{pasta_raiz}' in parents and trashed = false "
              "and mimeType = 'application/vnd.google-apps.folder'",
            fields="nextPageToken, files(id, name)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            pageSize=1000, pageToken=token,
        ).execute()
        pastas.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            break
    return pastas


def carregar_planilha(sheets, sheet_id: str) -> dict[str, dict]:
    """Lê cada aba e devolve, por aba, os índices de coluna e um mapa
    número→{linha, resp} (resp = se a coluna Resposta já está preenchida)."""
    indice: dict[str, dict] = {}
    for aba in ABAS:
        info = {"col_resp": -1, "col_dataresp": -1, "col_situacao": -1,
                "col_merito": -1, "mapa": {}}
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
        info["col_situacao"] = _idx_header(cab, COL_SITUACAO)
        info["col_merito"] = _idx_header(cab, COL_DATA_MERITO)
        if idx_num < 0:
            continue

        def celula(linha: list, col: int) -> str:
            return linha[col].strip() if 0 <= col < len(linha) else ""

        for n, linha in enumerate(valores[1:], start=2):  # nº da linha (1-based)
            if len(linha) > idx_num and linha[idx_num].strip():
                info["mapa"][_norm_num(linha[idx_num])] = {
                    "linha": n,
                    "resp": celula(linha, info["col_resp"]) != "",
                    "sit": celula(linha, info["col_situacao"]),
                }
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


def atualizar_classificacao(sheets, sheet_id: str, aba: str, info: dict, linha: int,
                            valores: dict) -> None:
    """Grava `Situação da resposta` e `Data da resposta de mérito` de uma linha.

    Silencioso quando `valores` não traz a situação — sinal de que a passagem não
    classificou todos os PDFs e não tem veredito confiável para escrever."""
    if COL_SITUACAO not in valores:
        return
    cs, cm = info.get("col_situacao", -1), info.get("col_merito", -1)
    if cs >= 0 and cm == cs + 1:  # colunas contíguas (é como são criadas)
        sheets.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"'{aba}'!{_col_letra(cs)}{linha}:{_col_letra(cm)}{linha}",
            valueInputOption="USER_ENTERED",
            body={"values": [[valores[COL_SITUACAO], valores.get(COL_DATA_MERITO, "")]]},
        ).execute()
        return
    for col, val in ((cs, valores[COL_SITUACAO]), (cm, valores.get(COL_DATA_MERITO, ""))):
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
def _executar(req, *, tentativas: int = 4, espera: float = 3.0):
    """Executa `req.execute()` com retry em erros transitórios de rede/SSL.

    A API do Google às vezes derruba a conexão (ssl.SSLEOFError, timeouts),
    o que abortava a run inteira mesmo após o trabalho útil ter concluído.
    """
    import socket
    import ssl
    for i in range(tentativas):
        try:
            return req.execute()
        except (ssl.SSLError, socket.error, ConnectionError, TimeoutError) as e:
            if i == tentativas - 1:
                raise
            print(f"  rede instável ({type(e).__name__}: {e}); "
                  f"retry {i + 2}/{tentativas} em {espera:.0f}s...", file=sys.stderr)
            time.sleep(espera)
            espera *= 2


def garantir_aba_log(sheets, sheet_id: str) -> None:
    """Cria a aba de log se não existir; se existir, completa o cabeçalho com as
    colunas que faltarem (as linhas são montadas pela ordem de LOG_COLUNAS)."""
    meta = _executar(sheets.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties.title"))
    titulos = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if LOG_ABA in titulos:
        res = _executar(sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{LOG_ABA}'!1:1"))
        cab = (res.get("values") or [[]])[0]
        if any(_idx_header(cab, c) < 0 for c in LOG_COLUNAS):
            _executar(sheets.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f"'{LOG_ABA}'!A1",
                valueInputOption="RAW", body={"values": [LOG_COLUNAS]}))
        return
    _executar(sheets.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": LOG_ABA}}}]},
    ))
    _executar(sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{LOG_ABA}'!A1",
        valueInputOption="RAW",
        body={"values": [LOG_COLUNAS]},
    ))


def registrar_log(sheets, sheet_id: str, entradas: list[dict]) -> None:
    if not entradas:
        return
    garantir_aba_log(sheets, sheet_id)
    linhas = [[e.get(c, "") for c in LOG_COLUNAS] for e in entradas]
    _executar(sheets.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"'{LOG_ABA}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": linhas},
    ))


# ── E-mail resumo ─────────────────────────────────────────────────────────────
def montar_email_html(entradas: list[dict], data: str) -> str:
    from html import escape as _esc  # campos raspados entram escapados no HTML
    linhas = ""
    for e in entradas:
        linhas += (
            "<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{_esc(e['Tipo'])}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{_esc(e['Número'])}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{_esc(e['Assunto'])}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{_esc(e['Data da resposta'])}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{_esc(e.get('Situação', '—'))}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>"
            f"<a href='{_esc(e['LinkUrl'])}'>abrir pasta</a></td>"
            "</tr>"
        )
    merito = sum(1 for e in entradas if e.get("Situação") == cls.ROTULOS[cls.RESPONDIDO])
    tramite = len(entradas) - merito
    resumo = f"{merito} resposta(s) de mérito"
    if tramite:
        resumo += f" e {tramite} de trâmite (prazo/encaminhamento)"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0A1628">
<div style="max-width:760px;margin:0 auto">
  <div style="border-top:3px solid #C9A84C;padding:16px 0">
    <h2 style="margin:0;color:#07111F">Respostas do Executivo</h2>
    <p style="color:#555;margin:4px 0 0">{resumo} — {data}</p>
  </div>
  <table style="border-collapse:collapse;width:100%;font-size:14px">
    <thead><tr style="background:#07111F;color:#fff">
      <th style="padding:8px 10px;text-align:left">Tipo</th>
      <th style="padding:8px 10px;text-align:left">Número</th>
      <th style="padding:8px 10px;text-align:left">Assunto</th>
      <th style="padding:8px 10px;text-align:left">Data resposta</th>
      <th style="padding:8px 10px;text-align:left">Situação</th>
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
    # destinatário dedicado (não compartilha com o ordem-do-dia); fallback p/ GMAIL_TO
    para = os.environ.get("RESPOSTAS_EMAIL_TO") or os.environ.get("GMAIL_TO")
    if not all([user, senha, para]):
        print("Aviso: GMAIL_USER/GMAIL_APP_PASSWORD/RESPOSTAS_EMAIL_TO não definidos; "
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
                   sep: str = ",", classificar_tudo: bool = True,
                   ) -> tuple[str, dict, str, bool]:
    """Baixa PDFs que ainda não estão arquivados, sobe ao Drive e devolve
    (aba, valores, pasta_url, resposta_nova) — `resposta_nova` indica se algum PDF
    de RESPOSTA foi arquivado agora (sinal robusto p/ saber se chegou novidade,
    independente do formato de data na planilha).

    `classificar_tudo` faz rebaixar também os PDFs já arquivados, para classificá-los.
    Só vale a pena quando a planilha ainda não tem veredito para o item — do
    contrário seriam centenas de downloads por dia sem novidade nenhuma."""
    aba = aba_do_item(item["tipo"])
    numero = item["numero"] or item["cod"]
    categoria = "REQUERIMENTO" if aba == ABA_REQUERIMENTOS else "INDICACAO"
    nome_pasta = _slug(f"{categoria}_{numero}")

    links_resposta = []
    pasta_id = None
    pasta_url = ""
    existentes: dict[str, str] = {}
    resposta_nova = False
    if not dry_run:
        pasta_id = obter_ou_criar_subpasta(drive, pasta_raiz, nome_pasta)
        pasta_url = f"https://drive.google.com/drive/folders/{pasta_id}"
        # Lista a pasta uma vez: limpa duplicatas antigas e monta o mapa nome→link.
        # Permite pular o download de PDFs já arquivados e detectar respostas novas.
        arquivos = limpar_duplicatas(drive, listar_arquivos_pasta(drive, pasta_id))
        existentes = {a["name"]: a.get("webViewLink", "") for a in arquivos}

    # Pedido (arquivado no Drive; a planilha não tem coluna própria p/ ele)
    if item["pedidoPdf"]:
        nome_pedido = _slug(f"PEDIDO {numero} {item['pedidoPdf']['nome']}")
        if not dry_run and nome_pedido not in existentes:
            dados = baixar_pdf_bytes(item["pedidoPdf"]["url"])
            if dados:
                subir_pdf(drive, pasta_id, nome_pedido, dados, existentes)

    # Respostas (arquivadas na subpasta), classificadas conforme chegam: nem todo
    # anexo é resposta — ver classificar.py.
    classes: list[str] = []
    datas_merito: list[str] = []
    for i, pdf in enumerate(item["respostasPdf"], 1):
        nome_resp = _slug(f"RESPOSTA {i} {numero} {pdf['nome']}")
        arquivado = (not dry_run) and nome_resp in existentes
        dados = None
        if arquivado:
            links_resposta.append(existentes[nome_resp])
            if classificar_tudo:
                dados = baixar_pdf_bytes(pdf["url"])
        else:
            dados = baixar_pdf_bytes(pdf["url"])
            if dry_run:
                links_resposta.append(pdf["url"])
            elif dados:
                links_resposta.append(
                    subir_pdf(drive, pasta_id, nome_resp, dados, existentes))
                resposta_nova = True
            else:
                continue
        if arquivado and not classificar_tudo:
            continue
        classe = cls.classificar(cls.texto_pdf(dados)) if dados else cls.INDETERMINADO
        classes.append(classe)
        if classe in (cls.MERITO, cls.INDETERMINADO) and pdf.get("data"):
            datas_merito.append(pdf["data"])

    # Coluna "Resposta": hyperlink clicável para a subpasta com os PDFs
    if dry_run:
        resposta_cell = "\n".join(links_resposta)
        resposta_nova = True  # sem Drive não dá pra comparar; trata como novidade
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
    # Só grava a situação se TODOS os PDFs foram classificados nesta passagem;
    # caso contrário sobrescreveríamos um veredito bom com um parcial.
    if len(classes) == len(item["respostasPdf"]):
        valores[COL_SITUACAO] = cls.situacao(classes)
        valores[COL_DATA_MERITO] = _data_mais_antiga(datas_merito)
    return aba, valores, pasta_url, resposta_nova


def main():
    parser = argparse.ArgumentParser(description="Respostas do Executivo — Câmara de Santos")
    parser.add_argument("--ano", default="",
                        help=f"Ano(s) da busca, separados por vírgula (ex.: 2025,2026). "
                             f"Padrão: de {ANO_INICIAL} até o ano corrente (respostas ficam "
                             f"no ano de envio da propositura, não no ano da resposta).")
    parser.add_argument("--autor", default=AUTOR_PADRAO,
                        help=f"Código do autor. Padrão: {AUTOR_PADRAO}.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Não escreve no Drive nem na planilha.")
    parser.add_argument("--limite", type=int, default=0,
                        help="Processa no máximo N itens (0 = todos).")
    parser.add_argument("--forcar", action="store_true",
                        help="Reprocessa mesmo itens cuja Resposta já está preenchida.")
    parser.add_argument("--cods", default="",
                        help="Processa apenas estes cods (lista separada por vírgula) e os "
                             "reprocessa mesmo se já respondidos — útil p/ reenviar um e-mail "
                             "que se perdeu, sem reprocessar a base inteira.")
    parser.add_argument("--email", action="store_true",
                        help="Envia e-mail resumo das respostas processadas (se houver).")
    parser.add_argument("--sem-log", action="store_true",
                        help="Não registra na aba Log diário (ex.: carga retroativa).")
    args = parser.parse_args()

    if args.ano.strip():
        anos = [a.strip() for a in args.ano.split(",") if a.strip()]
    else:
        anos = [str(a) for a in range(datetime.now().year, ANO_INICIAL - 1, -1)]

    print(f"Buscando respostas do Executivo — anos {', '.join(anos)}, "
          f"autor {args.autor}...", file=sys.stderr)
    itens: list[dict] = []
    vistos_cod: set[str] = set()
    for ano in anos:
        encontrados = coletar_cods(ano, args.autor)
        novos = [it for it in encontrados if it["cod"] not in vistos_cod]
        vistos_cod.update(it["cod"] for it in novos)
        itens.extend(novos)
        print(f"  {ano}: {len(encontrados)} itens.", file=sys.stderr)
    print(f"  {len(itens)} itens únicos no total.", file=sys.stderr)

    cods_alvo = {c.strip() for c in args.cods.split(",") if c.strip()}
    if cods_alvo:
        itens = [it for it in itens if it["cod"] in cods_alvo]
        print(f"  Filtrado para {len(itens)} de {len(cods_alvo)} cod(s)-alvo.",
              file=sys.stderr)

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
    falhas = 0
    log_entradas: list[dict] = []
    for item in itens:
        if args.limite and processados >= args.limite:
            break
        try:
            detalhes = detalhar_item(item["cod"])
            detalhes["dataResposta"] = detalhes["dataResposta"] or item["recebimentoBusca"]
            aba = aba_do_item(detalhes["tipo"])
            num = _norm_num(detalhes["numero"])
            if not num:
                continue
            info = indice.get(aba, {"mapa": {}})
            existente = info["mapa"].get(num)
            ja_respondido = bool(existente and existente.get("resp"))
            sit_atual = (existente or {}).get("sit", "")
            # Reclassifica quando ainda não há veredito de mérito: item sem situação
            # (anterior à classificação) ou parado em trâmite, que pode ter recebido
            # a resposta de verdade desde a última passagem. Com --forcar reclassifica
            # tudo — é o único jeito de preencher `Data da resposta de mérito` nos
            # itens que o backfill do Drive marcou como respondidos (a data de
            # recebimento só existe na página da Câmara).
            classificar_tudo = args.forcar or sit_atual != cls.RESPONDIDO

            aba, valores, pasta_url, resposta_nova = processar_item(
                detalhes, drive, pasta_raiz, args.dry_run, sep, classificar_tudo)

            # Item já respondido de mérito: só registra de novo se chegou RESPOSTA
            # nova no Drive (sinal robusto, imune ao reformato de data da planilha).
            if (ja_respondido and sit_atual == cls.RESPONDIDO and not resposta_nova
                    and not args.forcar and not cods_alvo):
                continue

            rotulo = f"{detalhes['tipo']} {detalhes['numero']} (cod={item['cod']}) → {aba}"
            acao = ("resposta nova" if ja_respondido
                    else "atualiza" if existente else "nova linha")
            print(f"Processando ({acao}): {rotulo}", file=sys.stderr)

            if args.dry_run:
                print(json.dumps({"aba": aba, "acao": acao, **valores},
                                 ensure_ascii=False, indent=2))
            else:
                if existente:
                    atualizar_resposta(sheets, sheet_id, aba, info, existente["linha"],
                                       valores["Resposta"], valores["Data da resposta"])
                    atualizar_classificacao(sheets, sheet_id, aba, info,
                                            existente["linha"], valores)
                    existente["resp"] = True
                    existente["sit"] = valores.get(COL_SITUACAO, sit_atual)
                else:
                    anexar_linha(sheets, sheet_id, aba, valores)
                    info["mapa"][num] = {
                        "linha": -1, "resp": True,
                        "sit": valores.get(COL_SITUACAO, ""),
                    }
                log_entradas.append({
                    "Data processamento": hoje,
                    "Tipo": detalhes["tipo"],
                    "Número": detalhes["numero"],
                    "Assunto": detalhes["ementa"],
                    "Data da resposta": detalhes["dataResposta"],
                    "Situação": cls.ROTULOS.get(valores.get(COL_SITUACAO, ""), "—"),
                    "Link": _hyperlink(pasta_url, "Abrir", sep),
                    "LinkUrl": pasta_url,
                })
            processados += 1
        except Exception as e:
            falhas += 1
            print(f"  ERRO no cod={item['cod']}: {e} — pulando.", file=sys.stderr)
            continue

    print(f"Concluído: {processados} itens processados, {falhas} falha(s).",
          file=sys.stderr)

    if not args.dry_run and log_entradas:
        # Log e e-mail são passos secundários: o trabalho útil (Drive + planilha)
        # já concluiu acima. Uma falha transitória aqui não deve marcar a run
        # inteira como falha nem impedir o passo seguinte.
        if not args.sem_log:
            try:
                registrar_log(sheets, sheet_id, log_entradas)
                print(f"Log diário: {len(log_entradas)} linha(s) registrada(s).", file=sys.stderr)
            except Exception as e:
                print(f"  AVISO: falha ao registrar log diário: {e} — seguindo.", file=sys.stderr)
        if args.email:
            try:
                enviar_email(log_entradas, hoje)
            except Exception as e:
                print(f"  AVISO: falha ao enviar e-mail resumo: {e} — seguindo.", file=sys.stderr)


if __name__ == "__main__":
    main()
