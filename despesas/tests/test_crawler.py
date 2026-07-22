import json
from types import SimpleNamespace

import crawler


def _resposta_soap(itens) -> bytes:
    """Monta a resposta real da API: XML SOAP <string> com JSON escapado dentro."""
    bruto = json.dumps(itens, ensure_ascii=False)
    escapado = bruto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<string xmlns="http://tempuri.org/">{escapado}</string>').encode("utf-8")


ITEM_API = {
    "unidade_gestora": "PREFEITURA MUNICIPAL DE SANTOS",
    "data": "2026-01-15T00:00:00",
    "especie": "Original",
    "empenho": "0000123/2026",
    "elemento_despesa": "339039 - OUTROS SERVIÇOS DE TERCEIROS",
    "subtitulo": "",
    "funcao": "10 - SAÚDE",
    "subfuncao": "301 - Atenção Básica",
    "programa": "Saúde para Todos",
    "fonte_recurso": "TESOURO",
    "grupo_despesa": "33 - OUTRAS DESPESAS CORRENTES",
    "documento_favorecido": "12.345.678/0001-90",
    "nome_favorecido": "ACME SERVIÇOS LTDA",
    "valor": 1234.567,
    "tipo_empenho": "Ordinário",
}


def test_coletar_mes_parseia_soap(monkeypatch):
    monkeypatch.setattr(crawler, "_http_get",
                        lambda url, params: SimpleNamespace(content=_resposta_soap([ITEM_API])))
    itens = crawler.coletar_mes("empenhos", 2026, 1)
    assert len(itens) == 1
    it = itens[0]
    assert it["ano"] == 2026 and it["mes"] == 1
    assert it["data"] == "2026-01-15"          # sem o sufixo T00:00:00
    assert it["valor"] == 1234.57              # arredondado a 2 casas
    assert it["nome_favorecido"] == "ACME SERVIÇOS LTDA"   # acentos preservados
    assert it["hash"]                          # chave de dedup presente


def test_coletar_mes_vazio(monkeypatch):
    monkeypatch.setattr(crawler, "_http_get",
                        lambda url, params: SimpleNamespace(
                            content=b'<string xmlns="http://tempuri.org/"></string>'))
    assert crawler.coletar_mes("pagamentos", 2026, 1) == []


def test_hash_identico_para_registro_igual(monkeypatch):
    monkeypatch.setattr(crawler, "_http_get",
                        lambda url, params: SimpleNamespace(content=_resposta_soap([ITEM_API, ITEM_API])))
    a, b = crawler.coletar_mes("empenhos", 2026, 1)
    assert a["hash"] == b["hash"]              # dedup via INSERT OR IGNORE


def test_valor_invalido_vira_zero(monkeypatch):
    item = dict(ITEM_API, valor="n/d")
    monkeypatch.setattr(crawler, "_http_get",
                        lambda url, params: SimpleNamespace(content=_resposta_soap([item])))
    assert crawler.coletar_mes("empenhos", 2026, 1)[0]["valor"] == 0.0


def test_data_iso():
    assert crawler._data_iso("2026-03-07T00:00:00") == "2026-03-07"
    assert crawler._data_iso(None) == ""
    assert crawler._data_iso("") == ""
