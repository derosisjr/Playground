#!/usr/bin/env python3
"""`garantir_colunas` só cria as colunas que a automação grava (cliente falso).

Em 12/10/2026 ela criou "Ordem", "Prazo" e "Data do Protocolo na PMS" vazias no
fim da aba de requerimentos, porque tentava completar TODAS as colunas de ABAS.
Desde out/2026 a coluna nova entra depois da última coluna com QUALQUER conteúdo
(coluna sem título com anotação é da equipe) e só as células novas são gravadas.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from index import ABA_REQUERIMENTOS, COL_DATA_MERITO, COL_SITUACAO, garantir_colunas  # noqa: E402


class _Exec:
    def __init__(self, resultado=None, registro=None, kwargs=None):
        self.resultado, self.registro, self.kwargs = resultado or {}, registro, kwargs

    def execute(self):
        if self.registro is not None:
            self.registro.append(self.kwargs)
        return self.resultado


class _Values:
    def __init__(self, linhas):
        self.linhas, self.updates = linhas, []

    def get(self, **kwargs):
        return _Exec({"values": self.linhas})

    def update(self, **kwargs):
        return _Exec(registro=self.updates, kwargs=kwargs)


class _Sheets:
    def __init__(self, linhas, colunas_na_grade=26):
        self.vals = _Values(linhas)
        self.colunas_na_grade = colunas_na_grade
        self.lotes = []

    def spreadsheets(self):
        return self

    def values(self):
        return self.vals

    def get(self, **kwargs):
        return _Exec({"sheets": [{"properties": {
            "sheetId": 7, "title": ABA_REQUERIMENTOS,
            "gridProperties": {"columnCount": self.colunas_na_grade}}}]})

    def batchUpdate(self, **kwargs):
        return _Exec(registro=self.lotes, kwargs=kwargs)


# cabeçalho real da aba em out/2026 (sem as duplicatas criadas em 12/10)
REAL = ["Assunto", "Secretaria", "Data da Sessão", "Nùmero", "Resposta",
        "Data da resposta", "Status atual", "Situação", "observação"]
LINHA = ["Poda", "SMS", "13/03/2025", "852/2025", "", "", "ok", "", ""]


class TestGarantirColunas(unittest.TestCase):
    def test_cria_so_as_de_classificacao_e_grava_so_as_celulas_novas(self):
        s = _Sheets([list(REAL), list(LINHA)])
        cab = garantir_colunas(s, "id", ABA_REQUERIMENTOS)
        self.assertEqual(cab, REAL + [COL_SITUACAO, COL_DATA_MERITO])
        for manual in ("Ordem", "Prazo", "Data do Protocolo na PMS"):
            self.assertNotIn(manual, cab)
        (upd,) = s.vals.updates
        # 9 colunas com conteúdo (A–I): as novas começam em J, e o cabeçalho antigo
        # não é regravado
        self.assertEqual(upd["range"], f"'{ABA_REQUERIMENTOS}'!J1")
        self.assertEqual(upd["body"]["values"], [[COL_SITUACAO, COL_DATA_MERITO]])
        self.assertEqual(s.lotes, [])  # a grade já comporta

    def test_coluna_sem_titulo_com_anotacao_nao_e_ocupada(self):
        # a equipe anotou na coluna J, que não tem título
        s = _Sheets([list(REAL), LINHA + ["anotação da equipe"]])
        cab = garantir_colunas(s, "id", ABA_REQUERIMENTOS)
        (upd,) = s.vals.updates
        self.assertEqual(upd["range"], f"'{ABA_REQUERIMENTOS}'!K1")
        self.assertEqual(cab, REAL + ["", COL_SITUACAO, COL_DATA_MERITO])

    def test_grade_estreita_ganha_colunas_no_fim(self):
        s = _Sheets([list(REAL), list(LINHA)], colunas_na_grade=10)
        garantir_colunas(s, "id", ABA_REQUERIMENTOS)
        (lote,) = s.lotes
        pedido = lote["body"]["requests"][0]["appendDimension"]
        self.assertEqual((pedido["sheetId"], pedido["dimension"], pedido["length"]), (7, "COLUMNS", 1))

    def test_nada_a_fazer_quando_ja_existem(self):
        s = _Sheets([REAL + [COL_SITUACAO, COL_DATA_MERITO]])
        garantir_colunas(s, "id", ABA_REQUERIMENTOS)
        self.assertEqual(s.vals.updates, [])


if __name__ == "__main__":
    unittest.main()
