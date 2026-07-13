# -*- coding: utf-8 -*-
"""Crawler do Painel de Endividamento (SICONFI/RGF → endividamento.sqlite).

Baixa, por quadrimestre, os anexos do RGF de Santos e grava só as contas
acompanhadas (fontes.CONTAS). Recarga idempotente (INSERT OR REPLACE);
controle_carga registra os quadrimestres já publicados — quadrimestres
encerrados não mudam, então só o exercício corrente e o anterior são
rebaixados por padrão (retificações são raras e recentes).

Um quadrimestre ainda não publicado devolve 0 itens e NÃO entra no
controle_carga: será tentado de novo na próxima execução.

Uso:
  python endividamento/crawler.py                    # carga/atualização
  python endividamento/crawler.py --ano 2023 --dry-run
  python endividamento/crawler.py --forcar           # rebaixa tudo
"""
import argparse
import os
import sqlite3
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fontes  # noqa: E402

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "endividamento.sqlite")
ANO_INICIAL = 2018  # série longa dá contexto: pré-pandemia → hoje
PAUSA = 0.5  # s entre requisições (educação com a API do Tesouro)

# console do Windows pode ser cp1252; a saída do script é utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def conectar():
    conn = sqlite3.connect(BASE)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rgf(
            ano INTEGER, periodo INTEGER, chave TEXT, coluna TEXT, valor REAL,
            PRIMARY KEY(ano, periodo, chave, coluna));
        CREATE TABLE IF NOT EXISTS controle_carga(
            ano INTEGER, periodo INTEGER, PRIMARY KEY(ano, periodo));
    """)
    return conn


def carregar_quadrimestre(conn, ano: int, periodo: int, dry_run=False) -> int:
    """Baixa os anexos de um quadrimestre; devolve nº de linhas gravadas."""
    linhas = []
    publicado = False
    for anexo in fontes.ANEXOS:
        itens = fontes.baixar_rgf(ano, periodo, anexo)
        time.sleep(PAUSA)
        if itens:
            publicado = True  # Anexo 03 vem vazio p/ Santos; basta um com dados
        for chave, coluna, valor in fontes.filtrar_contas(itens, anexo):
            linhas.append((ano, periodo, chave, coluna, valor))
    if dry_run:
        for ln in linhas[:20]:
            print("  rgf:", ln)
        return len(linhas)
    if not publicado:
        return 0  # não marca controle: retenta na próxima execução
    conn.executemany("INSERT OR REPLACE INTO rgf VALUES (?,?,?,?,?)", linhas)
    conn.execute("INSERT OR REPLACE INTO controle_carga VALUES (?,?)", (ano, periodo))
    conn.commit()
    return len(linhas)


def main():
    ap = argparse.ArgumentParser(description="Crawler do Painel de Endividamento (RGF)")
    ap.add_argument("--ano", type=int, help="só um exercício")
    ap.add_argument("--periodo", type=int, choices=[1, 2, 3], help="só um quadrimestre")
    ap.add_argument("--forcar", action="store_true", help="rebaixa quadrimestres já carregados")
    ap.add_argument("--dry-run", action="store_true", help="imprime sem gravar")
    args = ap.parse_args()

    conn = conectar()
    ja = {(r["ano"], r["periodo"]) for r in conn.execute("SELECT * FROM controle_carga")}
    ano_corrente = date.today().year

    anos = [args.ano] if args.ano else list(range(ANO_INICIAL, ano_corrente + 1))
    periodos = [args.periodo] if args.periodo else [1, 2, 3]

    total, falhas = 0, []
    for ano in anos:
        for periodo in periodos:
            # quadrimestres encerrados não mudam; retenta os 2 últimos exercícios
            if (ano, periodo) in ja and not (args.forcar or args.dry_run
                                             or ano >= ano_corrente - 1):
                continue
            try:
                n = carregar_quadrimestre(conn, ano, periodo, args.dry_run)
                print(f"rgf {ano}-Q{periodo}: {n} linhas"
                      + ("" if n else " (não publicado ainda)"))
                total += n
            except Exception as e:  # noqa: BLE001 — segue p/ os demais períodos
                falhas.append(f"rgf {ano}-Q{periodo}: {e}")

    for f in falhas:
        print(f"AVISO — período falhou (base mantém a carga anterior): {f}",
              file=sys.stderr)
    print(("[dry-run] " if args.dry_run else "") + f"total: {total} linhas")


if __name__ == "__main__":
    main()
