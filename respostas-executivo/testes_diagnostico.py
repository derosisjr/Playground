#!/usr/bin/env python3
"""Testes do diagnóstico somente leitura, do número canônico, da trava de escrita e do
parser da listagem da Câmara (sem rede: fixture e clientes falsos).

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import camara  # noqa: E402
from diagnostico import (analisar_aba, analisar_pastas, conciliar, dono_da_coluna,  # noqa: E402
                         mapa_colunas, pasta_id, picos_log)
from planilha import EscritaBloqueada, numero_canonico, somente_leitura  # noqa: E402


class TestNumeroCanonico(unittest.TestCase):
    def test_formas_reais(self):
        self.assertEqual(numero_canonico("0845/2026"), "845/2026")
        self.assertEqual(numero_canonico("7.562/2025"), "7562/2025")
        self.assertEqual(numero_canonico(" 12 / 2026 "), "12/2026")
        self.assertEqual(numero_canonico("5438/2026"), "5438/2026")

    def test_rejeita_o_que_nao_e_numero(self):
        for bruto in ("12/26", "27/11/2025", "", None, "SIM", "0/2026", "abc/2026"):
            self.assertIsNone(numero_canonico(bruto), bruto)


class _Req:
    def __init__(self, resultado):
        self.resultado = resultado

    def execute(self):
        return self.resultado


class _Values:
    def get(self, **kw):
        return _Req({"values": [["Número"], ["1/2026"]]})

    def update(self, **kw):  # pragma: no cover — a trava tem de impedir a chamada
        raise AssertionError("update chegou ao cliente")


class _Planilhas:
    def values(self):
        return _Values()

    def batchUpdate(self, **kw):  # pragma: no cover
        raise AssertionError("batchUpdate chegou ao cliente")


class _Sheets:
    def spreadsheets(self):
        return _Planilhas()


class TestSomenteLeitura(unittest.TestCase):
    def test_leitura_passa(self):
        s = somente_leitura(_Sheets())
        res = s.spreadsheets().values().get(spreadsheetId="x", range="a").execute()
        self.assertEqual(res["values"][1], ["1/2026"])

    def test_escrita_em_cadeia_e_bloqueada(self):
        s = somente_leitura(_Sheets())
        with self.assertRaises(EscritaBloqueada):
            s.spreadsheets().values().update(spreadsheetId="x", range="a", body={})
        with self.assertRaises(EscritaBloqueada):
            s.spreadsheets().batchUpdate(spreadsheetId="x", body={})
        with self.assertRaises(EscritaBloqueada):
            s.spreadsheets().values().append(spreadsheetId="x", range="a", body={})

    def test_nao_aceita_trocar_o_cliente(self):
        s = somente_leitura(_Sheets())
        with self.assertRaises(EscritaBloqueada):
            s.qualquer = 1


class TestListagemCamara(unittest.TestCase):
    def ler(self, nome):
        with open(os.path.join(AQUI, "fixtures", "camara", nome), "rb") as f:
            return camara.ler_listagem(f.read())

    def test_requerimentos(self):
        itens = self.ler("listagem-requerimentos.htm")
        self.assertEqual(len(itens), 3)
        i = itens[0]
        self.assertEqual((i["cod"], i["subtipo"], i["numero"], i["processo"], i["data"]),
                         ("293839", "Requerimento", "5438/2026", "15375/2026", "15/10/2026"))
        self.assertEqual(i["local"], "Sessão Ordinária")  # latin-1 lido certo
        self.assertTrue(i["ementa"].startswith("Oficiar ao Executivo"))

    def test_indicacoes(self):
        itens = self.ler("listagem-indicacoes.htm")
        self.assertEqual([i["numero"] for i in itens], ["7549/2026", "7548/2026", "7547/2026"])
        self.assertEqual({i["subtipo"] for i in itens}, {"Indicação"})
        self.assertEqual(itens[0]["situacao"], "Encaminhado")

    def test_subtipo_vai_com_o_numero(self):
        html = ("<table class='table-bordered'><thead><tr><th><strong>Requerimento de Convite - Nº 5/2026 "
                "[Processo Nº 77/2026]</strong></th></tr></thead><tbody><tr><th>Número:</th><td>5/2026</td></tr>"
                "</tbody></table><a href='detalhes.php?cod=9'>x</a>").encode("iso-8859-1")
        # o link fica fora da tabela: bloco sem link de detalhes é ignorado
        self.assertEqual(camara.ler_listagem(html), [])
        html = html.replace(b"</tbody></table><a href='detalhes.php?cod=9'>x</a>",
                            b"</tbody><tr><td><a href='detalhes.php?cod=9'>x</a></td></tr></table>")
        (i,) = camara.ler_listagem(html)
        self.assertEqual((i["subtipo"], i["numero"]), ("Requerimento de Convite", "5/2026"))


class TestDiagnostico(unittest.TestCase):
    CAB = ["sta", "Assunto", "Data da Sessão", "Número", "Resposta", "Data da resposta",
           "A contento", "Bairro", "Situação da resposta"]

    def test_dono_da_coluna(self):
        self.assertEqual(dono_da_coluna("Situação da resposta"), "robô")
        self.assertEqual(dono_da_coluna("Nùmero"), "robô na criação")
        self.assertEqual(dono_da_coluna("A contento"), "equipe")

    def test_mapa_inclui_coluna_sem_titulo_com_conteudo(self):
        valores = [["Número", "observação"], ["1/2026", "", "anotação à direita"], ["2/2026"]]
        colunas = mapa_colunas(valores)
        self.assertEqual([(c["coluna"], c["titulo"], c["dono"], c["preenchidas"]) for c in colunas],
                         [("A", "Número", "robô na criação", 2), ("B", "observação", "equipe", 0),
                          ("C", "(sem título)", "equipe (sem título)", 1)])

    def test_repetidas_limpas_e_com_conteudo_da_equipe(self):
        v = [self.CAB,
             ["", "resumo da equipe", "13/03/2025", "845/2026", "", "", "", "Gonzaga", ""],
             ["x", "outro", "", "900/2026", "", "", "pediu número", "", ""],
             # repetidas no fim (o robô anexou)
             ["", "ementa da Câmara", "13/03/2025", "0845/2026", "=HYPERLINK(...)", "01/04/2025", "", "", "respondido"],
             ["", "ementa", "", "900/2026", "", "", "outra anotação", "", ""]]
        r = analisar_aba(v, notas={(4, 2)})
        self.assertEqual(r["grupos_repetidos"], {2: 2})
        rep = r["repetidas"]
        self.assertEqual(rep["total"], 2)
        # linha 4 (845): sem conteúdo da equipe, mas com nota → não é limpa
        # linha 5 (900): "A contento" diferente da linha mantida → conflito
        self.assertEqual((rep["com_nota"], rep["com_conteudo_da_equipe_diferente"], rep["limpas"]), (1, 1, 0))
        det = {d["repetida"]: d for d in r["_detalhe"]["repetidas"]}
        self.assertEqual(det[5]["colunas_diferentes"], ["G"])
        self.assertTrue(det[4]["nota"])

    def test_fora_do_padrao(self):
        v = [["Número"], ["27/11/2025"], ["12/26"], ["5/2026"]]
        r = analisar_aba(v)
        self.assertEqual((r["fora_do_padrao"], r["numeros_validos"]), (2, 1))

    def test_pastas(self):
        self.assertEqual(pasta_id('=HYPERLINK("https://drive.google.com/drive/folders/1AbC_dEf-123456";"Ver")'),
                         "1AbC_dEf-123456")
        v = [["Número", "Resposta", "Situação da resposta"],
             ["1/2026", '=HYPERLINK("https://drive.google.com/drive/folders/PASTA_COM_PDF1";"x")', "respondido"],
             ["2/2026", '=HYPERLINK("https://drive.google.com/drive/folders/PASTA_VAZIA_22";"x")', ""],
             ["3/2026", "", ""]]
        r = analisar_pastas(v, {"PASTA_COM_PDF1"})
        self.assertEqual((r["com_pasta"], r["com_pasta_sem_situacao"], r["pasta_sem_pdf_de_resposta"]), (2, 1, 1))

    def test_picos_do_log(self):
        v = [["Data processamento", "Tipo"]] + [["11/10/2026 08:40", "Indicação"]] * 3 + [["12/10/2026", "Requerimento"]]
        r = picos_log(v)
        self.assertEqual(r["maiores_por_tipo"]["Indicação"][0], {"dia": "11/10/2026", "linhas": 3})
        self.assertEqual(r["maiores_por_tipo"]["Requerimento"][0], {"dia": "12/10/2026", "linhas": 1})

    def test_conciliacao(self):
        camara_itens = [
            {"numero": "10/2026", "subtipo": "Requerimento", "situacao": "Aprovado"},
            {"numero": "11/2026", "subtipo": "Requerimento", "situacao": "-"},
            {"numero": "5/2026", "subtipo": "Requerimento de Convite", "situacao": "Aprovado"},
        ]
        r = conciliar({"10/2026", "5/2026", "999/2025"}, camara_itens, "Requerimento")
        self.assertEqual((r["faltam_na_planilha"], r["na_planilha_de_outro_subtipo"],
                          r["na_planilha_nao_encontradas_no_autor"]), (1, 1, 1))
        self.assertEqual(r["situacao_na_camara_das_que_faltam"], {"-": 1})
        self.assertEqual(r["_detalhe"]["outro_subtipo"], {"5/2026": ["Requerimento de Convite"]})


if __name__ == "__main__":
    unittest.main()
