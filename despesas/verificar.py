#!/usr/bin/env python3
"""
Verificação de integridade dos artefatos publicados da Base de Despesas
=======================================================================

Substitui a guarda única "total geral > R$ 4 bi" do workflow por checagens por
partição e por conservação, executadas sobre o que o export ACABOU de gravar:

  1. cobertura: toda partição (estágio × mês) esperada de ANO_INICIAL-01 até o mês
     corrente tem carga, e nenhuma teve a última coleta com erro/suspeita
     (`--tolerar-erros` deixa passar falhas parciais, que já ficam visíveis);
  2. conservação: pago da base = pago somado na execução por empenho = pago somado
     na movimentação (o índice grava o bloco `conservacao`);
  3. manifestos × arquivos: cada `dados/AAAA-MM.json` e `dados/mov/AAAA-MM.json`
     listado existe, tem o nº de linhas anunciado e soma o valor anunciado;
  4. estágios: pago por mês na série = pago somado nos manifestos de movimentação;
  5. favorecidos: soma do top-N ≤ total geral; cada dossiê existe e seu total bate
     com o ranking (raio-X e ranking coerentes);
  6. piso de escala (o antigo "≥ R$ 4 bi"), mantido só como sanidade grosseira.

Sai 1 com a lista de falhas; 0 quando tudo passa. Uso:
    python despesas/verificar.py                 # artefatos do repo
    python despesas/verificar.py --raiz DIR      # candidato gerado com export --saida DIR
"""

import argparse
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
PISO_TOTAL = 4_000_000_000     # sanidade grosseira (mandato completo ≈ R$ 8 bi)
TOL = 1.0                      # tolerância em R$ nas somas (arredondamento a 2 casas)


def _ler(caminho):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def verificar(raiz: str, tolerar_erros: bool = False) -> list[str]:
    falhas = []
    idx_path = os.path.join(raiz, "despesas-index.json")
    if not os.path.exists(idx_path):
        return [f"índice ausente: {idx_path}"]
    idx = _ler(idx_path)

    # 1) cobertura por partição
    cob = idx.get("cobertura")
    if not cob:
        falhas.append("índice sem bloco `cobertura` (export antigo?)")
    else:
        if cob.get("faltantes"):
            falhas.append(f"{len(cob['faltantes'])} partição(ões) sem carga: {', '.join(cob['faltantes'][:6])}")
        if cob.get("com_erro"):
            msg = f"{len(cob['com_erro'])} partição(ões) com falha na última coleta: {'; '.join(cob['com_erro'][:3])}"
            (print("AVISO: " + msg, file=sys.stderr) if tolerar_erros else falhas.append(msg))

    # 2) conservação
    cons = idx.get("conservacao") or {}
    if not cons:
        falhas.append("índice sem bloco `conservacao`")
    elif not cons.get("ok"):
        falhas.append(f"conservação falhou: base {cons.get('pago_base')} × execução {cons.get('pago_execucao')} "
                      f"× movimentação {cons.get('pago_movimento')}")

    # 3) manifestos × arquivos
    campos = idx.get("campos_detalhe") or []
    iP = campos.index("pago") if "pago" in campos else -1
    for m in idx.get("meses") or []:
        arq = os.path.join(raiz, m["arquivo"])
        if not os.path.exists(arq):
            falhas.append(f"arquivo do manifesto ausente: {m['arquivo']}")
            continue
        d = _ler(arq)
        if len(d.get("linhas", [])) != m["n"]:
            falhas.append(f"{m['arquivo']}: {len(d.get('linhas', []))} linhas × manifesto {m['n']}")
        if iP >= 0:
            soma = round(sum((l[iP] or 0) for l in d["linhas"]), 2)
            if abs(soma - m["valor"]) > TOL:
                falhas.append(f"{m['arquivo']}: pago {soma} × manifesto {m['valor']}")
    campos_mov = idx.get("campos_movimento") or []
    iPm = campos_mov.index("pago") if "pago" in campos_mov else -1
    pago_mov_meses = {}
    for m in idx.get("meses_movimento") or []:
        arq = os.path.join(raiz, m["arquivo"])
        if not os.path.exists(arq):
            falhas.append(f"arquivo do manifesto ausente: {m['arquivo']}")
            continue
        d = _ler(arq)
        if len(d.get("linhas", [])) != m["n"]:
            falhas.append(f"{m['arquivo']}: {len(d.get('linhas', []))} linhas × manifesto {m['n']}")
        if iPm >= 0:
            soma = round(sum((l[iPm] or 0) for l in d["linhas"]), 2)
            if abs(soma - m["pago"]) > TOL:
                falhas.append(f"{m['arquivo']}: pago {soma} × manifesto {m['pago']}")
        pago_mov_meses[(m["ano"], m["mes"])] = m["pago"]

    # 4) série mensal (movimentação de pagamentos) × manifestos de movimentação
    if pago_mov_meses:
        for s in idx.get("series_mensais") or []:
            v = pago_mov_meses.get((s["ano"], s["mes"]))
            if v is None or abs(v - s["valor"]) > TOL:
                falhas.append(f"série {s['ano']}-{s['mes']:02d}: pago {s['valor']} × movimentação {v}")

    # 5) favorecidos: ranking × dossiês
    tops = idx.get("top_favorecidos") or []
    total = (idx.get("totais") or {}).get("geral") or 0
    soma_top = round(sum(t["valor"] for t in tops), 2)
    if soma_top > total + TOL:
        falhas.append(f"soma do top-{len(tops)} ({soma_top}) excede o total geral ({total})")
    fav_dir = os.path.join(raiz, "favorecidos")
    for t in tops:
        arq = os.path.join(fav_dir, f"{t.get('slug')}.json")
        if not os.path.exists(arq):
            falhas.append(f"dossiê ausente: favorecidos/{t.get('slug')}.json ({t['nome'][:40]})")
            continue
        d = _ler(arq)
        if abs((d.get("total") or 0) - t["valor"]) > TOL:
            falhas.append(f"dossiê {t.get('slug')}: total {d.get('total')} × ranking {t['valor']}")
        serie = round(sum(x["valor"] for x in d.get("serie_mensal") or []), 2)
        if abs(serie - t["valor"]) > TOL:
            falhas.append(f"dossiê {t.get('slug')}: série mensal soma {serie} × ranking {t['valor']}")
    chaves = [t.get("chave") for t in tops]
    if len(set(chaves)) != len(chaves):
        falhas.append("ranking com identidade repetida (consolidação falhou)")

    # 6) piso de escala
    if total < PISO_TOTAL:
        falhas.append(f"total geral {total:,.0f} abaixo do piso de sanidade {PISO_TOTAL:,.0f}")
    return falhas


def main():
    p = argparse.ArgumentParser(description="Verifica integridade dos artefatos da Base de Despesas")
    p.add_argument("--raiz", default=RAIZ, help="Raiz dos artefatos (padrão: o repo)")
    p.add_argument("--tolerar-erros", action="store_true",
                   help="Falha parcial de coleta vira aviso (as partições boas foram publicadas)")
    args = p.parse_args()
    falhas = verificar(args.raiz, args.tolerar_erros)
    if falhas:
        print("VERIFICAÇÃO FALHOU:", file=sys.stderr)
        for f in falhas:
            print("  - " + f, file=sys.stderr)
        sys.exit(1)
    idx = _ler(os.path.join(args.raiz, "despesas-index.json"))
    cob = idx.get("cobertura") or {}
    print(f"Verificação ok: total {idx['totais']['geral']:,.2f}, {len(cob.get('particoes', []))} partições, "
          f"{len(idx.get('meses', []))} meses, {len(idx.get('top_favorecidos', []))} dossiês, "
          f"conservação ok, {len(cob.get('duplicidade_sistematica', []))} partições com duplicidade sistemática na origem.")


if __name__ == "__main__":
    main()
