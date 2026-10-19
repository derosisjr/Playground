"""Contagens leves do hub (`bases-atualizacao.json`): o hub decide o rótulo de
requerimentos e fala (ou não) de notas do Regimento a partir delas."""
import importlib.util
import json
import os
import sys
from pathlib import Path

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
_spec = importlib.util.spec_from_file_location(
    "bases_atualizacao", os.path.join(RAIZ, ".github", "scripts", "bases_atualizacao.py"))
ba = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ba)


def _gravar(pasta, nome, dados):
    (pasta / nome).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def test_requerimentos_classificados(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "RAIZ", Path(tmp_path))
    _gravar(tmp_path, "requerimentos-index.json", [
        {"numero": "1/2026", "situacao": "respondido", "respondido": True,
         "data_resposta_merito": "10/02/2026"},
        {"numero": "2/2026", "situacao": "so_prorrogacao", "respondido": False},
        {"numero": "3/2026", "situacao": "pendente", "respondido": False},
    ])
    c = ba.contagens()["requerimentos-index.json"]
    assert c["n"] == 3 and c["respondidos"] == 1
    assert c["por_situacao"] == {"respondido": 1, "so_prorrogacao": 1, "pendente": 1}
    assert c["classificada"] is True


def test_fora_do_prazo_so_com_vence_em(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "RAIZ", Path(tmp_path))
    _gravar(tmp_path, "requerimentos-index.json", [
        {"numero": "1/2025", "situacao": "pendente", "respondido": False, "vence_em": "19/02/2025"},
        {"numero": "2/2025", "situacao": "so_prorrogacao", "respondido": False, "vence_em": "31/12/2999"},
        {"numero": "3/2025", "situacao": "respondido", "respondido": True, "vence_em": ""},
    ])
    assert ba.contagens()["requerimentos-index.json"]["fora_do_prazo"] == 1
    # índice antigo (sem vence_em): a chave não aparece e o hub não fala de prazo
    _gravar(tmp_path, "requerimentos-index.json", [
        {"numero": "1/2025", "situacao": "pendente", "respondido": False}])
    assert "fora_do_prazo" not in ba.contagens()["requerimentos-index.json"]


def test_requerimentos_sem_classificacao(tmp_path, monkeypatch):
    # fallback do export ("tem pasta no Drive"): só respondido/pendente, sem data de mérito
    monkeypatch.setattr(ba, "RAIZ", Path(tmp_path))
    _gravar(tmp_path, "requerimentos-index.json", [
        {"numero": "1/2026", "situacao": "respondido", "respondido": True,
         "data_resposta_merito": ""},
        {"numero": "2/2026", "situacao": "pendente", "respondido": False},
    ])
    assert ba.contagens()["requerimentos-index.json"]["classificada"] is False


def test_notas_do_regimento_ignoram_comentario(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "RAIZ", Path(tmp_path))
    _gravar(tmp_path, "regimento-notas.json", {"_leia-me": "texto"})
    assert ba.contagens()["regimento-notas.json"] == {"artigos_com_nota": 0}
    _gravar(tmp_path, "regimento-notas.json", {
        "_leia-me": "texto", "art-79": [{"tipo": "doutrina", "texto": "x"}], "art-80": []})
    assert ba.contagens()["regimento-notas.json"] == {"artigos_com_nota": 1}


def test_lei_organica_conta_so_o_corpo_e_os_alterados(tmp_path, monkeypatch):
    # o cartão mostra os artigos do corpo; as Disposições Transitórias recomeçam no art. 1
    monkeypatch.setattr(ba, "RAIZ", Path(tmp_path))
    _gravar(tmp_path, "lei-organica-index.json", [
        {"id": "art-1", "numero": "1", "adt": False, "notas": [{"bloco": 0, "texto": "x"}]},
        {"id": "art-2", "numero": "2", "adt": False, "notas": []},
        {"id": "art-2-a", "numero": "2-A", "adt": False, "notas": [{"bloco": None, "texto": "y"}]},
        {"id": "adt-art-1", "numero": "1", "adt": True, "notas": [{"bloco": 0, "texto": "z"}]},
    ])
    assert ba.contagens()["lei-organica-index.json"] == {"n": 3, "alterados": 2, "adt": 1}


def test_falha_num_indice_so_tira_a_chave_dele(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "RAIZ", Path(tmp_path))
    out = ba.contagens()  # nenhum arquivo: nenhuma chave, nenhuma exceção
    assert "requerimentos-index.json" not in out and "regimento-notas.json" not in out
    assert "lei-organica-index.json" not in out
