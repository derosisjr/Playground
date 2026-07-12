# -*- coding: utf-8 -*-
"""Export do painel Custo por Resultado → indicadores-index.json (raiz).

Junta o gasto liquidado por função (SICONFI/DCA — série completa 2019+, incl.
o exercício mais recente já publicado; metodologia idêntica entre municípios)
com os indicadores de resultado (IBGE), tudo per capita onde couber.
Valores em reais correntes (sem deflator na v1 — anotado no painel).

O resumo por tema é determinístico (template, sem IA): compara o primeiro e o
último ano da série de gasto e o indicador-chave nas duas pontas disponíveis.

Uso:  python indicadores/export.py [--dry-run]
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fontes  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "indicadores.sqlite")
SAIDA = os.path.join(RAIZ, "indicadores-index.json")

TEMAS = {
    "saude": {"nome": "Saúde", "funcao": "10", "indicador_chave": "mortalidade_infantil"},
    "educacao": {"nome": "Educação", "funcao": "12", "indicador_chave": "ideb_iniciais"},
}


def _pop(populacao: dict, municipio: str, ano: int):
    """População do ano, ou do ano disponível mais próximo (sem interpolar)."""
    if (municipio, ano) in populacao:
        return populacao[(municipio, ano)]
    anos = sorted(a for m, a in populacao if m == municipio)
    if not anos:
        return None
    mais_perto = min(anos, key=lambda a: abs(a - ano))
    return populacao[(municipio, mais_perto)]


def _fmt_pct(v: float) -> str:
    return f"{v:+.0f}%".replace("-", "−")


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def _num(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def montar(conn) -> dict:
    populacao = {(r["municipio"], r["ano"]): r["valor"]
                 for r in conn.execute("SELECT * FROM populacao")}
    temas = {}
    for slug_tema, meta in TEMAS.items():
        # gasto per capita por ano — Santos + comparáveis
        gasto = {}
        for r in conn.execute(
                "SELECT municipio, ano, valor FROM gasto_externo WHERE funcao=? "
                "ORDER BY ano", (meta["funcao"],)):
            p = _pop(populacao, r["municipio"], r["ano"])
            if not p:
                continue
            gasto.setdefault(r["ano"], {})[r["municipio"]] = round(r["valor"] / p, 2)
        gasto_pc = [{"ano": ano,
                     "santos": vals.get("3548500"),
                     "comparaveis": {m: v for m, v in vals.items() if m != "3548500"}}
                    for ano, vals in sorted(gasto.items()) if vals.get("3548500")]

        # indicadores do tema (série 2015+ para dar contexto)
        indicadores = []
        slugs = [s for s, i in fontes.INDICADORES.items() if i["tema"] == slug_tema]
        for slug in slugs:
            info = fontes.INDICADORES[slug]
            serie = {}
            for r in conn.execute(
                    "SELECT municipio, ano, valor FROM indicadores "
                    "WHERE indicador=? AND ano>=2015 ORDER BY ano", (slug,)):
                serie.setdefault(r["ano"], {})[r["municipio"]] = r["valor"]
            pontos = [{"ano": ano,
                       "santos": vals.get("3548500"),
                       "comparaveis": {m: v for m, v in vals.items() if m != "3548500"}}
                      for ano, vals in sorted(serie.items())]
            if not pontos:
                continue
            indicadores.append({
                "slug": slug, "nome": info["nome"], "melhor": info["melhor"],
                "fonte": info["fonte_nome"],
                "ultimo_ano": max(p["ano"] for p in pontos if p["santos"] is not None),
                "serie": pontos,
            })

        temas[slug_tema] = {
            "nome": meta["nome"],
            "indicador_chave": meta["indicador_chave"],
            "gasto_per_capita": gasto_pc,
            "indicadores": indicadores,
            "resumo": _resumo(meta, gasto_pc, indicadores),
        }
    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "comparaveis": fontes.COMPARAVEIS,
        "temas": temas,
    }


def _resumo(meta, gasto_pc, indicadores) -> str:
    """Frase determinística: variação do gasto vs variação do indicador-chave."""
    if len(gasto_pc) < 2:
        return ""
    g0, g1 = gasto_pc[0], gasto_pc[-1]
    var_gasto = (g1["santos"] / g0["santos"] - 1) * 100
    frase = (f"O gasto por habitante em {meta['nome'].lower()} foi de "
             f"{_brl(g0['santos'])} em {g0['ano']} a {_brl(g1['santos'])} "
             f"em {g1['ano']} ({_fmt_pct(var_gasto)}, valores correntes).")
    chave = next((i for i in indicadores if i["slug"] == meta["indicador_chave"]), None)
    if chave:
        pts = [p for p in chave["serie"] if p["santos"] is not None
               and p["ano"] >= gasto_pc[0]["ano"]]
        if len(pts) >= 2:
            i0, i1 = pts[0], pts[-1]
            melhorou = ((i1["santos"] < i0["santos"]) == (chave["melhor"] == "menor"))
            direcao = "melhorou" if melhorou else "piorou"
            if i1["santos"] == i0["santos"]:
                direcao = "ficou estável"
            nome_curto = chave["nome"].split(" (")[0]
            nome_curto = nome_curto[0].lower() + nome_curto[1:] \
                if not nome_curto.startswith("IDEB") else nome_curto
            frase += (f" No mesmo período, {nome_curto} "
                      f"{direcao}: {_num(i0['santos'])} ({i0['ano']}) → "
                      f"{_num(i1['santos'])} ({i1['ano']}).")
    return frase


def main():
    # console do Windows pode ser cp1252; a saída do script é utf-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(BASE)
    conn.row_factory = sqlite3.Row
    indice = montar(conn)

    for slug, t in indice["temas"].items():
        print(f"{slug}: {len(t['gasto_per_capita'])} anos de gasto, "
              f"{len(t['indicadores'])} indicadores")
        print("  resumo:", t["resumo"])
    if args.dry_run:
        print("[dry-run] nada gravado")
        return
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, separators=(",", ":"))
    print(f"gravado: {SAIDA}")


if __name__ == "__main__":
    main()
