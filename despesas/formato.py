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
  - CÂMARA exige "MUNICIPAL" (evita pegar Câmara de Comércio etc.).
Revisão de 2026-10 (fundações privadas e entidades "do Estado de São Paulo"
contadas como ente): ver `eh_ente_publico` — FUNDAÇÃO deixou de ser genérica.
"""

import hashlib
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
# Aplicado sobre o nome SEM acento e em MAIÚSCULAS (via sem_acento). Ordem da
# decisão em eh_ente_publico (revisão de 2026-10 — conferida nos nomes da base):
#   1. exceções públicas explícitas: estatais do município (PRODESAN, COHAB,
#      CET-Santos) — a concentração delas numa função é esperada (COHAB = 100% de
#      Habitação virava "anomalia"), e nenhuma guarda privada pode tirá-las;
#   2. guarda de forma PRIVADA, antes de qualquer marcador público: começa com
#      Associação/Federação/Sindicato, contém "Fundação de Apoio", ou tem
#      LTDA/EIRELI/ME/EPP — e as exceções nominais (AFIP, FIPE, FGV, SABESP).
#      Casos que a regra antiga contava como ente: AFIP ("…FUNDO DE INCENTIVO…"),
#      ANEPREM ("…MUNICIPIOS"), Federação de Tênis de Mesa e Associação de Lutas
#      ("…DO ESTADO DE SAO PAULO"), FUSP e FAP-UNIFESP (fundações de apoio);
#   3. FUNDAÇÃO não é mais marcador genérico: só a lista curada de fundações
#      públicas (SETTAPORT e FCTH, privadas, entravam pelo nome);
#   4. marcadores públicos (_ENTE_RE): FUNDO só seguido de qualificador público e
#      "ESTADO DE SÃO PAULO" só com marcador estatal antes (governo, secretaria,
#      polícia, companhia estadual…).
_ENTE_EXPLICITO_RE = re.compile(r"COMPANHIA DE ENGENHARIA DE TRAFEGO|\bPRODESAN\b|\bCOHAB\b")

_ENTE_RE = re.compile(
    r"MUNICIPIO|PREFEITURA|CAMARA MUNICIPAL|"
    r"INSTITUTO DE PREVID|PREVIDENCIA SOCIAL DOS SERVIDORES|IPREMM|"
    r"CAIXA DE ASSIST|CAPEP|\bIPS\b|"
    r"\bFUNDO (?:MUNICIPAL|ESTADUAL|NACIONAL|FEDERAL|PENITENCIARIO|PREVIDENCIARIO|SOCIAL DE SOLIDARIEDADE)\b|"
    r"INSS|INSTITUTO NACIONAL DO SEGURO|"
    r"CAIXA ECONOMICA FEDERAL|MINISTERIO|FAZENDA NACIONAL|"
    r"RECEITA|SECRETARIA DA RECEITA|TESOURO|"
    r"GOVERNO DO ESTADO|FAZENDA DO ESTADO|"
    r"\b(?:GOVERNO|FAZENDA|TRIBUNAL|POLICIA|BOMBEIROS|DEPARTAMENTO|PROCURADORIA|DEFENSORIA|ASSEMBLEIA|"
    r"COMPANHIA|CIA)\b.*\bESTADO DE SAO PAULO|"
    r"FUNDO DE GARANTIA|FGTS|PASEP|"
    r"\bSECRETARIA\b")   # órgãos (ex.: SECRETARIA DE TURISMO E VIAGENS, do Estado)

# Fundações PÚBLICAS conhecidas na base (o nome casa por trecho).
FUNDACOES_PUBLICAS = (
    "FUNDACAO ARQUIVO E MEMORIA DE SANTOS",          # FAMS — fundação municipal (UG da base)
    "FUNDACAO PRO-ESPORTE", "FUNDACAO PRO ESPORTE", "FUPES",  # Pró-Esporte — fundação municipal (UG da base)
    "MANOEL PEDRO PIMENTEL",                         # FUNAP — fundação do Governo do Estado de SP
    "FUNDACAO UNIVERSIDADE DE BRASILIA",             # FUB — fundação pública federal
    "FUNDACAO DE APOSENTADORIAS E PENSOES DOS SERVIDORES",  # FUNAPE/PE — previdência de servidores
)
# PENDENTES DE DECISÃO DO USUÁRIO (2026-10): natureza jurídica não confirmada.
# Seguem como ente público — o comportamento anterior — até a decisão.
FUNDACOES_DUVIDOSAS = (
    "FUNDACAO PARQUE TECNOLOGICO DE SANTOS",         # [Verificar] também é UG da base
    "FUNDACAO PINACOTECA BENEDITO CALIXTO",          # [Verificar]
    "CENEP",                                         # Fundação Centro de Excelência Portuária [Verificar]
    "FUNDACAO DE PREVIDENCIA COMPLEMENTAR DO ESTADO DE SAO PAULO",  # SP-PREVCOM [Verificar]
)

# Exceções nominais: entidades PRIVADAS contratadas como fornecedoras (conferido na
# base em 2026-07). SABESP: privatizada em jul/2024 — o nome ("…DO ESTADO DE SAO
# PAULO") casava como ente.
_NAO_ENTE_RE = re.compile(r"\bAFIP\b|\bFIPE\b|FUNDACAO GETULIO VARGAS|\bFGV\b|SABESP|SANEAMENTO BASICO DO ESTADO")
# Forma jurídica privada (ver item 2 acima); a sigla antes do nome ("XYZ - ASSOCIAÇÃO…") é tolerada.
_PRIVADO_RE = re.compile(
    r"^(?:[A-Z0-9.&/]+\s*-\s*)?(?:ASSOCIACAO|FEDERACAO|SINDICATO)\b|"
    r"FUNDACAO DE APOIO|"
    r"\b(?:LTDA|EIRELI|EPP)\b|[\s-]ME\.?$")


def eh_ente_publico(nome) -> bool:
    n = sem_acento(nome)
    if _ENTE_EXPLICITO_RE.search(n):
        return True
    if _NAO_ENTE_RE.search(n) or _PRIVADO_RE.search(n):
        return False
    if re.search(r"\bFUNDACAO\b", n) and any(f in n for f in FUNDACOES_PUBLICAS + FUNDACOES_DUVIDOSAS):
        return True
    return bool(_ENTE_RE.search(n))


# ── Identidade do favorecido (2026-09) ────────────────────────────────────────
# O Portal TP grafa o mesmo CNPJ de várias formas ("INSTITUTO DE PREVIDÊNCIA…",
# "INSTITUTO DE PREVIDENCIA…", "IPREV - INST. PREV…"), e o ranking agrupava por
# nome+documento enquanto o dossiê usava só o documento: entradas separadas no
# ranking e um dossiê que mostrava só a última grafia. A identidade canônica é:
#   - CNPJ completo (14 dígitos, sem máscara)  → "cnpj:<14 dígitos>"
#   - CPF mascarado ("***.158.308-**")         → "cpf:<dígitos visíveis>|<nome normalizado>"
#       (conservador: dígitos parciais NÃO bastam — só une com o mesmo nome)
#   - documento atípico/incompleto             → "doc:<dígitos>|<nome normalizado>"
#   - sem documento                            → "nome:<nome normalizado>"
# Nome normalizado = maiúsculas, sem acento, espaços colapsados — o mesmo
# algoritmo de Comum.identidadeFavorecido (comum.js); mudar um exige mudar o outro.
def nome_normalizado(nome) -> str:
    return " ".join(sem_acento(nome).split())


def identidade_favorecido(nome, doc) -> tuple[str, str]:
    """Devolve (chave canônica, tipo) — tipo ∈ {"cnpj", "cpf", "doc", "nome"}."""
    doc = (doc or "").strip()
    dig = re.sub(r"\D", "", doc)
    if "*" not in doc and len(dig) == 14:
        return "cnpj:" + dig, "cnpj"
    n = nome_normalizado(nome)
    if "*" in doc:
        return f"cpf:{dig}|{n}", "cpf"
    if dig:
        return f"doc:{dig}|{n}", "doc"
    return "nome:" + n, "nome"


def slug_favorecido(chave: str) -> str:
    """Slug do dossiê (favorecidos/<slug>.json): CNPJ vira os 14 dígitos (links
    antigos ?f=<cnpj> continuam válidos); os demais, hash curto da chave canônica."""
    if chave.startswith("cnpj:"):
        return chave[5:]
    return hashlib.md5(chave.encode("utf-8")).hexdigest()[:12]


def nome_exibicao(grafias: dict) -> str:
    """Escolha determinística do nome de exibição entre as grafias originais
    (`{grafia: nº de lançamentos}`): sem caractere de substituição (U+FFFD, sinal de
    codificação quebrada na origem) > mais lançamentos > mais longa > ordem alfabética."""
    if not grafias:
        return ""
    return min(grafias, key=lambda g: ("�" in g, -grafias[g], -len(g), g))
