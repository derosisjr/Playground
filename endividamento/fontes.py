# -*- coding: utf-8 -*-
"""Fonte do Painel de Endividamento: SICONFI/RGF (Tesouro Nacional).

RGF = Relatório de Gestão Fiscal, publicado por quadrimestre (municípios
> 50 mil hab.), com os números oficiais dos limites da LRF:
  - Anexo 01: despesa total com pessoal (limite 54% da RCL p/ o Executivo);
  - Anexo 02: dívida consolidada bruta/líquida, RCL, precatórios vencidos,
    disponibilidade de caixa e restos a pagar (limite DCL 120% da RCL);
  - Anexo 03: garantias concedidas (limite 22%) — Santos não publica itens
    (sem garantias); o pipeline degrada sem quebrar;
  - Anexo 04: operações de crédito (limite 16%; ARO 7%).

Mesma API JSON já usada pelo painel de indicadores (apidatalake do Tesouro,
verificada no ar em 2026-07-13 com dados de Santos até 2023-Q3+).
"""
import time
import unicodedata

import requests

IBGE_SANTOS = "3548500"

SICONFI_RGF = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rgf"

ANEXOS = ["RGF-Anexo 01", "RGF-Anexo 02", "RGF-Anexo 03", "RGF-Anexo 04"]

# Contas acompanhadas: chave interna → (anexo, fragmento do rótulo `conta`).
# Casamento por fragmento normalizado (sem acento, caixa alta): os rótulos do
# RGF carregam numerais romanos e fórmulas que mudam de grafia entre exercícios.
CONTAS = {
    # Anexo 01 — pessoal
    "pessoal_dtp":        ("RGF-Anexo 01", "DESPESA TOTAL COM PESSOAL - DTP"),
    "pessoal_rcl_ajust":  ("RGF-Anexo 01", "RECEITA CORRENTE LIQUIDA AJUSTADA PARA CALCULO DOS LIMITES DA DESPESA COM PESSOAL"),
    "pessoal_limite":     ("RGF-Anexo 01", "LIMITE MAXIMO"),
    "pessoal_prudencial": ("RGF-Anexo 01", "LIMITE PRUDENCIAL"),
    "pessoal_alerta":     ("RGF-Anexo 01", "LIMITE DE ALERTA"),
    # Anexo 02 — dívida consolidada
    "dc":                 ("RGF-Anexo 02", "DIVIDA CONSOLIDADA - DC"),
    "dcl":                ("RGF-Anexo 02", "DIVIDA CONSOLIDADA LIQUIDA"),
    "rcl":                ("RGF-Anexo 02", "RECEITA CORRENTE LIQUIDA - RCL"),
    "dc_pct":             ("RGF-Anexo 02", "% DA DC SOBRE A RCL"),
    "dcl_pct":            ("RGF-Anexo 02", "% DA DCL SOBRE A RCL"),
    "divida_limite":      ("RGF-Anexo 02", "LIMITE DEFINIDO POR RESOLUCAO DO SENADO"),
    "divida_alerta":      ("RGF-Anexo 02", "LIMITE DE ALERTA"),
    "precatorios_vencidos": ("RGF-Anexo 02", "PRECATORIOS POSTERIORES A 05/05/2000 (INCLUSIVE) VENCIDOS E NAO PAGOS"),
    "caixa_bruta":        ("RGF-Anexo 02", "DISPONIBILIDADE DE CAIXA BRUTA"),
    "rp_processados":     ("RGF-Anexo 02", "RESTOS A PAGAR PROCESSADOS"),
    "rp_nao_processados": ("RGF-Anexo 02", "RP NAO-PROCESSADOS"),
    "passivo_atuarial":   ("RGF-Anexo 02", "PASSIVO ATUARIAL"),
    # Anexo 03 — garantias (Santos publica vazio; mantido p/ quando surgir)
    "garantias":          ("RGF-Anexo 03", "TOTAL GARANTIAS CONCEDIDAS"),
    "garantias_limite":   ("RGF-Anexo 03", "LIMITE DEFINIDO POR RESOLUCAO DO SENADO"),
    # Anexo 04 — operações de crédito
    "opcred_total":       ("RGF-Anexo 04", "TOTAL CONSIDERADO PARA FINS DA APURACAO DO CUMPRIMENTO DO LIMITE"),
    "opcred_limite":      ("RGF-Anexo 04", "LIMITE GERAL DEFINIDO POR RESOLUCAO DO SENADO"),
    "opcred_alerta":      ("RGF-Anexo 04", "LIMITE DE ALERTA"),
}

_UA = {"User-Agent": "painel-endividamento-camara-santos (github.com/derosisjr/Playground)"}


def _get(url, params=None, tentativas=4, timeout=90):
    """GET com retry simples; devolve o JSON ou levanta a última exceção."""
    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 — retry genérico de rede
            ultimo = e
            time.sleep(8 * (i + 1))
    raise ultimo


def normalizar(texto: str) -> str:
    """Caixa alta sem acentos, p/ casar rótulos entre exercícios."""
    s = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in s if not unicodedata.combining(c)).upper()


def baixar_rgf(ano: int, periodo: int, anexo: str, ibge7: str = IBGE_SANTOS) -> list[dict]:
    """Itens de um anexo do RGF de um quadrimestre (lista vazia se não publicado)."""
    d = _get(SICONFI_RGF, {
        "an_exercicio": ano, "in_periodicidade": "Q", "nr_periodo": periodo,
        "co_tipo_demonstrativo": "RGF", "co_poder": "E",
        "no_anexo": anexo, "id_ente": ibge7,
    })
    return d.get("items", [])


def filtrar_contas(itens: list[dict], anexo: str) -> list[tuple]:
    """Reduz os itens do anexo às contas acompanhadas.

    Devolve tuplas (chave, coluna, valor). Uma mesma conta aparece em várias
    colunas (Valor, %, Até o Nº Quadrimestre...) — todas são preservadas; o
    export escolhe a coluna certa. Fragmentos mais longos têm precedência
    (evita 'LIMITE DE ALERTA' capturar o 'LIMITE MAXIMO', p.ex., não ocorre,
    mas '% DA DC' vs 'DIVIDA CONSOLIDADA - DC' sim).
    """
    mapa = sorted(((frag, chave) for chave, (ax, frag) in CONTAS.items() if ax == anexo),
                  key=lambda p: -len(p[0]))
    saida = []
    for it in itens:
        conta = normalizar(it.get("conta", ""))
        for frag, chave in mapa:
            if frag in conta:
                try:
                    valor = float(it.get("valor"))
                except (TypeError, ValueError):
                    break
                saida.append((chave, str(it.get("coluna", "")), valor))
                break
    return saida
