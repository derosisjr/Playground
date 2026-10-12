# -*- coding: utf-8 -*-
"""Custo por Resultado: dupla contagem do intraorçamentário e deflator IPCA.

1. A linha de topo 3.1.00.00.00 do DCA I-D soma a modalidade 91
   (intraorçamentária — sobretudo o patronal pago ao RPPS próprio). Contá-la
   infla o gasto com pessoal e pune quem tem RPPS próprio.
2. Comparar R$ de 2019 com R$ de 2025 sem deflator chama inflação de aumento
   de gasto: tudo em R$ do último ano, pelo IPCA médio anual.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import export  # noqa: E402
import fontes  # noqa: E402

COL = "Despesas Empenhadas"
# recorte real do DCA 2023 de Santos (I-D), valores em R$
ITENS_SANTOS_2023 = [
    {"conta": "3.0.00.00.00 - Despesas Correntes", "coluna": COL, "valor": 4151245275.39},
    {"conta": "3.1.00.00.00 - Pessoal e Encargos Sociais", "coluna": COL, "valor": 2129307233.81},
    {"conta": "3.1.90.00.00 - Aplicações Diretas", "coluna": COL, "valor": 1716085092.78},
    {"conta": "3.1.91.00.00 - Aplicação Direta Decorrente de Operação entre Órgãos, F",
     "coluna": COL, "valor": 413222141.03},
    {"conta": "3.1.91.00.00 - Aplicação Direta Decorrente de Operação entre Órgãos, F",
     "coluna": "Despesas Pagas", "valor": 1.0},
    {"conta": "4.4.00.00.00 - Investimentos", "coluna": COL, "valor": 371956200.57},
    {"conta": "4.4.90.00.00 - Aplicações Diretas", "coluna": COL, "valor": 364326759.76},
]


def test_conta_intra_troca_so_a_modalidade():
    assert fontes.conta_intra("3.1.00.00.00") == "3.1.91.00.00"
    assert fontes.conta_intra("4.4.00.00.00") == "4.4.91.00.00"


def test_pessoal_desconta_modalidade_91():
    v = fontes.valor_sem_intra(ITENS_SANTOS_2023, "3.1.00.00.00", COL)
    assert v == 1716085092.78  # = 3.1.90, não os R$ 2,13 bi da linha de topo


def test_sem_linha_91_nada_a_descontar():
    v = fontes.valor_sem_intra(ITENS_SANTOS_2023, "4.4.00.00.00", COL)
    assert v == 371956200.57


def test_conta_ausente_continua_none():
    assert fontes.valor_sem_intra([], "3.1.00.00.00", COL) is None


def test_pessoal_e_investimento_estao_marcados_sem_intra():
    assert {"pessoal", "investimento"} <= fontes.FISCAL_SEM_INTRA


def _serie_ipca(anos_meses: dict) -> dict:
    """{ano: índice constante no ano} → série mensal; ano com <12 meses = parcial."""
    serie = {}
    for ano, (indice, meses) in anos_meses.items():
        for m in range(1, meses + 1):
            serie[f"{ano}-{m:02d}"] = indice
    return serie


def test_media_anual_exige_12_meses():
    s = _serie_ipca({2024: (100.0, 12), 2025: (110.0, 7)})
    assert export.media_anual(s, 2024) == 100.0
    assert export.media_anual(s, 2025) is None


def test_fatores_levam_ao_ultimo_ano_completo():
    s = _serie_ipca({2019: (80.0, 12), 2024: (100.0, 12), 2025: (110.0, 12), 2026: (115.0, 8)})
    base, f = export.fatores_reais(s, [2019, 2024, 2025, 2026])
    assert base == 2025
    assert f[2025] == 1.0 and f[2024] == 1.1 and f[2019] == 1.375
    assert 2026 not in f  # ano sem IPCA completo não ganha fator inventado


def test_ano_sem_ipca_fica_fora_da_serie_em_reais():
    assert export._real(100.0, 2018, {2025: 1.0}) is None
    assert export._real(100.0, 2024, {2024: 1.1}) == 110.0


def test_resumo_fala_em_termos_reais():
    gasto = [{"ano": 2019, "santos": 1000.0}, {"ano": 2025, "santos": 1300.0}]
    txt = export._resumo({"nome": "Saúde", "indicador_chave": "x"}, gasto, [], 2025)
    assert "reais de 2025" in txt and "IPCA" in txt
    assert "+30% em termos reais" in txt
    assert "correntes" not in txt


def test_ipca_versionado_cobre_a_serie_desde_2019():
    ipca = export.carregar_ipca()
    assert ipca and export.media_anual(ipca["serie"], 2019) is not None
