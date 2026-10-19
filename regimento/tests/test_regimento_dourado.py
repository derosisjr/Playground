"""Teste dourado: o parser reaproveitado pela Lei Orgânica não pode mudar o Regimento.

Regera o índice a partir de regimento/regimento-fonte.md com as opções padrão e compara
com o regimento-index.json publicado — objeto a objeto e no formato que parser.py grava.
"""
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
from regimento import parser  # noqa: E402


def _regerar():
    with open(os.path.join(RAIZ, "regimento", "regimento-fonte.md"), encoding="utf-8") as f:
        return parser.parse(f.read())


def _publicado_texto():
    # o checkout no Windows pode trazer CRLF (core.autocrlf); o arquivo no git é LF
    with open(os.path.join(RAIZ, "regimento-index.json"), encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def test_regimento_regerado_igual_ao_publicado():
    novo = _regerar()
    publicado = json.loads(_publicado_texto())
    assert len(novo) == len(publicado) == 191
    for a, b in zip(novo, publicado):
        assert a == b, f"{a['id']} mudou"


def test_regimento_mesmo_formato_em_disco():
    # o que `python regimento/parser.py` gravaria: nenhum diff no arquivo publicado
    assert json.dumps(_regerar(), ensure_ascii=False, indent=1) == _publicado_texto()


def test_padrao_e_o_regimento():
    # parse(texto) sem opções continua sendo o Regimento (quem já chamava não muda)
    with open(os.path.join(RAIZ, "regimento", "regimento-fonte.md"), encoding="utf-8") as f:
        texto = f.read()
    assert parser.parse(texto) == parser.parse(texto, parser.REGIMENTO)
    assert all("notas" not in a and "adt" not in a for a in parser.parse(texto))
