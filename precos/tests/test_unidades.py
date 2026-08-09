# -*- coding: utf-8 -*-
"""Unidade de medida — o gate que impede comparar R$/m² com R$/unidade."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unidades  # noqa: E402


@pytest.mark.parametrize("bruto", ["M2", "MT2", "m²", "METRO QUADRADO", "mts2"])
def test_sinonimos_de_metro_quadrado(bruto):
    assert unidades.normalizar_unidade(bruto) == ("m2", 1)


def test_caixa_com_n_vira_fator():
    assert unidades.normalizar_unidade("CX C/100") == ("un", 100.0)
    assert unidades.normalizar_unidade("CAIXA COM 12") == ("un", 12.0)


def test_quantidade_embutida_em_volume_e_massa():
    assert unidades.normalizar_unidade("FRASCO 500ML") == ("l", 0.5)
    assert unidades.normalizar_unidade("SACO 5KG") == ("kg", 5.0)


def test_contagem_embutida_na_unidade_de_fornecimento():
    """'Pacote 100,00 FL' caía no fallback e virava ('un', 1) — erro de 100×."""
    assert unidades.normalizar_unidade("Pacote 100,00 FL") == ("un", 100.0)
    assert unidades.normalizar_unidade("Pacote 500,00 FL") == ("un", 500.0)
    assert unidades.normalizar_unidade("PACOTE (DE 25 PANOS)") == ("un", 25.0)


def test_separador_de_milhar_na_unidade():
    """'normalizar' iguala '5,000' e '5.000': a regra tem de ser posicional."""
    assert unidades.normalizar_unidade("CX COM 5.000 UND") == ("un", 5000.0)
    assert unidades.normalizar_unidade("PACOTE (DE 1.000 FOLHAS)") == ("un", 1000.0)


def test_fallback_recusa_quando_ha_contagem_nao_interpretada():
    """Política: contagem presente mas ilegível → recusa, nunca fator 1.

    Devolver 1 aqui publicaria o preço da embalagem como o preço da unidade.
    O sufixo é propositalmente inventado: o que se fixa é a REGRA, não a lista
    de embalagens conhecidas — essa cresce com caso real conferido.
    """
    assert unidades.normalizar_unidade("Xepa 7,00 ZZ") == (None, None)
    assert unidades.normalizar_unidade("Bandeja 12,00 QQ") == (None, None)


def test_embalagem_com_grandeza_declarada_converte():
    """Contagem + sufixo conhecido: converte de verdade, não só deixa de errar."""
    assert unidades.normalizar_unidade("Ampola 2,00 ML") == ("l", 0.002)
    assert unidades.normalizar_unidade("Rolo 100,00 M") == ("m", 100.0)
    assert unidades.normalizar_unidade("Garrafão 20,00 L") == ("l", 20.0)


def test_fallback_continua_valendo_para_unidade_com_digito_no_nome():
    """'m2'/'m3' têm dígito no NOME — não confundir com contagem."""
    assert unidades.normalizar_unidade("m2 instalado") == ("m2", 1)
    assert unidades.normalizar_unidade("un fornecida") == ("un", 1)


def test_quantidade_zero_na_embalagem_nao_vira_fator_zero():
    """Edital mal digitado ('FRASCO 0ML') não pode gerar divisão por zero."""
    assert unidades.normalizar_unidade("FRASCO 0ML") == (None, None)
    assert unidades.normalizar_unidade("CX C/0") == (None, None)
    assert unidades.converter("FRASCO 0ML", "l") is None


def test_unidade_desconhecida_devolve_none_em_vez_de_chutar():
    assert unidades.normalizar_unidade("XPTO") == (None, None)
    assert unidades.normalizar_unidade("") == (None, None)
    assert unidades.converter("XPTO", "m2") is None


def test_familias_diferentes_nunca_convertem():
    assert unidades.converter("UN", "m2") is None
    assert unidades.converter("KG", "m") is None
    assert unidades.converter("MES", "dia") is None   # mês de locação ≠ 30 diárias


def test_opacas_nunca_convertem():
    """VERBA/LOTE/SERVIÇO escondem a quantidade real — jamais viram preço unitário."""
    for op in ("VERBA", "LOTE", "SERVICO", "GLOBAL"):
        assert unidades.converter(op, "m2") is None
        assert unidades.converter(op, "un") is None


def test_conversao_dentro_da_familia():
    assert unidades.converter("CM", "m") == 0.01
    assert unidades.converter("TONELADA", "kg") == 1000
    assert unidades.converter("M3", "l") == 1000
    assert unidades.converter("ML", "m") == 1     # ML = metro linear em obras


def test_embalagem_sem_quantidade_nao_vira_unidade():
    """CX sem contagem pode ter 10 ou 100 itens — comparar com `un` seria inventar."""
    assert unidades.normalizar_unidade("CX") == ("caixa", 1)
    assert unidades.converter("CX", "un") is None
    assert unidades.converter("CAIXA", "caixa") == 1
    assert unidades.converter("FRS", "un") is None
    assert unidades.converter("Frasco", "frasco") == 1


def test_lt_continua_litro_e_lta_e_lata():
    """Abreviações vizinhas: LT (litro) é muito mais comum que lata."""
    assert unidades.normalizar_unidade("LT") == ("l", 1)
    assert unidades.normalizar_unidade("LTA") == ("lata", 1)


def test_grafias_do_pncp():
    assert unidades.normalizar_unidade("Kilograma") == ("kg", 1)
    assert unidades.normalizar_unidade("MetroQuadrado") == ("m2", 1)
    assert unidades.normalizar_unidade("Embalagem 500,00 G") == ("kg", 0.5)


def test_outras_unidades_e_srv_sao_opacas():
    assert unidades.converter("OUTRAS UNIDADES", "un") is None
    assert unidades.converter("SRV", "un") is None


def test_par_e_duzia_convertem_para_unidade():
    assert unidades.converter("PAR", "un") == 2
    assert unidades.converter("DUZIA", "un") == 12
    assert unidades.converter("MILHEIRO", "un") == 1000
