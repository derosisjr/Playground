# -*- coding: utf-8 -*-
"""Série do IPCA para corrigir preços de anos diferentes → precos/ipca.json.

Comparar o preço que Praia Grande pagou em 2025 com o que Santos pagou em 2026
sem corrigir a inflação subestima o preço antigo. Corrigir em silêncio, por
outro lado, é igualmente desonesto — por isso o painel mostra **nominal e
corrigido lado a lado**, e este arquivo existe só para alimentar a segunda coluna.

Fonte primária: SIDRA/IBGE tabela 1737, variável 2266 (número-índice do IPCA,
dez/1993 = 100). Fallback: série 433 do SGS/BCB (variação % mensal), encadeada
a partir de 100. Ambas verificadas no ar em 2026-08-08.

Atenção à defasagem: o IPCA de um mês sai em meados do mês seguinte. Em
2026-08-08 o último dado disponível era **junho/2026** — a base de correção é
sempre o último mês PUBLICADO, nunca "hoje", e o painel imprime qual é.

Uso:
  python precos/ipca.py            # atualiza precos/ipca.json
  python precos/ipca.py --dry-run
"""
import argparse
import json
import os
import sys

import requests

DIR = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(DIR, "ipca.json")
ANO_INICIAL = 2020

SIDRA = ("https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2266"
         "/p/{periodos}")
SGS = ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados"
       "?formato=json&dataInicial=01/01/{ano}")

_UA = {"User-Agent": "painel-precos-camara-santos (github.com/derosisjr/Playground)"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _do_sidra() -> dict:
    """{'AAAA-MM': número-índice} direto do IBGE."""
    r = requests.get(SIDRA.format(periodos="all"), headers=_UA, timeout=90)
    r.raise_for_status()
    dados = r.json()[1:]  # a primeira linha é o cabeçalho descritivo
    serie = {}
    for linha in dados:
        p = linha.get("D3C") or ""
        try:
            valor = float(linha.get("V"))
        except (TypeError, ValueError):
            continue  # '...' e '-' aparecem em períodos sem apuração
        if len(p) == 6 and int(p[:4]) >= ANO_INICIAL:
            serie[f"{p[:4]}-{p[4:]}"] = valor
    return serie


def _do_bcb() -> dict:
    """Fallback: encadeia a variação mensal do SGS a partir de 100."""
    r = requests.get(SGS.format(ano=ANO_INICIAL), headers=_UA, timeout=90)
    r.raise_for_status()
    serie, indice = {}, 100.0
    for linha in r.json():
        d, v = linha.get("data", ""), linha.get("valor")
        try:
            indice *= 1 + float(v) / 100
        except (TypeError, ValueError):
            continue
        serie[f"{d[6:10]}-{d[3:5]}"] = round(indice, 6)
    return serie


def gerar() -> dict:
    try:
        serie, fonte = _do_sidra(), "SIDRA/IBGE tabela 1737 (número-índice, v2266)"
    except Exception as e:  # noqa: BLE001 — fallback é o ponto
        print(f"AVISO — SIDRA falhou ({e}); usando SGS/BCB série 433", file=sys.stderr)
        serie, fonte = _do_bcb(), "SGS/BCB série 433 (variação % encadeada)"
    if not serie:
        raise SystemExit("ABORTANDO: série do IPCA vazia")
    return {"fonte": fonte, "base": max(serie), "serie": dict(sorted(serie.items()))}


def fator(serie: dict, de: str, para: str):
    """Multiplicador para levar um valor de `de` (AAAA-MM) até `para`.

    None quando qualquer das pontas falta — o chamador degrada para nominal em
    vez de inventar um fator.
    """
    a, b = serie.get(de), serie.get(para)
    if not a or not b:
        return None
    return b / a


def main():
    ap = argparse.ArgumentParser(description="Série do IPCA para o painel de preços")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    d = gerar()
    meses = list(d["serie"])
    print(f"IPCA: {len(meses)} meses ({meses[0]} → {meses[-1]}) · base {d['base']}")
    print(f"  fonte: {d['fonte']}")
    if args.dry_run:
        return
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"  gravado: {SAIDA}")


if __name__ == "__main__":
    main()
