#!/usr/bin/env python3
"""
Export da base de Despesas → JSON (agregado + detalhe), XLSX e CSV
==================================================================

Lê `despesas/despesas.sqlite` (esquema v2 do crawler, reconciliado por partição) e gera:
  - despesas-index.json (raiz)       índice AGREGADO do painel: séries, favorecidos
                                     consolidados por IDENTIDADE, alertas, execução,
                                     cobertura por partição
  - despesas/dados/AAAA-MM.json      EXECUÇÃO DOS EMPENHOS — uma linha por empenho do mês
                                     (com liquidado/pago acumulados até a data da base)
  - despesas/dados/mov/AAAA-MM.json  MOVIMENTAÇÃO NO PERÍODO — um documento por linha
                                     (empenho/liquidação/pagamento pela data de cada estágio)
  - despesas/dados/estagios/…        documentos de estágio por empenho (ficha)
  - favorecidos/<slug>.json          raio-X por favorecido (top-N, identidade canônica)
  - despesas/arvore.json             função→subfunção→elemento (treemap)
  - despesas/alertas-estado.json     histórico dos alertas (novo/persistente/resolvido)
  - despesas/alertas-candidatos.json todos os casos que acionaram as regras (CSV no painel)
  - despesas/historico/alteracoes-AAAA.jsonl.gz  linhas que a origem removeu/substituiu (só-acréscimo)
  - despesas/despesas.csv / .xlsx    execução por empenho completa (gitignored)

Duas visões, nunca misturadas (2026-09):
  * "Movimentação no período": cada lançamento conta no mês da SUA data (o Visão geral
    e as séries mensais são a movimentação de PAGAMENTOS pela data do pagamento);
  * "Execução dos empenhos": o empenho conta no mês em que foi emitido, com tudo o que
    já foi liquidado/pago dele, em qualquer mês posterior.
  Um empenho de janeiro pago em agosto aparece na movimentação de agosto e na execução
  de janeiro — nunca nos dois recortes de um mesmo mês.

Uso:
    python despesas/export.py                 # artefatos versionados do repo
    python despesas/export.py --db X --saida DIR   # candidato em diretório separado
"""

import argparse
import csv
import glob
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from formato import (brl, compacto as _brl_compacto, eh_ente_publico, fator, identidade_favorecido,
                     nome_exibicao, sem_acento, slug_favorecido)  # camada comum do módulo


AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
if RAIZ not in sys.path:
    sys.path.append(RAIZ)  # camada comum do repo (comum/)
from comum.saida import configurar_stdio  # noqa: E402

configurar_stdio()
from comum.escrita import gravar_bytes, gravar_json, gravar_json_se_mudou  # noqa: E402

ANO_INICIAL = 2025    # mesmo do crawler: 1º mês esperado na cobertura
FONTES = ("empenhos", "liquidacoes", "pagamentos")

# Caminhos (sobrescritos por --db/--saida em main; funções recebem-nos via globais
# para o monkeypatch dos testes continuar funcionando)
DB_PATH = os.path.join(AQUI, "despesas.sqlite")
CSV_PATH = os.path.join(AQUI, "despesas.csv")
XLSX_PATH = os.path.join(AQUI, "despesas.xlsx")
DADOS_DIR = os.path.join(AQUI, "dados")           # execução por empenho, mensal (versionado)
MOV_DIR = os.path.join(DADOS_DIR, "mov")          # movimentação por documento, mensal
ESTAGIOS_DIR = os.path.join(DADOS_DIR, "estagios")  # documentos de estágio por empenho (ficha)
JSON_PATH = os.path.join(RAIZ, "despesas-index.json")
FAV_DIR = os.path.join(RAIZ, "favorecidos")       # raio-X por favorecido (versionado; favorecido.html)
ARVORE_PATH = os.path.join(AQUI, "arvore.json")   # hierarquia função→subfunção→elemento (treemap)
ALERTAS_ESTADO_PATH = os.path.join(AQUI, "alertas-estado.json")  # histórico de alertas (versionado)
ALERTAS_CANDIDATOS_PATH = os.path.join(AQUI, "alertas-candidatos.json")  # todos os casos (versionado)
HISTORICO_DIR = os.path.join(AQUI, "historico")   # alterações da origem, só-acréscimo (versionado)
# recorte do índice só com o serviço da dívida (~1 KB): o painel de Endividamento baixava
# os ~400 KB do despesas-index.json inteiro só para ler esse bloco
SERVICO_DIVIDA_PATH = os.path.join(AQUI, "servico-divida.json")
PAINEL_URL = "./despesas.html"
RAIOX_URL = "./favorecido.html"

COLUNAS = [
    "ano", "mes", "unidade_gestora", "data", "especie", "empenho", "liquidacao",
    "pagamento", "tipo_pagamento", "elemento_despesa", "subtitulo", "funcao",
    "subfuncao", "programa", "fonte_recurso", "grupo_despesa",
    "documento_favorecido", "nome_favorecido", "valor",
]

# ── Limiares dos alertas fiscais (ajuste fino aqui) ───────────────────────────
TOP_FAVORECIDOS = 300           # quantos favorecidos exportar no JSON
ALERTA_FAV_VALOR = 5_000_000    # favorecido acima disso no acumulado → contexto
ALERTA_FAV_MESES = 6            # ...presente em ao menos N meses (recorrência)
ALERTA_CONCENTRACAO_PCT = 40    # favorecido que domina >X% de uma função → alerta
ALERTA_CONCENTRACAO_MIN = 1_000_000   # ...e move ao menos isso (evita ruído)
ALERTA_PICO_K = 2.5             # mês cujo gasto > média + k·desvio → alerta
ALERTA_EXTRA_VALOR = 1_000_000  # pagamento extra-orçamentário acima disso → alerta

# Lei 14.133/2021, art. 75, I (obras e serviços de engenharia) e II (compras e demais
# serviços) — valores atualizados por decreto a cada exercício (art. 182). A tabela
# registra a NORMA e COMO o valor foi verificado; sem verificação de fonte oficial o
# alerta diz isso em vez de afirmar enquadramento. Atualizar aqui ao sair novo decreto.
LIMITES_DISPENSA = {
    2024: {"compras": 59_906.02, "engenharia": 119_812.02,
           "norma": "Decreto 11.871/2023 (efeitos a partir de 1º/1/2024)",
           "verificacao": "valor que já constava do código (LIMITE_DISPENSA=59.906); não reverificado em 2026-09"},
    2025: {"compras": 62_725.59, "engenharia": 125_451.15,
           "norma": "Decreto 12.343/2024 (efeitos a partir de 1º/1/2025)",
           "verificacao": "fonte secundária (novaleilicitacao.com.br, 2025-01-03); texto no Planalto "
                          "não acessível em 2026-09-12 — conferir antes de citar"},
    2026: {"compras": 65_492.11, "engenharia": 130_984.20,
           "norma": "Decreto 12.807/2025 (efeitos a partir de 1º/1/2026)",
           "verificacao": "fontes secundárias (effecti.com.br, elicitacao.com.br; reajuste 4,41% IPCA-E); "
                          "texto no Planalto não acessível em 2026-09-12 — conferir antes de citar"},
}
FRAC_MIN_EMPENHOS = 4           # nº mínimo de EMPENHOS DISTINTOS < limite (mesma UG+favorecido+elemento+ano)
FRAC_FATOR_TOTAL = 1.5          # ...somando ao menos FATOR×limite
FRAC_INFO_FALTANTE = ["objeto da contratação", "modalidade/hipótese de contratação",
                      "processo administrativo", "contrato ou ata vinculada",
                      "valor total contratado (o empenho não é o contrato)"]
# Lei 14.133, art. 75, I também cobre "serviços de manutenção de veículos automotores":
# o limite é o MAIOR (o mesmo de obras/engenharia, coluna "engenharia" acima).
# 33903919 = serviço de manutenção e conservação de veículos; 33903039 = material
# (peças) p/ manutenção de veículos — incluído por decisão de 2026-10 (o § 7º do art. 75
# fala em manutenção "incluído o fornecimento de peças"). [Verificar] o § 7º também tira
# da soma do § 1º as contratações pequenas de manutenção de veículos próprios (R$ 8 mil
# na redação original, valor atualizado por decreto) — a triagem não aplica essa exclusão.
ELEM_MANUT_VEICULOS = ("33903919", "33903039")

# Etiqueta da triagem de fracionamento pelo espelho do Preço comparado (PNCP de Santos):
# fornecedor que venceu pregão com registro de preços nos 24 meses anteriores ao
# empenho provavelmente está fornecendo por ATA (muitos empenhos pequenos são o normal).
PRECOS_ESPELHO_DIR = os.path.join(RAIZ, "precos", "espelho")
IBGE_SANTOS = "3548500"
PNCP_JANELA_DIAS = 730          # 24 meses: a ata vale 1 ano, prorrogável por igual período (art. 84)
PNCP_URL_PUBLICA = "https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}"   # = precos/fontes.py URL_PUBLICA
PNCP_SITUACOES_FORA = ("REVOGADA", "ANULADA", "SUSPENSA")
ETIQUETAS_PNCP = ("provavel_ata", "vencedor_pregao", "dispensa_pncp")   # da mais forte para a mais fraca

# Pago acima do liquidado (por UG + empenho + nº da liquidação)
PAGO_ACIMA_MIN = 100.0          # excesso mínimo, na liquidação E no empenho inteiro
ALERTA_NOVO_MESES = 6           # "novo" = 1ª aparição nos últimos N meses
ALERTA_NOVO_VALOR = 1_000_000   # ...e já acumulou ao menos isso
ALERTA_YOY_FATOR = 3.0          # mesmo período (jan–M) do ano corrente ≥ FATOR× ano anterior
ALERTA_YOY_VALOR = 1_000_000    # ...e move ao menos isso no ano corrente
ALERTA_YOY_MIN_MESES = 3        # período comparado precisa de ao menos N meses completos
ALERTA_PF_VALOR = 100_000       # pessoa física (CPF) em elemento sensível acima disso
# Pico na série do PRÓPRIO favorecido/elemento (z-score local; o pico "global"
# da regra 3 só enxerga o total do mês — estes pegam explosões localizadas)
ALERTA_Z_K = 2.5                # limiar do z-score (mesmo espírito do pico global)
ALERTA_Z_MIN_MESES = 8          # histórico mínimo p/ média/desvio estáveis
ALERTA_ZFAV_VALOR = 1_000_000   # mês anômalo do favorecido move ao menos isso
ALERTA_ZELEM_VALOR = 5_000_000  # mês anômalo do elemento move ao menos isso
ALERTA_NL_VALOR = 1_000_000     # pagamentos "empenho não localizado" no ano acima disso → inconsistência
# elementos com pico de CALENDÁRIO (13º em dezembro, férias etc.): pico ali é
# sazonalidade óbvia, não achado — apontá-lo desmoralizaria a lista de alertas
ELEM_SAZONAIS = ("13º", "13O", "DECIMO TERCEIRO", "DÉCIMO TERCEIRO", "FERIAS", "FÉRIAS", "ABONO PECU")
CAP_POR_REGRA = 15             # teto de alertas por regra (não afogar o painel/e-mail)
CAP_ESPECIAL = {"extra_orcamentario": 20}   # regras com teto próprio
# regras sem teto por regra (poucos casos por construção: meses, partições, anos)
SEM_TETO = ("pico_mensal", "dados_duplicidade", "dados_particao", "dados_cobertura", "dados_taxa",
            "dados_nao_localizado", "dados_incompleto_origem")
MAX_ALERTAS = 120              # teto global — corta "contexto" primeiro
MAX_DOCS_ALERTA = 12           # documentos listados por alerta

# Classes de alerta (2026-09): o que o leitor deve fazer com cada um
CLASSE_CONTEXTO = "contexto"            # informação de escala/recorrência — não é achado
CLASSE_ANOMALIA = "anomalia"            # padrão a conferir (ponto de partida p/ requerimento)
CLASSE_INCONSISTENCIA = "inconsistencia"  # problema nos DADOS (origem ou cobertura)

# entes internos/governamentais — excluídos de "novo"/"YoY" (não são fornecedores
# de mercado). Heurística única em formato.eh_ente_publico (compartilhada c/ briefing).
# CPF mascarado: sem "/" e com "*"; elementos sensíveis p/ pessoa física
SQL_EH_CPF = "documento_favorecido NOT LIKE '%/%' AND documento_favorecido LIKE '%*%'"
ELEM_SENSIVEIS = ("%LOCA%IM%", "%TERCEIRIZA%", "%INDENIZA%", "%CONSULTORIA%", "%TERCEIRO%F_SICA%")

# Tipos (classificação das linhas) — ver rules/despesas.md
T_EMPENHO = "Empenho"
T_EMPENHO_PARCIAL = "Empenho (original fora da base)"   # só anulações/reforços na base
T_ORCAMENTARIO = "Orçamentário"                          # liquidação/pagamento de empenho do exercício
T_RESTOS = "Restos a pagar"                              # exercício de origem anterior (campo da fonte)
T_EXTRA = "Extra-orçamentário"                           # campo da fonte (retenções/consignações)
T_NAO_LOCALIZADO = "Empenho não localizado na base"      # orçamentário, mas o empenho não veio na base


def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _q(conn, sql, *params):
    return conn.execute(sql, params).fetchall()


# ── Identidade dos favorecidos ────────────────────────────────────────────────
# Uma tabela temporária (nome, doc) → chave canônica permite agregar por identidade
# em SQL: JOIN fav_ident fi ON fi.nome = COALESCE(t.nome_favorecido,'') AND
# fi.doc = COALESCE(t.documento_favorecido,''). Ver formato.identidade_favorecido.
FAV_JOIN = ("JOIN fav_ident fi ON fi.nome = COALESCE({t}.nome_favorecido,'') "
            "AND fi.doc = COALESCE({t}.documento_favorecido,'')")


def preparar_identidades(conn) -> dict:
    """Cria a temp table fav_ident e devolve chave → {chave, tipo, nome, documento,
    grafias, slug}. Cobre as três tabelas (o empenho pode ter grafia própria)."""
    conn.execute("DROP TABLE IF EXISTS fav_ident")
    conn.execute("CREATE TEMP TABLE fav_ident (nome TEXT, doc TEXT, chave TEXT, PRIMARY KEY (nome, doc))")
    pares: dict[tuple, int] = defaultdict(int)
    for t in FONTES:
        for r in _q(conn, f"SELECT COALESCE(nome_favorecido,'') n, COALESCE(documento_favorecido,'') d, "
                          f"COUNT(*) c FROM {t} GROUP BY n, d"):
            pares[(r["n"], r["d"])] += r["c"]
    ident: dict[str, dict] = {}
    linhas = []
    for (nome, doc), c in pares.items():
        chave, tipo = identidade_favorecido(nome, doc)
        o = ident.setdefault(chave, {"chave": chave, "tipo": tipo, "grafias": {}, "docs": {}})
        o["grafias"][nome] = o["grafias"].get(nome, 0) + c
        o["docs"][doc] = o["docs"].get(doc, 0) + c
        linhas.append((nome, doc, chave))
    conn.executemany("INSERT INTO fav_ident (nome, doc, chave) VALUES (?,?,?)", linhas)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_fav_ident_chave ON fav_ident(chave)")
    for t in FONTES:   # o JOIN por (nome, doc) e os recortes por favorecido dependem destes índices
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_fav ON {t}(nome_favorecido, documento_favorecido)")
    conn.commit()
    for o in ident.values():
        o["nome"] = nome_exibicao(o["grafias"])
        o["documento"] = nome_exibicao(o["docs"]) if o["docs"] else ""
        o["slug"] = slug_favorecido(o["chave"])
        o["grafias"] = sorted(o["grafias"], key=lambda g: (-o["grafias"][g], g))
        del o["docs"]
    return ident


def _marcar_ente_publico(d: dict) -> dict:
    """Flag p/ o painel separar fornecedores de entes públicos/repasses (Município,
    IPREV, CAPEP…) — a heurística única é formato.eh_ente_publico; o JS não a replica."""
    if eh_ente_publico(d.get("nome")):
        d["ente_publico"] = True
    return d


# ── Contratos e convênios publicados no portal (despesas/instrumentos.py, 2026-10) ──
# Fatias por prefixo do CNPJ em despesas/contratos/ — ENTRADA do export (como o
# espelho do PNCP), lida sempre do repo, mesmo com --saida. Só pessoa jurídica.
CONTRATOS_DIR = os.path.join(AQUI, "contratos")
INSTRUMENTOS_PATH = os.path.join(AQUI, "instrumentos.json")
CONTRATO_JANELA_DIAS = 730   # contrato assinado até 24 meses antes do empenho (a janela do PNCP)


def contratos_portal(diretorio: str | None = None) -> dict:
    """{cnpj (14 dígitos): {"c": [contratos], "v": [convênios firmados]}} — vazio sem os arquivos."""
    out = {}
    for arq in sorted(glob.glob(os.path.join(diretorio or CONTRATOS_DIR, "*.json"))):
        try:
            with open(arq, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        cc, cv = d.get("campos_contrato") or [], d.get("campos_convenio") or []
        for k, item in (d.get("cnpj") or {}).items():
            out[k] = {"c": [dict(zip(cc, l)) for l in item.get("c") or []],
                      "v": [dict(zip(cv, l)) for l in item.get("v") or []]}
    return out


def _instrumentos_do(chave: str, contratos: dict) -> dict | None:
    """Contratos e convênios do favorecido — só identidade com CNPJ e com os arquivos
    carregados (None: não dá para dizer "sem contrato")."""
    if not chave.startswith("cnpj:") or not contratos:
        return None
    return contratos.get(chave[5:]) or {"c": [], "v": []}


def instrumentos_indice() -> dict | None:
    """Bloco `instrumentos` do índice: o resumo de despesas/instrumentos.json (contratos,
    convênios, emendas, ordem cronológica) + o manifesto das emendas (o painel só baixa a
    lista quando a caixa aparece). None sem a coleta (índice anterior a ela)."""
    try:
        with open(INSTRUMENTOS_PATH, encoding="utf-8") as f:
            resumo = {k: v for k, v in json.load(f).items() if k != "versao"}
    except (OSError, ValueError):
        return None
    emendas = os.path.join(AQUI, "emendas.json")
    if os.path.exists(emendas):
        resumo["emendas_arquivo"] = {"arquivo": "despesas/emendas.json", "bytes": os.path.getsize(emendas)}
    return resumo


def _contagem_instrumentos(f: dict, contratos: dict) -> dict:
    """Ranking: quantos contratos e convênios o portal publica para o CNPJ do favorecido."""
    ins = _instrumentos_do(f["chave"], contratos)
    if ins is not None:
        f["contratos"], f["convenios"] = len(ins["c"]), len(ins["v"])
    return f


def _fav_campos(ident: dict, chave: str) -> dict:
    o = ident.get(chave) or {"nome": "", "documento": "", "slug": slug_favorecido(chave), "grafias": []}
    d = {"nome": o["nome"], "documento": o["documento"], "chave": chave, "slug": o["slug"]}
    if len(o.get("grafias") or []) > 1:
        d["grafias"] = o["grafias"]
    return d


# ── Cobertura por partição (o que a base realmente contém) ────────────────────
def cobertura(conn) -> dict:
    """Lê controle_carga e devolve a cobertura por (fonte, ano, mês): o que falta,
    o que veio com erro/suspeita e o que teve duplicidade sistemática na origem.
    Substitui a guarda única 'total > R$ 4 bi' do workflow."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(controle_carga)")}
    v2 = "status" in cols
    hoje = date.today()
    esperadas = [(f, a, m) for f in FONTES for a in range(ANO_INICIAL, hoje.year + 1)
                 for m in range(1, 13) if (a, m) <= (hoje.year, hoje.month)]
    part = {}
    sql = ("SELECT fonte, ano, mes, registros, soma, baixado_em, brutos, descartados, soma_descartada, "
           "duplicidade, status, erro, tentado_em FROM controle_carga") if v2 else \
          "SELECT fonte, ano, mes, registros, soma, baixado_em FROM controle_carga"
    for r in _q(conn, sql):
        d = dict(r)
        if not v2:
            d.update(brutos=None, descartados=0, soma_descartada=0, duplicidade=None,
                     status="ok", erro=None, tentado_em=d["baixado_em"])
        if d["duplicidade"]:
            try:
                diag = json.loads(d["duplicidade"])
            except ValueError:
                diag = {}
            d["duplicidade"] = {"identicas": diag.get("identicas", 0),
                                "sistematica": bool(diag.get("sistematica")) or bool(diag.get("particao")),
                                "dias_sistematicos": len(diag.get("sistematica") or []),
                                "particao": diag.get("particao")}
        part[(d["fonte"], d["ano"], d["mes"])] = d
    faltantes = [f"{f} {a}-{m:02d}" for (f, a, m) in esperadas
                 if (f, a, m) not in part or not part[(f, a, m)].get("baixado_em")]
    com_erro = [f"{d['fonte']} {d['ano']}-{d['mes']:02d}: {d['status']} — {d['erro']}"
                for d in part.values() if d.get("status") not in (None, "ok")]
    duplicadas = [f"{d['fonte']} {d['ano']}-{d['mes']:02d}" for d in part.values()
                  if d.get("duplicidade") and d["duplicidade"]["sistematica"]]
    lista = [{"fonte": d["fonte"], "ano": d["ano"], "mes": d["mes"], "registros": d["registros"],
              "soma": round(d["soma"] or 0, 2), "baixado_em": d["baixado_em"],
              "brutos": d["brutos"], "descartados": d["descartados"] or 0,
              "soma_descartada": round(d["soma_descartada"] or 0, 2),
              "duplicidade": d["duplicidade"], "status": d["status"], "erro": d["erro"],
              "tentado_em": d["tentado_em"]}
             for d in sorted(part.values(), key=lambda x: (x["ano"], x["mes"], x["fonte"]))]
    return {"esquema": 2 if v2 else 1, "particoes": lista, "faltantes": faltantes,
            "com_erro": com_erro, "duplicidade_sistematica": duplicadas,
            "integra": not faltantes and not com_erro}


def _particoes_ok(cob: dict) -> set:
    return {(p["fonte"], p["ano"], p["mes"]) for p in cob["particoes"] if p["baixado_em"]}


DEFASAGEM_DIAS = 15   # o portal publica pagamentos com semanas de atraso (ago/2026 tinha 2/3 do
                      # volume típico com a base em 10/09): um mês só é "completo" quando a
                      # data mais recente da base passa do fim dele por esta folga


def _mes_completo_ate(conn) -> tuple[int, int] | None:
    """Último mês COMPLETO da base (ano, mês): o último cujo fim está a mais de
    DEFASAGEM_DIAS da data de pagamento mais recente. Meses depois dele são parciais
    e ficam fora de comparações (YoY, picos, resumo)."""
    m = _q(conn, "SELECT MAX(data) m FROM pagamentos WHERE data <> ''")[0]["m"]
    if not m:
        return None
    try:
        ate = date.fromisoformat(m[:10])
    except ValueError:
        return None
    from datetime import timedelta
    limite = ate - timedelta(days=DEFASAGEM_DIAS)
    # o último mês inteiramente anterior a `limite`
    a, mes = limite.year, limite.month
    return (a, mes - 1) if mes > 1 else (a - 1, 12)


# ── Conciliação com o TCE-SP (AUDESP): mês incompleto na origem (2026-10) ──────
# despesas/tce.py grava os totais mensais que o município enviou ao Tribunal; aqui a
# base é comparada com eles. Nos meses íntegros o empenhado (originais + reforços −
# anulações) bate ao centavo e o liquidado SEM restos a pagar (o TCE conta só o do
# exercício) fica a ≤ 3%. Base abaixo do TCE além de TCE_LIMITE (e de TCE_PISO) = mês
# INCOMPLETO NA ORIGEM: sai das comparações (acumulado do ano, crescimento, picos, fim
# de exercício, valor mensal típico de PF) e vira alerta de dados. O dado do TCE não
# preenche a base (decisão do usuário, 2026-10-30). Base ACIMA do TCE fica só como
# status informativo ("acima"): o TCE também recebe o mês aos poucos.
CONCILIACAO_TCE_PATH = os.path.join(AQUI, "conciliacao-tce.json")
TCE_LIMITE = 0.05
TCE_PISO = 1_000_000


def _ler_conciliacao_tce(caminho: str | None = None) -> dict:
    try:
        with open(caminho or CONCILIACAO_TCE_PATH, encoding="utf-8") as f:
            return json.load(f).get("meses") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def conciliacao_tce(conn, meses_tce: dict | None = None) -> dict:
    """Mês a mês, base × TCE-SP. status: ok, incompleto (base abaixo), acima (base acima,
    informativo), sem_referencia (o TCE ainda não tem o mês) ou parcial (posterior ao
    último mês completo — os dois lados ainda estão publicando)."""
    meses_tce = _ler_conciliacao_tce() if meses_tce is None else meses_tce
    completo = _mes_completo_ate(conn)
    p_completo = completo[0] * 100 + completo[1] if completo else None
    base: dict[tuple, dict] = defaultdict(lambda: {"empenhado": 0.0, "liquidado": 0.0})
    for r in _q(conn, "SELECT ano, mes, SUM(valor) s FROM empenhos GROUP BY ano, mes"):
        base[(r["ano"], r["mes"])]["empenhado"] = r["s"] or 0
    for r in _q(conn, "SELECT ano, mes, tipo_liquidacao t, SUM(valor) s FROM liquidacoes GROUP BY ano, mes, t"):
        t = sem_acento(r["t"] or "").upper()
        if "RESTOS" not in t and "EXTRA" not in t:
            base[(r["ano"], r["mes"])]["liquidado"] += r["s"] or 0
    meses = []
    for ano, mes in sorted(base):
        per = f"{ano}-{mes:02d}"
        b = {c: round(v, 2) for c, v in base[(ano, mes)].items()}
        t = meses_tce.get(per)
        item = {"periodo": per, "base": b}
        if p_completo and ano * 100 + mes > p_completo:
            item["status"] = "parcial"
        elif not t:
            item["status"] = "sem_referencia"
        else:
            item["tce"] = {c: t.get(c) for c in ("empenhado", "liquidado", "pago")}
            item["tce_obtido_em"] = t.get("obtido_em")
            dif, abaixo, acima = {}, False, False
            for c in ("empenhado", "liquidado"):
                ref = t.get(c) or 0
                d = b[c] - ref
                dif[c] = round(100 * d / ref, 2) if ref else None
                margem = max(TCE_PISO, TCE_LIMITE * abs(ref))
                abaixo = abaixo or d < -margem
                acima = acima or d > margem
            item["dif_pct"] = dif
            item["status"] = "incompleto" if abaixo else ("acima" if acima else "ok")
        meses.append(item)
    return {"fonte": "TCE-SP (AUDESP), sem a Câmara — despesas/conciliacao-tce.json",
            "criterio": (f"empenhado e liquidado sem restos a pagar; abaixo do TCE em mais de "
                         f"{TCE_LIMITE:.0%} (e de {brl(TCE_PISO)}) = incompleto na origem"),
            "meses": meses,
            "incompletos": [m["periodo"] for m in meses if m["status"] == "incompleto"],
            "acima": [m["periodo"] for m in meses if m["status"] == "acima"]}


def cobertura_conciliada(conn, meses_tce: dict | None = None) -> dict:
    """cobertura() + a conciliação com o TCE-SP (`conciliacao_tce`, `incompletos_origem`):
    a MESMA leitura no export e no briefing — painel e e-mail excluem os mesmos meses."""
    cob = cobertura(conn)
    cob["conciliacao_tce"] = conciliacao_tce(conn, meses_tce)
    cob["incompletos_origem"] = cob["conciliacao_tce"]["incompletos"]
    return cob


def _incompletos(cob: dict | None) -> set:
    """{(ano, mês)} dos meses incompletos na origem (cobertura.incompletos_origem)."""
    return {(int(p[:4]), int(p[5:7])) for p in ((cob or {}).get("incompletos_origem") or [])}


def _rotulo_meses(meses) -> str:
    """[(2025, 1), (2025, 2)] → 'jan–fev/2025'; trechos não contíguos (ou de outro ano)
    separados por vírgula."""
    trechos = []
    for a, m in sorted(meses):
        if trechos and trechos[-1][0] == a and m == trechos[-1][2] + 1:
            trechos[-1][2] = m
        else:
            trechos.append([a, m, m])
    return ", ".join(f"{MESES_ABREV[i - 1]}{'–' + MESES_ABREV[f - 1] if f != i else ''}/{a}" for a, i, f in trechos)


def _rotulo_periodo(meses: list[int]) -> str:
    """Meses de um ano ([3, 4, …, 9]) → 'mar–set'; trechos não contíguos separados por vírgula."""
    trechos = []
    for m in sorted(meses):
        if trechos and m == trechos[-1][1] + 1:
            trechos[-1][1] = m
        else:
            trechos.append([m, m])
    return ", ".join(MESES_ABREV[i - 1] + (f"–{MESES_ABREV[f - 1]}" if f != i else "") for i, f in trechos)


# ── Agregações para o painel (movimentação de PAGAMENTOS pela data) ──────────
FONTE_EXTRA = "Extra-orçamentário (retenções e consignações)"


def agregados(conn, ident: dict | None = None, contratos: dict | None = None) -> dict:
    ident = ident if ident is not None else preparar_identidades(conn)
    contratos = contratos or {}
    total = _q(conn, "SELECT COALESCE(SUM(valor),0) s, COUNT(*) n FROM pagamentos")[0]
    anos = _q(conn, "SELECT ano, SUM(valor) s, COUNT(*) n FROM pagamentos GROUP BY ano ORDER BY ano")
    minmax = _q(conn, "SELECT MIN(ano*100+mes) a, MAX(ano*100+mes) b FROM pagamentos")[0]
    dados_ate = _q(conn, "SELECT MAX(data) m FROM pagamentos WHERE data <> ''")[0]["m"]

    def per(a):
        a = int(a); return f"{a//100}-{a%100:02d}"

    series = _q(conn,
        "SELECT ano, mes, SUM(valor) s FROM pagamentos GROUP BY ano, mes ORDER BY ano, mes")
    por_funcao = _q(conn,
        "SELECT COALESCE(NULLIF(funcao,''),'(sem função)') k, SUM(valor) s, COUNT(*) n "
        "FROM pagamentos GROUP BY k ORDER BY s DESC")
    por_elemento = _q(conn,
        "SELECT COALESCE(NULLIF(elemento_despesa,''),'(sem elemento)') k, SUM(valor) s, COUNT(*) n "
        "FROM pagamentos GROUP BY k ORDER BY s DESC LIMIT 50")
    # extra-orçamentário numa linha só: a origem o grava SEM o prefixo do grupo de fonte
    # ("1100000 - GERAL" × "01-1100000 - GERAL"), o que parecia fonte duplicada no gráfico
    por_fonte = _q(conn,
        f"SELECT CASE WHEN tipo_pagamento LIKE '%Extra%' THEN '{FONTE_EXTRA}' "
        "ELSE COALESCE(NULLIF(fonte_recurso,''),'(sem fonte)') END k, SUM(valor) s "
        "FROM pagamentos GROUP BY k ORDER BY s DESC LIMIT 50")
    # "para onde vai o dinheiro" (De cada R$ 100, recibo) só com o ORÇAMENTÁRIO: retenções
    # e consignações extra-orçamentárias só transitam pelo caixa
    por_funcao_orc = _q(conn,
        "SELECT COALESCE(NULLIF(funcao,''),'(sem função)') k, SUM(valor) s FROM pagamentos "
        "WHERE COALESCE(tipo_pagamento,'') NOT LIKE '%Extra%' GROUP BY k ORDER BY s DESC")
    # programa do PPA (o "para quê"): temático, não mapeia 1:1 para secretaria
    por_programa = _q(conn,
        "SELECT COALESCE(NULLIF(programa,''),'(sem programa)') k, SUM(valor) s FROM pagamentos "
        "WHERE COALESCE(tipo_pagamento,'') NOT LIKE '%Extra%' GROUP BY k ORDER BY s DESC LIMIT 15")
    por_unidade = _q(conn,
        "SELECT unidade_gestora k, SUM(valor) s FROM pagamentos GROUP BY k ORDER BY s DESC")
    # favorecidos consolidados por IDENTIDADE (CNPJ completo; CPF mascarado só com o mesmo nome)
    favorecidos = _q(conn,
        f"SELECT fi.chave k, SUM(p.valor) s, COUNT(*) n, COUNT(DISTINCT p.ano*100+p.mes) meses "
        f"FROM pagamentos p {FAV_JOIN.format(t='p')} GROUP BY fi.chave ORDER BY s DESC LIMIT ?",
        TOP_FAVORECIDOS)
    n_fav = _q(conn, f"SELECT COUNT(DISTINCT fi.chave) n FROM pagamentos p {FAV_JOIN.format(t='p')}")[0]["n"]
    n_grafias = _q(conn, "SELECT COUNT(DISTINCT nome_favorecido) n FROM pagamentos")[0]["n"]

    # serviço da dívida (consumido pelo painel de Endividamento): grupos
    # 32 = juros e encargos, 46 = amortização/refinanciamento (rótulos variam;
    # o código no prefixo do grupo é estável). Credores por identidade.
    FILTRO_DIVIDA = ("(grupo_despesa LIKE '32%' OR grupo_despesa LIKE '46%')")
    divida_anos = _q(conn,
        f"SELECT ano, SUBSTR(grupo_despesa,1,2) g, SUM(valor) s FROM pagamentos "
        f"WHERE {FILTRO_DIVIDA} GROUP BY ano, g ORDER BY ano")
    divida_credores = _q(conn,
        f"SELECT fi.chave k, SUM(p.valor) s, COUNT(*) n FROM pagamentos p {FAV_JOIN.format(t='p')} "
        f"WHERE {FILTRO_DIVIDA} AND p.nome_favorecido NOT LIKE '%IPAM%' "
        f"GROUP BY fi.chave ORDER BY s DESC LIMIT 10")

    # série mensal desagregada por função (consumida pelo painel de indicadores)
    serie_funcao = _q(conn,
        "SELECT ano, mes, COALESCE(NULLIF(funcao,''),'(sem função)') f, SUM(valor) s "
        "FROM pagamentos GROUP BY ano, mes, f ORDER BY ano, mes, s DESC")

    return {
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "versao_export": 2,       # 2 = identidade consolidada + duas visões + cobertura (2026-09)
        "dados_ate": dados_ate,   # data do pagamento mais recente (aviso de atualidade)
        "periodo": {"de": per(minmax["a"]) if minmax["a"] else None,
                    "ate": per(minmax["b"]) if minmax["b"] else None},
        "totais": {
            "geral": round(total["s"], 2),
            "pagamentos": total["n"],
            "favorecidos": n_fav,            # identidades distintas
            "grafias_favorecidos": n_grafias,  # nomes distintos (informativo)
            "por_ano": {str(r["ano"]): round(r["s"], 2) for r in anos},
        },
        "series_mensais": [{"ano": r["ano"], "mes": r["mes"], "valor": round(r["s"], 2)} for r in series],
        "series_mensais_por_funcao": [
            {"ano": r["ano"], "mes": r["mes"], "funcao": r["f"], "valor": round(r["s"], 2)}
            for r in serie_funcao
        ],
        "por_funcao": [{"funcao": r["k"], "valor": round(r["s"], 2), "qtd": r["n"]} for r in por_funcao],
        "por_elemento": [{"elemento": r["k"], "valor": round(r["s"], 2), "qtd": r["n"]} for r in por_elemento],
        "por_fonte": [{"fonte": r["k"], "valor": round(r["s"], 2)} for r in por_fonte],
        "por_funcao_orcamentario": [{"funcao": r["k"], "valor": round(r["s"], 2)} for r in por_funcao_orc],
        "por_programa": [{"programa": r["k"], "valor": round(r["s"], 2)} for r in por_programa],
        "por_unidade": [{"unidade": r["k"], "valor": round(r["s"], 2)} for r in por_unidade],
        "top_favorecidos": [_contagem_instrumentos(_marcar_ente_publico(
            dict(_fav_campos(ident, r["k"]), valor=round(r["s"], 2), qtd=r["n"], meses=r["meses"])), contratos)
            for r in favorecidos
        ],
        "servico_divida": {
            "por_ano": [
                {"ano": r["ano"],
                 "tipo": "juros" if r["g"] == "32" else "amortizacao",
                 "valor": round(r["s"], 2)} for r in divida_anos
            ],
            "credores": [
                {"nome": _fav_campos(ident, r["k"])["nome"], "valor": round(r["s"], 2), "qtd": r["n"]}
                for r in divida_credores
            ],
        },
    }


# ── Classificação das linhas ──────────────────────────────────────────────────
def exercicio_do_empenho(numero) -> int | None:
    """'0000123/2024' → 2024. Sem sufixo de ano → None."""
    m = re.search(r"/(\d{4})\s*$", str(numero or ""))
    return int(m.group(1)) if m else None


def classificar_documento(tipo_fonte, empenho, na_base: bool) -> str:
    """Tipo de uma liquidação/pagamento a partir do CAMPO DA FONTE (tipo_pagamento /
    tipo_liquidacao) e da presença do empenho na base. A ausência de nº de empenho,
    sozinha, não classifica nada; o exercício do nº de empenho, sozinho, também não."""
    t = sem_acento(tipo_fonte or "")
    if "EXTRA" in t:
        return T_EXTRA
    if "RESTOS" in t:
        return T_RESTOS
    if not empenho:
        return T_NAO_LOCALIZADO          # orçamentário sem nº — não dá para localizar
    return T_ORCAMENTARIO if na_base else T_NAO_LOCALIZADO


def _empenhos_na_base(conn) -> tuple[set, set]:
    """(chaves 'UG|nº' de todos os empenhos da base, chaves dos que têm linha Original)."""
    todos, originais = set(), set()
    for r in _q(conn, "SELECT unidade_gestora ug, empenho e, "
                      "SUM(CASE WHEN especie='Original' OR especie IS NULL OR especie='' THEN 1 ELSE 0 END) o "
                      "FROM empenhos GROUP BY ug, e"):
        k = f"{r['ug']}|{r['e']}"
        todos.add(k)
        if r["o"]:
            originais.add(k)
    return todos, originais


# ── Execução agregada (empenhado → liquidado → pago) ──────────────────────────
# Séries e taxas com os TRÊS estágios. As anulações vêm da API com valor NEGATIVO
# (espécie "Anulação"), então SUM(valor) já devolve o líquido. Meses sem partição
# carregada de um estágio ficam com null (desconhecido ≠ zero).
def execucao_agregada(conn, cob: dict | None = None) -> dict:
    cob = cob or cobertura(conn)
    ok = _particoes_ok(cob)
    tem_controle = bool(cob["particoes"])
    serie: dict[int, dict] = {}

    def acumular(tabela, campo):
        for r in _q(conn, f"SELECT ano, mes, ROUND(SUM(valor),2) s FROM {tabela} GROUP BY ano, mes"):
            p = r["ano"] * 100 + r["mes"]
            serie.setdefault(p, {"ano": r["ano"], "mes": r["mes"]})[campo] = r["s"]

    acumular("empenhos", "empenhado")
    acumular("liquidacoes", "liquidado")
    acumular("pagamentos", "pago")

    # classificação do pago de cada mês pelo campo da fonte + presença do empenho na base
    todos, _ = _empenhos_na_base(conn)
    for r in _q(conn, """
        SELECT ano, mes, unidade_gestora ug, empenho, tipo_pagamento tp, ROUND(SUM(valor),2) s
        FROM pagamentos GROUP BY ano, mes, ug, empenho, tp"""):
        p = r["ano"] * 100 + r["mes"]
        if p not in serie:
            continue
        na_base = f"{r['ug']}|{r['empenho']}" in todos
        tipo = classificar_documento(r["tp"], r["empenho"], na_base)
        campo = {T_EXTRA: "extra", T_RESTOS: "restos", T_NAO_LOCALIZADO: "nao_localizado"}.get(tipo)
        if campo:
            serie[p][campo] = round(serie[p].get(campo, 0) + r["s"], 2)

    linhas = [serie[p] for p in sorted(serie)]
    for l in linhas:
        for tabela, c in (("empenhos", "empenhado"), ("liquidacoes", "liquidado"), ("pagamentos", "pago")):
            if c not in l:
                # sem partição carregada → desconhecido (null); carregada e vazia → 0
                l[c] = 0 if (not tem_controle or (tabela, l["ano"], l["mes"]) in ok) else None
        for c in ("restos", "extra", "nao_localizado"):
            l.setdefault(c, 0)

    # totais por ano (movimentação de cada estágio pela própria data)
    por_ano: dict[str, dict] = {}
    for l in linhas:
        a = por_ano.setdefault(str(l["ano"]), {"empenhado": 0, "liquidado": 0, "pago": 0,
                                               "restos": 0, "extra": 0, "nao_localizado": 0})
        for c in ("empenhado", "liquidado", "pago", "restos", "extra", "nao_localizado"):
            if l[c] is None:
                a[c] = None if a[c] in (0, None) and not any(x[c] for x in linhas if x["ano"] == l["ano"] and x[c]) else a[c]
            elif a[c] is not None:
                a[c] = round(a[c] + l[c], 2)

    # Taxa de execução por ano DO EMPENHO, calculada só sobre os empenhos cujo
    # ORIGINAL está na base (empenho cujo original não veio — em 2025, os globais de
    # jan/2025, mês incompleto na origem — entra só como anulação/reforço e
    # subcontaria o denominador). A taxa é publicada como validada apenas quando:
    # cobertura dos 3 estágios completa para o ano (inclusive sem mês incompleto na
    # origem), denominador > 0 e liquidado ≤ empenhado, pago ≤ liquidado.
    # Caso contrário publica os números brutos + motivos, nunca um teto de 100%.
    hoje = date.today()
    incompletos = _incompletos(cob)
    for r in _q(conn, """
        SELECT e.ano,
               ROUND(SUM(CASE WHEN e.originais > 0 THEN e.empenhado ELSE 0 END),2) emp,
               ROUND(SUM(CASE WHEN e.originais > 0 THEN COALESCE(l.liquidado,0) ELSE 0 END),2) liq,
               ROUND(SUM(CASE WHEN e.originais > 0 THEN COALESCE(p.pago,0) ELSE 0 END),2) pago,
               ROUND(SUM(e.empenhado),2) emp_total,
               SUM(CASE WHEN e.originais = 0 THEN 1 ELSE 0 END) n_sem_original,
               ROUND(SUM(CASE WHEN e.originais = 0 THEN COALESCE(p.pago,0) ELSE 0 END),2) pago_sem_original,
               COUNT(*) n_empenhos
        FROM (SELECT unidade_gestora, empenho, MIN(ano) ano, ROUND(SUM(valor),2) empenhado,
                     SUM(CASE WHEN especie='Original' OR especie IS NULL OR especie='' THEN 1 ELSE 0 END) originais
              FROM empenhos GROUP BY unidade_gestora, empenho) e
        LEFT JOIN (SELECT unidade_gestora, empenho, ROUND(SUM(valor),2) liquidado
                   FROM liquidacoes GROUP BY unidade_gestora, empenho) l
          ON l.unidade_gestora = e.unidade_gestora AND l.empenho = e.empenho
        LEFT JOIN (SELECT unidade_gestora, empenho, ROUND(SUM(valor),2) pago
                   FROM pagamentos WHERE empenho IS NOT NULL AND empenho <> ''
                   GROUP BY unidade_gestora, empenho) p
          ON p.unidade_gestora = e.unidade_gestora AND p.empenho = e.empenho
        GROUP BY e.ano"""):
        a = por_ano.get(str(r["ano"]))
        if not a:
            continue
        motivos = []
        emp, liq, pago = r["emp"] or 0, r["liq"] or 0, r["pago"] or 0
        ano = r["ano"]
        ult_mes = 12 if ano < hoje.year else hoje.month
        if tem_controle:
            faltam = [f"{f} {ano}-{m:02d}" for f in FONTES for m in range(1, ult_mes + 1)
                      if (f, ano, m) not in ok]
            if faltam:
                motivos.append(f"cobertura incompleta ({len(faltam)} partições sem carga: "
                               f"{', '.join(faltam[:4])}{'…' if len(faltam) > 4 else ''})")
        inc_ano = sorted(k for k in incompletos if k[0] == ano)
        if inc_ano:
            motivos.append(f"{_rotulo_meses(inc_ano)} {'incompletos' if len(inc_ano) > 1 else 'incompleto'} na "
                           f"origem, conferido com o TCE-SP — os empenhos emitidos no período não vieram e a "
                           f"taxa cobre só parte do exercício")
        if emp <= 0:
            motivos.append(f"empenhado líquido dos empenhos íntegros é nulo ou negativo ({brl(emp)})")
        else:
            if liq > emp * 1.0001:
                motivos.append(f"liquidado ({brl(liq)}) supera o empenhado ({brl(emp)})")
            if pago > liq * 1.0001:
                motivos.append(f"pago ({brl(pago)}) supera o liquidado ({brl(liq)})")
            if pago > emp * 1.0001:
                motivos.append(f"pago ({brl(pago)}) supera o empenhado ({brl(emp)})")
        a["base_taxa"] = {
            "empenhos": r["n_empenhos"], "sem_original": r["n_sem_original"],
            "pago_sem_original": r["pago_sem_original"] or 0,
            "empenhado_integro": emp, "liquidado_integro": liq, "pago_integro": pago,
            "cobertura_pct": round(100 * emp / r["emp_total"], 1) if r["emp_total"] and emp > 0 and r["emp_total"] > 0 else None,
        }
        if emp > 0:
            a["taxas_brutas"] = {"liquidacao": round(100 * liq / emp, 1), "pagamento": round(100 * pago / emp, 1)}
        a["taxa_validada"] = not motivos
        if motivos:
            a["taxa_motivos"] = motivos
            if pago > emp > 0:
                a["empenho_incompleto"] = True   # compatibilidade com o painel antigo
        else:
            a["taxa_liquidacao"] = round(100 * liq / emp, 1)
            a["taxa_pagamento"] = round(100 * pago / emp, 1)

    # tríade por função (top 12 pelo empenhado)
    fn: dict[str, dict] = {}
    for tabela, campo in (("empenhos", "empenhado"), ("liquidacoes", "liquidado"),
                          ("pagamentos", "pago")):
        for r in _q(conn,
            f"SELECT COALESCE(NULLIF(funcao,''),'(sem função)') k, ROUND(SUM(valor),2) s "
            f"FROM {tabela} GROUP BY k"):
            fn.setdefault(r["k"], {"funcao": r["k"]})[campo] = r["s"]
    por_funcao = sorted(fn.values(), key=lambda x: -(x.get("empenhado") or 0))[:12]
    for f in por_funcao:
        for c in ("empenhado", "liquidado", "pago"):
            f.setdefault(c, 0)

    return {"serie": linhas, "por_ano": por_ano, "por_funcao": por_funcao}


# ── Resumo narrativo ("Em resumo") ────────────────────────────────────────────
# Texto determinístico (sem IA) exibido no topo do painel: último mês completo vs
# média móvel, função que mais variou, acumulado do ano vs mesmo período anterior
# e alertas ativos. Frases montadas por template — auditável e sem custo de token.
MESES_NOME = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
              "agosto", "setembro", "outubro", "novembro", "dezembro"]
MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


# ── Prazo entre liquidação e pagamento (ordem cronológica — art. 141 da Lei 14.133) ──
# Pagamento ORÇAMENTÁRIO casado com a liquidação pelo trio (UG, empenho, nº da liquidação).
# Extra-orçamentário fica fora (retenção não entra na fila); restos a pagar ficam.
PRAZO_FAIXAS = [(None, -1, "antes da liquidação"), (0, 1, "até 1 dia"), (2, 7, "2 a 7 dias"),
                (8, 30, "8 a 30 dias"), (31, 90, "31 a 90 dias"), (91, None, "mais de 90 dias")]
PRAZO_MIN_PAGS = 10          # favorecido com ao menos N pagamentos casados
PRAZO_MIN_VALOR = 1_000_000  # ...e ao menos isto pago nesses pagamentos
PRAZO_RAPIDO_DIAS = 1        # mediana ≤ isto (com a mediana geral ≥ PRAZO_GERAL_MIN) → triagem
PRAZO_GERAL_MIN = 5
PRAZO_LENTO_DIAS = 60        # mediana ≥ isto → atraso a conferir


def _mediana(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _pares_liq_pag(conn) -> list:
    return _q(conn, f"""
        SELECT fi.chave k, p.ano, p.valor v,
               CAST(ROUND(julianday(p.data) - julianday(l.data)) AS INTEGER) d
        FROM pagamentos p {FAV_JOIN.format(t='p')}
        JOIN (SELECT unidade_gestora, empenho, liquidacao, MIN(data) data FROM liquidacoes
              WHERE COALESCE(especie,'') NOT LIKE 'Anula%' GROUP BY 1, 2, 3) l
          ON l.unidade_gestora = p.unidade_gestora AND l.empenho = p.empenho AND l.liquidacao = p.liquidacao
        WHERE COALESCE(p.tipo_pagamento,'') NOT LIKE '%Extra%' AND p.valor > 0
          AND COALESCE(p.especie,'') NOT LIKE 'Anula%' AND COALESCE(p.liquidacao,'') <> ''""")


def prazos_pagamento(conn, ident: dict) -> dict:
    """Distribuição dos dias entre liquidação e pagamento por ano e os favorecidos
    (fornecedores) mais rápidos e mais lentos. `_linhas` (todos os favorecidos elegíveis)
    alimenta as regras de alerta e sai do índice antes de gravar."""
    pares = _pares_liq_pag(conn)
    por_ano = {}
    for ano in sorted({r["ano"] for r in pares}):
        rs = [r for r in pares if r["ano"] == ano]
        ds = [r["d"] for r in rs]
        faixas = []
        for a, b, rot in PRAZO_FAIXAS:
            sel = [r for r in rs if (a is None or r["d"] >= a) and (b is None or r["d"] <= b)]
            faixas.append({"faixa": rot, "qtd": len(sel), "valor": round(sum(r["v"] for r in sel), 2)})
        por_ano[str(ano)] = {"pagamentos": len(rs), "valor": round(sum(r["v"] for r in rs), 2),
                             "mediana_dias": _mediana(ds), "p90_dias": sorted(ds)[int(0.9 * (len(ds) - 1))],
                             "faixas": faixas}
    por_fav = defaultdict(list)
    for r in pares:
        por_fav[r["k"]].append(r)
    linhas = []
    for k, rs in por_fav.items():
        f = _fav_campos(ident, k)
        valor = sum(r["v"] for r in rs)
        if len(rs) < PRAZO_MIN_PAGS or valor < PRAZO_MIN_VALOR or eh_ente_publico(f["nome"]):
            continue
        linhas.append({**f, "mediana_dias": _mediana([r["d"] for r in rs]), "pagamentos": len(rs),
                       "valor": round(valor, 2)})
    geral = _mediana([r["d"] for r in pares])
    return {
        "mediana_geral_dias": geral,
        "casados": len(pares),
        "por_ano": por_ano,
        "mais_rapidos": sorted(linhas, key=lambda x: (x["mediana_dias"], -x["valor"]))[:10],
        "mais_lentos": sorted(linhas, key=lambda x: (-x["mediana_dias"], -x["valor"]))[:10],
        "criterio": (f"Pagamentos orçamentários (inclui restos a pagar) casados com a liquidação por UG, "
                     f"empenho e nº da liquidação; fornecedores com ≥ {PRAZO_MIN_PAGS} pagamentos e "
                     f"≥ {brl(PRAZO_MIN_VALOR)}; entes públicos fora."),
        "_linhas": linhas,
    }


# ── Anulações de empenho ──────────────────────────────────────────────────────
def anulacoes_empenho(conn, ident: dict, cob: dict | None = None) -> dict:
    """Quanto do empenhado foi anulado, por mês e por favorecido (valores POSITIVOS;
    a origem grava a anulação negativa). Ano com mês incompleto na origem não tem % do
    empenhado: as anulações chegam, os originais do mês faltante não."""
    incompletos = _incompletos(cob)
    serie = [{"ano": r["ano"], "mes": r["mes"], "qtd": r["n"], "valor": round(-r["s"], 2)} for r in _q(conn,
        "SELECT ano, mes, COUNT(*) n, SUM(valor) s FROM empenhos WHERE especie LIKE 'Anula%' "
        "GROUP BY ano, mes ORDER BY ano, mes")]
    emp_ano = {r["ano"]: r["s"] for r in _q(conn,
        "SELECT ano, SUM(valor) s FROM empenhos WHERE COALESCE(especie,'') NOT LIKE 'Anula%' GROUP BY ano")}
    por_ano = {}
    for s in serie:
        a = por_ano.setdefault(str(s["ano"]), {"qtd": 0, "valor": 0.0})
        a["qtd"] += s["qtd"]
        a["valor"] = round(a["valor"] + s["valor"], 2)
    for ano, a in por_ano.items():
        base = emp_ano.get(int(ano)) or 0
        inc_ano = sorted(k for k in incompletos if k[0] == int(ano))
        a["pct_do_empenhado"] = round(100 * a["valor"] / base, 1) if base > 0 and not inc_ano else None
        if inc_ano:
            a["incompleto_origem"] = [f"{y}-{m:02d}" for y, m in inc_ano]
    top = []
    for r in _q(conn, f"""
            SELECT fi.chave k, COUNT(*) n, -SUM(e.valor) s FROM empenhos e {FAV_JOIN.format(t='e')}
            WHERE e.especie LIKE 'Anula%' GROUP BY fi.chave ORDER BY s DESC LIMIT 15"""):
        emp = _q(conn, f"""SELECT SUM(e.valor) s FROM empenhos e {FAV_JOIN.format(t='e')}
                          WHERE fi.chave=? AND COALESCE(e.especie,'') NOT LIKE 'Anula%'""", r["k"])[0]["s"] or 0
        # anulado > empenhado na base = o original é anterior a jan/2025 (fora da base):
        # a razão não tem sentido e vira a marca original_fora_da_base
        fora = not emp or r["s"] > emp
        item = {**_fav_campos(ident, r["k"]), "anulacoes": r["n"], "valor": round(r["s"], 2),
                "pct_do_empenhado": None if fora else round(100 * r["s"] / emp, 1)}
        if fora:
            item["original_fora_da_base"] = True
        top.append(_marcar_ente_publico(item))
    return {"serie": serie, "por_ano": por_ano, "top_favorecidos": top}


# ── Fim de exercício: dezembro × média jan–nov ────────────────────────────────
def fim_de_exercicio(conn, cob: dict | None = None) -> dict:
    """Para cada ano com dezembro COMPLETO: empenhado (originais), liquidado, pago e
    anulado em dezembro contra a média mensal de jan–nov (razão). Corrida de liquidação
    e cancelamento de saldos no encerramento aparecem aqui. Mês incompleto na origem
    fica fora da média (`meses_excluidos`); dezembro incompleto tira o ano."""
    incompletos = _incompletos(cob)
    completo = _mes_completo_ate(conn)
    p_completo = completo[0] * 100 + completo[1] if completo else 0
    medidas = {
        "empenhado": "SELECT ano, mes, SUM(valor) s FROM empenhos WHERE COALESCE(especie,'') NOT LIKE 'Anula%' "
                     "AND COALESCE(especie,'') NOT LIKE 'Refor%' GROUP BY ano, mes",
        "liquidado": "SELECT ano, mes, SUM(valor) s FROM liquidacoes GROUP BY ano, mes",
        "pago": "SELECT ano, mes, SUM(valor) s FROM pagamentos GROUP BY ano, mes",
        "anulado": "SELECT ano, mes, -SUM(valor) s FROM empenhos WHERE especie LIKE 'Anula%' GROUP BY ano, mes",
    }
    vals = {m: {(r["ano"], r["mes"]): r["s"] or 0 for r in _q(conn, sql)} for m, sql in medidas.items()}
    out = {}
    for ano in sorted({a for (a, _m) in vals["pago"]}):
        if ano * 100 + 12 > p_completo or (ano, 12) in incompletos:
            continue
        meses = [k for k in range(1, 12) if (ano, k) not in incompletos]
        if not meses:
            continue
        linha = {}
        for m, v in vals.items():
            media = sum(v.get((ano, k), 0) for k in meses) / len(meses)
            dez = v.get((ano, 12), 0)
            linha[m] = {"dezembro": round(dez, 2), "media_jan_nov": round(media, 2),
                        "razao": round(dez / media, 2) if media else None}
        if len(meses) < 11:
            linha["meses_excluidos"] = [f"{ano}-{k:02d}" for k in range(1, 12) if k not in meses]
        out[str(ano)] = linha
    return out


def resumo_narrativo(conn, indice: dict) -> dict | None:
    series = indice.get("series_mensais") or []
    if len(series) < 3:
        return None

    # último mês COMPLETO (critério único de _mes_completo_ate: fim do mês + defasagem
    # do portal); os meses posteriores são parciais e não servem de referência
    completo = _mes_completo_ate(conn)
    idx = len(series) - 1
    if completo:
        p_lim = completo[0] * 100 + completo[1]
        while idx > 0 and series[idx]["ano"] * 100 + series[idx]["mes"] > p_lim:
            idx -= 1
    ref = series[idx]
    parciais = [f"{s['ano']}-{s['mes']:02d}" for s in series[idx + 1:]]
    # mês incompleto na origem (conciliação com o TCE-SP) não entra em comparação nenhuma
    inc = _incompletos(indice.get("cobertura"))

    # vs média dos até 12 meses anteriores comparáveis
    anteriores = [s for s in series[:idx] if (s["ano"], s["mes"]) not in inc][-12:]
    media = sum(s["valor"] for s in anteriores) / len(anteriores) if anteriores else None
    delta_media_pct = round((ref["valor"] - media) / media * 100) if media else None

    # função com maior variação absoluta vs o mês anterior
    destaque = None
    if idx >= 1 and (series[idx - 1]["ano"], series[idx - 1]["mes"]) not in inc:
        ant = series[idx - 1]
        rows = _q(conn, """
            SELECT COALESCE(NULLIF(funcao,''),'(sem função)') k,
                   SUM(CASE WHEN ano=? AND mes=? THEN valor ELSE 0 END) atual,
                   SUM(CASE WHEN ano=? AND mes=? THEN valor ELSE 0 END) anterior
            FROM pagamentos
            WHERE (ano=? AND mes=?) OR (ano=? AND mes=?)
            GROUP BY k""",
            ref["ano"], ref["mes"], ant["ano"], ant["mes"],
            ref["ano"], ref["mes"], ant["ano"], ant["mes"])
        difs = [(r["k"], (r["atual"] or 0) - (r["anterior"] or 0)) for r in rows]
        if difs:
            k, d = max(difs, key=lambda x: abs(x[1]))
            if abs(d) >= 1_000_000:  # só destaca variação relevante
                nome = re.sub(r"^\d+\s*-\s*", "", k).strip().capitalize()
                destaque = {"funcao": nome, "delta": round(d, 2)}

    # acumulado do ano (jan..mês de referência) vs mesmo período do ano anterior, só nos
    # meses comparáveis dos DOIS anos — `periodo` diz quais ("mar–set" se jan–fev caíram)
    yoy = None
    comp = [m for m in range(1, ref["mes"] + 1) if (ref["ano"], m) not in inc and (ref["ano"] - 1, m) not in inc]
    atual = sum(s["valor"] for s in series if s["ano"] == ref["ano"] and s["mes"] in comp)
    passado = sum(s["valor"] for s in series if s["ano"] == ref["ano"] - 1 and s["mes"] in comp)
    excluidos = sorted(k for k in inc if k[0] in (ref["ano"], ref["ano"] - 1) and k[1] <= ref["mes"])
    if passado and comp:
        yoy = {"atual": round(atual, 2), "anterior": round(passado, 2),
               "pct": round((atual - passado) / passado * 100), "periodo": _rotulo_periodo(comp)}
        if excluidos:
            yoy["excluidos"] = [f"{a}-{m:02d}" for a, m in excluidos]

    ativos = sum(1 for a in indice.get("alertas", []) if a.get("classe") != CLASSE_CONTEXTO)

    frases = []
    f1 = f"Em {MESES_NOME[ref['mes'] - 1]}, a Prefeitura pagou {_brl_compacto(ref['valor'])}"
    if delta_media_pct is not None and delta_media_pct != 0:
        f1 += (f" — {abs(delta_media_pct)}% "
               f"{'acima' if delta_media_pct > 0 else 'abaixo'} da média dos 12 meses anteriores")
    frases.append(f1 + ".")
    if destaque:
        sobe = destaque["delta"] > 0
        frases.append(f"{destaque['funcao']} teve a maior variação: "
                      f"{'+' if sobe else '−'}{_brl_compacto(abs(destaque['delta']))} "
                      f"em relação ao mês anterior.")
    if yoy:
        frases.append(f"No acumulado {'comparável ' if excluidos else ''}de {ref['ano']} ({yoy['periodo']}), "
                      f"o pago soma {_brl_compacto(yoy['atual'])}, "
                      f"{abs(yoy['pct'])}% {'acima' if yoy['pct'] >= 0 else 'abaixo'} "
                      f"do mesmo período de {ref['ano'] - 1}.")
    exe = (indice.get("execucao") or {}).get("por_ano", {}).get(str(ref["ano"]))
    if exe:
        partes = []
        if exe.get("taxa_pagamento") is not None:
            partes.append(f"Dos empenhos de {ref['ano']} com original na base, {exe['taxa_liquidacao']:.0f}% já foi "
                          f"liquidado e {exe['taxa_pagamento']:.0f}% pago")
        elif exe.get("taxa_motivos"):
            partes.append(f"A taxa de execução de {ref['ano']} não pôde ser validada "
                          f"({exe['taxa_motivos'][0]})")
        if exe.get("restos"):
            partes.append(f"{_brl_compacto(exe['restos'])} quitaram restos a pagar "
                          f"de exercícios anteriores")
        if partes:
            frases.append("; ".join(partes) + ".")
    if ativos:
        frases.append(f"Há {ativos} alertas para conferir (anomalias ou inconsistências de dados).")

    if parciais:
        varios = len(parciais) > 1
        frases.append(f"{'Os meses' if varios else 'O mês'} {', '.join(parciais)} ainda "
                      f"{'estão incompletos' if varios else 'está incompleto'} na origem e "
                      f"{'ficam' if varios else 'fica'} fora das comparações.")
    if inc:
        varios = len(inc) > 1
        frases.append(f"{_rotulo_meses(inc).capitalize()} {'foram publicados' if varios else 'foi publicado'} "
                      f"incompleto{'s' if varios else ''} pela Prefeitura (conferido com o TCE-SP) e "
                      f"{'ficam' if varios else 'fica'} fora das comparações.")
    return {
        "texto": " ".join(frases),
        "mes_ref": {"ano": ref["ano"], "mes": ref["mes"], "valor": ref["valor"]},
        "meses_parciais": parciais,
        "delta_media_pct": delta_media_pct,
        "funcao_destaque": destaque,
        "yoy": yoy,
        "alertas_ativos": ativos,
    }


# ── Detalhe por ano (retrospectiva.html) ──────────────────────────────────────
def anos_detalhe(conn, ident: dict | None = None) -> dict:
    """Top funções e favorecidos POR ANO — alimenta a página-história do ano."""
    ident = ident if ident is not None else preparar_identidades(conn)
    out = {}
    for r in _q(conn, "SELECT DISTINCT ano FROM pagamentos ORDER BY ano"):
        a = r["ano"]
        fn = [{"funcao": x["k"], "valor": round(x["s"], 2)}
              for x in _q(conn,
                  "SELECT COALESCE(NULLIF(funcao,''),'(sem função)') k, SUM(valor) s "
                  "FROM pagamentos WHERE ano=? GROUP BY k ORDER BY s DESC LIMIT 8", a)]
        todos = [_marcar_ente_publico(dict(_fav_campos(ident, x["k"]), valor=round(x["s"], 2)))
                 for x in _q(conn,
                     f"SELECT fi.chave k, SUM(p.valor) s FROM pagamentos p {FAV_JOIN.format(t='p')} "
                     f"WHERE p.ano=? GROUP BY fi.chave ORDER BY s DESC LIMIT 60", a)]
        # a lista geral é liderada por Município/IPREV/CAPEP (fluxos internos): os
        # fornecedores privados vêm à parte
        out[str(a)] = {"por_funcao": fn, "top_favorecidos": todos[:6],
                       "top_fornecedores": [f for f in todos if not f.get("ente_publico")][:5]}
    return out


# ── Raio-X por favorecido (favorecidos/<slug>.json) ───────────────────────────
# Um dossiê estático por IDENTIDADE do top-N: série mensal própria, por função,
# últimos pagamentos e alertas — consumido por favorecido.html?f=<slug>.
CONTRATOS_POR_DOSSIE = 60   # os mais recentes; o total vai em contratos_total


def exportar_favorecidos(conn, indice: dict, ident: dict | None = None, contratos: dict | None = None) -> int:
    ident = ident if ident is not None else preparar_identidades(conn)
    contratos = contratos or {}
    os.makedirs(FAV_DIR, exist_ok=True)
    tops = indice.get("top_favorecidos") or []
    validos = set()
    dossies = {}
    # total pago por elemento no período — p/ a participação do favorecido em cada elemento
    tot_elem = {r["e"]: r["s"] for r in _q(conn,
        "SELECT elemento_despesa e, SUM(valor) s FROM pagamentos GROUP BY elemento_despesa")}
    # pagamentos do top-N materializados UMA vez, indexados pela identidade: cada consulta
    # por favorecido refazia o join com fav_ident sobre a tabela inteira (300 × N varreduras
    # — o dossiê sozinho passava de 3 minutos)
    conn.execute("DROP TABLE IF EXISTS top_fav")
    conn.execute("CREATE TEMP TABLE top_fav (chave TEXT PRIMARY KEY)")
    conn.executemany("INSERT OR IGNORE INTO top_fav VALUES (?)", [(f["chave"],) for f in tops])
    conn.execute("DROP TABLE IF EXISTS pag_top")
    conn.execute(f"CREATE TEMP TABLE pag_top AS SELECT fi.chave chave, p.* FROM pagamentos p "
                 f"{FAV_JOIN.format(t='p')} JOIN top_fav t ON t.chave = fi.chave")
    conn.execute("CREATE INDEX temp.ix_pag_top ON pag_top(chave)")

    def por_chave(select, grupo, ordem):
        out = defaultdict(list)
        for r in _q(conn, f"SELECT p.chave c, {select} FROM pag_top p "
                          f"GROUP BY p.chave, {grupo} ORDER BY p.chave, {ordem}"):
            out[r["c"]].append(r)
        return out
    agg_elem = por_chave("p.elemento_despesa k, SUM(p.valor) s", "p.elemento_despesa", "s DESC")
    agg_ug = por_chave("p.unidade_gestora k, SUM(p.valor) s", "p.unidade_gestora", "s DESC")
    agg_tipo = por_chave("p.tipo_pagamento k, SUM(p.valor) s, COUNT(*) n", "p.tipo_pagamento", "s DESC")
    agg_nome = por_chave("p.nome_favorecido k, SUM(p.valor) s, COUNT(*) n, MIN(p.data) i, MAX(p.data) f",
                         "p.nome_favorecido", "i")
    for rank, f in enumerate(tops, 1):
        chave, slug = f["chave"], f["slug"]
        validos.add(slug + ".json")
        serie = [{"ano": r["ano"], "mes": r["mes"], "valor": round(r["s"], 2)}
                 for r in _q(conn,
                     "SELECT p.ano, p.mes, SUM(p.valor) s FROM pag_top p "
                     "WHERE p.chave=? GROUP BY p.ano, p.mes ORDER BY p.ano, p.mes", chave)]
        por_ano = {}
        for s in serie:
            por_ano[str(s["ano"])] = round(por_ano.get(str(s["ano"]), 0) + s["valor"], 2)
        funcoes = [{"funcao": r["k"], "valor": round(r["s"], 2)}
                   for r in _q(conn,
                       f"SELECT COALESCE(NULLIF(p.funcao,''),'(sem função)') k, SUM(p.valor) s "
                       "FROM pag_top p WHERE p.chave=? "
                       "GROUP BY k ORDER BY s DESC LIMIT 6", chave)]
        ultimos = [{"data": r["data"], "valor": round(r["valor"], 2), "funcao": r["funcao"],
                    "elemento": r["elemento_despesa"], "unidade": r["unidade_gestora"],
                    "tipo": r["tipo_pagamento"], "pagamento": r["pagamento"], "empenho": r["empenho"]}
                   for r in _q(conn,
                       f"SELECT p.data, p.valor, p.funcao, p.elemento_despesa, p.unidade_gestora, "
                       "p.tipo_pagamento, p.pagamento, p.empenho FROM pag_top p "
                       "WHERE p.chave=? ORDER BY p.data DESC, p.valor DESC, p.pagamento DESC, p.empenho DESC, "
                       "p.elemento_despesa, p.unidade_gestora, p.tipo_pagamento LIMIT 50", chave)]
        meus_alertas = [a for a in indice.get("alertas", [])
                        if (a.get("filtro") or {}).get("chave") == chave]
        # o que uma investigação pergunta primeiro: em quê, por quem, de que tipo, desde quando
        elementos = [{"elemento": r["k"], "valor": round(r["s"], 2),
                      "participacao_pct": round(100 * r["s"] / tot_elem[r["k"]], 1) if tot_elem.get(r["k"]) else None}
                     for r in agg_elem[chave][:8]]
        unidades = [{"unidade": r["k"], "valor": round(r["s"], 2)} for r in agg_ug[chave]]
        tipos = [{"tipo": r["k"] or "(não informado)", "valor": round(r["s"], 2), "qtd": r["n"]} for r in agg_tipo[chave]]
        # grafia × razão social: a origem pode trazer o mesmo CNPJ com outro NOME (troca de
        # razão social) — total e datas por nome deixam isso visível
        grafias_det = [{"nome": r["k"], "valor": round(r["s"], 2), "qtd": r["n"], "primeiro": r["i"], "ultimo": r["f"]}
                       for r in agg_nome[chave]]
        datas = {"i": min((g["primeiro"] for g in grafias_det if g["primeiro"]), default=None),
                 "f": max((g["ultimo"] for g in grafias_det if g["ultimo"]), default=None)}

        # só regrava se o CONTEÚDO mudou: com `atualizado_em` novo a cada run, os
        # 290 dossiês viravam diff diário (2,8 MB/dia no histórico e cache do Pages
        # invalidado em toda ficha) sem nenhum dado novo
        dossies[slug] = {
            "nome": f["nome"], "documento": f["documento"], "chave": chave, "slug": slug,
            "grafias": f.get("grafias") or [f["nome"]], "rank": rank,
            "total": f["valor"], "qtd": f["qtd"], "meses": f["meses"],
            "por_ano": por_ano, "serie_mensal": serie, "por_funcao": funcoes,
            "por_elemento": elementos, "por_unidade": unidades, "por_tipo": tipos,
            "primeiro_pagamento": datas["i"], "ultimo_pagamento": datas["f"],
            "ultimos_pagamentos": ultimos, "alertas": meus_alertas,
            "atualizado_em": indice.get("atualizado_em"),
        }
        if len(grafias_det) > 1:
            dossies[slug]["grafias_detalhe"] = grafias_det
        if f.get("ente_publico"):
            dossies[slug]["ente_publico"] = True
        # contratos/convênios publicados no portal para o CNPJ (lista vazia = conferido, nada publicado)
        ins = _instrumentos_do(chave, contratos)
        if ins is not None:
            dossies[slug]["contratos"] = ins["c"][:CONTRATOS_POR_DOSSIE]
            dossies[slug]["contratos_total"] = len(ins["c"])
            dossies[slug]["convenios"] = ins["v"]
    for slug, dossie in dossies.items():
        gravar_json_se_mudou(os.path.join(FAV_DIR, slug + ".json"), dossie, separators=(",", ":"))

    # remove dossiês de quem saiu do top-N
    for nome_arq in os.listdir(FAV_DIR):
        if nome_arq.endswith(".json") and nome_arq not in validos:
            os.remove(os.path.join(FAV_DIR, nome_arq))
    return len(validos)


# ── Alertas fiscais por regras ────────────────────────────────────────────────
def _id_alerta(*partes) -> str:
    return hashlib.sha1("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()[:12]


def _link_fav(f: dict, tops_slugs: set) -> str:
    if f["slug"] in tops_slugs:
        return f"{RAIOX_URL}?f={f['slug']}"
    from urllib.parse import quote
    return f"{RAIOX_URL}?doc={quote(f['documento'] or '')}&nome={quote(f['nome'] or '')}"


def _link_detalhe(**p) -> str:
    """Link para o Detalhamento já filtrado (mesmas chaves curtas do despesas-app.js).
    `favorecido` = chave de identidade (dfav): pega todas as grafias do mesmo CNPJ,
    o que a busca textual pelo nome (dq) não faz. `empenho` = "UG|nº" abre a ficha do
    empenho (emp=) quando a linha está nos meses carregados."""
    from urllib.parse import urlencode
    chaves = {"visao": "dv", "meses": "dm", "busca": "dq", "elemento": "del", "funcao": "df",
              "tipo": "dt", "unidade": "du", "favorecido": "dfav", "empenho": "emp"}
    q = {chaves[k]: v for k, v in p.items() if v}
    return f"{PAINEL_URL}?{urlencode(q)}#detalhe"


def _limite_dispensa(ano: int, elemento: str) -> dict:
    lim = LIMITES_DISPENSA.get(ano)
    e = sem_acento(elemento or "")
    veiculos = e.startswith(ELEM_MANUT_VEICULOS)
    engenharia = e.startswith("449051") or "ENGENHARIA" in e or "OBRAS" in e
    if not lim:
        return {"valor": None, "hipotese": None, "exercicio": ano, "norma": None,
                "verificacao": f"limite de {ano} não cadastrado — enquadramento não afirmado"}
    hipotese = ("art. 75, I (serviços de manutenção de veículos automotores)" if veiculos
                else "art. 75, I (obras e serviços de engenharia)" if engenharia
                else "art. 75, II (compras e demais serviços)")
    return {"valor": lim["engenharia"] if (veiculos or engenharia) else lim["compras"],
            "hipotese": hipotese + " — presumida pelo elemento de despesa",
            "exercicio": ano, "norma": lim["norma"], "verificacao": lim["verificacao"]}


# ── Espelho do PNCP (Preço comparado) → etiqueta da triagem de fracionamento ──
_ESPELHO_CACHE: dict = {}


def espelho_pncp(diretorio: str | None = None) -> dict:
    """Lê `precos/espelho/3548500-*.jsonl.gz` (compras do município de Santos no PNCP —
    pregão eletrônico e dispensa, versionadas pelo Preço comparado; formato em
    precos/crawler.py `gravar_espelho`) e devolve {"inicio": data da publicação mais
    antiga | None, "cnpj": {14 dígitos: [evidência…]}}. Evidência = contratação em que o
    CNPJ tem resultado (vencedor/registrado), com modalidade, SRP, data (do resultado ou
    da publicação), nº de controle, processo, objeto e link público. Lido uma vez por
    processo (cache por diretório); só biblioteca padrão."""
    diretorio = os.path.abspath(diretorio or PRECOS_ESPELHO_DIR)
    if diretorio in _ESPELHO_CACHE:
        return _ESPELHO_CACHE[diretorio]
    por_cnpj: dict[str, dict] = defaultdict(dict)
    inicio = None
    for arq in sorted(glob.glob(os.path.join(diretorio, f"{IBGE_SANTOS}-*.jsonl.gz"))):
        try:
            with gzip.open(arq, "rt", encoding="utf-8") as f:
                for linha in f:
                    if not linha.strip():
                        continue
                    c = json.loads(linha)
                    pub = (c.get("data_publicacao") or "")[:10]
                    if pub and (inicio is None or pub < inicio):
                        inicio = pub
                    if sem_acento(c.get("situacao") or "").startswith(PNCP_SITUACOES_FORA):
                        continue
                    for r in c.get("resultados") or []:
                        ni = re.sub(r"\D", "", r.get("ni_fornecedor") or "")
                        if len(ni) != 14:
                            continue
                        data = (r.get("data_resultado") or pub or "")[:10]
                        atual = por_cnpj[ni].get(c.get("ncp"))
                        if atual and atual["data"] <= data:
                            continue
                        por_cnpj[ni][c.get("ncp")] = {
                            "ncp": c.get("ncp"), "modalidade": c.get("modalidade"), "srp": bool(c.get("srp")),
                            "data": data, "processo": c.get("processo"), "orgao": c.get("razao_social"),
                            "objeto": " ".join((c.get("objeto") or "").split())[:160],
                            "link": PNCP_URL_PUBLICA.format(cnpj=c.get("cnpj"), ano=c.get("ano"),
                                                            seq=c.get("sequencial"))}
        except (OSError, ValueError, EOFError) as e:
            print(f"AVISO: espelho do PNCP ilegível ({os.path.basename(arq)}): {e}", file=sys.stderr)
    out = {"inicio": inicio, "cnpj": {k: sorted(v.values(), key=lambda x: x["data"]) for k, v in por_cnpj.items()}}
    _ESPELHO_CACHE[diretorio] = out
    return out


def etiqueta_pncp(evidencias: list, data_empenho: str) -> tuple:
    """(etiqueta, evidências da janela) para um empenho: pregão com registro de preços
    vencido nos PNCP_JANELA_DIAS anteriores → "provavel_ata"; pregão sem SRP →
    "vencedor_pregao"; só dispensa → "dispensa_pncp"; nada → (None, [])."""
    try:
        d = date.fromisoformat((data_empenho or "")[:10])
    except ValueError:
        return None, []
    ini = (d - timedelta(days=PNCP_JANELA_DIAS)).isoformat()
    jan = [e for e in evidencias if ini <= e["data"] <= d.isoformat()]
    for etiqueta, cond in (("provavel_ata", lambda e: e["modalidade"] == 6 and e["srp"]),
                           ("vencedor_pregao", lambda e: e["modalidade"] == 6),
                           ("dispensa_pncp", lambda e: e["modalidade"] == 8)):
        achadas = [e for e in jan if cond(e)]
        if achadas:
            return etiqueta, achadas
    return None, []


def _mes_ano(iso: str | None) -> str:
    """'2025-01-02' → 'jan/2025'."""
    return f"{MESES_ABREV[int(iso[5:7]) - 1]}/{iso[:4]}" if iso else "—"


# ── Prioridade dentro de pf_sensivel ─────────────────────────────────────────
# Aluguel mensal fixo de imóvel de PF é o padrão esperado; o que merece olhar é
# reajuste acima da inflação ou contrato que começou dentro do mandato.
IPCA_JSON = os.path.join(RAIZ, "precos", "ipca.json")
PF_JANELA = 3            # meses de cada ponta para o valor mensal típico (mediana)
PF_EXCESSO_MIN = 0.05    # reajuste acima do IPCA a partir de 5 p.p. ganha destaque


def _ipca_serie() -> dict:
    try:
        with open(IPCA_JSON, encoding="utf-8") as f:
            return json.load(f).get("serie") or {}
    except (OSError, ValueError):
        return {}


def _mediana(xs: list) -> float:
    xs = sorted(xs)
    n = len(xs)
    return (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2) if n else 0.0


def reajuste_pf(mensal: dict, inicio_base: tuple, ultimo_completo: tuple, ipca: dict) -> dict:
    """Mede, numa série {(ano, mes): valor}, o reajuste do valor mensal típico entre
    a 1ª e a última janela de PF_JANELA meses com pagamento (até `ultimo_completo`),
    contra o IPCA do mesmo intervalo. Devolve {reajuste, ipca, excesso, recente,
    desde} — `None` onde não dá para medir (série curta, IPCA ausente)."""
    meses = sorted(k for k, v in mensal.items() if v > 0 and k <= ultimo_completo)
    out = {"reajuste": None, "ipca": None, "excesso": None,
           "recente": bool(meses) and meses[0] > inicio_base, "desde": meses[0] if meses else None}
    if len(meses) < 2 * PF_JANELA:
        return out
    ini, fim = meses[:PF_JANELA], meses[-PF_JANELA:]
    v_ini = _mediana([mensal[k] for k in ini])
    v_fim = _mediana([mensal[k] for k in fim])
    if v_ini <= 0:
        return out
    out["reajuste"] = v_fim / v_ini - 1
    a = ipca.get(f"{ini[len(ini) // 2][0]}-{ini[len(ini) // 2][1]:02d}")
    b = ipca.get(f"{fim[len(fim) // 2][0]}-{fim[len(fim) // 2][1]:02d}")
    if a and b:
        out["ipca"] = b / a - 1
        out["excesso"] = out["reajuste"] - out["ipca"]
    return out


def _prioridade_pf(m: dict, soma: float) -> tuple:
    acima = m["excesso"] is not None and m["excesso"] >= PF_EXCESSO_MIN
    return (not acima, -(m["excesso"] or 0) if acima else 0, not m["recente"], -soma)


def _filtro_fav(f: dict, chave: str, **extra) -> dict:
    """Filtro de alerta de favorecido: nome, chave de identidade e documento (o painel
    monta o raio-X por ?doc= quando o favorecido está fora do top-300)."""
    return {"favorecido": f["nome"], "chave": chave, "documento": f.get("documento") or "", **extra}


def _eh_ordinario(tipo_empenho) -> bool:
    """Empenho ordinário — tipo vazio também (a origem às vezes não informa)."""
    t = sem_acento(tipo_empenho or "")
    return not t or t.startswith("ORDINARIO")


def candidatos_alertas(conn, ident: dict | None = None, cob: dict | None = None,
                       execucao: dict | None = None, prazos: dict | None = None,
                       espelho: dict | None = None, contratos: dict | None = None) -> list[dict]:
    """TODOS os casos que acionaram as regras (sem tetos). Cada alerta traz: id estável,
    classe (contexto / anomalia / inconsistência), severidade, filtro (com a chave de
    identidade), valor e, quando barato, o link; `_ordem` é a prioridade dentro da regra
    e `_completar` monta documentos/link caros (consultas por alerta) — `publicar()`
    só chama isso para os publicados. `espelho` = espelho_pncp() (padrão: o do repo)."""
    ident = ident if ident is not None else preparar_identidades(conn)
    cob = cob or cobertura(conn)
    out = []
    tops_slugs = {o["slug"] for o in ident.values()}   # todo favorecido tem slug; o link ?f= só
    # funciona p/ top-300 — o export troca para ?doc= quando o dossiê não existe (ver main)
    fav = lambda chave: _fav_campos(ident, chave)  # noqa: E731
    completo = _mes_completo_ate(conn)
    p_completo = completo[0] * 100 + completo[1] if completo else None
    inc = _incompletos(cob)   # mês incompleto na origem: fora de picos, crescimento e PF

    def meses_pag(where, *params) -> str:
        """Meses (AAAA-MM) com pagamento no recorte — o link baixa só esses arquivos."""
        return ",".join(f"{r['ano']}-{r['mes']:02d}" for r in _q(conn,
            f"SELECT DISTINCT p.ano, p.mes FROM pagamentos p {FAV_JOIN.format(t='p')} "
            f"WHERE {where} ORDER BY p.ano, p.mes", *params))

    def docs_pag(where, *params, limite=MAX_DOCS_ALERTA):
        return [{"data": r["data"], "doc": r["pagamento"], "empenho": r["empenho"], "ug": r["unidade_gestora"],
                 "valor": round(r["valor"], 2), "elemento": (r["elemento_despesa"] or "")[:60]}
                for r in _q(conn, f"SELECT p.data, p.pagamento, p.empenho, p.unidade_gestora, p.valor, "
                                  f"p.elemento_despesa FROM pagamentos p {FAV_JOIN.format(t='p')} "
                                  f"WHERE {where} ORDER BY p.valor DESC, p.data, p.pagamento, p.empenho, "
                                  f"p.unidade_gestora, p.elemento_despesa LIMIT {limite}", *params)]

    def adiar(docs=None, link=None):
        """Documentos/link calculados só se o alerta for publicado."""
        def completar(a):
            if docs:
                a["documentos"] = docs()
            if link:
                a["link"] = link()
        return completar

    # 1) Favorecido recorrente de alto valor — CONTEXTO (escala, não irregularidade)
    recorrentes = _q(conn,
        f"SELECT fi.chave k, SUM(p.valor) s, COUNT(DISTINCT p.ano*100+p.mes) meses "
        f"FROM pagamentos p {FAV_JOIN.format(t='p')} GROUP BY fi.chave "
        f"HAVING s >= ? AND meses >= ? ORDER BY s DESC",
        ALERTA_FAV_VALOR, ALERTA_FAV_MESES)
    for r in recorrentes:
        f = fav(r["k"])
        out.append({
            "id": _id_alerta("favorecido_recorrente", r["k"]),
            "tipo": "favorecido_recorrente", "classe": CLASSE_CONTEXTO, "severidade": "baixa",
            "titulo": f"Grande recebedor recorrente: {f['nome']}",
            "detalhe": f"{brl(r['s'])} acumulados em {r['meses']} meses. Valor alto e recorrência, "
                       f"por si, indicam escala do contrato/repasse — não irregularidade.",
            "valor": round(r["s"], 2),
            "filtro": _filtro_fav(f, r["k"]),
            "link": _link_fav(f, tops_slugs),
            "_ordem": (-r["s"],),
        })

    # 2) Concentração: favorecido que domina uma função
    tot_funcao = {r["k"]: r["s"] for r in _q(conn,
        "SELECT COALESCE(NULLIF(funcao,''),'(sem função)') k, SUM(valor) s "
        "FROM pagamentos GROUP BY k")}
    for r in _q(conn,
        f"SELECT COALESCE(NULLIF(p.funcao,''),'(sem função)') f, fi.chave k, SUM(p.valor) s "
        f"FROM pagamentos p {FAV_JOIN.format(t='p')} GROUP BY f, fi.chave HAVING s >= ? ORDER BY s DESC",
        ALERTA_CONCENTRACAO_MIN):
        base = tot_funcao.get(r["f"], 0) or 1
        pct = 100 * r["s"] / base
        if pct >= ALERTA_CONCENTRACAO_PCT and r["f"] != "(sem função)":
            f = fav(r["k"])
            publico = eh_ente_publico(f["nome"])
            out.append({
                "id": _id_alerta("concentracao", r["k"], r["f"]),
                "tipo": "concentracao",
                "classe": CLASSE_CONTEXTO if publico else CLASSE_ANOMALIA,
                "severidade": "baixa" if publico else "media",
                "titulo": f"Concentração: {f['nome']} concentra {pct:.0f}% da função {r['f']}",
                "detalhe": f"{brl(r['s'])} de {brl(base)} na função." +
                           (" Ente público/repasse institucional — concentração esperada." if publico else ""),
                "valor": round(r["s"], 2),
                "filtro": _filtro_fav(f, r["k"], funcao=r["f"]),
                "link": _link_fav(f, tops_slugs),
                "_ordem": (-r["s"],),
                "_completar": adiar(link=lambda k=r["k"], fn=r["f"]: _link_detalhe(
                    visao="mov", favorecido=k, funcao=fn,
                    meses=meses_pag("fi.chave=? AND COALESCE(NULLIF(p.funcao,''),'(sem função)')=?", k, fn))),
            })

    # 3) Pico mensal (sobre o total geral por mês) — só meses completos e íntegros na origem
    serie = [r for r in _q(conn, "SELECT ano, mes, SUM(valor) s FROM pagamentos GROUP BY ano, mes ORDER BY ano, mes")
             if (p_completo is None or r["ano"] * 100 + r["mes"] <= p_completo) and (r["ano"], r["mes"]) not in inc]
    vals = [r["s"] for r in serie]
    if len(vals) >= 4:
        media = sum(vals) / len(vals)
        desvio = (sum((v - media) ** 2 for v in vals) / len(vals)) ** 0.5
        limite = media + ALERTA_PICO_K * desvio
        for r in serie:
            if r["s"] > limite:
                out.append({
                    "id": _id_alerta("pico_mensal", r["ano"], r["mes"]),
                    "tipo": "pico_mensal", "classe": CLASSE_ANOMALIA, "severidade": "media",
                    "titulo": f"Pico de gasto em {r['ano']}-{r['mes']:02d}",
                    "detalhe": f"{brl(r['s'])} (média mensal {brl(media)}). Confira sazonalidade "
                               f"(13º, precatórios, repasses concentrados) antes de concluir.",
                    "valor": round(r["s"], 2),
                    "filtro": {"ano": r["ano"], "mes": r["mes"]},
                    "link": _link_detalhe(visao="mov", meses=f"{r['ano']}-{r['mes']:02d}"),
                    "_ordem": (-r["s"],),
                })

    # 4) Extra-orçamentário relevante — CONTEXTO (retenções/consignações são esperadas)
    extras = _q(conn,
        f"SELECT fi.chave k, p.elemento_despesa e, SUM(p.valor) s, COUNT(*) n "
        f"FROM pagamentos p {FAV_JOIN.format(t='p')} WHERE p.tipo_pagamento LIKE '%Extra%' "
        f"GROUP BY fi.chave, p.elemento_despesa HAVING s >= ? ORDER BY s DESC",
        ALERTA_EXTRA_VALOR)
    for r in extras:
        f = fav(r["k"])
        out.append({
            "id": _id_alerta("extra_orcamentario", r["k"], r["e"]),
            "tipo": "extra_orcamentario", "classe": CLASSE_CONTEXTO, "severidade": "baixa",
            "titulo": f"Extra-orçamentário relevante: {f['nome']}",
            "detalhe": f"{brl(r['s'])} em {r['n']} pagamentos — {(r['e'] or '')[:60]}.",
            "valor": round(r["s"], 2),
            "filtro": _filtro_fav(f, r["k"], elemento=r["e"]),
            "link": _link_fav(f, tops_slugs),
            "_ordem": (-r["s"],),
            "_completar": adiar(link=lambda k=r["k"], e=r["e"]: _link_detalhe(
                visao="mov", favorecido=k, elemento=e,
                meses=meses_pag("fi.chave=? AND p.elemento_despesa IS ? AND p.tipo_pagamento LIKE '%Extra%'", k, e))),
        })

    # 5) Possível fracionamento — TRIAGEM (v2, 2026-10): conta EMPENHOS ORDINÁRIOS
    # DISTINTOS pelo valor líquido (original + reforços − anulações) por (unidade
    # gestora, favorecido, elemento, exercício do empenho) — o art. 75, § 1º, I da Lei
    # 14.133 soma o despendido no exercício pela MESMA unidade gestora (a v1 somava UGs).
    # Global/estimativo (em geral ligados a contrato) ficam fora da conta e aparecem só
    # no detalhe; empenho sem o original na base (exercício incerto) também fica fora.
    # Limite do exercício por hipótese presumida pelo elemento (manutenção de veículos =
    # art. 75, I). Etiqueta do PNCP (espelho do Preço comparado): fornecedor que venceu
    # pregão com registro de preços nos 24 meses anteriores = provável compra por ata.
    # O padrão financeiro sozinho NÃO demonstra fracionamento irregular.
    por_grupo: dict[tuple, list] = defaultdict(list)
    for r in _q(conn, f"""
        SELECT e.unidade_gestora ug, fi.chave k, e.elemento_despesa el, e.empenho emp,
               ROUND(SUM(e.valor),2) liquido,
               MIN(CASE WHEN e.especie='Original' OR e.especie IS NULL OR e.especie='' THEN e.ano END) ano,
               MIN(CASE WHEN e.especie='Original' OR e.especie IS NULL OR e.especie='' THEN e.data END) data,
               SUM(CASE WHEN e.especie='Original' OR e.especie IS NULL OR e.especie='' THEN 1 ELSE 0 END) originais,
               SUM(CASE WHEN e.especie LIKE 'Refor%' THEN 1 ELSE 0 END) reforcos,
               SUM(CASE WHEN e.especie LIKE 'Anula%' THEN 1 ELSE 0 END) anulacoes,
               MAX(CASE WHEN e.especie='Original' OR e.especie IS NULL OR e.especie='' THEN e.tipo_empenho END) tipo
        FROM empenhos e {FAV_JOIN.format(t='e')}
        GROUP BY e.unidade_gestora, fi.chave, e.elemento_despesa, e.empenho"""):
        if r["originais"]:
            por_grupo[(r["ug"], r["k"], r["el"], r["ano"])].append(dict(r))
    esp = espelho if espelho is not None else espelho_pncp()
    ctr = contratos if contratos is not None else contratos_portal()   # contratos do portal (instrumentos.py)
    cobertura_pncp = (f"o espelho do PNCP usado aqui cobre só pregão eletrônico e dispensa de Santos "
                      f"publicados desde {_mes_ano(esp.get('inicio'))} — “sem registro” não quer dizer "
                      f"“sem licitação”") if esp.get("inicio") else "espelho do PNCP indisponível nesta execução"
    for (ug, k, el, ano), emps in por_grupo.items():
        lim = _limite_dispensa(ano, el)
        if not lim["valor"] or eh_ente_publico(fav(k)["nome"]):
            continue
        ordinarios = [e for e in emps if _eh_ordinario(e["tipo"])]
        outros = [e for e in emps if not _eh_ordinario(e["tipo"])]
        abaixo = [e for e in ordinarios if 0 < e["liquido"] < lim["valor"]]
        soma = round(sum(e["liquido"] for e in abaixo), 2)
        if len(abaixo) < FRAC_MIN_EMPENHOS or soma < FRAC_FATOR_TOTAL * lim["valor"]:
            continue
        f = fav(k)
        # etiqueta PNCP: por empenho (janela de 24 meses antes da data dele); a do alerta é
        # a mais forte encontrada, com quantos dos empenhos ela alcança
        evid = esp.get("cnpj", {}).get(k[5:], []) if k.startswith("cnpj:") else []
        por_emp = [etiqueta_pncp(evid, e["data"]) for e in abaixo]
        etiqueta, achadas = None, {}
        for et in ETIQUETAS_PNCP:
            alcancados = [ev for (t, ev) in por_emp if t == et]
            if alcancados:
                etiqueta = et
                for ev in alcancados:
                    achadas.update({x["ncp"]: x for x in ev})
                break
        n_et = sum(1 for (t, _) in por_emp if t == etiqueta) if etiqueta else 0
        pncp = sorted(achadas.values(), key=lambda x: x["data"], reverse=True)[:3]
        if etiqueta:
            x = pncp[0]
            o_que = {"provavel_ata": "venceu pregão com registro de preços",
                     "vencedor_pregao": "venceu pregão sem registro de preços",
                     "dispensa_pncp": "foi contratado por dispensa publicada"}[etiqueta]
            pncp_txt = (f" PNCP: este CNPJ {o_que} nos 24 meses anteriores a {n_et} de {len(abaixo)} empenhos "
                        f"({x['ncp']}, processo {x['processo'] or '—'}: {x['objeto'][:90]})"
                        + (" — provável compra por ata, não fracionamento; confira a ata."
                           if etiqueta == "provavel_ata" else "; confira se os empenhos são dessa contratação.")
                        + f" Ressalva: {cobertura_pncp}.")
        else:
            pncp_txt = f" Sem registro deste fornecedor no PNCP na janela de 24 meses ({cobertura_pncp})."
        # contrato publicado no portal com o mesmo CNPJ, assinado até 24 meses antes de algum
        # empenho: os empenhos podem ser execução dele, não fracionamento (vai para o fim da fila)
        ins, contrato, n_ct = _instrumentos_do(k, ctr), None, 0
        for e in (abaixo if ins and ins["c"] else []):
            d_emp = (e["data"] or "")[:10]
            if not d_emp:
                continue
            ini = (date.fromisoformat(d_emp) - timedelta(days=CONTRATO_JANELA_DIAS)).isoformat()
            cobre = [c for c in ins["c"] if c["assinatura"] and ini <= c["assinatura"] <= d_emp]
            if cobre:
                n_ct += 1
                melhor = max(cobre, key=lambda c: (c["assinatura"], c["contrato"]))
                if not contrato or (melhor["assinatura"], melhor["contrato"]) > (contrato["assinatura"], contrato["contrato"]):
                    contrato = melhor
        contrato_txt = ""
        if contrato:
            contrato_txt = (f" Portal: há contrato publicado com este CNPJ assinado nos 24 meses anteriores a "
                            f"{n_ct} de {len(abaixo)} empenhos — nº {contrato['contrato']} (processo "
                            f"{contrato['processo'] or '—'}), {'/'.join(reversed(contrato['assinatura'].split('-')))}, "
                            f"{brl(contrato['valor'])}: {contrato['objeto'][:90]} — os empenhos podem ser execução "
                            f"desse contrato; confira.")
        fora_txt = ""
        if outros:
            fora_txt = (f" Fora da conta: {len(outros)} empenho(s) global(is)/estimativo(s) do mesmo favorecido e "
                        f"elemento nesta unidade ({brl(sum(e['liquido'] for e in outros))}), em geral ligados a contrato.")
        ug_curta = "" if ug == "PREFEITURA MUNICIPAL DE SANTOS" else f", {ug}"
        docs = [{"ug": e["ug"], "empenho": e["emp"], "data": e["data"], "valor": e["liquido"],
                 "originais": e["originais"], "reforcos": e["reforcos"], "anulacoes": e["anulacoes"]}
                for e in sorted(abaixo, key=lambda e: -e["liquido"])[:MAX_DOCS_ALERTA]]
        out.append({
            "id": _id_alerta("fracionamento", ug, k, el, ano),
            # continuidade: o id que a regra v1 (sem UG) daria — herda o "desde" do histórico
            "ids_anteriores": [_id_alerta("fracionamento", k, el, ano)],
            "tipo": "fracionamento", "classe": CLASSE_ANOMALIA, "severidade": "media",
            "titulo": f"Triagem de fracionamento: {len(abaixo)} empenhos distintos a {f['nome']} ({ano}{ug_curta})",
            "detalhe": (f"{brl(soma)} em {len(abaixo)} empenhos ordinários distintos da unidade {ug}, cada um "
                        f"abaixo de {brl(lim['valor'])} ({lim['hipotese']}; {lim['norma']}) — {(el or '')[:50]}. "
                        f"A Lei 14.133 (art. 75, § 1º, I) soma o que a mesma unidade gestora gastou no exercício. "
                        f"Padrão financeiro apenas: o valor empenhado não é o valor da contratação, e "
                        f"o limite se aplica ao objeto.{fora_txt}{pncp_txt}{contrato_txt} "
                        f"Faltam: {', '.join(FRAC_INFO_FALTANTE)}."),
            "valor": soma,
            "filtro": _filtro_fav(f, k, elemento=el, tipo_doc="pj", ano=ano, unidade=ug),
            "limite": lim,
            "etiqueta": etiqueta,
            "etiqueta_alcance": [n_et, len(abaixo)] if etiqueta else None,
            "pncp": pncp,
            **({"contrato": {c: contrato[c] for c in ("contrato", "processo", "assinatura", "valor", "objeto")},
                "contrato_alcance": [n_ct, len(abaixo)]} if contrato else {}),
            "documentos": docs,
            "informacoes_faltantes": FRAC_INFO_FALTANTE,
            # execução: cada empenho está no arquivo do mês em que foi emitido (1º documento)
            "link": _link_detalhe(visao="exe", favorecido=k, elemento=el, unidade=ug,
                                  meses=",".join(sorted({(e["data"] or "")[:7] for e in abaixo} - {""})) or str(ano)),
            "_ordem": (-soma,),
        })

    # 6) Favorecido novo (1ª aparição recente) de alto valor
    ultimo = _q(conn, "SELECT MAX(ano*100+mes) m FROM pagamentos")[0]["m"]
    if ultimo:
        ay, am = ultimo // 100, ultimo % 100
        cm = am - ALERTA_NOVO_MESES
        cy = ay
        while cm <= 0:
            cm += 12
            cy -= 1
        corte = cy * 100 + cm
        for r in _q(conn,
            f"SELECT fi.chave k, SUM(p.valor) s, MIN(p.ano*100+p.mes) ini FROM pagamentos p "
            f"{FAV_JOIN.format(t='p')} GROUP BY fi.chave HAVING ini >= ? AND s >= ? ORDER BY s DESC",
            corte, ALERTA_NOVO_VALOR):
            f = fav(r["k"])
            if eh_ente_publico(f["nome"]):
                continue
            out.append({
                "id": _id_alerta("favorecido_novo", r["k"]),
                "tipo": "favorecido_novo", "classe": CLASSE_ANOMALIA, "severidade": "media",
                "titulo": f"Favorecido novo de alto valor: {f['nome']}",
                "detalhe": (f"{brl(r['s'])} desde {r['ini'] // 100}-{r['ini'] % 100:02d} "
                            f"(1ª aparição na base, que começa em {ANO_INICIAL}-01)."),
                "valor": round(r["s"], 2),
                "filtro": _filtro_fav(f, r["k"]),
                "link": _link_fav(f, tops_slugs),
                "_ordem": (-r["s"],),
                "_completar": adiar(docs=lambda k=r["k"]: docs_pag("fi.chave=?", k)),
            })

    # 7) Crescimento ano-a-ano no MESMO período (jan–M do último mês completo em
    # ambos os anos, menos os meses incompletos na origem em qualquer dos dois) — sem
    # projeção anualizada
    comp = [m for m in range(1, completo[1] + 1)
            if (completo[0], m) not in inc and (completo[0] - 1, m) not in inc] if completo else []
    if len(comp) >= ALERTA_YOY_MIN_MESES:
        atual, mlim = completo
        ant = atual - 1
        em = f"p.mes IN ({','.join(str(m) for m in comp)})"   # inteiros do próprio código
        fora = sorted(k for k in inc if k[0] in (atual, ant) and k[1] <= mlim)
        fora_txt = (f"; {_rotulo_meses(fora)} fora — {'incompletos' if len(fora) > 1 else 'incompleto'} na origem"
                    if fora else "")
        for r in _q(conn,
            f"SELECT fi.chave k, "
            f"SUM(CASE WHEN p.ano=? AND {em} THEN p.valor ELSE 0 END) v_ant, "
            f"SUM(CASE WHEN p.ano=? AND {em} THEN p.valor ELSE 0 END) v_atual "
            f"FROM pagamentos p {FAV_JOIN.format(t='p')} GROUP BY fi.chave "
            f"HAVING v_ant > 0 AND v_atual >= ? ORDER BY v_atual DESC",
            ant, atual, ALERTA_YOY_VALOR):
            f = fav(r["k"])
            if eh_ente_publico(f["nome"]) or r["v_atual"] < ALERTA_YOY_FATOR * r["v_ant"]:
                continue
            per = _rotulo_periodo(comp)
            out.append({
                "id": _id_alerta("crescimento_yoy", r["k"], atual),
                "tipo": "crescimento_yoy", "classe": CLASSE_ANOMALIA, "severidade": "media",
                "titulo": f"Crescimento no mesmo período: {f['nome']}",
                "detalhe": (f"{brl(r['v_atual'])} em {per}/{atual} vs {brl(r['v_ant'])} em {per}/{ant} "
                            f"— {fator(r['v_atual'] / r['v_ant'])} (meses completos; sem projeção{fora_txt})."),
                "valor": round(r["v_atual"], 2),
                "filtro": _filtro_fav(f, r["k"]),
                "link": _link_fav(f, tops_slugs),
                "_ordem": (-r["v_atual"],),
                "_completar": adiar(docs=lambda k=r["k"]: docs_pag(f"fi.chave=? AND p.ano=? AND {em}", k, atual)),
            })

    # 8) Pessoa física (CPF) recebendo em elemento sensível. Severidade MÉDIA (era
    # alta): o caso típico é aluguel mensal fixo de imóvel de PF, padrão esperado —
    # não pode ocupar sozinho o topo da lista (decisão de 2026-09-29).
    cond_elem = " OR ".join(f"p.elemento_despesa LIKE '{x}'" for x in ELEM_SENSIVEIS)
    pfs = _q(conn,
        f"SELECT fi.chave k, p.elemento_despesa e, SUM(p.valor) s, COUNT(*) qt "
        f"FROM pagamentos p {FAV_JOIN.format(t='p')} WHERE fi.chave LIKE 'cpf:%' AND ({cond_elem}) "
        f"GROUP BY fi.chave, p.elemento_despesa HAVING s >= ? ORDER BY s DESC",
        ALERTA_PF_VALOR)
    # Prioridade: reajuste acima do IPCA, depois início dentro da base, depois valor.
    mensal_pf: dict = defaultdict(dict)
    if pfs:
        for m in _q(conn,
                f"SELECT fi.chave k, p.elemento_despesa e, p.ano a, p.mes m, SUM(p.valor) v "
                f"FROM pagamentos p {FAV_JOIN.format(t='p')} WHERE fi.chave LIKE 'cpf:%' AND ({cond_elem}) "
                f"GROUP BY 1, 2, 3, 4"):
            if (m["a"], m["m"]) not in inc:   # mês incompleto na origem não mede valor típico
                mensal_pf[(m["k"], m["e"])][(m["a"], m["m"])] = m["v"]
    lim = _q(conn, "SELECT MIN(ano*100+mes) i, MAX(ano*100+mes) f FROM pagamentos")[0]
    inicio_base = (lim["i"] // 100, lim["i"] % 100) if lim["i"] else (0, 0)
    while inicio_base in inc:   # "início dentro da base" conta do 1º mês íntegro na origem
        inicio_base = (inicio_base[0], inicio_base[1] + 1) if inicio_base[1] < 12 else (inicio_base[0] + 1, 1)
    ult = (lim["f"] // 100, lim["f"] % 100) if lim["f"] else (0, 0)
    ultimo_completo = (ult[0] - 1, 12) if ult[1] == 1 else (ult[0], ult[1] - 1)  # mês corrente é parcial
    ipca = _ipca_serie()
    medidas = {(r["k"], r["e"]): reajuste_pf(mensal_pf[(r["k"], r["e"])], inicio_base, ultimo_completo, ipca)
               for r in pfs}
    for r in pfs:
        f = fav(r["k"])
        elem_curto = (r["e"] or "").split(" - ", 1)[-1][:40]
        m = medidas[(r["k"], r["e"])]
        extra = ""
        if m["excesso"] is not None and m["excesso"] >= PF_EXCESSO_MIN:
            extra = (f" Valor mensal típico subiu {m['reajuste']:.0%} contra IPCA de {m['ipca']:.0%} "
                     f"no mesmo intervalo — reajuste acima da inflação ou imóvel novo; confira o contrato.")
        elif m["recente"] and m["desde"]:
            extra = f" Pagamentos começaram em {MESES_ABREV[m['desde'][1] - 1]}/{m['desde'][0]}, dentro da base."
        out.append({
            "id": _id_alerta("pf_sensivel", r["k"], r["e"]),
            "tipo": "pf_sensivel", "classe": CLASSE_ANOMALIA, "severidade": "media",
            "titulo": f"Pessoa física em {elem_curto}: {f['nome']}",
            "detalhe": f"{brl(r['s'])} em {r['qt']} pagamentos a pessoa física — {(r['e'] or '')[:50]}.{extra}",
            "reajuste": None if m["reajuste"] is None else round(m["reajuste"], 4),
            "reajuste_ipca": None if m["ipca"] is None else round(m["ipca"], 4),
            "valor": round(r["s"], 2),
            "filtro": _filtro_fav(f, r["k"], elemento=r["e"], tipo_doc="pf"),
            "link": _link_fav(f, tops_slugs),
            "_ordem": _prioridade_pf(m, r["s"]),
            "_completar": adiar(
                docs=lambda k=r["k"], e=r["e"]: docs_pag("fi.chave=? AND p.elemento_despesa=?", k, e),
                link=lambda k=r["k"], e=r["e"]: _link_detalhe(
                    visao="mov", favorecido=k, elemento=e,
                    meses=meses_pag("fi.chave=? AND p.elemento_despesa=?", k, e))),
        })

    # 8b) Prazo liquidação → pagamento fora do padrão — TRIAGEM da ordem cronológica
    # (art. 141 da Lei 14.133): pago muito mais rápido que a fila, ou muito mais devagar
    # (atraso = risco de juros/reequilíbrio). A ordem vale por fonte de recurso e tem
    # exceções justificadas (§1º) — o texto diz o que falta para concluir.
    prz = prazos if prazos is not None else prazos_pagamento(conn, ident)
    geral = prz.get("mediana_geral_dias")
    linhas_prz = prz.get("_linhas") or []
    for tipo, cond, ordem in (
            ("prazo_rapido", lambda x: geral is not None and geral >= PRAZO_GERAL_MIN
                                       and x["mediana_dias"] <= PRAZO_RAPIDO_DIAS,
             lambda x: -x["valor"]),
            ("prazo_lento", lambda x: x["mediana_dias"] >= PRAZO_LENTO_DIAS, lambda x: -x["mediana_dias"])):
        achados = sorted((x for x in linhas_prz if cond(x)), key=ordem)
        for x in achados:
            rapido = tipo == "prazo_rapido"
            out.append({
                "id": _id_alerta(tipo, x["chave"]),
                "tipo": tipo, "classe": CLASSE_ANOMALIA, "severidade": "media",
                "titulo": (f"Pago bem mais rápido que a fila: {x['nome']}" if rapido
                           else f"Pago bem mais devagar que a fila: {x['nome']}"),
                "detalhe": (f"Mediana de {x['mediana_dias']:g} dia(s) entre liquidação e pagamento em "
                            f"{x['pagamentos']} pagamentos ({brl(x['valor'])}), contra {geral:g} dia(s) no geral. "
                            + ("Triagem de ordem cronológica (art. 141 da Lei 14.133): a ordem vale por fonte de "
                               "recurso e admite exceções justificadas — confira a fonte e a justificativa."
                               if rapido else
                               "Atraso de pagamento pode gerar juros, correção e pedido de reequilíbrio — confira "
                               "se houve glosa, pendência documental ou falta de caixa.")),
                "valor": x["valor"],
                "filtro": _filtro_fav(x, x["chave"]),
                "link": _link_fav(x, tops_slugs),
                "_ordem": (ordem(x), -x["valor"]),
            })

    # 9/10) Pico na série do próprio favorecido / elemento (z-score local) — meses completos
    def _picos_locais(campo_sql, tipo, valor_min, rotulo):
        series: dict[str, list] = {}
        sql = (f"SELECT {campo_sql} k, p.ano*100+p.mes per, SUM(p.valor) s FROM pagamentos p "
               f"{FAV_JOIN.format(t='p')} GROUP BY k, per ORDER BY k, per")
        for r in _q(conn, sql):
            if not r["k"] or (p_completo and r["per"] > p_completo) or (r["per"] // 100, r["per"] % 100) in inc:
                continue
            series.setdefault(r["k"], []).append((r["per"], r["s"]))
        achados = []
        for k, pts in series.items():
            nome = fav(k)["nome"] if tipo == "pico_favorecido" else k
            if len(pts) < ALERTA_Z_MIN_MESES or (tipo == "pico_favorecido" and eh_ente_publico(nome)):
                continue
            if tipo == "pico_elemento" and any(s in (k or "").upper() for s in ELEM_SAZONAIS):
                continue
            vals = [s for _, s in pts]
            media = sum(vals) / len(vals)
            desvio = (sum((v - media) ** 2 for v in vals) / len(vals)) ** 0.5
            if not desvio:
                continue
            limite = media + ALERTA_Z_K * desvio
            anominos = [(p, s) for p, s in pts if s > limite and s >= valor_min and s >= 2 * media]
            if not anominos:
                continue
            p, s = anominos[-1]   # o mais recente
            achados.append((k, p, s, media, nome))
        achados.sort(key=lambda x: -x[2])
        for k, p, s, media, nome in achados:
            mes_txt = f"{p // 100}-{p % 100:02d}"
            if tipo == "pico_favorecido":
                filtro = _filtro_fav(fav(k), k, ano=p // 100, mes=p % 100)
                docs = lambda k=k, p=p: docs_pag("fi.chave=? AND p.ano=? AND p.mes=?", k, p // 100, p % 100)  # noqa: E731
                link = _link_detalhe(visao="mov", meses=mes_txt, favorecido=k)
                curto = nome
            else:
                filtro = {"elemento": k, "ano": p // 100, "mes": p % 100}
                docs = lambda k=k, p=p: docs_pag("p.elemento_despesa=? AND p.ano=? AND p.mes=?",  # noqa: E731
                                                 k, p // 100, p % 100)
                link = _link_detalhe(visao="mov", meses=mes_txt, elemento=k)
                curto = (k or "").split(" - ", 1)[-1][:60]
            out.append({
                "id": _id_alerta(tipo, k, p),
                "tipo": tipo, "classe": CLASSE_ANOMALIA, "severidade": "media",
                "titulo": f"Pico de {rotulo}: {curto} em {mes_txt}",
                "detalhe": (f"{brl(s)} no mês — {fator(s / media)} a média mensal "
                            f"histórica ({brl(media)}). Mês completo; confira sazonalidade."),
                "valor": round(s, 2),
                "filtro": filtro, "link": link,
                "_ordem": (-s,),
                "_completar": adiar(docs=docs),
            })

    _picos_locais("fi.chave", "pico_favorecido", ALERTA_ZFAV_VALOR, "pagamento a favorecido")
    _picos_locais("p.elemento_despesa", "pico_elemento", ALERTA_ZELEM_VALOR, "gasto no elemento")

    # 11) INCONSISTÊNCIAS DE DADOS (origem/cobertura) — separadas das anomalias
    dup_mes: dict[tuple, list] = defaultdict(list)
    for p in cob["particoes"]:
        d = p.get("duplicidade")
        if d and d.get("sistematica"):
            dup_mes[(p["ano"], p["mes"])].append(p)
    for (ano, mes), parts in sorted(dup_mes.items()):
        mes_txt = f"{ano}-{mes:02d}"
        fontes_txt = ", ".join(p["fonte"] for p in parts)
        n_desc = sum(p["descartados"] for p in parts)
        soma_desc = round(sum(p["soma_descartada"] for p in parts), 2)
        pago_desc = round(sum(p["soma_descartada"] for p in parts if p["fonte"] == "pagamentos"), 2)
        out.append({
            "id": _id_alerta("dados_duplicidade", ano, mes),
            "tipo": "dados_duplicidade", "classe": CLASSE_INCONSISTENCIA, "severidade": "media",
            "titulo": f"Origem devolveu {mes_txt} em duplicidade sistemática ({fontes_txt})",
            "detalhe": (f"{n_desc} linhas idênticas descartadas ({brl(soma_desc)} nos três estágios; "
                        f"{brl(pago_desc)} em pagamentos): lotes inteiros vieram repetidos na API "
                        f"(dias completos de uma unidade gestora ou ≥ 5% das linhas do mês). Sem o "
                        f"descarte, o mês somaria a mais na visão corrente. Conferir no portal oficial."),
            "valor": pago_desc,
            "filtro": {"ano": ano, "mes": mes},
            "link": _link_detalhe(visao="mov", meses=mes_txt),
        })
    # mês que a origem publicou pela metade (conciliação com o TCE-SP — ver conciliacao_tce)
    for m in (cob.get("conciliacao_tce") or {}).get("meses") or []:
        if m["status"] != "incompleto":
            continue
        ano, mes = int(m["periodo"][:4]), int(m["periodo"][5:7])
        b, t = m["base"], m["tce"]
        out.append({
            "id": _id_alerta("dados_incompleto_origem", ano, mes),
            "tipo": "dados_incompleto_origem", "classe": CLASSE_INCONSISTENCIA, "severidade": "media",
            "titulo": f"Prefeitura publicou {MESES_ABREV[mes - 1]}/{ano} incompleto (conferido com o TCE-SP)",
            "detalhe": (f"No portal da Prefeitura: {brl(b['empenhado'])} empenhados e {brl(b['liquidado'])} "
                        f"liquidados no mês (sem restos a pagar). No TCE-SP, que recebe a contabilidade do "
                        f"município: {brl(t['empenhado'])} e {brl(t['liquidado'])}, sem a Câmara. O mês fica fora "
                        f"das comparações (acumulado do ano, crescimento, picos, fim de exercício). Empenhos "
                        f"emitidos nele e não publicados aparecem depois só pelas liquidações e pagamentos "
                        f"(“original fora da base”). Conferir no portal oficial."),
            "valor": round(max(t["empenhado"] - b["empenhado"], t["liquidado"] - b["liquidado"]), 2),
            "filtro": {"ano": ano, "mes": mes},
            "link": _link_detalhe(visao="mov", meses=m["periodo"]),
        })
    for p in cob["particoes"]:
        if p.get("status") not in (None, "ok"):
            out.append({
                "id": _id_alerta("dados_particao", p["fonte"], p["ano"], p["mes"]),
                "tipo": "dados_particao", "classe": CLASSE_INCONSISTENCIA, "severidade": "media",
                "titulo": f"Coleta de {p['fonte']} {p['ano']}-{p['mes']:02d} falhou ({p['status']})",
                "detalhe": f"{p['erro']} Versão anterior mantida (de {p['baixado_em'] or 'nunca carregada'}).",
                "valor": 0, "filtro": {"ano": p["ano"], "mes": p["mes"], "fonte": p["fonte"]},
                "link": _link_detalhe(visao="mov", meses=f"{p['ano']}-{p['mes']:02d}"),
            })
    if cob["faltantes"]:
        out.append({
            "id": _id_alerta("dados_cobertura", ",".join(cob["faltantes"])),
            "tipo": "dados_cobertura", "classe": CLASSE_INCONSISTENCIA, "severidade": "media",
            "titulo": f"{len(cob['faltantes'])} partição(ões) sem carga na base",
            "detalhe": "Faltam: " + ", ".join(cob["faltantes"][:12]) + ("…" if len(cob["faltantes"]) > 12 else "") +
                       ". Totais e taxas desses meses estão incompletos.",
            "valor": 0, "filtro": {}, "link": PAINEL_URL + "#geral",
        })
    exe = execucao or {}
    for ano, a in (exe.get("por_ano") or {}).items():
        if a.get("taxa_motivos"):
            out.append({
                "id": _id_alerta("dados_taxa", ano),
                "tipo": "dados_taxa", "classe": CLASSE_INCONSISTENCIA, "severidade": "baixa",
                "titulo": f"Taxa de execução de {ano} não validada",
                "detalhe": "; ".join(a["taxa_motivos"]) + ". Números brutos publicados sem teto artificial.",
                "valor": 0, "filtro": {"ano": int(ano)}, "link": PAINEL_URL + "#geral",
            })
    todos, _ = _empenhos_na_base(conn)
    nl: dict[int, list] = defaultdict(lambda: [0, 0.0])
    for r in _q(conn, "SELECT ano, unidade_gestora ug, empenho, tipo_pagamento tp, COUNT(*) n, SUM(valor) s "
                      "FROM pagamentos WHERE empenho IS NOT NULL AND empenho <> '' GROUP BY ano, ug, empenho, tp"):
        if classificar_documento(r["tp"], r["empenho"], f"{r['ug']}|{r['empenho']}" in todos) == T_NAO_LOCALIZADO:
            nl[r["ano"]][0] += r["n"]
            nl[r["ano"]][1] += r["s"]
    for ano, (qtd, soma) in sorted(nl.items()):
        if soma >= ALERTA_NL_VALOR:
            inc_ano = sorted(k for k in inc if k[0] == ano)
            causa = (f"provável empenho emitido em {_rotulo_meses(inc_ano)}, que a origem publicou incompleto"
                     if inc_ano else f"provável empenho emitido antes de {ANO_INICIAL}-01 ou lacuna da origem")
            out.append({
                "id": _id_alerta("dados_nao_localizado", ano),
                "tipo": "dados_nao_localizado", "classe": CLASSE_INCONSISTENCIA, "severidade": "baixa",
                "titulo": f"Pagamentos orçamentários de {ano} cujo empenho não está na base",
                "detalhe": (f"{brl(soma)} em {qtd} pagamentos classificados pela origem como orçamentários, "
                            f"mas o nº de empenho não veio no endpoint de empenhos ({causa}). "
                            f"Não são restos a pagar."),
                "valor": round(soma, 2), "filtro": {"ano": ano, "tipo": T_NAO_LOCALIZADO},
                "link": _link_detalhe(visao="exe", meses=str(ano), tipo=T_NAO_LOCALIZADO),
            })

    # 12) Pago acima do liquidado / liquidação paga duas vezes (2026-10) — ANOMALIA a
    # conferir. Por (UG, empenho, nº da liquidação), detectado direto no SQLite; guardas
    # contra artefato da base em pago_acima_liquidado().
    ruins = {(p["fonte"], p["ano"], p["mes"]) for p in cob["particoes"]
             if p.get("status") not in (None, "ok") or (p.get("duplicidade") or {}).get("sistematica")}
    for x in pago_acima_liquidado(conn, ruins, ident):
        f = fav(x["chave"])
        ug_txt = "" if x["ug"] == "PREFEITURA MUNICIPAL DE SANTOS" else f" ({x['ug']})"
        out.append({
            "id": _id_alerta("pago_acima_liquidado", x["ug"], x["empenho"], x["liquidacao"]),
            "tipo": "pago_acima_liquidado", "classe": CLASSE_ANOMALIA, "severidade": "media",
            "titulo": (f"Liquidação paga duas vezes: {f['nome']}" if x["dobro"]
                       else f"Pago acima do liquidado: {f['nome']}"),
            "detalhe": (f"Liquidação {x['liquidacao']} do empenho {x['empenho']}{ug_txt}: liquidado "
                        f"{brl(x['liquidado'])}, pago {brl(x['pago'])} em {x['pagamentos']} pagamento(s) — "
                        f"{brl(x['excesso_liquidacao'])} a mais. O empenho inteiro também está pago acima do "
                        f"liquidado ({brl(x['excesso_empenho'])}). Pode ser estorno ainda não publicado, nº de "
                        f"liquidação trocado na origem ou pagamento em duplicidade — confira as notas de "
                        f"liquidação e as ordens de pagamento."),
            "valor": x["excesso"],
            "filtro": _filtro_fav(f, x["chave"], unidade=x["ug"], empenho=x["empenho"],
                                  liquidacao=x["liquidacao"]),
            "link": _link_fav(f, tops_slugs),
            "_ordem": (-x["excesso"],),
            "_completar": adiar(docs=lambda x=x: _docs_liquidacao(conn, x),
                                link=lambda x=x: _link_detalhe(
                                    visao="exe", meses=_periodo_execucao(conn, x["ug"], x["empenho"]),
                                    busca=x["empenho"], unidade=x["ug"], empenho=f"{x['ug']}|{x['empenho']}")),
        })
    return out


def pago_acima_liquidado(conn, particoes_ruins=frozenset(), ident: dict | None = None) -> list[dict]:
    """Liquidações pagas acima do valor liquidado, por (UG, empenho, nº da liquidação).

    Universo: pagamentos com nº de empenho e de liquidação, exceto extra-orçamentário
    (retenções repassadas a terceiros com o mesmo nº) e "Restos a Pagar Processados"
    (o nº aponta liquidação de outro exercício, fora da base). Para virar caso:
      - a liquidação está na base com o registro original e saldo > 0 (sem isso a base
        está incompleta — não dá para comparar);
      - pagamento orçamentário exige o empenho original na base (idem);
      - o favorecido não é ente público (folha, previdência, repasses: fluxo interno);
      - o excesso é ≥ PAGO_ACIMA_MIN na liquidação E no empenho inteiro (excesso só na
        liquidação = nº de liquidação trocado entre parcelas do mesmo empenho);
      - nenhuma partição envolvida (estágio × mês) com erro ou duplicidade sistemática.
    `dobro` = pago exatamente 2× o liquidado com ≥ 2 pagamentos distintos. Linhas
    idênticas NÃO são deduplicadas aqui: a base já trata a duplicidade sistemática, e
    há estornos repetidos legítimos (a deduplicação inventava excesso)."""
    ident = ident if ident is not None else preparar_identidades(conn)
    _, originais = _empenhos_na_base(conn)
    liq = {}
    for r in _q(conn, """
        SELECT unidade_gestora ug, empenho e, liquidacao lq, ROUND(SUM(valor),2) v,
               SUM(CASE WHEN especie='Original' OR especie IS NULL OR especie='' THEN 1 ELSE 0 END) orig,
               GROUP_CONCAT(DISTINCT ano*100+mes) per
        FROM liquidacoes WHERE COALESCE(empenho,'') <> '' AND COALESCE(liquidacao,'') <> ''
        GROUP BY 1, 2, 3"""):
        liq[(r["ug"], r["e"], r["lq"])] = r
    pag: dict[tuple, dict] = {}
    for r in _q(conn, f"""
        SELECT p.unidade_gestora ug, p.empenho e, p.liquidacao lq, p.tipo_pagamento tp,
               ROUND(SUM(p.valor),2) v, GROUP_CONCAT(DISTINCT CASE WHEN p.valor > 0 THEN p.pagamento END) docs,
               GROUP_CONCAT(DISTINCT p.ano*100+p.mes) per, MAX(fi.chave) k
        FROM pagamentos p {FAV_JOIN.format(t='p')}
        WHERE COALESCE(p.empenho,'') <> '' AND COALESCE(p.liquidacao,'') <> ''
        GROUP BY 1, 2, 3, 4"""):
        t = sem_acento(r["tp"] or "")
        if "EXTRA" in t or ("RESTOS" in t and "NAO PROCESSADO" not in t):
            continue
        g = pag.setdefault((r["ug"], r["e"], r["lq"]), {"v": 0.0, "docs": set(), "per": set(),
                                                       "orc": False, "k": r["k"]})
        g["v"] += r["v"]
        g["docs"] |= set(filter(None, (r["docs"] or "").split(",")))
        g["per"] |= {int(p) for p in (r["per"] or "").split(",") if p}
        g["orc"] = g["orc"] or not t.startswith("RESTOS")
    emp_pago, emp_liq = defaultdict(float), defaultdict(float)
    for (ug, e, _lq), g in pag.items():
        emp_pago[(ug, e)] += g["v"]
    for (ug, e, _lq), r in liq.items():
        emp_liq[(ug, e)] += r["v"]
    out = []
    for (ug, e, lq), g in pag.items():
        l = liq.get((ug, e, lq))
        if not l or not l["orig"] or l["v"] <= 0.005:
            continue
        exc_liq = round(g["v"] - l["v"], 2)
        if exc_liq < PAGO_ACIMA_MIN:
            continue
        if g["orc"] and f"{ug}|{e}" not in originais:
            continue
        exc_emp = round(emp_pago[(ug, e)] - emp_liq[(ug, e)], 2)
        if exc_emp < PAGO_ACIMA_MIN:
            continue
        if eh_ente_publico(_fav_campos(ident, g["k"])["nome"]):
            continue
        parts = ({("pagamentos", p // 100, p % 100) for p in g["per"]} |
                 {("liquidacoes", int(p) // 100, int(p) % 100) for p in (l["per"] or "").split(",") if p})
        if parts & set(particoes_ruins):
            continue
        out.append({"ug": ug, "empenho": e, "liquidacao": lq, "chave": g["k"],
                    "liquidado": round(l["v"], 2), "pago": round(g["v"], 2), "pagamentos": len(g["docs"]),
                    "excesso_liquidacao": exc_liq, "excesso_empenho": exc_emp,
                    "excesso": min(exc_liq, exc_emp),
                    "dobro": len(g["docs"]) >= 2 and abs(g["v"] - 2 * l["v"]) < 0.01,
                    "meses": sorted(f"{p // 100}-{p % 100:02d}" for p in g["per"])})
    return sorted(out, key=lambda x: -x["excesso"])


def _docs_liquidacao(conn, x: dict) -> list[dict]:
    """A liquidação e os pagamentos dela (documentos do alerta pago_acima_liquidado)."""
    docs = [{"data": r["data"], "fase": "Liquidação", "doc": r["liquidacao"], "empenho": x["empenho"],
             "valor": round(r["valor"], 2), "especie": r["especie"] if r["especie"] not in (None, "", "Original") else None}
            for r in _q(conn, "SELECT data, liquidacao, valor, especie FROM liquidacoes WHERE unidade_gestora=? "
                              "AND empenho=? AND liquidacao=? ORDER BY data, valor, especie",
                        x["ug"], x["empenho"], x["liquidacao"])]
    docs += [{"data": r["data"], "fase": "Pagamento", "doc": r["pagamento"], "empenho": x["empenho"],
              "valor": round(r["valor"], 2), "especie": r["especie"] if r["especie"] not in (None, "", "Original") else None}
             for r in _q(conn, "SELECT data, pagamento, valor, especie, tipo_pagamento FROM pagamentos "
                               "WHERE unidade_gestora=? AND empenho=? AND liquidacao=? "
                               "AND COALESCE(tipo_pagamento,'') NOT LIKE '%Extra%' ORDER BY data, pagamento, valor, especie",
                         x["ug"], x["empenho"], x["liquidacao"])]
    return [{k: v for k, v in d.items() if v is not None} for d in docs[:MAX_DOCS_ALERTA]]


def _periodo_execucao(conn, ug: str, empenho: str) -> str:
    """Mês (AAAA-MM) da linha do empenho na visão de execução: o do 1º documento do
    empenho; sem empenho na base (restos a pagar), o do 1º documento de restos."""
    p = _q(conn, "SELECT MIN(ano*100+mes) p FROM empenhos WHERE unidade_gestora=? AND empenho=?", ug, empenho)[0]["p"]
    if not p:
        p = _q(conn, "SELECT MIN(p) p FROM (SELECT MIN(ano*100+mes) p FROM liquidacoes WHERE unidade_gestora=? "
                     "AND empenho=? AND tipo_liquidacao LIKE 'Restos%' UNION ALL SELECT MIN(ano*100+mes) FROM "
                     "pagamentos WHERE unidade_gestora=? AND empenho=? AND tipo_pagamento LIKE 'Restos%')",
               ug, empenho, ug, empenho)[0]["p"]
    return f"{p // 100}-{p % 100:02d}" if p else ""


# ── Publicação: prioridade e tetos ────────────────────────────────────────────
ORDEM_SEVERIDADE = {"alta": 0, "media": 1, "baixa": 2}
ORDEM_CLASSE = {CLASSE_INCONSISTENCIA: 0, CLASSE_ANOMALIA: 1, CLASSE_CONTEXTO: 2}
# só "novo" sobe na fila: sem histórico (idade desconhecida) empata com persistente
ORDEM_ESTADO = {"novo": 0, "sem_historico": 1, "persistente": 1}   # sem estado = 1 (neutro)


def _prioridade_publicacao(a: dict) -> tuple:
    """Dentro da regra: novo antes de persistente, depois a prioridade própria da regra
    (valor, na maioria); provável compra por ata (etiqueta do PNCP) ou contrato publicado
    no portal (provável execução contratual) por último."""
    return (a.get("etiqueta") == "provavel_ata" or bool(a.get("contrato")), ORDEM_ESTADO.get(a.get("estado"), 1),
            a.get("_ordem") or (-(a.get("valor") or 0),))


def publicar(cands: list[dict], contagem: dict | None = None) -> list[dict]:
    """Escolhe os alertas publicados entre os candidatos: por regra, os CAP_POR_REGRA
    (ou CAP_ESPECIAL) primeiros em _prioridade_publicacao; depois o teto global
    MAX_ALERTAS, que corta "contexto" primeiro. Só os publicados ganham documentos e
    link do recorte (consultas caras). Se `contagem` for um dict, recebe por regra
    {"candidatos": N, "publicados": M} — o painel diz quantos ficaram de fora."""
    por_tipo: dict[str, list] = defaultdict(list)
    for a in cands:
        por_tipo[a["tipo"]].append(a)
    escolhidos = []
    for tipo, lista in por_tipo.items():
        lista = sorted(lista, key=_prioridade_publicacao)
        escolhidos += lista if tipo in SEM_TETO else lista[:CAP_ESPECIAL.get(tipo, CAP_POR_REGRA)]
    escolhidos.sort(key=lambda a: (ORDEM_CLASSE.get(a["classe"], 9), ORDEM_SEVERIDADE.get(a["severidade"], 9),
                                   a.get("etiqueta") == "provavel_ata", ORDEM_ESTADO.get(a.get("estado"), 1),
                                   -(a.get("valor") or 0)))
    pub = escolhidos[:MAX_ALERTAS]
    for a in pub:
        completar = a.pop("_completar", None)
        if completar:
            completar(a)
        a.pop("_ordem", None)
    pub.sort(key=lambda a: (ORDEM_SEVERIDADE.get(a["severidade"], 9), ORDEM_CLASSE.get(a["classe"], 9),
                            a.get("etiqueta") == "provavel_ata", ORDEM_ESTADO.get(a.get("estado"), 1),
                            -(a.get("valor") or 0)))
    if contagem is not None:
        n_pub = Counter(a["tipo"] for a in pub)
        for tipo, lista in por_tipo.items():
            contagem[tipo] = {"candidatos": len(lista), "publicados": n_pub.get(tipo, 0)}
    return pub


def alertas(conn, ident: dict | None = None, cob: dict | None = None,
            execucao: dict | None = None, contagem: dict | None = None,
            prazos: dict | None = None) -> list[dict]:
    """Alertas PUBLICADOS (candidatos_alertas + publicar), sem histórico — a mesma
    assinatura e o mesmo retorno de sempre (briefing e testes dependem). O export
    aplica o histórico sobre TODOS os candidatos antes de publicar (ver main)."""
    return publicar(candidatos_alertas(conn, ident, cob, execucao, prazos), contagem)


def aplicar_historico_alertas(lista: list[dict], caminho: str = None, hoje: str = None) -> dict:
    """Marca cada alerta como novo / persistente (ou sem_historico quando não há
    arquivo de estado) e atualiza despesas/alertas-estado.json. Devolve o bloco
    `alertas_historico` do índice. O export passa TODOS os candidatos (não só os
    publicados): um alerta que o teto deixou de fora continua ativo — não vira
    "resolvido" nem volta como "novo". Continuidade entre versões de regra: alerta
    com `ids_anteriores` herda o `primeiro_em` do id antigo, que sai do estado sem ir
    para os resolvidos. Sem `ultimo_em`: a data mudava em todas as linhas todo dia."""
    caminho = caminho or ALERTAS_ESTADO_PATH
    hoje = hoje or date.today().isoformat()
    estado = {"alertas": {}, "resolvidos": {}}
    disponivel = False
    versao = 2
    if os.path.exists(caminho):
        try:
            with open(caminho, encoding="utf-8") as f:
                lido = json.load(f)
            estado["alertas"] = lido.get("alertas") or {}
            estado["resolvidos"] = lido.get("resolvidos") or {}
            disponivel = bool(estado["alertas"] or estado["resolvidos"])
            versao = lido.get("versao") or 1
        except (OSError, ValueError):
            pass
    # estado v1 (até 2026-10) guardava só os PUBLICADOS: na migração, um candidato fora
    # dele não é necessariamente novo — fica "sem_historico" (sem selo) por um dia
    so_publicados = disponivel and versao < 2
    atuais = {a["id"] for a in lista}
    migrados = set()
    novos = persistentes = 0
    for a in lista:
        h = estado["alertas"].get(a["id"])
        if not h:
            for velho in a.get("ids_anteriores") or ():
                hv = estado["alertas"].get(velho)
                if hv:
                    migrados.add(velho)
                    if not h or hv.get("primeiro_em", hoje) < h.get("primeiro_em", hoje):
                        h = hv
        if h:
            a["estado"], a["primeiro_em"] = "persistente", h.get("primeiro_em", hoje)
            persistentes += 1
        elif disponivel and not so_publicados:
            a["estado"], a["primeiro_em"] = "novo", hoje
            novos += 1
        else:
            a["estado"], a["primeiro_em"] = "sem_historico", hoje
        estado["alertas"][a["id"]] = {"primeiro_em": a["primeiro_em"], "tipo": a["tipo"], "titulo": a["titulo"]}
    resolvidos_agora = []
    for aid in list(estado["alertas"]):
        if aid not in atuais:
            h = estado["alertas"].pop(aid)
            if aid in migrados:          # o mesmo achado, agora com o id da regra nova
                continue
            h["resolvido_em"] = hoje
            estado["resolvidos"][aid] = h
            resolvidos_agora.append(dict(h, id=aid))
    # mantém só os 200 resolvidos mais recentes
    if len(estado["resolvidos"]) > 200:
        ordenados = sorted(estado["resolvidos"].items(), key=lambda kv: kv[1].get("resolvido_em", ""))
        estado["resolvidos"] = dict(ordenados[-200:])
    desde = min((h.get("primeiro_em", hoje) for h in estado["alertas"].values()), default=hoje)
    # versao 2 = guarda TODOS os candidatos (até 2026-10, só os publicados)
    gravar_json_se_mudou(caminho, {"versao": 2, "atualizado_em": hoje, "alertas": estado["alertas"],
                                   "resolvidos": estado["resolvidos"]}, indent=1)
    recentes = sorted(estado["resolvidos"].items(), key=lambda kv: kv[1].get("resolvido_em", ""), reverse=True)[:20]
    return {"disponivel": disponivel, "desde": desde if disponivel else None,
            "novos": novos, "persistentes": persistentes,
            "resolvidos_recentes": [dict(v, id=k) for k, v in recentes],
            "nota": (None if disponivel else
                     "Sem histórico anterior de alertas: não é possível dizer quais são novos.")}


# ── Todos os candidatos (despesas/alertas-candidatos.json → CSV no painel) ────
CAMPOS_CANDIDATOS = ["id", "tipo", "classe", "severidade", "estado", "primeiro_em", "publicado", "valor",
                     "titulo", "favorecido", "documento", "unidade", "elemento", "ano", "etiqueta", "link"]


def exportar_candidatos(cands: list[dict], publicados: list[dict], caminho: str | None = None) -> int:
    """Grava todos os casos que acionaram as regras — os tetos mostram só uma parte no
    painel, e a linha do teto oferece o resto em CSV. Compacto (campos + linhas) e só
    regrava se mudou (o carimbo não conta)."""
    pub = {a["id"] for a in publicados}
    linhas = []
    for a in sorted(cands, key=lambda a: (a["tipo"], a["id"] not in pub, ORDEM_ESTADO.get(a.get("estado"), 1),
                                          -(a.get("valor") or 0))):
        f = a.get("filtro") or {}
        linhas.append([a["id"], a["tipo"], a["classe"], a["severidade"], a.get("estado"), a.get("primeiro_em"),
                       a["id"] in pub, a.get("valor"), a.get("titulo"), f.get("favorecido"), f.get("documento"),
                       f.get("unidade"), f.get("elemento"), f.get("ano"), a.get("etiqueta"), a.get("link")])
    gravar_json_se_mudou(caminho or ALERTAS_CANDIDATOS_PATH,
                         {"atualizado_em": datetime.now().isoformat(timespec="seconds"),
                          "campos": CAMPOS_CANDIDATOS, "linhas": linhas}, separators=(",", ":"))
    return len(linhas)


# ── Publicidade (só agregados — decisão do usuário, 2026-10) ──────────────────
# Elementos 3.3.90.39.88 (serviços de propaganda) e 3.3.90.39.90 (publicidade legal:
# editais, balanços, atos oficiais). Nenhum sinal sobre empresas: só quanto, quando
# e a quem, pela data do pagamento (inclui restos a pagar).
ELEM_PUBLICIDADE = {"33903988": "propaganda", "33903990": "legal"}
PUB_TOP_FAVORECIDOS = 10


def publicidade(conn, ident: dict, cob: dict | None = None) -> dict | None:
    """Bloco `publicidade` do índice: por ano, mesmo período do ano anterior (jan–M do
    último mês completo, sem os meses incompletos na origem), série mensal e
    favorecidos (por identidade)."""
    incompletos = _incompletos(cob)
    cond = " OR ".join(f"p.elemento_despesa LIKE '{c}%'" for c in ELEM_PUBLICIDADE)
    tipo = lambda el: ELEM_PUBLICIDADE.get((el or "")[:8], "propaganda")  # noqa: E731
    rows = _q(conn, f"SELECT p.ano, p.mes, p.elemento_despesa el, SUM(p.valor) s, COUNT(*) n "
                    f"FROM pagamentos p WHERE {cond} GROUP BY 1, 2, 3")
    if not rows:
        return None
    nomes_elem = {tipo(r["el"]): r["el"] for r in rows}
    lim = _q(conn, "SELECT MIN(ano*100+mes) i, MAX(ano*100+mes) f FROM pagamentos")[0]
    mensal: dict[int, dict] = {}
    p = lim["i"]
    while p and p <= lim["f"]:      # todos os meses da base (lacuna = 0)
        mensal[p] = {"ano": p // 100, "mes": p % 100, "propaganda": 0.0, "legal": 0.0}
        p = p + 1 if p % 100 < 12 else (p // 100 + 1) * 100 + 1
    por_ano: dict[str, dict] = {}
    for r in rows:
        m = mensal.setdefault(r["ano"] * 100 + r["mes"], {"ano": r["ano"], "mes": r["mes"],
                                                          "propaganda": 0.0, "legal": 0.0})
        m[tipo(r["el"])] = round(m[tipo(r["el"])] + r["s"], 2)
        a = por_ano.setdefault(str(r["ano"]), {"propaganda": 0.0, "legal": 0.0, "total": 0.0, "pagamentos": 0})
        a[tipo(r["el"])] = round(a[tipo(r["el"])] + r["s"], 2)
        a["total"] = round(a["total"] + r["s"], 2)
        a["pagamentos"] += r["n"]
    serie = [mensal[k] for k in sorted(mensal)]
    comparacao = None
    completo = _mes_completo_ate(conn)
    if completo:
        ano, mes = completo
        comp = [m for m in range(1, mes + 1) if (ano, m) not in incompletos and (ano - 1, m) not in incompletos]
        soma = lambda a, c: round(sum(s[c] for s in serie if s["ano"] == a and s["mes"] in comp), 2)  # noqa: E731
        atual = {c: soma(ano, c) for c in ("propaganda", "legal")}
        anterior = {c: soma(ano - 1, c) for c in ("propaganda", "legal")}
        t_at, t_an = round(sum(atual.values()), 2), round(sum(anterior.values()), 2)
        if comp and any(s["ano"] == ano - 1 for s in serie):
            comparacao = {"ano": ano, "mes": mes, "atual": t_at, "anterior": t_an,
                          "pct": round(100 * (t_at - t_an) / t_an) if t_an > 0 else None,
                          "periodo": _rotulo_periodo(comp),
                          "por_tipo": {c: {"atual": atual[c], "anterior": anterior[c]} for c in atual}}
    fav = []
    for r in _q(conn, f"SELECT fi.chave k, SUM(p.valor) s, COUNT(*) n, "
                      f"SUM(CASE WHEN p.elemento_despesa LIKE '33903990%' THEN p.valor ELSE 0 END) legal "
                      f"FROM pagamentos p {FAV_JOIN.format(t='p')} WHERE {cond} "
                      f"GROUP BY fi.chave ORDER BY s DESC LIMIT ?", PUB_TOP_FAVORECIDOS):
        fav.append(_marcar_ente_publico(dict(_fav_campos(ident, r["k"]), valor=round(r["s"], 2), qtd=r["n"],
                                             legal=round(r["legal"], 2), propaganda=round(r["s"] - r["legal"], 2))))
    return {"elementos": nomes_elem, "por_ano": por_ano, "comparacao": comparacao, "serie": serie,
            "favorecidos": fav,
            "criterio": ("Pagamentos nos elementos 3.3.90.39.88 (serviços de propaganda) e 3.3.90.39.90 "
                         "(publicidade legal), pela data do pagamento, incluindo restos a pagar. O portal não "
                         "informa campanha, veículo nem peça — só quanto, quando e a quem.")}


# ── Histórico versionado de alterações da origem (só-acréscimo) ───────────────
# O SQLite (com `linhas_historico`) vive no cache do Actions, que o GitHub apaga após
# 7 dias sem uso: o que a origem removeu ou corrigiu sumiria junto. Aqui o histórico
# vai para despesas/historico/alteracoes-AAAA.jsonl.gz (AAAA = ano da partição) e só
# CRESCE: lê o versionado e acrescenta o que ainda não está lá; nunca apaga.
CAMPOS_HISTORICO = {"unidade_gestora": "ug", "empenho": "emp", "liquidacao": "liq", "pagamento": "pag",
                    "data": "data", "especie": "esp", "valor": "valor", "nome_favorecido": "fav",
                    "documento_favorecido": "doc", "elemento_despesa": "elem",
                    "tipo_empenho": "tipo", "tipo_liquidacao": "tipo", "tipo_pagamento": "tipo"}


def exportar_historico_alteracoes(conn, diretorio: str | None = None) -> dict:
    """Acrescenta ao histórico versionado as linhas de `linhas_historico` com motivo
    `removido`/`substituido` (a duplicidade sistemática fica de fora — já está na
    cobertura). Descarta o artefato de largura do nº (7→8 dígitos em 2026-09-30, e a
    volta à largura histórica depois da correção): a linha que, normalizada, ainda
    existe na partição não mudou de verdade. Campos enxutos; chave de deduplicação =
    (hash, repetição, motivo, registrado_em). Devolve {ano: linhas acrescentadas}."""
    import crawler   # mesma normalização e mesmo hash do crawler (import tardio: só aqui)
    diretorio = diretorio or HISTORICO_DIR
    # a pasta existe sempre: o `git add despesas/historico` do workflow falha se ela faltar
    os.makedirs(diretorio, exist_ok=True)
    tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "linhas_historico" not in tabelas:
        return {}
    existentes: dict[str, list] = {}
    chaves: set = set()
    for arq in sorted(glob.glob(os.path.join(diretorio, "alteracoes-*.jsonl.gz"))):
        ano = os.path.basename(arq)[len("alteracoes-"):-len(".jsonl.gz")]
        with gzip.open(arq, "rt", encoding="utf-8") as f:
            existentes[ano] = [ln for ln in f.read().splitlines() if ln.strip()]
        for ln in existentes[ano]:
            d = json.loads(ln)
            chaves.add((d.get("h"), d.get("r"), d.get("m"), d.get("em")))
    hashes_atuais: dict[tuple, set] = {}

    def atuais(fonte, ano, mes):
        k = (fonte, ano, mes)
        if k not in hashes_atuais:
            hashes_atuais[k] = {r[0] for r in conn.execute(
                f"SELECT hash FROM {crawler.STREAMS[fonte]['tabela']} WHERE ano=? AND mes=?", (ano, mes))}
        return hashes_atuais[k]

    novos: dict[str, list] = defaultdict(list)
    for r in conn.execute("SELECT fonte, ano, mes, motivo, registrado_em, hash, repeticao, conteudo "
                          "FROM linhas_historico WHERE motivo IN ('removido', 'substituido') ORDER BY id"):
        fonte, ano, mes, motivo, em, h, rep, conteudo = r
        if (h, rep, motivo, em) in chaves or fonte not in crawler.STREAMS:
            continue
        chaves.add((h, rep, motivo, em))
        try:
            linha = json.loads(conteudo or "{}")
        except ValueError:
            continue
        norm = dict(linha)
        for c in crawler.CAMPOS_NUMERO_DOC:
            if c in norm:
                norm[c] = crawler.numero_documento(norm[c])
        norm["grupo_despesa"] = crawler.codigo_grupo(norm.get("grupo_despesa"))
        if crawler._hash_linha(fonte, norm) in atuais(fonte, ano, mes):
            continue        # a mesma linha (normalizada) segue na base: artefato de largura
        d = {"em": em, "f": fonte, "p": f"{ano}-{mes:02d}", "m": motivo, "h": h, "r": rep}
        for c, k in CAMPOS_HISTORICO.items():
            if linha.get(c) not in (None, ""):
                d[k] = linha[c]
        novos[str(ano)].append(json.dumps(d, ensure_ascii=False, sort_keys=True))
    for ano, linhas in novos.items():
        todas = existentes.get(ano, []) + linhas
        alvo = os.path.join(diretorio, f"alteracoes-{ano}.jsonl.gz")
        buf = io.BytesIO()
        # mtime=0: sem carimbo no cabeçalho gzip (bytes idênticos a cada regravação)
        with gzip.GzipFile(filename=os.path.basename(alvo), mode="wb", fileobj=buf, mtime=0) as f:
            f.write(("\n".join(todas) + "\n").encode("utf-8"))
        gravar_bytes(alvo, buf.getvalue())
    return {ano: len(v) for ano, v in novos.items()}


# ── Árvore do gasto (função → subfunção → elemento) p/ o treemap ──────────────
# Gravada em arquivo próprio (despesas/arvore.json) para não inchar o índice:
# são ~100 subfunções; os elementos são limitados ao top-N + "Demais" por
# subfunção. Folhas com soma ≤ 0 (anulações líquidas) são absorvidas em "Demais".
TOP_ELEM_ARVORE = 10

def exportar_arvore(conn, indice: dict) -> int:
    rows = _q(conn, """
        SELECT COALESCE(NULLIF(funcao,''),'(sem função)') f,
               COALESCE(NULLIF(subfuncao,''),'(sem subfunção)') sf,
               COALESCE(NULLIF(elemento_despesa,''),'(sem elemento)') e,
               ROUND(SUM(valor),2) s
        FROM pagamentos GROUP BY f, sf, e""")
    arvore: dict[str, dict] = {}
    for r in rows:
        fn = arvore.setdefault(r["f"], {"n": r["f"], "v": 0, "f": {}})
        sf = fn["f"].setdefault(r["sf"], {"n": r["sf"], "v": 0, "f": []})
        fn["v"] = round(fn["v"] + r["s"], 2)
        sf["v"] = round(sf["v"] + r["s"], 2)
        sf["f"].append({"n": r["e"], "v": r["s"]})

    saida = []
    for fn in sorted(arvore.values(), key=lambda x: -x["v"]):
        subs = []
        for sf in sorted(fn["f"].values(), key=lambda x: -x["v"]):
            folhas = sorted(sf["f"], key=lambda x: -x["v"])
            top = [x for x in folhas[:TOP_ELEM_ARVORE] if x["v"] > 0]
            resto = round(sum(x["v"] for x in folhas[TOP_ELEM_ARVORE:]) +
                          sum(x["v"] for x in folhas[:TOP_ELEM_ARVORE] if x["v"] <= 0), 2)
            if resto > 0:
                top.append({"n": "Demais elementos", "v": resto})
            subs.append({"n": sf["n"], "v": sf["v"], "f": top})
        saida.append({"n": fn["n"], "v": fn["v"], "f": subs})

    gravar_json_se_mudou(ARVORE_PATH, {"atualizado_em": indice.get("atualizado_em"),
                                       "total": indice.get("totais", {}).get("geral"),
                                       "arvore": saida}, separators=(",", ":"))
    return len(saida)


# ── Execução por empenho (empenhado / liquidado / pago) ───────────────────────
# Unidade da linha = o EMPENHO, no mês em que foi emitido (_periodo), com tudo o
# que já foi liquidado/pago dele até a data da base. Inclui o que não casa com
# empenho da base, classificado pelo CAMPO DA FONTE (nunca inferido só do nº):
#   - "Restos a pagar": tipo da fonte diz restos (exercício de origem anterior)
#   - "Extra-orçamentário": tipo da fonte diz extra (retenções, consignações)
#   - "Empenho não localizado na base": orçamentário cujo empenho não veio no endpoint
CAMPOS_DETALHE = [
    "data", "unidade_gestora", "tipo", "nome_favorecido", "documento_favorecido",
    "funcao", "subfuncao", "programa", "elemento_despesa", "fonte_recurso",
    "grupo_despesa", "empenho", "empenhado", "liquidado", "pago",
]
COLS_NUM = {"empenhado", "liquidado", "pago"}


def montar_execucao(conn) -> list[dict]:
    """Devolve uma linha por empenho (+ não casados), com _periodo (AAAAMM do empenho)."""
    rows = []
    # 1) Empenhos da base, com liquidado e pago somados por empenho.
    for r in _q(conn, """
        SELECT e.unidade_gestora, e.empenho, e.periodo, e.data, e.favorecido, e.doc,
               e.funcao, e.subfuncao, e.programa, e.elemento, e.fonte, e.grupo,
               e.empenhado, e.originais,
               COALESCE(l.liquidado, 0) liquidado, COALESCE(p.pago, 0) pago
        FROM (
            SELECT unidade_gestora, empenho, MIN(ano*100+mes) periodo, MIN(data) data,
                   MAX(nome_favorecido) favorecido, MAX(documento_favorecido) doc,
                   MAX(funcao) funcao, MAX(subfuncao) subfuncao, MAX(programa) programa,
                   MAX(elemento_despesa) elemento, MAX(fonte_recurso) fonte,
                   MAX(grupo_despesa) grupo, ROUND(SUM(valor), 2) empenhado,
                   SUM(CASE WHEN especie='Original' OR especie IS NULL OR especie='' THEN 1 ELSE 0 END) originais
            FROM empenhos GROUP BY unidade_gestora, empenho
        ) e
        LEFT JOIN (SELECT unidade_gestora, empenho, ROUND(SUM(valor),2) liquidado
                   FROM liquidacoes GROUP BY unidade_gestora, empenho) l
          ON l.unidade_gestora = e.unidade_gestora AND l.empenho = e.empenho
        LEFT JOIN (SELECT unidade_gestora, empenho, ROUND(SUM(valor),2) pago
                   FROM pagamentos WHERE empenho IS NOT NULL AND empenho <> ''
                   GROUP BY unidade_gestora, empenho) p
          ON p.unidade_gestora = e.unidade_gestora AND p.empenho = e.empenho
    """):
        rows.append({"_periodo": r["periodo"], "data": r["data"],
                     "unidade_gestora": r["unidade_gestora"],
                     "tipo": T_EMPENHO if r["originais"] else T_EMPENHO_PARCIAL,
                     "nome_favorecido": r["favorecido"], "documento_favorecido": r["doc"],
                     "funcao": r["funcao"], "subfuncao": r["subfuncao"], "programa": r["programa"],
                     "elemento_despesa": r["elemento"], "fonte_recurso": r["fonte"],
                     "grupo_despesa": r["grupo"], "empenho": r["empenho"],
                     "empenhado": r["empenhado"], "liquidado": r["liquidado"], "pago": r["pago"]})

    # 2) Liquidações e pagamentos que NÃO casam com empenho da base — agrupados por
    # (UG, nº de empenho, tipo) quando há nº (o "pseudo-empenho" recebe tudo, no mês
    # do 1º documento), e por documento quando não há nº.
    todos, _ = _empenhos_na_base(conn)
    grupos: dict[tuple, dict] = {}

    def acumular(fonte, campo_valor, campo_tipo):
        # colunas fora do GROUP BY com MAX() e ORDER BY total: coluna "solta" no SQLite vem de
        # uma linha arbitrária do grupo (a ordem física) e o arquivo mudava sem dado novo
        for r in _q(conn, f"""
            SELECT unidade_gestora, empenho, ano*100+mes periodo, data, nome_favorecido,
                   MAX(documento_favorecido) documento_favorecido, MAX(funcao) funcao,
                   MAX(subfuncao) subfuncao, MAX(programa) programa, elemento_despesa,
                   MAX(fonte_recurso) fonte_recurso, MAX(grupo_despesa) grupo_despesa,
                   {campo_tipo} tipo_fonte, ROUND(SUM(valor),2) v
            FROM {fonte}
            GROUP BY unidade_gestora, empenho, ano, mes, data, nome_favorecido, elemento_despesa, {campo_tipo}
            ORDER BY unidade_gestora, empenho, ano, mes, data, nome_favorecido, elemento_despesa, {campo_tipo}"""):
            emp = r["empenho"] or ""
            if emp and f"{r['unidade_gestora']}|{emp}" in todos:
                continue
            tipo = classificar_documento(r["tipo_fonte"], emp, False)
            chave = (r["unidade_gestora"], emp, tipo) if emp else \
                    (r["unidade_gestora"], "", tipo, r["periodo"], r["data"], r["nome_favorecido"], r["elemento_despesa"])
            g = grupos.get(chave)
            if not g:
                g = {"_periodo": r["periodo"], "data": r["data"],
                     "unidade_gestora": r["unidade_gestora"], "tipo": tipo,
                     "nome_favorecido": r["nome_favorecido"], "documento_favorecido": r["documento_favorecido"],
                     "funcao": r["funcao"], "subfuncao": r["subfuncao"], "programa": r["programa"],
                     "elemento_despesa": r["elemento_despesa"], "fonte_recurso": r["fonte_recurso"],
                     "grupo_despesa": r["grupo_despesa"], "empenho": emp,
                     "empenhado": None, "liquidado": None, "pago": None}
                grupos[chave] = g
            if (r["periodo"], r["data"]) < (g["_periodo"], g["data"] or ""):
                g["_periodo"], g["data"] = r["periodo"], r["data"]
            g[campo_valor] = round((g[campo_valor] or 0) + r["v"], 2)

    acumular("liquidacoes", "liquidado", "tipo_liquidacao")
    acumular("pagamentos", "pago", "tipo_pagamento")
    rows.extend(grupos.values())
    for g in rows:
        if g["pago"] is None and g["tipo"] not in (T_EMPENHO, T_EMPENHO_PARCIAL):
            g["pago"] = 0.0
    rows.sort(key=lambda x: (x["_periodo"], x["data"] or "", -(x["pago"] or 0),
                             *(str(x.get(c)) for c in CAMPOS_DETALHE)))   # empate: ordem total
    return rows


# ── Movimentação no período (um documento por linha, pela data do estágio) ────
CAMPOS_MOV = [
    "data", "fase", "especie", "unidade_gestora", "tipo", "nome_favorecido", "documento_favorecido",
    "funcao", "subfuncao", "programa", "elemento_despesa", "fonte_recurso", "grupo_despesa",
    "empenho", "documento", "empenhado", "liquidado", "pago", "periodo_empenho",
]
# colunas codificadas por dicionário nos arquivos mensais (reduz ~4× o tamanho)
MOV_DICIONARIO = ["unidade_gestora", "nome_favorecido", "documento_favorecido", "funcao",
                  "subfuncao", "programa", "elemento_despesa", "fonte_recurso", "grupo_despesa"]


def montar_movimento(conn) -> list[dict]:
    """Uma linha por documento de estágio (E/L/P) no mês da PRÓPRIA data. Um empenho de
    janeiro pago em agosto gera a linha E em janeiro e a linha P em agosto."""
    todos, originais = _empenhos_na_base(conn)
    periodo_emp = {}
    for r in _q(conn, "SELECT unidade_gestora ug, empenho e, MIN(ano*100+mes) p FROM empenhos GROUP BY ug, e"):
        periodo_emp[f"{r['ug']}|{r['e']}"] = r["p"]
    rows = []
    comuns = ("unidade_gestora, data, especie, empenho, elemento_despesa, funcao, subfuncao, programa, "
              "fonte_recurso, grupo_despesa, documento_favorecido, nome_favorecido, valor, ano*100+mes periodo")
    for r in _q(conn, f"SELECT {comuns}, empenho documento, tipo_empenho FROM empenhos"):
        k = f"{r['unidade_gestora']}|{r['empenho']}"
        rows.append(_linha_mov(r, "E", T_EMPENHO if k in originais else T_EMPENHO_PARCIAL,
                               r["documento"], periodo_emp.get(k), empenhado=r["valor"]))
    for r in _q(conn, f"SELECT {comuns}, liquidacao documento, tipo_liquidacao tf FROM liquidacoes"):
        k = f"{r['unidade_gestora']}|{r['empenho']}"
        rows.append(_linha_mov(r, "L", classificar_documento(r["tf"], r["empenho"], k in todos),
                               r["documento"], periodo_emp.get(k), liquidado=r["valor"]))
    for r in _q(conn, f"SELECT {comuns}, pagamento documento, tipo_pagamento tf FROM pagamentos"):
        k = f"{r['unidade_gestora']}|{r['empenho']}"
        rows.append(_linha_mov(r, "P", classificar_documento(r["tf"], r["empenho"], k in todos),
                               r["documento"], periodo_emp.get(k), pago=r["valor"]))
    # ordem TOTAL pelo conteúdo: (mês, data, fase) e, no empate, todas as colunas. Sem
    # isto o empate saía na ordem física do SQLite — que muda a cada recarga do ano
    # corrente — e os arquivos de dados/mov/ eram regravados todo dia sem dado novo
    # (dicionário pela 1ª aparição reembaralhado): ~35 MiB/mês no histórico em out/2026.
    rows.sort(key=lambda x: (x["_periodo"], x["data"] or "", x["fase"], *(str(x.get(c)) for c in CAMPOS_MOV)))
    return rows


def _linha_mov(r, fase, tipo, documento, periodo_emp, empenhado=None, liquidado=None, pago=None) -> dict:
    return {"_periodo": r["periodo"], "data": r["data"], "fase": fase,
            "especie": r["especie"] or "Original", "unidade_gestora": r["unidade_gestora"], "tipo": tipo,
            "nome_favorecido": r["nome_favorecido"], "documento_favorecido": r["documento_favorecido"],
            "funcao": r["funcao"], "subfuncao": r["subfuncao"], "programa": r["programa"],
            "elemento_despesa": r["elemento_despesa"], "fonte_recurso": r["fonte_recurso"],
            "grupo_despesa": r["grupo_despesa"], "empenho": r["empenho"] or "", "documento": documento or "",
            "empenhado": empenhado, "liquidado": liquidado, "pago": pago,
            "periodo_empenho": periodo_emp}


def exportar_movimento_mensal(rows: list[dict]) -> list[dict]:
    """Grava despesas/dados/mov/AAAA-MM.json (dicionário + linhas) e devolve o manifesto."""
    os.makedirs(MOV_DIR, exist_ok=True)
    por_mes: dict[int, list] = {}
    for r in rows:
        por_mes.setdefault(r["_periodo"], []).append(r)
    validos = {f"{p // 100}-{p % 100:02d}.json" for p in por_mes}
    for nome in os.listdir(MOV_DIR):
        if nome.endswith(".json") and nome not in validos:
            os.remove(os.path.join(MOV_DIR, nome))
    manifesto = []
    idx_dic = {c: CAMPOS_MOV.index(c) for c in MOV_DICIONARIO}
    for periodo in sorted(por_mes):
        ano, mes = periodo // 100, periodo % 100
        dic = {c: {} for c in MOV_DICIONARIO}
        linhas = []
        for r in por_mes[periodo]:
            linha = [r.get(c) for c in CAMPOS_MOV]
            for c, i in idx_dic.items():
                v = linha[i]
                d = dic[c]
                if v not in d:
                    d[v] = len(d)
                linha[i] = d[v]
            linhas.append(linha)
        arquivo = f"{ano}-{mes:02d}.json"
        gravar_json(os.path.join(MOV_DIR, arquivo),
                    {"campos": CAMPOS_MOV, "dicionario": {c: list(d) for c, d in dic.items()}, "linhas": linhas},
                    separators=(",", ":"))
        soma = {c: round(sum((r[c] or 0) for r in por_mes[periodo]), 2) for c in ("empenhado", "liquidado", "pago")}
        manifesto.append({"ano": ano, "mes": mes, "n": len(linhas), **soma,
                          "bytes": os.path.getsize(os.path.join(MOV_DIR, arquivo)),
                          "arquivo": f"despesas/dados/mov/{arquivo}"})
    return manifesto


# ── Cubo do Explorador de pagamentos (despesas/dados/cubo/AAAA.json) ──────────
# Os PAGAMENTOS de um ano (fase P da movimentação: as mesmas linhas de dados/mov/, no
# mês da partição = pela data do pagamento) agregados por mês × unidade gestora × tipo ×
# favorecido × função × subfunção × programa × elemento × fonte × grupo, com `pago`
# (soma em centavos inteiros → 2 casas exatas) e `n` (nº de documentos). É a tabela que
# o explorador.html monta no SQLite do navegador (~30 mil linhas/ano em vez de ~75 mil
# documentos). Colunas textuais por dicionário, como em dados/mov/; o favorecido é a
# IDENTIDADE (formato.identidade_favorecido), publicada como [chave, nome, documento] — a
# chave do ranking/dossiês (agrupar só por nome ou só por CPF mascarado funde pessoas), o
# nome de exibição do ranking e o documento como a origem o publica (CPF mascarado): nada
# que dados/mov/ e nomes-favorecidos.json já não publiquem. Vazio vira null (a função "(sem função)" do extra-orçamentário). Serialização
# determinística (ordem das linhas e dos dicionários só depende do dado): mesmo dado →
# mesmos bytes, então o ano fechado não vira diff diário no git.
CAMPOS_CUBO = ["mes", "unidade_gestora", "tipo", "favorecido", "funcao", "subfuncao", "programa",
               "elemento_despesa", "fonte_recurso", "grupo_despesa", "pago", "n"]
CUBO_DICIONARIO = CAMPOS_CUBO[1:10]     # colunas por dicionário (mes, pago e n vão como número)
CUBO_VERSAO = 1


def montar_cubos(rows: list[dict], ident: dict) -> dict:
    """{ano: objeto do cubo} a partir das linhas de montar_movimento (só a fase P)."""
    agg: dict = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # ano → chave → [centavos, n]
    for r in rows:
        if r["fase"] != "P":
            continue
        nome, doc = r.get("nome_favorecido") or "", r.get("documento_favorecido") or ""
        chave = identidade_favorecido(nome, doc)[0]
        o = ident.get(chave)
        fav = (chave, o["nome"], o["documento"] or "") if o else (chave, nome, doc)
        k = (r["_periodo"] % 100, r["unidade_gestora"] or None, r["tipo"] or None, fav,
             r["funcao"] or None, r["subfuncao"] or None, r["programa"] or None,
             r["elemento_despesa"] or None, r["fonte_recurso"] or None, r["grupo_despesa"] or None)
        a = agg[r["_periodo"] // 100][k]
        a[0] += round((r["pago"] or 0) * 100)
        a[1] += 1

    def ordem(item):   # mês, maior valor primeiro, depois o texto (desempate total e estável)
        k, (centavos, _) = item
        return (k[0], -centavos, tuple("\x1f".join(v) if isinstance(v, tuple) else (v or "") for v in k[1:]))

    cubos = {}
    for ano in sorted(agg):
        dic = {c: {} for c in CUBO_DICIONARIO}
        linhas = []
        for k, (centavos, n) in sorted(agg[ano].items(), key=ordem):
            lin = [k[0]]
            for campo, v in zip(CUBO_DICIONARIO, k[1:]):
                d = dic[campo]
                if v not in d:
                    d[v] = len(d)   # 1ª aparição: os maiores valores ganham os índices curtos
                lin.append(d[v])
            lin += [centavos // 100 if centavos % 100 == 0 else centavos / 100, n]
            linhas.append(lin)
        cubos[ano] = {"versao": CUBO_VERSAO, "ano": ano, "campos": CAMPOS_CUBO,
                      "campos_favorecido": ["chave", "nome", "documento"],
                      "dicionario": {c: [list(v) if isinstance(v, tuple) else v for v in d]
                                     for c, d in dic.items()},
                      "linhas": linhas}
    return cubos


def exportar_cubos(rows: list[dict], ident: dict) -> list[dict]:
    """Grava dados/cubo/AAAA.json (só se os bytes mudaram) e devolve o manifesto do
    índice (`cubos`): ano, arquivo, linhas, bytes, gzip (estimativa do download), pago, n."""
    pasta = os.path.join(DADOS_DIR, "cubo")   # segue o --saida (DADOS_DIR já é o do candidato)
    os.makedirs(pasta, exist_ok=True)
    cubos = montar_cubos(rows, ident)
    validos = {f"{a}.json" for a in cubos}
    for nome in os.listdir(pasta):
        if nome.endswith(".json") and nome not in validos:
            os.remove(os.path.join(pasta, nome))
    manifesto = []
    for ano, obj in cubos.items():
        dados = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        caminho = os.path.join(pasta, f"{ano}.json")
        try:
            with open(caminho, "rb") as f:
                igual = f.read() == dados
        except OSError:
            igual = False
        if not igual:
            gravar_bytes(caminho, dados)
        iP, iN = CAMPOS_CUBO.index("pago"), CAMPOS_CUBO.index("n")
        manifesto.append({"ano": ano, "arquivo": f"despesas/dados/cubo/{ano}.json",
                          "linhas": len(obj["linhas"]), "bytes": len(dados),
                          "gzip": len(gzip.compress(dados, 6, mtime=0)),
                          "pago": round(sum(l[iP] for l in obj["linhas"]), 2),
                          "n": sum(l[iN] for l in obj["linhas"])})
    return manifesto


# ── Calendário de pagamentos e caminho do dinheiro (M8, 2026-10) ──────────────
# Dois agregados pequenos do Visão geral, tirados das MESMAS linhas de pagamento (fase P)
# que vão para dados/mov/ — conservam por construção com a série mensal e com o pago do ano:
#   dados/calendario.json  pago e nº de documentos por DIA, mandato inteiro;
#   dados/fluxo.json       por ano: grupo da fonte → função → favorecido (identidade), SEM o
#                          extra-orçamentário (só transita pelo caixa), em duas variantes —
#                          todos e só fornecedores privados (sem formato.eh_ente_publico).
# O índice leva só o manifesto (`dados_graficos`: arquivo + bytes): sem ele o painel nem
# tenta baixar (é o caso do índice publicado antes do 1º export que gera os arquivos).
CAMPOS_CALENDARIO = ["dia", "pago", "n", "anulacoes"]   # n = documentos de pagamento (anulações inclusas)
# Grupo da fonte = prefixo AUDESP do código ("01-1100000 - GERAL" → "01"); 91–98 são os mesmos
# grupos com saldo de exercícios anteriores e vão juntos ("9x"). 01/02/04/05 seguem o glossário
# do painel; os demais, a tabela AUDESP conferida com as fontes de cada grupo na base (03 = FUNDURB,
# FEPAR e outros fundos; 07 = FINISA; 08 = metade Saúde, metade geral, como as emendas
# impositivas) [Verificar]. A dica do gráfico mostra as principais fontes de cada grupo.
GRUPOS_FONTE = {
    "01": "Tesouro municipal", "02": "Transferências estaduais", "03": "Fundos especiais",
    "04": "Adm. indireta (recursos próprios)", "05": "Transferências federais", "06": "Outras fontes",
    "07": "Operações de crédito", "08": "Emendas parlamentares", "9x": "Exercícios anteriores",
}
FLUXO_TOPOS = (8, 10, 15)     # grupos de fonte, funções e favorecidos por recorte; o resto vira "Demais"
FLUXO_DEMAIS = ("Demais fontes", "Demais funções", "Demais favorecidos")
FLUXO_FONTES_GRUPO = 3        # fontes que exemplificam cada grupo (dica do gráfico)


def _centavos(v: float) -> float:
    return round(v, 2) + 0.0   # + 0.0: o -0.0 de um arredondamento vira 0.0 (mesmos bytes)


def _dia_pagamento(r: dict) -> str:
    """Dia da linha DENTRO do mês da partição: a série mensal soma por partição (a consulta
    à API). A origem traz alguns pagamentos com a data de outro ano no mesmo mês (23 em
    out/2026, R$ 174 mil, todos extra-orçamentários — 25/04/2024 na partição abr/2025):
    contam no mesmo dia do mês consultado (dia fora do mês vai para o último dia dele)."""
    ano, mes = divmod(r["_periodo"], 100)
    ultimo = (date(ano + mes // 12, mes % 12 + 1, 1) - timedelta(days=1)).day
    try:
        dia = int((r["data"] or "")[8:10])
    except ValueError:
        dia = 1
    return f"{ano}-{mes:02d}-{min(max(dia, 1), ultimo):02d}"


def calendario_pagamentos(mov: list[dict]) -> dict:
    """Pago (líquido das anulações) e nº de documentos de pagamento por dia."""
    dias: dict[str, list] = {}
    redatados = [0, 0.0]
    for r in mov:
        if r["fase"] != "P":
            continue
        dia, v = _dia_pagamento(r), r["pago"] or 0.0
        if dia != (r["data"] or "")[:10]:
            redatados[0] += 1
            redatados[1] += v
        d = dias.setdefault(dia, [0.0, 0, 0])
        d[0] += v
        d[1] += 1
        d[2] += r["especie"] == "Anulação"
    linhas = [[dia, _centavos(v), n, a] for dia, (v, n, a) in sorted(dias.items())]
    return {"versao": 1, "campos": CAMPOS_CALENDARIO, "ate": linhas[-1][0] if linhas else None,
            # pagamentos com a data de outro ano na origem, contados no mês da partição
            "redatados": {"n": redatados[0], "pago": _centavos(redatados[1])},
            "linhas": linhas}


def _grupo_fonte(fonte) -> str:
    m = re.match(r"(\d{2})-", fonte or "")
    if not m:
        return "??"
    return "9x" if m.group(1).startswith("9") else m.group(1)


def _cod_funcao(funcao) -> str:
    """'10 - SAÚDE' → '10': o código une as grafias da mesma função."""
    m = re.match(r"\s*(\d+)\s*-", funcao or "")
    return m.group(1) if m else sem_acento(funcao or "(sem função)").strip()


def _sankey(linhas: list[tuple], ident: dict, tops_slugs: set, entes: set) -> dict:
    """Nós (3 níveis, maiores primeiro, a cauda em "Demais") e ligações de um recorte.
    `linhas`: (grupo, código da função, função, chave do favorecido, fonte, valor)."""
    soma = (defaultdict(float), defaultdict(float), defaultdict(float))
    nomes_funcao: dict[str, Counter] = defaultdict(Counter)
    soma_fontes: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for g, cf, f, k, fonte, v in linhas:
        soma[0][g] += v
        soma[1][cf] += v
        soma[2][k] += v
        nomes_funcao[cf][f] += 1
        soma_fontes[g][fonte] += v
    # em centavos logo de saída: a ordem (e o desempate) não depende da ordem das linhas
    tot = [{c: _centavos(v) for c, v in s.items()} for s in soma]
    fontes = {g: sorted(((f, _centavos(v)) for f, v in fs.items()), key=lambda fv: (-fv[1], fv[0]))
              for g, fs in soma_fontes.items()}
    prefixo = ("g:", "f:", "v:")
    nos, destino = [], ({}, {}, {})   # destino[nível]: código → id do nó (o próprio ou "Demais")
    for nivel in range(3):
        ordem = sorted(tot[nivel].items(), key=lambda kv: (-kv[1], kv[0]))
        topo = [c for c, v in ordem if v > 0][:FLUXO_TOPOS[nivel]]
        no_topo = set(topo)
        resto = [c for c, _ in ordem if c not in no_topo]
        if len(resto) == 1 and tot[nivel][resto[0]] > 0:
            topo.append(resto.pop())   # "Demais" de um só é ele mesmo
        for c in topo:
            # favorecido: id pelo slug do dossiê (estável entre exports, curto)
            no = {"id": prefixo[nivel] + (slug_favorecido(c) if nivel == 2 else c),
                  "nivel": nivel, "valor": tot[nivel][c]}
            if nivel == 0:
                no["nome"] = GRUPOS_FONTE.get(c, "Fonte sem grupo na origem")
                no["fontes"] = [[f, v] for f, v in fontes[c] if v > 0][:FLUXO_FONTES_GRUPO]
            elif nivel == 1:
                no["nome"] = nome_exibicao(nomes_funcao[c])
            else:   # raio-X: dossiê pré-computado (?f=) ou a rota por documento e nome
                fav = _fav_campos(ident, c)
                no.update(nome=fav["nome"], documento=fav["documento"], link=_link_fav(fav, tops_slugs))
                if c in entes:
                    no["ente_publico"] = True
            destino[nivel][c] = no["id"]
            nos.append(no)
        if resto:
            no = {"id": prefixo[nivel] + "demais", "nivel": nivel, "nome": FLUXO_DEMAIS[nivel], "demais": True,
                  "valor": _centavos(sum(tot[nivel][c] for c in resto))}
            if nivel == 0:
                no["inclui"] = [GRUPOS_FONTE.get(c, "Fonte sem grupo na origem") for c in resto]
            elif nivel == 1:
                no["inclui"] = [nome_exibicao(nomes_funcao[c]) for c in resto]
            else:
                no["qtd"] = len(resto)
            destino[nivel].update(dict.fromkeys(resto, no["id"]))
            nos.append(no)
    lig: dict[tuple, float] = defaultdict(float)
    for g, cf, _, k, _, v in linhas:
        a, b, c = destino[0][g], destino[1][cf], destino[2][k]
        lig[(0, a, b)] += v
        lig[(1, b, c)] += v
    ordem = sorted(((k, _centavos(v)) for k, v in lig.items()), key=lambda kv: (kv[0][0], -kv[1], kv[0][1], kv[0][2]))
    # ligação líquida negativa (mais anulação que pagamento) fica no arquivo — conserva a soma —
    # e o painel não a desenha; zero não leva informação
    return {"total": _centavos(sum(l[-1] for l in linhas)), "nos": nos,
            "ligacoes": [[a, b, v] for (_, a, b), v in ordem if v != 0]}


def fluxo_dinheiro(mov: list[dict], ident: dict, indice: dict) -> dict:
    """Caminho do dinheiro por ano (pela partição, como totais.por_ano): todos os
    favorecidos e só os fornecedores privados; o extra-orçamentário fica fora, declarado."""
    entes = set(indice.get("entes_publicos") or [])
    tops_slugs = {f["slug"] for f in indice.get("top_favorecidos") or []}   # quem tem dossiê
    chaves: dict[tuple, str] = {}
    por_ano: dict[int, list] = defaultdict(list)
    extra: dict[int, float] = defaultdict(float)
    for r in mov:
        if r["fase"] != "P":
            continue
        ano, v = r["_periodo"] // 100, r["pago"] or 0.0
        if r["tipo"] == T_EXTRA:
            extra[ano] += v
            continue
        par = (r["nome_favorecido"] or "", r["documento_favorecido"] or "")
        if par not in chaves:
            chaves[par] = _chave_fav(*par)
        funcao = r["funcao"] or "(sem função)"
        por_ano[ano].append((_grupo_fonte(r["fonte_recurso"]), _cod_funcao(funcao), funcao, chaves[par],
                             r["fonte_recurso"] or "", v))
    anos = {}
    for ano in sorted(set(por_ano) | set(extra)):
        linhas = por_ano.get(ano, [])
        anos[str(ano)] = {"extra": _centavos(extra.get(ano, 0.0)),
                          "todos": _sankey(linhas, ident, tops_slugs, entes),
                          "privados": _sankey([l for l in linhas if l[3] not in entes], ident, tops_slugs, entes)}
    return {"versao": 1, "anos": anos}


def exportar_graficos_movimento(mov: list[dict], ident: dict, indice: dict) -> dict:
    """Grava dados/calendario.json e dados/fluxo.json (bytes estáveis: sem carimbo de hora,
    tudo ordenado) e devolve o manifesto que vai no índice."""
    saida = {}
    for nome, obj in (("calendario", calendario_pagamentos(mov)), ("fluxo", fluxo_dinheiro(mov, ident, indice))):
        caminho = os.path.join(DADOS_DIR, nome + ".json")
        gravar_json(caminho, obj, separators=(",", ":"))
        saida[nome] = {"arquivo": f"despesas/dados/{nome}.json", "bytes": os.path.getsize(caminho)}
    return saida


# ── Exports tabulares (completos, gitignored) ─────────────────────────────────
def exportar_csv(rows: list[dict]) -> None:
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(CAMPOS_DETALHE)
        for r in rows:
            w.writerow([r.get(c) for c in CAMPOS_DETALHE])


def exportar_xlsx(rows: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.utils import get_column_letter

    def limpar(v):
        return ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v

    wb = Workbook()
    ws = wb.active
    ws.title = "Execução por empenho"
    ws.append(CAMPOS_DETALHE)
    for r in rows:
        ws.append([limpar(r.get(c)) for c in CAMPOS_DETALHE])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(CAMPOS_DETALHE))}{len(rows)+1}"
    larguras = {"unidade_gestora": 32, "elemento_despesa": 40, "nome_favorecido": 36,
                "funcao": 22, "fonte_recurso": 26, "grupo_despesa": 26, "programa": 28,
                "empenhado": 14, "liquidado": 14, "pago": 14, "tipo": 16}
    for i, c in enumerate(CAMPOS_DETALHE, 1):
        ws.column_dimensions[get_column_letter(i)].width = larguras.get(c, 14)
    wb.save(XLSX_PATH)


def exportar_detalhe_mensal(rows: list[dict]) -> list[dict]:
    """Grava despesas/dados/AAAA-MM.json (um por mês do EMPENHO) e devolve o manifesto."""
    os.makedirs(DADOS_DIR, exist_ok=True)
    por_mes: dict[int, list] = {}
    for r in rows:
        por_mes.setdefault(r["_periodo"], []).append([r.get(c) for c in CAMPOS_DETALHE])

    validos = {f"{p // 100}-{p % 100:02d}.json" for p in por_mes} | set(INDICES_LEVES)
    for nome in os.listdir(DADOS_DIR):
        if nome.endswith(".json") and nome not in validos:
            os.remove(os.path.join(DADOS_DIR, nome))

    manifesto = []
    iE, iL, iP = (CAMPOS_DETALHE.index(c) for c in ("empenhado", "liquidado", "pago"))
    for periodo in sorted(por_mes):
        ano, mes = periodo // 100, periodo % 100
        linhas = por_mes[periodo]
        arquivo = f"{ano}-{mes:02d}.json"
        gravar_json(os.path.join(DADOS_DIR, arquivo),
                    {"campos": CAMPOS_DETALHE, "linhas": linhas}, separators=(",", ":"))
        manifesto.append({"ano": ano, "mes": mes, "n": len(linhas),
                          "empenhado": round(sum((l[iE] or 0) for l in linhas), 2),
                          "liquidado": round(sum((l[iL] or 0) for l in linhas), 2),
                          "valor": round(sum((l[iP] or 0) for l in linhas), 2),   # pago acumulado
                          "bytes": os.path.getsize(os.path.join(DADOS_DIR, arquivo)),  # estimativa antes de baixar
                          "arquivo": f"despesas/dados/{arquivo}"})
    return manifesto


# ── Documentos de estágio por empenho (ficha do empenho, padrão CGU/ITP) ──────
# dados/estagios/AAAA-MM.json — particionado pelo MESMO mês da linha de detalhe,
# então a ficha baixa exatamente 1 arquivo. Chave "UG|empenho" →
#   {"t": tipo_empenho (omitido se vazio),
#    "e": [[fase, nº_doc, data, valor(, especie)], ...]}
# fase: "E"=empenho, "L"=liquidação, "P"=pagamento. A espécie só aparece quando
# NÃO é "Original" (Anulação/Reforço — valores negativos/positivos, padrão
# "Evento" TCE-SP); tupla de 4 itens = Original. Linhas não casadas com nº de
# empenho recebem os próprios documentos; sem nº ficam fora (a ficha usa a linha).
def exportar_estagios(conn, rows: list[dict]) -> int:
    eventos: dict[str, dict] = {}

    def chave(ug, emp):
        return f"{ug}|{emp}"

    def evento(fase, doc, data, valor, especie):
        ev = [fase, doc or "", data or "", round(valor, 2)]
        if especie and especie != "Original":
            ev.append(especie)
        return ev

    # ORDER BY: o tipo do empenho é o da última linha com tipo — com a ordem física ele
    # trocava de um dia para o outro (Ordinário × Estimativo no mesmo empenho)
    for r in _q(conn, "SELECT unidade_gestora ug, empenho emp, data, valor, especie, "
                      "tipo_empenho FROM empenhos ORDER BY ug, emp, data, especie, tipo_empenho, valor"):
        o = eventos.setdefault(chave(r["ug"], r["emp"]), {"e": []})
        if r["tipo_empenho"]:
            o["t"] = r["tipo_empenho"]
        o["e"].append(evento("E", r["emp"], r["data"], r["valor"], r["especie"]))
    for r in _q(conn, "SELECT unidade_gestora ug, empenho emp, liquidacao doc, data, "
                      "valor, especie FROM liquidacoes WHERE empenho IS NOT NULL AND empenho <> ''"):
        eventos.setdefault(chave(r["ug"], r["emp"]), {"e": []})["e"].append(
            evento("L", r["doc"], r["data"], r["valor"], r["especie"]))
    for r in _q(conn, "SELECT unidade_gestora ug, empenho emp, pagamento doc, data, "
                      "valor, especie FROM pagamentos WHERE empenho IS NOT NULL AND empenho <> ''"):
        eventos.setdefault(chave(r["ug"], r["emp"]), {"e": []})["e"].append(
            evento("P", r["doc"], r["data"], r["valor"], r["especie"]))

    for o in eventos.values():   # data, fase e, no empate, o próprio evento (ordem total)
        o["e"].sort(key=lambda ev: (ev[2], "ELP".index(ev[0]) if ev[0] in "ELP" else 9, ev[1], ev[3], *ev[4:]))

    # partição: cada mês recebe as chaves cujas linhas de detalhe vivem nele
    os.makedirs(ESTAGIOS_DIR, exist_ok=True)
    por_mes: dict[int, dict] = {}
    for r in rows:
        if not r.get("empenho"):
            continue
        k = chave(r["unidade_gestora"], r["empenho"])
        if k in eventos:
            por_mes.setdefault(r["_periodo"], {})[k] = eventos[k]

    validos = {f"{p // 100}-{p % 100:02d}.json" for p in por_mes}
    for nome in os.listdir(ESTAGIOS_DIR):
        if nome.endswith(".json") and nome not in validos:
            os.remove(os.path.join(ESTAGIOS_DIR, nome))

    total = 0
    for periodo, mapa in sorted(por_mes.items()):
        arquivo = f"{periodo // 100}-{periodo % 100:02d}.json"
        gravar_json(os.path.join(ESTAGIOS_DIR, arquivo), mapa, separators=(",", ":"))
        total += len(mapa)
    return total


# ── Índices leves (evitam baixar os ~20 MB de detalhe no painel) ──────────────
# Três arquivos pequenos em despesas/dados/:
#   elementos.json          opções do filtro de elemento por tipo de documento
#   pf-resumo.json          agregado das pessoas físicas (modo PF sem detalhe)
#   indice-favorecidos.json identidade → meses onde aparece (a ficha baixa SÓ esses)
# Chave = identidade canônica (formato.identidade_favorecido) — TEM de casar com
# Comum.identidadeFavorecido() do comum.js.
INDICES_LEVES = ("elementos.json", "pf-resumo.json", "indice-favorecidos.json", "nomes-favorecidos.json")
PF_RESUMO_TOP = 1000


def _eh_cpf(doc) -> bool:
    return bool(doc) and "/" not in doc and "*" in doc


def _chave_fav(nome, doc) -> str:
    return identidade_favorecido(nome, doc)[0]


def exportar_indices_leves(rows: list[dict], mov: list[dict] | None = None) -> None:
    elementos = {"todos": set(), "pf": set(), "pj": set()}
    pf: dict[str, dict] = {}
    fav_meses: dict[str, set] = {}
    fav_meses_mov: dict[str, set] = {}
    todos_meses = set()

    for r in rows:
        doc = r.get("documento_favorecido") or ""
        nome = r.get("nome_favorecido") or ""
        elem = r.get("elemento_despesa")
        periodo = r["_periodo"]
        todos_meses.add(periodo)
        if elem:
            elementos["todos"].add(elem)
            if _eh_cpf(doc):
                elementos["pf"].add(elem)
            elif "/" in doc:
                elementos["pj"].add(elem)
        chave = _chave_fav(nome, doc)
        fav_meses.setdefault(chave, set()).add(periodo)
        if _eh_cpf(doc):
            o = pf.setdefault(chave, {"nomes": {}, "documento": doc, "valor": 0.0, "qtd": 0, "meses": set()})
            o["nomes"][nome] = o["nomes"].get(nome, 0) + 1
            o["valor"] += r.get("pago") or 0
            o["qtd"] += 1
            if r.get("data"):
                o["meses"].add(str(r["data"])[:7])
    for r in (mov or []):
        fav_meses_mov.setdefault(_chave_fav(r.get("nome_favorecido") or "", r.get("documento_favorecido") or ""),
                                 set()).add(r["_periodo"])

    gravar_json(os.path.join(DADOS_DIR, "elementos.json"),
                {k: sorted(v) for k, v in elementos.items()}, separators=(",", ":"))

    itens_pf = sorted(pf.items(), key=lambda kv: -kv[1]["valor"])[:PF_RESUMO_TOP]
    gravar_json(os.path.join(DADOS_DIR, "pf-resumo.json"),
                {"itens": [{"nome": nome_exibicao(o["nomes"]), "documento": o["documento"], "chave": k,
                            "valor": round(o["valor"], 2), "qtd": o["qtd"],
                            "meses": len(o["meses"])} for k, o in itens_pf]},
                separators=(",", ":"))

    # quem aparece em quase todos os meses fica FORA do índice (baixar tudo equivale);
    # chave ausente no painel = fallback para todos os meses.
    corte = max(1, len(todos_meses) - 2)
    fav = {k: sorted(v) for k, v in fav_meses.items() if len(v) < corte}
    fav_mov = {k: sorted(v) for k, v in fav_meses_mov.items() if len(v) < corte}
    gravar_json(os.path.join(DADOS_DIR, "indice-favorecidos.json"),
                {"meses_total": len(todos_meses), "versao": 2, "fav": fav, "mov": fav_mov},
                separators=(",", ":"))


def exportar_servico_divida(indice: dict) -> bool:
    """Grava `despesas/servico-divida.json` (lido por endividamento-app.js) a partir do
    bloco `servico_divida` do índice. Só regrava se o dado mudou (ignora o carimbo)."""
    return gravar_json_se_mudou(SERVICO_DIVIDA_PATH, {
        "atualizado_em": indice.get("atualizado_em"),
        "dados_ate": indice.get("dados_ate"),
        **(indice.get("servico_divida") or {"por_ano": [], "credores": []}),
    }, separators=(",", ":"))


def main():
    global DB_PATH, CSV_PATH, XLSX_PATH, DADOS_DIR, MOV_DIR, ESTAGIOS_DIR, JSON_PATH, FAV_DIR, ARVORE_PATH, \
        ALERTAS_ESTADO_PATH, SERVICO_DIVIDA_PATH, ALERTAS_CANDIDATOS_PATH, HISTORICO_DIR
    p = argparse.ArgumentParser(description="Export da base de Despesas → JSON/CSV/XLSX")
    p.add_argument("--db", default=DB_PATH, help="SQLite de entrada (padrão: despesas/despesas.sqlite)")
    p.add_argument("--saida", help="Diretório de saída alternativo (candidato): reproduz a árvore do repo lá dentro")
    args = p.parse_args()
    DB_PATH = args.db
    if args.saida:
        base = os.path.abspath(args.saida)
        CSV_PATH = os.path.join(base, "despesas", "despesas.csv")
        XLSX_PATH = os.path.join(base, "despesas", "despesas.xlsx")
        DADOS_DIR = os.path.join(base, "despesas", "dados")
        MOV_DIR = os.path.join(DADOS_DIR, "mov")
        ESTAGIOS_DIR = os.path.join(DADOS_DIR, "estagios")
        JSON_PATH = os.path.join(base, "despesas-index.json")
        FAV_DIR = os.path.join(base, "favorecidos")
        ARVORE_PATH = os.path.join(base, "despesas", "arvore.json")
        SERVICO_DIVIDA_PATH = os.path.join(base, "despesas", "servico-divida.json")
        ALERTAS_CANDIDATOS_PATH = os.path.join(base, "despesas", "alertas-candidatos.json")
        # o estado dos alertas e o histórico de alterações do repo são a referência; o
        # candidato grava a sua cópia (o histórico só cresce a partir do versionado)
        import shutil
        estado_repo, historico_repo = ALERTAS_ESTADO_PATH, HISTORICO_DIR
        ALERTAS_ESTADO_PATH = os.path.join(base, "despesas", "alertas-estado.json")
        HISTORICO_DIR = os.path.join(base, "despesas", "historico")
        os.makedirs(os.path.dirname(ALERTAS_ESTADO_PATH), exist_ok=True)
        if os.path.exists(estado_repo) and not os.path.exists(ALERTAS_ESTADO_PATH):
            shutil.copy2(estado_repo, ALERTAS_ESTADO_PATH)
        if os.path.isdir(historico_repo) and not os.path.exists(HISTORICO_DIR):
            shutil.copytree(historico_repo, HISTORICO_DIR)
    if not os.path.exists(DB_PATH):
        print(f"Banco não encontrado: {DB_PATH}. Rode o crawler primeiro.", file=sys.stderr)
        sys.exit(1)
    conn = conectar()
    ident = preparar_identidades(conn)
    # conciliação com o TCE-SP ANTES de tudo: mês incompleto na origem sai das comparações
    cob = cobertura_conciliada(conn)
    contratos = contratos_portal()   # contratos e convênios do portal (despesas/instrumentos.py)
    indice = agregados(conn, ident, contratos)
    indice["cobertura"] = cob
    indice["execucao"] = execucao_agregada(conn, cob)
    # identidades classificadas como ente público (p/ o filtro "fornecedores privados"
    # também quando o painel reagrega do detalhe por elemento)
    indice["entes_publicos"] = sorted(k for k, o in ident.items() if eh_ente_publico(o["nome"]))
    # análises (Lote D5): prazo liquidação→pagamento, anulações, fim de exercício
    indice["prazos_pagamento"] = prazos_pagamento(conn, ident)
    indice["anulacoes"] = anulacoes_empenho(conn, ident, cob)
    indice["fim_de_exercicio"] = fim_de_exercicio(conn, cob)
    indice["publicidade"] = publicidade(conn, ident, cob)   # só agregados (2026-10)
    # alertas: TODOS os candidatos → histórico sobre todos (deslocado pelo teto não vira
    # "resolvido") → publicação por prioridade e tetos → lista completa p/ o CSV do painel
    cands = candidatos_alertas(conn, ident, cob, indice["execucao"], prazos=indice["prazos_pagamento"],
                               contratos=contratos)
    indice["prazos_pagamento"].pop("_linhas", None)   # só alimenta as regras; fora do índice
    historico = aplicar_historico_alertas(cands)
    indice["alertas_regras"] = {}   # por regra: candidatos × publicados (tetos declarados no painel)
    indice["alertas"] = publicar(cands, contagem=indice["alertas_regras"])
    tops = {f["slug"] for f in indice["top_favorecidos"]}
    for a in cands:   # link ?f= só existe para o top-300; os demais vão pela rota por documento
        if (a.get("link") or "").startswith(RAIOX_URL + "?f=") and a["link"].split("?f=")[1] not in tops:
            f = _fav_campos(ident, a["filtro"]["chave"])
            a["link"] = _link_fav(f, set())
    # as contagens do índice falam dos PUBLICADOS (o que o painel mostra)
    historico["candidatos"] = {"total": len(cands), "novos": historico["novos"],
                               "persistentes": historico["persistentes"]}
    historico["novos"] = sum(1 for a in indice["alertas"] if a.get("estado") == "novo")
    historico["persistentes"] = sum(1 for a in indice["alertas"] if a.get("estado") == "persistente")
    indice["alertas_historico"] = historico
    n_cands = exportar_candidatos(cands, indice["alertas"])
    alteracoes = exportar_historico_alteracoes(conn)
    indice["resumo"] = resumo_narrativo(conn, indice)
    indice["anos_detalhe"] = anos_detalhe(conn, ident)
    n_fav_raiox = exportar_favorecidos(conn, indice, ident, contratos)
    indice["instrumentos"] = instrumentos_indice()
    n_arvore = exportar_arvore(conn, indice)
    execucao = montar_execucao(conn)
    movimento = montar_movimento(conn)
    indice["meses"] = exportar_detalhe_mensal(execucao)
    indice["meses_movimento"] = exportar_movimento_mensal(movimento)
    indice["cubos"] = exportar_cubos(movimento, ident)   # Explorador de pagamentos (SQL no navegador)
    # calendário de pagamentos e caminho do dinheiro (M8): das mesmas linhas de dados/mov/
    indice["dados_graficos"] = exportar_graficos_movimento(movimento, ident, indice)
    exportar_indices_leves(execucao, movimento)
    # nome de exibição + documento de TODAS as identidades (~7,8 mil): o raio-X por nome
    # (?nome=) acha quem está fora do top-300 sem varrer os 45 MB da movimentação
    gravar_json(os.path.join(DADOS_DIR, "nomes-favorecidos.json"),
                {k: [o["nome"], o["documento"] or ""] for k, o in sorted(ident.items())},
                separators=(",", ":"))
    n_estagios = exportar_estagios(conn, execucao)
    indice["campos_detalhe"] = CAMPOS_DETALHE
    indice["campos_movimento"] = CAMPOS_MOV
    indice["limites_dispensa"] = {str(k): v for k, v in LIMITES_DISPENSA.items()}
    # conservação: a soma do pago na execução e na movimentação tem de ser a base inteira
    pago_exe = round(sum((r["pago"] or 0) for r in execucao), 2)
    pago_mov = round(sum((r["pago"] or 0) for r in movimento), 2)
    indice["conservacao"] = {"pago_base": indice["totais"]["geral"], "pago_execucao": pago_exe,
                             "pago_movimento": pago_mov,
                             "ok": abs(pago_exe - indice["totais"]["geral"]) < 1 and
                                   abs(pago_mov - indice["totais"]["geral"]) < 1}
    gravar_json(JSON_PATH, indice, separators=(",", ":"))
    exportar_servico_divida(indice)

    exportar_csv(execucao)
    try:
        exportar_xlsx(execucao)
        xlsx_msg = os.path.basename(XLSX_PATH)
    except ImportError:
        xlsx_msg = "(openpyxl ausente — XLSX pulado)"
    conn.close()

    print(f"Export concluído: {indice['totais']['pagamentos']} pagamentos (movimentação), "
          f"{len(execucao)} linhas de execução por empenho, {len(movimento)} documentos de movimentação, "
          f"{brl(indice['totais']['geral'])}, {len(indice['alertas'])} alertas ({n_cands} candidatos), "
          f"histórico de alterações +{sum(alteracoes.values())} linhas, "
          f"{len(indice['meses'])} meses, {n_fav_raiox} raio-X de favorecidos "
          f"({indice['totais']['favorecidos']} identidades), árvore com {n_arvore} funções, "
          f"estágios de {n_estagios} empenhos; conservação {'ok' if indice['conservacao']['ok'] else 'FALHOU'}; "
          f"cobertura {'íntegra' if cob['integra'] else 'INCOMPLETA: ' + str(cob['faltantes'][:3]) + str(cob['com_erro'][:3])} → "
          f"{os.path.basename(JSON_PATH)}, dados/, dados/mov/, favorecidos/, {os.path.basename(CSV_PATH)}, {xlsx_msg}.",
          file=sys.stderr)
    if not indice["conservacao"]["ok"]:
        sys.exit(3)


if __name__ == "__main__":
    main()
