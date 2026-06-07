#!/usr/bin/env python3
"""
Crawler do Legis (Prefeitura de Santos) — índice enxuto (só metadados)
======================================================================

Varre o sistema Legis (`egov.santos.sp.gov.br/legis`) e indexa os METADADOS de
cada norma (tipo, número, ano, data, ementa, tags) + link para o PDF oficial,
gravando num SQLite. NÃO baixa o PDF nem extrai texto integral (ver plano).

Navegação:
  tipo:  /legis/topics/{T}/documents        (lista os anos como sub-tópicos)
  ano:   /legis/topics/{Y}/documents?page=N  (lista /legis/documents/{ID})
  norma: /legis/documents/{ID}               (h1 + badges = ementa/tags)
  PDF:   /legis/documents/{ID}/download

Encoding: páginas em latin-1, MAS alguns campos (ementa/tags) contêm UTF-8
"dentro" do latin-1 (double-encoding). Resolve-se decodificando a página como
latin-1 (1:1, sem sniffing) e reparando cada campo com `_fix`.

Uso:
    python legis/crawler.py --tipo 6 --ano 2024 --limite 5   # amostra
    python legis/crawler.py --tipo 6                          # um tipo inteiro
    python legis/crawler.py                                   # tudo (carga completa)
    python legis/crawler.py --forcar                          # reprocessa existentes
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

BASE_URL = "https://egov.santos.sp.gov.br"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LegisIndexBot/1.0)"}
AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(AQUI, "legis.sqlite")
SCHEMA_PATH = os.path.join(AQUI, "schema.sql")
FONTE = "Legis Prefeitura de Santos"
PAUSA = 0.2  # cortesia entre requisições (s)

# Tópico de cada tipo de norma (confirmado por inspeção).
TIPOS = {
    6: "Lei ordinária",
    5: "Lei complementar",
    7: "Decreto",
    4: "Consolidação",
    8: "Índice de leis e decretos",
    150: "Ordem de Serviço",
    1: "Código",
    2: "Lei Orgânica",
}

MESES = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}


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


def _fix(t: str) -> str:
    """Repara campos UTF-8 que vieram embutidos numa página latin-1."""
    try:
        return t.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return t


def _soup(url: str, params: dict | None = None) -> BeautifulSoup:
    raw = _http_get(url, params=params).content
    # decodifica 1:1 como latin-1 e passa str (evita o sniffing UTF-8 do BS)
    return BeautifulSoup(raw.decode("latin-1"), "html.parser")


def _txt(tag) -> str:
    return _fix(tag.get_text(" ", strip=True)) if tag else ""


# ── Navegação ─────────────────────────────────────────────────────────────────
def mapear_anos(topico: int) -> dict[int, str]:
    """Retorna {ano: url_do_subtopico}. Vazio se o tipo não tem nível de ano."""
    soup = _soup(f"{BASE_URL}/legis/topics/{topico}/documents")
    anos: dict[int, str] = {}
    for a in soup.select("a[href]"):
        rotulo = a.get_text(strip=True)
        href = a.get("href", "")
        if re.fullmatch(r"\d{4}", rotulo) and re.search(r"/topics/\d+/documents", href):
            anos[int(rotulo)] = href if href.startswith("http") else BASE_URL + href
    return anos


def coletar_ids(listagem_url: str) -> list[int]:
    """Pagina a listagem (?page=N) e devolve os IDs de documentos, em ordem."""
    ids: list[int] = []
    vistos: set[int] = set()
    page = 1
    while True:
        soup = _soup(listagem_url, params={"page": page} if page > 1 else None)
        novos = 0
        for a in soup.select("a[href]"):
            m = re.search(r"/legis/documents/(\d+)(?:$|[/?#])", a.get("href", ""))
            if m:
                did = int(m.group(1))
                if did not in vistos:
                    vistos.add(did)
                    ids.append(did)
                    novos += 1
        if novos == 0:
            break
        page += 1
        time.sleep(PAUSA)
    return ids


def detalhar(docid: int, tipo: str, ano: int | None) -> dict:
    """Faz scraping da página da norma e devolve metadados + temas."""
    url = f"{BASE_URL}/legis/documents/{docid}"
    soup = _soup(url)
    h1 = _txt(soup.select_one("h1"))

    # "2024 » Lei n.º 4.450, de 01 de março"  /  "Consolidações » Estatuto ..."
    prefixo, _, resto = h1.partition("»")
    prefixo, resto = prefixo.strip(), resto.strip()
    titulo = resto or prefixo

    numero = ""
    m = re.search(r"n\.?º\s*([\d][\d.\-/]*)", resto)
    if m:
        numero = m.group(1)

    if ano is None:
        ma = re.fullmatch(r"\d{4}", prefixo)
        if ma:
            ano = int(prefixo)

    # data "..., de 01 de março" + ano
    data_norma = ""
    md = re.search(r",\s*de\s+(\d{1,2})\s+de\s+([A-Za-zçãéê]+)", resto, re.I)
    if md and ano:
        dia = int(md.group(1))
        mes = MESES.get(md.group(2).lower())
        if mes:
            data_norma = f"{dia:02d}/{mes:02d}/{ano}"

    # badges: frases longas = ementa; curtas = temas
    ementa_partes, temas = [], []
    for b in soup.select(".badge-primary"):
        texto = _txt(b)
        if not texto:
            continue
        if len(texto) > 40 or len(texto.split()) > 4:
            ementa_partes.append(texto)
        else:
            temas.append(texto)
    ementa = " ".join(ementa_partes)

    return {
        "id": docid,
        "tipo": tipo,
        "numero": numero,
        "ano": ano,
        "data_norma": data_norma,
        "titulo": titulo,
        "ementa": ementa,
        "tags": "; ".join(temas),
        "situacao": "",
        "url_legis": url,
        "url_pdf": f"{url}/download",
        "fonte": FONTE,
        "data_coleta": datetime.now().isoformat(timespec="seconds"),
        "_temas": temas,
    }


# ── Banco ─────────────────────────────────────────────────────────────────────
def abrir_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def ids_existentes(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT id FROM normas")}


def upsert(conn: sqlite3.Connection, n: dict) -> None:
    cols = ["id", "tipo", "numero", "ano", "data_norma", "titulo", "ementa",
            "tags", "situacao", "url_legis", "url_pdf", "fonte", "data_coleta"]
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT OR REPLACE INTO normas ({','.join(cols)}) VALUES ({placeholders})",
        [n[c] for c in cols],
    )
    conn.execute("DELETE FROM temas WHERE norma_id = ?", (n["id"],))
    conn.executemany(
        "INSERT OR IGNORE INTO temas (norma_id, tema) VALUES (?, ?)",
        [(n["id"], t) for t in n["_temas"]],
    )


# ── Orquestração ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Crawler do Legis — índice de metadados")
    parser.add_argument("--tipo", type=int, help="ID do tópico de tipo (ver TIPOS). Padrão: todos.")
    parser.add_argument("--ano", type=int, help="Ano específico. Padrão: todos os anos do tipo.")
    parser.add_argument("--limite", type=int, default=0, help="Máx. de normas a processar (0=todas).")
    parser.add_argument("--forcar", action="store_true", help="Reprocessa normas já no banco.")
    parser.add_argument("--dry-run", action="store_true", help="Não grava no banco (só imprime).")
    args = parser.parse_args()

    tipos = {args.tipo: TIPOS.get(args.tipo, f"Tópico {args.tipo}")} if args.tipo else dict(TIPOS)

    conn = None if args.dry_run else abrir_db()
    existentes = ids_existentes(conn) if conn else set()
    processados = 0

    for tid, nome_tipo in tipos.items():
        print(f"== Tipo {tid} — {nome_tipo} ==", file=sys.stderr)
        try:
            anos = mapear_anos(tid)
        except Exception as e:
            print(f"  ERRO ao mapear anos do tipo {tid}: {e} — pulando tipo.", file=sys.stderr)
            continue
        if anos:
            if args.ano:
                anos = {args.ano: anos[args.ano]} if args.ano in anos else {}
            alvos = sorted(anos.items(), reverse=True)
        else:
            # tipo sem nível de ano (ex.: Lei Orgânica, Códigos) — lista direto
            alvos = [(None, f"{BASE_URL}/legis/topics/{tid}/documents")]

        for ano, url in alvos:
            try:
                ids = coletar_ids(url)
            except Exception as e:
                print(f"  ERRO ao listar {nome_tipo} {ano or ''}: {e} — pulando.", file=sys.stderr)
                continue
            print(f"  {nome_tipo} {ano or ''}: {len(ids)} documentos.", file=sys.stderr)
            for did in ids:
                if args.limite and processados >= args.limite:
                    break
                if did in existentes and not args.forcar:
                    continue
                try:
                    n = detalhar(did, nome_tipo, ano)
                except Exception as e:
                    print(f"  ERRO doc {did}: {e} — pulando.", file=sys.stderr)
                    continue
                if args.dry_run:
                    print(f"  [{n['tipo']}] nº {n['numero']} ({n['ano']}) — "
                          f"{(n['ementa'] or n['titulo'])[:80]} | tags={n['tags']}")
                else:
                    upsert(conn, n)
                    conn.commit()
                    existentes.add(did)
                processados += 1
                time.sleep(PAUSA)
            if args.limite and processados >= args.limite:
                break
        if args.limite and processados >= args.limite:
            break

    if conn:
        conn.close()
    print(f"Concluído: {processados} normas processadas.", file=sys.stderr)


if __name__ == "__main__":
    main()
