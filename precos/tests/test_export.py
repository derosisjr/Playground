# -*- coding: utf-8 -*-
"""Estatística e guardas do export.

Com 5 a 15 observações, média e desvio-padrão são teatro. Os testes aqui fixam
as três promessas do painel: mediana em vez de média, silêncio quando `n` é
pequeno, e nenhuma mistura entre preço estimado e homologado.
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import export  # noqa: E402
import ipca as ipca_mod  # noqa: E402


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
