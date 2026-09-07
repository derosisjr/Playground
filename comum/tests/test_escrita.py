import json
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
from comum.escrita import gravar_bytes, gravar_json, gravar_json_se_mudou  # noqa: E402


def test_gravar_json_escreve_utf8_sem_escape(tmp_path):
    alvo = tmp_path / "x.json"
    gravar_json(alvo, {"a": "ação"}, separators=(",", ":"))
    assert alvo.read_text(encoding="utf-8") == '{"a":"ação"}'


def test_gravar_cria_pasta_e_nao_deixa_temporario(tmp_path):
    alvo = tmp_path / "sub" / "y.json"
    gravar_json(alvo, [1, 2])
    assert json.loads(alvo.read_text(encoding="utf-8")) == [1, 2]
    assert os.listdir(tmp_path / "sub") == ["y.json"]


def test_falha_na_escrita_preserva_o_arquivo_anterior(tmp_path, monkeypatch):
    alvo = tmp_path / "z.json"
    alvo.write_text('{"velho":1}', encoding="utf-8")

    def replace_que_falha(*a, **k):
        raise OSError("disco cheio")

    monkeypatch.setattr(os, "replace", replace_que_falha)
    with pytest.raises(OSError):
        gravar_bytes(alvo, b"{}")
    assert alvo.read_text(encoding="utf-8") == '{"velho":1}'
    assert os.listdir(tmp_path) == ["z.json"], "temporário deve ser removido na falha"


def test_se_mudou_ignora_carimbo_e_preserva_o_antigo(tmp_path):
    alvo = tmp_path / "fav.json"
    assert gravar_json_se_mudou(alvo, {"total": 1.5, "atualizado_em": "2026-01-01"}) is True
    assert gravar_json_se_mudou(alvo, {"total": 1.5, "atualizado_em": "2026-02-02"}) is False
    assert json.loads(alvo.read_text(encoding="utf-8"))["atualizado_em"] == "2026-01-01"
    assert gravar_json_se_mudou(alvo, {"total": 2.0, "atualizado_em": "2026-02-02"}) is True
    assert json.loads(alvo.read_text(encoding="utf-8")) == {"total": 2.0, "atualizado_em": "2026-02-02"}


def test_se_mudou_regrava_arquivo_corrompido(tmp_path):
    alvo = tmp_path / "c.json"
    alvo.write_text("{trunc", encoding="utf-8")
    assert gravar_json_se_mudou(alvo, {"a": 1}) is True


def test_se_mudou_trata_tupla_como_lista(tmp_path):
    alvo = tmp_path / "t.json"
    gravar_json_se_mudou(alvo, {"periodo": (2026, 6), "atualizado_em": "a"})
    assert gravar_json_se_mudou(alvo, {"periodo": (2026, 6), "atualizado_em": "b"}) is False
    assert gravar_json_se_mudou(alvo, {"periodo": (2026, 7), "atualizado_em": "b"}) is True
