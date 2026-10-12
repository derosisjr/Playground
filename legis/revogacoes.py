#!/usr/bin/env python3
"""
Situação das normas (revogada / revogada parcialmente / alterada) — INFERIDA
==========================================================================

O Legis da Prefeitura NÃO publica a situação de uma norma: a página da lei
revogada não traz marca alguma (conferido em 2026-10 nas Leis 2.182/2004,
2.490/2007 e LC 543/2005, todas revogadas expressamente). O que o Legis
publica é a EMENTA OFICIAL de cada norma (`<p class="descricao">`), e as normas
revogadoras quase sempre dizem o que fazem nela:

    "REVOGA A LEI Nº 2.182, DE 06 DE JANEIRO DE 2004."            → revogada
    "REVOGA O ARTIGO 2.º DA LEI N.º 1.803, DE 20 DE ..."          → revogada parcialmente
    "ALTERA DISPOSITIVOS DA LEI COMPLEMENTAR Nº 312, DE ..."      → alterada

Este módulo (sem rede, testado em `legis/tests/`) lê essas ementas, extrai os
vínculos (norma de origem → norma-alvo) e calcula a situação de cada alvo.
É inferência de revogação EXPRESSA declarada na ementa da norma posterior:
não pega revogação que só aparece no corpo do texto nem a tácita
("revogadas as disposições em contrário").
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz do repo: comum/
from comum.formato import sem_acento  # noqa: E402

# Relações, da mais forte para a mais fraca (a situação do alvo é a mais forte).
REVOGA, REVOGA_PARCIAL, ALTERA = "revoga", "revoga_parcial", "altera"
SITUACAO = {REVOGA: "revogada", REVOGA_PARCIAL: "revogada parcialmente", ALTERA: "alterada"}
_FORCA = {REVOGA: 3, REVOGA_PARCIAL: 2, ALTERA: 1}

# Tipo citado na ementa → tipo gravado no banco (TIPOS do crawler).
_TIPO = {"LEI COMPLEMENTAR": "Lei complementar", "LEIS COMPLEMENTARES": "Lei complementar",
         "LEI": "Lei ordinária", "LEIS": "Lei ordinária",
         "DECRETO": "Decreto", "DECRETOS": "Decreto"}

# Verbos de ação da norma de origem. "FICA REVOGADA"/"REVOGA-SE" são do corpo do
# texto, mas aparecem em algumas ementas e custam nada aqui.
_VERBO = re.compile(
    r"\b(?:(?P<rev>REVOGAM?(?:-SE)?|FICAM? REVOGAD[AO]S?)"
    r"|(?P<alt>ALTERAM?|DA NOVA REDACAO|DAO NOVA REDACAO|ACRESCE(?:NTA)?M?|ACRESCIDOS?|INSERE|INCLUI))\b"
)

# Onde a cláusula de ação acaba: oração relativa ("QUE INSTITUI...", "QUE REVOGOU..."),
# agente ("JÁ ALTERADA PELA LEI ...") e remissões ("NOS TERMOS DA LEI ...").
_FIM = re.compile(
    r"\b(?:QUE|PEL[AO]S?|JA|NOS TERMOS|CONFORME|TRATA|PREVIST[AO]S?|REFERID[AO]S?|PARA"
    r"|DISPOE|INSTITUI|CRIA|AUTORIZA|ESTABELECE|DISCIPLINA|REGULAMENTA|OUTRAS PROVIDENCIAS"
    r"|PROVIDENCIAS CORRELATAS)\b"
)

# Dispositivo (revogação/alteração só de parte da norma).
_PARCIAL = re.compile(
    r"\b(?:ARTIGOS?|ART|DISPOSITIVOS?|INCISOS?|PARAGRAFOS?|ALINEAS?|ITE(?:M|NS)|CAPUT"
    r"|ANEXOS?|TABELAS?|CAPITULOS?|SECAO|SECOES|SUBSECAO|EMENTA)\b|§"
)

_NUM = r"(\d{1,3}(?:\.\d{3})+|\d{1,5})"
_DATA = (r"(?:\s*,?\s*DE\s+\d{1,2}\.?\s+(?:DE\s+)?[A-Z]+\s+(?:DE\s+)?(\d{4})"
         r"|\s*/\s*(\d{4}|\d{2})\b)?")
_REF = re.compile(
    r"(?<!-)\b(?P<tipo>LEIS COMPLEMENTARES|LEI COMPLEMENTAR|LEIS|LEI|DECRETOS|DECRETO)"
    r"(?P<qual>\s+(?:MUNICIPAL|MUNICIPAIS|FEDERAL|FEDERAIS|ESTADUAL|ESTADUAIS|ORGANICA|-LEI))?"
    r"\s*(?:N(?:OS|S|O)?\.?\s*)?" + _NUM + _DATA
)
# Itens seguintes de uma lista no plural ("LEIS NºS 1.234, DE ..., E 2.345, DE ...").
_MAIS = re.compile(r"\s*(?:,\s*E\s+|,\s*|E\s+)(?:N(?:OS|S|O)?\.?\s*)?" + _NUM + _DATA)


def normalizar(texto: str) -> str:
    """Caixa alta, sem acento, sem º/°/ª, espaços colapsados."""
    t = re.sub(r"[º°ª]", "", texto or "")
    t = sem_acento(t, caixa="alta")
    t = t.replace("–", "-").replace("—", "-")
    return " ".join(t.split())


def _ano(a4: str | None, a2: str | None) -> int | None:
    if a4:
        return int(a4)
    if a2:
        n = int(a2)
        if len(a2) == 4:
            return n
        return 2000 + n if n <= 30 else 1900 + n
    return None


def _num(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _refs(trecho: str):
    """Referências a normas no trecho: [(inicio, fim, tipo_banco, numero, ano)].
    Ignora leis federais/estaduais, Lei Orgânica e decreto-lei."""
    out = []
    for m in _REF.finditer(trecho):
        qual = (m.group("qual") or "").strip()
        if qual and qual not in ("MUNICIPAL", "MUNICIPAIS"):
            continue
        tipo = _TIPO[m.group("tipo")]
        out.append((m.start(), m.end(), tipo, _num(m.group(3)), _ano(m.group(4), m.group(5))))
        if m.group("tipo").endswith("S"):  # plural: consome a lista
            fim = m.end()
            while True:
                m2 = _MAIS.match(trecho, fim)
                if not m2:
                    break
                out.append((m2.start(), m2.end(), tipo, _num(m2.group(1)), _ano(m2.group(2), m2.group(3))))
                fim = m2.end()
    return out


def extrair_vinculos(texto: str) -> list[dict]:
    """Ementa (ou cláusula) → [{relacao, tipo, numero, ano, trecho}].

    Cada verbo de ação abre uma cláusula que vai até o próximo verbo ou até um
    marcador de fim (_FIM). Verbos encadeados sem objeto ("ALTERA E REVOGA
    DISPOSITIVOS DA LEI X", "REVOGA O INCISO V E DÁ NOVA REDAÇÃO AO ... DA LEI X")
    passam adiante para a cláusula seguinte. Dentro da cláusula, cada norma
    citada é parcial se o trecho entre ela e a anterior fala de dispositivo
    ("ARTIGO", "INCISO", "§"...); "..., DA LEI Y" herda a parcialidade da
    anterior e "..., E O DECRETO Y" volta a ser a norma inteira.
    """
    t = normalizar(texto)
    verbos = list(_VERBO.finditer(t))
    vinculos: list[dict] = []
    pendentes: list[tuple[str, bool]] = []  # (tipo de verbo, já há dispositivo no trecho)
    for i, v in enumerate(verbos):
        fim_clausula = verbos[i + 1].start() if i + 1 < len(verbos) else len(t)
        corpo = t[v.end():fim_clausula]
        mf = _FIM.search(corpo)
        if mf:
            corpo = corpo[:mf.start()]
        acao = "rev" if v.group("rev") else "alt"
        refs = _refs(corpo)
        if not refs:
            # verbo sem objeto: se emenda no próximo ("REVOGA E ALTERA ...") — só
            # se nada além de dispositivo/conjunção ficou no meio
            if i + 1 < len(verbos) and not mf:
                pendentes.append((acao, bool(_PARCIAL.search(corpo))))
            else:
                pendentes = []
            continue
        acoes = pendentes + [(acao, False)]
        pendentes = []
        anterior, parcial = 0, False
        for ini, fim, tipo, numero, ano in refs:
            meio = corpo[anterior:ini].strip()
            if _PARCIAL.search(meio):
                parcial = True
            elif not (anterior and re.search(r"\b(?:DA|DO|DAS|DOS)$", meio)):
                parcial = False  # "..., E O DECRETO Y" = norma inteira; ", DA LEI Y" herda
            trecho = (t[v.start():v.end()] + corpo[:fim])[-160:]
            for a, parcial_pendente in acoes:
                if a == "rev":
                    rel = REVOGA_PARCIAL if (parcial or parcial_pendente) else REVOGA
                else:
                    rel = ALTERA
                vinculos.append({"relacao": rel, "tipo": tipo, "numero": numero,
                                 "ano": ano, "trecho": trecho.strip()})
            anterior = fim
    # dedup preservando a ordem
    vistos, unicos = set(), []
    for x in vinculos:
        chave = (x["relacao"], x["tipo"], x["numero"], x["ano"])
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(x)
    return unicos


def calcular_situacoes(normas: list[dict]) -> dict[int, dict]:
    """normas: [{id, tipo, numero, ano, descricao}] (todas as do banco).

    Devolve {id_alvo: {"situacao", "revogada_por", "por"}} só para as normas
    afetadas. `revogada_por` = a revogadora (total ou parcial) mais recente;
    `por` = a norma de origem da relação mais forte (inclui alteração).
    Um alvo só é resolvido se existir no banco com mesmo tipo e número — e
    mesmo ano quando a ementa traz o ano; sem ano, só se o número for único
    no tipo. A origem tem de ser do mesmo ano ou posterior ao alvo.
    """
    por_chave: dict[tuple, int] = {}
    por_num: dict[tuple, list[int]] = {}
    info = {}
    for n in normas:
        num = _num(n.get("numero"))
        info[n["id"]] = n
        if not num:
            continue
        por_chave[(n["tipo"], num, n.get("ano"))] = n["id"]
        por_num.setdefault((n["tipo"], num), []).append(n["id"])

    def ordem(nid):  # cronologia aproximada da origem: ano, depois número
        n = info[nid]
        return (n.get("ano") or 0, int(_num(n.get("numero")) or 0), nid)

    melhor: dict[int, dict] = {}
    for n in normas:
        if not n.get("descricao"):
            continue
        for v in extrair_vinculos(n["descricao"]):
            if v["ano"]:
                alvo = por_chave.get((v["tipo"], v["numero"], v["ano"]))
            else:
                cands = por_num.get((v["tipo"], v["numero"]), [])
                alvo = cands[0] if len(cands) == 1 else None
            if alvo is None or alvo == n["id"]:
                continue
            ano_alvo, ano_orig = info[alvo].get("ano"), n.get("ano")
            if ano_alvo and ano_orig and ano_alvo > ano_orig:
                continue
            m = melhor.setdefault(alvo, {"forca": 0, "por": None, "revogada_por": None})
            f = _FORCA[v["relacao"]]
            if f > m["forca"] or (f == m["forca"] and ordem(n["id"]) > ordem(m["por"])):
                m["forca"], m["por"], m["relacao"] = f, n["id"], v["relacao"]
            if v["relacao"] in (REVOGA, REVOGA_PARCIAL):
                atual = m["revogada_por"]
                f_atual = m.get("forca_rev", 0)
                if f > f_atual or (f == f_atual and ordem(n["id"]) > ordem(atual)):
                    m["revogada_por"], m["forca_rev"] = n["id"], f
    return {alvo: {"situacao": SITUACAO[m["relacao"]], "revogada_por": m["revogada_por"],
                   "por": m["por"]}
            for alvo, m in melhor.items()}
