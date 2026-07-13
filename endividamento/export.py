# -*- coding: utf-8 -*-
"""Export do Painel de Endividamento → endividamento-index.json (raiz).

Lê o endividamento.sqlite (RGF por quadrimestre) e monta:
  - serie: evolução quadrimestral (dívida bruta, DCL, RCL, % LRF, pessoal,
    operações de crédito, precatórios vencidos, restos a pagar, caixa);
  - semaforo: um mostrador por limite da LRF (dívida, pessoal, op. crédito),
    com cor verde/amarelo/vermelho pelos limites OFICIAIS do próprio RGF
    (limite de alerta e limite máximo, art. 59 da LRF);
  - totais + resumo narrativo determinístico (template, sem IA).

Guarda anti-truncamento: aborta se a RCL do período mais recente vier
implausível (fonte fora do ar / resposta parcial).

Uso:  python endividamento/export.py [--dry-run]
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "endividamento.sqlite")
SAIDA = os.path.join(RAIZ, "endividamento-index.json")

RCL_MINIMA_PLAUSIVEL = 1_000_000_000  # Santos: RCL ~R$ 3,5 bi; < R$ 1 bi = truncado

# console do Windows pode ser cp1252; a saída do script é utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _carregar(conn) -> dict:
    """{(ano, periodo): {chave: {coluna_normalizada: valor}}}"""
    dados = {}
    for r in conn.execute("SELECT * FROM rgf"):
        per = dados.setdefault((r["ano"], r["periodo"]), {})
        per.setdefault(r["chave"], {})[r["coluna"].upper()] = r["valor"]
    return dados


def _v(per: dict, chave: str, coluna: str):
    """Valor de uma conta numa coluna (casamento por fragmento, caixa alta)."""
    cols = per.get(chave) or {}
    for c, v in cols.items():
        if coluna in c:
            return v
    return None


def _ponto(ano: int, q: int, per: dict) -> dict:
    """Um ponto da série: anexo 02 usa a coluna do quadrimestre; 01/04, 'Valor'."""
    quad = f"ATÉ O {q}º QUADRIMESTRE"

    def a2(chave):
        return _v(per, chave, quad)

    rp_proc = a2("rp_processados")
    rp_nproc = a2("rp_nao_processados")
    return {
        "ano": ano, "q": q, "rotulo": f"{q}º quad. {ano}",
        "dc": a2("dc"), "dcl": a2("dcl"), "rcl": a2("rcl"),
        "dc_pct": a2("dc_pct"), "dcl_pct": a2("dcl_pct"),
        "precatorios": a2("precatorios_vencidos"),
        "caixa_bruta": a2("caixa_bruta"),
        "rp": (rp_proc or 0) + (rp_nproc or 0) if (rp_proc is not None or rp_nproc is not None) else None,
        "passivo_atuarial": a2("passivo_atuarial"),
        "pessoal": _v(per, "pessoal_dtp", "VALOR"),
        "pessoal_pct": _v(per, "pessoal_dtp", "% SOBRE A RCL"),
        # sem operação contratada no período a linha TOTAL não existe no RGF:
        # com o Anexo 04 publicado, ausência = zero
        "opcred": _v(per, "opcred_total", "VALOR")
                  or (0.0 if "opcred_limite" in per else None),
        "opcred_pct": _v(per, "opcred_total", "% SOBRE A RCL")
                      or (0.0 if "opcred_limite" in per else None),
    }


def _cor(pct, alerta, limite):
    if pct is None or alerta is None or limite is None:
        return None
    if pct >= limite:
        return "vermelho"
    if pct >= alerta:
        return "amarelo"
    return "verde"


def _pct_limite(v, padrao):
    """Alguns exercícios declaram o limite em R$ em vez de %; os percentuais
    são fixos por Resolução do Senado — acima de 200, é R$: usa o padrão."""
    if v is None or v > 200:
        return padrao
    return v


def _semaforo(per: dict, ponto: dict) -> list[dict]:
    quad = f"ATÉ O {ponto['q']}º QUADRIMESTRE"
    mostradores = []

    # Dívida consolidada líquida ÷ RCL (limite Senado 120%; alerta 108%)
    lim = _pct_limite(_v(per, "divida_limite", quad), 120.0)
    ale = _pct_limite(_v(per, "divida_alerta", quad), 108.0)
    mostradores.append({
        "slug": "divida", "nome": "Dívida consolidada líquida",
        "pergunta": "A dívida cabe na receita?",
        "pct": ponto["dcl_pct"], "alerta": ale, "limite": lim,
        "valor": ponto["dcl"], "cor": _cor(ponto["dcl_pct"], ale, lim),
        "base_legal": "Res. Senado 40/2001 · limite 120% da RCL",
    })

    # Despesa com pessoal ÷ RCL ajustada (limite Executivo 54%; alerta 48,6%)
    lim = _v(per, "pessoal_limite", "% SOBRE A RCL")
    ale = _v(per, "pessoal_alerta", "% SOBRE A RCL")
    mostradores.append({
        "slug": "pessoal", "nome": "Despesa com pessoal",
        "pergunta": "A folha cabe na receita?",
        "pct": ponto["pessoal_pct"], "alerta": ale, "limite": lim,
        "valor": ponto["pessoal"], "cor": _cor(ponto["pessoal_pct"], ale, lim),
        "base_legal": "LRF, art. 20 · limite 54% da RCL (Executivo)",
    })

    # Operações de crédito ÷ RCL (limite Senado 16%; alerta 14,4%) —
    # o zero de "nenhuma operação no período" já vem resolvido em _ponto()
    lim = _pct_limite(_v(per, "opcred_limite", "% SOBRE A RCL"), 16.0)
    ale = _pct_limite(_v(per, "opcred_alerta", "% SOBRE A RCL"), 14.4)
    mostradores.append({
        "slug": "opcred", "nome": "Operações de crédito",
        "pergunta": "Quanto se tomou emprestado no ano?",
        "pct": ponto["opcred_pct"], "alerta": ale, "limite": lim,
        "valor": ponto["opcred"], "cor": _cor(ponto["opcred_pct"], ale, lim),
        "base_legal": "Res. Senado 43/2001 · limite 16% da RCL",
    })
    return mostradores


def _brl_compacto(v: float) -> str:
    if abs(v) >= 1e9:
        n = v / 1e9
        plural = "bilhões" if round(n, 1) >= 2 else "bilhão"
        return f"R$ {n:.1f} {plural}".replace(".", ",")
    n = round(v / 1e6)
    return f"R$ {n} {'milhões' if abs(n) >= 2 else 'milhão'}"


def _resumo(serie: list[dict], ponto: dict, semaforo: list[dict]) -> str:
    partes = []
    partes.append(
        f"No {ponto['rotulo'].replace('quad.', 'quadrimestre de')}, a dívida "
        f"consolidada de Santos era de {_brl_compacto(ponto['dc'])} — "
        f"{ponto['dc_pct']:.1f}% da receita corrente líquida".replace(".", ","))
    primeiro = next((p for p in serie if p["dc"]), None)
    if primeiro and primeiro is not ponto and primeiro["dc"]:
        var = (ponto["dc"] / primeiro["dc"] - 1) * 100
        verbo = "cresceu" if var >= 0 else "caiu"
        partes.append(
            f"desde o {primeiro['rotulo']}, ela {verbo} "
            f"{abs(var):.0f}% em valores correntes")
    fora = [m["nome"].lower() for m in semaforo if m["cor"] == "vermelho"]
    aviso = [m["nome"].lower() for m in semaforo if m["cor"] == "amarelo"]
    if fora:
        partes.append("ACIMA do limite legal: " + ", ".join(fora))
    elif aviso:
        partes.append("em zona de alerta da LRF: " + ", ".join(aviso))
    else:
        partes.append("todos os limites da Lei de Responsabilidade Fiscal "
                      "estão sendo cumpridos com folga")
    if ponto.get("precatorios"):
        partes.append(f"o estoque de precatórios vencidos e não pagos soma "
                      f"{_brl_compacto(ponto['precatorios'])}")
    return ". ".join(p[0].upper() + p[1:] for p in partes) + "."


def montar(conn) -> dict:
    dados = _carregar(conn)
    if not dados:
        raise SystemExit("base vazia — rode o crawler primeiro")

    serie = [_ponto(ano, q, per) for (ano, q), per in sorted(dados.items())]
    serie = [p for p in serie if p["dc"] is not None or p["pessoal"] is not None]

    ultimo = serie[-1]
    per_ultimo = dados[(ultimo["ano"], ultimo["q"])]
    semaforo = _semaforo(per_ultimo, ultimo)

    # dívida das estatais (curadoria manual anual — endividamento/estatais.json)
    estatais = None
    arq_estatais = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estatais.json")
    if os.path.exists(arq_estatais):
        with open(arq_estatais, encoding="utf-8") as f:
            estatais = json.load(f)
        estatais.pop("_comentario", None)

    return {
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": "Tesouro Nacional/SICONFI — Relatório de Gestão Fiscal (RGF), Prefeitura de Santos",
        "ultimo": {"ano": ultimo["ano"], "q": ultimo["q"], "rotulo": ultimo["rotulo"]},
        "totais": {
            "divida": ultimo["dc"], "dcl": ultimo["dcl"], "rcl": ultimo["rcl"],
            "dc_pct": ultimo["dc_pct"], "dcl_pct": ultimo["dcl_pct"],
            "precatorios": ultimo["precatorios"],
            "passivo_atuarial": ultimo["passivo_atuarial"],
        },
        "semaforo": semaforo,
        "serie": serie,
        "estatais": estatais,
        "resumo": _resumo(serie, ultimo, semaforo),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(BASE)
    conn.row_factory = sqlite3.Row
    indice = montar(conn)

    u = indice["totais"]
    print(f"período: {indice['ultimo']['rotulo']} · pontos na série: {len(indice['serie'])}")
    print(f"dívida: {u['divida']:,.0f} · DCL: {u['dcl']:,.0f} · RCL: {u['rcl']:,.0f}")
    for m in indice["semaforo"]:
        print(f"  {m['slug']}: {m['pct']}% (alerta {m['alerta']}% · limite {m['limite']}%) → {m['cor']}")
    print("resumo:", indice["resumo"])

    # guarda anti-truncamento
    if not u["rcl"] or u["rcl"] < RCL_MINIMA_PLAUSIVEL:
        raise SystemExit("ABORTANDO: RCL implausível — fonte truncada?")
    if any(m["cor"] is None for m in indice["semaforo"]):
        raise SystemExit("ABORTANDO: semáforo incompleto — anexo faltando?")

    if args.dry_run:
        print("[dry-run] nada gravado")
        return
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, separators=(",", ":"))
    print(f"gravado: {SAIDA}")


if __name__ == "__main__":
    main()
