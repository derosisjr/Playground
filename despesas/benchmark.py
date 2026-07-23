#!/usr/bin/env python3
"""
Benchmark de despesa por função — Santos × municípios pares (SICONFI/DCA)
=========================================================================

Compara a despesa POR FUNÇÃO de Santos com municípios paulistas de porte
semelhante, na fonte padronizada da federação: DCA (Declaração de Contas
Anuais) do SICONFI, Anexo I-E, via `apidatalake.tesouro.gov.br` — a mesma API
já usada pelo módulo `endividamento/`.

Gera `despesas/benchmark.json` (versionado), consumido pela seção
"Santos × cidades pares" do painel de despesas. O painel divide pelos
habitantes (Censo 2022, embutido aqui) para exibir per capita.

Notas metodológicas:
  - DCA = competência anual consolidada (inclui adm. indireta), publicada
    ~abril do ano seguinte. NÃO é comparável 1:1 com a visão caixa/pago do
    painel (fonte municipal, adm. direta + entidades do portal).
  - População: Censo 2022 (IBGE, agregado 4709) para TODAS as cidades —
    a mesma base de `Comum.POP_SANTOS` (unificado em 418.608 em 2026-07).
  - Pares por porte (379–452 mil hab.): Jundiaí, Piracicaba, Mogi das Cruzes,
    Bauru; + São José dos Campos (697 mil) como referência regional maior.

Uso:
    python despesas/benchmark.py --dry-run          # mostra sem gravar
    python despesas/benchmark.py                    # exercício mais recente disponível
    python despesas/benchmark.py --ano 2024
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

API = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca"
ANEXO = "DCA-Anexo I-E"
PAUSA = 0.5
AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, "benchmark.json")

# População: Censo 2022 (IBGE, agregado 4709, variável 93) — conferido em 2026-07.
CIDADES = [
    {"ibge": 3548500, "nome": "Santos", "pop": 418_608},
    {"ibge": 3525904, "nome": "Jundiaí", "pop": 443_221},
    {"ibge": 3538709, "nome": "Piracicaba", "pop": 423_323},
    {"ibge": 3530607, "nome": "Mogi das Cruzes", "pop": 451_505},
    {"ibge": 3506003, "nome": "Bauru", "pop": 379_146},
    {"ibge": 3549904, "nome": "São José dos Campos", "pop": 697_054},
]

# No Anexo I-E, função = conta SEM subfunção (ex.: "10 - Saúde"; "10.301 - ..." é subfunção)
RE_FUNCAO = re.compile(r"^\d{2} - ")


def _get(params: dict, tentativas: int = 4) -> dict:
    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(API, params=params, headers={"accept": "application/json"}, timeout=90)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            ultimo = e
            if i < tentativas - 1:
                espera = 5 * (i + 1)
                print(f"  Aviso: {e}; tentativa {i+1}/{tentativas}, {espera}s...", file=sys.stderr)
                time.sleep(espera)
    raise ultimo


def coletar_cidade(ibge: int, ano: int) -> dict[str, dict]:
    """Despesa por função (pago e liquidado) de um ente no exercício."""
    d = _get({"an_exercicio": ano, "no_anexo": ANEXO, "id_ente": ibge})
    funcoes: dict[str, dict] = {}
    for item in d.get("items", []):
        conta = item.get("conta") or ""
        if not RE_FUNCAO.match(conta):
            continue                      # ignora linhas de subfunção
        col = item.get("coluna")
        campo = {"Despesas Pagas": "pago", "Despesas Liquidadas": "liquidado"}.get(col)
        if not campo:
            continue
        f = funcoes.setdefault(conta, {"pago": 0.0, "liquidado": 0.0})
        f[campo] = round(f[campo] + (item.get("valor") or 0), 2)
    return funcoes


def coletar(ano: int) -> list[dict]:
    saida = []
    for c in CIDADES:
        print(f"== {c['nome']} ({c['ibge']}) — DCA {ano} ==", file=sys.stderr)
        funcoes = coletar_cidade(c["ibge"], ano)
        print(f"  {len(funcoes)} funções", file=sys.stderr)
        saida.append({**c, "por_funcao": funcoes})
        time.sleep(PAUSA)
    return saida


def main():
    p = argparse.ArgumentParser(description="Benchmark de despesa por função (SICONFI/DCA)")
    p.add_argument("--ano", type=int, help="Exercício. Padrão: o mais recente com dados.")
    p.add_argument("--dry-run", action="store_true", help="Imprime resumo; não grava.")
    args = p.parse_args()

    if args.ano:
        anos = [args.ano]
    else:
        # DCA sai ~abril do ano seguinte: tenta o ano anterior e recua se ainda não publicado
        corrente = datetime.now().year
        anos = [corrente - 1, corrente - 2]

    cidades, exercicio = None, None
    for ano in anos:
        dados = coletar(ano)
        com_dados = [c for c in dados if c["por_funcao"]]
        if len(com_dados) >= 4 and any(c["ibge"] == 3548500 and c["por_funcao"] for c in dados):
            cidades, exercicio = dados, ano
            break
        print(f"DCA {ano} incompleta ({len(com_dados)}/{len(CIDADES)} entes) — recuando.",
              file=sys.stderr)

    if not cidades:
        print("Sem exercício com dados suficientes — nada gravado.", file=sys.stderr)
        sys.exit(1)

    # publica só quem tem dados; cidade sem DCA no exercício fica de fora do gráfico
    cidades = [c for c in cidades if c["por_funcao"]]

    if args.dry_run:
        for c in cidades:
            total = sum(f["pago"] for f in c["por_funcao"].values())
            print(f"{c['nome']:22} R$ {total:>18,.2f} pago · R$ {total/c['pop']:>9,.2f} per capita")
        print(f"[dry-run] exercício {exercicio}; nada gravado.", file=sys.stderr)
        return

    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump({
            "exercicio": exercicio,
            "fonte": f"SICONFI/Tesouro Nacional — {ANEXO} (competência anual consolidada)",
            "populacao_fonte": "IBGE, Censo 2022",
            "gerado_em": datetime.now().isoformat(timespec="seconds"),
            "cidades": cidades,
        }, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Gravado {os.path.basename(SAIDA)}: exercício {exercicio}, "
          f"{len(cidades)} cidades.", file=sys.stderr)


if __name__ == "__main__":
    main()
