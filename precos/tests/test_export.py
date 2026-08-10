# -*- coding: utf-8 -*-
"""Estatística e guardas do export.

Com 5 a 15 observações, média e desvio-padrão são teatro. Os testes aqui fixam
as três promessas do painel: mediana em vez de média, silêncio quando `n` é
pequeno, e nenhuma mistura entre preço estimado e homologado.
"""
import os
import sqlite3
import statistics
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crawler  # noqa: E402
import export  # noqa: E402
import ipca as ipca_mod  # noqa: E402
import texto  # noqa: E402


def _obs(precos, cidades=None, datas=None):
    cidades = cidades or [f"35000{i:02d}" for i in range(len(precos))]
    datas = datas or ["2025-06-01"] * len(precos)
    return [{"preco": p, "ibge": c, "data": d, "preco_corrigido": None}
            for p, c, d in zip(precos, cidades, datas)]


def test_mediana_e_nao_media():
    """Um outlier sobrevivente não pode arrastar a referência."""
    e = export._estatistica(_obs([100.0, 110.0, 120.0, 900.0]), "2026-06")
    assert e["mediana"] == 115.0
    assert e["mediana"] != statistics.mean([100, 110, 120, 900])


def test_min_max_e_contagem_de_cidades():
    e = export._estatistica(
        _obs([100.0, 110.0, 120.0], cidades=["3518701", "3518701", "3541000"]),
        "2026-06")
    assert (e["n"], e["n_cidades"]) == (3, 2)
    assert (e["min"], e["max"]) == (100.0, 120.0)


def test_quartis_so_com_amostra_suficiente():
    """Quartil com n=4 seria ruído com cara de precisão."""
    assert export._estatistica(_obs([1.0, 2.0, 3.0, 4.0]), "2026-06")["q1"] is None
    e = export._estatistica(_obs([float(i) for i in range(1, 11)]), "2026-06")
    assert e["q1"] is not None and e["q3"] is not None


def test_mediana_corrigida_so_quando_todas_as_pontas_existem():
    """Corrigir metade da amostra produziria uma mediana híbrida, sem significado."""
    obs = _obs([100.0, 110.0, 120.0])
    obs[0]["preco_corrigido"] = 105.0          # só uma corrigida
    e = export._estatistica(obs, "2026-06")
    assert e["mediana_corrigida"] is None and e["base_correcao"] is None
    for o, v in zip(obs, [105.0, 115.0, 126.0]):
        o["preco_corrigido"] = v
    e = export._estatistica(obs, "2026-06")
    assert e["mediana_corrigida"] == 115.0 and e["base_correcao"] == "2026-06"


def test_amostra_vazia_nao_quebra():
    e = export._estatistica([], "2026-06")
    assert e["n"] == 0 and e["mediana"] is None and e["data_min"] is None


def test_fator_ipca_conhecido():
    serie = {"2025-01": 100.0, "2026-06": 110.0}
    assert ipca_mod.fator(serie, "2025-01", "2026-06") == 1.1


def test_fator_ipca_ausente_devolve_none_em_vez_de_chutar():
    serie = {"2025-01": 100.0}
    assert ipca_mod.fator(serie, "2025-01", "2026-06") is None
    assert export._corrigir(serie, 100.0, "2019-01-05", "2026-06") is None
    assert export._corrigir(None, 100.0, "2025-01-05", "2026-06") is None


def test_corrigir_aplica_o_fator():
    serie = {"2025-01": 100.0, "2026-06": 110.0}
    assert export._corrigir(serie, 200.0, "2025-01-20", "2026-06") == 220.0


def test_limiares_do_modo_e_da_extrapolacao():
    """Os números que governam o silêncio do painel não podem mudar sem teste."""
    assert export.N_MINIMO_MEDIANA == 3
    assert export.N_MIN_QUARTIS == 8
    assert (export.N_MIN_EXTRAPOLACAO, export.CIDADES_MIN_EXTRAPOLACAO) == (5, 3)


def test_resumo_sem_comparacao_com_mediana():
    txt = export._resumo([{"modo": "referencias_pontuais", "titulo": "X",
                           "razao": None, "delta_pct": None, "pares": {}}])
    assert "Nenhuma comparação" in txt


def test_resumo_narra_o_pior_caso():
    comps = [
        {"modo": "mediana", "titulo": "Placas", "razao": 2.3, "delta_pct": 130.0,
         "pares": {"n": 9, "n_cidades": 5}},
        {"modo": "mediana", "titulo": "Papel", "razao": 0.9, "delta_pct": -10.0,
         "pares": {"n": 6, "n_cidades": 4}},
    ]
    txt = export._resumo(comps)
    assert "Placas" in txt and "1 de 2" in txt


# ── catálogo "O que Santos comprou" ─────────────────────────────────────────

NCP_A = "58200015000183-1-000011/2026"
NCP_B = "49203409000102-1-000005/2026"


@pytest.fixture
def conn_cat():
    """Espelho mínimo com dois órgãos municipais de Santos."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(crawler.SCHEMA)
    for ncp, cnpj, seq, razao in ((NCP_A, "58200015000183", 11, "MUNICIPIO DE SANTOS"),
                                  (NCP_B, "49203409000102", 5, "CAMARA MUNICIPAL")):
        c.execute("INSERT INTO contratacao(ncp,ibge,cnpj,razao_social,ano,sequencial,"
                  "modalidade,modalidade_nome,srp,itens_status,data_publicacao) VALUES "
                  "(?,'3548500',?,?,2026,?,6,'Pregão - Eletrônico',0,'ok','2026-02-01')",
                  (ncp, cnpj, razao, seq))
    return c


def _item_cat(c, ncp, n, desc, situacao="Homologado", status="ok"):
    c.execute(
        "INSERT INTO item(ncp,numero_item,descricao,descricao_norm,quantidade,"
        "unidade_medida,unidade_norm,fator_canonico,valor_unitario_estimado,"
        "situacao_item,tem_resultado,resultado_status) "
        "VALUES (?,?,?,?,100,'UN','un',1,9.9,?,1,?)",
        (ncp, n, desc, texto.normalizar(desc), situacao, status))


def _res_cat(c, ncp, n, valor, data="2026-03-01"):
    c.execute("INSERT INTO resultado VALUES (?,?,1,?,?,1,'1','FORN LTDA','ME',?,"
              "'Homologado',1)", (ncp, n, valor, valor, data))


def test_catalogo_so_com_preco_homologado(conn_cat):
    """Item em andamento tem só a estimativa do edital — teto, não preço pago."""
    _item_cat(conn_cat, NCP_A, 1, "PAPEL A4 75G")
    _res_cat(conn_cat, NCP_A, 1, 17.9)
    _item_cat(conn_cat, NCP_A, 2, "CANETA AZUL", status="nao_pedido")   # sem preço
    cat = export.catalogo(conn_cat)
    assert len(cat["linhas"]) == 1
    assert cat["linhas"][0][0] == "PAPEL A4 75G"


def test_catalogo_descarta_situacao_invalida(conn_cat):
    _item_cat(conn_cat, NCP_A, 1, "PAPEL A4", situacao="Cancelado")
    _res_cat(conn_cat, NCP_A, 1, 17.9)
    assert export.catalogo(conn_cat)["linhas"] == []


def test_catalogo_trunca_descricao(conn_cat):
    _item_cat(conn_cat, NCP_A, 1, "X" * 400)
    _res_cat(conn_cat, NCP_A, 1, 1.0)
    assert len(export.catalogo(conn_cat)["linhas"][0][0]) == export.CATALOGO_DESC


def test_catalogo_identifica_o_orgao_comprador(conn_cat):
    """O espelho é varrido por IBGE, então 'Santos' inclui Câmara, fundações e
    autarquias — quem comprou precisa ser coluna, não nota de rodapé."""
    _item_cat(conn_cat, NCP_A, 1, "PAPEL A4")
    _res_cat(conn_cat, NCP_A, 1, 17.9)
    _item_cat(conn_cat, NCP_B, 1, "PAPEL A4")
    _res_cat(conn_cat, NCP_B, 1, 22.0)
    cat = export.catalogo(conn_cat)
    orgaos = {cat["orgaos"][l[8]] for l in cat["linhas"]}
    assert orgaos == {"MUNICIPIO DE SANTOS", "CAMARA MUNICIPAL"}


def test_catalogo_usa_lookup_para_valores_repetidos(conn_cat):
    """Órgão e modalidade são índices: guardar o texto 3.775 vezes custa ~200 KB."""
    for n in range(1, 4):
        _item_cat(conn_cat, NCP_A, n, f"ITEM {n}")
        _res_cat(conn_cat, NCP_A, n, 1.0 * n)
    cat = export.catalogo(conn_cat)
    assert len(cat["orgaos"]) == 1 and len(cat["modalidades"]) == 1
    assert all(isinstance(l[8], int) and isinstance(l[9], int) for l in cat["linhas"])


def test_catalogo_tem_ordem_estavel(conn_cat):
    """Sem ordenação fixa, o shard versionado gera diff a cada execução."""
    for n in range(1, 6):
        _item_cat(conn_cat, NCP_A, n, f"ITEM {n}")
        _res_cat(conn_cat, NCP_A, n, 1.0 * n, data=f"2026-03-0{n}")
    assert export.catalogo(conn_cat)["linhas"] == export.catalogo(conn_cat)["linhas"]


def test_catalogo_campos_batem_com_o_cabecalho(conn_cat):
    _item_cat(conn_cat, NCP_A, 1, "PAPEL A4")
    _res_cat(conn_cat, NCP_A, 1, 17.9)
    cat = export.catalogo(conn_cat)
    assert cat["campos"] == export.CAMPOS_CATALOGO
    assert all(len(l) == len(cat["campos"]) for l in cat["linhas"])
