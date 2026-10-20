#!/usr/bin/env python3
"""Mescla das indicações repetidas (R4), sem rede: uma planilha falsa em memória que faz
cópia de aba, gravação de valores e exclusão de linha como a API do Google.

Garantias testadas: nada da equipe é apagado nem sobrescrito; grupo com conflito não é
mexido; o item publicado no site sai igual; a cópia da aba vem antes de qualquer escrita;
hash errado não faz nada; linha que mudou no meio não é apagada.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import contextlib
import copy
import io
import os
import re
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export  # noqa: E402
import mesclar_indicacoes as mi  # noqa: E402

CAB = ["sta", "Assunto", "Data da Sessão", "Número", "Data do Protocolo na PMS", "Prazo",
       "Resposta", "Data da resposta", "A contento", "Bairro", "Situação da resposta",
       "Data da resposta de mérito"]
LINK = '=HYPERLINK("https://drive.google.com/drive/folders/PASTA_AAAAAAAA";"Resposta")'


def serial(d, m, a):
    return (date(a, m, d) - date(1899, 12, 30)).days


def data(d, m, a, robo=True):
    """Célula de data: exibida dd/mm (robô) ou M/D (equipe); bruto = nº de série."""
    texto = f"{d:02d}/{m:02d}/{a}" if robo else f"{m}/{d}/{a}"
    return (texto, texto, serial(d, m, a))


def equipe(numero, assunto="Poda na rua X", sta="17", bairro="GONZAGA", resposta="", protocolo=""):
    return [sta, assunto, data(4, 2, 2025, robo=False), numero, protocolo, "", resposta, "", "",
            bairro, "", ""]


def robo(numero, ementa="Indica ao Executivo a poda de árvore na rua X.", merito=True):
    return ["", ementa, data(4, 2, 2025), numero, "", "", ("Resposta", LINK, LINK), data(25, 4, 2025),
            "", "", "respondido", data(25, 4, 2025) if merito else ""]


_INTERVALO = range  # o get() da API tem um parâmetro chamado "range"


class _Planilha:
    def __init__(self, linhas, notas=()):
        self.abas = {"indicações": [list(CAB)] + [list(x) for x in linhas]}
        self.notas = set(notas)  # (linha base 0, coluna)
        self.chamadas = []       # ordem das operações de escrita
        self.ao_gravar = None    # gancho: a "equipe" mexe na planilha durante a mescla

    def spreadsheets(self):
        return self

    def values(self):
        return self

    @staticmethod
    def _render(c, i):
        if isinstance(c, tuple):
            return c[i]
        return c

    def get(self, spreadsheetId, range=None, valueRenderOption="FORMATTED_VALUE", ranges=None,
            includeGridData=False, fields=None):
        if ranges:  # meta da aba: id e notas
            linhas = len(self.abas["indicações"])
            row_data = [{"values": [{"note": "nota"} if (r, c) in self.notas else {}
                                    for c in _INTERVALO(len(CAB) + 1)]} for r in _INTERVALO(linhas)]
            return _Exec({"sheets": [{"properties": {"sheetId": 7}, "data": [{"rowData": row_data}]}]})
        if range is None:  # títulos das abas (e largura da grade)
            return _Exec({"sheets": [{"properties": {"title": t, "sheetId": i, "gridProperties": {"columnCount": 40}}}
                                     for i, t in enumerate(self.abas)]})
        i = {"FORMULA": 1, "UNFORMATTED_VALUE": 2}.get(valueRenderOption, 0)
        grade = self.abas[range.strip("'").split("'!")[0]]
        return _Exec({"values": [[self._render(c, i) for c in linha] for linha in grade]})

    def update(self, spreadsheetId, range, valueInputOption, body):
        self.chamadas.append(("cabecalho", range))
        aba, cel = re.fullmatch(r"'(.+)'!([A-Z]+)(\d+)", range).groups()[0], range
        col = ord(re.search(r"!([A-Z]+)", range).group(1)) - 65
        linha = self.abas[aba][0]
        linha.extend([""] * (col + 1 - len(linha)))
        linha[col] = body["values"][0][0]
        return _Exec({})

    def batchUpdate(self, spreadsheetId, body):
        if "data" in body:  # values.batchUpdate (USER_ENTERED)
            self.chamadas.append(("valores", len(body["data"])))
            for d in body["data"]:
                aba, col, lin = re.fullmatch(r"'(.+)'!([A-Z]+)(\d+)", d["range"]).groups()
                linha = self.abas[aba][int(lin) - 1]
                c = ord(col) - 65
                linha.extend([""] * (c + 1 - len(linha)))
                v = d["values"][0][0]
                m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", v)
                linha[c] = (v, v, serial(int(m[1]), int(m[2]), int(m[3]))) if m else (
                    ("Resposta", v, v) if v.startswith("=") else v)
            if self.ao_gravar:
                self.ao_gravar(self)
            return _Exec({})
        for req in body["requests"]:
            if "duplicateSheet" in req:
                self.chamadas.append(("copia", req["duplicateSheet"]["newSheetName"]))
                self.abas[req["duplicateSheet"]["newSheetName"]] = copy.deepcopy(self.abas["indicações"])
            elif "deleteDimension" in req:
                r = req["deleteDimension"]["range"]
                self.chamadas.append(("apaga", r["startIndex"]))
                del self.abas["indicações"][r["startIndex"]:r["endIndex"]]
            elif "appendDimension" in req:
                self.chamadas.append(("colunas", req["appendDimension"]["length"]))
        return _Exec({})


class _Drive:
    def __init__(self, comentarios=()):
        self.comentarios = list(comentarios)

    def comments(self):
        return self

    def list(self, **kw):
        return _Exec({"comments": self.comentarios})


class _Exec:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


def _export(p):
    aba = p.abas["indicações"]
    leituras = [[[_Planilha._render(c, i) for c in linha] for linha in aba] for i in range(3)]
    return export.montar_indicacoes(*leituras)[0]


def _aplicar(p, h, drive=None):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return mi.aplicar(drive or _Drive(), p, "S", h)


class TestSimular(unittest.TestCase):
    def test_par_limpo_mescla_e_o_item_publicado_nao_muda(self):
        p = _Planilha([equipe("26/2025"), equipe("30/2025", assunto="Outra"), robo("26/2025")])
        plano = mi.simular(mi.ler(p, "S"))
        self.assertEqual([g["numero"] for g in plano["mesclar"]], ["26/2025"])
        g = plano["mesclar"][0]
        self.assertEqual(g["linhas"], [2, 4])
        self.assertEqual(sorted(g["escritas"]), ["Data da resposta", "Data da resposta de mérito",
                                                  "Ementa (Câmara)", "Resposta", "Situação da resposta"])
        self.assertTrue(plano["criar_ementa"])

    def test_valor_da_equipe_so_na_linha_do_robo_e_copiado_para_a_celula_vazia(self):
        r = robo("26/2025")
        r[4] = "10/02/2025"  # protocolo anotado na linha de baixo
        p = _Planilha([equipe("26/2025"), r])
        g = mi.simular(mi.ler(p, "S"))["mesclar"][0]
        self.assertEqual(g["escritas"]["Data do Protocolo na PMS"], "10/02/2025")

    def test_conflitos_nao_sao_mexidos(self):
        diferente = robo("1/2025")
        diferente[0] = "99"  # "sta" diferente nas duas linhas
        casos = {
            "1/2025": [equipe("1/2025"), diferente],
            "2/2025": [equipe("2/2025", resposta="SIM"), robo("2/2025")],  # "SIM" digitado na Resposta
        }
        p = _Planilha([linha for linhas in casos.values() for linha in linhas] + [equipe("3/2025"), robo("3/2025")],
                      notas={(6, 1)})  # nota na linha do robô do 3/2025
        plano = mi.simular(mi.ler(p, "S"))
        motivos = {g["numero"]: g["motivos"] for g in plano["conflitos"]}
        self.assertEqual(motivos["1/2025"], ["coluna da equipe 'sta' diferente entre as linhas"])
        self.assertEqual(motivos["2/2025"], ["coluna do robô 'Resposta' com outro valor na linha que fica"])
        self.assertEqual(motivos["3/2025"], ["nota na linha que sairia"])
        self.assertEqual(plano["mesclar"], [])

    def test_trio(self):
        p = _Planilha([equipe("7238/2025"), robo("7238/2025", merito=False), robo("7238/2025")])
        g = mi.simular(mi.ler(p, "S"))["mesclar"][0]
        self.assertEqual(g["linhas"], [2, 3, 4])


class TestAplicar(unittest.TestCase):
    def preparar(self):
        p = _Planilha([equipe("26/2025"), equipe("30/2025", assunto="Outra"), robo("26/2025"),
                       equipe("1/2025"), robo("1/2025", ementa="Indica ao Executivo outra coisa.")])
        p.abas["indicações"][5][0] = "99"  # conflito no 1/2025: fica como está
        return p, mi.hash_plano(mi.simular(mi.ler(p, "S")))

    def test_hash_errado_nao_faz_nada(self):
        p, _ = self.preparar()
        self.assertEqual(_aplicar(p, "0000"), 1)
        self.assertEqual(p.chamadas, [])

    def test_mescla_com_copia_antes_e_export_igual(self):
        p, h = self.preparar()
        antes = _export(p)
        equipe_antes = [linha[:6] + linha[8:10] for linha in p.abas["indicações"][1:3]]
        self.assertEqual(_aplicar(p, h), 0)
        self.assertEqual(p.chamadas[0][0], "copia")  # a cópia vem antes de qualquer escrita
        self.assertIn("indicações (backup ", p.chamadas[0][1])
        self.assertEqual([c[0] for c in p.chamadas[1:]], ["cabecalho", "valores", "apaga"])
        aba = p.abas["indicações"]
        self.assertEqual([linha[3] for linha in aba[1:]], ["26/2025", "30/2025", "1/2025", "1/2025"])
        self.assertEqual([linha[:6] + linha[8:10] for linha in aba[1:3]], equipe_antes)  # equipe intacta
        self.assertEqual(aba[0][-1], "Ementa (Câmara)")
        self.assertEqual(_export(p), antes)  # o site sai igual
        self.assertEqual(len(p.abas), 2)

    def test_linha_que_mudou_no_meio_nao_e_apagada(self):
        p, h = self.preparar()

        def equipe_mexe(planilha):  # durante a gravação, alguém anota na linha do robô
            planilha.abas["indicações"][3][8] = "anotação"
        p.ao_gravar = equipe_mexe
        self.assertEqual(_aplicar(p, h), 2)
        self.assertNotIn("apaga", [c[0] for c in p.chamadas])
        self.assertEqual(len(p.abas["indicações"]), 6)

    def test_comentario_aberto_nao_faz_nada(self):
        p, h = self.preparar()
        self.assertEqual(_aplicar(p, h, _Drive([{"id": "c1"}])), 1)
        self.assertEqual(p.chamadas, [])


if __name__ == "__main__":
    unittest.main()
