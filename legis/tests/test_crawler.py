# -*- coding: utf-8 -*-
"""Crawler: ementa oficial, migração do banco, upsert e revisita (sem rede)."""
import sqlite3

from bs4 import BeautifulSoup

import crawler

# Trecho real de /legis/documents/6573 (latin-1 com UTF-8 embutido, como vem do site).
HTML_6573 = """
<div class="container py-3"><div class="row"><div class="col-10">
<h1 class="mb-4">2017 » Lei n.º 3.386, de 29 de setembro</h1></div></div>
<p class="tags mb-5"><span class="badge badge-pill badge-primary">revoga a lei nº 2.182 06 de janeiro de 2004</span></p>
<p class="descricao">REVOGA A LEI Nº 2.182, DE 06
DE JANEIRO DE 2004.</p>
<p class="info mb-5">Publicada no D.O. de 02/10/17.</p></div>
""".encode("utf-8").decode("latin-1")


def test_detalhar_le_a_ementa_oficial(monkeypatch):
    monkeypatch.setattr(crawler, "_soup", lambda url, params=None: BeautifulSoup(HTML_6573, "html.parser"))
    n = crawler.detalhar(6573, "Lei ordinária", 2017)
    assert n["numero"] == "3.386"
    assert n["descricao"] == "REVOGA A LEI Nº 2.182, DE 06 DE JANEIRO DE 2004."
    assert "situacao" not in n  # situação é do recálculo, não do scraping


SCHEMA_ANTIGO = """
CREATE TABLE normas (id INTEGER PRIMARY KEY, tipo TEXT, numero TEXT, ano INTEGER,
  data_norma TEXT, titulo TEXT, ementa TEXT, tags TEXT, situacao TEXT, url_legis TEXT,
  url_pdf TEXT, fonte TEXT, data_coleta TEXT);
CREATE TABLE temas (norma_id INTEGER, tema TEXT, PRIMARY KEY (norma_id, tema));
"""


def _banco_antigo(tmp_path, monkeypatch):
    db = tmp_path / "legis.sqlite"
    c = sqlite3.connect(db)
    c.executescript(SCHEMA_ANTIGO)
    c.executemany(
        "INSERT INTO normas (id, tipo, numero, ano, titulo, situacao, data_coleta) VALUES (?,?,?,?,?,?,?)",
        [(1026, "Lei ordinária", "2.182", 2004, "Lei nº 2.182", "", "2026-06-06T20:49:32"),
         (6573, "Lei ordinária", "3.386", 2017, "Lei n.º 3.386", "", "2026-06-07T10:00:00"),
         (9000, "Lei ordinária", "4.000", 2021, "Lei n.º 4.000", "", "2026-10-01T10:00:00")])
    c.commit()
    c.close()
    monkeypatch.setattr(crawler, "DB_PATH", str(db))
    return db


def test_migracao_preserva_dados_e_acrescenta_colunas(tmp_path, monkeypatch):
    _banco_antigo(tmp_path, monkeypatch)
    conn = crawler.abrir_db()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(normas)")}
    assert {"descricao", "revogada_por"} <= cols
    assert conn.execute("SELECT COUNT(*) FROM normas").fetchone()[0] == 3
    crawler.abrir_db().close()  # idempotente


def test_upsert_recalculo_e_revisita(tmp_path, monkeypatch):
    _banco_antigo(tmp_path, monkeypatch)
    conn = crawler.abrir_db()
    # revisita: a verificada há mais tempo primeiro, sem repetir as desta execução
    assert [r[0] for r in crawler.revisitar_ids(conn, 2, pular=set())] == [1026, 6573]
    assert [r[0] for r in crawler.revisitar_ids(conn, 2, pular={1026})] == [6573, 9000]

    monkeypatch.setattr(crawler, "_soup", lambda url, params=None: BeautifulSoup(HTML_6573, "html.parser"))
    crawler.upsert(conn, crawler.detalhar(6573, "Lei ordinária", 2017))
    conn.commit()
    sit = crawler.recalcular_situacao(conn)
    assert sit[1026]["situacao"] == "revogada"
    assert conn.execute("SELECT situacao, revogada_por FROM normas WHERE id=1026").fetchone() == \
        ("revogada", 6573)
    # revisitar a própria revogada (upsert) não apaga a situação gravada até o
    # próximo recálculo (ON CONFLICT, não INSERT OR REPLACE)
    revogada = {"id": 1026, "tipo": "Lei ordinária", "numero": "2.182", "ano": 2004,
                "data_norma": "06/01/2004", "titulo": "Lei nº 2.182", "ementa": "",
                "tags": "", "descricao": "PROÍBE A EXIGÊNCIA DE EXPERIÊNCIA MÍNIMA",
                "url_legis": "", "url_pdf": "", "fonte": "", "data_coleta": "2026-10-02T00:00:00",
                "_temas": []}
    crawler.upsert(conn, revogada)
    conn.commit()
    assert conn.execute("SELECT situacao, revogada_por FROM normas WHERE id=1026").fetchone() == \
        ("revogada", 6573)
    # revisitada sai do fim da fila
    assert [r[0] for r in crawler.revisitar_ids(conn, 3, pular=set())][-1] == 6573
