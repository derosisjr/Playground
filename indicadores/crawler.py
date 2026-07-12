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
        CREATE TABLE IF NOT EXISTS fiscal(
            municipio TEXT, ano INTEGER, conta TEXT, valor REAL,
            PRIMARY KEY(municipio, ano, conta));
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


# ── SICONFI/DCA: receita e despesa por categoria (tema fiscal) ───────────────
def carregar_fiscal(conn, ano: int, dry_run=False) -> int:
    linhas = []
    for ibge7 in fontes.COMPARAVEIS:
        contas = fontes.baixar_fiscal(ano, ibge7)
        for chave, valor in contas.items():
            linhas.append((ibge7, ano, chave, valor))
    if dry_run:
        for ln in linhas[:12]:
            print("  fiscal:", ln)
        return len(linhas)
    conn.executemany("INSERT OR REPLACE INTO fiscal VALUES (?,?,?,?)", linhas)
    conn.execute("INSERT OR REPLACE INTO controle_carga VALUES ('fiscal', ?)", (ano,))
    conn.commit()
    return len(linhas)


# ── IBGE: indicadores (municípios + referência estadual SP) ──────────────────
def _linhas_ibge(slug, municipios, aceitar):
    """Lê um indicador IBGE e devolve linhas (municipio, ano, slug, valor).
    `aceitar(loc)` mapeia a localidade da API p/ o código a gravar (ou None)."""
    linhas = []
    for ind in fontes.baixar_indicador_ibge(slug, municipios):
        for res in ind.get("res", []):
            cod = aceitar(str(res.get("localidade", "")))
            if not cod:
                continue
            for ano, valor in (res.get("res") or {}).items():
                if valor in (None, "-", "...", ".."):
                    continue
                try:
                    linhas.append((cod, int(ano), slug, float(valor)))
                except ValueError:
                    continue
    return linhas


def carregar_ibge(conn, dry_run=False, incluir_sp=True) -> int:
    linhas = []
    for slug in fontes.INDICADORES:
        # municípios comparáveis
        linhas += _linhas_ibge(slug, fontes._MUN_PIPE,
                               lambda loc: fontes.IBGE6_PARA_7.get(loc))
        # referência estadual (grava municipio="35"); degrada se a API não expõe
        if incluir_sp:
            try:
                linhas += _linhas_ibge(
                    slug, fontes.UF_SP,
                    lambda loc: fontes.UF_SP if loc in (fontes.UF_SP, "35") else None)
            except Exception as e:  # noqa: BLE001 — indicador sem série estadual
                print(f"  (sem referência SP p/ {slug}: {e})", file=sys.stderr)
    if dry_run:
        for ln in linhas[:14]:
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
    ap.add_argument("--fonte", choices=["dca", "fiscal", "ibge", "pop"],
                    help="só uma fonte")
    ap.add_argument("--ano", type=int, help="só um ano (fontes dca/fiscal)")
    ap.add_argument("--forcar", action="store_true", help="rebaixa anos já carregados")
    ap.add_argument("--dry-run", action="store_true", help="imprime sem gravar")
    args = ap.parse_args()

    conn = conectar()
    ja = {f: {r["ano"] for r in conn.execute(
              "SELECT ano FROM controle_carga WHERE fonte=?", (f,))}
          for f in ("dca", "fiscal")}
    ano_corrente = date.today().year

    def _anos_a_baixar(fonte):
        anos = [args.ano] if args.ano else list(range(ANO_INICIAL, ano_corrente + 1))
        # anos encerrados não mudam; retenta só os 2 últimos (podem ser retificados)
        return [a for a in anos if args.forcar or args.dry_run
                or a not in ja[fonte] or a >= ano_corrente - 1]

    # Cada fonte falha de forma independente: a base (cache) preserva a carga
    # anterior e a guarda do workflow impede publicar índice incompleto.
    total, falhas = 0, []
    if args.fonte in (None, "dca"):
        for ano in _anos_a_baixar("dca"):
            try:
                n = carregar_dca(conn, ano, args.dry_run)
                print(f"dca {ano}: {n} linhas")
                total += n
            except Exception as e:  # noqa: BLE001
                falhas.append(f"dca {ano}: {e}")
    if args.fonte in (None, "fiscal"):
        for ano in _anos_a_baixar("fiscal"):
            try:
                n = carregar_fiscal(conn, ano, args.dry_run)
                print(f"fiscal {ano}: {n} linhas")
                total += n
            except Exception as e:  # noqa: BLE001
                falhas.append(f"fiscal {ano}: {e}")
    if args.fonte in (None, "ibge"):
        try:
            n = carregar_ibge(conn, args.dry_run)
            print(f"ibge (indicadores): {n} linhas")
            total += n
        except Exception as e:  # noqa: BLE001
            falhas.append(f"ibge: {e}")
    if args.fonte in (None, "pop"):
        try:
            n = carregar_populacao(conn, list(range(ANO_INICIAL, ano_corrente + 1)),
                                   args.dry_run)
            print(f"populacao: {n} linhas")
            total += n
        except Exception as e:  # noqa: BLE001
            falhas.append(f"populacao: {e}")

    for f in falhas:
        print(f"AVISO — fonte falhou (base mantém a carga anterior): {f}",
              file=sys.stderr)
    print(("[dry-run] " if args.dry_run else "") + f"total: {total} linhas")


if __name__ == "__main__":
    main()
