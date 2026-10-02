"""A identidade do favorecido em JS (Comum.identidadeFavorecido, comum.js) tem de
ser o ESPELHO exato de formato.identidade_favorecido — o painel filtra os arquivos
mensais e o índice de favorecidos com a chave gerada em Python. Roda só onde o
Playwright (Chromium) está instalado; no CI é pulado."""
import os

import pytest

from formato import identidade_favorecido, nome_normalizado

CASOS = [
    ("INSTITUTO DE PREVIDÊNCIA SOCIAL", "08.717.299/0001-01"),
    ("IPREV - INST. PREV. SOCIAL", "08717299000101"),
    ("José  da Silva", "***.158.308-**"),
    ("MARIA SOUZA", "***.158.308-**"),
    ("FULANO DE TAL", ""),
    ("Fulano de Tal", None),
    ("ÇÃO ÊXITO LTDA", "12.345.678/0001-9"),      # documento incompleto (13 dígitos)
    ("MUNICÍPIO DE SANTOS", "58.200.015/0001-83"),
    ("PREVID�NCIA", "08.717.299/0001-01"),
]


@pytest.mark.skipif(pytest.importorskip("playwright", reason="playwright ausente") is None, reason="")
def test_identidade_js_espelha_python():
    from playwright.sync_api import sync_playwright
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    comum_js = os.path.join(raiz, "comum.js")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<html><body></body></html>")
        page.add_script_tag(path=comum_js)
        for nome, doc in CASOS:
            js = page.evaluate("([n, d]) => [Comum.identidadeFavorecido(n, d), Comum.nomeNormalizado(n)]", [nome, doc])
            assert js[0] == identidade_favorecido(nome, doc)[0], (nome, doc, js)
            assert js[1] == nome_normalizado(nome), (nome, js)
        browser.close()
