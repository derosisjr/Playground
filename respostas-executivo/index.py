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
    python respostas-executivo/index.py --planejar      # lê tudo (só leitura) e mostra o plano
    python respostas-executivo/index.py --limite 3      # processa no máx N itens novos

Gravação (out/2026): a varredura não grava célula a célula; acumula um plano e o aplica com
`planilha.aplicar` a cada LOTE_ITENS itens ou LOTE_SEG segundos — relendo a aba na hora, só
nas colunas do robô e sem sobrescrever o que a equipe escreveu. Códigos de saída: 0 ok;
1 busca vazia em todos os anos ou planilha ilegível; 2 item com erro, gravação, log ou e-mail
que falhou, ou varredura cortada pelo orçamento de tempo (--orcamento-min).
"""

import argparse
import io
import json
import os
import re
import smtplib
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz do repo: comum/
from comum.formato import sem_acento  # noqa: E402
from comum import http  # noqa: E402
import time
import unicodedata
from collections import Counter
from datetime import datetime
from typing import NamedTuple
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classificar as cls  # noqa: E402  (mesmo diretório; ver bloco sys.path acima)
import planilha  # noqa: E402
import precadastro  # noqa: E402
from planilha import numero_canonico  # noqa: E402

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
    "Origem",  # "resposta" ou "pré-cadastro" (R5, out/2026)
]

# O job tem 35 min de timeout: a varredura para aos ORCAMENTO_MIN para dar tempo de gravar,
# registrar o log, mandar o e-mail e exportar. Antes o timeout cortava tudo isso.
ORCAMENTO_MIN = 28
LOTE_ITENS = 50      # o plano é gravado a cada N itens…
LOTE_SEG = 8 * 60    # …ou a cada 8 min, o que vier antes (e sempre no fim)

# Marca na subpasta do pedido (appProperties: só o app vê, a equipe não): "pendente" desde que
# uma resposta é arquivada até ela sair no log e no e-mail. Execução que cai no meio deixa a
# marca, e a seguinte avisa — antes, o e-mail dessas respostas se perdia para sempre.
AVISO = "aviso"
AVISO_PENDENTE = "pendente"
AVISO_FEITO = "avisado"


# ── HTTP ──────────────────────────────────────────────────────────────────────
def _http_get(url: str, params: dict | None = None, timeout: int = 30,
              tentativas: int = 4) -> requests.Response:
    """GET com retry/backoff para tolerar timeouts transitórios do site."""
    return http.get(url, params, tentativas=tentativas, passo=4, timeout=timeout, headers=HEADERS)


def fetch_html(url: str) -> bytes:
    return _http_get(url, timeout=30).content


def _eh_pdf(dados: bytes | None) -> bool:
    return bool(dados) and b"%PDF" in dados[:1024]


def baixar_pdf_bytes(url: str) -> bytes | None:
    try:
        dados = _http_get(url, timeout=60).content
    except Exception as e:
        print(f"  Aviso: não foi possível baixar PDF {url}: {e}", file=sys.stderr)
        return None
    # Página de erro em HTML (ou arquivo truncado) não é PDF: subiria ao Drive como
    # RESPOSTA e nunca mais seria trocada, porque o nome já existiria na pasta.
    if not _eh_pdf(dados):
        print(f"  Aviso: {url} não devolveu um PDF — ignorado nesta passada.", file=sys.stderr)
        return None
    return dados


def _text(tag) -> str:
    return tag.get_text(separator=" ", strip=True) if tag else ""


def _sem_acento(s: str) -> str:
    return sem_acento(s, forma="NFKD", caixa="baixa").strip()


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


def aba_do_item(tipo: str) -> str | None:
    """Aba do pedido pelo tipo da página da Câmara. Só "Requerimento" e "Indicação":
    moção, convite, homenagem… voltam None. Antes tudo que não era indicação ia para
    "requerimentos" e para a pasta REQUERIMENTO_<nº> — a Moção 19/2026 foi gravada na
    pasta e na linha do Requerimento 19/2026 (a numeração é por tipo e subtipo)."""
    t = _sem_acento(tipo)
    if t == "indicacao":
        return ABA_INDICACOES
    if t == "requerimento":
        return ABA_REQUERIMENTOS
    return None


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


def buscar_subpasta(drive, pasta_raiz: str, nome: str) -> dict | None:
    """Subpasta `nome` ({id, appProperties}) ou None se não existe — só leitura."""
    nome_escapado = nome.replace("'", "\\'")
    q = (
        f"name = '{nome_escapado}' and '{pasta_raiz}' in parents "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    res = drive.files().list(
        q=q, fields="files(id, appProperties)", supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    arquivos = res.get("files", [])
    return arquivos[0] if arquivos else None


def obter_ou_criar_subpasta(drive, pasta_raiz: str, nome: str) -> dict:
    existente = buscar_subpasta(drive, pasta_raiz, nome)
    if existente:
        return existente
    meta = {
        "name": nome,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [pasta_raiz],
    }
    pasta = drive.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    return {"id": pasta["id"]}


def marcar_aviso(drive, pasta_id: str, estado: str) -> None:
    """Grava a marca de aviso (ver AVISO) na subpasta do pedido."""
    drive.files().update(fileId=pasta_id, body={"appProperties": {AVISO: estado}},
                         fields="id", supportsAllDrives=True).execute()


def listar_arquivos_pasta(drive, pasta_id: str) -> list[dict]:
    """Lista os arquivos (não-pasta) de uma pasta, com id/nome/link/criação."""
    arquivos: list[dict] = []
    token = None
    while True:
        res = drive.files().list(
            q=f"'{pasta_id}' in parents and trashed = false "
              "and mimeType != 'application/vnd.google-apps.folder'",
            fields="nextPageToken, files(id, name, webViewLink, createdTime, size, "
                   "capabilities/canDelete)",
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
                if extra.get("capabilities", {}).get("canDelete") is False:
                    continue  # cópia de outro dono: apagar dá 403 em toda execução
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


def baixar_drive(drive, file_id: str) -> bytes | None:
    """Cópia arquivada no Drive — reserva quando a Câmara não entrega o PDF de novo.
    None se não der para ler ou se o arquivo não for PDF."""
    from googleapiclient.http import MediaIoBaseDownload

    try:
        buf = io.BytesIO()
        # o baixador quer a requisição de verdade, não o embrulho de retentativa
        req = planilha.desembrulhar(drive.files().get_media(fileId=file_id, supportsAllDrives=True))
        baixador = MediaIoBaseDownload(buf, req)
        concluido = False
        while not concluido:
            _, concluido = baixador.next_chunk()
        dados = buf.getvalue()
    except Exception as e:
        print(f"  Aviso: não foi possível ler a cópia do Drive {file_id}: {e}", file=sys.stderr)
        return None
    return dados if _eh_pdf(dados) else None


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
    """Índice 0-based → letra(s) de coluna A1 (A…Z, AA, AB…)."""
    letras = ""
    idx += 1
    while idx:
        idx, resto = divmod(idx - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras


def _idx_header(cabecalhos: list[str], alvo: str) -> int:
    alvo = _sem_acento(alvo)
    for i, h in enumerate(cabecalhos):
        if _sem_acento(h) == alvo:
            return i
    return -1


def garantir_colunas(sheets, sheet_id: str, aba: str, colunas: list[str] | None = None) -> list[str]:
    """Garante que o cabeçalho da aba tenha as colunas que ESTA automação grava
    (as de classificação), acrescentando ao fim as que faltarem. Devolve o
    cabeçalho resultante.

    Só as automáticas: colunas manuais de ABAS que a planilha não tem (ou tem com
    outra grafia) não são criadas — em 12/10/2026 isto criou "Ordem", "Prazo" e
    "Data do Protocolo na PMS" vazias no fim da aba. `planilha.aplicar` já descarta
    valor sem coluna correspondente, então nada se perde.

    As colunas novas entram DEPOIS da última coluna com qualquer conteúdo, com ou sem
    título: coluna sem título com anotações é da equipe e não pode ser ocupada. Só as
    células novas do cabeçalho são gravadas (antes a linha 1 inteira era regravada)."""
    res = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{aba}'",
    ).execute()
    valores = res.get("values") or [[]]
    cab = valores[0] if valores else []
    faltantes = [c for c in (colunas or COLUNAS_CLASSIFICACAO) if _idx_header(cab, c) < 0]
    if not faltantes:
        return cab
    inicio = max(len(linha) for linha in valores)  # 1ª coluna vazia em todas as linhas
    _garantir_largura(sheets, sheet_id, aba, inicio + len(faltantes))
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{aba}'!{_col_letra(inicio)}1",
        valueInputOption="RAW",
        body={"values": [faltantes]},
    ).execute()
    print(f"  Aba '{aba}': coluna(s) criada(s) — {', '.join(faltantes)}.", file=sys.stderr)
    return cab + [""] * (inicio - len(cab)) + faltantes


def _garantir_largura(sheets, sheet_id: str, aba: str, colunas: int) -> None:
    """Acrescenta colunas vazias no fim da grade se ela não comporta `colunas`."""
    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties(sheetId,title,gridProperties.columnCount)",
    ).execute()
    for s in meta.get("sheets", []):
        p = s.get("properties", {})
        if p.get("title") == aba:
            atual = p.get("gridProperties", {}).get("columnCount", 0)
            if atual < colunas:
                sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
                    {"appendDimension": {"sheetId": p["sheetId"], "dimension": "COLUMNS",
                                         "length": colunas - atual}}]}).execute()
            return


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


MIN_LINHAS = 100  # as abas reais têm 600+ linhas: menos que isso é leitura suspeita


def carregar_planilha(sheets, sheet_id: str, min_linhas: int = MIN_LINHAS) -> dict[str, dict]:
    """Lê cada aba e devolve, por aba, os índices de coluna e um mapa
    número canônico→{linha, resp, sit} (resp = se a coluna Resposta já está preenchida).

    Aborta (RuntimeError) se não conseguir ler uma aba, se ela vier quase vazia ou sem a
    coluna do número: seguir com o mapa vazio transformava todo item já respondido em
    "linha nova" — em 20/08/2026 isso criou 321 linhas repetidas em indicações.

    Número repetido na aba (os pares de 20/08): vale a ÚLTIMA linha, a que o robô já mantém
    atualizada; a da equipe fica intocada até a mescla."""
    indice: dict[str, dict] = {}
    for aba in ABAS:
        info = {"col_resp": -1, "col_situacao": -1, "mapa": {}, "repetidos": 0}
        indice[aba] = info
        try:
            res = sheets.spreadsheets().values().get(
                spreadsheetId=sheet_id, range=f"'{aba}'",
            ).execute()
        except Exception as e:
            raise RuntimeError(f"não consegui ler a aba '{aba}' ({e}) — nada foi gravado") from e
        valores = res.get("values", [])
        if len(valores) - 1 < min_linhas:
            raise RuntimeError(f"aba '{aba}' veio com {max(0, len(valores) - 1)} linha(s) — "
                               "leitura suspeita; nada foi gravado")
        cab = valores[0]
        idx_num = _idx_coluna_numero(cab)
        info["col_resp"] = _idx_header(cab, "Resposta")
        info["col_situacao"] = _idx_header(cab, COL_SITUACAO)
        col_sit_camara = _idx_header(cab, precadastro.COL_SIT_CAMARA)
        col_assunto = _idx_header(cab, "Assunto")
        if idx_num < 0:
            raise RuntimeError(f"aba '{aba}' sem a coluna do número no cabeçalho — nada foi gravado")

        def celula(linha: list, col: int) -> str:
            return linha[col].strip() if 0 <= col < len(linha) else ""

        for n, linha in enumerate(valores[1:], start=2):  # nº da linha (1-based)
            num = numero_canonico(celula(linha, idx_num))
            if not num:
                continue
            if num in info["mapa"]:
                info["repetidos"] += 1
            info["mapa"][num] = {
                "linha": n,
                "resp": celula(linha, info["col_resp"]) != "",
                "sit": celula(linha, info["col_situacao"]),
                "sit_camara": celula(linha, col_sit_camara),
                "assunto": celula(linha, col_assunto),
            }
        if info["repetidos"]:
            print(f"  Aviso: aba '{aba}' com {info['repetidos']} linha(s) de número repetido "
                  "(vale a última; a mescla é à parte).", file=sys.stderr)
    return indice


def _hyperlink(url: str, texto: str, sep: str) -> str:
    return f'=HYPERLINK("{url}"{sep}"{texto}")'


# ── Log diário ────────────────────────────────────────────────────────────────
def _executar(req, *, tentativas: int = 4, espera: float = 3.0):
    """Executa `req.execute()` com retry em erros transitórios de rede/SSL e nas
    respostas 429/5xx da API.

    A API do Google às vezes derruba a conexão (ssl.SSLEOFError, timeouts),
    o que abortava a run inteira mesmo após o trabalho útil ter concluído.
    Desde out/2026 vale para TODA chamada do robô (`planilha.com_retentativa`).
    """
    import socket
    import ssl
    for i in range(tentativas):
        try:
            return req.execute()
        except Exception as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            transitorio = (isinstance(e, (ssl.SSLError, socket.error, ConnectionError, TimeoutError))
                           or status in (429, 500, 502, 503, 504))
            if not transitorio or i == tentativas - 1:
                raise
            print(f"  rede instável ({type(e).__name__}: {e}); "
                  f"retry {i + 2}/{tentativas} em {espera:.0f}s...", file=sys.stderr)
            time.sleep(espera)
            espera *= 2


def garantir_aba_log(sheets, sheet_id: str) -> None:
    """Cria a aba de log se não existir; se existir, completa o cabeçalho com as
    colunas que faltarem (as linhas são montadas pela ordem de LOG_COLUNAS).
    O cliente já vem com retentativa (`planilha.com_retentativa` no main)."""
    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties.title").execute()
    titulos = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if LOG_ABA in titulos:
        res = sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{LOG_ABA}'!1:1").execute()
        cab = (res.get("values") or [[]])[0]
        if any(_idx_header(cab, c) < 0 for c in LOG_COLUNAS):
            sheets.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f"'{LOG_ABA}'!A1",
                valueInputOption="RAW", body={"values": [LOG_COLUNAS]}).execute()
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
def montar_email_html(entradas: list[dict], data: str, novos: list[dict] = ()) -> str:
    """Respostas que chegaram (`entradas`) e, desde o pré-cadastro (R5), os pedidos que
    entraram na planilha (`novos`) — a equipe completa Secretaria e Bairro."""
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
    if novos:
        resumo += f"; {len(novos)} pedido(s) novo(s) na planilha"
    td = "<td style='padding:6px 10px;border-bottom:1px solid #eee'>"
    linhas_novos = "".join(
        f"<tr>{td}{_esc(e['Tipo'])}</td>{td}{_esc(e['Número'])}</td>{td}{_esc(e['Assunto'])}</td>"
        f"{td}{_esc(e.get('Situação') or '—')}</td></tr>" for e in novos)
    secao_novos = f"""
  <h3 style="margin:24px 0 8px;color:#07111F">{len(novos)} pedido(s) novo(s) — completar Secretaria e Bairro</h3>
  <table style="border-collapse:collapse;width:100%;font-size:14px">
    <thead><tr style="background:#07111F;color:#fff">
      <th style="padding:8px 10px;text-align:left">Tipo</th>
      <th style="padding:8px 10px;text-align:left">Número</th>
      <th style="padding:8px 10px;text-align:left">Assunto</th>
      <th style="padding:8px 10px;text-align:left">Situação na Câmara</th>
    </tr></thead>
    <tbody>{linhas_novos}</tbody>
  </table>""" if novos else ""
    tabela = f"""
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
  </table>""" if entradas else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0A1628">
<div style="max-width:760px;margin:0 auto">
  <div style="border-top:3px solid #C9A84C;padding:16px 0">
    <h2 style="margin:0;color:#07111F">Respostas do Executivo</h2>
    <p style="color:#555;margin:4px 0 0">{resumo} — {data}</p>
  </div>{tabela}{secao_novos}
  <p style="color:#888;font-size:12px;margin-top:16px">
    Gerado automaticamente pela rotina Respostas do Executivo — Câmara de Santos.
  </p>
</div></body></html>"""


def enviar_email(entradas: list[dict], data: str, novos: list[dict] = ()) -> None:
    user = os.environ.get("GMAIL_USER")
    senha = os.environ.get("GMAIL_APP_PASSWORD")
    # destinatário dedicado (não compartilha com o ordem-do-dia); fallback p/ GMAIL_TO
    para = os.environ.get("RESPOSTAS_EMAIL_TO") or os.environ.get("GMAIL_TO")
    if not all([user, senha, para]):
        # com --email pedido, e-mail não enviado é falha (sai 2 e a marca de aviso fica)
        raise EnvironmentError("GMAIL_USER/GMAIL_APP_PASSWORD/RESPOSTAS_EMAIL_TO não definidos; "
                               "e-mail não enviado.")
    destinatarios = [d.strip() for d in para.split(",") if d.strip()]
    msg = MIMEMultipart("alternative")
    extra = f" e {len(novos)} pedido(s) novo(s)" if novos else ""
    msg["Subject"] = f"Respostas do Executivo — {len(entradas)} nova(s){extra} em {data}"
    msg["From"] = f"Respostas do Executivo <{user}>"
    msg["To"] = ", ".join(destinatarios)
    resumo = "\n".join(
        [f"- {e['Tipo']} {e['Número']}: {e['Assunto']} (resposta {e['Data da resposta']})"
         for e in entradas]
        + [f"- novo: {e['Tipo']} {e['Número']}: {e['Assunto']} — completar Secretaria e Bairro"
           for e in novos]
    )
    msg.attach(MIMEText(resumo, "plain", "utf-8"))
    msg.attach(MIMEText(montar_email_html(entradas, data, novos), "html", "utf-8"))
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(user, senha)
        server.sendmail(user, destinatarios, msg.as_string())
    print(f"E-mail enviado para {', '.join(destinatarios)}.", file=sys.stderr)


# ── Processamento ─────────────────────────────────────────────────────────────
class Processado(NamedTuple):
    aba: str
    valores: dict
    pasta_url: str
    resposta_nova: bool          # PDF de resposta arquivado agora (na simulação: subiria agora)
    sem_pdf: bool                # nenhum PDF de resposta arquivado: nada vai à planilha
    pasta_id: str | None = None
    aviso_pendente: bool = False  # a pasta tem a marca AVISO_PENDENTE


def processar_item(item: dict, drive, pasta_raiz: str, dry_run: bool,
                   sep: str = ",", classificar_tudo: bool = True,
                   simular: bool = False) -> Processado:
    """Baixa PDFs que ainda não estão arquivados, sobe ao Drive e devolve um `Processado`.

    `resposta_nova` indica se algum PDF de RESPOSTA foi arquivado agora (sinal robusto p/
    saber se chegou novidade, independente do formato de data na planilha); `sem_pdf`, que
    nenhum PDF de resposta está arquivado (o chamador não grava Resposta nem Data e conta
    como falha). Antes de subir a 1ª resposta nova, a pasta recebe a marca AVISO_PENDENTE.

    `classificar_tudo` faz rebaixar também os PDFs já arquivados, para classificá-los.
    Só vale a pena quando a planilha ainda não tem veredito para o item — do
    contrário seriam centenas de downloads por dia sem novidade nenhuma.

    `simular` (o --planejar) lê Drive e Câmara como de verdade, mas não cria pasta, não sobe
    arquivo, não apaga cópia repetida nem marca a pasta."""
    aba = aba_do_item(item["tipo"])
    numero = item["numero"] or item["cod"]
    categoria = "REQUERIMENTO" if aba == ABA_REQUERIMENTOS else "INDICACAO"
    nome_pasta = _slug(f"{categoria}_{numero}")

    links_resposta = []
    pasta_id = None
    pasta_url = ""
    existentes: dict[str, str] = {}
    ids_existentes: dict[str, str] = {}
    resposta_nova = False
    aviso_pendente = False
    if not dry_run:
        pasta = (buscar_subpasta if simular else obter_ou_criar_subpasta)(drive, pasta_raiz, nome_pasta)
        if pasta:  # na simulação, pasta que ainda não existe fica None
            pasta_id = pasta["id"]
            pasta_url = f"https://drive.google.com/drive/folders/{pasta_id}"
            aviso_pendente = (pasta.get("appProperties") or {}).get(AVISO) == AVISO_PENDENTE
            # Lista a pasta uma vez: limpa duplicatas antigas e monta o mapa nome→link.
            # Permite pular o download de PDFs já arquivados e detectar respostas novas.
            arquivos = listar_arquivos_pasta(drive, pasta_id)
            if not simular:
                arquivos = limpar_duplicatas(drive, arquivos)
            existentes = {a["name"]: a.get("webViewLink", "") for a in arquivos}
            ids_existentes = {a["name"]: a["id"] for a in arquivos if a.get("id")}

    # Pedido (arquivado no Drive; a planilha não tem coluna própria p/ ele)
    if item["pedidoPdf"]:
        nome_pedido = _slug(f"PEDIDO {numero} {item['pedidoPdf']['nome']}")
        if not dry_run and not simular and nome_pedido not in existentes:
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
        if arquivado:
            links_resposta.append(existentes[nome_resp])
            if not classificar_tudo:
                continue
            # O PDF já arquivado é rebaixado só para classificar. Se a Câmara não o
            # entrega, vale a cópia do Drive; sem nenhuma das duas, o item fica sem
            # veredito NESTA passada. Antes isso virava INDETERMINADO, que conta como
            # mérito: um "respondido" falso que nunca mais era reclassificado.
            dados = baixar_pdf_bytes(pdf["url"])
            if dados is None and nome_resp in ids_existentes:
                dados = baixar_drive(drive, ids_existentes[nome_resp])
            if dados is None:
                continue
        else:
            dados = baixar_pdf_bytes(pdf["url"])
            if dados is None:
                continue
            if dry_run:
                links_resposta.append(pdf["url"])
            elif simular:
                links_resposta.append(pdf["url"])
                resposta_nova = True  # subiria agora
            else:
                if not aviso_pendente:
                    # marca ANTES de subir: se a execução cair entre o upload e o aviso,
                    # a próxima vê a marca e avisa
                    marcar_aviso(drive, pasta_id, AVISO_PENDENTE)
                    aviso_pendente = True
                links_resposta.append(
                    subir_pdf(drive, pasta_id, nome_resp, dados, existentes))
                resposta_nova = True
        # PDF lido mas sem camada de texto continua INDETERMINADO = mérito (falha
        # segura: nunca rebaixar um item por não conseguir ler o arquivo).
        classe = cls.classificar(cls.texto_pdf(dados))
        classes.append(classe)
        if classe in (cls.MERITO, cls.INDETERMINADO) and pdf.get("data"):
            datas_merito.append(pdf["data"])

    # Coluna "Resposta": hyperlink clicável para a subpasta com os PDFs
    if dry_run:
        resposta_cell = "\n".join(links_resposta)
        resposta_nova = True  # sem Drive não dá pra comparar; trata como novidade
    else:
        resposta_cell = _hyperlink(pasta_url or "(pasta a criar)", "Resposta", sep)

    col_numero = "Número" if aba == ABA_INDICACOES else "Nùmero"
    valores = {
        "Assunto": item["ementa"],
        precadastro.COL_EMENTA: item["ementa"],  # só entra se a linha for nova
        "Data da Sessão": item["dataPropositura"],
        col_numero: numero,
        "Resposta": resposta_cell,
        "Data da resposta": item["dataResposta"],
    }
    # Só grava a situação se TODOS os PDFs foram classificados nesta passagem;
    # caso contrário sobrescreveríamos um veredito bom com um parcial.
    if classes and len(classes) == len(item["respostasPdf"]):
        valores[COL_SITUACAO] = cls.situacao(classes)
        valores[COL_DATA_MERITO] = _data_mais_antiga(datas_merito)
    sem_pdf = not links_resposta
    return Processado(aba, valores, pasta_url, resposta_nova, sem_pdf, pasta_id, aviso_pendente)


def anos_do_mandato() -> list[str]:
    """Do ano corrente até ANO_INICIAL (as respostas ficam no ano de envio do pedido)."""
    return [str(a) for a in range(datetime.now().year, ANO_INICIAL - 1, -1)]


def executar_precadastro(sheets, sheet_id: str, indice: dict, anos: list[str], gravar: bool,
                         hoje: str) -> tuple[list[dict], "planilha.Relatorio"]:
    """Pré-cadastro (precadastro.py), antes da busca de respostas: cria as linhas dos pedidos
    protocolados que ainda não estão na planilha e acerta o espelho "Situação na Câmara".
    Com `gravar` desligado só conta. Devolve as entradas do log/e-mail e o relatório."""
    conhecidos = {aba: {n: x.get("sit_camara", "") for n, x in info["mapa"].items()}
                  for aba, info in indice.items()}
    # segunda-feira, ou a 1ª vez (espelho vazio em tudo): varredura completa
    completo = datetime.now().weekday() == 0 or not any(v for d in conhecidos.values() for v in d.values())
    itens, _ = precadastro.coletar(anos, conhecidos, completo,
                                   {"Requerimento": ABA_REQUERIMENTOS, "Indicação": ABA_INDICACOES})
    novas, espelho = precadastro.planejar(itens, conhecidos)
    rel = planilha.aplicar(sheets, sheet_id, novas + espelho, gravar=gravar)
    print(f"Pré-cadastro{'' if gravar else ' (desligado: só contado)'}: {len(itens)} pedido(s) "
          f"vistos na Câmara ({'completa' if completo else 'só os mais novos'}); "
          f"{len(rel.novas)} linha(s) nova(s), \"{precadastro.COL_SIT_CAMARA}\" acertada em "
          f"{len(rel.escritas)}.", file=sys.stderr)
    if not gravar:
        return [], rel
    valores = {(n.aba, n.numero): n.valores for n in novas}
    entradas = []
    for aba, num, linha in rel.novas:
        v = valores[(aba, num)]
        # a busca de respostas vem depois: o pedido novo já tem linha
        indice[aba]["mapa"][num] = {"linha": linha, "resp": False, "sit": "",
                                    "sit_camara": v.get(precadastro.COL_SIT_CAMARA, ""),
                                    "assunto": v.get("Assunto", "")}
        entradas.append({
            "Data processamento": hoje,
            "Tipo": "Requerimento" if aba == ABA_REQUERIMENTOS else "Indicação",
            "Número": num, "Assunto": v.get("Assunto", ""), "Data da resposta": "",
            "Link": "", "Situação": v.get(precadastro.COL_SIT_CAMARA, ""), "Origem": "pré-cadastro",
        })
    return entradas, rel


def _resumo_actions(titulo: str, linhas: list[tuple[str, object]], alertas: list[str]) -> None:
    """Contagens no resumo do job do Actions. O repo é público: só números e rótulos fixos,
    nunca texto da planilha nem mensagem de erro (que pode trazer o ID dela)."""
    caminho = os.environ.get("GITHUB_STEP_SUMMARY")
    if not caminho:
        return
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(f"### {titulo}\n\n| | |\n|---|---:|\n")
        f.writelines(f"| {rotulo} | {valor} |\n" for rotulo, valor in linhas)
        f.writelines(f"\n> ⚠️ {a}\n" for a in alertas)


def main() -> int:
    inicio = time.monotonic()
    parser = argparse.ArgumentParser(description="Respostas do Executivo — Câmara de Santos")
    parser.add_argument("--ano", default="",
                        help=f"Ano(s) da busca, separados por vírgula (ex.: 2025,2026). "
                             f"Padrão: de {ANO_INICIAL} até o ano corrente (respostas ficam "
                             f"no ano de envio da propositura, não no ano da resposta).")
    parser.add_argument("--autor", default=AUTOR_PADRAO,
                        help=f"Código do autor. Padrão: {AUTOR_PADRAO}.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Não escreve no Drive nem na planilha.")
    parser.add_argument("--planejar", action="store_true",
                        help="Lê Câmara, Drive e planilha em modo somente leitura e mostra só as "
                             "contagens do que seria gravado. Nada é gravado nem enviado.")
    parser.add_argument("--limite", type=int, default=0,
                        help="Processa no máximo N itens com novidade (0 = todos).")
    parser.add_argument("--orcamento-min", type=float, default=ORCAMENTO_MIN,
                        help=f"Encerra a varredura após N minutos e grava, registra o log e manda "
                             f"o e-mail antes do timeout do job. Padrão: {ORCAMENTO_MIN}.")
    parser.add_argument("--forcar", action="store_true",
                        help="Reclassifica todos os PDFs e avisa todos os itens, com ou sem "
                             "mudança (não sobrescreve o que já está preenchido na planilha).")
    parser.add_argument("--cods", default="",
                        help="Processa apenas estes cods (lista separada por vírgula) e os "
                             "avisa mesmo sem mudança — útil p/ reenviar um e-mail que se "
                             "perdeu, sem reprocessar a base inteira.")
    parser.add_argument("--email", action="store_true",
                        help="Envia e-mail resumo das respostas processadas (se houver).")
    parser.add_argument("--sem-log", action="store_true",
                        help="Não registra na aba Log diário (ex.: carga retroativa).")
    args = parser.parse_args()
    if args.planejar and args.dry_run:
        parser.error("--planejar e --dry-run não combinam (o --dry-run nem abre o Google)")

    if args.ano.strip():
        anos = [a.strip() for a in args.ano.split(",") if a.strip()]
    else:
        anos = anos_do_mandato()

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
    if not itens:
        # a busca nunca volta vazia de verdade (há respostas desde 2025): é o layout que mudou
        print("ERRO: a busca não devolveu nenhum item em nenhum ano — o layout da Câmara mudou?",
              file=sys.stderr)
        _resumo_actions("Respostas do Executivo", [("Itens na busca", 0)],
                        ["Busca vazia em todos os anos: o layout da Câmara pode ter mudado."])
        return 1

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

    # pré-cadastro (R5): ligado pela variável do repositório PRECADASTRO_ATIVO=true;
    # desligado, só conta o que faria
    precadastro_ativo = os.environ.get("PRECADASTRO_ATIVO", "").strip().lower() == "true"
    if not args.dry_run:
        if not sheet_id or not pasta_raiz:
            raise EnvironmentError("Defina SHEET_ID e DRIVE_FOLDER_ID.")
        drive, sheets = _google_services()
        # Retentativa (rede, 429, 5xx) em TODA chamada ao Drive e ao Sheets. No --planejar, a
        # trava de somente leitura por cima: qualquer gravação levanta EscritaBloqueada.
        drive = planilha.com_retentativa(drive, _executar)
        sheets = planilha.com_retentativa(sheets, _executar)
        if args.planejar:
            drive, sheets = planilha.somente_leitura(drive), planilha.somente_leitura(sheets)
        else:
            # Sem as colunas de classificação a situação nunca era gravada: todo item
            # parecia "sem veredito", era rebaixado e reclassificado todo dia e saía
            # no log e no e-mail como resposta nova (~576 por execução, out/2026).
            for aba in ABAS:
                garantir_colunas(sheets, sheet_id, aba, COLUNAS_CLASSIFICACAO
                                 + (precadastro.COLUNAS_NOVAS if precadastro_ativo else []))
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
    # --forcar e --cods servem para testar/reenviar o e-mail: avisam mesmo sem mudança
    avisar_sempre = args.forcar or bool(cods_alvo)
    cont: Counter = Counter()
    plano: list = []                     # escritas acumuladas desde a última gravação
    candidatos: dict[tuple, dict] = {}   # (aba, nº) do lote em curso → entrada do log/e-mail
    avisos: list[dict] = []              # entradas confirmadas depois da gravação
    rel_total = planilha.Relatorio()
    ultimo_lote = time.monotonic()

    # Pré-cadastro (R5): os pedidos protocolados entram na planilha ANTES da busca de
    # respostas — a resposta de um pedido novo já encontra a linha dele
    novos_pre: list[dict] = []
    rel_pre = planilha.Relatorio()
    if not args.dry_run and not cods_alvo:
        try:
            novos_pre, rel_pre = executar_precadastro(
                sheets, sheet_id, indice, anos, precadastro_ativo and not args.planejar, hoje)
        except Exception as e:
            cont["pré-cadastro com erro"] += 1
            print(f"  ERRO no pré-cadastro: {e} — segue a busca de respostas.", file=sys.stderr)

    def gravar_lote() -> None:
        """Aplica o plano acumulado (relendo a planilha agora) e confirma os avisos do lote:
        aviso é mudança real gravada ou resposta arquivada que ainda não foi avisada."""
        nonlocal plano, ultimo_lote
        lote, plano = plano, []
        do_lote = dict(candidatos)
        candidatos.clear()
        ultimo_lote = time.monotonic()
        if not lote:
            return
        try:
            rel = planilha.aplicar(sheets, sheet_id, lote, gravar=not args.planejar)
        except Exception as e:
            cont["lotes com erro"] += 1
            print(f"  ERRO ao gravar {len(lote)} item(ns) na planilha: {e} — nada desse lote "
                  "foi gravado; a próxima execução refaz.", file=sys.stderr)
            return
        rel_total.somar(rel)
        mudou = set(rel.escritas) | {(a, n) for a, n, _ in rel.novas}
        sem_linha = set(rel.sem_linha) | set(rel.ja_existia)
        for chave, c in do_lote.items():
            if chave in sem_linha:
                continue  # a linha sumiu (ou surgiu) no meio: a marca fica e a próxima resolve
            if (chave in mudou and c["_avisar"]) or c["_novidade"] or avisar_sempre:
                avisos.append(c)

    interrompidos = 0
    try:
        for pos, item in enumerate(itens):
            if args.limite and cont["com novidade"] >= args.limite:
                break
            if time.monotonic() - inicio > args.orcamento_min * 60:
                interrompidos = len(itens) - pos
                print(f"  ORÇAMENTO de {args.orcamento_min:g} min esgotado: {interrompidos} "
                      "item(ns) ficam para a próxima execução.", file=sys.stderr)
                break
            try:
                detalhes = detalhar_item(item["cod"])
                detalhes["dataResposta"] = detalhes["dataResposta"] or item["recebimentoBusca"]
                if not detalhes["tipo"]:
                    raise RuntimeError("página sem tipo no título (layout da Câmara mudou?)")
                aba = aba_do_item(detalhes["tipo"])
                if aba is None:
                    cont["fora das abas"] += 1
                    print(f"  Fora das abas: {detalhes['tipo']} {detalhes['numero']} "
                          f"(cod={item['cod']}) — só requerimentos e indicações.", file=sys.stderr)
                    continue
                num = numero_canonico(detalhes["numero"])
                if not num:
                    raise RuntimeError(f"número fora do padrão: {detalhes['numero']!r}")
                info = indice.get(aba, {"mapa": {}})
                existente = info["mapa"].get(num)
                ja_respondido = bool(existente and existente.get("resp"))
                sit_atual = (existente or {}).get("sit", "")
                # Reclassifica quando ainda não há veredito de mérito: item sem situação
                # (anterior à classificação) ou parado em trâmite, que pode ter recebido
                # a resposta de verdade desde a última passagem. Com --forcar reclassifica
                # tudo — mas o veredito só entra em célula vazia (ou com documento novo).
                classificar_tudo = args.forcar or sit_atual != cls.RESPONDIDO

                r = processar_item(detalhes, drive, pasta_raiz, args.dry_run, sep,
                                   classificar_tudo, simular=args.planejar)
                if r.sem_pdf:
                    # sem nenhum PDF de resposta arquivado, a pasta não prova resposta:
                    # nada vai à planilha (tenta de novo na próxima execução)
                    raise RuntimeError("nenhum PDF de resposta arquivado — nada gravado")
                cont["vistos"] += 1

                # Novidade: resposta arquivada agora ou numa execução que caiu antes de
                # avisar (marca na pasta). Só ela autoriza atualizar as colunas de resposta
                # já preenchidas; sem novidade, o robô só preenche célula vazia — e em
                # silêncio, se o item já tinha resposta.
                novidade = r.resposta_nova or r.aviso_pendente
                avisar = novidade or not ja_respondido or avisar_sempre
                acao = ("nova linha" if not existente else "resposta nova" if novidade
                        else "atualiza" if avisar else "confere")
                if avisar:
                    cont["com novidade"] += 1
                    print(f"Processando ({acao}): {detalhes['tipo']} {detalhes['numero']} "
                          f"(cod={item['cod']}) → {aba}", file=sys.stderr)
                if args.dry_run:
                    print(json.dumps({"aba": aba, "acao": acao, **r.valores},
                                     ensure_ascii=False, indent=2))
                    continue
                if existente:
                    plano.append(planilha.Escrita(
                        aba, num, {c: v for c, v in r.valores.items() if c in planilha.COLUNAS_RESPOSTA},
                        resposta_nova=novidade))
                else:
                    plano.append(planilha.NovaLinha(aba, num, r.valores))
                candidatos[(aba, num)] = {
                    "Data processamento": hoje,
                    "Tipo": detalhes["tipo"],
                    "Número": detalhes["numero"],
                    "Assunto": detalhes["ementa"],
                    "Data da resposta": detalhes["dataResposta"],
                    # sem reclassificação nesta passada (já respondido), vale a da planilha
                    "Situação": cls.ROTULOS.get(r.valores.get(COL_SITUACAO) or sit_atual, "—"),
                    "Link": _hyperlink(r.pasta_url, "Abrir", sep),
                    "LinkUrl": r.pasta_url,
                    "Origem": "resposta",
                    "_avisar": avisar,
                    "_novidade": novidade,
                    "_pasta_marcada": r.pasta_id if r.aviso_pendente else None,
                }
            except Exception as e:
                cont["com erro"] += 1
                print(f"  ERRO no cod={item['cod']}: {e} — pulando.", file=sys.stderr)
                continue
            if len(plano) >= LOTE_ITENS or time.monotonic() - ultimo_lote > LOTE_SEG:
                gravar_lote()
    finally:
        # também em erro inesperado ou Ctrl+C: o que já foi processado não se perde
        if not args.dry_run:
            gravar_lote()

    print(f"Concluído: {cont['vistos']} itens vistos, {cont['com novidade']} com novidade, "
          f"{cont['com erro']} falha(s), {cont['fora das abas']} fora das abas "
          "(moção, convite…).", file=sys.stderr)
    if not args.dry_run:
        verbo = "seriam gravadas" if args.planejar else "gravadas"
        print(f"Planilha: {rel_total.celulas} célula(s) {verbo} — {len(rel_total.novas)} linha(s) "
              f"nova(s), {len(rel_total.escritas)} linha(s) atualizada(s).", file=sys.stderr)
        por_coluna = Counter((a, c) for a, _, c in rel_total.divergencias)
        if por_coluna:
            print("Divergências (mantido o que está na planilha): " + "; ".join(
                f"{a}/{c}: {n}" for (a, c), n in sorted(por_coluna.items())), file=sys.stderr)
        for rotulo, lista in (("Linha sumiu antes da gravação", rel_total.sem_linha),
                              ("Linha já existia (criada no meio)", rel_total.ja_existia)):
            if lista:
                print(f"{rotulo}: " + ", ".join(f"{a} {n}" for a, n in lista[:20]), file=sys.stderr)

    falhas_aviso: list[str] = []
    if (avisos or novos_pre) and not args.dry_run and not args.planejar:
        if not args.sem_log:
            try:
                registrar_log(sheets, sheet_id, avisos + novos_pre)
                print(f"Log diário: {len(avisos) + len(novos_pre)} linha(s) registrada(s).", file=sys.stderr)
            except Exception as e:
                falhas_aviso.append("log diário")
                print(f"  ERRO ao registrar o log diário: {e}", file=sys.stderr)
        if args.email:
            try:
                enviar_email(avisos, hoje, novos_pre)
            except Exception as e:
                falhas_aviso.append("e-mail")
                print(f"  ERRO ao enviar o e-mail resumo: {e}", file=sys.stderr)
        if not falhas_aviso:
            # aviso dado: a marca sai. Se o log ou o e-mail falhou, ela fica e a próxima avisa.
            for a in avisos:
                if a["_pasta_marcada"]:
                    try:
                        marcar_aviso(drive, a["_pasta_marcada"], AVISO_FEITO)
                    except Exception as e:
                        falhas_aviso.append("marca de aviso")
                        print(f"  ERRO ao tirar a marca de aviso de {a['Número']}: {e}",
                              file=sys.stderr)

    alertas = []
    if cont["pré-cadastro com erro"]:
        alertas.append("O pré-cadastro falhou — ver o log do passo.")
    if cont["com erro"]:
        alertas.append(f"{cont['com erro']} item(ns) com erro — ver o log do passo.")
    if cont["lotes com erro"]:
        alertas.append(f"A gravação na planilha falhou em {cont['lotes com erro']} lote(s); "
                       "a próxima execução refaz.")
    if falhas_aviso:
        alertas.append(f"Falhou: {', '.join(dict.fromkeys(falhas_aviso))} — a marca de aviso fica "
                       "e a próxima execução avisa de novo.")
    if interrompidos:
        alertas.append(f"Orçamento de {args.orcamento_min:g} min esgotado: {interrompidos} "
                       "item(ns) não vistos nesta execução.")
    _resumo_actions(
        "Respostas do Executivo" + (" — plano (nada gravado)" if args.planejar else ""),
        [("Itens na busca", len(itens)), ("Itens vistos", cont["vistos"]),
         ("Fora das abas (moção, convite…)", cont["fora das abas"]),
         ("Com novidade", cont["com novidade"]),
         ("Células gravadas" if not args.planejar else "Células a gravar", rel_total.celulas),
         ("Linhas novas", len(rel_total.novas)), ("Linhas atualizadas", len(rel_total.escritas)),
         ("Divergências (mantido o valor da planilha)", len(rel_total.divergencias)),
         ("Linha sumiu ou surgiu no meio", len(rel_total.sem_linha) + len(rel_total.ja_existia)),
         ("Avisos (log e e-mail)", len(avisos)), ("Itens com erro", cont["com erro"]),
         ("Pré-cadastro: linhas novas" + ("" if precadastro_ativo else " (desligado: só contado)"),
          len(rel_pre.novas)),
         ("Situação na Câmara acertada", len(rel_pre.escritas)),
         ("Minutos", f"{(time.monotonic() - inicio) / 60:.1f}")],
        alertas)
    for a in alertas:
        print(f"ATENÇÃO: {a}", file=sys.stderr)
    return 2 if alertas else 0


if __name__ == "__main__":
    sys.exit(main())
