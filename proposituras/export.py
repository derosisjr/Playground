#!/usr/bin/env python3
"""
Export da base de Proposituras → XLSX, CSV e JSON
=================================================

Lê `proposituras/proposituras.sqlite` e gera:
  - proposituras/proposituras.xlsx   (planilha p/ gabinete; abas Proposituras + Tramitação)
  - proposituras/proposituras.csv    (análise)
  - proposituras-index.json (raiz)   (índice consumido pelo painel proposituras.html)

Ordem: data da propositura (mais recente primeiro), depois ano e número numérico.
O índice traz, além dos metadados, `tram`/`ua` em todos os itens e `ual`/`uad` só
nos em tramitação — contrato em .claude/rules/proposituras.md.

Uso:
    python proposituras/export.py
    python proposituras/export.py --db outro.sqlite --saida /tmp/teste   # não toca o índice versionado
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
from crawler import situacao_final  # noqa: E402  (mesma regra da revisita: arquivado/transformado)
DB_PATH = os.path.join(AQUI, "proposituras.sqlite")
XLSX_PATH = os.path.join(AQUI, "proposituras.xlsx")
CSV_PATH = os.path.join(AQUI, "proposituras.csv")
JSON_PATH = os.path.join(RAIZ, "proposituras-index.json")

COLUNAS = ["cod", "tipo", "subtipo", "numero", "ano", "processo", "data_propositura",
           "autor", "ementa", "local_atual", "situacao", "data_situacao",
           "url_detalhes", "url_pdf", "fonte", "data_coleta"]


def _data_iso(data: str | None) -> str:
    """'dd/mm/aaaa[ hh:mm:ss]' → 'aaaa-mm-dd' ('' se vazia ou fora do formato)."""
    m = re.match(r"\s*(\d{2})/(\d{2})/(\d{4})", data or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else ""


def _numero(numero: str | None) -> int:
    """'204/2026' → 204. Ordem numérica: o ORDER BY de texto abria a lista em "1, 10, 11…"."""
    m = re.match(r"\s*(\d[\d.]*)", numero or "")
    return int(m.group(1).replace(".", "")) if m else 0


def chave_ordem(p: dict) -> tuple:
    """Para `reverse=True` (mais recente primeiro): data da propositura, ano, número e,
    no empate, o cod — ordem total, para o índice versionado não mudar à toa. Sem data,
    o item vai para o fim do próprio ano."""
    return (_data_iso(p["data_propositura"]) or f"{p['ano'] or 0:04d}", p["ano"] or 0,
            _numero(p["numero"]), p["cod"])


def resumir(texto: str | None, limite: int = 120) -> str:
    """Espaços e quebras de linha colapsados; acima de `limite`, corta na última palavra
    inteira e fecha com "…" (o total, com o "…", não passa de `limite`)."""
    t = " ".join((texto or "").split())
    if len(t) <= limite:
        return t
    corte = t[:limite - 1]  # reserva 1 caractere para o "…"
    if t[limite - 1] != " " and " " in corte:  # parou no meio de uma palavra: descarta-a
        corte = corte.rsplit(" ", 1)[0]
    return corte.rstrip(" ,;:.-–—") + "…"


def ler_proposituras(db: str = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT {','.join(COLUNAS)} FROM proposituras").fetchall()
    conn.close()
    return sorted((dict(r) for r in rows), key=chave_ordem, reverse=True)


def ler_tramitacao(db: str = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT prop_cod, ordem, data, local, despacho, url_arquivo "
        "FROM tramitacao ORDER BY prop_cod, ordem"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def exportar_csv(props: list[dict], caminho: str = CSV_PATH) -> None:
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(props)


def exportar_xlsx(props: list[dict], tramites: list[dict], caminho: str = XLSX_PATH) -> None:
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.utils import get_column_letter

    def limpar(v):
        # remove caracteres de controle que o openpyxl recusa (ex.: em despachos)
        return ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v

    wb = Workbook()
    ws = wb.active
    ws.title = "Proposituras"
    ws.append(COLUNAS)
    for p in props:
        ws.append([limpar(p.get(c, "")) for c in COLUNAS])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUNAS))}{len(props)+1}"
    larguras = {"subtipo": 26, "ementa": 70, "autor": 28, "local_atual": 20,
                "situacao": 18, "url_detalhes": 45, "url_pdf": 45}
    for i, c in enumerate(COLUNAS, 1):
        ws.column_dimensions[get_column_letter(i)].width = larguras.get(c, 14)

    ws2 = wb.create_sheet("Tramitação")
    cols2 = ["prop_cod", "ordem", "data", "local", "despacho", "url_arquivo"]
    ws2.append(cols2)
    for t in tramites:
        ws2.append([limpar(t.get(c, "")) for c in cols2])
    ws2.freeze_panes = "A2"
    for i, c in enumerate(cols2, 1):
        ws2.column_dimensions[get_column_letter(i)].width = {"despacho": 80, "url_arquivo": 45}.get(c, 16)

    wb.save(caminho)


def exportar_json(props: list[dict], ultimos: dict[int, dict], caminho: str = JSON_PATH) -> int:
    """Grava o índice; devolve quantos itens estão em tramitação.
    `ultimos`: cod -> linha de `tramitacao` do andamento mais recente (ordem 0)."""
    # campos enxutos para o painel (sem fonte/data_coleta/processo)
    campos = ["cod", "tipo", "subtipo", "numero", "ano", "data_propositura",
              "autor", "ementa", "local_atual", "situacao", "url_detalhes", "url_pdf"]
    dados = [{c: p.get(c, "") for c in campos} for p in props]
    # `tram` e `ua` em todos (o `tram` sempre presente é o que separa índice novo de antigo
    # no painel); local e despacho do último andamento só nos em tramitação (~1,7 mil de
    # ~7 mil) — nos arquivados seriam peso sem uso
    for d, p in zip(dados, props):
        u = ultimos.get(p["cod"]) or {}
        d["tram"] = 0 if situacao_final(p["local_atual"], p["situacao"]) else 1
        d["ua"] = _data_iso(u.get("data") or p.get("data_situacao"))
        if d["tram"]:
            d["ual"] = " ".join((u.get("local") or "").split())
            d["uad"] = resumir(u.get("despacho"))
    gravar_json(caminho, dados, separators=(",", ":"))
    return sum(d["tram"] for d in dados)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Export da base de Proposituras → XLSX, CSV e JSON")
    ap.add_argument("--db", default=DB_PATH, help="SQLite de entrada (padrão: proposituras/proposituras.sqlite)")
    ap.add_argument("--saida", help="Pasta para os três arquivos (padrão: índice na raiz do repo, XLSX/CSV "
                                    "em proposituras/) — para testar sem sobrescrever o índice versionado")
    args = ap.parse_args(argv)
    if not os.path.exists(args.db):
        print(f"Banco não encontrado: {args.db}. Rode o crawler primeiro.", file=sys.stderr)
        sys.exit(1)
    caminho_xlsx, caminho_csv, caminho_json = XLSX_PATH, CSV_PATH, JSON_PATH
    if args.saida:
        os.makedirs(args.saida, exist_ok=True)
        caminho_xlsx, caminho_csv, caminho_json = (
            os.path.join(args.saida, os.path.basename(p)) for p in (XLSX_PATH, CSV_PATH, JSON_PATH))
    props = ler_proposituras(args.db)
    tramites = ler_tramitacao(args.db)
    ultimos = {t["prop_cod"]: t for t in tramites if t["ordem"] == 0}
    exportar_csv(props, caminho_csv)
    exportar_xlsx(props, tramites, caminho_xlsx)
    em_tramitacao = exportar_json(props, ultimos, caminho_json)
    print(f"Export concluído: {len(props)} proposituras ({em_tramitacao} em tramitação; "
          f"{len(tramites)} despachos) → {caminho_xlsx}, {caminho_csv}, {caminho_json}.", file=sys.stderr)


if __name__ == "__main__":
    main()
