#!/usr/bin/env python3
"""Testes da escrita/leitura da planilha (sem rede: o cliente do Sheets é falso).

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export import _data  # noqa: E402
from index import COL_SITUACAO, anexar_linha, montar_linha  # noqa: E402


class _Req:
    def __init__(self, registro, kwargs):
        self.registro, self.kwargs = registro, kwargs

    def execute(self):
        self.registro.append(self.kwargs)
        return {}


class _Values:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        return _Req(self.updates, kwargs)

    def append(self, **kwargs):  # pragma: no cover — não deve mais ser usado
        raise AssertionError("anexar_linha não pode usar values().append")


class _Sheets:
    def __init__(self):
        self.vals = _Values()

    def spreadsheets(self):
        return self

    def values(self):
        return self.vals


class DataTest(unittest.TestCase):
    def test_serial_normal(self):
        self.assertEqual(_data(46000), "09/12/2025")

    def test_serial_gigante_nao_estoura(self):
        # Data digitada sem barras: o Sheets guarda 13082026 como número.
        self.assertEqual(_data(13082026), "13/08/2026")
        self.assertEqual(_data(1082026), "01/08/2026")

    def test_serial_invalido_vira_vazio(self):
        self.assertEqual(_data(99999999), "")
        self.assertEqual(_data(-5), "")

    def test_texto_e_bool(self):
        self.assertEqual(_data(" 13/08/2026 "), "13/08/2026")
        self.assertEqual(_data(True), "")


class AnexarLinhaTest(unittest.TestCase):
    # Cabeçalho real em ordem diferente da de ABAS e sem "Secretaria".
    CAB = ["Ordem", "Assunto", "Nùmero", "Data da Sessão", "Data do Protocolo na PMS",
           "Prazo", "Resposta", "Data da resposta", "Status atual", COL_SITUACAO]

    def test_montar_linha_segue_cabecalho_real(self):
        linha = montar_linha(self.CAB, {
            "Assunto": "Poda", "Data da Sessão": "13/08/2026", "Nùmero": "4071/2026",
            "Resposta": "=HYPERLINK(...)", "Secretaria": "ignorada",
        })
        self.assertEqual(len(linha), len(self.CAB))
        self.assertEqual(linha[2], "4071/2026")
        self.assertEqual(linha[3], "13/08/2026")
        self.assertEqual(linha[6], "=HYPERLINK(...)")
        self.assertNotIn("ignorada", linha)

    def test_casa_sem_acento(self):
        linha = montar_linha(["Numero"], {"Nùmero": "1/2026"})
        self.assertEqual(linha, ["1/2026"])

    def test_anexar_grava_na_proxima_linha_e_avanca(self):
        sheets = _Sheets()
        info = {"cab": self.CAB, "n_linhas": 623}
        anexar_linha(sheets, "id", "Requerimentos", info, {"Nùmero": "1/2026"})
        anexar_linha(sheets, "id", "Requerimentos", info, {"Nùmero": "2/2026"})
        r1, r2 = sheets.vals.updates
        self.assertEqual(r1["range"], "'Requerimentos'!A624:J624")
        self.assertEqual(r2["range"], "'Requerimentos'!A625:J625")
        self.assertEqual(r2["body"]["values"][0][2], "2/2026")
        self.assertEqual(info["n_linhas"], 625)

    def test_sem_cabecalho_falha(self):
        with self.assertRaises(RuntimeError):
            anexar_linha(_Sheets(), "id", "X", {"cab": [], "n_linhas": 0}, {})


if __name__ == "__main__":
    unittest.main()
