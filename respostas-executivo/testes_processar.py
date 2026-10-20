#!/usr/bin/env python3
"""`processar_item` e o roteamento por tipo, sem rede: Drive, Câmara e o leitor de PDF
são substituídos por falsos (não depende de pypdf).

Casos que geravam "respondido" falso até out/2026: o PDF já arquivado não baixava e
virava INDETERMINADO (que conta como mérito); a moção caía na linha do requerimento.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classificar as cls  # noqa: E402
import index  # noqa: E402
import planilha  # noqa: E402
from index import (ABA_INDICACOES, ABA_REQUERIMENTOS, COL_DATA_MERITO, COL_SITUACAO,  # noqa: E402
                   aba_do_item, baixar_pdf_bytes, processar_item)

MERITO = b"%PDF-1.7 merito"
PRORROGA = b"%PDF-1.7 prorrogacao"
TEXTO = {MERITO: "mérito", PRORROGA: "prorrogação"}
CLASSE = {"mérito": cls.MERITO, "prorrogação": cls.PRORROGACAO}


def _item(*pdfs):
    return {"tipo": "Requerimento", "numero": "852/2025", "cod": "1", "ementa": "Pedido",
            "dataPropositura": "13/03/2025", "dataResposta": "24/04/2025", "pedidoPdf": None,
            "respostasPdf": [{"url": f"https://camara/{n}.pdf", "nome": f"{n}.pdf", "data": d}
                             for n, d in pdfs]}


class _Base(unittest.TestCase):
    """Drive com os arquivos de `arquivados` (nome → id); `camara` e `drive` dizem o que
    cada download devolve (None = falhou)."""

    def preparar(self, arquivados=(), camara=None, drive=None, pasta=None):
        camara, drive = camara or {}, drive or {}
        arquivos = [{"name": n, "id": i, "webViewLink": f"https://drive/{i}"} for n, i in arquivados]
        self.subidos, self.ordem = [], []
        patches = [
            mock.patch.object(index, "obter_ou_criar_subpasta", return_value=pasta or {"id": "PASTA"}),
            mock.patch.object(index, "marcar_aviso", side_effect=self._marcar),
            mock.patch.object(index, "listar_arquivos_pasta", return_value=arquivos),
            mock.patch.object(index, "limpar_duplicatas", side_effect=lambda d, a: a),
            mock.patch.object(index, "baixar_pdf_bytes", side_effect=lambda url: camara.get(url)),
            mock.patch.object(index, "baixar_drive", side_effect=lambda d, fid: drive.get(fid)),
            mock.patch.object(index, "subir_pdf", side_effect=self._subir),
            mock.patch.object(cls, "texto_pdf", side_effect=lambda dados: TEXTO[dados]),
            mock.patch.object(cls, "classificar", side_effect=lambda t: CLASSE[t]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _subir(self, drive, pasta, nome, dados, existentes):
        self.subidos.append(nome)
        self.ordem.append(("sobe", nome))
        return f"https://drive/novo/{nome}"

    def _marcar(self, drive, pasta_id, estado):
        self.ordem.append(("marca", pasta_id, estado))


class TestRespondidoFalso(_Base):
    ARQ = "RESPOSTA_1_852-2025_a.pdf"

    def test_download_falho_usa_a_copia_do_drive(self):
        self.preparar(arquivados=[(self.ARQ, "id1")], camara={}, drive={"id1": MERITO})
        r = processar_item(
            _item(("a", "24/04/2025")), object(), "RAIZ", False, ";", classificar_tudo=True)
        self.assertEqual(r.aba, ABA_REQUERIMENTOS)
        self.assertEqual(r.valores[COL_SITUACAO], cls.RESPONDIDO)
        self.assertEqual(r.valores[COL_DATA_MERITO], "24/04/2025")
        self.assertFalse(r.resposta_nova)
        self.assertFalse(r.sem_pdf)
        self.assertEqual(self.ordem, [])  # nada subiu: a pasta não é marcada

    def test_sem_camara_e_sem_drive_nao_grava_situacao(self):
        # antes: INDETERMINADO → "respondido" falso e permanente
        self.preparar(arquivados=[(self.ARQ, "id1")], camara={}, drive={})
        r = processar_item(
            _item(("a", "24/04/2025")), object(), "RAIZ", False, ";", classificar_tudo=True)
        self.assertNotIn(COL_SITUACAO, r.valores)
        self.assertNotIn(COL_DATA_MERITO, r.valores)
        self.assertFalse(r.sem_pdf)  # o PDF está arquivado; só não deu para ler agora

    def test_um_pdf_ilegivel_impede_veredito_parcial(self):
        # prorrogação nova lida + mérito arquivado ilegível: gravar "só prorrogação"
        # rebaixaria um item respondido — fica sem veredito nesta passada
        self.preparar(arquivados=[(self.ARQ, "id1")],
                      camara={"https://camara/b.pdf": PRORROGA}, drive={})
        r = processar_item(
            _item(("a", "24/04/2025"), ("b", "01/05/2025")), object(), "RAIZ", False, ";", True)
        self.assertNotIn(COL_SITUACAO, r.valores)
        self.assertTrue(r.resposta_nova)

    def test_sem_nenhum_pdf_de_resposta_arquivado(self):
        self.preparar(arquivados=[], camara={}, drive={})
        r = processar_item(
            _item(("a", "24/04/2025")), object(), "RAIZ", False, ";", True)
        self.assertTrue(r.sem_pdf)
        self.assertFalse(r.resposta_nova)
        self.assertNotIn(COL_SITUACAO, r.valores)
        self.assertEqual(self.subidos, [])

    def test_resposta_nova_e_classificada(self):
        self.preparar(arquivados=[], camara={"https://camara/a.pdf": MERITO})
        r = processar_item(
            _item(("a", "24/04/2025")), object(), "RAIZ", False, ";", True)
        self.assertEqual((r.valores[COL_SITUACAO], r.resposta_nova, r.sem_pdf), (cls.RESPONDIDO, True, False))
        self.assertEqual(self.subidos, ["RESPOSTA_1_852-2025_a.pdf"])
        # a pasta é marcada ANTES de subir: se a execução cair no meio, a próxima avisa
        self.assertEqual(self.ordem, [("marca", "PASTA", index.AVISO_PENDENTE),
                                      ("sobe", "RESPOSTA_1_852-2025_a.pdf")])
        self.assertTrue(r.aviso_pendente)

    def test_marca_de_execucao_anterior_e_lida_e_nao_regravada(self):
        self.preparar(arquivados=[(self.ARQ, "id1")], camara={"https://camara/a.pdf": MERITO,
                                                              "https://camara/b.pdf": MERITO},
                      pasta={"id": "PASTA", "appProperties": {index.AVISO: index.AVISO_PENDENTE}})
        r = processar_item(_item(("a", "24/04/2025"), ("b", "01/05/2025")), object(), "RAIZ", False, ";", True)
        self.assertTrue(r.aviso_pendente)
        self.assertEqual(self.ordem, [("sobe", "RESPOSTA_2_852-2025_b.pdf")])


class _DriveFalso:
    """files().list devolve a subpasta (consulta por pasta) ou os arquivos dela. Não tem
    create/update/delete: na simulação, a trava de somente leitura barra antes."""

    def __init__(self, pasta, arquivos):
        self.pasta, self.arquivos = pasta, arquivos

    def files(self):
        return self

    def list(self, q, **kw):
        if "mimeType = 'application/vnd.google-apps.folder'" in q:
            return _Exec({"files": [self.pasta] if self.pasta else []})
        return _Exec({"files": self.arquivos})


class _Exec:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r


class TestSimulacao(unittest.TestCase):
    """--planejar: lê Drive e Câmara de verdade, sob a trava de somente leitura."""

    def setUp(self):
        for p in (mock.patch.object(index, "baixar_pdf_bytes", return_value=MERITO),
                  mock.patch.object(cls, "texto_pdf", side_effect=lambda dados: TEXTO[dados]),
                  mock.patch.object(cls, "classificar", side_effect=lambda t: CLASSE[t])):
            p.start()
            self.addCleanup(p.stop)

    def test_pasta_existente_resposta_que_subiria(self):
        repetido = {"name": "RESPOSTA_1_852-2025_a.pdf", "id": "x", "webViewLink": "https://drive/x"}
        drive = planilha.somente_leitura(_DriveFalso(
            {"id": "PASTA_EXISTENTE"}, [repetido, dict(repetido, id="y")]))  # cópia repetida: não apaga
        r = processar_item(_item(("a", "24/04/2025"), ("b", "01/05/2025")), drive, "RAIZ", False, ";",
                           True, simular=True)
        self.assertTrue(r.resposta_nova)        # "b" subiria agora
        self.assertFalse(r.aviso_pendente)      # e a pasta não foi marcada
        self.assertEqual(r.pasta_id, "PASTA_EXISTENTE")
        self.assertEqual(r.valores[COL_SITUACAO], cls.RESPONDIDO)

    def test_pasta_que_ainda_nao_existe_nao_e_criada(self):
        drive = planilha.somente_leitura(_DriveFalso(None, []))
        r = processar_item(_item(("a", "24/04/2025")), drive, "RAIZ", False, ";", True, simular=True)
        self.assertIsNone(r.pasta_id)
        self.assertTrue(r.resposta_nova)
        self.assertFalse(r.sem_pdf)

    def test_sem_simular_a_trava_barra_a_criacao(self):
        # a mesma chamada fora da simulação tenta criar a pasta — e a trava pega
        drive = planilha.somente_leitura(_DriveFalso(None, []))
        with self.assertRaises(planilha.EscritaBloqueada):
            processar_item(_item(("a", "24/04/2025")), drive, "RAIZ", False, ";", True)


class TestPdfValido(unittest.TestCase):
    def test_pagina_html_nao_e_pdf(self):
        class _Resp:
            def __init__(self, c):
                self.content = c
        with mock.patch.object(index, "_http_get", return_value=_Resp(b"<html>erro</html>")):
            self.assertIsNone(baixar_pdf_bytes("https://camara/x.pdf"))
        with mock.patch.object(index, "_http_get", return_value=_Resp(b"%PDF-1.4 ...")):
            self.assertEqual(baixar_pdf_bytes("https://camara/x.pdf"), b"%PDF-1.4 ...")


class TestRoteamento(unittest.TestCase):
    def test_so_requerimento_e_indicacao_vao_as_abas(self):
        self.assertEqual(aba_do_item("Requerimento"), ABA_REQUERIMENTOS)
        self.assertEqual(aba_do_item("Indicação"), ABA_INDICACOES)
        for fora in ("Moção", "Requerimento de Convite", "Requerimento de Homenagem", ""):
            self.assertIsNone(aba_do_item(fora), fora)


if __name__ == "__main__":
    unittest.main()
