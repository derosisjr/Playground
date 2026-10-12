"""carregar_santos não relista o ano do CNPJ para âncoras já carregadas."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crawler  # noqa: E402
import fontes  # noqa: E402

CNPJ, ANO, SEQ = "58200015000183", 2026, 42


def _base(tmp_path, monkeypatch, itens_status):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(crawler.SCHEMA)
    ncp = fontes.montar_ncp(CNPJ, ANO, SEQ)
    c.execute("INSERT INTO contratacao(ncp, ibge, cnpj, ano, sequencial, itens_status) "
              "VALUES (?,?,?,?,?,?)", (ncp, fontes.IBGE_SANTOS, CNPJ, ANO, SEQ, itens_status))
    (tmp_path / "x.json").write_text(json.dumps(
        {"slug": "x", "santos": {"cnpj": CNPJ, "ano": ANO, "sequencial": SEQ}}), encoding="utf-8")
    monkeypatch.setattr(crawler, "CONSULTAS", str(tmp_path))
    chamadas = []
    monkeypatch.setattr(fontes, "listar", lambda *a, **k: chamadas.append(a) or [])
    monkeypatch.setattr(fontes, "itens", lambda *a, **k: chamadas.append(a) or [])
    return c, chamadas


def test_ancora_ja_carregada_nao_relista(tmp_path, monkeypatch):
    c, chamadas = _base(tmp_path, monkeypatch, "ok")
    _, falhas = crawler.carregar_santos(c)
    assert falhas == [] and chamadas == []


def test_ancora_pendente_lista_e_carrega(tmp_path, monkeypatch):
    c, chamadas = _base(tmp_path, monkeypatch, "pendente")
    _, falhas = crawler.carregar_santos(c)
    assert falhas == [] and len(chamadas) == 3   # listar ×2 (modalidades 6 e 8) + itens
