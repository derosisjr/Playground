"""Lei Orgânica: contagens, ids, art. 58 XVIII, notas de emenda fora do texto.

A fonte é ordem-do-dia/references/lei-organica-santos.md (texto do PDF oficial, Legis
doc. 9596). Os números esperados vêm dela: 253 artigos + 56-A, 58-A e 63-A no corpo,
21 nas Disposições Transitórias, uma nota de emenda por marcador "" do PDF.
"""
import json
import os
import re
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
from regimento import lei_organica as lom  # noqa: E402


@pytest.fixture(scope="module")
def fonte():
    with open(lom.FONTE, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def artigos(fonte):
    return lom.parse(fonte)


@pytest.fixture(scope="module")
def por_id(artigos):
    return {a["id"]: a for a in artigos}


def _bloco(art, rotulo):
    return next(b for b in art["blocos"] if b["rotulo"] == rotulo)


def test_contagens(artigos, fonte):
    corpo = [a for a in artigos if not a["adt"]]
    adt = [a for a in artigos if a["adt"]]
    assert len(corpo) == 256
    assert [a["numero"] for a in corpo if "-" in a["numero"]] == ["56-A", "58-A", "63-A"]
    assert corpo[-1]["numero"] == "253"
    assert len(adt) == 21 and adt[0]["numero"] == "1" and adt[-1]["numero"] == "21"
    # toda nota do PDF vem depois de um marcador: nenhuma se perde, nenhuma sobra
    assert sum(len(a["notas"]) for a in artigos) == fonte.count(lom.MARCADOR_NOTA) == 151


def test_ids_unicos_e_ancoras(artigos):
    ids = [a["id"] for a in artigos]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"art-\d+(-[a-z])?", a["id"]) for a in artigos if not a["adt"])
    assert all(re.fullmatch(r"adt-art-\d+", a["id"]) for a in artigos if a["adt"])
    assert {"art-1", "adt-art-1", "art-56-a"} <= set(ids)


def test_esquema_do_regimento_mais_notas_e_adt(artigos):
    with open(os.path.join(RAIZ, "regimento-index.json"), encoding="utf-8") as f:
        chaves_regimento = set(json.load(f)[0])
    for a in artigos:
        assert set(a) == chaves_regimento | {"notas", "adt"}
        assert a["blocos"][0]["tipo"] == "caput"
        assert all(set(b) == {"tipo", "rotulo", "texto"} for b in a["blocos"])


def test_art_58_xviii_quinze_dias(por_id):
    a = por_id["art-58"]
    xviii = _bloco(a, "XVIII –")
    assert xviii["tipo"] == "inciso"
    assert xviii["texto"].startswith("prestar, à Câmara, obrigatoriamente, dentro de quinze dias,")
    assert xviii["texto"].endswith("dos dados pleiteados;")
    # as duas notas de redação do inciso seguem o XVIII, fora do texto
    i = a["blocos"].index(xviii)
    notas = [n["texto"] for n in a["notas"] if n["bloco"] == i]
    assert len(notas) == 2 and all(t.startswith("Inciso com redação dada") for t in notas)
    assert a["secao"] == "SEÇÃO I — DAS ATRIBUIÇÕES DO PREFEITO"
    assert a["capitulo"] == "CAPÍTULO ÚNICO — DO PREFEITO E DO VICE-PREFEITO"


def test_art_1(por_id):
    a = por_id["art-1"]
    assert a["blocos"][0]["rotulo"] == "Art. 1º"
    assert a["blocos"][0]["texto"].startswith("O Município de Santos, em união indissolúvel ao "
                                              "Estado de São Paulo")
    assert a["titulo_sup"] == "TÍTULO I — DISPOSIÇÕES PRELIMINARES"
    assert a["secao"] == "SEÇÃO I — DOS PRINCÍPIOS FUNDAMENTAIS"
    assert [b["rotulo"] for b in a["blocos"]] == [
        "Art. 1º", "§ 1º", "§ 2º", "I –", "II –", "III –", "IV –", "V –", "VI –", "VII –",
        "§ 3º", "I –", "II –", "III –", "IV –"]
    # a quebra de página (nº 1) no meio do § 2º não deixa rastro
    assert a["blocos"][9]["texto"] == "pela ação fiscalizadora sobre a Administração Pública."
    assert a["notas"] == [{"bloco": 11, "texto": (
        "Inciso com redação dada pela Emenda à Lei Orgânica nº 13, de 19 de abril de 1993 "
        "(Jornal “A Tribuna de 24/04/1993).")}]


def test_notas_nunca_no_texto(artigos):
    for a in artigos:
        for b in a["blocos"]:
            assert not lom.RE_NOTA.search(b["texto"]), (a["id"], b["rotulo"])
            assert lom.MARCADOR_NOTA not in b["texto"]
        for n in a["notas"]:
            assert lom.RE_NOTA.search(n["texto"]), (a["id"], n["texto"])
            assert n["bloco"] is None or 0 <= n["bloco"] < len(a["blocos"])
    assert lom.conferir(artigos) == []


def test_nota_depois_de_cabecalho_fica_com_o_artigo_seguinte(por_id):
    # "SEÇÃO II / DA GUARDA CIVIL MUNICIPAL / • Título com denominação alterada…"
    a70 = por_id["art-70"]
    assert a70["secao"] == "SEÇÃO II — DA GUARDA CIVIL MUNICIPAL"
    assert a70["notas"][0]["bloco"] is None
    assert a70["notas"][0]["texto"].startswith("Título com denominação alterada")
    assert por_id["art-69"]["notas"][-1]["texto"].startswith("Artigo com redação dada")


def test_rotulos_e_casos_do_pdf(por_id):
    assert por_id["art-10"]["blocos"][0]["rotulo"] == "Art. 10."
    # "Art. 56 O Prefeito" (sem pontuação no PDF) e "Artigo 59." abrem artigo
    assert por_id["art-56"]["blocos"][0]["rotulo"] == "Art. 56."
    assert por_id["art-56"]["blocos"][0]["texto"].startswith("O Prefeito e o Vice-Prefeito não poderão")
    assert por_id["art-59"]["blocos"][0]["texto"].startswith("A Câmara, tomando conhecimento")
    assert por_id["art-56-a"]["blocos"][0]["rotulo"] == "Art. 56-A."
    a73 = por_id["art-73"]
    rotulos = [b["rotulo"] for b in a73["blocos"] if b["tipo"] == "paragrafo"]
    assert rotulos[:6] == ["§ 1º", "§ 2º", "§ 3º", "§ 4º", "§ 4º-A.", "§ 5º"]
    assert "§ 10." in rotulos and "§ 15." in rotulos
    assert _bloco(por_id["art-4"], "Parágrafo único.")["texto"].startswith("Qualquer alteração territorial")
    # "Parágrafo Único." e o texto na linha de baixo
    assert _bloco(por_id["art-99"], "Parágrafo único.")["texto"].startswith("O Município manterá órgãos")
    # "IX –" sozinho na linha, texto embaixo
    assert _bloco(por_id["art-20"], "IX –")["texto"] == "autorizar planos e programas municipais de desenvolvimento;"
    assert por_id["art-167"]["blocos"][0]["texto"].startswith("O Município direcionará esforços")
    a115 = [b["rotulo"] for b in por_id["art-115"]["blocos"] if b["tipo"] == "paragrafo"]
    assert a115[:4] == ["§ 1º", "§ 2º", "§ 2º-A.", "§ 2º-B."] and "§ 2º-K." in a115
    assert por_id["art-83"]["blocos"][0]["texto"] == "REVOGADO."


def test_texto_corrido_sem_residuos(artigos, por_id):
    # palavra partida no hífen junta sem espaço; nº de página no meio da frase some
    assert "reunir-se-ão sob a presidência" in por_id["art-26"]["blocos"][0]["texto"]
    assert "far-se-á eleição" in por_id["art-55"]["blocos"][0]["texto"]
    assert ("Concessionárias de Serviços Públicos para que, no prazo de 8 (oito) dias"
            in por_id["art-22"]["blocos"][0]["texto"])
    todo = " ".join(b["texto"] for a in artigos for b in a["blocos"])
    for lixo in ("fonte:", "baixado_em", "PREÂMBULO", "Sala das Sessões", "BONAVIDES", "  "):
        assert lixo not in todo
    # a última nota não engole as assinaturas
    assert por_id["adt-art-21"]["notas"][-1]["texto"].endswith("(DOM de 20/09/2017).")


def test_disposicoes_transitorias(por_id):
    a = por_id["adt-art-1"]
    assert a["adt"] is True and a["numero"] == "1"
    assert a["titulo_sup"] == "TÍTULO VIII — DISPOSIÇÕES TRANSITÓRIAS"
    assert "adt" in a["texto_busca"].split()
    assert por_id["art-1"]["adt"] is False


def test_secao_sem_numero(por_id):
    # "CAPÍTULO I / DA POLÍTICA ECONÔMICA / DISPOSIÇÕES GERAIS" → seção sem número
    a = por_id["art-128"]
    assert a["capitulo"] == "CAPÍTULO I — DA POLÍTICA ECONÔMICA"
    assert a["secao"] == "DISPOSIÇÕES GERAIS"
    assert por_id["art-101"]["secao"] == "PRINCÍPIOS GERAIS"
    assert por_id["art-115"]["secao"] == "SEÇÃO I"


def test_indice_publicado_em_dia(artigos):
    # mexeu na fonte ou no parser? regere: python regimento/lei_organica.py
    with open(lom.SAIDA, encoding="utf-8") as f:
        assert json.load(f) == artigos


def test_opcoes_em_texto_sintetico():
    texto = "\n".join([
        "---", "fonte: x", "---", "# LEI", "PREÂMBULO", "Texto do preâmbulo.",
        "TÍTULO I", "DISPOSIÇÕES", "PRELIMINARES", "CAPÍTULO I", "DA ORDEM", "PRINCÍPIOS GERAIS",
        "Art. 1º O Município", "    7", "", "de Santos reunir-", "se-á.",
        "§ 2º-A. Texto do parágrafo;", lom.MARCADOR_NOTA,
        "Parágrafo acrescido pela Emenda à Lei Orgânica nº 1, de 01 de", "janeiro de 2000 (DOM de 02/01/2000).",
        "IX –", "autorizar algo;",
        lom.MARCADOR_NOTA + "Inciso com redação dada pela Emenda à Lei Orgânica nº 2 (DOM de 03/01/2000).",
        "TÍTULO II", "DISPOSIÇÕES TRANSITÓRIAS",
        "Art. 1º Fica revogado.", "Sala das Sessões, em 05 de abril de 1990.", "FULANO DE TAL",
    ])
    a, b = lom.parse(texto)
    assert a["id"] == "art-1" and b["id"] == "adt-art-1"
    assert a["titulo_sup"] == "TÍTULO I — DISPOSIÇÕES PRELIMINARES"
    assert a["capitulo"] == "CAPÍTULO I — DA ORDEM" and a["secao"] == "PRINCÍPIOS GERAIS"
    assert a["blocos"] == [
        {"tipo": "caput", "rotulo": "Art. 1º", "texto": "O Município de Santos reunir-se-á."},
        {"tipo": "paragrafo", "rotulo": "§ 2º-A.", "texto": "Texto do parágrafo;"},
        {"tipo": "inciso", "rotulo": "IX –", "texto": "autorizar algo;"},
    ]
    assert a["notas"] == [
        {"bloco": 1, "texto": "Parágrafo acrescido pela Emenda à Lei Orgânica nº 1, de 01 de "
                              "janeiro de 2000 (DOM de 02/01/2000)."},
        {"bloco": 2, "texto": "Inciso com redação dada pela Emenda à Lei Orgânica nº 2 (DOM de 03/01/2000)."},
    ]
    assert b["adt"] is True and b["blocos"][0]["texto"] == "Fica revogado." and b["notas"] == []
