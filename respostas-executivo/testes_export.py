#!/usr/bin/env python3
"""Testes do export público de requerimentos (sem Google: as três leituras da aba
são listas montadas à mão).

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export import CAMPOS_PUBLICOS, campos_fora_da_lista, montar_itens  # noqa: E402

# Cabeçalho como o da planilha real (inclusive o "Nùmero" com acento grave e a
# coluna interna "Status atual", que NÃO pode sair no índice público).
CAB = ["Ordem", "Assunto", "Secretaria", "Data da Sessão", "Nùmero",
       "Resposta", "Data da resposta", "Status atual",
       "Situação da resposta", "Data da resposta de mérito"]
LINK = '=HYPERLINK("https://drive.google.com/drive/folders/abc";"Resposta")'


def _aba(linhas):
    """Devolve (valores, formulas, brutos) alinhados, como as três leituras."""
    valores = [CAB] + [l["valores"] for l in linhas]
    formulas = [CAB] + [l.get("formulas", l["valores"]) for l in linhas]
    brutos = [CAB] + [l.get("brutos", l["valores"]) for l in linhas]
    return valores, formulas, brutos


def _linha(numero, status="", situacao="", resposta="", sessao=46000, merito=""):
    valores = ["1", "Assunto qualquer", "SEMES", "", numero, "Resposta" if resposta else "",
               "", status, situacao, ""]
    formulas = list(valores)
    formulas[5] = resposta
    brutos = list(valores)
    brutos[3] = sessao
    brutos[9] = merito
    return {"valores": valores, "formulas": formulas, "brutos": brutos}


class TestExportPublico(unittest.TestCase):
    def test_status_interno_nao_vai_ao_indice(self):
        itens = montar_itens(*_aba([
            _linha("1234/2026", status="ok (Falar com o Rui)", situacao="respondido",
                   resposta=LINK, merito=46010),
        ]))
        self.assertEqual(len(itens), 1)
        self.assertNotIn("status", itens[0])
        self.assertNotIn("Falar com o Rui", repr(itens[0]))
        self.assertEqual(campos_fora_da_lista(itens), set())
        self.assertLessEqual(set(itens[0]), set(CAMPOS_PUBLICOS))

    def test_linha_fantasma_com_data_no_numero_e_descartada(self):
        itens = montar_itens(*_aba([
            _linha("27/08/2026", status="07/10/2026"),
            _linha("4386/2026"),
        ]))
        self.assertEqual([i["numero"] for i in itens], ["4386/2026"])

    def test_situacao_vazia_cai_no_criterio_antigo(self):
        itens = montar_itens(*_aba([
            _linha("1/2026", resposta=LINK),   # tem pasta no Drive
            _linha("2/2026"),                  # não tem
        ]))
        self.assertEqual([i["situacao"] for i in itens], ["respondido", "pendente"])
        self.assertEqual([i["respondido"] for i in itens], [True, False])
        self.assertEqual(itens[0]["url_resposta"], "https://drive.google.com/drive/folders/abc")

    def test_situacao_da_planilha_prevalece(self):
        itens = montar_itens(*_aba([
            _linha("10/2025", situacao="so_prorrogacao", resposta=LINK),
        ]))
        self.assertEqual(itens[0]["situacao"], "so_prorrogacao")
        self.assertFalse(itens[0]["respondido"])

    def test_guarda_acusa_campo_novo(self):
        self.assertEqual(campos_fora_da_lista([{"numero": "1/2026", "status": "x"}]),
                         {"status"})

    def test_aba_vazia(self):
        self.assertEqual(montar_itens([], [], []), [])


if __name__ == "__main__":
    unittest.main()
