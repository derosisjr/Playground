#!/usr/bin/env python3
"""Guarda de FRESCOR: cada base ainda está recebendo dado novo?

Por que existe: as guardas dos workflows de base medem VOLUME ("a base está
mutilada?") — despesas ≥ R$ 4 bi, proposituras ≥ 6.000 registros. Nenhuma media
FRESCOR ("a base está congelada?"), e uma base íntegra e velha passa em todas.

Foi assim que a Base de Despesas ficou 40 dias parada (2026-07-09 → 08-17): o
portal passou a devolver 403, o crawler engolia o erro, o export reexportava o
cache íntegro do .sqlite e a guarda dos R$ 4 bi aprovava. Workflow verde todo dia.

`bases-atualizacao.json` também não pegava: ele publica a data do último COMMIT
que tocou o arquivo, e o arquivo mudava mesmo — o export reescrevia o índice
diariamente com dado velho. Data de commit honesta, dado congelado.

A pergunta certa é sobre o dado DENTRO do índice, que é o que este script lê.
Nenhuma base ganha campo novo: todas já publicavam o sinal (`dados_ate`,
`cobertura.ate`, a data mais recente da lista); ninguém o estava lendo.

Os limites são generosos de propósito — servem para pegar congelamento, não
atraso normal. Precisam cobrir o recesso parlamentar (janeiro sem propositura
nova é normal) e a defasagem de publicação de cada fonte.

Uso:
    python .github/scripts/frescor_bases.py            # sai != 0 se algo congelou
    python .github/scripts/frescor_bases.py --aviso    # só reporta, sempre sai 0
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

RAIZ = Path(__file__).resolve().parents[2]


# ── extratores: onde mora a data do DADO em cada índice ──────────────────────
def _data_iso(texto):
    """'2026-08-14' ou '2026-08-14T12:00:00' → date."""
    if not texto:
        return None
    return datetime.fromisoformat(str(texto).split("T", 1)[0]).date()


def _data_br(texto):
    """'14/08/2026' → date. Devolve None no que não casar (campo vazio, lixo)."""
    try:
        d, m, a = str(texto).split("/")
        return date(int(a), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def campo(*caminho):
    """Data ISO em doc[c1][c2]... — para índices que já publicam a data do dado."""
    def extrair(doc):
        no = doc
        for c in caminho:
            if not isinstance(no, dict):
                return None
            no = no.get(c)
        return _data_iso(no)
    return extrair


def maior_data_br(nome_campo):
    """Data mais recente de uma LISTA de registros (datas em DD/MM/AAAA).

    max() sobre a string daria resposta errada: '31/12/2004' > '13/08/2026'
    lexicograficamente. Precisa parsear antes de comparar.
    """
    def extrair(doc):
        if not isinstance(doc, list):
            return None
        datas = [d for d in (_data_br(r.get(nome_campo)) for r in doc
                             if isinstance(r, dict)) if d]
        return max(datas) if datas else None
    return extrair


def mes_de(*caminho):
    """'2026-08' → último dia do mês (a cobertura é mensal, não diária)."""
    def extrair(doc):
        no = doc
        for c in caminho:
            if not isinstance(no, dict):
                return None
            no = no.get(c)
        if not no:
            return None
        ano, mes = (int(x) for x in str(no).split("-")[:2])
        fim = date(ano + (mes == 12), (mes % 12) + 1, 1)
        return date.fromordinal(fim.toordinal() - 1)
    return extrair


def quadrimestre(doc):
    """{'ano': 2026, 'q': 1} → último dia do quadrimestre (RGF é quadrimestral)."""
    u = doc.get("ultimo") if isinstance(doc, dict) else None
    if not isinstance(u, dict) or not u.get("ano") or not u.get("q"):
        return None
    fim_mes = int(u["q"]) * 4          # q1→abr, q2→ago, q3→dez
    ano, mes = int(u["ano"]), fim_mes
    fim = date(ano + (mes == 12), (mes % 12) + 1, 1)
    return date.fromordinal(fim.toordinal() - 1)


# ── o que vigiar ─────────────────────────────────────────────────────────────
# limite = dias tolerados entre a data do dado mais recente e hoje.
BASES = {
    "despesas-index.json": {
        "limite": 20,   # crawl diário; o portal publica com alguns dias de atraso
        "extrator": campo("dados_ate"),
        "sinal": "dados_ate",
    },
    "legis-index.json": {
        "limite": 45,   # crawl semanal + semanas sem norma nova publicada
        "extrator": maior_data_br("data_norma"),
        "sinal": "data_norma mais recente",
    },
    "proposituras-index.json": {
        "limite": 60,   # recesso parlamentar de janeiro não gera propositura
        "extrator": maior_data_br("data_propositura"),
        "sinal": "data_propositura mais recente",
    },
    "requerimentos-index.json": {
        "limite": 60,   # depende do Executivo responder; recesso também pesa
        "extrator": maior_data_br("data_resposta"),
        "sinal": "data_resposta mais recente",
    },
    "precos-index.json": {
        "limite": 60,   # cobertura é mensal e o PNCP publica com atraso
        "extrator": mes_de("cobertura", "ate"),
        "sinal": "cobertura.ate",
    },
    "endividamento-index.json": {
        "limite": 270,  # RGF é quadrimestral e sai meses depois do fechamento
        "extrator": quadrimestre,
        "sinal": "ultimo quadrimestre",
    },
    "indicadores-index.json": {
        "limite": 120,  # fontes anuais (IBGE/Finbra); único sinal é a geração
        "extrator": campo("gerado_em"),
        "sinal": "gerado_em (sem data de dado no índice)",
    },
}

# Fora da vigília DE PROPÓSITO — silêncio aqui seria esquecimento, então fica escrito:
ISENTAS = {
    "regimento-index.json": "estático (OCR manual do Regimento; só muda se o texto mudar)",
    "consulta/consultas/*.json": "escuta pública parada — worker pendente de deploy",
}


def avaliar(hoje=None):
    """[(base, data_do_dado, dias, limite, ok, sinal), ...] + lista de erros."""
    hoje = hoje or date.today()
    linhas, erros = [], []
    for nome, cfg in sorted(BASES.items()):
        caminho = RAIZ / nome
        if not caminho.exists():
            erros.append(f"{nome}: arquivo não encontrado")
            continue
        try:
            doc = json.loads(caminho.read_text(encoding="utf-8"))
            quando = cfg["extrator"](doc)
        except (json.JSONDecodeError, ValueError, TypeError, OSError) as e:
            erros.append(f"{nome}: não deu para ler a data ({e})")
            continue
        if quando is None:
            # sinal sumiu do índice: o formato mudou e a guarda ficaria cega
            erros.append(f"{nome}: sinal de frescor ausente ({cfg['sinal']})")
            continue
        dias = (hoje - quando).days
        linhas.append((nome, quando, dias, cfg["limite"], dias <= cfg["limite"],
                       cfg["sinal"]))
    return linhas, erros


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aviso", action="store_true",
                    help="reporta e sai 0 (para observar sem quebrar o workflow)")
    args = ap.parse_args()

    linhas, erros = avaliar()

    print(f"{'base':32} {'dado até':12} {'dias':>5} {'limite':>7}  situação")
    for nome, quando, dias, limite, ok, sinal in linhas:
        print(f"{nome:32} {quando.isoformat():12} {dias:5} {limite:7}  "
              f"{'ok' if ok else 'CONGELADA'}  ({sinal})")
    for nome, motivo in ISENTAS.items():
        print(f"{nome:32} {'—':12} {'—':>5} {'—':>7}  isenta   ({motivo})")

    velhas = [ln for ln in linhas if not ln[4]]
    sys.stdout.flush()  # senão o diagnóstico em stderr aparece antes da tabela
    if erros:
        print("\nProblemas ao apurar:", file=sys.stderr)
        for e in erros:
            print(f"  {e}", file=sys.stderr)
    if velhas:
        print("\nBASES CONGELADAS:", file=sys.stderr)
        for nome, quando, dias, limite, _, sinal in velhas:
            print(f"  {nome}: dado mais recente é {quando} — {dias} dias "
                  f"(limite {limite}). Ver o crawler/workflow dessa base.",
                  file=sys.stderr)

    if args.aviso:
        return 0
    return 1 if (velhas or erros) else 0


if __name__ == "__main__":
    raise SystemExit(main())
