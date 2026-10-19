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
     calendário de pagamentos (soma dos dias de cada mês = série; documentos = pagamentos)
     e caminho do dinheiro (cada nível soma o pago do ano sem o extra-orçamentário);
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
# Fração do pago de um mês cujo empenho não está na base. Histórico 2025–ago/2026:
# 0–8% (globais de dezembro do exercício anterior).
LIMITE_NAO_LOCALIZADO = 0.25
PISO_NL_PAGO = 5_000_000      # meses com pago menor (ex.: mês corrente no dia 1) não contam
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

    # 4b) calendário de pagamentos e caminho do dinheiro (dados/calendario.json e
    # dados/fluxo.json, M8): somam o mesmo que a série mensal e o pago de cada ano
    falhas += verificar_calendario(raiz, idx) + verificar_fluxo(raiz, idx)

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

    # 7) casamento pagamento → empenho: a conservação não enxerga quando a origem
    # muda o formato do nº de empenho (out/2026: 72% do pago virou "não localizado").
    for s in (idx.get("execucao") or {}).get("serie") or []:
        pago, nl = s.get("pago") or 0, s.get("nao_localizado") or 0
        if pago >= PISO_NL_PAGO and nl / pago > LIMITE_NAO_LOCALIZADO:
            falhas.append(f"{s['ano']}-{s['mes']:02d}: {nl / pago:.0%} do pago com empenho não localizado "
                          f"(limite {LIMITE_NAO_LOCALIZADO:.0%}) — formato do nº de empenho mudou na origem?")
    return falhas


# ── Calendário de pagamentos e caminho do dinheiro (M8) ──────────────────────
def _arquivo_grafico(raiz: str, idx: dict, nome: str):
    """(conteúdo, falhas) do arquivo `nome` do manifesto `dados_graficos` do índice."""
    man = (idx.get("dados_graficos") or {}).get(nome)
    if not man:
        return None, [f"índice sem `dados_graficos.{nome}` (export anterior ao M8?)"]
    caminho = os.path.join(raiz, man["arquivo"])
    if not os.path.exists(caminho):
        return None, [f"arquivo do manifesto ausente: {man['arquivo']}"]
    falhas = []
    if os.path.getsize(caminho) != man.get("bytes"):
        falhas.append(f"{man['arquivo']}: {os.path.getsize(caminho)} bytes × manifesto {man.get('bytes')}")
    return _ler(caminho), falhas


def verificar_calendario(raiz: str, idx: dict) -> list[str]:
    """Soma dos dias de cada mês = série mensal do índice (o export conta o dia dentro do mês
    da partição, como a série); documentos = pagamentos da base; dias válidos, únicos, em ordem."""
    from datetime import date
    cal, falhas = _arquivo_grafico(raiz, idx, "calendario")
    if cal is None:
        return falhas
    campos = cal.get("campos") or []
    if not {"dia", "pago", "n"} <= set(campos):
        return falhas + [f"calendário com campos inesperados: {campos}"]
    iD, iP, iN = (campos.index(c) for c in ("dia", "pago", "n"))
    por_mes, docs, dias = {}, 0, []
    for linha in cal.get("linhas") or []:
        try:
            date.fromisoformat(linha[iD])
        except (TypeError, ValueError):
            falhas.append(f"calendário: dia inválido {linha[iD]!r}")
            continue
        por_mes[linha[iD][:7]] = por_mes.get(linha[iD][:7], 0) + linha[iP]
        docs += linha[iN]
        dias.append(linha[iD])
    if dias != sorted(set(dias)):
        falhas.append("calendário: dias repetidos ou fora de ordem")
    serie = {f"{s['ano']}-{s['mes']:02d}": s["valor"] for s in idx.get("series_mensais") or []}
    for mes in sorted(set(serie) | set(por_mes)):
        a, b = por_mes.get(mes), serie.get(mes)
        if a is None or b is None or abs(a - b) > TOL:
            falhas.append(f"calendário {mes}: soma dos dias {a if a is None else round(a, 2)} × série mensal {b}")
    pagamentos = (idx.get("totais") or {}).get("pagamentos")
    if docs != pagamentos:
        falhas.append(f"calendário: {docs} documentos × {pagamentos} pagamentos na base")
    if cal.get("ate") != (dias[-1] if dias else None):
        falhas.append(f"calendário: `ate` {cal.get('ate')} × último dia {dias[-1] if dias else None}")
    return falhas


def verificar_fluxo(raiz: str, idx: dict) -> list[str]:
    """Por ano e variante: cada nível (fonte, função, favorecido) e cada camada de ligações
    somam o total, e cada nó entrega/recebe o próprio valor; o total de "todos" = pago do ano
    sem o extra-orçamentário (execucao.por_ano); "privados" sem ente público."""
    import formato   # mesmo diretório (o slug das identidades de entes_publicos)
    fx, falhas = _arquivo_grafico(raiz, idx, "fluxo")
    if fx is None:
        return falhas
    anos = fx.get("anos") or {}
    anos_base = sorted((idx.get("totais") or {}).get("por_ano") or {})
    if sorted(anos) != anos_base:
        falhas.append(f"caminho do dinheiro: anos {sorted(anos)} × anos da base {anos_base}")
    exe = (idx.get("execucao") or {}).get("por_ano") or {}
    entes = {"v:" + formato.slug_favorecido(k) for k in idx.get("entes_publicos") or []}
    for ano, a in sorted(anos.items()):
        e = exe.get(ano) or {}
        if abs((a.get("extra") or 0) - (e.get("extra") or 0)) > TOL:
            falhas.append(f"caminho {ano}: extra-orçamentário {a.get('extra')} × execução {e.get('extra')}")
        for var in ("todos", "privados"):
            s = a.get(var) or {}
            nos, lig, total = s.get("nos") or [], s.get("ligacoes") or [], s.get("total") or 0
            rot = f"caminho {ano} ({var})"
            if var == "todos":
                alvo = round((e.get("pago") or 0) - (e.get("extra") or 0), 2)
                if abs(total - alvo) > TOL:
                    falhas.append(f"{rot}: total {total} × pago do ano sem o extra-orçamentário {alvo}")
            elif total > ((a.get("todos") or {}).get("total") or 0) + TOL:
                falhas.append(f"{rot}: total {total} acima do de todos os favorecidos")
            if len(lig) > 300:
                falhas.append(f"{rot}: {len(lig)} ligações (teto 300)")
            nivel = {n["id"]: n["nivel"] for n in nos}
            if len(nivel) != len(nos):
                falhas.append(f"{rot}: id de nó repetido")
            entra, sai = {}, {}
            for de, para, v in lig:
                if nivel.get(para, -1) != nivel.get(de, -9) + 1:
                    falhas.append(f"{rot}: ligação inválida {de} → {para}")
                    continue
                sai[de] = sai.get(de, 0) + v
                entra[para] = entra.get(para, 0) + v
            for k in (0, 1, 2):
                soma = sum(n["valor"] for n in nos if n["nivel"] == k)
                if abs(soma - total) > TOL:
                    falhas.append(f"{rot}: nível {k} soma {round(soma, 2)} × total {total}")
            for n in nos:   # o que sai de um nó e o que chega nele é o valor dele
                if n["nivel"] < 2 and abs(sai.get(n["id"], 0) - n["valor"]) > TOL:
                    falhas.append(f"{rot}: {n['id']} entrega {round(sai.get(n['id'], 0), 2)} × valor {n['valor']}")
                if n["nivel"] > 0 and abs(entra.get(n["id"], 0) - n["valor"]) > TOL:
                    falhas.append(f"{rot}: {n['id']} recebe {round(entra.get(n['id'], 0), 2)} × valor {n['valor']}")
            if var == "privados":
                publicos = [n["nome"] for n in nos if n["id"] in entes or n.get("ente_publico")]
                if publicos:
                    falhas.append(f"{rot}: ente público entre os privados: {', '.join(publicos[:3])}")
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
