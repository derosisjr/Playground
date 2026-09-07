"""Texto e moeda em pt-BR — camada comum (eram 9 normalizadores e 5 formatadores).

Os módulos diferem de propósito em dois eixos, por isso são parâmetros e não
uma regra única:
  - forma: "NFD" (só tira acento) ou "NFKD" (também decompõe compatibilidade:
    "º"→"o", "²"→"2"). Um classificador que casa regex contra "nº" depende
    disso — não trocar em silêncio.
  - caixa: None (preserva), "baixa", "alta" ou "casefold".
"""
import unicodedata


def sem_acento(s, forma="NFD", caixa=None) -> str:
    s = "" if s is None else str(s)
    s = "".join(c for c in unicodedata.normalize(forma, s) if not unicodedata.combining(c))
    if caixa == "baixa":
        return s.lower()
    if caixa == "alta":
        return s.upper()
    if caixa == "casefold":
        return s.casefold()
    return s


def brl(v, casas=2) -> str:
    """R$ 1.234.567,89 — separadores pt-BR, `casas` decimais (None e 0 viram R$ 0,00)."""
    return ("R$ " + f"{(v or 0):,.{casas}f}").replace(",", "X").replace(".", ",").replace("X", ".")


def fator(v) -> str:
    """4,3× (uma casa, vírgula decimal) — razão entre dois valores."""
    return f"{v:.1f}".replace(".", ",") + "×"


def compacto(v) -> str:
    """R$ 8,44 bi · R$ 157,0 mi · R$ 500 mil · R$ 123,45 — a mesma escala do site (comum.js)."""
    v = v or 0
    a = abs(v)
    if a >= 1e9:
        return "R$ " + f"{v / 1e9:.2f}".replace(".", ",") + " bi"
    if a >= 1e6:
        return "R$ " + f"{v / 1e6:.1f}".replace(".", ",") + " mi"
    if a >= 1e3:
        return "R$ " + f"{v / 1e3:.0f}".replace(".", ",") + " mil"
    return brl(v)
