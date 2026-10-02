#!/usr/bin/env python3
"""
Comparação antes/depois dos artefatos da Base de Despesas
=========================================================

Compara dois conjuntos de artefatos (ex.: os publicados no repo × um candidato
gerado com `export.py --saida DIR`) e, opcionalmente, duas bases SQLite, explicando
as diferenças por causa:

  - por ano, mês e estágio (empenhado/liquidado/pago): série do bloco `execucao`;
  - por unidade gestora (pago);
  - por tipo de linha na execução (Empenho / Restos / Extra / Não localizado);
  - favorecidos: identidades × grafias no ranking, e os N maiores deslocamentos;
  - com `--db-antes/--db-depois`: reconciliação linha a linha por partição —
    linhas removidas, adicionadas, alteradas (mesma chave natural, valor diferente),
    descartadas por duplicidade sistemática e mantidas por serem idênticas
    legítimas (a v1 as descartava).

Uso:
    python despesas/comparar.py --antes . --depois despesas/_candidato
    python despesas/comparar.py --antes . --depois despesas/_candidato \\
        --db-antes despesas/_backup/despesas.sqlite.v1-AAAAMMDD --db-depois despesas/_candidato/despesas.sqlite \\
        --saida despesas/_candidato/comparacao.md
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from formato import brl  # noqa: E402

CAUSAS = {
    "removido": "exclusão na origem (linha não veio mais na fotografia do mês)",
    "adicionado": "linha nova na origem (ou mês ainda não carregado antes)",
    "alterado": "correção na origem (mesma chave natural, conteúdo/valor diferente)",
    "identica_mantida": "linha idêntica legítima mantida (a v1 descartava por hash)",
    "duplicidade_sistematica": "duplicidade sistemática da origem descartada",
}


def _ler(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _serie(idx):
    out = {}
    for l in (idx.get("execucao") or {}).get("serie") or []:
        out[(l["ano"], l["mes"])] = l
    return out


def _fmt(v):
    return "—" if v is None else brl(v)


def comparar_indices(antes: dict, depois: dict) -> list[str]:
    L = []
    ta, td = antes.get("totais", {}), depois.get("totais", {})
    L.append("## Totais\n")
    L.append("| | antes | depois | diferença |\n|---|---:|---:|---:|")
    for k, rot in (("geral", "pago geral"), ("pagamentos", "nº pagamentos"), ("favorecidos", "favorecidos")):
        a, d = ta.get(k), td.get(k)
        dif = (d or 0) - (a or 0)
        f = (lambda x: f"{x:,}") if k != "geral" else _fmt
        L.append(f"| {rot} | {f(a) if a is not None else '—'} | {f(d) if d is not None else '—'} | {f(dif)} |")
    if "grafias_favorecidos" in td:
        L.append(f"\nDepois: {td['favorecidos']} identidades para {td['grafias_favorecidos']} grafias "
                 f"(antes o contador era de nomes distintos: {ta.get('favorecidos')}).")
    L.append("\n## Por ano e estágio (movimentação, pela data de cada estágio)\n")
    L.append("| ano | estágio | antes | depois | diferença |\n|---|---|---:|---:|---:|")
    pa, pd_ = (antes.get("execucao") or {}).get("por_ano") or {}, (depois.get("execucao") or {}).get("por_ano") or {}
    for ano in sorted(set(pa) | set(pd_)):
        for c in ("empenhado", "liquidado", "pago", "restos", "extra", "nao_localizado"):
            a, d = (pa.get(ano) or {}).get(c), (pd_.get(ano) or {}).get(c)
            if a is None and d is None:
                continue
            L.append(f"| {ano} | {c} | {_fmt(a)} | {_fmt(d)} | {_fmt((d or 0) - (a or 0))} |")
    L.append("\n## Por mês (pago pela data do pagamento)\n")
    L.append("| mês | antes | depois | diferença | observação |\n|---|---:|---:|---:|---|")
    sa, sd = _serie(antes), _serie(depois)
    dup = set()
    for p in ((depois.get("cobertura") or {}).get("duplicidade_sistematica") or []):
        f, ym = p.split(" ")
        dup.add(ym)
    for k in sorted(set(sa) | set(sd)):
        a, d = (sa.get(k) or {}).get("pago"), (sd.get(k) or {}).get("pago")
        obs = []
        ym = f"{k[0]}-{k[1]:02d}"
        if a is None:
            obs.append("mês novo")
        if ym in dup:
            obs.append("origem em duplicidade sistemática (descartada no depois)")
        L.append(f"| {ym} | {_fmt(a)} | {_fmt(d)} | {_fmt((d or 0) - (a or 0))} | {'; '.join(obs)} |")
    L.append("\n## Por unidade gestora (pago)\n")
    L.append("| unidade | antes | depois | diferença |\n|---|---:|---:|---:|")
    ua = {u["unidade"]: u["valor"] for u in antes.get("por_unidade") or []}
    ud = {u["unidade"]: u["valor"] for u in depois.get("por_unidade") or []}
    for u in sorted(set(ua) | set(ud), key=lambda x: -(ud.get(x) or 0)):
        L.append(f"| {u} | {_fmt(ua.get(u))} | {_fmt(ud.get(u))} | {_fmt((ud.get(u) or 0) - (ua.get(u) or 0))} |")
    L.append("\n## Taxas de execução\n")
    for ano in sorted(set(pa) | set(pd_)):
        a, d = pa.get(ano) or {}, pd_.get(ano) or {}
        L.append(f"- {ano}: antes liq {a.get('taxa_liquidacao', '—')}% / pago {a.get('taxa_pagamento', '—')}%"
                 f"{' (empenho_incompleto)' if a.get('empenho_incompleto') else ''}; depois "
                 + (f"liq {d.get('taxa_liquidacao')}% / pago {d.get('taxa_pagamento')}% validada sobre "
                    f"{(d.get('base_taxa') or {}).get('cobertura_pct')}% do empenhado"
                    if d.get("taxa_validada") else f"NÃO validada: {'; '.join(d.get('taxa_motivos') or [])}"))
    L.append("\n## Favorecidos (ranking)\n")
    fa = {(t["nome"], t.get("documento") or ""): t["valor"] for t in antes.get("top_favorecidos") or []}
    fd = {t.get("chave") or t["nome"]: t for t in depois.get("top_favorecidos") or []}
    # antes: agrupa por documento p/ comparar com a identidade
    from formato import identidade_favorecido
    fa_ident = defaultdict(float)
    grafias = defaultdict(set)
    for (n, doc), v in fa.items():
        ch = identidade_favorecido(n, doc)[0]
        fa_ident[ch] += v
        grafias[ch].add(n)
    consolidados = [(ch, gs) for ch, gs in grafias.items() if len(gs) > 1]
    L.append(f"- antes: {len(fa)} entradas no top (nome+documento); depois: {len(fd)} identidades.")
    L.append(f"- {len(consolidados)} identidades tinham mais de uma grafia no top antigo (consolidadas):")
    for ch, gs in sorted(consolidados, key=lambda x: -fa_ident[x[0]])[:15]:
        t = fd.get(ch) or {}
        L.append(f"  - {ch}: {len(gs)} grafias somando {_fmt(fa_ident[ch])} antes → {_fmt(t.get('valor'))} depois "
                 f"({t.get('nome', '?')[:50]})")
    L.append("\n## Alertas\n")
    ca = Counter(a.get("severidade") for a in antes.get("alertas") or [])
    cd = Counter((a.get("classe"), a.get("severidade")) for a in depois.get("alertas") or [])
    L.append(f"- antes: {len(antes.get('alertas') or [])} alertas {dict(ca)}")
    L.append(f"- depois: {len(depois.get('alertas') or [])} alertas por (classe, severidade): "
             + ", ".join(f"{k[0]}/{k[1]}: {v}" for k, v in sorted(cd.items(), key=lambda x: -x[1])))
    return L


# ── reconciliação linha a linha entre duas bases ─────────────────────────────
def _linhas(conn, tabela, cols):
    cur = conn.execute(f"SELECT {','.join(cols)} FROM {tabela}")
    return [tuple("" if v is None else v for v in r) for r in cur]


def comparar_bases(db_antes: str, db_depois: str) -> list[str]:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import crawler
    L = ["\n## Reconciliação linha a linha (base antes × base depois)\n"]
    ca, cd = sqlite3.connect(db_antes), sqlite3.connect(db_depois)
    L.append("| estágio | mês | linhas antes | linhas depois | removidas | adicionadas | alteradas | idênticas mantidas | dup. sistemática | Δ valor |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    tot = Counter()
    for fonte, cfg in crawler.STREAMS.items():
        cols = crawler._cols(fonte)
        iv, ia, im = cols.index("valor"), cols.index("ano"), cols.index("mes")
        chave_cols = [cols.index(c) for c in cfg["chave"]]
        A = defaultdict(Counter)   # (ano, mes) → Counter(linha completa)
        D = defaultdict(Counter)
        for r in _linhas(ca, cfg["tabela"], cols):
            A[(r[ia], r[im])][r] += 1
        for r in _linhas(cd, cfg["tabela"], cols):
            D[(r[ia], r[im])][r] += 1
        desc = {}
        try:
            for r in cd.execute("SELECT ano, mes, descartados FROM controle_carga WHERE fonte=?", (fonte,)):
                desc[(r[0], r[1])] = r[2] or 0
        except sqlite3.OperationalError:
            pass
        for ym in sorted(set(A) | set(D)):
            a, d = A[ym], D[ym]
            removidas = a - d
            adicionadas = d - a
            chaves_add = Counter(tuple(r[i] for i in chave_cols) for r in adicionadas.elements())
            alteradas = sum(1 for r in removidas.elements() if chaves_add.get(tuple(r[i] for i in chave_cols)))
            identicas = sum(v - 1 for v in d.values() if v > 1)
            dv = round(sum(r[iv] * n for r, n in d.items()) - sum(r[iv] * n for r, n in a.items()), 2)
            na, nd = sum(a.values()), sum(d.values())
            nrem, nadd = sum(removidas.values()), sum(adicionadas.values())
            if na == nd and not nrem and not nadd:
                continue
            L.append(f"| {fonte} | {ym[0]}-{ym[1]:02d} | {na} | {nd} | {nrem} | {nadd} | {alteradas} | "
                     f"{identicas} | {desc.get(ym, 0)} | {_fmt(dv)} |")
            tot.update({"removidas": nrem, "adicionadas": nadd, "alteradas": alteradas,
                        "identicas": identicas, "dup": desc.get(ym, 0)})
    L.append(f"\nTotais: {dict(tot)}. Legenda das causas: " +
             "; ".join(f"**{k}** = {v}" for k, v in CAUSAS.items()) + ".")
    return L


def main():
    p = argparse.ArgumentParser(description="Compara artefatos antes/depois da Base de Despesas")
    p.add_argument("--antes", required=True, help="raiz dos artefatos antigos (ex.: .)")
    p.add_argument("--depois", required=True, help="raiz dos artefatos novos (ex.: despesas/_candidato)")
    p.add_argument("--db-antes")
    p.add_argument("--db-depois")
    p.add_argument("--saida", help="grava o relatório Markdown neste caminho (senão imprime)")
    args = p.parse_args()
    antes = _ler(os.path.join(args.antes, "despesas-index.json"))
    depois = _ler(os.path.join(args.depois, "despesas-index.json"))
    L = [f"# Comparação antes/depois — {antes.get('atualizado_em')} × {depois.get('atualizado_em')}\n"]
    L += comparar_indices(antes, depois)
    if args.db_antes and args.db_depois:
        L += comparar_bases(args.db_antes, args.db_depois)
    texto = "\n".join(L) + "\n"
    if args.saida:
        with open(args.saida, "w", encoding="utf-8") as f:
            f.write(texto)
        print(f"Relatório gravado em {args.saida}", file=sys.stderr)
    else:
        sys.stdout.write(texto)


if __name__ == "__main__":
    main()
