# -*- coding: utf-8 -*-
"""Busca por item (`achar.py`).

Três propriedades a proteger, todas descobertas testando com dado real:

  1. o ranqueamento por posição, sem o qual buscar "agulha" devolve máquinas de
     costura (a palavra aparece no fundo do spec);
  2. a contagem de embalagem só vale quando a unidade cobrada É a embalagem —
     propor conversão num item já vendido por unidade dividiria o preço por 100;
  3. o rascunho nasce estéril: sem termos, sem confirmados, não publicado.
"""
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import achar  # noqa: E402
import crawler  # noqa: E402
import texto  # noqa: E402

NCP_SANTOS = "58200015000183-1-000011/2026"
NCP_PAR = "44959021000104-1-000138/2025"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(crawler.SCHEMA)
    for ncp, ibge, cnpj, seq in ((NCP_SANTOS, "3548500", "58200015000183", 11),
                                 (NCP_PAR, "3518701", "44959021000104", 138)):
        c.execute("INSERT INTO contratacao(ncp,ibge,cnpj,ano,sequencial,modalidade,"
                  "srp,itens_status,data_publicacao,modalidade_nome,objeto) "
                  "VALUES (?,?,?,2026,?,6,0,'ok','2026-02-01','Pregão','compra)')",
                  (ncp, ibge, cnpj, seq))
    return c


def _item(c, ncp, n, desc, un, un_norm, fator, ms="M", tem_res=1, qtd=100.0):
    c.execute(
        "INSERT INTO item(ncp,numero_item,descricao,descricao_norm,material_ou_servico,"
        "quantidade,unidade_medida,unidade_norm,fator_canonico,valor_unitario_estimado,"
        "situacao_item,tem_resultado,resultado_status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,'Homologado',?,'nao_pedido')",
        (ncp, n, desc, texto.normalizar(desc), ms, qtd, un, un_norm, fator, 1.0, tem_res))


# ── ranqueamento ────────────────────────────────────────────────────────────

def test_relevancia_premia_o_titulo():
    d = texto.normalizar("AGULHA DESCARTÁVEL 40X12 - Especificação: aço inox")
    assert achar.relevancia(d, ["agulha"]) == 3


def test_relevancia_rebaixa_mencao_no_corpo_do_spec():
    """Máquina de costura menciona 'agulha' no fim do spec — não é o produto."""
    d = texto.normalizar(
        "MAQUINA DE COSTURA INDUSTRIAL - Especificação: máquina reta eletrônica, "
        + "motor direct drive, " * 12 + "com kit de agulha")
    assert achar.relevancia(d, ["agulha"]) <= 1


def test_relevancia_negativa_quando_falta_termo():
    d = texto.normalizar("CADEIRA GIRATÓRIA COM RODÍZIOS")
    assert achar.relevancia(d, ["cadeira", "rodas"]) == -1


def test_busca_exige_todos_os_termos(conn):
    _item(conn, NCP_SANTOS, 1, "AGULHA DESCARTAVEL 40X12", "UN", "un", 1.0)
    _item(conn, NCP_SANTOS, 2, "AGULHA GENGIVAL LONGA", "UN", "un", 1.0)
    assert len(achar.buscar(conn, ["agulha"])) == 2
    assert len(achar.buscar(conn, ["agulha", "gengival"])) == 1


# ── contagem de embalagem ───────────────────────────────────────────────────

DESC_CAIXA = texto.normalizar(
    "AGULHA DESCARTAVEL 40X12, ESTERIL, CAIXA COM 100 UNIDADES")


def test_contagem_vale_quando_a_unidade_e_a_embalagem():
    assert achar.contagem_declarada(DESC_CAIXA, "CX") == 100


def test_contagem_ignorada_quando_a_unidade_ja_e_a_grandeza_final():
    """Item vendido por UNIDADE cuja descrição cita a caixa de entrega.

    Propor conversão aqui dividiria o preço por 100 — erro de duas ordens de
    grandeza, exatamente a classe que o módulo existe para evitar.
    """
    assert achar.contagem_declarada(DESC_CAIXA, "UNI") is None
    assert achar.contagem_declarada(DESC_CAIXA, "KG") is None


def test_contagem_nao_arrisca_em_unidade_desconhecida():
    """Sem saber a família, não se propõe fator — o rascunho apenas reporta."""
    assert achar.contagem_declarada(DESC_CAIXA, "XPTO") is None
    assert achar.contagem_declarada(DESC_CAIXA) == 100   # sem unidade: só detecta


def test_separador_de_milhar_vira_o_numero_certo():
    """`texto.normalizar` iguala '5,000' e '5.000' — a regra tem de ser posicional."""
    assert achar.contagem_declarada(texto.normalizar("CX COM 5.000 UN"), "CX") == 5000
    assert achar.contagem_declarada(texto.normalizar("cx com 1.000 folhas"), "CX") == 1000


def test_contagem_fracionaria_e_recusada():
    assert achar.contagem_declarada(texto.normalizar("CX COM 2.5 UN"), "CX") is None


def test_contagem_unitaria_nao_vira_conversao():
    assert achar.contagem_declarada(texto.normalizar("CX COM 1 UN"), "CX") is None


# ── funil ───────────────────────────────────────────────────────────────────

def test_funil_nunca_e_mais_estreito_que_os_gates(conn):
    """O funil é TETO: pode superestimar, nunca subestimar.

    Se ele subestimasse, o curador descartaria comparações viáveis sem saber.
    """
    _item(conn, NCP_SANTOS, 1, "AGULHA DESCARTAVEL 40X12", "UN", "un", 1.0)
    for i, (desc, un, norm) in enumerate([
            ("AGULHA DESCARTAVEL 40X12 ESTERIL", "UN", "un"),
            ("AGULHA DESCARTAVEL 40X12 CX C/100", "CX", "caixa"),   # cai na unidade
            ("AGULHA GENGIVAL LONGA", "UN", "un"),                   # cai no texto
    ], start=1):
        _item(conn, NCP_PAR, i, desc, un, norm, 1.0)
    pares = [dict(r) for r in conn.execute(
        "SELECT i.*, c.ibge FROM item i JOIN contratacao c ON c.ncp=i.ncp "
        "WHERE c.ibge<>'3548500'")]
    a, b, c, cidades, perdidos = achar.funil(
        conn, pares, ["agulha", "40x12"], "un", "homologado")
    assert (a, b, c) == (2, 1, 1)
    assert perdidos["CX"] == 1


def test_funil_conta_cidades_distintas(conn):
    _item(conn, NCP_SANTOS, 1, "COPO DESCARTAVEL 200ML", "UN", "un", 1.0)
    conn.execute("INSERT INTO contratacao(ncp,ibge,cnpj,ano,sequencial,modalidade,"
                 "srp,itens_status,data_publicacao) VALUES "
                 "('OUTRA-1-000001/2026','3541000','1',2026,1,6,0,'ok','2026-01-01')")
    _item(conn, NCP_PAR, 1, "COPO DESCARTAVEL 200ML", "UN", "un", 1.0)
    _item(conn, "OUTRA-1-000001/2026", 1, "COPO DESCARTAVEL 200ML", "UN", "un", 1.0)
    pares = [dict(r) for r in conn.execute(
        "SELECT i.*, c.ibge FROM item i JOIN contratacao c ON c.ncp=i.ncp "
        "WHERE c.ibge<>'3548500'")]
    *_, cidades, _ = achar.funil(conn, pares, ["copo"], "un", "homologado")
    assert cidades == 2


def test_veredicto_denuncia_teto_alto():
    """Teto grande é sintoma de termo genérico, não de comparação pronta."""
    assert "genéricos" in achar.veredicto(achar.TETO_SUSPEITO + 1, 5)
    assert "insuficiente" in achar.veredicto(1, 1)
    assert achar.veredicto(6, 4) == "dá mediana e extrapolação"


# ── rascunho ────────────────────────────────────────────────────────────────

def _santos(conn):
    return dict(conn.execute("SELECT i.*, c.ano FROM item i JOIN contratacao c "
                             "ON c.ncp=i.ncp WHERE i.ncp=? AND i.numero_item=1",
                             (NCP_SANTOS,)).fetchone())


def test_rascunho_nasce_esteril(conn):
    _item(conn, NCP_SANTOS, 1, "AGULHA DESCARTAVEL 40X12", "UN", "un", 1.0)
    d = achar.montar_rascunho(_santos(conn), ["agulha"], "Saúde", "x")
    assert d["publicada"] is False and d["publicada_em"] is None
    assert d["termos"] == {"obrigatorios": [], "algum_de": [], "excluir": []}
    assert d["revisao"]["confirmados"] == [] and d["revisao"]["rejeitados"] == []
    assert d["rascunho"]["revisar"]           # a lista do que conferir não é vazia
    assert d["nota_metodologica"].startswith("RASCUNHO")


def test_rascunho_propoe_conversao_so_quando_cabe(conn):
    _item(conn, NCP_SANTOS, 1,
          "AGULHA DESCARTAVEL 40X12, CAIXA COM 100 UNIDADES", "CX", "caixa", 1.0)
    d = achar.montar_rascunho(_santos(conn), ["agulha"], None, "x")
    assert d["conversoes_extra"] == {"CX": 100}
    assert any("CONFERIR" in r or "conferir" in r for r in d["rascunho"]["revisar"])


def test_rascunho_nao_propoe_conversao_para_item_ja_unitario(conn):
    _item(conn, NCP_SANTOS, 1,
          "AGULHA DESCARTAVEL 40X12, CAIXA COM 100 UNIDADES", "UNI", "un", 1.0)
    d = achar.montar_rascunho(_santos(conn), ["agulha"], None, "x")
    assert d["conversoes_extra"] == {}


def test_rascunho_e_json_valido_no_formato_da_casa(conn):
    _item(conn, NCP_SANTOS, 1, "AGULHA DESCARTAVEL 40X12", "UN", "un", 1.0)
    d = achar.montar_rascunho(_santos(conn), ["agulha"], "Saúde", "x")
    recarregado = json.loads(json.dumps(d, ensure_ascii=False))
    for chave in ("slug", "titulo", "tema", "publicada", "santos", "unidade_canonica",
                  "conversoes_extra", "termos", "material_ou_servico", "srp", "numeros",
                  "faixa_quantidade", "janela_meses", "modalidades", "cidades",
                  "correcao", "revisao", "nota_metodologica"):
        assert chave in recarregado, chave
    assert recarregado["santos"]["itens"] == [1]
