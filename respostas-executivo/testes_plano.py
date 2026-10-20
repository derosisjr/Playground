#!/usr/bin/env python3
"""Motor de escrita planejada (`planilha.aplicar`), com planilha falsa em memória.

As garantias que a equipe pediu (20/10/2026) — nada escrito à mão é apagado ou
sobrescrito, em nenhuma linha — são testadas aqui, não só prometidas:
  - cada escrita é resolvida pelo NÚMERO na hora de gravar (linhas deslocadas no meio);
  - célula preenchida não é sobrescrita sem documento de resposta novo;
  - coluna que não é do robô é recusada antes de gravar qualquer coisa;
  - não existe exclusão: a única chamada de gravação é values.batchUpdate com valores.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from planilha import Escrita, EscritaProibida, NovaLinha, aplicar  # noqa: E402

PASTA_A = '=HYPERLINK("https://drive.google.com/drive/folders/PASTA_AAAAAA";"Resposta")'
PASTA_B = '=HYPERLINK("https://drive.google.com/drive/folders/PASTA_BBBBBB";"Resposta")'
CAB = ["sta", "Assunto", "Data da Sessão", "Número", "Resposta", "Data da resposta",
       "A contento", "Bairro", "Situação da resposta", "Data da resposta de mérito"]


class _Planilha:
    """Grade com duas leituras (exibido e fórmula) e registro das gravações."""

    def __init__(self, abas):
        # abas = {nome: [linha, ...]} onde cada célula é valor ou (exibido, formula)
        self.abas = abas
        self.lotes = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range, valueRenderOption="FORMATTED_VALUE"):
        # célula = valor ou (exibido, fórmula[, bruto]); sem bruto, o bruto é o exibido
        grade = self.abas[range.strip("'")]
        i = {"FORMULA": 1, "UNFORMATTED_VALUE": 2}.get(valueRenderOption, 0)
        return _Exec({"values": [[(c[i] if i < len(c) else c[0]) if isinstance(c, tuple) else c
                                  for c in linha] for linha in grade]})

    def batchUpdate(self, spreadsheetId, body):
        self.lotes.append(body)
        return _Exec({})


class _Exec:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


def _linha(numero, resposta="", data="", sit="", sta="", bairro=""):
    cel_resp = ("Resposta", resposta) if resposta else ""
    return [sta, "assunto", "13/03/2025", numero, cel_resp, data, "", bairro, sit, ""]


def _gravadas(planilha):
    """{range: valor} de todas as gravações."""
    out = {}
    for lote in planilha.lotes:
        assert set(lote) == {"valueInputOption", "data"}, lote  # só valores, nada estrutural
        for d in lote["data"]:
            out[d["range"]] = d["values"]
    return out


class TestAplicar(unittest.TestCase):
    def test_preenche_celula_vazia_pela_linha_do_numero_na_hora(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026"), _linha("11/2026")]})
        plano = [Escrita("indicações", "11/2026", {"Resposta": PASTA_A, "Data da resposta": "01/10/2026",
                                                   "Situação da resposta": "respondido"})]
        # a equipe inseriu uma linha no topo entre a leitura e a gravação
        p.abas["indicações"].insert(1, _linha("99/2026"))
        rel = aplicar(p, "id", plano)
        g = _gravadas(p)
        self.assertEqual(set(g), {"'indicações'!E4", "'indicações'!F4", "'indicações'!I4"})
        self.assertEqual(rel.escritas, [("indicações", "11/2026")])
        self.assertEqual(rel.celulas, 3)

    def test_nao_sobrescreve_sem_documento_novo(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026", PASTA_A, "01/09/2026", "so_prorrogacao")]})
        rel = aplicar(p, "id", [Escrita("indicações", "10/2026",
                                        {"Data da resposta": "05/10/2026", "Situação da resposta": "respondido"})])
        self.assertEqual(p.lotes, [])
        self.assertEqual(sorted(c for _, _, c in rel.divergencias), ["Data da resposta", "Situação da resposta"])

    def test_documento_novo_atualiza_as_colunas_de_resposta(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026", PASTA_A, "01/09/2026", "so_prorrogacao")]})
        aplicar(p, "id", [Escrita("indicações", "10/2026",
                                  {"Data da resposta": "05/10/2026", "Situação da resposta": "respondido"},
                                  resposta_nova=True)])
        self.assertEqual(_gravadas(p), {"'indicações'!F2": [["05/10/2026"]], "'indicações'!I2": [["respondido"]]})

    def test_mesmo_valor_nao_regrava(self):
        # mesma pasta no hyperlink e mesma data (exibida em outro formato)
        p = _Planilha({"indicações": [CAB, _linha("10/2026", PASTA_A, "1/9/2026", "respondido")]})
        rel = aplicar(p, "id", [Escrita("indicações", "10/2026",
                                        {"Resposta": PASTA_A, "Data da resposta": "01/09/2026",
                                         "Situação da resposta": "respondido"})])
        self.assertEqual((p.lotes, rel.divergencias, rel.escritas), ([], [], []))

    def test_data_pelo_valor_e_nao_pelo_texto_exibido(self):
        # parte da planilha real exibe m/d/aaaa: "5/20/2026" é 20/05/2026 (nº de série 46162)
        serial = (datetime(2026, 5, 20) - datetime(1899, 12, 30)).days
        linha = _linha("10/2026", PASTA_A, "", "respondido")
        linha[5] = ("5/20/2026", "5/20/2026", serial)
        p = _Planilha({"indicações": [CAB, linha]})
        rel = aplicar(p, "id", [Escrita("indicações", "10/2026", {"Data da resposta": "20/05/2026"})])
        self.assertEqual((p.lotes, rel.divergencias), ([], []))
        rel = aplicar(p, "id", [Escrita("indicações", "10/2026", {"Data da resposta": "05/02/2026"})])
        self.assertEqual(rel.divergencias, [("indicações", "10/2026", "Data da resposta")])

    def test_pasta_diferente_e_divergencia(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026", PASTA_A)]})
        rel = aplicar(p, "id", [Escrita("indicações", "10/2026", {"Resposta": PASTA_B})])
        self.assertEqual(p.lotes, [])
        self.assertEqual(rel.divergencias, [("indicações", "10/2026", "Resposta")])

    def test_coluna_da_equipe_e_recusada_antes_de_gravar_qualquer_coisa(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026"), _linha("11/2026")]})
        plano = [Escrita("indicações", "10/2026", {"Resposta": PASTA_A}),
                 Escrita("indicações", "11/2026", {"Bairro": "Gonzaga"})]
        with self.assertRaises(EscritaProibida):
            aplicar(p, "id", plano)
        self.assertEqual(p.lotes, [])
        for coluna in ("A contento", "sta", "Status atual", "observação", "Assunto"):
            with self.assertRaises(EscritaProibida):
                aplicar(p, "id", [Escrita("indicações", "10/2026", {coluna: "x"})])

    def test_linha_nova_vai_depois_da_ultima_e_segue_o_cabecalho(self):
        cab = ["Número", "sta", "Resposta", "Assunto", "Data da Sessão"]  # outra ordem
        p = _Planilha({"indicações": [cab, ["10/2026", "x", "", "a", "01/01/2026"]]})
        rel = aplicar(p, "id", [NovaLinha("indicações", "12/2026", {
            "Número": "0012/2026", "Assunto": "Poda", "Data da Sessão": "02/10/2026", "Resposta": PASTA_A,
            "Data da resposta": ""})])
        # só as células do robô, uma a uma: a coluna "sta" da linha nova não é tocada, e o
        # número vai na forma canônica
        self.assertEqual(_gravadas(p), {"'indicações'!A3": [["12/2026"]], "'indicações'!C3": [[PASTA_A]],
                                        "'indicações'!D3": [["Poda"]], "'indicações'!E3": [["02/10/2026"]]})
        self.assertEqual(rel.novas, [("indicações", "12/2026", 3)])
        self.assertEqual(rel.celulas, 4)

    def test_valor_vazio_nunca_limpa_celula(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026", PASTA_A, "01/09/2026", "respondido")]})
        rel = aplicar(p, "id", [Escrita("indicações", "10/2026",
                                        {"Data da resposta": "", "Data da resposta de mérito": ""},
                                        resposta_nova=True)])
        self.assertEqual((p.lotes, rel.escritas, rel.divergencias), ([], [], []))

    def test_limpar_so_coluna_de_resposta_e_com_autorizacao(self):
        linha = _linha("10/2026", PASTA_A, "01/09/2026", "respondido")
        linha[9] = "01/09/2026"  # Data da resposta de mérito
        p = _Planilha({"indicações": [CAB, linha]})
        for errada in (Escrita("indicações", "10/2026", {}, limpar=("Data da resposta de mérito",)),
                       Escrita("indicações", "10/2026", {}, resposta_nova=True, limpar=("Bairro",)),
                       Escrita("indicações", "10/2026", {"Data da resposta de mérito": "02/09/2026"},
                               resposta_nova=True, limpar=("Data da resposta de mérito",))):
            with self.assertRaises(EscritaProibida):
                aplicar(p, "id", [errada])
        self.assertEqual(p.lotes, [])
        rel = aplicar(p, "id", [Escrita("indicações", "10/2026", {"Situação da resposta": "so_prorrogacao"},
                                        resposta_nova=True, limpar=("Data da resposta de mérito",))])
        self.assertEqual(_gravadas(p), {"'indicações'!I2": [["so_prorrogacao"]], "'indicações'!J2": [[""]]})
        self.assertEqual(rel.celulas, 2)

    def test_limpar_celula_ja_vazia_nao_grava(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026", PASTA_A, "01/09/2026", "respondido")]})
        aplicar(p, "id", [Escrita("indicações", "10/2026", {}, resposta_nova=True,
                                  limpar=("Data da resposta de mérito",))])
        self.assertEqual(p.lotes, [])

    def test_espelho_da_camara_acompanha_a_listagem(self):
        cab = CAB + ["Situação na Câmara"]
        p = _Planilha({"indicações": [cab, _linha("10/2026") + ["-"]]})
        rel = aplicar(p, "id", [Escrita("indicações", "10/2026", {"Situação na Câmara": "Aprovado"})])
        self.assertEqual(_gravadas(p), {"'indicações'!K2": [["Aprovado"]]})
        self.assertEqual(rel.divergencias, [])
        # e continua sendo só ela: as outras colunas da equipe seguem recusadas
        with self.assertRaises(EscritaProibida):
            aplicar(p, "id", [Escrita("indicações", "10/2026", {"Ementa (Câmara)": "x"})])

    def test_numero_fora_da_forma_canonica_e_recusado(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026")]})
        with self.assertRaises(ValueError):
            aplicar(p, "id", [Escrita("indicações", "010/2026", {"Resposta": PASTA_A})])
        self.assertEqual(p.lotes, [])

    def test_linha_nova_de_numero_que_ja_existe_nao_duplica(self):
        p = _Planilha({"indicações": [CAB, _linha("0845/2026")]})
        rel = aplicar(p, "id", [NovaLinha("indicações", "845/2026", {"Número": "845/2026"})])
        self.assertEqual(p.lotes, [])
        self.assertEqual(rel.ja_existia, [("indicações", "845/2026")])

    def test_linha_nova_nao_aceita_coluna_da_equipe(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026")]})
        with self.assertRaises(EscritaProibida):
            aplicar(p, "id", [NovaLinha("indicações", "12/2026", {"Número": "12/2026", "Bairro": "x"})])

    def test_linha_que_sumiu_e_relatada(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026")]})
        rel = aplicar(p, "id", [Escrita("indicações", "77/2026", {"Resposta": PASTA_A})])
        self.assertEqual((p.lotes, rel.sem_linha), ([], [("indicações", "77/2026")]))

    def test_numero_repetido_grava_na_ultima(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026", sta="equipe"), _linha("10/2026")]})
        aplicar(p, "id", [Escrita("indicações", "10/2026", {"Situação da resposta": "respondido"})])
        self.assertEqual(set(_gravadas(p)), {"'indicações'!I3"})

    def test_aba_sem_coluna_do_numero_aborta(self):
        p = _Planilha({"indicações": [["x", "Resposta"], ["1", ""]]})
        with self.assertRaises(RuntimeError):
            aplicar(p, "id", [Escrita("indicações", "1/2026", {"Resposta": PASTA_A})])
        self.assertEqual(p.lotes, [])

    def test_uma_gravacao_so_para_varias_abas(self):
        p = _Planilha({"indicações": [CAB, _linha("10/2026")],
                       "requerimentos": [["Nùmero", "Resposta"], ["5/2026", ""]]})
        aplicar(p, "id", [Escrita("indicações", "10/2026", {"Resposta": PASTA_A}),
                          Escrita("requerimentos", "5/2026", {"Resposta": PASTA_B})])
        self.assertEqual(len(p.lotes), 1)
        self.assertEqual(set(_gravadas(p)), {"'indicações'!E2", "'requerimentos'!B2"})


if __name__ == "__main__":
    unittest.main()
