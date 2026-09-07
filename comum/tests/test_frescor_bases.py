"""A guarda de frescor decide se uma base está morta — e não tinha teste."""
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
_spec = importlib.util.spec_from_file_location(
    "frescor_bases", os.path.join(RAIZ, ".github", "scripts", "frescor_bases.py"))
fb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fb)


def test_parsers_de_data():
    assert fb._data_br("14/08/2026") == date(2026, 8, 14)
    assert fb._data_br("") is None and fb._data_br("lixo") is None
    assert fb._data_iso("2026-08-14T12:00:00") == date(2026, 8, 14)
    assert fb._data_iso(None) is None


def test_maior_data_br_compara_datas_nao_strings():
    ext = fb.maior_data_br("d")
    assert ext([{"d": "31/12/2004"}, {"d": "13/08/2026"}, {"d": ""}]) == date(2026, 8, 13)
    assert ext("nao e lista") is None


def test_mes_de_e_quadrimestre_fecham_no_ultimo_dia():
    assert fb.mes_de("cobertura", "ate")({"cobertura": {"ate": "2026-02"}}) == date(2026, 2, 28)
    assert fb.mes_de("cobertura", "ate")({"cobertura": {"ate": "2026-12"}}) == date(2026, 12, 31)
    assert fb.quadrimestre({"ultimo": {"ano": 2026, "q": 1}}) == date(2026, 4, 30)
    assert fb.quadrimestre({"ultimo": {"ano": 2026, "q": 3}}) == date(2026, 12, 31)
    assert fb.quadrimestre({"ultimo": {}}) is None


def test_avaliar_marca_congelada_e_sinal_ausente(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "RAIZ", Path(tmp_path))
    monkeypatch.setattr(fb, "BASES", {
        "a.json": {"limite": 20, "extrator": fb.campo("dados_ate"), "sinal": "dados_ate"},
        "b.json": {"limite": 20, "extrator": fb.campo("dados_ate"), "sinal": "dados_ate"},
        "c.json": {"limite": 20, "extrator": fb.campo("dados_ate"), "sinal": "dados_ate"},
    })
    (tmp_path / "a.json").write_text(json.dumps({"dados_ate": "2026-09-01"}), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"dados_ate": "2026-07-01"}), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"outra": 1}), encoding="utf-8")
    linhas, erros = fb.avaliar(hoje=date(2026, 9, 7))
    por_nome = {ln[0]: ln for ln in linhas}
    assert por_nome["a.json"][4] is True and por_nome["a.json"][2] == 6
    assert por_nome["b.json"][4] is False                       # 68 dias > 20: CONGELADA
    assert any(e.startswith("c.json: sinal de frescor ausente") for e in erros)
