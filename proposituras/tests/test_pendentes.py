"""Revisita do ano anterior: só os projetos fora de situação final, com teto.

Sem rede: a listagem e a tramitação são substituídas por fixtures; o banco é um
SQLite temporário com o schema real.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crawler  # noqa: E402

ARQUIVO = "Divisão de Arquivo Público"
PAUTA = "Diretoria Legislativa - Aguardando Pautação"


def item(cod, local, situacao="Encaminhado", ano=2025):
    return {"cod": cod, "tipo": "Projeto", "subtipo": "Projeto de Lei", "numero": f"{cod}/{ano}",
            "ano": ano, "processo": "", "data_propositura": "", "autor": "Fulano", "ementa": "x",
            "local_atual": local, "situacao": situacao, "data_situacao": "",
            "url_detalhes": "", "url_pdf": "", "fonte": crawler.FONTE, "data_coleta": "2026-10-11T00:00:00"}


def test_situacao_final():
    assert crawler.situacao_final(ARQUIVO, "Encaminhado")
    assert crawler.situacao_final("divisão de arquivo público", "Aprovado")
    assert crawler.situacao_final("", "Transformado")
    assert not crawler.situacao_final(PAUTA, "Encaminhado")
    assert not crawler.situacao_final("CCJ - Assinatura de Parecer", "Aprovado")
    assert not crawler.situacao_final("Diretoria Legislativa - Prazo Para Sanção/Veto", "Aprovado")
    assert not crawler.situacao_final("", "Encaminhado")   # local vazio: revisita
    assert not crawler.situacao_final(None, None)


def test_selecionar_pendentes_ordem_e_filtro():
    listados = [item(1, ARQUIVO), item(2, PAUTA), item(3, PAUTA), item(4, PAUTA), item(5, PAUTA)]
    gravados = {
        1: (ARQUIVO, "Encaminhado", "2026-01-01"),   # final no banco → fica de fora
        2: (PAUTA, "Encaminhado", "2026-09-01"),
        3: (PAUTA, "Encaminhado", "2026-03-01"),     # coletado há mais tempo
        5: (ARQUIVO, "Encaminhado", "2026-05-01"),   # final no banco → fora, mesmo listado como pauta
    }
    sel = crawler.selecionar_pendentes(listados, gravados)
    assert [i["cod"] for i in sel] == [4, 3, 2]       # novo primeiro, depois o mais antigo


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler, "DB_PATH", str(tmp_path / "p.sqlite"))
    monkeypatch.setattr(crawler, "PAUSA", 0)
    conn = crawler.abrir_db()
    yield conn
    conn.close()


def test_revisitar_pendentes_atualiza_so_os_nao_finais_com_teto(banco, monkeypatch):
    # estado gravado: 10 arquivado; 11 e 12 aguardando pautação (12 coletado antes)
    for cod, local, coleta in ((10, ARQUIVO, "2026-01-01"), (11, PAUTA, "2026-08-01"), (12, PAUTA, "2026-02-01")):
        p = item(cod, local)
        p["data_coleta"] = coleta
        crawler.upsert(banco, p, [{"ordem": 0, "data": "01/01/2026", "local": local, "despacho": "d",
                                   "url_arquivo": ""}])
    banco.commit()

    # a Câmara agora lista o 12 como arquivado e o 11 ainda na pauta
    pagina = [item(10, ARQUIVO), item(11, PAUTA), item(12, ARQUIVO)]
    monkeypatch.setattr(crawler, "coletar_pagina", lambda ano, off: pagina if off == 0 else [])
    tramitados = []

    def tramitacao(cod):
        tramitados.append(cod)
        return [{"ordem": 0, "data": "10/10/2026", "local": "x", "despacho": "novo", "url_arquivo": ""}]
    monkeypatch.setattr(crawler, "coletar_tramitacao", tramitacao)

    n = crawler.revisitar_pendentes(banco, 2025, teto=1, sem_tramitacao=False, dry_run=False)
    assert n == 1 and tramitados == [12]              # teto 1: o coletado há mais tempo
    local12 = banco.execute("SELECT local_atual, data_situacao FROM proposituras WHERE cod=12").fetchone()
    assert local12 == (ARQUIVO, "10/10/2026")         # registrou o estado final

    tramitados.clear()
    n = crawler.revisitar_pendentes(banco, 2025, teto=0, sem_tramitacao=False, dry_run=False)
    assert tramitados == [11]                         # 10 e 12 agora finais: só o 11
    assert banco.execute("SELECT despacho FROM tramitacao WHERE prop_cod=10").fetchone() == ("d",)
