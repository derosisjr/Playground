#!/usr/bin/env python3
"""Listagem pública da Câmara por autor — requerimentos e indicações do mandato.

    busca_documento_pub/filtro.php?pesquisa_autor[ano]=AAAA&pesquisa_autor[vereador]=282
        &pesquisa_autor[tipo]=1|3&pesquisa_autor[subtipo]=&limite=<offset>

1 = Requerimento, 3 = Indicação. Páginas em ISO-8859-1, 20 blocos `table.table-bordered`
por página, número decrescente; offset além do fim devolve 0 blocos. É a mesma estrutura
que `proposituras/crawler.py` (`_parse_bloco`) lê para os projetos. **A numeração dos
requerimentos é por subtipo**: existem "Requerimento Nº 10/2025" e "Requerimento de
Homenagem Nº 10/2025" — o subtipo vai junto com o número.

Funções puras (`ler_listagem`) testadas com fixture em `fixtures/camara/`; a rede fica em
`listar_autor`.
"""

import os
import re
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz: comum/
from bs4 import BeautifulSoup  # noqa: E402

from planilha import numero_canonico  # noqa: E402

BASE_URL = "https://administrativo.camarasantos.sp.gov.br"
FILTRO_URL = f"{BASE_URL}/dispositivo/customizado_publico/legislativo/busca_documento_pub/filtro.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RespostasExecutivoBot/1.0)"}
TIPO_REQUERIMENTO = "1"
TIPO_INDICACAO = "3"
POR_PAGINA = 20


def _texto(tag) -> str:
    return tag.get_text(" ", strip=True) if tag else ""


def ler_listagem(html: bytes) -> list[dict]:
    """Blocos de uma página da listagem → dicts com cod, subtipo ("Requerimento",
    "Requerimento de Convite", "Indicação"…), numero (canônico), numero_original, processo,
    data, situacao, autor, local e ementa. Bloco sem link de detalhes é ignorado."""
    soup = BeautifulSoup(html, "html.parser", from_encoding="iso-8859-1")
    itens = []
    for tab in soup.select("table.table-bordered"):
        link = tab.select_one("a[href*='detalhes.php']")
        m = re.search(r"cod=(\d+)", link.get("href", "")) if link else None
        if not m:
            continue
        titulo = _texto(tab.select_one("thead strong"))
        mt = re.match(r"\s*(.+?)\s*-\s*N[ºo°]\s*([\d./-]+)", titulo)
        mp = re.search(r"Processo\s*N[ºo°]\s*([\d./-]+)", titulo)
        campos = {}
        for row in tab.select("tbody tr"):
            th = row.find("th")
            td = th.find_next_sibling("td") if th else None
            if th and td:
                chave = th.get_text(strip=True).rstrip(":")
                if chave and chave != "\xa0":
                    campos[chave] = td.get_text(" ", strip=True)
        ementa = ""
        span = tab.find("span", string=re.compile(r"Ementa", re.I))
        if span and span.find_parent("td"):
            ementa = re.sub(r"^\s*Ementa:\s*", "", span.find_parent("td").get_text(" ", strip=True)).strip()
        numero_original = campos.get("Número") or (mt.group(2) if mt else "")
        itens.append({
            "cod": m.group(1),
            "subtipo": mt.group(1).strip() if mt else "",
            "numero": numero_canonico(numero_original),
            "numero_original": numero_original,
            "processo": mp.group(1) if mp else "",
            "data": campos.get("Data", ""),
            "situacao": campos.get("Situação", ""),
            "autor": campos.get("Autor", ""),
            "local": campos.get("Local", ""),
            "ementa": ementa,
        })
    return itens


def listar_autor(ano: int | str, tipo: str, autor: str = "282", pausa: float = 0.4,
                 max_paginas: int = 200, parar=None) -> list[dict]:
    """Páginas da listagem de um ano/tipo do autor (GET com retentativa), da mais nova
    para a mais antiga. `parar(blocos_da_pagina)` → True encerra depois daquela página
    (a varredura diária do pré-cadastro para quando só encontra o que já conhece)."""
    from comum import http
    itens: list[dict] = []
    for pagina in range(max_paginas):
        params = {
            "pesquisa_autor[ano]": str(ano), "pesquisa_autor[vereador]": autor,
            "pesquisa_autor[tipo]": tipo, "pesquisa_autor[subtipo]": "",
            "limite": str(pagina * POR_PAGINA),
        }
        r = http.get(FILTRO_URL, params, tentativas=4, passo=4, timeout=30, headers=HEADERS)
        blocos = ler_listagem(r.content)
        if not blocos:
            break
        itens.extend(blocos)
        if parar and parar(blocos):
            break
        time.sleep(pausa)
    return itens
