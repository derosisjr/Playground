#!/usr/bin/env python3
"""Testes da escrita/leitura da planilha (sem rede: o cliente do Sheets é falso).

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export import _data  # noqa: E402
from index import COL_SITUACAO, _col_letra, anexar_linha, carregar_planilha, montar_linha  # noqa: E402


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
