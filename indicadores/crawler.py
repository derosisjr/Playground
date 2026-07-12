# -*- coding: utf-8 -*-
"""Crawler do painel Custo por Resultado.

Baixa para o indicadores.sqlite:
  - gasto_externo: despesa liquidada por função (SICONFI/DCA), 2019+;
  - indicadores: mortalidade infantil e IDEB (APIs do IBGE);
  - populacao: população por município/ano (estimativas + Censo 2022).

Recarga idempotente (INSERT OR REPLACE); controle_carga registra o que já foi
baixado — o DCA de anos encerrados não muda, então só o ano mais recente é
rebaixado por padrão (use --forcar para reprocessar tudo).

Uso:
  python indicadores/crawler.py                     # carga/atualização completa
  python indicadores/crawler.py --fonte dca --ano 2023 --dry-run
  python indicadores/crawler.py --fonte ibge --dry-run
"""
import argparse
import os
import re
import sqlite3
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fontes  # noqa: E402

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "indicadores.sqlite")
ANO_INICIAL = 2019  # série pré-mandato dá contexto ao debate de orçamento


def conectar():
    conn = sqlite3.connect(BASE)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS indicadores(
            municipio TEXT, ano INTEGER, indicador TEXT, valor REAL,
            PRIMARY KEY(municipio, ano, indicador));
        CREATE TABLE IF NOT EXISTS gasto_externo(
            municipio TEXT, ano INTEGER, funcao TEXT, valor REAL,
            PRIMARY KEY(municipio, ano, funcao));
        CREATE TABLE IF NOT EXISTS populacao(
            municipio TEXT, ano INTEGER, valor INTEGER,
            PRIMARY KEY(municipio, ano));
        CREATE TABLE IF NOT EXISTS controle_carga(
            fonte TEXT, ano INTEGER, PRIMARY KEY(fonte, ano));
    """)
    return conn


# ── SICONFI/DCA: despesa liquidada por função ────────────────────────────────
def carregar_dca(conn, ano: int, dry_run=False) -> int:
    linhas = []
    for ibge7 in fontes.COMPARAVEIS:
        itens = fontes.baixar_dca(ano, ibge7)
        for it in itens:
            conta = str(it.get("conta", ""))
            m = re.match(r"^(\d{2}) - ", conta)  # só funções (não subfunções)
            if not m or m.group(1) not in fontes.FUNCOES:
                continue
            if it.get("coluna") != "Despesas Liquidadas":
                continue
            linhas.append((ibge7, ano, m.group(1), float(it.get("valor") or 0)))
    if dry_run:
        for ln in linhas[:12]:
            print("  dca:", ln)
        return len(linhas)
    conn.executemany(
        "INSERT OR REPLACE INTO gasto_externo VALUES (?,?,?,?)", linhas)
    conn.execute("INSERT OR REPLACE INTO controle_carga VALUES ('dca', ?)", (ano,))
    conn.commit()
    return len(linhas)


# ── IBGE: indicadores (todos os períodos numa chamada por indicador) ─────────
def carregar_ibge(conn, dry_run=False) -> int:
    linhas = []
    for slug in fontes.INDICADORES:
        dados = fontes.baixar_indicador_ibge(slug)
        for ind in dados:
            for res in ind.get("res", []):
                ibge7 = fontes.IBGE6_PARA_7.get(str(res.get("localidade", "")))
                if not ibge7:
                    continue
                for ano, valor in (res.get("res") or {}).items():
                    if valor in (None, "-", "...", ".."):
                        continue
                    try:
                        linhas.append((ibge7, int(ano), slug, float(valor)))
                    except ValueError:
                        continue
    if dry_run:
        for ln in linhas[:12]:
            print("  ibge:", ln)
        return len(linhas)
    conn.executemany(
        "INSERT OR REPLACE INTO indicadores VALUES (?,?,?,?)", linhas)
    conn.execute("INSERT OR REPLACE INTO controle_carga VALUES ('ibge', 0)")
    conn.commit()
    return len(linhas)


# ── IBGE: população ──────────────────────────────────────────────────────────
def carregar_populacao(conn, anos, dry_run=False) -> int:
    pop = fontes.baixar_populacao(anos)
    linhas = [(m, a, v) for (m, a), v in pop.items()]
    if dry_run:
        for ln in linhas[:12]:
            print("  pop:", ln)
        return len(linhas)
    conn.executemany(
        "INSERT OR REPLACE INTO populacao VALUES (?,?,?)", linhas)
    conn.commit()
    return len(linhas)


def main():
    ap = argparse.ArgumentParser(description="Crawler de indicadores (Custo por Resultado)")
    ap.add_argument("--fonte", choices=["dca", "ibge", "pop"], help="só uma fonte")
    ap.add_argument("--ano", type=int, help="só um ano (fonte dca)")
    ap.add_argument("--forcar", action="store_true", help="rebaixa anos já carregados")
    ap.add_argument("--dry-run", action="store_true", help="imprime sem gravar")
    args = ap.parse_args()

    conn = conectar()
    ja = {r["ano"] for r in conn.execute(
        "SELECT ano FROM controle_carga WHERE fonte='dca'")}
    ano_corrente = date.today().year

    total = 0
    if args.fonte in (None, "dca"):
        anos = [args.ano] if args.ano else list(range(ANO_INICIAL, ano_corrente + 1))
        for ano in anos:
            # DCA de anos encerrados não muda; o dos 2 últimos anos pode
            # aparecer/ser retificado — sempre retenta esses.
            if not args.forcar and not args.dry_run \
                    and ano in ja and ano < ano_corrente - 1:
                continue
            n = carregar_dca(conn, ano, args.dry_run)
            print(f"dca {ano}: {n} linhas")
            total += n
    if args.fonte in (None, "ibge"):
        n = carregar_ibge(conn, args.dry_run)
        print(f"ibge (indicadores): {n} linhas")
        total += n
    if args.fonte in (None, "pop"):
        n = carregar_populacao(conn, list(range(ANO_INICIAL, ano_corrente + 1)),
                               args.dry_run)
        print(f"populacao: {n} linhas")
        total += n

    print(("[dry-run] " if args.dry_run else "") + f"total: {total} linhas")


if __name__ == "__main__":
    main()
