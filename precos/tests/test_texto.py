# -*- coding: utf-8 -*-
"""Normalização e tokenização — a base do casamento textual."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import texto  # noqa: E402


def test_sem_acento_e_caixa():
    assert texto.normalizar("PLACAS DE METALON COM ILUMINAÇÃO") == \
        "placas de metalon com iluminacao"


def test_superscrito_vira_digito():
    assert "m2" in texto.normalizar("Área de 10 M²")


def test_abreviacao_com_barra():
    n = texto.normalizar("CX C/100 UN")
    assert "com" in n and "c 100" not in n


def test_abreviacao_exige_fronteira_de_palavra():
    """Sem fronteira, `replace("s/", "sem")` parte qualquer palavra em -s + barra.

    Media 2% das descrições do espelho: 'criticos/graves' virava 'critico sem
    graves', inventando um token e apagando o certo.
    """
    assert texto.normalizar("pacientes criticos/graves") == "pacientes criticos graves"
    assert texto.normalizar("copos/talheres") == "copos talheres"
    assert texto.normalizar("registro MS/ANVISA") == "registro ms anvisa"
    # e a abreviação de verdade continua funcionando
    assert texto.normalizar("papel A4 p/ impressora") == "papel a4 para impressora"
    assert texto.normalizar("caixa c/ tampa") == "caixa com tampa"


def test_virgula_decimal_preservada_entre_digitos():
    assert "1.5" in texto.normalizar("espessura 1,5 mm")


def test_pontuacao_final_nao_vira_decimal():
    assert texto.normalizar("placa.") == "placa"


def test_tokens_descartam_stopword_mas_mantem_alfanumerico():
    t = texto.tokens("PAPEL SULFITE A4 75G PARA IMPRESSORA")
    assert "para" not in t          # stopword
    assert "a4" in t and "75g" in t  # curtos, mas com dígito: discriminantes
    assert "papel" in t and "sulfite" in t


def test_jaccard_extremos():
    a = texto.tokens("placa metalon lona")
    assert texto.jaccard(a, a) == 1.0
    assert texto.jaccard(a, texto.tokens("cadeira giratoria")) == 0.0
    assert texto.jaccard(a, set()) == 0.0


def test_contem_respeita_fronteira_de_palavra():
    d = texto.normalizar("PLACA EM LONA IMPRESSA")
    assert texto.contem(d, "lona")
    assert texto.contem(d, "placa")
    assert not texto.contem(d, "ona")     # não casa no meio da palavra


def test_contem_tolera_plural_simples():
    d = texto.normalizar("PLACAS DE METALON")
    assert texto.contem(d, "placa")


def test_contem_termo_multipalavra():
    d = texto.normalizar("PLACA DE SINALIZACAO VIARIA REFLETIVA")
    assert texto.contem(d, "sinalizacao viaria")
    assert not texto.contem(d, "sinalizacao predial")


def test_sem_stemming_nao_aproxima_palavras_diferentes():
    # 'papel' e 'papelaria' NÃO podem colidir: seria falso positivo silencioso
    assert not texto.contem(texto.normalizar("MATERIAL DE PAPELARIA"), "papel")
