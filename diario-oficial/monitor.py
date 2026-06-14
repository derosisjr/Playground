#!/usr/bin/env python3
"""
Monitor do Diário Oficial de Santos — captura automática de atos
================================================================

Automatiza a varredura diária que os assessores fazem à mão: baixa o PDF do DOM,
extrai e **classifica deterministicamente** (sem IA) os atos das quatro categorias
— Contratos/aditivos, Licitações/dispensas, Convênios/fomento e Pessoal/normas —
e **anexa os atos novos numa planilha do Google Sheets** (uma aba por categoria).

Pipeline:  extrator.py  →  classificador.py  →  dedup SQLite  →  sheets.py

Dedup/idempotência (padrão do `despesas/crawler.py`):
  - `controle_carga(data_edicao PK)` registra as edições já processadas.
  - `atos(hash UNIQUE)` — MD5 de (data|categoria|tipo|numero|favorecido); `INSERT
    OR IGNORE` garante que reprocessar uma edição não duplica linhas na planilha.

O `.sqlite` NÃO é versionado — persiste entre execuções do GitHub Actions via cache.

Variáveis de ambiente (secrets):
    GOOGLE_OAUTH_TOKEN   token OAuth (mesmo do respostas-executivo; escopo Sheets)
    DOM_SHEET_ID         ID da planilha de destino (dedicada ao DOM)

Uso:
    python diario-oficial/monitor.py --dry-run            # última edição, imprime, não grava
    python diario-oficial/monitor.py --data 2026-06-12    # uma edição específica
    python diario-oficial/monitor.py --desde 2026-06-01   # intervalo (carga retroativa)
    python diario-oficial/monitor.py                      # edições novas desde o último run
    python diario-oficial/monitor.py --data 2026-06-12 --forcar   # reprocessa edição já vista
"""

import argparse
import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import extrator
import classificador
import risco as risco_mod
import sheets as gsheets

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(AQUI, "diario.sqlite")

# Mapeia cada campo do ato (classificador) para a coluna da planilha (sheets.COLUNAS).
# "Data DO" e "Edição" entram no monitor; o resto vem do ato.
SCHEMA = """
CREATE TABLE IF NOT EXISTS controle_carga (
    data_edicao  TEXT PRIMARY KEY,
    n_atos       INTEGER,
    processado_em TEXT
);
CREATE TABLE IF NOT EXISTS atos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hash        TEXT UNIQUE,
    data_edicao TEXT,
    categoria   TEXT,
    tipo        TEXT,
    numero      TEXT,
    secretaria  TEXT,
    favorecido  TEXT,
    valor_num   REAL
);
CREATE INDEX IF NOT EXISTS ix_atos_data ON atos(data_edicao);
CREATE INDEX IF NOT EXISTS ix_atos_fav ON atos(favorecido);
"""


def abrir_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def _hash(data_edicao: str, ato: dict) -> str:
    chave = "|".join([
        data_edicao, ato["categoria"], ato["tipo"],
        ato.get("numero", ""), ato.get("favorecido", "")[:60],
        ato.get("objeto", "")[:40],
    ])
    return hashlib.md5(chave.encode("utf-8")).hexdigest()


def edicoes_processadas(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT data_edicao FROM controle_carga")}


def datas_intervalo(desde: str, ate: str) -> list[str]:
    d0 = datetime.strptime(desde, "%Y-%m-%d").date()
    d1 = datetime.strptime(ate, "%Y-%m-%d").date()
    out = []
    d = d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def linha_planilha(data_edicao: str, ato: dict, sep: str, captado: str) -> list:
    """Monta a linha na ordem de gsheets.COLUNAS (aba única, com Risco e Categoria)."""
    edicao_cell = gsheets.hyperlink(extrator.url_edicao(data_edicao), data_edicao, sep)
    return [
        data_edicao, ato.get("risco", ""), ato.get("motivo", ""),
        ato.get("categoria", ""), ato.get("tipo", ""), ato.get("secretaria", ""),
        ato.get("numero", ""), ato.get("objeto", ""), ato.get("valor", ""),
        ato.get("favorecido", ""), ato.get("processo", ""), ato.get("modalidade", ""),
        ato.get("vigencia", ""), ato.get("fundamentacao", ""), ato.get("pagina", ""),
        edicao_cell, captado,
    ]


def processar_edicao(data_edicao: str) -> list[dict]:
    """Baixa, extrai e classifica uma edição. [] se a edição não existir."""
    pdf = extrator.baixar_pdf(data_edicao)
    if not pdf:
        print(f"  {data_edicao}: edição não encontrada.", file=sys.stderr)
        return []
    paginas = extrator.extrair_edicao(pdf)
    ano = int(data_edicao[:4]) if data_edicao[:4].isdigit() else None
    return classificador.classificar(paginas, ano_edicao=ano)


def main():
    p = argparse.ArgumentParser(description="Monitor do Diário Oficial de Santos")
    p.add_argument("--data", help="Edição específica (AAAA-MM-DD).")
    p.add_argument("--desde", help="Início de um intervalo (AAAA-MM-DD); até hoje ou --ate.")
    p.add_argument("--ate", help="Fim do intervalo (AAAA-MM-DD). Padrão: hoje.")
    p.add_argument("--dias", type=int, default=7,
                   help="Sem --data/--desde: varre os últimos N dias (padrão 7).")
    p.add_argument("--forcar", action="store_true", help="Reprocessa edição já registrada.")
    p.add_argument("--dry-run", action="store_true",
                   help="Não grava no SQLite nem no Sheets; imprime os atos.")
    p.add_argument("--limite", type=int, default=0, help="Máx. de atos a imprimir no dry-run.")
    args = p.parse_args()

    hoje = datetime.now().date()
    if args.data:
        datas = [args.data]
    elif args.desde:
        datas = datas_intervalo(args.desde, args.ate or hoje.isoformat())
    else:
        datas = datas_intervalo((hoje - timedelta(days=args.dias - 1)).isoformat(),
                                hoje.isoformat())

    conn = None if args.dry_run else abrir_db()
    ja = edicoes_processadas(conn) if conn else set()

    sheets = sheet_id = sep = None
    if not args.dry_run:
        sheet_id = os.environ.get("DOM_SHEET_ID", "")
        if not sheet_id:
            raise EnvironmentError("Defina DOM_SHEET_ID (planilha de destino).")
        sheets = gsheets.conectar_sheets()
        gsheets.garantir_aba(sheets, sheet_id)
        sep = gsheets.separador_formula(sheets, sheet_id)

    captado = datetime.now().strftime("%d/%m/%Y %H:%M")
    total_novos = 0
    for data_edicao in datas:
        if conn and data_edicao in ja and not args.forcar:
            continue
        atos = processar_edicao(data_edicao)
        if not atos:
            continue

        # avalia risco (usa conn p/ gatilhos cross-edição; no dry-run vai sem histórico)
        for a, r in zip(atos, risco_mod.avaliar(atos, conn)):
            a["risco"], a["motivo"] = r["risco"], r["motivo"]

        if args.dry_run:
            print(f"== {data_edicao}: {len(atos)} atos ==", file=sys.stderr)
            import collections
            for k, v in collections.Counter(a["risco"] for a in atos).items():
                print(f"   {v}  {k}", file=sys.stderr)
            for a in atos[:(args.limite or 8)]:
                print(f"   {a['risco']} [{a['tipo']}] nº {a['numero']} | "
                      f"{a['secretaria'][:20]} | {a['objeto'][:40]} | {a['motivo'][:60]}")
            continue

        # dedup via SQLite → linhas novas para a aba única
        linhas_novas: list[list] = []
        for a in atos:
            h = _hash(data_edicao, a)
            cur = conn.execute(
                "INSERT OR IGNORE INTO atos (hash, data_edicao, categoria, tipo, numero, secretaria, favorecido, valor_num) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (h, data_edicao, a["categoria"], a["tipo"], a.get("numero", ""),
                 a.get("secretaria", ""), a.get("favorecido", ""), a.get("valor_num")),
            )
            if cur.rowcount:  # inserido = ato novo
                linhas_novas.append(linha_planilha(data_edicao, a, sep, captado))
        gsheets.anexar_linhas(sheets, sheet_id, linhas_novas)
        novos = len(linhas_novas)
        conn.execute(
            "INSERT OR REPLACE INTO controle_carga (data_edicao, n_atos, processado_em) VALUES (?,?,?)",
            (data_edicao, len(atos), datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        total_novos += novos
        print(f"== {data_edicao}: {len(atos)} atos ({novos} novos na planilha) ==", file=sys.stderr)

    if conn:
        conn.close()
    print(f"Concluído: {total_novos} atos novos.", file=sys.stderr)


if __name__ == "__main__":
    main()
