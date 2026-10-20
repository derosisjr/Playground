#!/usr/bin/env python3
"""Testes da escrita/leitura da planilha (sem rede: o cliente do Sheets é falso).

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export import _data  # noqa: E402
from index import COL_SITUACAO, _col_letra, carregar_planilha  # noqa: E402


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


class _Leitura:
    """Cliente falso de leitura: `abas` = {nome: linhas | Exception}."""

    def __init__(self, abas):
        self.abas = abas

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range, **kw):
        conteudo = self.abas[range.strip("'")]
        if isinstance(conteudo, Exception):
            raise conteudo
        return _Resultado({"values": conteudo})


class _Resultado:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


def _aba(cab, numeros):
    return [cab] + [[n] + [""] * (len(cab) - 1) for n in numeros]


class CarregarPlanilhaTest(unittest.TestCase):
    """Seguir com o mapa vazio transformava todo item respondido em "linha nova":
    em 20/08/2026 isso criou 321 linhas repetidas em indicações."""

    CAB_REQ = ["Nùmero", "Resposta", COL_SITUACAO]
    CAB_IND = ["Número", "Resposta", COL_SITUACAO]

    def abas(self, req=None, ind=None):
        return {"requerimentos": req if req is not None else _aba(self.CAB_REQ, ["1/2026", "2/2026"]),
                "indicações": ind if ind is not None else _aba(self.CAB_IND, ["0845/2026", "9/2025"])}

    def test_mapa_pelo_numero_canonico(self):
        indice = carregar_planilha(_Leitura(self.abas()), "id", min_linhas=1)
        self.assertEqual(sorted(indice["indicações"]["mapa"]), ["845/2026", "9/2025"])
        self.assertEqual(indice["indicações"]["mapa"]["845/2026"]["linha"], 2)

    def test_erro_de_leitura_aborta(self):
        with self.assertRaises(RuntimeError):
            carregar_planilha(_Leitura(self.abas(ind=ConnectionError("SSL"))), "id", min_linhas=1)

    def test_aba_sem_coluna_do_numero_aborta(self):
        with self.assertRaises(RuntimeError):
            carregar_planilha(_Leitura(self.abas(ind=_aba(["Num.", "Resposta"], ["1/2026"]))), "id",
                              min_linhas=1)

    def test_aba_quase_vazia_aborta(self):
        with self.assertRaises(RuntimeError):
            carregar_planilha(_Leitura(self.abas()), "id")  # 2 linhas < MIN_LINHAS

    def test_numero_repetido_vale_a_ultima_e_e_contado(self):
        ind = _aba(self.CAB_IND, ["845/2026", "9/2025", "0845/2026"])
        indice = carregar_planilha(_Leitura(self.abas(ind=ind)), "id", min_linhas=1)
        self.assertEqual(indice["indicações"]["mapa"]["845/2026"]["linha"], 4)
        self.assertEqual(indice["indicações"]["repetidos"], 1)


class ColunaLetraTest(unittest.TestCase):
    def test_alem_de_z(self):
        self.assertEqual([_col_letra(i) for i in (0, 25, 26, 27, 51, 52, 701, 702)],
                         ["A", "Z", "AA", "AB", "AZ", "BA", "ZZ", "AAA"])


if __name__ == "__main__":
    unittest.main()
