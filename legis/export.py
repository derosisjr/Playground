#!/usr/bin/env python3
"""
Export da base Legis → XLSX, CSV e JSON
=======================================

Lê `legis/legis.sqlite` e gera:
  - legis/legis.xlsx        (planilha p/ gabinete)
  - legis/legis.csv         (análise)
  - legis-index.json (raiz) (índice consumido pelo painel legis.html)
  - legis/ementas.json      ({id: ementa oficial} — fora do índice por tamanho)

Ordem: data da norma (mais recente primeiro). Número ausente no banco é tirado do
título quando dá ("Decreto n.° 11.161, de 05 de março" → "11.161").

Uso:
    python legis/export.py
    python legis/export.py --db outro.sqlite --saida /tmp/teste   # não toca os arquivos versionados
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys


AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
if RAIZ not in sys.path:
    sys.path.append(RAIZ)  # camada comum do repo (comum/)
from comum.saida import configurar_stdio  # noqa: E402

configurar_stdio()
from comum.escrita import gravar_json  # noqa: E402
DB_PATH = os.path.join(AQUI, "legis.sqlite")
XLSX_PATH = os.path.join(AQUI, "legis.xlsx")
CSV_PATH = os.path.join(AQUI, "legis.csv")
JSON_PATH = os.path.join(RAIZ, "legis-index.json")
EMENTAS_PATH = os.path.join(AQUI, "ementas.json")

COLUNAS = ["id", "tipo", "numero", "ano", "data_norma", "titulo", "ementa", "descricao",
           "tags", "situacao", "revogada_por", "url_legis", "url_pdf", "fonte", "data_coleta"]

# "n.°", "n,º", "nº.", "n. º", "n°", "n." — grafias do Legis que o regex do crawler
# (n\.?º) não reconhece; 62 das 66 normas sem número em 2026-10 (as outras 4 não têm
# número no título: Lei Orgânica e consolidações)
RE_NUMERO_TITULO = re.compile(r"\bn[\s.,º°]*(\d[\d.]*)", re.I)


def numero_do_titulo(titulo: str | None) -> str:
    """'Decreto n.° 11.161, de 05 de março' → '11.161' ('' se o título não traz número)."""
    m = RE_NUMERO_TITULO.search(titulo or "")
    return m.group(1).rstrip(".") if m else ""


def _data_iso(data: str | None) -> str:
    """'dd/mm/aaaa' → 'aaaa-mm-dd' ('' se vazia ou fora do formato)."""
    m = re.match(r"\s*(\d{2})/(\d{2})/(\d{4})", data or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else ""


def _numero(numero: str | None) -> int:
    """'4.450' → 4450 (ordem numérica: no texto, '999' vinha antes de '1.000')."""
    m = re.match(r"\s*(\d[\d.]*)", numero or "")
    return int(m.group(1).replace(".", "")) if m else 0


def chave_ordem(n: dict) -> tuple:
    """Para `reverse=True` (mais recente primeiro): data da norma, número e, no empate, o
    id — ordem total, para o índice versionado não mudar à toa. Sem data, a norma vai
    para o fim do próprio ano; sem ano (Lei Orgânica, consolidações), para o fim."""
    return (_data_iso(n["data_norma"]) or f"{n['ano'] or 0:04d}", _numero(n["numero"]), n["id"])


def ler_normas(db: str = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT {','.join(COLUNAS)} FROM normas").fetchall()
    conn.close()
    normas = [dict(r) for r in rows]
    for n in normas:
        if not (n["numero"] or "").strip():
            n["numero"] = numero_do_titulo(n["titulo"])
    return sorted(normas, key=chave_ordem, reverse=True)


def exportar_csv(normas: list[dict], caminho: str = CSV_PATH) -> None:
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(normas)


def exportar_xlsx(normas: list[dict], caminho: str = XLSX_PATH) -> None:
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Normas"
    ws.append(COLUNAS)
    for n in normas:
        ws.append([n.get(c, "") for c in COLUNAS])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUNAS))}{len(normas)+1}"
    larguras = {"titulo": 50, "ementa": 70, "descricao": 70, "tags": 30, "url_legis": 45, "url_pdf": 45}
    for i, c in enumerate(COLUNAS, 1):
        ws.column_dimensions[get_column_letter(i)].width = larguras.get(c, 14)
    wb.save(caminho)


def exportar_json(normas: list[dict], caminho: str = JSON_PATH) -> None:
    # campos enxutos para o painel (sem fonte/data_coleta)
    campos = ["id", "tipo", "numero", "ano", "data_norma", "titulo", "ementa",
              "tags", "situacao", "url_legis", "url_pdf"]
    dados = [{c: n.get(c, "") for c in campos} for n in normas]
    # revogadora (id) só onde há — a imensa maioria não tem; a ementa oficial
    # (`descricao`) fica fora do índice por tamanho (vai no ementas.json e no CSV/XLSX)
    for d, n in zip(dados, normas):
        if n.get("revogada_por"):
            d["revogada_por"] = n["revogada_por"]
    gravar_json(caminho, dados, separators=(",", ":"))


def exportar_ementas(normas: list[dict], caminho: str = EMENTAS_PATH) -> int:
    """{"<id>": ementa oficial} só das normas que a têm, em ordem crescente de id (norma
    nova entra no fim: diff pequeno). O painel busca sob demanda; devolve quantas são."""
    ementas = {str(n["id"]): n["descricao"] for n in sorted(normas, key=lambda n: n["id"])
               if (n.get("descricao") or "").strip()}
    gravar_json(caminho, ementas, separators=(",", ":"))
    return len(ementas)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Export da base Legis → XLSX, CSV e JSON")
    ap.add_argument("--db", default=DB_PATH, help="SQLite de entrada (padrão: legis/legis.sqlite)")
    ap.add_argument("--saida", help="Pasta para os quatro arquivos (padrão: índice na raiz do repo, "
                                    "ementas/XLSX/CSV em legis/) — para testar sem sobrescrever os versionados")
    args = ap.parse_args(argv)
    if not os.path.exists(args.db):
        print(f"Banco não encontrado: {args.db}. Rode o crawler primeiro.", file=sys.stderr)
        sys.exit(1)
    caminhos = (XLSX_PATH, CSV_PATH, JSON_PATH, EMENTAS_PATH)
    if args.saida:
        os.makedirs(args.saida, exist_ok=True)
        caminhos = tuple(os.path.join(args.saida, os.path.basename(p)) for p in caminhos)
    caminho_xlsx, caminho_csv, caminho_json, caminho_ementas = caminhos
    normas = ler_normas(args.db)
    exportar_csv(normas, caminho_csv)
    exportar_xlsx(normas, caminho_xlsx)
    exportar_json(normas, caminho_json)
    n_ementas = exportar_ementas(normas, caminho_ementas)
    sem_numero = sum(1 for n in normas if not n["numero"])
    print(f"Export concluído: {len(normas)} normas ({n_ementas} com ementa oficial; "
          f"{sem_numero} sem número nem no título) → {', '.join(caminhos)}.", file=sys.stderr)


if __name__ == "__main__":
    main()
