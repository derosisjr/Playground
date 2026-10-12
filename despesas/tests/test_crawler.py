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


def test_valor_invalido_rejeita_resposta(monkeypatch):
    # v2: valor não numérico invalida a resposta inteira (a partição anterior fica);
    # valor nulo continua lido como 0,00
    import pytest
    item = dict(ITEM_API, valor="n/d")
    monkeypatch.setattr(crawler, "_http_get",
                        lambda url, params: SimpleNamespace(content=_resposta_soap([item])))
    with pytest.raises(crawler.RespostaInvalida):
        crawler.coletar_mes("empenhos", 2026, 1)
    nulo = dict(ITEM_API, valor=None)
    monkeypatch.setattr(crawler, "_http_get",
                        lambda url, params: SimpleNamespace(content=_resposta_soap([nulo])))
    assert crawler.coletar_mes("empenhos", 2026, 1)[0]["valor"] == 0.0


def test_coletar_mes_descarta_entidade_demonstracao(monkeypatch):
    demo = dict(ITEM_API, unidade_gestora="PREFEITURA MUNICIPAL DEMONSTRAÇÃO",
                nome_favorecido="ECORONDÔNIA AMBIENTAL S/A")
    monkeypatch.setattr(crawler, "_http_get",
                        lambda url, params: SimpleNamespace(content=_resposta_soap([ITEM_API, demo])))
    itens = crawler.coletar_mes("empenhos", 2026, 1)
    assert len(itens) == 1
    assert itens[0]["unidade_gestora"] == "PREFEITURA MUNICIPAL DE SANTOS"


def test_expurgar_demo_limpa_cache():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.executescript(crawler._schema())
    cols = ["hash"] + crawler._cols("pagamentos")
    base = {c: "" for c in cols}
    base.update({"ano": 2025, "mes": 1, "valor": 10.0})
    for i, ug in enumerate(["PREFEITURA MUNICIPAL DE SANTOS",
                            "PREFEITURA MUNICIPAL DEMONSTRAÇÃO"]):
        row = dict(base, hash=f"h{i}", unidade_gestora=ug)
        conn.execute(f"INSERT INTO pagamentos ({','.join(cols)}) "
                     f"VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
    assert crawler.expurgar_demo(conn) == 1
    sobra = conn.execute("SELECT unidade_gestora FROM pagamentos").fetchall()
    assert sobra == [("PREFEITURA MUNICIPAL DE SANTOS",)]
    assert crawler.expurgar_demo(conn) == 0   # idempotente


def test_data_iso():
    assert crawler._data_iso("2026-03-07T00:00:00") == "2026-03-07"
    assert crawler._data_iso(None) == ""
    assert crawler._data_iso("") == ""


def test_numero_documento_volta_a_largura_historica():
    # 2026-09-30: a origem passou a mandar 8 dígitos; o casamento é por texto exato.
    assert crawler.numero_documento("00000504/2026") == "0000504/2026"
    assert crawler.numero_documento("0000504/2026") == "0000504/2026"
    assert crawler.numero_documento("12345678/2026") == "12345678/2026"
    for v in ("", None, "s/n"):
        assert crawler.numero_documento(v) == v


def test_codigo_grupo_volta_a_largura_historica():
    assert crawler.codigo_grupo("33000000000 - OUTRAS") == "330000000000 - OUTRAS"
    assert crawler.codigo_grupo("330000000000 - OUTRAS") == "330000000000 - OUTRAS"
    assert crawler.codigo_grupo("33 - OUTRAS") == "33 - OUTRAS"
    assert crawler.codigo_grupo(None) is None


def test_normalizar_formatos_novo_e_antigo_dao_o_mesmo_hash():
    antigo = {**ITEM_API, "empenho": "0000504/2026", "liquidacao": "0025195/2026",
              "pagamento": "0001234/2026", "grupo_despesa": "330000000000 - OUTRAS"}
    novo = {**ITEM_API, "empenho": "00000504/2026", "liquidacao": "00025195/2026",
            "pagamento": "00001234/2026", "grupo_despesa": "33000000000 - OUTRAS"}
    (a,), _ = crawler.normalizar("pagamentos", 2026, 1, [antigo])
    (b,), _ = crawler.normalizar("pagamentos", 2026, 1, [novo])
    assert b["empenho"] == "0000504/2026"
    assert b["liquidacao"] == "0025195/2026"
    assert b["grupo_despesa"] == "330000000000 - OUTRAS"
    assert a["hash"] == b["hash"]
