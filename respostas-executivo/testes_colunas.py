#!/usr/bin/env python3
"""`garantir_colunas` só cria as colunas que a automação grava (cliente falso).

Em 12/10/2026 ela criou "Ordem", "Prazo" e "Data do Protocolo na PMS" vazias no
fim da aba de requerimentos, porque tentava completar TODAS as colunas de ABAS.

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
    def __init__(self, cab):
        self.cab, self.updates = cab, []

    def get(self, **kwargs):
        return _Exec({"values": [self.cab]})

    def update(self, **kwargs):
        return _Exec(registro=self.updates, kwargs=kwargs)


class _Sheets:
    def __init__(self, cab):
        self.vals = _Values(cab)

    def spreadsheets(self):
        return self

    def values(self):
        return self.vals


# cabeçalho real da aba em out/2026 (sem as duplicatas criadas em 12/10)
REAL = ["Assunto", "Secretaria", "Data da Sessão", "Nùmero", "Resposta",
        "Data da resposta", "Status atual", "Situação", "observação"]


class TestGarantirColunas(unittest.TestCase):
    def test_cria_so_as_de_classificacao(self):
        s = _Sheets(list(REAL))
        cab = garantir_colunas(s, "id", ABA_REQUERIMENTOS)
        self.assertEqual(cab, REAL + [COL_SITUACAO, COL_DATA_MERITO])
        for manual in ("Ordem", "Prazo", "Data do Protocolo na PMS"):
            self.assertNotIn(manual, cab)
        self.assertEqual(len(s.vals.updates), 1)

    def test_nada_a_fazer_quando_ja_existem(self):
        s = _Sheets(REAL + [COL_SITUACAO, COL_DATA_MERITO])
        garantir_colunas(s, "id", ABA_REQUERIMENTOS)
        self.assertEqual(s.vals.updates, [])


if __name__ == "__main__":
    unittest.main()
