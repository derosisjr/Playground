#!/usr/bin/env python3
"""Auditoria dos "respondido" (R1c) e backfill do reclassificar.py, sem rede: Drive, Câmara
e leitor de PDF falsos; planilha falsa em memória que aplica as gravações.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classificar as cls  # noqa: E402
import index  # noqa: E402
import reclassificar as rc  # noqa: E402
from index import COL_DATA_MERITO, COL_SITUACAO, Processado  # noqa: E402

CAB = ["Assunto", "Secretaria", "Data da Sessão", "Nùmero", "Resposta", "Data da resposta",
       "Status atual", "Situação", "observação", COL_SITUACAO, COL_DATA_MERITO]
CAB_IND = ["sta", "Assunto", "Data da Sessão", "Número", "Resposta", "Data da resposta",
           "Bairro", COL_SITUACAO, COL_DATA_MERITO]


def _link(pasta):
    return ("Resposta", f'=HYPERLINK("https://drive.google.com/drive/folders/{pasta}";"Resposta")')


def _req(numero, pasta, data, sit, merito, status="cobrar"):
    return ["assunto", "SMS", "01/02/2026", numero, _link(pasta) if pasta else "", data,
            status, "manual", "obs", sit, merito]


class _Planilha:
    """Grade por aba; célula = texto ou (exibido, fórmula). Aplica values.batchUpdate."""

    def __init__(self, req, ind=None):
        self.abas = {"requerimentos": [CAB] + req, "indicações": [CAB_IND] + (ind or [])}
        self.lotes = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range, valueRenderOption="FORMATTED_VALUE", **kw):
        i = 1 if valueRenderOption == "FORMULA" else 0
        grade = self.abas[range.strip("'")]
        return _Exec({"values": [[c[i] if isinstance(c, tuple) else c for c in l] for l in grade]})

    def batchUpdate(self, spreadsheetId, body):
        self.lotes.append(body)
        for d in body["data"]:
            aba, col, lin = re.fullmatch(r"'(.+)'!([A-Z]+)(\d+)", d["range"]).groups()
            linha = self.abas[aba][int(lin) - 1]
            c = ord(col) - 65
            linha.extend([""] * (c + 1 - len(linha)))
            linha[c] = d["values"][0][0]
        return _Exec({})

    def celula(self, aba, numero, coluna):
        cab = self.abas[aba][0]
        i_num = cab.index("Nùmero" if aba == "requerimentos" else "Número")
        for linha in self.abas[aba][1:]:
            if linha[i_num] == numero:
                v = linha[cab.index(coluna)]
                return v[1] if isinstance(v, tuple) else v
        raise KeyError(numero)


class _Exec:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


PRORROGA, MERITO = b"%PDF prorrogacao", b"%PDF merito"
TEXTO = {PRORROGA: "prorrogação", MERITO: "mérito"}
CLASSE = {"prorrogação": cls.PRORROGACAO, "mérito": cls.MERITO}


class _Base(unittest.TestCase):
    """`pastas` = {id: [(nome, conteúdo)]}: o Drive falso de listar_arquivos_pasta/baixar."""

    def preparar(self, pastas):
        arquivos = {pid: [{"name": n, "id": f"{pid}/{n}", "size": "1000", "createdTime": str(i)}
                          for i, (n, _) in enumerate(lista)] for pid, lista in pastas.items()}
        conteudo = {f"{pid}/{n}": dados for pid, lista in pastas.items() for n, dados in lista}
        for p in (mock.patch.object(rc, "listar_arquivos_pasta", side_effect=lambda d, pid: arquivos[pid]),
                  mock.patch.object(rc, "baixar", side_effect=lambda d, fid: conteudo[fid]),
                  mock.patch.object(cls, "texto_pdf", side_effect=lambda dados: TEXTO[dados]),
                  mock.patch.object(cls, "classificar", side_effect=lambda t: CLASSE[t])):
            p.start()
            self.addCleanup(p.stop)

    def comparar(self, planilha):
        with contextlib.redirect_stderr(io.StringIO()):
            return rc.comparar(object(), planilha, "S", "RAIZ", {})


class TestComparar(_Base):
    def test_respondido_que_e_so_prorrogacao_vira_correcao_e_limpa_o_merito(self):
        self.preparar({"PASTA_AAAAAAAA": [("RESPOSTA_1_7-2025_a.pdf", PRORROGA)],
                       "PASTA_BBBBBBBB": [("RESPOSTA_1_8-2025_b.pdf", MERITO)]})
        p = _Planilha([_req("7/2025", "PASTA_AAAAAAAA", "10/03/2025", cls.RESPONDIDO, "10/03/2025"),
                       _req("8/2025", "PASTA_BBBBBBBB", "11/03/2025", cls.RESPONDIDO, "11/03/2025"),
                       _req("9/2025", "PASTA_AAAAAAAA", "12/03/2025", cls.SO_PRORROGACAO, "")])
        correcoes, cont = self.comparar(p)
        self.assertEqual([(c["numero"], c["depois"], c["limpar"]) for c in correcoes],
                         [("7/2025", {COL_SITUACAO: cls.SO_PRORROGACAO}, [COL_DATA_MERITO])])
        self.assertEqual(cont["requerimentos: respondidos revistos"], 2)  # o 9/2025 não é revisto

    def test_pasta_com_dois_pedidos_vai_pela_pagina_da_camara(self):
        # Requerimento 19/2026 com as datas da Moção 19/2026 (que caiu na mesma pasta)
        self.preparar({"PASTA_19XXXXXX": [("PEDIDO_19-2026_mocao.pdf", b""), ("PEDIDO_19-2026_req.pdf", b"")]})
        p = _Planilha([_req("19/2026", "PASTA_19XXXXXX", "03/06/2026", cls.RESPONDIDO, "03/06/2026")])
        listagem = [{"numero": "19/2026", "subtipo": "Requerimento", "cod": "273917"},
                    {"numero": "19/2026", "subtipo": "Requerimento de Convite", "cod": "1"}]
        valores = {"Data da resposta": "25/02/2026", COL_SITUACAO: cls.RESPONDIDO,
                   COL_DATA_MERITO: "25/02/2026", "Assunto": "x"}
        with mock.patch("camara.listar_autor", return_value=listagem), \
                mock.patch.object(index, "detalhar_item", return_value={"cod": "273917"}) as det, \
                mock.patch.object(index, "processar_item",
                                  return_value=Processado("requerimentos", valores, "", False, False)) as proc:
            correcoes, _ = self.comparar(p)
        det.assert_called_once_with("273917")
        self.assertTrue(proc.call_args.kwargs["simular"])  # só leitura
        self.assertEqual(correcoes[0]["depois"], {"Data da resposta": "25/02/2026",
                                                  COL_DATA_MERITO: "25/02/2026"})
        self.assertEqual(correcoes[0]["limpar"], [])


class TestAplicar(_Base):
    def plano(self, planilha):
        self.preparar({"PASTA_AAAAAAAA": [("RESPOSTA_1_7-2025_a.pdf", PRORROGA)]})
        correcoes, _ = self.comparar(planilha)
        caminho = os.path.join(tempfile.mkdtemp(), "plano.json")
        h = rc._hash(correcoes)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"sheet_id": "S", "hash": h, "correcoes": correcoes}, f)
        return caminho, h

    def aplicar(self, planilha, caminho, h):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return rc.aplicar_divergentes(planilha, "S", caminho, h)

    def test_hash_errado_nao_grava(self):
        p = _Planilha([_req("7/2025", "PASTA_AAAAAAAA", "10/03/2025", cls.RESPONDIDO, "10/03/2025")])
        caminho, _ = self.plano(p)
        self.assertEqual(self.aplicar(p, caminho, "0000"), 1)
        self.assertEqual(p.lotes, [])

    def test_grava_so_as_colunas_do_robo_e_so_o_que_nao_mudou(self):
        p = _Planilha([_req("7/2025", "PASTA_AAAAAAAA", "10/03/2025", cls.RESPONDIDO, "10/03/2025"),
                       _req("6/2025", "PASTA_AAAAAAAA", "09/03/2025", cls.RESPONDIDO, "09/03/2025")])
        caminho, h = self.plano(p)
        # depois da simulação, alguém mexeu no 6/2025: ele fica como está
        p.abas["requerimentos"][2][CAB.index(COL_DATA_MERITO)] = "15/03/2025"
        self.assertEqual(self.aplicar(p, caminho, h), 0)
        self.assertEqual(p.celula("requerimentos", "7/2025", COL_SITUACAO), cls.SO_PRORROGACAO)
        self.assertEqual(p.celula("requerimentos", "7/2025", COL_DATA_MERITO), "")
        self.assertEqual(p.celula("requerimentos", "6/2025", COL_SITUACAO), cls.RESPONDIDO)
        for coluna, valor in (("Status atual", "cobrar"), ("Situação", "manual"), ("observação", "obs")):
            self.assertEqual(p.celula("requerimentos", "7/2025", coluna), valor)
        gravadas = {d["range"] for lote in p.lotes for d in lote["data"]}
        self.assertEqual(gravadas, {"'requerimentos'!J2", "'requerimentos'!K2"})

    def test_plano_de_outra_planilha_nao_grava(self):
        p = _Planilha([_req("7/2025", "PASTA_AAAAAAAA", "10/03/2025", cls.RESPONDIDO, "10/03/2025")])
        caminho, h = self.plano(p)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rc.aplicar_divergentes(p, "OUTRA", caminho, h), 1)
        self.assertEqual(p.lotes, [])


class TestBackfill(_Base):
    def test_so_preenche_celula_vazia(self):
        self.preparar({"PASTA_AAAAAAAA": [("RESPOSTA_1_7-2025_a.pdf", MERITO)],
                       "PASTA_BBBBBBBB": [("RESPOSTA_1_8-2025_b.pdf", MERITO)]})
        p = _Planilha([_req("7/2025", "PASTA_AAAAAAAA", "10/03/2025", "", ""),
                       _req("8/2025", "PASTA_BBBBBBBB", "11/03/2025", cls.SO_PRORROGACAO, "")])
        pastas = [{"name": "REQUERIMENTO_7-2025", "id": "PASTA_AAAAAAAA"},
                  {"name": "REQUERIMENTO_8-2025", "id": "PASTA_BBBBBBBB"}]
        with mock.patch.object(rc, "_google_services", return_value=(object(), p)), \
                mock.patch.object(rc, "listar_subpastas", return_value=pastas), \
                mock.patch.object(rc, "garantir_colunas"), \
                mock.patch.object(rc, "carregar_cache", return_value={}), \
                mock.patch.object(rc, "salvar_cache"), \
                mock.patch.dict(os.environ, {"SHEET_ID": "S", "DRIVE_FOLDER_ID": "RAIZ"}), \
                mock.patch.object(sys, "argv", ["reclassificar.py"]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rc.main(), 0)
        self.assertEqual(p.celula("requerimentos", "7/2025", COL_SITUACAO), cls.RESPONDIDO)
        # antes o backfill regravava tudo; agora a divergência fica (e vai para o --comparar)
        self.assertEqual(p.celula("requerimentos", "8/2025", COL_SITUACAO), cls.SO_PRORROGACAO)


if __name__ == "__main__":
    unittest.main()
