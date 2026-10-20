#!/usr/bin/env python3
"""Prazo da Lei Orgânica (art. 58, XVIII), desdobramentos citados no assunto e
sigla da secretaria — regras puras, sem rede.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest
from datetime import date

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.append(os.path.dirname(AQUI))  # comum/ (usado por secretarias.py)
import prazos  # noqa: E402
from secretarias import canonica  # noqa: E402


class TestVencimento(unittest.TestCase):
    def test_sem_resposta_vence_em_15_dias(self):
        self.assertEqual(prazos.vence_em("04/02/2025", "pendente"), "19/02/2025")
        self.assertEqual(prazos.vence_em("04/02/2025", "so_encaminhamento"), "19/02/2025")

    def test_prorrogacao_dobra_o_prazo(self):
        self.assertEqual(prazos.vence_em("04/02/2025", "so_prorrogacao"), "06/03/2025")

    def test_respondido_e_data_invalida_nao_vencem(self):
        self.assertEqual(prazos.vence_em("04/02/2025", "respondido"), "")
        self.assertEqual(prazos.vence_em("", "pendente"), "")
        self.assertEqual(prazos.vence_em("31/02/2025", "pendente"), "")

    def test_fora_do_prazo_compara_com_hoje(self):
        item = {"situacao": "pendente", "vence_em": "19/02/2025"}
        self.assertFalse(prazos.fora_do_prazo(item, date(2025, 2, 19)))  # último dia
        self.assertTrue(prazos.fora_do_prazo(item, date(2025, 2, 20)))
        self.assertFalse(prazos.fora_do_prazo({"situacao": "respondido", "vence_em": ""},
                                              date(2030, 1, 1)))


class TestEnviado(unittest.TestCase):
    def test_so_aprovado_ou_encaminhado_e_vazio(self):
        for sim in ("Aprovado", "Encaminhado", " aprovado ", ""):
            self.assertTrue(prazos.enviado(sim), sim)
        for nao in ("-", "Aguardando Votação", "Retirado"):
            self.assertFalse(prazos.enviado(nao), nao)


class TestCitados(unittest.TestCase):
    def test_formatos_reais_da_planilha(self):
        self.assertEqual(prazos.citados("Resposta ao Requerimento 10/2025C - omplementação"), ["10/2025"])
        self.assertEqual(prazos.citados("Resposta rrequerimento 938/2025 - Locação"), ["938/2025"])
        self.assertEqual(prazos.citados("informações relacionadas à resposta ao requerimento 278/2025"),
                         ["278/2025"])
        self.assertEqual(prazos.citados("Requerimento nº 1.022/2025 e requerimento n. 1022/2025"),
                         ["1022/2025"])

    def test_sem_citacao_e_numero_absurdo(self):
        self.assertEqual(prazos.citados("Cargos de Assessoria Empresas Públicas"), [])
        self.assertEqual(prazos.citados("requerimento 1234567/2025"), [])


class TestSecretaria(unittest.TestCase):
    def test_sinonimos_unificados(self):
        self.assertEqual(canonica("COMUNICAÇÃO"), "SECOM")
        self.assertEqual(canonica("Saúde"), "SMS")
        self.assertEqual(canonica("SED´S"), "SEDS")
        self.assertEqual(canonica("SETUR"), "SECTUR")
        self.assertEqual(canonica(" secult "), "SECULT")

    def test_par_em_qualquer_ordem(self):
        self.assertEqual(canonica("SEDUC/SEDS"), canonica("SEDS/SEDUC"))

    def test_o_que_nao_e_secretaria_fica_vazio(self):
        for v in ("", "NÃO SEI", "#NAME?", "GERAL", "EMPRESAS", "SEMPRE", "12/05/2026"):
            self.assertEqual(canonica(v), "", v)


if __name__ == "__main__":
    unittest.main()
