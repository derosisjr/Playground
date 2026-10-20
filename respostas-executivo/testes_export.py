#!/usr/bin/env python3
"""Testes do export público de requerimentos (sem Google: as três leituras da aba
são listas montadas à mão).

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import date  # noqa: E402

from export import CAMPOS_PUBLICOS, campos_fora_da_lista, montar_itens, resumo_prazos  # noqa: E402

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


def _linha(numero, status="", situacao="", resposta="", sessao=46000, merito="",
           assunto="Assunto qualquer", secretaria="SEMES"):
    valores = ["1", assunto, secretaria, "", numero, "Resposta" if resposta else "",
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

    def test_pasta_sem_veredito_e_a_classificar_nao_respondido(self):
        # pasta no Drive não prova resposta de mérito (pode ter sido criada sem PDF de
        # resposta): até out/2026 ela virava "respondido"
        itens = montar_itens(*_aba([
            _linha("1/2026", resposta=LINK),   # tem pasta no Drive, sem situação
            _linha("2/2026"),                  # não tem
        ]))
        self.assertEqual([i["situacao"] for i in itens], ["a_classificar", "pendente"])
        self.assertEqual([i["respondido"] for i in itens], [False, False])
        self.assertEqual(itens[0]["url_resposta"], "https://drive.google.com/drive/folders/abc")
        self.assertTrue(itens[0]["vence_em"])  # sem mérito, segue na conta do prazo

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

    # 46000 = 09/12/2025 no calendário do Sheets
    def test_campos_de_cobranca(self):
        itens = montar_itens(*_aba([
            _linha("210/2025", situacao="so_prorrogacao", resposta=LINK, secretaria="Saúde"),
            _linha("1578/2025", situacao="pendente", secretaria="NÃO SEI",
                   assunto="Resposta ao requerimento 210/2025 - Licença; ver também requerimento 9/2020"),
            _linha("20/2026", situacao="respondido", resposta=LINK, merito=46010,
                   assunto="Requerimento 20/2026 cita a si mesmo"),
        ]))
        por_num = {i["numero"]: i for i in itens}
        self.assertEqual(por_num["210/2025"]["secretaria"], "SMS")
        self.assertEqual(por_num["1578/2025"]["secretaria"], "")  # "NÃO SEI" não vira sigla
        self.assertEqual(por_num["210/2025"]["vence_em"], "08/01/2026")   # 15 + 15
        self.assertEqual(por_num["1578/2025"]["vence_em"], "24/12/2025")  # 15
        self.assertEqual(por_num["20/2026"]["vence_em"], "")              # respondido
        # só cita o que existe na base e não a si mesmo
        self.assertEqual(por_num["1578/2025"]["cita"], ["210/2025"])
        self.assertNotIn("cita", por_num["20/2026"])
        self.assertEqual(campos_fora_da_lista(itens), set())

    def test_resumo_dos_prazos(self):
        itens = montar_itens(*_aba([
            _linha("1/2026", situacao="respondido", resposta=LINK, merito=46010),  # 10 dias
            _linha("2/2026", situacao="respondido", resposta=LINK, merito=46040),  # 40 dias
            _linha("3/2026", situacao="pendente"),
        ]))
        r = resumo_prazos(itens, hoje=date(2026, 3, 1))
        self.assertEqual((r["com_merito"], r["ate_15"], r["ate_30"]), (2, 1, 1))
        self.assertEqual(r["mediana"], 25)
        self.assertEqual((r["sem_merito"], r["fora_do_prazo"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
