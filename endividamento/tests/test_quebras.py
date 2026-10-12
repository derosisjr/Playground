# -*- coding: utf-8 -*-
"""Quebra contábil da série de endividamento.

No 3º quadrimestre de 2025 os precatórios foram reclassificados no RGF: a dívida
consolidada registrada caiu de ~R$ 1,01 bi para ~R$ 522 mi sem pagamento
equivalente. O resumo nunca pode comparar a dívida total através dessa quebra.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import export  # noqa: E402


def _p(ano, q, dc, prec, pct=10.0):
    return {"ano": ano, "q": q, "rotulo": f"{q}º quad. {ano}",
            "dc": dc, "dc_pct": pct, "precatorios": prec}


SERIE = [
    _p(2018, 1, 442e6, None),
    _p(2020, 2, 772e6, 429e6),
    _p(2025, 2, 1010.65e6, 539.62e6),
    _p(2025, 3, 522.0e6, 62.6e6),
    _p(2026, 2, 613.29e6, 178.71e6),
]
SEMAFORO = [{"nome": "Dívida", "cor": "verde"}]


def _serie():
    return [dict(p) for p in SERIE]


def test_anota_so_o_ponto_da_quebra():
    s = _serie()
    quebras = export.anotar_quebras(s)
    assert [(q["ano"], q["q"]) for q in quebras] == [(2025, 3)]
    assert "quebra" in s[3] and "reclassifica" in s[3]["quebra"]
    assert all("quebra" not in p for i, p in enumerate(s) if i != 3)


def test_quebra_fora_da_serie_nao_aparece():
    s = [p for p in _serie() if p["ano"] < 2025]
    assert export.anotar_quebras(s) == []


def test_variacao_sem_precatorios_comeca_no_primeiro_ponto_com_precatorios():
    s = _serie()
    base, ini, fim, var = export.variacao_sem_precatorios(s, s[-1])
    assert (base["ano"], base["q"]) == (2020, 2)
    assert round(ini / 1e6) == 343 and round(fim / 1e6) == 435
    assert round(var) == 27


def test_resumo_nao_compara_divida_total_atraves_da_quebra():
    s = _serie()
    quebras = export.anotar_quebras(s)
    txt = export._resumo(s, s[-1], SEMAFORO, quebras)
    # a comparação antiga (dívida total desde 2018) dava "+39%": proibida
    assert "1º quad. 2018" not in txt
    assert "39%" not in txt
    assert "excluir os precatórios" in txt and "3º quad. 2025" in txt
    assert "27%" in txt


def test_resumo_sem_quebra_mantem_comparacao_total():
    s = [_p(2018, 1, 400e6, None), _p(2019, 1, 500e6, None)]
    txt = export._resumo(s, s[-1], SEMAFORO, [])
    assert "cresceu 25% em valores correntes" in txt
