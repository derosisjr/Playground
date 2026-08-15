#!/usr/bin/env python3
"""
Coleta da pauta — Ordem do Dia da Câmara de Santos
==================================================

Scraping da pauta + download/extração dos PDFs anexos, extraído de `index.py`
(2026-08) para servir aos dois caminhos:

  - legado (`index.py`, via API): PDF escaneado vira base64 para a API ler por OCR;
  - rotina /schedule (`pauta_md.py`): com `dir_anexos`, o PDF escaneado é gravado
    em disco e o agente o lê direto com a ferramenta Read — sem custo de API.

Sem IA e sem envio de e-mail aqui: só rede, parsing e PDF.
"""

import base64
import os
import re
import sys
from urllib.parse import urljoin

import requests
import fitz  # PyMuPDF
from bs4 import BeautifulSoup

BASE_URL = "https://administrativo.camarasantos.sp.gov.br"
IFRAME_URL = f"{BASE_URL}/dispositivo/ideCustom/legislativo/ordem_dia_eletronica/publico/"
LISTAGEM_URL = f"{IFRAME_URL}listagem.php?codigo="
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OrdemDoDiaBot/1.0)"}


# ── PDF ───────────────────────────────────────────────────────────────────────
def baixar_pdf(url: str) -> bytes | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"  Aviso: não foi possível baixar PDF {url}: {e}", file=sys.stderr)
        return None


def extrair_texto_pdf(dados: bytes) -> str | None:
    """Extrai o texto do PDF localmente (PyMuPDF), poupando tokens de imagem na API.

    Retorna None quando o PDF é escaneado (sem camada de texto útil) — nesse caso
    o chamador envia o PDF em base64 como bloco document, que a API sabe ler por OCR."""
    try:
        with fitz.open(stream=dados, filetype="pdf") as pdf:
            paginas = [pagina.get_text() for pagina in pdf]
    except Exception as e:
        print(f"  Aviso: falha ao extrair texto do PDF: {e}", file=sys.stderr)
        return None
    texto = "\n\n".join(paginas).replace("\x00", "")
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    # heurística de PDF escaneado: pouquíssimo texto por página
    if len(texto) < 200 * len(paginas):
        return None
    return texto


# ── Scraping ──────────────────────────────────────────────────────────────────
def fetch_html(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.content


def get_sessao(sessao_id: str | None) -> dict:
    if sessao_id:
        return {"id": sessao_id, "nome": f"Sessão {sessao_id}"}
    html = fetch_html(IFRAME_URL)
    soup = BeautifulSoup(html, "html.parser")  # BeautifulSoup detecta charset do meta
    options = soup.select("#selSessao option")[1:]
    if not options:
        raise RuntimeError("Nenhuma sessão encontrada.")
    first = options[0]
    return {"id": first["value"], "nome": first.get_text(strip=True)}


def _text(tag) -> str:
    return tag.get_text(separator=" ", strip=True) if tag else ""


def _nome_arquivo(label: str, seq: int) -> str:
    """Nome de arquivo seguro para um anexo escaneado gravado em disco."""
    base = re.sub(r"[^\w\s-]", "", label, flags=re.U).strip()
    base = re.sub(r"[\s]+", "-", base)[:60] or "anexo"
    return f"{seq:02d}-{base}.pdf"


def get_documentos(sessao_id: str, dir_anexos: str | None = None) -> list[dict]:
    """Itens da pauta com anexos.

    Cada anexo vem como {"label", "texto"} (texto extraído local) ou, quando o PDF
    é escaneado: {"label", "data"} (base64, caminho legado da API) — a menos que
    `dir_anexos` seja informado, caso em que o PDF é gravado em disco e o anexo
    vem como {"label", "arquivo"} (caminho absoluto), para o agente ler direto."""
    page_url = f"{LISTAGEM_URL}{sessao_id}"
    html = fetch_html(page_url)
    soup = BeautifulSoup(html, "html.parser")
    if dir_anexos:
        os.makedirs(dir_anexos, exist_ok=True)
    documentos = []
    seq_escaneado = 0
    for doc in soup.select(".documento"):
        titulo = _text(doc.select_one(".titulo_documento a"))
        processo = _text(doc.select_one(".titulo_documento_processo a"))
        spans = [s.get_text(strip=True) for s in doc.select(".documento_corpo_esquerdo span")]
        tipo_discussao = spans[0] if spans else ""
        quorum = spans[1] if len(spans) > 1 else ""
        campos: dict[str, str] = {}
        for row in doc.select(".documento_corpo_direito tr"):
            th = row.find("th")
            if not th:
                continue
            chave = th.get_text(strip=True).rstrip(":")
            tds = row.find_all("td")
            if tds:
                valor = tds[0].get_text(separator=" ", strip=True)
                if valor:
                    campos[chave] = valor

        # baixa PDFs do rodapé; texto extraído local vai como texto (barato),
        # PDF escaneado vai como base64 (API/OCR) ou para disco (rotina, dir_anexos)
        pdfs: list[dict] = []
        for a in doc.select(".documento_rodape_anexo a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            pdf_url = urljoin(page_url, href)
            label = a.get_text(strip=True) or "Documento"
            print(f"  Baixando PDF: {label}...", file=sys.stderr)
            dados = baixar_pdf(pdf_url)
            if not dados:
                continue
            texto = extrair_texto_pdf(dados)
            if texto:
                print(f"    texto extraído ({len(texto)} chars)", file=sys.stderr)
                pdfs.append({"label": label, "texto": texto})
            elif dir_anexos:
                seq_escaneado += 1
                caminho = os.path.join(os.path.abspath(dir_anexos),
                                       _nome_arquivo(label, seq_escaneado))
                with open(caminho, "wb") as f:
                    f.write(dados)
                print(f"    escaneado → {caminho}", file=sys.stderr)
                pdfs.append({"label": label, "arquivo": caminho})
            else:
                print("    escaneado → base64", file=sys.stderr)
                data = base64.standard_b64encode(dados).decode("utf-8")
                pdfs.append({"label": label, "data": data})

        if not titulo:
            continue
        documentos.append({
            "titulo": titulo,
            "processo": processo,
            "tipoDiscussao": tipo_discussao,
            "quorum": quorum,
            "autor": campos.get("Autor", ""),
            "ementa": campos.get("Ementa", ""),
            "historico": campos.get("Histórico", ""),
            "discussao": campos.get("Discussão", ""),
            "pdfs": pdfs,
        })
    return documentos
