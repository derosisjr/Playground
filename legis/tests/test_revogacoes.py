# -*- coding: utf-8 -*-
"""Inferência de revogação/alteração a partir da ementa oficial (sem rede).

As ementas abaixo são reais (Legis da Prefeitura de Santos, conferidas em 2026-10).
"""
import revogacoes as r
from revogacoes import ALTERA, REVOGA, REVOGA_PARCIAL

LO, LC, DEC = "Lei ordinária", "Lei complementar", "Decreto"


def vinc(texto):
    return [(v["relacao"], v["tipo"], v["numero"], v["ano"]) for v in r.extrair_vinculos(texto)]


# ── extração ─────────────────────────────────────────────────────────────────
def test_revoga_lei_inteira():
    # Lei 3.386/2017
    assert vinc("REVOGA A LEI Nº 2.182, DE 06 DE JANEIRO DE 2004.") == [(REVOGA, LO, "2182", 2004)]


def test_revoga_lei_complementar_com_oracao_relativa():
    # LC 1.019/2018: o "QUE INSTITUI..." descreve o alvo, não é outra ação
    t = ("REVOGA A LEI COMPLEMENTAR Nº 543, DE 04 DE OUTUBRO DE 2005, QUE INSTITUI NA "
         "SECRETARIA DA CÂMARA MUNICIPAL DE SANTOS A COMISSÃO DE AVALIAÇÃO DE DESEMPENHO "
         "FUNCIONAL  CADEF.")
    assert vinc(t) == [(REVOGA, LC, "543", 2005)]


def test_revoga_decreto_n_grau_e_sem_virgula():
    assert vinc("REVOGA O DECRETO N° 9.817, DE 27 DE SETEMBRO DE 2022, QUE OUTORGA ...") == \
        [(REVOGA, DEC, "9817", 2022)]
    assert vinc("REVOGA O DECRETO Nº 8.659 DE 17 DE OUTUBRO DE 2019 QUE OUTORGA PERMISSÃO") == \
        [(REVOGA, DEC, "8659", 2019)]


def test_quebra_de_linha_na_ementa():
    t = "REVOGA O DECRETO Nº 8.489, DE 24\nDE JUNHO DE 2019, QUE\nREORGANIZA, JUNTO À SECRETARIA"
    assert vinc(t) == [(REVOGA, DEC, "8489", 2019)]


def test_revoga_artigo_e_parcial():
    t = ("REVOGA O ARTIGO 2.º DA LEI N.º 1.803, DE 20 DE SETEMBRO DE 1999, QUE INSTITUI A "
         "SEMANA DA DOAÇÃO DE SANGUE NO MUNICÍPIO DE SANTOS.")
    assert vinc(t) == [(REVOGA_PARCIAL, LO, "1803", 1999)]
    assert vinc("Revoga dispositivo da Lei n.º 4.623, de 12 de junho de 1984, que dispõe") == \
        [(REVOGA_PARCIAL, LO, "4623", 1984)]
    assert vinc("REVOGA O PARÁGRAFO 1º DO ARTIGO 2º DA LEI Nº 2.873, DE 27 DE NOVEMBRO DE 2012") == \
        [(REVOGA_PARCIAL, LO, "2873", 2012)]


def test_dispositivo_de_um_e_outro_inteiro():
    # Decreto 9.798/2022: parcial para o 1º, total para o 2º
    t = ("REVOGA DISPOSITIVO DO DECRETO Nº 8.944, DE 23 DE ABRIL DE 2020, E O DECRETO Nº 9.706, "
         "DE 02 DE JUNHO DE 2022, E DÁ OUTRAS PROVIDÊNCIAS.")
    assert vinc(t) == [(REVOGA_PARCIAL, DEC, "8944", 2020), (REVOGA, DEC, "9706", 2022)]


def test_dois_decretos_inteiros():
    t = ("REVOGA O DECRETO Nº 6.482, DE 02 DE AGOSTO DE 2013 E O DECRETO Nº 11.060, DE 13 DE "
         "NOVEMBRO DE 2025, QUE OUTORGA PERMISSÃO DE USO")
    assert vinc(t) == [(REVOGA, DEC, "6482", 2013), (REVOGA, DEC, "11060", 2025)]


def test_altera_varias_leis_separadas_por_ponto_e_virgula():
    t = ("ACRESCENTA E ALTERA DISPOSITIVOS DA LEI COMPLEMENTAR Nº 1.187, DE 30 DEZEMBRO DE 2022; "
         "DA LEI COMPLEMENTAR Nº 1.087, DE 30 DE DEZEMBRO DE 2019; DA LEI COMPLEMENTAR Nº 53, "
         "DE 15 DE MAIO DE 1992, E DÁ OUTRAS PROVIDÊNCIAS.")
    assert vinc(t) == [(ALTERA, LC, "1187", 2022), (ALTERA, LC, "1087", 2019), (ALTERA, LC, "53", 1992)]


def test_verbos_encadeados_compartilham_o_objeto():
    # LC 930/2016 e Lei 3.253/2016
    assert set(vinc("ALTERA E REVOGA DISPOSITIVOS DA LEI Nº 3.529, DE 16 DE ABRIL DE 1968")) == \
        {(ALTERA, LO, "3529", 1968), (REVOGA_PARCIAL, LO, "3529", 1968)}
    t = ("REVOGA O INCISO V E DÁ NOVA REDAÇÃO AO INCISO VII DO ARTIGO 1º DA LEI Nº 2.949, "
         "DE 19 DE DEZEMBRO DE 2013.")
    assert set(vinc(t)) == {(REVOGA_PARCIAL, LO, "2949", 2013), (ALTERA, LO, "2949", 2013)}


def test_altera_depois_de_dispoe_sobre():
    t = ("DISPÕE SOBRE O SISTEMA PREVIDENCIÁRIO MUNICIPAL, ALTERA DISPOSITIVOS DA LEI "
         "COMPLEMENTAR Nº 592, DE 28 DE DEZEMBRO DE 2006, E DÁ OUTRAS PROVIDÊNCIAS.")
    assert vinc(t) == [(ALTERA, LC, "592", 2006)]


def test_mencoes_que_nao_sao_acao_desta_norma():
    # "JÁ ALTERADA PELA LEI 2.516" e "QUE REVOGOU A LEI 2.822" descrevem o alvo
    t = ("ALTERA DISPOSITIVOS DA LEI N.º 2.432, DE 22 DE DEZEMBRO DE 2006, JÁ ALTERADA PELA LEI "
         "N.º 2.516, DE 26 DE DEZEMBRO DE 2007, QUE AUTORIZA O PODER EXECUTIVO")
    assert vinc(t) == [(ALTERA, LO, "2432", 2006)]
    t = ("REVOGA A LEI Nº 2.939, DE 30 DE JULHO DE 1964, QUE REVOGOU A LEI Nº 2.822, DE 11 DE "
         "MARÇO DE 1964, VOLTANDO ESTA A TER VIGÊNCIA EM SEUS EXATOS TERMOS, POR REPRISTINAÇÃO.")
    assert vinc(t) == [(REVOGA, LO, "2939", 1964)]
    t = ("REVOGA DISPOSITIVOS DO DECRETO Nº 10.422, DE 26 DE ABRIL DE 2024, QUE DISPÕE ... NOS "
         "TERMOS DO ARTIGO 49 DA LEI COMPLEMENTAR Nº 1.253, DE 03 DE ABRIL DE 2024.")
    assert vinc(t) == [(REVOGA_PARCIAL, DEC, "10422", 2024)]


def test_ignora_lei_federal_organica_e_decreto_lei():
    assert vinc("ALTERA A LEI FEDERAL Nº 8.666, DE 21 DE JUNHO DE 1993") == []
    assert vinc("ALTERA A LEI ORGÂNICA Nº 85") == []
    assert vinc("REVOGA O DECRETO-LEI Nº 201, DE 27 DE FEVEREIRO DE 1967") == []


def test_sem_objeto_normativo():
    assert vinc("ALTERA DENOMINÇÃO DE VIA PÚBLICA QUE ESPECIFICA.") == []
    assert vinc("ESTIMA A RECEITA E FIXA A DESPESA DO MUNICÍPIO DE SANTOS PARA 2007.") == []
    assert vinc("") == []


def test_clausulas_do_corpo_do_texto():
    assert vinc("Art. 1.º Fica revogada a Lei n.º 1.799, de 09 de setembro de 1999.") == \
        [(REVOGA, LO, "1799", 1999)]
    assert vinc("Ficam revogadas as Leis nºs 1.234, de 1º de janeiro de 2001, e 2.345, "
                "de 2 de março de 2002.") == [(REVOGA, LO, "1234", 2001), (REVOGA, LO, "2345", 2002)]
    assert vinc("Revoga-se o Decreto nº 7.213/2015.") == [(REVOGA, DEC, "7213", 2015)]


# ── resolução e situação ─────────────────────────────────────────────────────
def _n(id_, tipo, numero, ano, descricao=""):
    return {"id": id_, "tipo": tipo, "numero": numero, "ano": ano, "descricao": descricao}


def test_situacao_revogada_com_revogadora():
    normas = [
        _n(1026, LO, "2.182", 2004, "PROÍBE A EXIGÊNCIA DE EXPERIÊNCIA MÍNIMA"),
        _n(6573, LO, "3.386", 2017, "REVOGA A LEI Nº 2.182, DE 06 DE JANEIRO DE 2004."),
    ]
    assert r.calcular_situacoes(normas) == {
        1026: {"situacao": "revogada", "revogada_por": 6573, "por": 6573}}


def test_alvo_fora_do_banco_ou_de_outro_ano_nao_marca_nada():
    normas = [
        _n(1, LO, "2.182", 2005),  # mesmo número, ano diferente
        _n(2, LO, "3.386", 2017, "REVOGA A LEI Nº 2.182, DE 06 DE JANEIRO DE 2004."),
    ]
    assert r.calcular_situacoes(normas) == {}


def test_sem_ano_so_resolve_numero_unico_e_anterior():
    rev = "REVOGA A LEI Nº 500."
    assert r.calcular_situacoes([_n(1, LO, "500", 1990), _n(2, LO, "900", 2000, rev)])[1]["situacao"] \
        == "revogada"
    # ambíguo (dois "500" no tipo) → não arrisca
    assert r.calcular_situacoes([_n(1, LO, "500", 1990), _n(3, LO, "500", 1991),
                                 _n(2, LO, "900", 2000, rev)]) == {}
    # alvo posterior à origem → impossível, ignora
    assert r.calcular_situacoes([_n(1, LO, "500", 2010), _n(2, LO, "900", 2000, rev)]) == {}


def test_precedencia_e_revogadora_mais_recente():
    normas = [
        _n(1, LC, "100", 2000),
        _n(2, LC, "200", 2005, "ALTERA DISPOSITIVOS DA LEI COMPLEMENTAR Nº 100, DE 1 DE MAIO DE 2000"),
        _n(3, LC, "300", 2010, "REVOGA O ARTIGO 5º DA LEI COMPLEMENTAR Nº 100, DE 1 DE MAIO DE 2000"),
        _n(4, LC, "400", 2012, "REVOGA O ARTIGO 6º DA LEI COMPLEMENTAR Nº 100, DE 1 DE MAIO DE 2000"),
    ]
    s = r.calcular_situacoes(normas)[1]
    assert s["situacao"] == "revogada parcialmente" and s["revogada_por"] == 4
    normas.append(_n(5, LC, "500", 2015, "REVOGA A LEI COMPLEMENTAR Nº 100, DE 1 DE MAIO DE 2000"))
    s = r.calcular_situacoes(normas)[1]
    assert s == {"situacao": "revogada", "revogada_por": 5, "por": 5}


def test_alterada_nao_tem_revogadora():
    normas = [_n(1, LO, "1.821", 1999),
              _n(2, LO, "2.420", 2006, "Altera dispositivos da Lei n.º 1.821, de 24 de novembro de 1999")]
    assert r.calcular_situacoes(normas)[1] == {"situacao": "alterada", "revogada_por": None, "por": 2}
