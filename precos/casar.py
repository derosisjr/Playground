# -*- coding: utf-8 -*-
"""Casamento determinístico entre o item de Santos e os itens das cidades-par.

Sem IA e sem score fuzzy decidindo sozinho: uma cadeia de gates booleanos onde o
PRIMEIRO que falha rejeita o item e grava o motivo. O jaccard entra depois, e só
para graduar confiança — nunca para admitir um item que um gate reprovou.

A política é assimétrica de propósito:

  - rejeitar é barato e reversível (o motivo fica visível na revisão);
  - aceitar errado publica um número falso com a marca do gabinete.

Por isso `revisao.confirmados` no arquivo de consulta só PROMOVE confiança de um
item que já passou por todos os gates. Não existe caminho para ressuscitar um
item reprovado sem editar as regras da própria consulta — o que aparece no diff
do git e fica auditável.

Uso:
  python precos/casar.py --todas
  python precos/casar.py --slug placas-metalon-lona-2026 --revisar
"""
import argparse
import glob
import json
import os
import statistics
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crawler  # noqa: E402
import fontes  # noqa: E402
import texto  # noqa: E402
import unidades  # noqa: E402

CONSULTAS = os.path.join(crawler.DIR, "consultas")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Limiares da CONTENÇÃO (ver texto.contencao). Abaixo do menor, os itens só
# compartilham os termos que a própria consulta impôs, e nada mais.
S_ALTA, S_MEDIA = 0.60, 0.35
# Contenção 1,0 sobre 1 token isolado corrobora muito pouco: exige-se um mínimo
# de tokens discriminantes no lado mais curto antes de conceder confiança alta.
MIN_TOKENS_DISCRIMINANTES = 3


def carregar_consultas(slug=None) -> list[dict]:
    saida = []
    for caminho in sorted(glob.glob(os.path.join(CONSULTAS, "*.json"))):
        with open(caminho, encoding="utf-8") as f:
            q = json.load(f)
        q.setdefault("slug", os.path.splitext(os.path.basename(caminho))[0])
        if slug and q["slug"] != slug:
            continue
        saida.append(q)
    return saida


def _ancora(conn, q):
    """Item(ns) de Santos da consulta, com o preço que servirá de referência."""
    s = q.get("santos") or {}
    if s.get("cnpj") and s.get("ano") and s.get("sequencial"):
        cnpj, ano, seq = s["cnpj"], int(s["ano"]), int(s["sequencial"])
    else:
        cnpj, ano, seq = fontes.parse_ncp(s.get("numero_controle_pncp"))
    ncp = fontes.montar_ncp(cnpj, ano, seq)
    nums = s.get("itens") or []
    linhas = []
    for n in nums:
        r = conn.execute("SELECT * FROM item WHERE ncp=? AND numero_item=?",
                         (ncp, n)).fetchone()
        if r:
            linhas.append(dict(r))
    return ncp, cnpj, ano, seq, linhas


def preco_homologado(conn, ncp, numero_item):
    """(valor unitário, data, fornecedor, ni) do resultado vencedor, ou None.

    Um item pode ter vários resultados (SRP registra classificação). O vencedor é
    o de `ordem_classificacao_srp = 1`; sem isso, o menor `sequencial_resultado`.
    Resultado cancelado nunca é preço praticado.
    """
    rs = conn.execute(
        "SELECT * FROM resultado WHERE ncp=? AND numero_item=? "
        "ORDER BY COALESCE(ordem_classificacao_srp, 9999), sequencial_resultado",
        (ncp, numero_item)).fetchall()
    for r in rs:
        sit = texto.sem_acento(r["situacao_resultado"] or "")
        if "cancelad" in sit:
            continue
        if (r["valor_unitario_homologado"] or 0) > 0:
            return (r["valor_unitario_homologado"], r["data_resultado"],
                    r["nome_fornecedor"], r["ni_fornecedor"])
    return None


def fator_para_canonica(q, unidade):
    """Fator da unidade informada até a canônica da consulta, ou None.

    `conversoes_extra` do arquivo de consulta tem precedência sobre a tabela
    geral: é o escape curado para o caso em que a QUANTIDADE está na descrição e
    não na unidade ("CX" cuja descrição diz "caixa com 100 unidades"). Fica
    versionado e visível no diff — nunca é adivinhado pelo código.
    """
    extra = {texto.normalizar(k): v for k, v in (q.get("conversoes_extra") or {}).items()}
    f = extra.get(texto.normalizar(unidade))
    if f is None:
        f = unidades.converter(unidade, q.get("unidade_canonica") or "")
    return f if (f and f > 0) else None


def base_da_ancora(conn, ref) -> str:
    """'homologado' quando Santos já tem preço adjudicado; senão 'estimado'.

    A base escolhida vale para TODA a comparação. Misturar o homologado de uma
    cidade com o estimado de outra produz o erro mais fácil e mais indefensável
    deste painel: o estimado é teto de edital, o homologado é preço de mercado.
    """
    return "homologado" if preco_homologado(conn, ref["ncp"], ref["numero_item"]) \
        else "estimado"


def _gates(q, alvo, ref, fator_ref, conn, base="homologado"):
    """Aplica a cadeia de gates. Devolve (ok, motivo, fator, preco, data, forn, ni)."""
    termos = q.get("termos") or {}
    desc = alvo["descricao_norm"] or ""

    sit = texto.sem_acento(alvo["situacao_item"] or "")
    if any(s in sit for s in
           (texto.sem_acento(x) for x in fontes.SITUACOES_ITEM_INVALIDAS)):
        return (False, "situacao_invalida", None, None, None, None, None)

    ms = q.get("material_ou_servico")
    if ms and (alvo["material_ou_servico"] or "").upper() != ms.upper():
        return (False, "natureza_diferente", None, None, None, None, None)

    for t in termos.get("obrigatorios") or []:
        if not texto.contem(desc, t):
            return (False, "sem_termo_obrigatorio", None, None, None, None, None)

    for grupo in termos.get("algum_de") or []:
        if not any(texto.contem(desc, t) for t in grupo):
            return (False, "sem_termo_do_grupo", None, None, None, None, None)

    for t in termos.get("excluir") or []:
        if texto.contem(desc, t):
            return (False, f"termo_excluido:{t}", None, None, None, None, None)

    fator = fator_para_canonica(q, alvo["unidade_medida"])
    if not fator:
        return (False, "unidade_desconhecida", None, None, None, None, None)

    for spec in q.get("numeros") or []:
        if not any(texto.contem(desc, str(v)) for v in (spec.get("valores") or [])):
            return (False, f"spec_ausente:{spec.get('rotulo','?')}",
                    None, None, None, None, None)

    faixa = q.get("faixa_quantidade")
    if faixa and ref.get("quantidade") and alvo["quantidade"]:
        # quantidades comparadas já na unidade canônica
        qa = (alvo["quantidade"] or 0) * fator
        qr = (ref["quantidade"] or 0) * (fator_ref or 1)
        if qr > 0 and not (faixa[0] <= qa / qr <= faixa[1]):
            return (False, "quantidade_fora_da_faixa", None, None, None, None, None)

    srp_regra = q.get("srp")
    if srp_regra:
        srp = conn.execute("SELECT srp FROM contratacao WHERE ncp=?",
                           (alvo["ncp"],)).fetchone()
        srp = bool(srp and srp[0])
        if (srp_regra == "apenas" and not srp) or (srp_regra == "excluir" and srp):
            return (False, "srp_incompativel", None, None, None, None, None)

    if base == "estimado":
        valor = alvo.get("valor_unitario_estimado") or 0
        data = (alvo.get("data_publicacao") or "")[:10] or None
        forn = ni = None
        if valor <= 0:
            return (False, "preco_invalido", fator, None, None, None, None)
    else:
        if not alvo["tem_resultado"]:
            return (False, "sem_resultado_publicado", fator, None, None, None, None)
        ph = preco_homologado(conn, alvo["ncp"], alvo["numero_item"])
        if not ph:
            # ainda não buscado (Tier 3 pendente) — aceita para ENTRAR NA FILA;
            # o export só publica observação que já tem preço.
            return (True, None, fator, None, None, None, None)
        valor, data, forn, ni = ph

    preco = valor / fator
    if preco <= 0:
        return (False, "preco_invalido", fator, None, None, None, None)

    janela = int(q.get("janela_meses") or 36)
    if data:
        meses = (date.today().year - int(data[:4])) * 12 + \
                (date.today().month - int(data[5:7]))
        if meses > janela:
            return (False, "fora_da_janela", fator, preco, data, forn, ni)

    return (True, None, fator, preco, data, forn, ni)


def _confianca(q, ref, alvo, fator):
    """(confiança, jaccard). Jaccard sobre os tokens que NÃO são da consulta.

    Medir sobre todos os tokens mediria a própria consulta: os termos exigidos
    estão nos dois lados por construção. O que interessa é o que sobra — se o
    candidato não tem NADA além dos termos exigidos (o PNCP tem muitos itens
    catalogados apenas como "Seringa" ou "Copo Descartável"), não há como
    verificar que é o mesmo produto, e ele é descartado como genérico.
    """
    tq = set()
    for t in (q.get("termos") or {}).get("obrigatorios") or []:
        tq |= texto.tokens(t)
    for g in (q.get("termos") or {}).get("algum_de") or []:
        for t in g:
            tq |= texto.tokens(t)
    restante_alvo = texto.tokens(alvo["descricao"]) - tq
    if not restante_alvo:
        return "generica", 0.0
    s = texto.contencao(texto.tokens(ref["descricao"]) - tq, restante_alvo)

    chave = f"{alvo['ncp']}#{alvo['numero_item']}"
    if chave in ((q.get("revisao") or {}).get("confirmados") or []):
        return "alta", s
    if alvo.get("catalogo_codigo") and alvo["catalogo_codigo"] == ref.get("catalogo_codigo"):
        return "alta", s
    # descrição curta demais corrobora pouco, mesmo com contenção 1,0
    if len(restante_alvo) < MIN_TOKENS_DISCRIMINANTES:
        return ("media" if s >= S_ALTA else "baixa"), s
    if s >= S_ALTA:
        return ("alta" if abs(fator - 1.0) < 1e-9 else "media"), s
    if s >= S_MEDIA:
        return "media", s
    return "baixa", s


def casar(conn, q, aplicar_outlier=True):
    """Avalia todos os itens das cidades-par contra a âncora. Persiste em `casamento`."""
    slug = q["slug"]
    ncp_ref, _, _, _, refs = _ancora(conn, q)
    if not refs:
        return {"slug": slug, "erro": "âncora de Santos ausente — rode --santos"}
    ref = refs[0]
    fator_ref = fator_para_canonica(q, ref["unidade_medida"])
    if not fator_ref:
        # cair em fator 1 aqui publicaria o preço da CAIXA como preço da UNIDADE:
        # errar por 100× e com a marca do gabinete. Melhor não publicar.
        return {"slug": slug,
                "erro": f"unidade da âncora ({ref['unidade_medida']!r}) não converte "
                        f"para {q.get('unidade_canonica')!r} — declare em conversoes_extra"}
    base = base_da_ancora(conn, ref)

    rejeitados_curadoria = set((q.get("revisao") or {}).get("rejeitados") or [])
    mods = q.get("modalidades") or sorted(fontes.MODALIDADES)
    cidades = q.get("cidades") or [c[0] for c in fontes.CIDADES]

    sql = ("SELECT i.*, c.ibge, c.razao_social, c.srp AS c_srp, c.data_publicacao "
           "FROM item i JOIN contratacao c ON c.ncp=i.ncp "
           f"WHERE c.ibge IN ({','.join('?' * len(cidades))}) "
           f"AND c.modalidade IN ({','.join('?' * len(mods))})")
    candidatos = [dict(r) for r in conn.execute(sql, cidades + mods)]

    linhas, aceitos, motivos = [], [], {}
    for alvo in candidatos:
        chave = f"{alvo['ncp']}#{alvo['numero_item']}"
        if chave in rejeitados_curadoria:
            motivos["curadoria_rejeitou"] = motivos.get("curadoria_rejeitou", 0) + 1
            linhas.append((slug, alvo["ncp"], alvo["numero_item"], 0, None, None,
                           "curadoria_rejeitou", "rejeitado"))
            continue
        ok, motivo, fator, preco, data, forn, ni = _gates(
            q, alvo, ref, fator_ref, conn, base)
        if not ok:
            motivos[motivo] = motivos.get(motivo, 0) + 1
            linhas.append((slug, alvo["ncp"], alvo["numero_item"], 0, None, None,
                           motivo, None))
            continue
        conf, j = _confianca(q, ref, alvo, fator)
        if conf in ("baixa", "generica"):
            motivo = ("descricao_generica" if conf == "generica" else "confianca_baixa")
            motivos[motivo] = motivos.get(motivo, 0) + 1
            linhas.append((slug, alvo["ncp"], alvo["numero_item"], 0, conf, j,
                           motivo, None))
            continue
        cur = "confirmado" if chave in ((q.get("revisao") or {}).get("confirmados") or []) else None
        linhas.append((slug, alvo["ncp"], alvo["numero_item"], 1, conf, j, None, cur))
        aceitos.append(dict(alvo, _preco=preco, _data=data, _conf=conf, _j=j,
                            _fator=fator, _forn=forn, _ni=ni))

    # 2ª passada: outlier grosseiro só quando já há preço e coorte suficiente
    if aplicar_outlier:
        precos = [a["_preco"] for a in aceitos if a["_preco"]]
        if len(precos) >= 4:
            med = statistics.median(precos)
            for a in aceitos:
                if a["_preco"] and not (med / 6 <= a["_preco"] <= med * 6):
                    motivos["outlier"] = motivos.get("outlier", 0) + 1
                    linhas = [ln for ln in linhas
                              if not (ln[1] == a["ncp"] and ln[2] == a["numero_item"])]
                    linhas.append((slug, a["ncp"], a["numero_item"], 0, a["_conf"],
                                   a["_j"], "outlier", None))
            aceitos = [a for a in aceitos
                       if not a["_preco"] or med / 6 <= a["_preco"] <= med * 6]

    conn.execute("DELETE FROM casamento WHERE slug=?", (slug,))
    conn.executemany("INSERT OR REPLACE INTO casamento VALUES (?,?,?,?,?,?,?,?)", linhas)
    conn.commit()

    com_preco = [a for a in aceitos if a["_preco"]]
    return {"slug": slug, "ncp_ref": ncp_ref, "base": base, "ref": ref,
            "fator_ref": fator_ref, "aceitos_detalhe": aceitos,
            "avaliados": len(candidatos), "aceitos": len(aceitos),
            "com_preco": len(com_preco),
            "descartados": len(candidatos) - len(aceitos), "motivos": motivos}


def revisar(conn, q):
    """Tela de curadoria: o que foi aceito, o que foi rejeitado e por quê."""
    r = casar(conn, q, aplicar_outlier=True)
    if r.get("erro"):
        print(r["erro"])
        return
    _, _, _, _, refs = _ancora(conn, q)
    ref = refs[0]
    print(f"\n=== {q.get('titulo')} ({q['slug']}) ===")
    print(f"Âncora Santos · item {ref['numero_item']}: {ref['descricao'][:90]}")
    print(f"  {ref['quantidade']} {ref['unidade_medida']} · "
          f"estimado R$ {ref['valor_unitario_estimado']}")
    ph = preco_homologado(conn, ref["ncp"], ref["numero_item"])
    print(f"  homologado: {ph[0] if ph else '— (Tier 3 pendente)'}"
          + (f" em {ph[1]} · {ph[2]}" if ph else ""))
    print(f"\nAvaliados {r['avaliados']} · aceitos {r['aceitos']} "
          f"(com preço {r['com_preco']}) · descartados {r['descartados']}")

    print("\n-- ACEITOS " + "-" * 60)
    for row in conn.execute(
            "SELECT k.*, i.descricao, i.unidade_medida, i.quantidade, c.razao_social, c.ibge "
            "FROM casamento k JOIN item i ON i.ncp=k.ncp AND i.numero_item=k.numero_item "
            "JOIN contratacao c ON c.ncp=k.ncp WHERE k.slug=? AND k.aceito=1 "
            "ORDER BY k.jaccard DESC", (q["slug"],)):
        p = preco_homologado(conn, row["ncp"], row["numero_item"])
        cidade = next((c[1] for c in fontes.CIDADES if c[0] == row["ibge"]), row["ibge"])
        print(f"  [{row['confianca']:5s} j={row['jaccard']:.2f}] {cidade:20s} "
              f"{(p[0] if p else 0) or 0:>12,.2f} {row['unidade_medida']:8s} "
              f"{row['descricao'][:60]}")
        print(f"          {row['ncp']}#{row['numero_item']}")

    print("\n-- MOTIVOS DE DESCARTE " + "-" * 48)
    for motivo, n in sorted(r["motivos"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:6d}  {motivo}")
    print("\nPara confirmar/rejeitar à mão, cole a chave NCP#item em "
          f"consultas/{q['slug']}.json → revisao.confirmados / revisao.rejeitados")


def main():
    ap = argparse.ArgumentParser(description="Casamento de itens (Preço comparado)")
    ap.add_argument("--slug")
    ap.add_argument("--todas", action="store_true")
    ap.add_argument("--revisar", action="store_true", help="tela de curadoria")
    args = ap.parse_args()

    conn = crawler.conectar()
    consultas = carregar_consultas(args.slug)
    if not consultas:
        print("nenhuma consulta em precos/consultas/")
        return
    for q in consultas:
        if args.revisar:
            revisar(conn, q)
        else:
            r = casar(conn, q)
            if r.get("erro"):
                print(f"{r['slug']}: {r['erro']}")
            else:
                print(f"{r['slug']}: avaliados {r['avaliados']} · aceitos {r['aceitos']} "
                      f"(com preço {r['com_preco']}) · descartados {r['descartados']}")


if __name__ == "__main__":
    main()
