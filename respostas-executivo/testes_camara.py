#!/usr/bin/env python3
"""Listagem pública da Câmara por autor (`camara.py`), com as páginas reais salvas em
`fixtures/camara/` (latin-1) e sem rede.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest
from unittest import mock

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import camara  # noqa: E402
from comum import http  # noqa: E402

PAGINA = open(os.path.join(AQUI, "fixtures", "camara", "listagem-requerimentos.htm"), "rb").read()


class _Resp:
    def __init__(self, content):
        self.content = content


class TestListagem(unittest.TestCase):
    def test_le_os_blocos_da_pagina_real(self):
        itens = camara.ler_listagem(PAGINA)
        self.assertEqual([(i["subtipo"], i["numero"], i["situacao"]) for i in itens],
                         [("Requerimento", "5438/2026", "-"), ("Requerimento", "5437/2026", "-"),
                          ("Requerimento", "5436/2026", "-")])

    def test_para_quando_a_pagina_vem_vazia(self):
        paginas = [PAGINA, PAGINA, b"<html></html>"]
        with mock.patch.object(http, "get", side_effect=lambda *a, **k: _Resp(paginas.pop(0))), \
                mock.patch.object(camara.time, "sleep"):
            self.assertEqual(len(camara.listar_autor(2026, camara.TIPO_REQUERIMENTO)), 6)

    def test_parar_encerra_depois_da_pagina(self):
        pedidas = []

        def get(url, params, **kw):
            pedidas.append(params["limite"])
            return _Resp(PAGINA)
        with mock.patch.object(http, "get", side_effect=get), mock.patch.object(camara.time, "sleep"):
            itens = camara.listar_autor(2026, camara.TIPO_REQUERIMENTO, parar=lambda blocos: len(pedidas) == 2)
        self.assertEqual((pedidas, len(itens)), (["0", "20"], 6))


if __name__ == "__main__":
    unittest.main()
