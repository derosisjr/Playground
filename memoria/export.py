# -*- coding: utf-8 -*-
"""Gera memoria/memoria-index.json (LOCAL, gitignored) para o painel de busca.

O painel memoria.html roda localmente (python -m http.server) e faz a busca
lexical no navegador; o texto de cada documento vai truncado (o suficiente
para achar e abrir a fonte — a pergunta com IA usa o sqlite completo).

Uso:  python memoria/export.py [--dry-run]
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(AQUI, "memoria.sqlite")
SAIDA = os.path.join(AQUI, "memoria-index.json")
TRUNCAR = 1200  # chars de texto por documento no índice do painel


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(BASE)
    conn.row_factory = sqlite3.Row
    docs = [{
        "id": r["id"], "origem": r["origem"], "titulo": r["titulo"],
        "data": r["data"], "url": r["url"],
        "texto": (r["texto"] or "")[:TRUNCAR],
    } for r in conn.execute(
        "SELECT id, origem, titulo, data, url, texto FROM documentos "
        "ORDER BY data DESC")]

    por_origem = {}
    for d in docs:
        por_origem[d["origem"]] = por_origem.get(d["origem"], 0) + 1
    print("documentos por origem:", por_origem)
    if args.dry_run:
        print("[dry-run] nada gravado")
        return
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump({"gerado_em": datetime.now().isoformat(timespec="seconds"),
                   "documentos": docs}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"gravado: {SAIDA} ({len(docs)} documentos)")


if __name__ == "__main__":
    main()
