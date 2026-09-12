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
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime

from formato import (brl, compacto as _brl_compacto, eh_ente_publico, fator, identidade_favorecido,
                     nome_exibicao, sem_acento, slug_favorecido)  # camada comum do módulo


AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
if RAIZ not in sys.path:
    sys.path.append(RAIZ)  # camada comum do repo (comum/)
from comum.saida import configurar_stdio  # noqa: E402

configurar_stdio()
from comum.escrita import gravar_json, gravar_json_se_mudou  # noqa: E402

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
FRAC_MIN_EMPENHOS = 4           # nº mínimo de EMPENHOS DISTINTOS < limite no mesmo favorecido+elemento+ano
FRAC_FATOR_TOTAL = 1.5          # ...somando ao menos FATOR×limite
FRAC_INFO_FALTANTE = ["objeto da contratação", "modalidade/hipótese de contratação",
                      "processo administrativo", "contrato ou ata vinculada",
                      "valor total contratado (o empenho não é o contrato)"]
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
MAX_ALERTAS = 120
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


# ── Agregações para o painel (movimentação de PAGAMENTOS pela data) ──────────
def agregados(conn, ident: dict | None = None) -> dict:
    ident = ident if ident is not None else preparar_identidades(conn)
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
    por_fonte = _q(conn,
        "SELECT COALESCE(NULLIF(fonte_recurso,''),'(sem fonte)') k, SUM(valor) s "
        "FROM pagamentos GROUP BY k ORDER BY s DESC LIMIT 50")
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
        "por_unidade": [{"unidade": r["k"], "valor": round(r["s"], 2)} for r in por_unidade],
        "top_favorecidos": [
            dict(_fav_campos(ident, r["k"]), valor=round(r["s"], 2), qtd=r["n"], meses=r["meses"])
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
    # ORIGINAL está na base (empenhos globais emitidos em dez do exercício anterior
    # entram só como anulação/reforço e subcontariam o denominador). A taxa é
    # publicada como validada apenas quando: cobertura dos 3 estágios completa
    # para o ano, denominador > 0 e liquidado ≤ empenhado, pago ≤ liquidado.
    # Caso contrário publica os números brutos + motivos, nunca um teto de 100%.
    hoje = date.today()
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

    # vs média dos até 12 meses anteriores
    anteriores = series[max(0, idx - 12):idx]
    media = sum(s["valor"] for s in anteriores) / len(anteriores) if anteriores else None
    delta_media_pct = round((ref["valor"] - media) / media * 100) if media else None

    # função com maior variação absoluta vs o mês anterior
    destaque = None
    if idx >= 1:
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

    # acumulado do ano (jan..mês de referência) vs mesmo período do ano anterior
    yoy = None
    atual = sum(s["valor"] for s in series if s["ano"] == ref["ano"] and s["mes"] <= ref["mes"])
    passado = sum(s["valor"] for s in series if s["ano"] == ref["ano"] - 1 and s["mes"] <= ref["mes"])
    if passado:
        yoy = {"atual": round(atual, 2), "anterior": round(passado, 2),
               "pct": round((atual - passado) / passado * 100)}

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
        frases.append(f"No acumulado de {ref['ano']} (jan–{MESES_ABREV[ref['mes'] - 1]}), "
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
        frases.append(f"{'Os meses' if len(parciais) > 1 else 'O mês'} {', '.join(parciais)} ainda "
                      f"{'estão' if len(parciais) > 1 else 'está'} incompleto(s) na origem e "
                      f"{'ficam' if len(parciais) > 1 else 'fica'} fora das comparações.")
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
        fav = [dict(_fav_campos(ident, x["k"]), valor=round(x["s"], 2))
               for x in _q(conn,
                   f"SELECT fi.chave k, SUM(p.valor) s FROM pagamentos p {FAV_JOIN.format(t='p')} "
                   f"WHERE p.ano=? GROUP BY fi.chave ORDER BY s DESC LIMIT 6", a)]
        out[str(a)] = {"por_funcao": fn, "top_favorecidos": fav}
    return out


# ── Raio-X por favorecido (favorecidos/<slug>.json) ───────────────────────────
# Um dossiê estático por IDENTIDADE do top-N: série mensal própria, por função,
# últimos pagamentos e alertas — consumido por favorecido.html?f=<slug>.
def exportar_favorecidos(conn, indice: dict, ident: dict | None = None) -> int:
    ident = ident if ident is not None else preparar_identidades(conn)
    os.makedirs(FAV_DIR, exist_ok=True)
    tops = indice.get("top_favorecidos") or []
    validos = set()
    dossies = {}
    for rank, f in enumerate(tops, 1):
        chave, slug = f["chave"], f["slug"]
        validos.add(slug + ".json")
        serie = [{"ano": r["ano"], "mes": r["mes"], "valor": round(r["s"], 2)}
                 for r in _q(conn,
                     f"SELECT p.ano, p.mes, SUM(p.valor) s FROM pagamentos p {FAV_JOIN.format(t='p')} "
                     f"WHERE fi.chave=? GROUP BY p.ano, p.mes ORDER BY p.ano, p.mes", chave)]
        por_ano = {}
        for s in serie:
            por_ano[str(s["ano"])] = round(por_ano.get(str(s["ano"]), 0) + s["valor"], 2)
        funcoes = [{"funcao": r["k"], "valor": round(r["s"], 2)}
                   for r in _q(conn,
                       f"SELECT COALESCE(NULLIF(p.funcao,''),'(sem função)') k, SUM(p.valor) s "
                       f"FROM pagamentos p {FAV_JOIN.format(t='p')} WHERE fi.chave=? "
                       f"GROUP BY k ORDER BY s DESC LIMIT 6", chave)]
        ultimos = [{"data": r["data"], "valor": round(r["valor"], 2), "funcao": r["funcao"],
                    "elemento": r["elemento_despesa"], "unidade": r["unidade_gestora"],
                    "tipo": r["tipo_pagamento"]}
                   for r in _q(conn,
                       f"SELECT p.data, p.valor, p.funcao, p.elemento_despesa, p.unidade_gestora, "
                       f"p.tipo_pagamento FROM pagamentos p {FAV_JOIN.format(t='p')} WHERE fi.chave=? "
                       f"ORDER BY p.data DESC, p.valor DESC LIMIT 50", chave)]
        meus_alertas = [a for a in indice.get("alertas", [])
                        if (a.get("filtro") or {}).get("chave") == chave]

        # só regrava se o CONTEÚDO mudou: com `atualizado_em` novo a cada run, os
        # 290 dossiês viravam diff diário (2,8 MB/dia no histórico e cache do Pages
        # invalidado em toda ficha) sem nenhum dado novo
        dossies[slug] = {
            "nome": f["nome"], "documento": f["documento"], "chave": chave, "slug": slug,
            "grafias": f.get("grafias") or [f["nome"]], "rank": rank,
            "total": f["valor"], "qtd": f["qtd"], "meses": f["meses"],
            "por_ano": por_ano, "serie_mensal": serie, "por_funcao": funcoes,
            "ultimos_pagamentos": ultimos, "alertas": meus_alertas,
            "atualizado_em": indice.get("atualizado_em"),
        }
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
    """Link para o Detalhamento já filtrado (mesmas chaves curtas do despesas-app.js)."""
    from urllib.parse import urlencode
    chaves = {"visao": "dv", "meses": "dm", "busca": "dq", "elemento": "del", "funcao": "df",
              "tipo": "dt", "unidade": "du"}
    q = {chaves[k]: v for k, v in p.items() if v}
    return f"{PAINEL_URL}?{urlencode(q)}#detalhe"


def _limite_dispensa(ano: int, elemento: str) -> dict:
    lim = LIMITES_DISPENSA.get(ano)
    e = sem_acento(elemento or "")
    engenharia = e.startswith("449051") or "ENGENHARIA" in e or "OBRAS" in e
    if not lim:
        return {"valor": None, "hipotese": None, "exercicio": ano, "norma": None,
                "verificacao": f"limite de {ano} não cadastrado — enquadramento não afirmado"}
    return {"valor": lim["engenharia"] if engenharia else lim["compras"],
            "hipotese": ("art. 75, I (obras e serviços de engenharia)" if engenharia
                         else "art. 75, II (compras e demais serviços)") + " — presumida pelo elemento de despesa",
            "exercicio": ano, "norma": lim["norma"], "verificacao": lim["verificacao"]}


def alertas(conn, ident: dict | None = None, cob: dict | None = None,
            execucao: dict | None = None) -> list[dict]:
    """Regras determinísticas. Cada alerta traz: id estável, classe (contexto /
    anomalia / inconsistência), severidade, filtro (com a chave de identidade),
    link para o recorte e documentos que o sustentam."""
    ident = ident if ident is not None else preparar_identidades(conn)
    cob = cob or cobertura(conn)
    out = []
    tops_slugs = {o["slug"] for o in ident.values()}   # todo favorecido tem slug; o link ?f= só
    # funciona p/ top-300 — o export troca para ?doc= quando o dossiê não existe (ver main)
    fav = lambda chave: _fav_campos(ident, chave)  # noqa: E731
    completo = _mes_completo_ate(conn)
    p_completo = completo[0] * 100 + completo[1] if completo else None
    meses_tudo = [f"{r['ano']}" for r in _q(conn, "SELECT DISTINCT ano FROM pagamentos ORDER BY ano")]

    def docs_pag(where, *params, limite=MAX_DOCS_ALERTA):
        return [{"data": r["data"], "doc": r["pagamento"], "empenho": r["empenho"], "ug": r["unidade_gestora"],
                 "valor": round(r["valor"], 2), "elemento": (r["elemento_despesa"] or "")[:60]}
                for r in _q(conn, f"SELECT p.data, p.pagamento, p.empenho, p.unidade_gestora, p.valor, "
                                  f"p.elemento_despesa FROM pagamentos p {FAV_JOIN.format(t='p')} "
                                  f"WHERE {where} ORDER BY p.valor DESC LIMIT {limite}", *params)]

    # 1) Favorecido recorrente de alto valor — CONTEXTO (escala, não irregularidade)
    for r in _q(conn,
        f"SELECT fi.chave k, SUM(p.valor) s, COUNT(DISTINCT p.ano*100+p.mes) meses "
        f"FROM pagamentos p {FAV_JOIN.format(t='p')} GROUP BY fi.chave "
        f"HAVING s >= ? AND meses >= ? ORDER BY s DESC LIMIT ?",
        ALERTA_FAV_VALOR, ALERTA_FAV_MESES, CAP_POR_REGRA):
        f = fav(r["k"])
        out.append({
            "id": _id_alerta("favorecido_recorrente", r["k"]),
            "tipo": "favorecido_recorrente", "classe": CLASSE_CONTEXTO, "severidade": "baixa",
            "titulo": f"Grande recebedor recorrente: {f['nome']}",
            "detalhe": f"{brl(r['s'])} acumulados em {r['meses']} meses. Valor alto e recorrência, "
                       f"por si, indicam escala do contrato/repasse — não irregularidade.",
            "valor": round(r["s"], 2),
            "filtro": {"favorecido": f["nome"], "chave": r["k"]},
            "link": _link_fav(f, tops_slugs),
        })

    # 2) Concentração: favorecido que domina uma função
    tot_funcao = {r["k"]: r["s"] for r in _q(conn,
        "SELECT COALESCE(NULLIF(funcao,''),'(sem função)') k, SUM(valor) s "
        "FROM pagamentos GROUP BY k")}
    n_conc = 0
    for r in _q(conn,
        f"SELECT COALESCE(NULLIF(p.funcao,''),'(sem função)') f, fi.chave k, SUM(p.valor) s "
        f"FROM pagamentos p {FAV_JOIN.format(t='p')} GROUP BY f, fi.chave HAVING s >= ? ORDER BY s DESC",
        ALERTA_CONCENTRACAO_MIN):
        base = tot_funcao.get(r["f"], 0) or 1
        pct = 100 * r["s"] / base
        if pct >= ALERTA_CONCENTRACAO_PCT and r["f"] != "(sem função)":
            if n_conc >= CAP_POR_REGRA:
                break
            n_conc += 1
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
                "filtro": {"favorecido": f["nome"], "chave": r["k"], "funcao": r["f"]},
                "link": _link_detalhe(visao="mov", meses=",".join(meses_tudo), busca=f["nome"], funcao=r["f"]),
            })

    # 3) Pico mensal (sobre o total geral por mês) — só meses completos
    serie = [r for r in _q(conn, "SELECT ano, mes, SUM(valor) s FROM pagamentos GROUP BY ano, mes ORDER BY ano, mes")
             if p_completo is None or r["ano"] * 100 + r["mes"] <= p_completo]
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
                })

    # 4) Extra-orçamentário relevante — CONTEXTO (retenções/consignações são esperadas)
    for r in _q(conn,
        f"SELECT fi.chave k, p.elemento_despesa e, SUM(p.valor) s, COUNT(*) n "
        f"FROM pagamentos p {FAV_JOIN.format(t='p')} WHERE p.tipo_pagamento LIKE '%Extra%' "
        f"GROUP BY fi.chave, p.elemento_despesa HAVING s >= ? ORDER BY s DESC LIMIT 20",
        ALERTA_EXTRA_VALOR):
        f = fav(r["k"])
        out.append({
            "id": _id_alerta("extra_orcamentario", r["k"], r["e"]),
            "tipo": "extra_orcamentario", "classe": CLASSE_CONTEXTO, "severidade": "baixa",
            "titulo": f"Extra-orçamentário relevante: {f['nome']}",
            "detalhe": f"{brl(r['s'])} em {r['n']} pagamentos — {(r['e'] or '')[:60]}.",
            "valor": round(r["s"], 2),
            "filtro": {"favorecido": f["nome"], "chave": r["k"], "elemento": r["e"]},
            "link": _link_detalhe(visao="mov", meses=",".join(meses_tudo), busca=f["nome"], elemento=r["e"]),
        })

    # 5) Possível fracionamento — TRIAGEM: conta EMPENHOS DISTINTOS (UG + nº) pelo
    # valor líquido (original + reforços − anulações); limite do exercício por hipótese
    # presumida. O padrão financeiro sozinho NÃO demonstra fracionamento irregular.
    n = 0
    por_grupo: dict[tuple, list] = defaultdict(list)
    for r in _q(conn, f"""
        SELECT fi.chave k, e.elemento_despesa el, e.ano, e.unidade_gestora ug, e.empenho emp,
               ROUND(SUM(e.valor),2) liquido, MIN(e.data) data,
               SUM(CASE WHEN e.especie='Original' OR e.especie IS NULL OR e.especie='' THEN 1 ELSE 0 END) originais,
               SUM(CASE WHEN e.especie LIKE 'Refor%' THEN 1 ELSE 0 END) reforcos,
               SUM(CASE WHEN e.especie LIKE 'Anula%' THEN 1 ELSE 0 END) anulacoes
        FROM empenhos e {FAV_JOIN.format(t='e')}
        GROUP BY fi.chave, e.elemento_despesa, e.ano, e.unidade_gestora, e.empenho"""):
        por_grupo[(r["k"], r["el"], r["ano"])].append(dict(r))
    candidatos = []
    for (k, el, ano), emps in por_grupo.items():
        lim = _limite_dispensa(ano, el)
        if not lim["valor"] or eh_ente_publico(fav(k)["nome"]):
            continue
        abaixo = [e for e in emps if 0 < e["liquido"] < lim["valor"]]
        soma = round(sum(e["liquido"] for e in abaixo), 2)
        if len(abaixo) >= FRAC_MIN_EMPENHOS and soma >= FRAC_FATOR_TOTAL * lim["valor"]:
            candidatos.append((k, el, ano, abaixo, soma, lim, len(emps)))
    for k, el, ano, abaixo, soma, lim, n_total in sorted(candidatos, key=lambda x: -x[4]):
        if n >= CAP_POR_REGRA:
            break
        n += 1
        f = fav(k)
        docs = [{"ug": e["ug"], "empenho": e["emp"], "data": e["data"], "valor": e["liquido"],
                 "originais": e["originais"], "reforcos": e["reforcos"], "anulacoes": e["anulacoes"]}
                for e in sorted(abaixo, key=lambda e: -e["liquido"])[:MAX_DOCS_ALERTA]]
        out.append({
            "id": _id_alerta("fracionamento", k, el, ano),
            "tipo": "fracionamento", "classe": CLASSE_ANOMALIA, "severidade": "media",
            "titulo": f"Triagem de fracionamento: {len(abaixo)} empenhos distintos a {f['nome']} ({ano})",
            "detalhe": (f"{brl(soma)} em {len(abaixo)} empenhos distintos, cada um abaixo de "
                        f"{brl(lim['valor'])} ({lim['hipotese']}; {lim['norma']}) — {(el or '')[:50]}. "
                        f"Padrão financeiro apenas: o valor empenhado não é o valor da contratação, e "
                        f"o limite se aplica ao objeto. Faltam: {', '.join(FRAC_INFO_FALTANTE)}."),
            "valor": soma,
            "filtro": {"favorecido": f["nome"], "chave": k, "elemento": el, "tipo_doc": "pj", "ano": ano},
            "limite": lim,
            "documentos": docs,
            "informacoes_faltantes": FRAC_INFO_FALTANTE,
            "link": _link_detalhe(visao="exe", meses=str(ano), busca=f["nome"], elemento=el),
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
        n = 0
        for r in _q(conn,
            f"SELECT fi.chave k, SUM(p.valor) s, MIN(p.ano*100+p.mes) ini FROM pagamentos p "
            f"{FAV_JOIN.format(t='p')} GROUP BY fi.chave HAVING ini >= ? AND s >= ? ORDER BY s DESC",
            corte, ALERTA_NOVO_VALOR):
            f = fav(r["k"])
            if eh_ente_publico(f["nome"]):
                continue
            if n >= CAP_POR_REGRA:
                break
            n += 1
            out.append({
                "id": _id_alerta("favorecido_novo", r["k"]),
                "tipo": "favorecido_novo", "classe": CLASSE_ANOMALIA, "severidade": "media",
                "titulo": f"Favorecido novo de alto valor: {f['nome']}",
                "detalhe": (f"{brl(r['s'])} desde {r['ini'] // 100}-{r['ini'] % 100:02d} "
                            f"(1ª aparição na base, que começa em {ANO_INICIAL}-01)."),
                "valor": round(r["s"], 2),
                "filtro": {"favorecido": f["nome"], "chave": r["k"]},
                "documentos": docs_pag("fi.chave=?", r["k"]),
                "link": _link_fav(f, tops_slugs),
            })

    # 7) Crescimento ano-a-ano no MESMO período (jan–M do último mês completo em
    # ambos os anos) — sem projeção anualizada
    if completo and completo[1] >= ALERTA_YOY_MIN_MESES:
        atual, mlim = completo
        ant = atual - 1
        n = 0
        for r in _q(conn,
            f"SELECT fi.chave k, "
            f"SUM(CASE WHEN p.ano=? AND p.mes<=? THEN p.valor ELSE 0 END) v_ant, "
            f"SUM(CASE WHEN p.ano=? AND p.mes<=? THEN p.valor ELSE 0 END) v_atual "
            f"FROM pagamentos p {FAV_JOIN.format(t='p')} GROUP BY fi.chave "
            f"HAVING v_ant > 0 AND v_atual >= ? ORDER BY v_atual DESC",
            ant, mlim, atual, mlim, ALERTA_YOY_VALOR):
            f = fav(r["k"])
            if eh_ente_publico(f["nome"]) or r["v_atual"] < ALERTA_YOY_FATOR * r["v_ant"]:
                continue
            if n >= CAP_POR_REGRA:
                break
            n += 1
            per = f"jan–{MESES_ABREV[mlim - 1]}"
            out.append({
                "id": _id_alerta("crescimento_yoy", r["k"], atual),
                "tipo": "crescimento_yoy", "classe": CLASSE_ANOMALIA, "severidade": "media",
                "titulo": f"Crescimento no mesmo período: {f['nome']}",
                "detalhe": (f"{brl(r['v_atual'])} em {per}/{atual} vs {brl(r['v_ant'])} em {per}/{ant} "
                            f"— {fator(r['v_atual'] / r['v_ant'])} (meses completos; sem projeção)."),
                "valor": round(r["v_atual"], 2),
                "filtro": {"favorecido": f["nome"], "chave": r["k"]},
                "documentos": docs_pag("fi.chave=? AND p.ano=? AND p.mes<=?", r["k"], atual, mlim),
                "link": _link_fav(f, tops_slugs),
            })

    # 8) Pessoa física (CPF) recebendo em elemento sensível
    cond_elem = " OR ".join(f"p.elemento_despesa LIKE '{x}'" for x in ELEM_SENSIVEIS)
    n = 0
    for r in _q(conn,
        f"SELECT fi.chave k, p.elemento_despesa e, SUM(p.valor) s, COUNT(*) qt "
        f"FROM pagamentos p {FAV_JOIN.format(t='p')} WHERE fi.chave LIKE 'cpf:%' AND ({cond_elem}) "
        f"GROUP BY fi.chave, p.elemento_despesa HAVING s >= ? ORDER BY s DESC",
        ALERTA_PF_VALOR):
        if n >= CAP_POR_REGRA:
            break
        n += 1
        f = fav(r["k"])
        elem_curto = (r["e"] or "").split(" - ", 1)[-1][:40]
        out.append({
            "id": _id_alerta("pf_sensivel", r["k"], r["e"]),
            "tipo": "pf_sensivel", "classe": CLASSE_ANOMALIA, "severidade": "alta",
            "titulo": f"Pessoa física em {elem_curto}: {f['nome']}",
            "detalhe": f"{brl(r['s'])} em {r['qt']} pagamentos a pessoa física — {(r['e'] or '')[:50]}.",
            "valor": round(r["s"], 2),
            "filtro": {"favorecido": f["nome"], "chave": r["k"], "elemento": r["e"], "tipo_doc": "pf"},
            "documentos": docs_pag("fi.chave=? AND p.elemento_despesa=?", r["k"], r["e"]),
            "link": _link_detalhe(visao="mov", meses=",".join(meses_tudo), busca=f["nome"], elemento=r["e"]),
        })

    # 9/10) Pico na série do próprio favorecido / elemento (z-score local) — meses completos
    def _picos_locais(campo_sql, tipo, valor_min, rotulo):
        series: dict[str, list] = {}
        sql = (f"SELECT {campo_sql} k, p.ano*100+p.mes per, SUM(p.valor) s FROM pagamentos p "
               f"{FAV_JOIN.format(t='p')} GROUP BY k, per ORDER BY k, per")
        for r in _q(conn, sql):
            if not r["k"] or (p_completo and r["per"] > p_completo):
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
        for k, p, s, media, nome in achados[:CAP_POR_REGRA]:
            mes_txt = f"{p // 100}-{p % 100:02d}"
            if tipo == "pico_favorecido":
                filtro = {"favorecido": nome, "chave": k, "ano": p // 100, "mes": p % 100}
                docs = docs_pag("fi.chave=? AND p.ano=? AND p.mes=?", k, p // 100, p % 100)
                link = _link_detalhe(visao="mov", meses=mes_txt, busca=nome)
                curto = nome
            else:
                filtro = {"elemento": k, "ano": p // 100, "mes": p % 100}
                docs = docs_pag("p.elemento_despesa=? AND p.ano=? AND p.mes=?", k, p // 100, p % 100)
                link = _link_detalhe(visao="mov", meses=mes_txt, elemento=k)
                curto = (k or "").split(" - ", 1)[-1][:60]
            out.append({
                "id": _id_alerta(tipo, k, p),
                "tipo": tipo, "classe": CLASSE_ANOMALIA, "severidade": "media",
                "titulo": f"Pico de {rotulo}: {curto} em {mes_txt}",
                "detalhe": (f"{brl(s)} no mês — {fator(s / media)} a média mensal "
                            f"histórica ({brl(media)}). Mês completo; confira sazonalidade."),
                "valor": round(s, 2),
                "filtro": filtro, "documentos": docs, "link": link,
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
            out.append({
                "id": _id_alerta("dados_nao_localizado", ano),
                "tipo": "dados_nao_localizado", "classe": CLASSE_INCONSISTENCIA, "severidade": "baixa",
                "titulo": f"Pagamentos orçamentários de {ano} cujo empenho não está na base",
                "detalhe": (f"{brl(soma)} em {qtd} pagamentos classificados pela origem como orçamentários, "
                            f"mas o nº de empenho não veio no endpoint de empenhos (provável empenho emitido "
                            f"antes de {ANO_INICIAL}-01 ou lacuna da origem). Não são restos a pagar."),
                "valor": round(soma, 2), "filtro": {"ano": ano, "tipo": T_NAO_LOCALIZADO},
                "link": _link_detalhe(visao="exe", meses=str(ano), tipo=T_NAO_LOCALIZADO),
            })

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    ordem_classe = {CLASSE_INCONSISTENCIA: 0, CLASSE_ANOMALIA: 1, CLASSE_CONTEXTO: 2}
    out.sort(key=lambda a: (ordem.get(a["severidade"], 9), ordem_classe.get(a["classe"], 9), -a["valor"]))
    return out[:MAX_ALERTAS]


def aplicar_historico_alertas(lista: list[dict], caminho: str = None, hoje: str = None) -> dict:
    """Marca cada alerta como novo / persistente (ou sem_historico quando não há
    arquivo de estado) e atualiza despesas/alertas-estado.json. Devolve o bloco
    `alertas_historico` do índice."""
    caminho = caminho or ALERTAS_ESTADO_PATH
    hoje = hoje or date.today().isoformat()
    estado = {"alertas": {}, "resolvidos": {}}
    disponivel = False
    if os.path.exists(caminho):
        try:
            with open(caminho, encoding="utf-8") as f:
                lido = json.load(f)
            estado["alertas"] = lido.get("alertas") or {}
            estado["resolvidos"] = lido.get("resolvidos") or {}
            disponivel = bool(estado["alertas"] or estado["resolvidos"])
        except (OSError, ValueError):
            pass
    atuais = {a["id"] for a in lista}
    novos = persistentes = 0
    for a in lista:
        h = estado["alertas"].get(a["id"])
        if h:
            a["estado"], a["primeiro_em"] = "persistente", h.get("primeiro_em", hoje)
            persistentes += 1
        elif disponivel:
            a["estado"], a["primeiro_em"] = "novo", hoje
            novos += 1
        else:
            a["estado"], a["primeiro_em"] = "sem_historico", hoje
        estado["alertas"][a["id"]] = {"primeiro_em": a["primeiro_em"], "ultimo_em": hoje,
                                      "tipo": a["tipo"], "titulo": a["titulo"]}
    resolvidos_agora = []
    for aid in list(estado["alertas"]):
        if aid not in atuais:
            h = estado["alertas"].pop(aid)
            h["resolvido_em"] = hoje
            estado["resolvidos"][aid] = h
            resolvidos_agora.append(dict(h, id=aid))
    # mantém só os 200 resolvidos mais recentes
    if len(estado["resolvidos"]) > 200:
        ordenados = sorted(estado["resolvidos"].items(), key=lambda kv: kv[1].get("resolvido_em", ""))
        estado["resolvidos"] = dict(ordenados[-200:])
    desde = min((h.get("primeiro_em", hoje) for h in estado["alertas"].values()), default=hoje)
    gravar_json_se_mudou(caminho, {"atualizado_em": hoje, "alertas": estado["alertas"],
                                   "resolvidos": estado["resolvidos"]}, indent=1)
    recentes = sorted(estado["resolvidos"].items(), key=lambda kv: kv[1].get("resolvido_em", ""), reverse=True)[:20]
    return {"disponivel": disponivel, "desde": desde if disponivel else None,
            "novos": novos, "persistentes": persistentes,
            "resolvidos_recentes": [dict(v, id=k) for k, v in recentes],
            "nota": (None if disponivel else
                     "Sem histórico anterior de alertas: não é possível dizer quais são novos.")}


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
        for r in _q(conn, f"""
            SELECT unidade_gestora, empenho, ano*100+mes periodo, data, nome_favorecido,
                   documento_favorecido, funcao, subfuncao, programa, elemento_despesa,
                   fonte_recurso, grupo_despesa, {campo_tipo} tipo_fonte, ROUND(SUM(valor),2) v
            FROM {fonte}
            GROUP BY unidade_gestora, empenho, ano, mes, data, nome_favorecido, elemento_despesa, {campo_tipo}"""):
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
    rows.sort(key=lambda x: (x["_periodo"], x["data"] or "", -(x["pago"] or 0)))
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
    rows.sort(key=lambda x: (x["_periodo"], x["data"] or "", x["fase"]))
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
                          "arquivo": f"despesas/dados/mov/{arquivo}"})
    return manifesto


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

    for r in _q(conn, "SELECT unidade_gestora ug, empenho emp, data, valor, especie, "
                      "tipo_empenho FROM empenhos"):
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

    for o in eventos.values():
        o["e"].sort(key=lambda ev: (ev[2], "ELP".index(ev[0]) if ev[0] in "ELP" else 9))

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
INDICES_LEVES = ("elementos.json", "pf-resumo.json", "indice-favorecidos.json")
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


def main():
    global DB_PATH, CSV_PATH, XLSX_PATH, DADOS_DIR, MOV_DIR, ESTAGIOS_DIR, JSON_PATH, FAV_DIR, ARVORE_PATH, \
        ALERTAS_ESTADO_PATH
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
        # o estado dos alertas do repo é a referência de histórico; o candidato grava a sua cópia
        estado_repo = ALERTAS_ESTADO_PATH
        ALERTAS_ESTADO_PATH = os.path.join(base, "despesas", "alertas-estado.json")
        os.makedirs(os.path.dirname(ALERTAS_ESTADO_PATH), exist_ok=True)
        if os.path.exists(estado_repo) and not os.path.exists(ALERTAS_ESTADO_PATH):
            import shutil
            shutil.copy2(estado_repo, ALERTAS_ESTADO_PATH)
    if not os.path.exists(DB_PATH):
        print(f"Banco não encontrado: {DB_PATH}. Rode o crawler primeiro.", file=sys.stderr)
        sys.exit(1)
    conn = conectar()
    ident = preparar_identidades(conn)
    cob = cobertura(conn)
    indice = agregados(conn, ident)
    indice["cobertura"] = cob
    indice["execucao"] = execucao_agregada(conn, cob)
    indice["alertas"] = alertas(conn, ident, cob, indice["execucao"])
    tops = {f["slug"] for f in indice["top_favorecidos"]}
    for a in indice["alertas"]:   # link ?f= só existe para o top-300; os demais vão pela rota por documento
        if a.get("link", "").startswith(RAIOX_URL + "?f=") and a["link"].split("?f=")[1] not in tops:
            f = _fav_campos(ident, a["filtro"]["chave"])
            a["link"] = _link_fav(f, set())
    indice["alertas_historico"] = aplicar_historico_alertas(indice["alertas"])
    indice["resumo"] = resumo_narrativo(conn, indice)
    indice["anos_detalhe"] = anos_detalhe(conn, ident)
    n_fav_raiox = exportar_favorecidos(conn, indice, ident)
    n_arvore = exportar_arvore(conn, indice)
    execucao = montar_execucao(conn)
    movimento = montar_movimento(conn)
    indice["meses"] = exportar_detalhe_mensal(execucao)
    indice["meses_movimento"] = exportar_movimento_mensal(movimento)
    exportar_indices_leves(execucao, movimento)
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

    exportar_csv(execucao)
    try:
        exportar_xlsx(execucao)
        xlsx_msg = os.path.basename(XLSX_PATH)
    except ImportError:
        xlsx_msg = "(openpyxl ausente — XLSX pulado)"
    conn.close()

    print(f"Export concluído: {indice['totais']['pagamentos']} pagamentos (movimentação), "
          f"{len(execucao)} linhas de execução por empenho, {len(movimento)} documentos de movimentação, "
          f"{brl(indice['totais']['geral'])}, {len(indice['alertas'])} alertas, "
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
