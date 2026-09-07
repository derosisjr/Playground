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

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz do repo: comum/
from comum.formato import brl, compacto, fator  # noqa: E402,F401 — reexportados p/ export.py e briefing.py
from comum.formato import sem_acento as _sem_acento  # noqa: E402


def sem_acento(s) -> str:
    """Maiúsculas sem acento (NFD) — a forma que _ENTE_RE espera."""
    return _sem_acento(s, caixa="alta")


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
