#!/usr/bin/env python3
"""
Crawler de Proposituras (Câmara Municipal de Santos) — tipo "Projeto"
====================================================================

Varre a busca pública de documentos legislativos da Câmara
(`administrativo.camarasantos.sp.gov.br/.../busca_documento_pub/`) e indexa os
METADADOS de cada propositura do tipo **Projeto** (Projeto de Lei, PL Complementar,
Projeto de Decreto Legislativo, Resolução, Emenda à LOM) + a situação/tramitação,
gravando num SQLite. NÃO baixa o PDF nem extrai texto integral (ver plano).

Navegação:
  listagem: filtro.php?pesquisa_autor[tipo]=4&pesquisa_autor[ano]=AAAA  (paginada por &limite=N)
  detalhe:  detalhes.php?cod=COD  (tabela "Tramitação" = histórico de despachos)

A listagem já traz quase tudo (nº, data, situação, autor, local, ementa, PDF); a
página de detalhes é consultada apenas para o histórico completo de tramitação.

Encoding: páginas em ISO-8859-1 (latin-1) — ler com `from_encoding="iso-8859-1"`.

Uso:
    python proposituras/crawler.py --ano 2026 --limite 5 --dry-run   # amostra
    python proposituras/crawler.py --ano 2026                        # um ano
    python proposituras/crawler.py                                   # tudo (carga completa)
    python proposituras/crawler.py --forcar                          # reprocessa existentes
    python proposituras/crawler.py --sem-tramitacao                  # pula detalhes.php (mais rápido)
"""

import argparse
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

BASE_URL = "https://administrativo.camarasantos.sp.gov.br"
BUSCA_DIR = f"{BASE_URL}/dispositivo/customizado_publico/legislativo/busca_documento_pub"
FILTRO_URL = f"{BUSCA_DIR}/filtro.php"
DETALHES_URL = f"{BUSCA_DIR}/detalhes.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PropositurasIndexBot/1.0)"}

AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(AQUI, "proposituras.sqlite")
SCHEMA_PATH = os.path.join(AQUI, "schema.sql")
FONTE = "Câmara Municipal de Santos"

TIPO_PROJETO = 4          # value do <option> "Projeto"
PAGINA_TAMANHO = 20       # resultados por página (passo do offset `limite`)
PAUSA = 0.2               # cortesia entre requisições (s)
ANO_MIN = 2012            # primeiro ano com dados no sistema


# ── HTTP / parsing ────────────────────────────────────────────────────────────
def _http_get(url: str, params: dict | None = None, tentativas: int = 4) -> requests.Response:
    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            ultimo = e
            if i < tentativas - 1:
                espera = 4 * (i + 1)
                print(f"  Aviso: falha HTTP ({e}); tentativa {i+1}/{tentativas}, "
                      f"aguardando {espera}s...", file=sys.stderr)
                time.sleep(espera)
    raise ultimo


def _soup(url: str, params: dict | None = None) -> BeautifulSoup:
    raw = _http_get(url, params=params).content
    return BeautifulSoup(raw, "html.parser", from_encoding="iso-8859-1")


def _txt(tag) -> str:
    return tag.get_text(" ", strip=True) if tag else ""


# ── Parsing da listagem ─────────────────────────────────────────────────────────
def _parse_bloco(tab) -> dict | None:
    """Extrai os metadados de um <table.table-bordered> da listagem."""
    link = tab.select_one("a[href*='detalhes.php']")
    if not link:
        return None
    m = re.search(r"cod=(\d+)", link.get("href", ""))
    if not m:
        return None
    cod = int(m.group(1))

    # Título: "Projeto de Lei - Nº 204/2026 [Processo Nº 7767/2026]"
    titulo = _txt(tab.select_one("thead strong"))
    subtipo, numero, processo = "", "", ""
    mt = re.match(r"\s*(.+?)\s*-\s*N[ºo°]\s*([\d./-]+)", titulo)
    if mt:
        subtipo = mt.group(1).strip()
        numero = mt.group(2).strip()
    mp = re.search(r"Processo\s*N[ºo°]\s*([\d./-]+)", titulo)
    if mp:
        processo = mp.group(1).strip()

    # Linhas <th>rótulo</th><td>valor</td>
    campos: dict[str, str] = {}
    for row in tab.select("tbody tr"):
        th = row.find("th")
        td = th.find_next_sibling("td") if th else None
        if th and td:
            chave = th.get_text(strip=True).rstrip(":")
            if chave and chave != "\xa0":
                campos[chave] = td.get_text(" ", strip=True)

    # Ementa: o td que segue o <span>Ementa:</span>
    ementa = ""
    span = tab.find("span", string=re.compile(r"Ementa", re.I))
    if span:
        td = span.find_parent("td")
        if td:
            ementa = re.sub(r"^\s*Ementa:\s*", "", td.get_text(" ", strip=True)).strip()

    # PDF do projeto
    url_pdf = ""
    a_pdf = tab.find("a", href=re.compile(r"\.pdf", re.I))
    if a_pdf:
        href = a_pdf["href"]
        url_pdf = href if href.startswith("http") else BASE_URL + href

    numero = numero or campos.get("Número", "")
    ano = None
    ma = re.search(r"/(\d{4})", numero)
    if ma:
        ano = int(ma.group(1))

    return {
        "cod": cod,
        "tipo": "Projeto",
        "subtipo": subtipo,
        "numero": numero,
        "ano": ano,
        "processo": processo,
        "data_propositura": campos.get("Data", ""),
        "autor": campos.get("Autor", ""),
        "ementa": ementa,
        "local_atual": campos.get("Local", ""),
        "situacao": campos.get("Situação", ""),
        "data_situacao": "",
        "url_detalhes": f"{DETALHES_URL}?cod={cod}",
        "url_pdf": url_pdf,
        "fonte": FONTE,
        "data_coleta": datetime.now().isoformat(timespec="seconds"),
    }


def coletar_pagina(ano: int | str, limite: int) -> list[dict]:
    """Devolve os itens de uma página da listagem (offset `limite`)."""
    params = {
        "pesquisa_autor[tipo]": TIPO_PROJETO,
        "pesquisa_autor[ano]": ano,
        "pesquisa_autor[vereador]": "",
        "pesquisa_autor[subtipo]": "",
    }
    if limite:
        params["limite"] = limite
    soup = _soup(FILTRO_URL, params=params)
    itens = []
    for tab in soup.select("table.table-bordered"):
        item = _parse_bloco(tab)
        if item:
            itens.append(item)
    return itens


# ── Parsing da tramitação (detalhes.php) ────────────────────────────────────────
def coletar_tramitacao(cod: int) -> list[dict]:
    """Devolve o histórico de despachos (tabela #historico_despacho)."""
    soup = _soup(f"{DETALHES_URL}?cod={cod}")
    tab = soup.select_one("table#historico_despacho")
    if not tab:
        return []
    despachos = []
    for i, row in enumerate(tab.select("tbody tr")):
        tds = row.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        data = " ".join(tds[0].get_text(" ", strip=True).split())
        local = tds[1].get_text(" ", strip=True)
        despacho = tds[2].get_text(" ", strip=True)
        url_arquivo = ""
        a = row.find("a", href=re.compile(r"\.(pdf|docx?)", re.I))
        if a:
            href = a["href"]
            url_arquivo = href if href.startswith("http") else BASE_URL + href
        despachos.append({
            "ordem": i, "data": data, "local": local,
            "despacho": despacho, "url_arquivo": url_arquivo,
        })
    return despachos


# ── Banco ─────────────────────────────────────────────────────────────────────
def abrir_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def ids_existentes(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT cod FROM proposituras")}


def upsert(conn: sqlite3.Connection, p: dict, tramites: list[dict]) -> None:
    cols = ["cod", "tipo", "subtipo", "numero", "ano", "processo", "data_propositura",
            "autor", "ementa", "local_atual", "situacao", "data_situacao",
            "url_detalhes", "url_pdf", "fonte", "data_coleta"]
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT OR REPLACE INTO proposituras ({','.join(cols)}) VALUES ({placeholders})",
        [p[c] for c in cols],
    )
    conn.execute("DELETE FROM tramitacao WHERE prop_cod = ?", (p["cod"],))
    conn.executemany(
        "INSERT OR IGNORE INTO tramitacao (prop_cod, ordem, data, local, despacho, url_arquivo) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(p["cod"], t["ordem"], t["data"], t["local"], t["despacho"], t["url_arquivo"])
         for t in tramites],
    )


# ── Orquestração ──────────────────────────────────────────────────────────────
def anos_alvo(arg_ano: int | None) -> list[int | str]:
    if arg_ano:
        return [arg_ano]
    # do ano corrente para trás + "Anteriores" (atos antigos)
    corrente = datetime.now().year
    return list(range(corrente, ANO_MIN - 1, -1)) + ["Anteriores"]


def main():
    parser = argparse.ArgumentParser(description="Crawler de Proposituras (Câmara de Santos) — tipo Projeto")
    parser.add_argument("--ano", type=int, help="Ano específico. Padrão: todos (corrente→2012 + Anteriores).")
    parser.add_argument("--limite", type=int, default=0, help="Máx. de proposituras a processar (0=todas).")
    parser.add_argument("--forcar", action="store_true", help="Reprocessa itens já no banco.")
    parser.add_argument("--sem-tramitacao", action="store_true", help="Não consulta detalhes.php (pula histórico).")
    parser.add_argument("--dry-run", action="store_true", help="Não grava no banco (só imprime).")
    args = parser.parse_args()

    conn = None if args.dry_run else abrir_db()
    existentes = ids_existentes(conn) if conn else set()
    processados = 0

    for ano in anos_alvo(args.ano):
        print(f"== Projeto — ano {ano} ==", file=sys.stderr)
        offset = 0
        vistos: set[int] = set()
        while True:
            try:
                itens = coletar_pagina(ano, offset)
            except Exception as e:
                print(f"  ERRO ao listar ano {ano} (offset {offset}): {e} — pulando ano.", file=sys.stderr)
                break
            novos = [i for i in itens if i["cod"] not in vistos]
            if not novos:
                break
            for item in novos:
                vistos.add(item["cod"])
                if args.limite and processados >= args.limite:
                    break
                if item["cod"] in existentes and not args.forcar:
                    continue
                tramites = []
                if not args.sem_tramitacao:
                    try:
                        tramites = coletar_tramitacao(item["cod"])
                    except Exception as e:
                        print(f"  Aviso: tramitação do cod {item['cod']} falhou: {e}", file=sys.stderr)
                    if tramites:
                        item["data_situacao"] = tramites[0]["data"]
                    time.sleep(PAUSA)

                if args.dry_run:
                    print(f"  [{item['subtipo']}] nº {item['numero']} — {item['autor']} | "
                          f"sit={item['situacao']} | {(item['ementa'])[:70]}")
                else:
                    upsert(conn, item, tramites)
                    conn.commit()
                    existentes.add(item["cod"])
                processados += 1
            if args.limite and processados >= args.limite:
                break
            offset += PAGINA_TAMANHO
            time.sleep(PAUSA)
        if args.limite and processados >= args.limite:
            break

    if conn:
        conn.close()
    print(f"Concluído: {processados} proposituras processadas.", file=sys.stderr)


if __name__ == "__main__":
    main()
