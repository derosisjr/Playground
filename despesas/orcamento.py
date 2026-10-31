#!/usr/bin/env python3
"""
Orçamento × execução por função — RREO Anexo 02 (SICONFI)
==========================================================

Quanto do orçamento de cada função (Saúde, Educação…) já foi empenhado e liquidado no
exercício, pela fonte oficial bimestral: o RREO que o município entrega ao Tesouro
(`apidatalake.tesouro.gov.br`, a mesma API do Endividamento e do benchmark). Grava
`despesas/orcamento.json` (versionado), lido pela caixa "Orçamento × execução" do painel.

Por que não a API do portal: `json_orcamento_despesas` soma R$ 11,2 bi para 2026 contra
R$ 6,3 bi de dotação inicial no RREO (conferido em 2026-10-30) — não serve de orçamento.

Notas: RREO = competência (empenhado/liquidado até o bimestre), soma das despesas exceto
intra-orçamentárias e das intra; NÃO é a visão caixa/pago do painel. No Anexo 02 função e
subfunção vêm intercaladas, sem marcador de nível: a função é reconhecida pelo nome na
lista das 28 funções de governo (Portaria MOG 42/1999). Exercício corrente: o bimestre
mais recente publicado; exercício anterior: o 6º bimestre (ano fechado).

Uso:
    python despesas/orcamento.py --dry-run
    python despesas/orcamento.py
"""

import argparse
import json
import os
import sys
import time
from datetime import date

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz do repo: comum/
from comum import http  # noqa: E402
from comum.escrita import gravar_json  # noqa: E402
from comum.formato import sem_acento  # noqa: E402
from comum.saida import configurar_stdio  # noqa: E402

configurar_stdio()

API = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"
IBGE_SANTOS = "3548500"
ANEXO = "RREO-Anexo 02"
PAUSA = 0.5
AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, "orcamento.json")
COLUNAS = {"DOTACAO INICIAL": "dotacao_inicial", "DOTACAO ATUALIZADA (A)": "dotacao_atualizada",
           "DESPESAS EMPENHADAS ATE O BIMESTRE (B)": "empenhado",
           "DESPESAS LIQUIDADAS ATE O BIMESTRE (D)": "liquidado"}
FUNCOES = {"LEGISLATIVA": "01", "JUDICIARIA": "02", "ESSENCIAL A JUSTICA": "03", "ADMINISTRACAO": "04",
           "DEFESA NACIONAL": "05", "SEGURANCA PUBLICA": "06", "RELACOES EXTERIORES": "07",
           "ASSISTENCIA SOCIAL": "08", "PREVIDENCIA SOCIAL": "09", "SAUDE": "10", "TRABALHO": "11",
           "EDUCACAO": "12", "CULTURA": "13", "DIREITOS DA CIDADANIA": "14", "URBANISMO": "15",
           "HABITACAO": "16", "SANEAMENTO": "17", "GESTAO AMBIENTAL": "18", "CIENCIA E TECNOLOGIA": "19",
           "AGRICULTURA": "20", "ORGANIZACAO AGRARIA": "21", "INDUSTRIA": "22", "COMERCIO E SERVICOS": "23",
           "COMUNICACOES": "24", "ENERGIA": "25", "TRANSPORTE": "26", "DESPORTO E LAZER": "27",
           "ENCARGOS ESPECIAIS": "28", "RESERVA DE CONTINGENCIA": "99"}
MESES = ["", "fev", "abr", "jun", "ago", "out", "dez"]   # último mês de cada bimestre


def chave(s: str) -> str:
    return sem_acento(s or "").upper().strip()


def baixar(ano: int, bimestre: int) -> list[dict]:
    d = http.get_json(API, {"an_exercicio": ano, "in_periodicidade": "B", "nr_periodo": bimestre,
                            "co_tipo_demonstrativo": "RREO", "no_anexo": ANEXO, "co_esfera": "M",
                            "id_ente": IBGE_SANTOS}, tentativas=3, passo=5, timeout=90,
                      headers={"accept": "application/json"})
    time.sleep(PAUSA)
    return d.get("items") or []


def por_funcao(itens: list[dict]) -> list[dict]:
    """Soma, por função, exceto intra + intra, as quatro colunas que interessam."""
    out = {}
    for i in itens:
        cod = FUNCOES.get(chave(i.get("conta")))
        campo = COLUNAS.get(chave(i.get("coluna")))
        if not cod or not campo:
            continue
        f = out.setdefault(cod, {"codigo": cod, "funcao": i["conta"].strip(), **{c: 0.0 for c in COLUNAS.values()}})
        f[campo] = round(f[campo] + (i.get("valor") or 0), 2)
    return sorted(out.values(), key=lambda f: (-f["dotacao_atualizada"], f["codigo"]))


def exercicio(ano: int, bimestres: range) -> dict | None:
    for b in bimestres:
        funcoes = por_funcao(baixar(ano, b))
        if funcoes:
            total = {c: round(sum(f[c] for f in funcoes), 2) for c in COLUNAS.values()}
            return {"exercicio": ano, "bimestre": b, "ate_mes": MESES[b], "funcoes": funcoes, "total": total}
    return None


def main():
    p = argparse.ArgumentParser(description="Orçamento × execução por função (RREO Anexo 02, SICONFI)")
    p.add_argument("--dry-run", action="store_true", help="Mostra sem gravar.")
    args = p.parse_args()
    hoje = date.today()
    atual = exercicio(hoje.year, range(6, 0, -1))
    anterior = exercicio(hoje.year - 1, range(6, 5, -1))
    exercicios = [e for e in (atual, anterior) if e]
    if not exercicios:
        print("RREO sem dados — nada gravado.", file=sys.stderr)
        sys.exit(1)
    for e in exercicios:
        t = e["total"]
        print(f"{e['exercicio']} até {e['ate_mes']}: dotação atualizada R$ {t['dotacao_atualizada']:,.2f} · "
              f"empenhado {100 * t['empenhado'] / t['dotacao_atualizada']:.1f}% · "
              f"liquidado {100 * t['liquidado'] / t['dotacao_atualizada']:.1f}% ({len(e['funcoes'])} funções)",
              file=sys.stderr)
    if args.dry_run:
        print("[dry-run] nada gravado.", file=sys.stderr)
        return
    gravar_json(SAIDA, {"versao": 1, "fonte": "SICONFI/Tesouro Nacional — RREO Anexo 02 (despesa por função), "
                                              "exceto intra-orçamentárias + intra-orçamentárias; competência",
                        "exercicios": exercicios}, separators=(",", ":"))
    print(f"Gravado {os.path.basename(SAIDA)}.", file=sys.stderr)


if __name__ == "__main__":
    main()
