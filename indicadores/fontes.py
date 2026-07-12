# -*- coding: utf-8 -*-
"""Registro das fontes externas do painel Custo por Resultado.

Todas as fontes da v1 são APIs JSON estáveis, verificadas no ar em 2026-07-12:
  - SICONFI/DCA (Tesouro): despesa por função, todos os municípios, 2019+.
  - IBGE pesquisa 39 (Registro Civil): taxa de mortalidade infantil.
  - IBGE pesquisa 40: IDEB rede pública municipal (anos iniciais/finais).
  - IBGE agregado 6579: população residente estimada por ano (per capita).

Fase 2 (fontes sem API formal, exigem POST em formulário — não incluídas na v1
para não criar dependência frágil): DATASUS/TABNET (internações por condições
sensíveis, produção ambulatorial) e e-Gestor AB (cobertura da atenção básica).
"""
import time

import requests

# Municípios comparáveis (código IBGE de 7 dígitos → nome).
# Critério: municípios paulistas de porte populacional similar a Santos.
COMPARAVEIS = {
    "3548500": "Santos",
    "3549904": "São José dos Campos",
    "3543402": "Ribeirão Preto",
    "3552205": "Sorocaba",
    "3529401": "Mauá",
    "3513801": "Diadema",
}

# A API de pesquisas do IBGE responde com códigos de 6 dígitos (sem o dígito
# verificador); este mapa devolve o código canônico de 7 dígitos.
IBGE6_PARA_7 = {c[:6]: c for c in COMPARAVEIS}

_MUN_PIPE = "|".join(COMPARAVEIS)

# Indicadores da v1: slug → metadados usados pelo crawler e pelo export.
# "melhor" indica a direção desejável do indicador ("maior" ou "menor").
INDICADORES = {
    "mortalidade_infantil": {
        "nome": "Mortalidade infantil (óbitos por mil nascidos vivos)",
        "tema": "saude", "melhor": "menor", "fonte_nome": "IBGE/Registro Civil",
        "pesquisa_ibge": 39, "indicador_ibge": 30279,
    },
    "ideb_iniciais": {
        "nome": "IDEB — anos iniciais (rede municipal)",
        "tema": "educacao", "melhor": "maior", "fonte_nome": "INEP/IDEB via IBGE",
        "pesquisa_ibge": 40, "indicador_ibge": 78188,
    },
    "ideb_finais": {
        "nome": "IDEB — anos finais (rede municipal)",
        "tema": "educacao", "melhor": "maior", "fonte_nome": "INEP/IDEB via IBGE",
        "pesquisa_ibge": 40, "indicador_ibge": 78193,
    },
}

# Funções orçamentárias acompanhadas (código no DCA → tema do painel).
FUNCOES = {"10": "saude", "12": "educacao"}

SICONFI_DCA = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca"
IBGE_PESQUISAS = ("https://servicodados.ibge.gov.br/api/v1/pesquisas/"
                  "{pesquisa}/periodos/all/indicadores/{indicador}/resultados/{municipios}")
# Agregados v3: localidades separadas por vírgula; períodos por "|".
# 6579 = estimativas de população; 9514 = Censo 2022 (preenche o ano-censo).
IBGE_POPULACAO = ("https://servicodados.ibge.gov.br/api/v3/agregados/6579/"
                  "periodos/{periodos}/variaveis/9324?localidades=N6[{municipios}]")
IBGE_CENSO_2022 = ("https://servicodados.ibge.gov.br/api/v3/agregados/9514/"
                   "periodos/2022/variaveis/93?localidades=N6[{municipios}]"
                   "&classificacao=2[6794]|287[100362]|286[113635]")

_UA = {"User-Agent": "painel-indicadores-camara-santos (github.com/derosisjr/Playground)"}


def _get(url, params=None, tentativas=3, timeout=60):
    """GET com retry simples; devolve o JSON ou levanta a última exceção."""
    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 — retry genérico de rede
            ultimo = e
            time.sleep(3 * (i + 1))
    raise ultimo


def baixar_dca(ano: int, ibge7: str) -> list[dict]:
    """Itens do DCA Anexo I-E (despesa por função) de um município/ano."""
    d = _get(SICONFI_DCA, {"an_exercicio": ano, "no_anexo": "DCA-Anexo I-E",
                           "id_ente": ibge7})
    return d.get("items", [])


def baixar_indicador_ibge(slug: str) -> list[dict]:
    """Resultados (todos os períodos, todos os comparáveis) de um indicador."""
    meta = INDICADORES[slug]
    url = IBGE_PESQUISAS.format(pesquisa=meta["pesquisa_ibge"],
                                indicador=meta["indicador_ibge"],
                                municipios=_MUN_PIPE)
    return _get(url)


def _extrair_series_v3(d: list) -> dict:
    saida = {}
    for agregado in d:
        for resultado in agregado.get("resultados", []):
            for serie in resultado.get("series", []):
                loc = serie["localidade"]["id"]
                for ano, valor in serie["serie"].items():
                    if valor not in (None, "-", "...", ".."):
                        saida[(loc, int(ano))] = int(float(valor))
    return saida


def baixar_populacao(anos: list[int]) -> dict:
    """População por município/ano: {(ibge7, ano): int}.

    Estimativas (6579) não cobrem todos os anos (ex.: 2022, ano do Censo);
    pede um ano por vez, ignora os indisponíveis e completa 2022 com o Censo.
    O consumidor deve usar o ano disponível mais próximo para os que faltarem.
    """
    mun = ",".join(COMPARAVEIS)
    saida = {}
    for ano in anos:
        try:
            d = _get(IBGE_POPULACAO.format(periodos=ano, municipios=mun))
            saida.update(_extrair_series_v3(d))
        except Exception:  # noqa: BLE001 — ano sem estimativa publicada
            continue
    if any(a == 2022 for a in anos) and not any(k[1] == 2022 for k in saida):
        try:
            saida.update(_extrair_series_v3(
                _get(IBGE_CENSO_2022.format(municipios=mun))))
        except Exception:  # noqa: BLE001
            pass
    return saida
