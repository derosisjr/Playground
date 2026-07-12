# -*- coding: utf-8 -*-
"""Registro das fontes externas do painel Custo por Resultado.

Todas APIs JSON estáveis, verificadas no ar (v1 em 2026-07-12; v2 em 2026-07-13):
  - SICONFI/DCA (Tesouro): despesa por função (I-E), receita (I-C) e despesa por
    categoria econômica (I-D — pessoal, investimento), todos os municípios, 2019+.
  - IBGE pesquisa 39 (Registro Civil): taxa de mortalidade infantil.
  - IBGE pesquisa 40: IDEB rede pública municipal (anos iniciais/finais).
  - IBGE pesquisa 13 (Censo Escolar): matrículas e docentes por rede.
  - IBGE agregado 6579: população residente estimada por ano (per capita).
  - Referência "média do Estado de SP" (N3[35]) onde a API do IBGE a fornece
    (mortalidade infantil sim; IDEB via IBGE não expõe estadual — degrada).

Fase futura (exigem POST em formulário / agregação registro a registro —
fora do escopo para não criar dependência frágil): DATASUS/TABNET (internações
por condições sensíveis, produção ambulatorial), e-Gestor AB (cobertura da
atenção básica) e segurança (SSP-SP, estadual e instável).
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

# Indicadores de fonte IBGE (pesquisas): slug → metadados p/ crawler e export.
# "melhor" indica a direção desejável ("maior" ou "menor"). `folhas` (opcional):
# lista de indicadores-folha a SOMAR (Censo Escolar dá valor por rede/série);
# `por_mil`: normaliza por mil habitantes; `divisor_slug`: forma uma razão.
INDICADORES = {
    "mortalidade_infantil": {
        "nome": "Mortalidade infantil (óbitos por mil nascidos vivos)",
        "tema": "saude", "melhor": "menor", "fonte_nome": "IBGE/Registro Civil",
        "pesquisa_ibge": 39, "indicador_ibge": 30279, "formato": "num",
    },
    "ideb_iniciais": {
        "nome": "IDEB — anos iniciais (rede municipal)",
        "tema": "educacao", "melhor": "maior", "fonte_nome": "INEP/IDEB via IBGE",
        "pesquisa_ibge": 40, "indicador_ibge": 78188, "formato": "num",
    },
    "ideb_finais": {
        "nome": "IDEB — anos finais (rede municipal)",
        "tema": "educacao", "melhor": "maior", "fonte_nome": "INEP/IDEB via IBGE",
        "pesquisa_ibge": 40, "indicador_ibge": 78193, "formato": "num",
    },
    "matriculas_creche_pc": {
        "nome": "Matrículas em creche (rede municipal, por mil hab.)",
        "tema": "educacao", "melhor": "maior", "fonte_nome": "IBGE/Censo Escolar",
        "pesquisa_ibge": 13, "folhas": [77883], "por_mil": True, "formato": "num",
    },
    "alunos_por_docente": {
        "nome": "Alunos por docente — anos iniciais (rede municipal)",
        "tema": "educacao", "melhor": "menor", "fonte_nome": "IBGE/Censo Escolar",
        "pesquisa_ibge": 13,
        # matrículas 1º–5º ano municipal ÷ docentes anos iniciais municipal
        "folhas": [77941, 77945, 77949, 77953, 77957],
        "folhas_divisor": [77997], "formato": "num",
    },
}

# Indicadores fiscais (derivados do SICONFI): calculados no export a partir da
# tabela `fiscal` + população. `conta`/`divisor` referem-se às chaves de FISCAL_CONTAS.
INDICADORES_FISCAIS = {
    "receita_propria_pc": {
        "nome": "Receita tributária própria por habitante (R$)",
        "melhor": "maior", "conta": "tributos", "per_capita": True, "formato": "brl",
    },
    "autonomia_fiscal": {
        "nome": "Autonomia fiscal (% da receita corrente que é arrecadação própria)",
        "melhor": "maior", "conta": "tributos", "divisor": "receita_corrente",
        "percentual": True, "formato": "pct",
    },
    "investimento_pc": {
        "nome": "Investimento por habitante (R$)",
        "melhor": "maior", "conta": "investimento", "per_capita": True, "formato": "brl",
    },
    "pessoal_pc": {
        "nome": "Despesa com pessoal por habitante (R$)",
        "melhor": "menor", "conta": "pessoal", "per_capita": True, "formato": "brl",
    },
}

# Contas do DCA que compõem a tabela `fiscal` (chave → (anexo, conta exata, coluna)).
# Linhas de topo do plano de contas — casamento por conta exata (robusto).
FISCAL_CONTAS = {
    "tributos": ("DCA-Anexo I-C", "1.1.0.0.00.0.0", "Receitas Brutas Realizadas"),
    "receita_corrente": ("DCA-Anexo I-C", "1.0.0.0.00.0.0", "Receitas Brutas Realizadas"),
    "pessoal": ("DCA-Anexo I-D", "3.1.00.00.00", "Despesas Empenhadas"),
    "investimento": ("DCA-Anexo I-D", "4.4.00.00.00", "Despesas Empenhadas"),
}

# Funções orçamentárias acompanhadas (código no DCA → tema do painel).
FUNCOES = {"10": "saude", "12": "educacao"}

# Código do Estado de SP na API de pesquisas do IBGE (nível N3).
UF_SP = "35"

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


def baixar_dca(ano: int, ibge7: str, anexo: str = "DCA-Anexo I-E") -> list[dict]:
    """Itens de um anexo do DCA (I-E despesa/função, I-C receita, I-D despesa/econ.)."""
    d = _get(SICONFI_DCA, {"an_exercicio": ano, "no_anexo": anexo, "id_ente": ibge7})
    return d.get("items", [])


def _valor_conta(itens: list[dict], conta: str, coluna: str):
    """Valor de uma conta exata do DCA (ou None se ausente)."""
    for it in itens:
        if str(it.get("conta", "")).startswith(conta) and it.get("coluna") == coluna:
            return float(it.get("valor") or 0)
    return None


def baixar_fiscal(ano: int, ibge7: str) -> dict:
    """Agrega as contas fiscais (tributos, receita corrente, pessoal, investimento)
    de um município/ano a partir dos anexos I-C e I-D. Devolve {chave: valor}."""
    cache: dict[str, list] = {}
    saida = {}
    for chave, (anexo, conta, coluna) in FISCAL_CONTAS.items():
        if anexo not in cache:
            cache[anexo] = baixar_dca(ano, ibge7, anexo)
        v = _valor_conta(cache[anexo], conta, coluna)
        if v is not None:
            saida[chave] = v
    return saida


def _somar_folhas(folhas: list[int], municipios: str) -> dict:
    """Soma os valores de várias folhas do IBGE por (localidade, ano)."""
    tot: dict[tuple, float] = {}
    for iid in folhas:
        url = IBGE_PESQUISAS.format(pesquisa=13, indicador=iid, municipios=municipios)
        for ind in _get(url):
            for res in ind.get("res", []):
                loc = str(res.get("localidade", ""))
                for ano, v in (res.get("res") or {}).items():
                    if v not in (None, "-", "...", ".."):
                        tot[(loc, int(ano))] = tot.get((loc, int(ano)), 0) + float(v)
    return tot


def baixar_indicador_ibge(slug: str, municipios: str = _MUN_PIPE) -> list[dict]:
    """Resultados de um indicador IBGE p/ os municípios (ou UF de referência).

    Indicadores diretos usam `indicador_ibge`; indicadores compostos usam `folhas`
    (soma) e, opcionalmente, `folhas_divisor` (razão). Devolve sempre no formato
    padrão da API: [{"res": [{"localidade", "res": {ano: valor}}]}].
    """
    meta = INDICADORES[slug]
    if "indicador_ibge" in meta:
        url = IBGE_PESQUISAS.format(pesquisa=meta["pesquisa_ibge"],
                                    indicador=meta["indicador_ibge"],
                                    municipios=municipios)
        return _get(url)
    # composto: soma de folhas, eventualmente dividido por outra soma
    num = _somar_folhas(meta["folhas"], municipios)
    div = _somar_folhas(meta["folhas_divisor"], municipios) if meta.get("folhas_divisor") else None
    por_loc: dict[str, dict] = {}
    for (loc, ano), v in num.items():
        if div is not None:
            d = div.get((loc, ano))
            if not d:
                continue
            v = round(v / d, 2)
        por_loc.setdefault(loc, {})[str(ano)] = v
    return [{"res": [{"localidade": loc, "res": r} for loc, r in por_loc.items()]}]


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
