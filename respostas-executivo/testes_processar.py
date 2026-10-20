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

    def preparar(self, arquivados=(), camara=None, drive=None):
        camara, drive = camara or {}, drive or {}
        arquivos = [{"name": n, "id": i, "webViewLink": f"https://drive/{i}"} for n, i in arquivados]
        self.subidos = []
        patches = [
            mock.patch.object(index, "obter_ou_criar_subpasta", return_value="PASTA"),
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
        return f"https://drive/novo/{nome}"


class TestRespondidoFalso(_Base):
    ARQ = "RESPOSTA_1_852-2025_a.pdf"

    def test_download_falho_usa_a_copia_do_drive(self):
        self.preparar(arquivados=[(self.ARQ, "id1")], camara={}, drive={"id1": MERITO})
        aba, valores, _, nova, sem_pdf = processar_item(
            _item(("a", "24/04/2025")), object(), "RAIZ", False, ";", classificar_tudo=True)
        self.assertEqual(aba, ABA_REQUERIMENTOS)
        self.assertEqual(valores[COL_SITUACAO], cls.RESPONDIDO)
        self.assertEqual(valores[COL_DATA_MERITO], "24/04/2025")
        self.assertFalse(nova)
        self.assertFalse(sem_pdf)

    def test_sem_camara_e_sem_drive_nao_grava_situacao(self):
        # antes: INDETERMINADO → "respondido" falso e permanente
        self.preparar(arquivados=[(self.ARQ, "id1")], camara={}, drive={})
        _, valores, _, _, sem_pdf = processar_item(
            _item(("a", "24/04/2025")), object(), "RAIZ", False, ";", classificar_tudo=True)
        self.assertNotIn(COL_SITUACAO, valores)
        self.assertNotIn(COL_DATA_MERITO, valores)
        self.assertFalse(sem_pdf)  # o PDF está arquivado; só não deu para ler agora

    def test_um_pdf_ilegivel_impede_veredito_parcial(self):
        # prorrogação nova lida + mérito arquivado ilegível: gravar "só prorrogação"
        # rebaixaria um item respondido — fica sem veredito nesta passada
        self.preparar(arquivados=[(self.ARQ, "id1")],
                      camara={"https://camara/b.pdf": PRORROGA}, drive={})
        _, valores, _, nova, _ = processar_item(
            _item(("a", "24/04/2025"), ("b", "01/05/2025")), object(), "RAIZ", False, ";", True)
        self.assertNotIn(COL_SITUACAO, valores)
        self.assertTrue(nova)

    def test_sem_nenhum_pdf_de_resposta_arquivado(self):
        self.preparar(arquivados=[], camara={}, drive={})
        _, valores, _, nova, sem_pdf = processar_item(
            _item(("a", "24/04/2025")), object(), "RAIZ", False, ";", True)
        self.assertTrue(sem_pdf)
        self.assertFalse(nova)
        self.assertNotIn(COL_SITUACAO, valores)
        self.assertEqual(self.subidos, [])

    def test_resposta_nova_e_classificada(self):
        self.preparar(arquivados=[], camara={"https://camara/a.pdf": MERITO})
        _, valores, _, nova, sem_pdf = processar_item(
            _item(("a", "24/04/2025")), object(), "RAIZ", False, ";", True)
        self.assertEqual((valores[COL_SITUACAO], nova, sem_pdf), (cls.RESPONDIDO, True, False))
        self.assertEqual(self.subidos, ["RESPOSTA_1_852-2025_a.pdf"])


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
