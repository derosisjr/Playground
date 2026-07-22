#!/usr/bin/env python3
"""
Formatação e classificação compartilhadas da Base de Despesas
=============================================================

Única fonte para:
  - moeda pt-BR (`brl`, `compacto`) e variação (`pct`) — antes reimplementadas
    com regras divergentes em export.py e briefing.py;
  - `eh_ente_publico()` — classificação "ente público/repasse" × "fornecedor de
    mercado", antes duas heurísticas paralelas (regex no export, lista no briefing).

Notas da unificação (2026-07):
  - FUNDAÇÃO entra genérica: as recorrentes em Santos são municipais (FAMS,
    FUPES, Parque Tecnológico). Se uma fundação PRIVADA virar fornecedora
    relevante, restrinja aqui (um só lugar).
  - CÂMARA exige "MUNICIPAL" (evita pegar Câmara de Comércio etc.).
"""

import re
import unicodedata


def sem_acento(s) -> str:
    s = "" if s is None else str(s)
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").upper()


def brl(v) -> str:
    """R$ 1.234.567,89 (sempre 2 casas)."""
    return "R$ " + f"{(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def compacto(v) -> str:
    """R$ 8,44 bi · R$ 157,0 mi · R$ 500 mil · R$ 123,45."""
    v = v or 0
    a = abs(v)
    if a >= 1e9:
        return "R$ " + f"{v/1e9:.2f}".replace(".", ",") + " bi"
    if a >= 1e6:
        return "R$ " + f"{v/1e6:.1f}".replace(".", ",") + " mi"
    if a >= 1e3:
        return "R$ " + f"{v/1e3:.0f}".replace(".", ",") + " mil"
    return brl(v)


def pct(novo, velho) -> str:
    """Variação percentual com seta (▲ 12% / ▼ 5% / •)."""
    if not velho:
        return "—"
    p = 100 * ((novo or 0) - velho) / velho
    seta = "▲" if p > 0 else ("▼" if p < 0 else "•")
    return f"{seta} {abs(p):.0f}%"


# Entes públicos e repasses institucionais (municipais, estaduais e federais).
# Aplicado sobre o nome SEM acento e em MAIÚSCULAS (via sem_acento).
_ENTE_RE = re.compile(
    r"MUNICIPIO|PREFEITURA|CAMARA MUNICIPAL|"
    r"INSTITUTO DE PREVID|PREVIDENCIA SOCIAL DOS SERVIDORES|IPREMM|"
    r"CAIXA DE ASSIST|CAPEP|\bIPS\b|"
    r"FUNDO |FUNDACAO|"
    r"INSS|INSTITUTO NACIONAL DO SEGURO|"
    r"CAIXA ECONOMICA FEDERAL|MINISTERIO|FAZENDA NACIONAL|"
    r"RECEITA|SECRETARIA DA RECEITA|TESOURO|"
    r"GOVERNO DO ESTADO|ESTADO DE SAO PAULO|FAZENDA DO ESTADO|"
    r"FUNDO DE GARANTIA|FGTS|PASEP")


# Exceções: nomes que casam com FUNDO/FUNDAÇÃO mas são entidades PRIVADAS
# contratadas como fornecedoras (conferido na base em 2026-07).
_NAO_ENTE_RE = re.compile(r"\bAFIP\b|\bFIPE\b|FUNDACAO GETULIO VARGAS|\bFGV\b")


def eh_ente_publico(nome) -> bool:
    n = sem_acento(nome)
    if _NAO_ENTE_RE.search(n):
        return False
    return bool(_ENTE_RE.search(n))
