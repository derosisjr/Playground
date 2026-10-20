#!/usr/bin/env python3
"""O laço do robô (`index.main`) de ponta a ponta, sem rede: Câmara, Drive e PDFs falsos e
uma planilha falsa em memória que aplica as gravações.

Cobre o que o R3 promete: grava no pedido certo mesmo com linha inserida no meio, não
sobrescreve o que a equipe escreveu, avisa só mudança real (ou aviso pendente), tira a marca
de aviso só depois do log e do e-mail, `--planejar` não grava nada e os códigos de saída.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classificar as cls  # noqa: E402
import index  # noqa: E402
from index import COL_DATA_MERITO, COL_SITUACAO, Processado  # noqa: E402

CAB_IND = ["sta", "Assunto", "Data da Sessão", "Número", "Data do Protocolo na PMS", "Prazo",
           "Resposta", "Data da resposta", "A contento", "Bairro", COL_SITUACAO, COL_DATA_MERITO]
CAB_REQ = ["Ordem", "Assunto", "Secretaria", "Data da Sessão", "Nùmero", "Data do Protocolo na PMS",
           "Prazo", "Resposta", "Data da resposta", "Status atual", COL_SITUACAO, COL_DATA_MERITO]
N_LINHAS = 110  # carregar_planilha recusa aba com menos de 100


def _link(pasta):
    return f'=HYPERLINK("https://drive.google.com/drive/folders/{pasta}";"Resposta")'


class _Planilha:
    """Grade por aba; célula = texto ou (exibido, fórmula). Aplica values.batchUpdate."""

    def __init__(self):
        self.abas = {
            "indicações": [CAB_IND] + [["ok", f"assunto {i}", "01/03/2025", f"{i}/2025", "", "",
                                        "", "", "sim", "Centro", "", ""] for i in range(1, N_LINHAS)],
            "requerimentos": [CAB_REQ] + [[str(i), f"assunto {i}", "Saúde", "01/03/2025", f"{i}/2025",
                                           "", "", "", "", "cobrar", "", ""] for i in range(1, N_LINHAS)],
        }
        self.gravacoes = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range=None, valueRenderOption="FORMATTED_VALUE", fields=None):
        if fields:
            return _Exec({"properties": {"locale": "pt_BR"}})
        i = 1 if valueRenderOption == "FORMULA" else 0
        grade = self.abas[range.strip("'")]
        return _Exec({"values": [[c[i] if isinstance(c, tuple) else c for c in linha] for linha in grade]})

    def batchUpdate(self, spreadsheetId, body):
        self.gravacoes.append(body)
        for d in body["data"]:
            aba, celula = re.fullmatch(r"'(.+)'!([A-Z]+\d+)", d["range"]).groups()
            col, lin = re.fullmatch(r"([A-Z]+)(\d+)", celula).groups()
            c, n = ord(col) - 65, int(lin)
            grade = self.abas[aba]
            while len(grade) < n:
                grade.append([])
            linha = grade[n - 1]
            linha.extend([""] * (c + 1 - len(linha)))
            v = d["values"][0][0]
            linha[c] = ("Resposta", v) if str(v).startswith("=HYPERLINK") else v
        return _Exec({})

    def celula(self, aba, numero, coluna):
        grade = self.abas[aba]
        i_num, i_col = grade[0].index("Número" if aba == "indicações" else "Nùmero"), grade[0].index(coluna)
        for linha in grade[1:]:
            if len(linha) > i_num and linha[i_num] == numero:
                v = linha[i_col] if i_col < len(linha) else ""
                return v[1] if isinstance(v, tuple) else v
        raise KeyError(numero)


class _Exec:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


def _det(cod, tipo, numero):
    return {"cod": cod, "tipo": tipo, "numero": numero, "processo": "", "ementa": f"Ementa {numero}",
            "dataPropositura": "01/03/2025", "dataResposta": "10/10/2026", "autor": "", "detalhesUrl": "",
            "pedidoPdf": None, "respostasPdf": [{}]}


def _proc(aba, numero, pasta="PASTA_AAAAAAAA", sit=cls.RESPONDIDO, nova=False, pendente=False,
          data="10/10/2026", merito="10/10/2026"):
    col_num = "Número" if aba == "indicações" else "Nùmero"
    valores = {"Assunto": f"Ementa {numero}", "Data da Sessão": "01/03/2025", col_num: numero,
               "Resposta": _link(pasta), "Data da resposta": data, COL_SITUACAO: sit, COL_DATA_MERITO: merito}
    return Processado(aba, valores, f"https://drive.google.com/drive/folders/{pasta}", nova, False,
                      pasta, pendente or nova)


class _Base(unittest.TestCase):
    def rodar(self, itens, *args, antes=None, ao_processar=None, email_falha=False, log_falha=False,
              pre=(), ambiente=None):
        """`itens` = [(detalhes, Processado | Exception)]; `antes(planilha)` mexe na planilha antes
        da leitura inicial, `ao_processar(planilha)` durante a varredura. Devolve o código de saída."""
        self.planilha = _Planilha()
        if antes:
            antes(self.planilha)
        self.log, self.emails, self.marcas, self.simular = [], [], [], []
        por_cod = {d["cod"]: (d, p) for d, p in itens}

        def detalhar(cod):
            d, p = por_cod[cod]
            if isinstance(p, Exception):
                raise p
            return dict(d)

        def processar(det, drive, raiz, dry, sep, tudo, simular=False):
            self.simular.append(simular)
            if ao_processar:
                ao_processar(self.planilha)
            return por_cod[det["cod"]][1]

        def registrar(sheets, sid, entradas):
            if log_falha:
                raise ConnectionError("sem rede")
            self.log.extend(entradas)

        def enviar(entradas, data, novos=()):
            if email_falha:
                raise ConnectionError("smtp")
            self.emails.append(len(entradas))
            self.novos_email = list(novos)

        resumo = tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8")
        resumo.close()
        self.addCleanup(os.unlink, resumo.name)
        patches = [
            mock.patch.object(sys, "argv", ["index.py", "--ano", "2026", "--email", *args]),
            mock.patch.dict(os.environ, {"SHEET_ID": "S", "DRIVE_FOLDER_ID": "D",
                                         "GITHUB_STEP_SUMMARY": resumo.name,
                                         "PRECADASTRO_ATIVO": "", **(ambiente or {})}),
            # a listagem da Câmara do pré-cadastro: `pre` = pedidos do autor (nunca a rede)
            mock.patch.object(index.precadastro, "coletar", return_value=(list(pre), [])),
            mock.patch.object(index, "_google_services", return_value=(object(), self.planilha)),
            mock.patch.object(index, "coletar_cods", return_value=[
                {"cod": d["cod"], "recebimentoBusca": ""} for d, _ in itens]),
            mock.patch.object(index, "detalhar_item", side_effect=detalhar),
            mock.patch.object(index, "processar_item", side_effect=processar),
            mock.patch.object(index, "garantir_colunas"),
            mock.patch.object(index, "registrar_log", side_effect=registrar),
            mock.patch.object(index, "enviar_email", side_effect=enviar),
            mock.patch.object(index, "marcar_aviso",
                              side_effect=lambda drive, pasta, estado: self.marcas.append((pasta, estado))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            codigo = index.main()
        self.saida = err.getvalue()
        with open(resumo.name, encoding="utf-8") as f:
            self.resumo = f.read()
        return codigo


class TestGravacao(_Base):
    def test_resposta_nova_atualiza_avisa_e_tira_a_marca(self):
        def preparar(p):  # linha já respondida: prorrogação de 01/09
            for aba, num, col, val in (("indicações", "5/2025", "Resposta", ("Resposta", _link("PASTA_AAAAAAAA"))),
                                       ("indicações", "5/2025", "Data da resposta", "01/09/2026"),
                                       ("indicações", "5/2025", COL_SITUACAO, cls.SO_PRORROGACAO)):
                linha = p.abas[aba][5]
                linha[p.abas[aba][0].index(col)] = val
        codigo = self.rodar([(_det("1", "Indicação", "5/2025"), _proc("indicações", "5/2025", nova=True))],
                            antes=preparar)
        self.assertEqual(codigo, 0)
        self.assertEqual(self.planilha.celula("indicações", "5/2025", COL_SITUACAO), cls.RESPONDIDO)
        self.assertEqual(self.planilha.celula("indicações", "5/2025", "Data da resposta"), "10/10/2026")
        self.assertEqual([e["Número"] for e in self.log], ["5/2025"])
        self.assertEqual(self.emails, [1])
        self.assertEqual(self.marcas, [("PASTA_AAAAAAAA", index.AVISO_FEITO)])

    def test_sem_novidade_so_preenche_celula_vazia_em_silencio(self):
        def preparar(p):  # já respondido; a equipe acertou a data à mão; situação vazia
            linha = p.abas["requerimentos"][7]
            cab = p.abas["requerimentos"][0]
            linha[cab.index("Resposta")] = ("Resposta", _link("PASTA_AAAAAAAA"))
            linha[cab.index("Data da resposta")] = "02/10/2026"
        codigo = self.rodar([(_det("1", "Requerimento", "7/2025"), _proc("requerimentos", "7/2025"))],
                            antes=preparar)
        self.assertEqual(codigo, 0)
        self.assertEqual(self.planilha.celula("requerimentos", "7/2025", COL_SITUACAO), cls.RESPONDIDO)
        self.assertEqual(self.planilha.celula("requerimentos", "7/2025", "Data da resposta"), "02/10/2026")
        self.assertEqual(self.planilha.celula("requerimentos", "7/2025", "Status atual"), "cobrar")
        self.assertEqual((self.log, self.emails, self.marcas), ([], [], []))
        self.assertIn("Divergências", self.saida)

    def test_pedido_novo_vira_linha_no_fim_e_avisa(self):
        codigo = self.rodar([(_det("1", "Indicação", "0845/2026"),
                              _proc("indicações", "0845/2026", nova=True))])
        self.assertEqual(codigo, 0)
        ultima = self.planilha.abas["indicações"][-1]
        self.assertEqual(len(self.planilha.abas["indicações"]), N_LINHAS + 1)
        self.assertEqual(ultima[CAB_IND.index("Número")], "845/2026")  # forma canônica
        self.assertEqual(ultima[CAB_IND.index("sta")], "")             # coluna da equipe intocada
        self.assertEqual(len(self.log), 1)

    def test_linha_inserida_durante_a_varredura(self):
        def inserir(p):  # a equipe insere uma linha no topo depois da leitura inicial
            p.abas["indicações"].insert(1, ["", "nova da equipe", "", "999/2026"] + [""] * 8)
        self.rodar([(_det("1", "Indicação", "9/2025"), _proc("indicações", "9/2025", nova=True))],
                   ao_processar=inserir)
        self.assertEqual(self.planilha.celula("indicações", "9/2025", COL_SITUACAO), cls.RESPONDIDO)
        self.assertEqual(self.planilha.celula("indicações", "999/2026", COL_SITUACAO), "")

    def test_marca_pendente_sem_mudanca_ainda_avisa(self):
        # a execução anterior gravou a planilha e caiu antes do e-mail
        def preparar(p):
            linha, cab = p.abas["indicações"][3], p.abas["indicações"][0]
            for col, val in (("Resposta", ("Resposta", _link("PASTA_AAAAAAAA"))), ("Data da resposta", "10/10/2026"),
                             (COL_SITUACAO, cls.RESPONDIDO), (COL_DATA_MERITO, "10/10/2026")):
                linha[cab.index(col)] = val
        self.rodar([(_det("1", "Indicação", "3/2025"), _proc("indicações", "3/2025", pendente=True))],
                   antes=preparar)
        self.assertEqual(self.planilha.gravacoes, [])
        self.assertEqual(len(self.log), 1)
        self.assertEqual(self.marcas, [("PASTA_AAAAAAAA", index.AVISO_FEITO)])

    def test_reaviso_sem_reclassificar_mostra_a_situacao_da_planilha(self):
        def preparar(p):
            linha, cab = p.abas["indicações"][3], p.abas["indicações"][0]
            linha[cab.index("Resposta")] = ("Resposta", _link("PASTA_AAAAAAAA"))
            linha[cab.index(COL_SITUACAO)] = cls.RESPONDIDO
        proc = _proc("indicações", "3/2025", pendente=True)
        proc.valores.pop(COL_SITUACAO)  # já respondido: nesta passada não reclassifica
        self.rodar([(_det("1", "Indicação", "3/2025"), proc)], antes=preparar)
        self.assertEqual(self.log[0]["Situação"], cls.ROTULOS[cls.RESPONDIDO])


def _pedido(aba, numero, situacao="Encaminhado"):
    return {"aba": aba, "numero": numero, "situacao": situacao, "data": "15/10/2026",
            "ementa": f"Indica ao Executivo o pedido {numero}.", "subtipo": "Indicação", "tipo": "Indicação"}


class TestPreCadastro(_Base):
    def test_ligado_cria_a_linha_antes_da_busca_e_a_resposta_cai_nela(self):
        codigo = self.rodar([(_det("1", "Indicação", "900/2026"), _proc("indicações", "900/2026", nova=True))],
                            pre=[_pedido("indicações", "900/2026"), _pedido("indicações", "901/2026")],
                            ambiente={"PRECADASTRO_ATIVO": "true"})
        self.assertEqual(codigo, 0)
        aba = self.planilha.abas["indicações"]
        numeros = [linha[CAB_IND.index("Número")] for linha in aba[1:]]
        self.assertEqual(numeros.count("900/2026"), 1)  # uma linha só: a resposta achou a do pré-cadastro
        self.assertIn("901/2026", numeros)
        self.assertEqual(self.planilha.celula("indicações", "900/2026", COL_SITUACAO), cls.RESPONDIDO)
        self.assertEqual(sorted(e["Origem"] for e in self.log), ["pré-cadastro", "pré-cadastro", "resposta"])
        self.assertEqual([e["Número"] for e in self.novos_email], ["900/2026", "901/2026"])
        self.assertIn("| Pré-cadastro: linhas novas | 2 |", self.resumo)

    def test_desligado_so_conta(self):
        codigo = self.rodar([(_det("1", "Indicação", "4/2025"), _proc("indicações", "4/2025"))],
                            pre=[_pedido("indicações", "901/2026")])
        self.assertEqual(codigo, 0)
        numeros = [linha[CAB_IND.index("Número")] for linha in self.planilha.abas["indicações"][1:]]
        self.assertNotIn("901/2026", numeros)
        self.assertIn("| Pré-cadastro: linhas novas (desligado: só contado) | 1 |", self.resumo)

    def test_espelho_da_camara_e_acertado_em_linha_existente(self):
        # a coluna existe na aba: o robô acompanha a situação da listagem
        def preparar(p):
            for aba in p.abas.values():
                aba[0].append("Situação na Câmara")
                for linha in aba[1:]:
                    linha.append("-")
        self.rodar([(_det("1", "Indicação", "4/2025"), _proc("indicações", "4/2025"))],
                   pre=[_pedido("requerimentos", "7/2025", situacao="Aprovado")],
                   antes=preparar, ambiente={"PRECADASTRO_ATIVO": "true"})
        self.assertEqual(self.planilha.celula("requerimentos", "7/2025", "Situação na Câmara"), "Aprovado")
        self.assertEqual(self.planilha.celula("requerimentos", "8/2025", "Situação na Câmara"), "-")


class TestFalhaAVista(_Base):
    def test_busca_vazia_sai_1(self):
        self.assertEqual(self.rodar([]), 1)
        self.assertIn("Busca vazia", self.resumo)

    def test_item_com_erro_sai_2_e_os_outros_gravam(self):
        codigo = self.rodar([(_det("1", "Indicação", "2/2025"), RuntimeError("Câmara fora do ar")),
                             (_det("2", "Indicação", "4/2025"), _proc("indicações", "4/2025", nova=True))])
        self.assertEqual(codigo, 2)
        self.assertEqual(self.planilha.celula("indicações", "4/2025", COL_SITUACAO), cls.RESPONDIDO)
        self.assertIn("1 item(ns) com erro", self.resumo)

    def test_email_falho_mantem_a_marca_e_sai_2(self):
        codigo = self.rodar([(_det("1", "Indicação", "4/2025"), _proc("indicações", "4/2025", nova=True))],
                            email_falha=True)
        self.assertEqual(codigo, 2)
        self.assertEqual(self.marcas, [])  # fica "pendente": a próxima execução avisa

    def test_log_falho_mantem_a_marca_e_sai_2(self):
        codigo = self.rodar([(_det("1", "Indicação", "4/2025"), _proc("indicações", "4/2025", nova=True))],
                            log_falha=True)
        self.assertEqual(codigo, 2)
        self.assertEqual(self.marcas, [])

    def test_orcamento_esgotado_sai_2(self):
        codigo = self.rodar([(_det("1", "Indicação", "4/2025"), _proc("indicações", "4/2025", nova=True))],
                            "--orcamento-min", "0")
        self.assertEqual(codigo, 2)
        self.assertEqual(self.planilha.gravacoes, [])
        self.assertIn("Orçamento de 0 min esgotado", self.resumo)

    def test_resumo_so_tem_contagens(self):
        self.rodar([(_det("1", "Indicação", "4/2025"), _proc("indicações", "4/2025", nova=True))])
        self.assertNotIn("Ementa", self.resumo)
        self.assertIn("| Avisos (log e e-mail) | 1 |", self.resumo)


class TestPlanejar(_Base):
    def test_nao_grava_nem_avisa_e_conta(self):
        codigo = self.rodar([(_det("1", "Indicação", "4/2025"), _proc("indicações", "4/2025", nova=True)),
                             (_det("2", "Indicação", "0901/2026"), _proc("indicações", "0901/2026", nova=True))],
                            "--planejar")
        self.assertEqual(codigo, 0)
        self.assertEqual(self.simular, [True, True])
        self.assertEqual(self.planilha.gravacoes, [])
        self.assertEqual((self.log, self.emails, self.marcas), ([], [], []))
        self.assertIn("| Linhas novas | 1 |", self.resumo)
        self.assertIn("plano (nada gravado)", self.resumo)


if __name__ == "__main__":
    unittest.main()
