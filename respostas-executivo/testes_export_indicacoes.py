#!/usr/bin/env python3
"""Testes do export público de INDICAÇÕES (sem Google: as três leituras da aba são
listas montadas à mão, com o cabeçalho real da aba "indicações").

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import argparse
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export  # noqa: E402
from export import (  # noqa: E402
    CAMPOS_PUBLICOS_INDICACOES, campos_fora_da_lista_indicacoes, dados_pessoais,
    montar_indicacoes,
)

CAB = ["sta", "Assunto", "Data da Sessão", "Número", "Data do Protocolo na PMS", "Prazo",
       "Resposta", "Data da resposta", "A contento", "Bairro", "Situação da resposta",
       "Data da resposta de mérito"]
LINK = '=HYPERLINK("https://drive.google.com/drive/folders/pasta1";"Resposta")'
# conteúdo das colunas internas: nada disso pode aparecer no índice público
INTERNO = {"sta": "17", "protocolo": "PROTOCOLO-INTERNO", "prazo": "SIM",
           "contento": "pediu número — falar com o Rui"}


def serial(d, m, a):
    return (date(a, m, d) - date(1899, 12, 30)).days


def _linha(numero, assunto="", sessao=None, robo=True, resposta="", data_resp=None,
           bairro="", situacao="", merito=None, interno=True):
    """Uma linha nas três leituras. Datas são (d, m, a): o bruto é o nº de série e o
    exibido segue o formato de quem escreveu — robô dd/mm/aaaa, assessoria M/D/AAAA."""
    def exib(t):
        if t is None:
            return ""
        if isinstance(t, str):
            return t
        d, m, a = t
        return f"{d:02d}/{m:02d}/{a}" if robo else f"{m}/{d}/{a}"

    def bruto(t):
        return "" if t is None else (t if isinstance(t, str) else serial(*t))

    i = dict(INTERNO) if interno else {k: "" for k in INTERNO}
    resp_exib = "Resposta" if resposta.startswith("=") else resposta
    valores = [i["sta"], assunto, exib(sessao), numero, i["protocolo"], i["prazo"], resp_exib,
               exib(data_resp), i["contento"], bairro, situacao, exib(merito)]
    formulas = list(valores)
    formulas[6] = resposta
    brutos = list(valores)
    brutos[2], brutos[7], brutos[11] = bruto(sessao), bruto(data_resp), bruto(merito)
    return {"valores": valores, "formulas": formulas, "brutos": brutos}


def _aba(*linhas):
    return ([CAB] + [x["valores"] for x in linhas], [CAB] + [x["formulas"] for x in linhas],
            [CAB] + [x["brutos"] for x in linhas])


def _um(*linhas):
    itens, rel = montar_indicacoes(*_aba(*linhas))
    return itens, rel


# Caso real (26/2025): a linha da assessoria (resumo + bairro, datas M/D) no começo da
# aba e a do robô (ementa da Câmara + data de mérito) anexada lá embaixo.
ASSESSORIA = _linha("26/2025", "Canteiro em frente a UBS Odete", (4, 2, 2025), robo=False,
                    resposta=LINK, data_resp=(25, 4, 2025), bairro="PONTA DA PRAIA",
                    situacao="respondido")
ROBO = _linha("26/2025", "\xa0Indica ao Executivo a manutenção de canteiros em frente a UBS "
              "Odete Gomes de Rosis.", (4, 2, 2025), resposta=LINK, data_resp=(25, 4, 2025),
              situacao="respondido", merito=(25, 4, 2025), interno=False)


class TestJuncao(unittest.TestCase):
    def test_linhas_repetidas_viram_uma_indicacao(self):
        itens, rel = _um(ASSESSORIA, _linha("25/2025", "Outra", (4, 2, 2025), robo=False), ROBO)
        self.assertEqual([i["numero"] for i in itens], ["26/2025", "25/2025"])
        i = itens[0]
        # texto e datas da linha do robô (sem o espaço inquebrável); bairro da assessoria
        self.assertEqual(i["assunto"], "Indica ao Executivo a manutenção de canteiros em "
                                       "frente a UBS Odete Gomes de Rosis.")
        self.assertEqual((i["data_sessao"], i["data_resposta"], i["data_resposta_merito"]),
                         ("04/02/2025", "25/04/2025", "25/04/2025"))
        self.assertEqual((i["bairro"], i["regiao"]), ("Ponta da Praia", ""))
        self.assertEqual((i["situacao"], i["respondido"]), ("respondido", True))
        self.assertEqual(i["url_resposta"], "https://drive.google.com/drive/folders/pasta1")
        self.assertEqual(rel["grupos"], {2: 1, 1: 1})
        self.assertEqual(rel["assuntos_diferentes"], [])  # resumo e ementa falam da mesma coisa

    def test_juncao_nao_depende_da_ordem_das_linhas(self):
        a, _ = _um(ASSESSORIA, ROBO)
        b, _ = _um(ROBO, ASSESSORIA)
        self.assertEqual(a, b)

    def test_sem_data_de_merito_vale_o_formato_do_robo(self):
        # 2 linhas sem mérito: a do robô é a da sessão em dd/mm (a assessoria exibe M/D)
        robo = _linha("900/2026", "Indica ao Executivo a poda de árvore.", (12, 3, 2026))
        assessoria = _linha("900/2026", "Poda árvore", (12, 3, 2026), robo=False, bairro="GONZAGA")
        for ordem in ((robo, assessoria), (assessoria, robo)):
            i = _um(*ordem)[0][0]
            self.assertEqual(i["assunto"], "Indica ao Executivo a poda de árvore.")
            self.assertEqual(i["bairro"], "Gonzaga")
            self.assertEqual(i["situacao"], "pendente")

    def test_tres_linhas_e_sim_na_coluna_resposta(self):
        # 7238/2025: assessoria com "SIM", cópia com espaço inquebrável, robô com mérito
        itens, _ = _um(
            _linha("7238/2025", "Indica ao Executivo o reparo da linha 42.", (11, 11, 2025),
                   robo=False, resposta="SIM", data_resp=(14, 1, 2026)),
            _linha("7238/2025", "\xa0Indica ao Executivo o reparo da linha 42.", (11, 11, 2025),
                   resposta=LINK, data_resp=(14, 1, 2026), situacao="respondido"),
            _linha("7238/2025", "Indica ao Executivo o reparo da linha 42.", (11, 11, 2025),
                   resposta=LINK, data_resp=(14, 1, 2026), situacao="respondido",
                   merito=(14, 1, 2026)))
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["situacao"], "respondido")
        self.assertEqual(itens[0]["data_resposta_merito"], "14/01/2026")

    def test_datas_divergentes_vale_a_do_robo(self):
        # 7441/2025: a assessoria anotou 27/11, a Câmara diz 25/11
        itens, rel = _um(
            _linha("7441/2025", "Resumo", (27, 11, 2025), robo=False, bairro="EMBARÉ"),
            _linha("7441/2025", "Indica ao Executivo algo.", (25, 11, 2025), resposta=LINK,
                   situacao="respondido", merito=(10, 12, 2025)))
        self.assertEqual(itens[0]["data_sessao"], "25/11/2025")
        self.assertEqual(rel["datas"]["sessao:divergente"], 1)

    def test_numero_invalido_e_zero_a_esquerda(self):
        itens, rel = _um(
            _linha("", "Indica ao Executivo a poda (sem número)", (4, 2, 2025)),
            _linha("27/08/2026", "linha-fantasma", (4, 2, 2025)),
            _linha("0845/2026", "Indica ao Executivo X.", (26, 2, 2026)),
            _linha("845/2026", "X", (26, 2, 2026), robo=False, bairro="CENTRO"))
        self.assertEqual([i["numero"] for i in itens], ["845/2026"])
        self.assertEqual(itens[0]["bairro"], "Centro")
        self.assertEqual(rel["descartadas"], [2, 3])


class TestPrivacidade(unittest.TestCase):
    def test_colunas_internas_nunca_saem(self):
        itens, _ = _um(ASSESSORIA, ROBO)
        texto = json.dumps(itens, ensure_ascii=False)
        for v in INTERNO.values():
            self.assertNotIn(v, texto)
        self.assertEqual(campos_fora_da_lista_indicacoes(itens), set())
        self.assertLessEqual(set(itens[0]), set(CAMPOS_PUBLICOS_INDICACOES))
        self.assertEqual(set(itens[0]), set(CAMPOS_PUBLICOS_INDICACOES))

    def test_texto_cru_do_bairro_nunca_sai(self):
        itens, rel = _um(
            _linha("1/2026", "A", (6, 1, 2026), bairro="RESPOSTA EM 07 MESES"),
            _linha("2/2026", "B", (6, 1, 2026), bairro="ITARARÉ"),
            _linha("3/2026", "C", (6, 1, 2026), bairro="GERAL"),
            _linha("4/2026", "D", (6, 1, 2026), bairro="JD. CASTELO"))
        por_num = {i["numero"]: i for i in itens}
        self.assertEqual((por_num["1/2026"]["bairro"], por_num["1/2026"]["regiao"]), ("", ""))
        self.assertEqual((por_num["2/2026"]["bairro"], por_num["2/2026"]["regiao"]), ("", ""))
        self.assertEqual((por_num["3/2026"]["bairro"], por_num["3/2026"]["regiao"]), ("", "Cidade toda"))
        self.assertEqual(por_num["4/2026"]["bairro"], "Castelo")
        texto = json.dumps(itens, ensure_ascii=False)
        for cru in ("RESPOSTA EM 07 MESES", "07 MESES", "ITARARÉ", "Itararé", "GERAL", "JD."):
            self.assertNotIn(cru, texto)
        # o relatório guarda as grafias (só para o --dry-run local)
        self.assertEqual(rel["nao_reconhecidos"], {"RESPOSTA EM 07 MESES": 1, "ITARARÉ": 1})

    def test_situacao_sai_de_um_vocabulario_fechado(self):
        itens, _ = _um(
            _linha("1/2026", "A", (6, 1, 2026), situacao="ok (Falar com o Rui)"),
            _linha("2/2026", "B", (6, 1, 2026), resposta="SIM", data_resp=(9, 2, 2026)),
            _linha("3/2026", "C", (6, 1, 2026), resposta=LINK, situacao="so_encaminhamento"),
            _linha("4/2026", "D", (6, 1, 2026), resposta=LINK))
        sit = {i["numero"]: (i["situacao"], i["respondido"]) for i in itens}
        self.assertEqual(sit, {
            "1/2026": ("pendente", False),       # texto estranho na coluna é ignorado
            "2/2026": ("a_classificar", False),  # o gabinete registrou resposta, sem classificar
            "3/2026": ("so_encaminhamento", False),
            "4/2026": ("a_classificar", False),  # pasta no Drive sem veredito
        })
        self.assertNotIn("Falar com o Rui", json.dumps(itens, ensure_ascii=False))

    def test_dados_pessoais_no_assunto(self):
        self.assertEqual(dados_pessoais("Indica ao Executivo a poda na Rua X, nº 323."), ([], False))
        self.assertEqual(dados_pessoais("Contato fulano@gmail.com")[0], ["e-mail"])
        self.assertEqual(dados_pessoais("Morador CPF 123.456.789-09")[0], ["CPF"])
        self.assertEqual(dados_pessoais("Morador CPF nº 12345678909")[0], ["CPF"])
        self.assertEqual(dados_pessoais("documento 52998224725 do morador")[0], ["CPF"])  # DV válido
        self.assertEqual(dados_pessoais("protocolo 12345678901")[0], [])  # 11 dígitos, DV inválido
        self.assertEqual(dados_pessoais("ligar (13) 99123-4567"), ([], True))
        self.assertEqual(dados_pessoais("Requerimento 1729/2026 e Lei 3.531/2018"), ([], False))


class TestDatas(unittest.TestCase):
    def test_texto_e_ano_com_digito_a_mais(self):
        itens, rel = _um(
            _linha("1384/2025", "Conserto aquecedor", "18/03/82025", robo=False),
            _linha("1385/2025", "Outro", "31/02/2025"),
            _linha("1386/2025", "Mais um", "03/04/2025"))
        por_num = {i["numero"]: i["data_sessao"] for i in itens}
        self.assertEqual(por_num, {"1384/2025": "18/03/2025", "1385/2025": "", "1386/2025": "03/04/2025"})
        self.assertEqual((rel["datas"]["sessao:consertada"], rel["datas"]["sessao:invalida"]), (1, 1))


class TestMain(unittest.TestCase):
    def _rodar(self, itens):
        rel = montar_indicacoes([], [], [])[1]
        with tempfile.TemporaryDirectory() as tmp:
            destino = os.path.join(tmp, "indicacoes-index.json")
            args = argparse.Namespace(dry_run=False, salvar=destino)
            with mock.patch.object(export, "coletar_indicacoes", return_value=(itens, rel)), \
                    mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                codigo = export.main_indicacoes(args)
            return codigo, os.path.exists(destino)

    def test_aborta_com_campo_fora_da_lista(self):
        item = dict(montar_indicacoes(*_aba(ASSESSORIA, ROBO))[0][0], bairro_planilha="X")
        self.assertEqual(self._rodar([item]), (1, False))

    def test_aborta_com_email_no_assunto(self):
        item = dict(montar_indicacoes(*_aba(ASSESSORIA, ROBO))[0][0], assunto="a@b.com.br")
        self.assertEqual(self._rodar([item]), (1, False))

    def test_grava_quando_limpo(self):
        itens = montar_indicacoes(*_aba(ASSESSORIA, ROBO))[0]
        self.assertEqual(self._rodar(itens), (0, True))


if __name__ == "__main__":
    unittest.main()
