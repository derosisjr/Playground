import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
from comum.formato import brl, compacto, fator, sem_acento  # noqa: E402


def test_sem_acento_formas_e_caixas():
    assert sem_acento("Ação nº 12") == "Acao nº 12"                       # NFD preserva º
    assert sem_acento("Ação nº 12", forma="NFKD") == "Acao no 12"         # NFKD decompõe º
    assert sem_acento("Ação", caixa="alta") == "ACAO"
    assert sem_acento("AÇÃO", caixa="baixa") == "acao"
    assert sem_acento("Straße", caixa="casefold") == "strasse"
    assert sem_acento(None) == ""


def test_brl_casas():
    assert brl(1234567.891) == "R$ 1.234.567,89"
    assert brl(0.0737, 4) == "R$ 0,0737"
    assert brl(1234.5, 0) == "R$ 1.234"
    assert brl(None) == "R$ 0,00"


def test_compacto_e_fator():
    assert compacto(8_440_000_000) == "R$ 8,44 bi"
    assert compacto(157_000_000) == "R$ 157,0 mi"
    assert compacto(500_000) == "R$ 500 mil"
    assert compacto(123.45) == "R$ 123,45"
    assert fator(4.3) == "4,3×"
