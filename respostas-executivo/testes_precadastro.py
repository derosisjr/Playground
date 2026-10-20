#!/usr/bin/env python3
"""Pré-cadastro (R5) sem rede: a listagem da Câmara é falsa e respeita o `parar`.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camara  # noqa: E402
import planilha  # noqa: E402
import precadastro as pc  # noqa: E402

ABAS = {"Requerimento": "requerimentos", "Indicação": "indicações"}


def _b(numero, subtipo="Requerimento", situacao="Aprovado", ementa="Oficiar ao Executivo sobre a poda."):
    return {"cod": numero.split("/")[0], "subtipo": subtipo, "numero": numero, "situacao": situacao,
            "data": "15/10/2026", "ementa": ementa}


def _listagem(paginas: dict):
    """listar_autor falso: `paginas` = {(ano, codigo): [[blocos], ...]}; registra o que foi lido."""
    lidas = []

    def listar(ano, codigo, parar=None):
        itens = []
        for n, blocos in enumerate(paginas.get((str(ano), codigo), [])):
            lidas.append((str(ano), codigo, n))
            itens.extend(blocos)
            if parar and parar(blocos):
                break
        return itens
    return listar, lidas


class TestColetaEPlano(unittest.TestCase):
    def test_plano_cria_o_que_falta_e_acerta_o_espelho(self):
        paginas = {("2026", camara.TIPO_REQUERIMENTO): [[
            _b("10/2026", situacao="-"),                               # novo, ainda não votado
            _b("9/2026", situacao="Aprovado"),                         # já na planilha, situação mudou
            _b("8/2026"),                                              # já na planilha, igual
            _b("1/2026", subtipo="Requerimento de Convite"),           # outro subtipo: fora
        ]], ("2026", camara.TIPO_INDICACAO): [[_b("700/2026", subtipo="Indicação", situacao="Encaminhado")]]}
        conhecidos = {"requerimentos": {"9/2026": "-", "8/2026": "Aprovado"}, "indicações": {}}
        listar, _ = _listagem(paginas)
        with mock.patch.object(camara, "listar_autor", side_effect=listar):
            itens, fora = pc.coletar(["2026"], conhecidos, True, ABAS)
        self.assertEqual([f["numero"] for f in fora], ["1/2026"])
        novas, espelho = pc.planejar(itens, conhecidos)
        self.assertEqual([(n.aba, n.numero) for n in novas], [("requerimentos", "10/2026"), ("indicações", "700/2026")])
        self.assertEqual(novas[0].valores, {"Assunto": "Oficiar ao Executivo sobre a poda.",
                                            "Ementa (Câmara)": "Oficiar ao Executivo sobre a poda.",
                                            "Data da Sessão": "15/10/2026", "Situação na Câmara": "-"})
        self.assertEqual([(e.numero, e.valores) for e in espelho], [("9/2026", {"Situação na Câmara": "Aprovado"})])
        # o motor aceita exatamente estas colunas (nada da equipe)
        for p in novas + espelho:
            permitidas = planilha.COLUNAS_RESPOSTA + (planilha.COLUNAS_CRIACAO if isinstance(p, planilha.NovaLinha)
                                                      else planilha.COLUNAS_ESPELHO)
            self.assertLessEqual(set(p.valores), set(permitidas))

    def test_diaria_para_depois_de_duas_paginas_sem_novidade(self):
        paginas = {("2026", camara.TIPO_REQUERIMENTO): [
            [_b("30/2026")],                     # novo
            [_b("29/2026")], [_b("28/2026")],    # conhecidos e iguais: 2 seguidas → para
            [_b("27/2026")],                     # não chega a ser lida
        ]}
        conhecidos = {"requerimentos": {"29/2026": "Aprovado", "28/2026": "Aprovado", "27/2026": "-"},
                      "indicações": {}}
        listar, lidas = _listagem(paginas)
        with mock.patch.object(camara, "listar_autor", side_effect=listar):
            itens, _ = pc.coletar(["2026"], conhecidos, False, ABAS)
        self.assertEqual([n for a, c, n in lidas if c == camara.TIPO_REQUERIMENTO], [0, 1, 2])
        self.assertEqual([i["numero"] for i in itens], ["30/2026", "29/2026", "28/2026"])
        # completa: lê tudo (e acha o 27/2026 que mudou de situação)
        listar, lidas = _listagem(paginas)
        with mock.patch.object(camara, "listar_autor", side_effect=listar):
            itens, _ = pc.coletar(["2026"], conhecidos, True, ABAS)
        self.assertIn("27/2026", [i["numero"] for i in itens])


class TestConciliacao(unittest.TestCase):
    def test_numero_de_outro_subtipo_e_o_que_nao_e_do_autor(self):
        itens = [{**_b("2/2026", ementa="Oficiar ao Executivo sobre a reforma da Escola Municipal X."),
                  "aba": "requerimentos", "tipo": "Requerimento"},
                 {**_b("3/2026"), "aba": "requerimentos", "tipo": "Requerimento"}]
        fora = [{**_b("1/2026", subtipo="Requerimento de Convite"), "aba": "requerimentos", "tipo": "Requerimento"}]
        na_planilha = {"requerimentos": {"1/2026": "Reforma da Escola Municipal X", "3/2026": "poda"},
                       "indicações": {"6680/2025": "Tapa-buraco"}}
        achados = {(a["aba"], a["numero"]): a for a in pc.conciliar(itens, fora, na_planilha)}
        self.assertEqual(achados[("requerimentos", "1/2026")]["motivo"], "na Câmara é Requerimento de Convite")
        self.assertEqual(achados[("requerimentos", "1/2026")]["provavel"], "2/2026")
        self.assertEqual(achados[("indicações", "6680/2025")]["motivo"], "não aparece entre os pedidos do autor")
        self.assertNotIn(("requerimentos", "3/2026"), achados)


if __name__ == "__main__":
    unittest.main()
