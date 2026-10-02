#!/usr/bin/env python3
"""
Crawler de Despesas (Prefeitura Municipal de Santos) — execução orçamentária
============================================================================

Baixa do Portal da Transparência de Santos (`santos-sp.portaltp.com.br`) os três
estágios da execução da despesa, cada um num endpoint próprio:

  - **empenhos**     json_empenhos      → valor EMPENHADO   (campo extra: tipo_empenho)
  - **liquidações**  json_liquidacoes   → valor LIQUIDADO   (liquidacao, tipo_liquidacao)
  - **pagamentos**   json_pagamentos    → valor PAGO        (liquidacao, pagamento, tipo_pagamento)

Todos aceitam `?ano=AAAA&mes=M` (mês = 1..12) e devolvem um **XML SOAP** (`<string>`)
com um **array JSON embutido como texto** — extrai `.text`, `html.unescape`, `json.loads`.
A resposta de um mês é a FOTOGRAFIA COMPLETA daquele mês na origem (todas as linhas
datadas no mês, inclusive anulações com valor negativo). Não há campo de versão nem
de exclusão: correções e cancelamentos só aparecem como linhas alteradas ou ausentes
na próxima fotografia.

Reconciliação por partição (fonte, ano, mês) — versão 2 do esquema (2026-09)
----------------------------------------------------------------------------
Até a versão 1 a gravação era `INSERT OR IGNORE` por hash das colunas-chave (que
incluíam o valor): um pagamento corrigido de 100 para 80 virava duas linhas (180),
linhas removidas da origem ficavam para sempre e linhas legítimas idênticas (lotes
de depósitos judiciais) eram descartadas. Agora cada recarga SUBSTITUI a partição
inteira dentro de uma transação, depois de validar a resposta:

  1. estrutura (lista de objetos com os campos esperados, datas dentro do mês);
  2. resposta vazia quando a partição já tinha linhas → SUSPEITA, mantém a anterior
     (`--aceitar-vazio` libera);
  3. queda de mais de (1 − LIMITE_REDUCAO) nas linhas ou no valor absoluto → SUSPEITA,
     mantém a anterior (`--aceitar-reducao` libera);
  4. depois de gravar, conta e soma o que ficou no banco e compara com a resposta —
     divergência aborta a transação (ROLLBACK) e a versão anterior fica intacta.

As linhas que saíram ou mudaram vão para `linhas_historico` (histórico separado,
nunca somado à visão corrente) e cada execução deixa uma linha em
`historico_reconciliacao` (antes/depois, adicionadas, removidas, alteradas).

Duplicidade sistemática da origem
---------------------------------
A granularidade exposta pela API não distingue linhas idênticas legítimas (um lote
de depósitos judiciais tem vários itens com o mesmo valor) de um defeito de
duplicação. Em 2026-09 a API passou a devolver TODAS as linhas da UG Prefeitura de
jan–mai/2026 exatamente duas vezes. A regra adotada (documentada em
rules/despesas.md): por (unidade gestora, dia), se ≥ DUP_FRACAO das linhas distintas
aparecem repetidas, a duplicação é sistemática e cada grupo idêntico é reduzido por
uma linha só (a taxa de pares idênticos legítimos nos meses limpos é < 0,2%); pela
partição inteira, ≥ 5% das linhas distintas repetidas também é sistemático (os lotes
repetidos atravessam dias). Fora desses padrões TODAS as linhas são mantidas. O descarte
fica registrado em `controle_carga` (contagem, valor, diagnóstico) e em `linhas_historico`.

Uso:
    python despesas/crawler.py --ano 2026 --mes 6 --dry-run     # amostra dos 3 streams
    python despesas/crawler.py --ano 2026 --mes 6               # um mês
    python despesas/crawler.py --ano 2026                       # ano inteiro
    python despesas/crawler.py                                  # mandato (2025→corrente)
    python despesas/crawler.py --forcar                         # reconcilia meses já carregados
    python despesas/crawler.py --fonte pagamentos               # só um stream
    python despesas/crawler.py --bruto-dir DIR                  # cache das respostas brutas
    python despesas/crawler.py --db OUTRO.sqlite                # banco alternativo (candidato)

Códigos de saída: 0 = tudo ok; 1 = NENHUMA coleta funcionou (portal fora, bloqueio);
2 = falha parcial (alguma partição com erro ou suspeita — as demais foram atualizadas).
"""

import argparse
import hashlib
import html
import json
import math
import os
import shutil
import sqlite3
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz do repo: comum/
from comum.saida import configurar_stdio  # noqa: E402
from comum import http  # noqa: E402
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime

import requests

configurar_stdio()

BASE_URL = "https://santos-sp.portaltp.com.br"
API = f"{BASE_URL}/api/transparencia.asmx"
# O WAF do portal passou a devolver 403 para o UA antigo ("...DespesasIndexBot/1.0")
# em 2026-07-09 — o filtro pega o token "Bot". UA sem essa palavra, ainda
# identificando quem somos e com link de contato, volta a receber 200.
HEADERS = {"User-Agent": "GabineteSantos/1.0 (+https://github.com/derosisjr/Playground)"}

AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(AQUI, "despesas.sqlite")
FONTE = "Prefeitura Municipal de Santos"

ANO_INICIAL = 2025        # 1º ano do mandato
PAUSA = 0.4               # cortesia entre requisições (s)
SCHEMA_VERSAO = 2

# Validação da partição nova contra a anterior (ver docstring)
LIMITE_REDUCAO = 0.7      # linhas ou |valor| abaixo de 70% do anterior → suspeito
TOLERANCIA_DATA_FORA = 0.01  # até 1% das linhas com data fora do mês pedido → aviso, não erro
# Duplicidade sistemática — dois níveis (ver docstring e rules/despesas.md):
#  (a) por (unidade gestora, dia): ≥ DUP_FRACAO das linhas distintas do dia repetidas;
#  (b) pela partição inteira: ≥ DUP_PART_MIN linhas distintas repetidas E ≥ DUP_PART_FRACAO
#      das distintas — em jan–mai/2026 a origem repete lotes que atravessam dias
#      (32–54% das linhas de um dia), o que o nível (a) não enxerga. Nos meses limpos
#      de 2025 a taxa de linhas idênticas legítimas fica entre 0,02% e 3%.
DUP_MIN_LINHAS = 3        # mínimo de linhas distintas no dia p/ avaliar o padrão (a)
DUP_FRACAO = 0.9          # ≥ 90% das linhas distintas repetidas → sistemática (a)
DUP_PART_MIN = 50         # mínimo de linhas distintas repetidas p/ avaliar (b)
DUP_PART_FRACAO = 0.05    # ≥ 5% das linhas distintas repetidas → partição sistemática (b)

# A API de Santos devolve, misturada, a entidade-demonstração da plataforma
# Portal TP ("PREFEITURA MUNICIPAL DEMONSTRAÇÃO" — dados de um município de
# Rondônia, R$ 696 mi 2025-01→2025-10; levantamento 2026-07). Não é despesa de
# Santos: descartamos na coleta e expurgamos o que já entrou no cache.
UG_EXCLUIR = "DEMONSTRA"

# Campos comuns a todos os estágios (base do registro)
COMUNS = [
    "ano", "mes", "unidade_gestora", "data", "especie", "empenho",
    "elemento_despesa", "subtitulo", "funcao", "subfuncao", "programa",
    "fonte_recurso", "grupo_despesa", "documento_favorecido", "nome_favorecido", "valor",
]
OBRIGATORIOS = ("unidade_gestora", "data", "valor")   # sem eles a linha é inválida

# Definição de cada stream: endpoint, tabela, colunas extras e chave natural
# (identifica o documento SEM o valor — serve p/ reconhecer "mesma linha, valor
# corrigido" na reconciliação; a identidade da linha em si é o hash do conteúdo).
STREAMS = {
    "empenhos": {
        "endpoint": "json_empenhos",
        "tabela": "empenhos",
        "extras": ["tipo_empenho"],
        "chave": ["unidade_gestora", "empenho", "data", "especie", "elemento_despesa"],
    },
    "liquidacoes": {
        "endpoint": "json_liquidacoes",
        "tabela": "liquidacoes",
        "extras": ["liquidacao", "tipo_liquidacao"],
        "chave": ["unidade_gestora", "empenho", "liquidacao", "data", "especie"],
    },
    "pagamentos": {
        "endpoint": "json_pagamentos",
        "tabela": "pagamentos",
        "extras": ["liquidacao", "pagamento", "tipo_pagamento"],
        "chave": ["unidade_gestora", "empenho", "liquidacao", "pagamento", "data", "especie",
                  "elemento_despesa", "documento_favorecido"],
    },
}


class RespostaInvalida(Exception):
    """A resposta da origem não passou na validação — nada é gravado."""


class ParticaoSuspeita(Exception):
    """A resposta é válida, mas incompatível com a partição já carregada."""


def _cols(fonte: str) -> list[str]:
    """Colunas da tabela do stream = comuns + extras (empenho já está em comuns)."""
    extras = [c for c in STREAMS[fonte]["extras"]]
    # insere extras logo após 'empenho' para legibilidade do schema
    base = COMUNS.copy()
    i = base.index("empenho") + 1
    return base[:i] + extras + base[i:]


def _schema() -> str:
    partes = [f"""
    CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
    INSERT OR IGNORE INTO meta (chave, valor) VALUES ('schema_versao', '{SCHEMA_VERSAO}');
    CREATE TABLE IF NOT EXISTS controle_carga (
        fonte      TEXT,
        ano        INTEGER,
        mes        INTEGER,
        registros  INTEGER,      -- linhas efetivas na partição (visão corrente)
        soma       REAL,         -- soma das linhas efetivas
        baixado_em TEXT,         -- quando a partição corrente foi gravada
        brutos     INTEGER,      -- linhas devolvidas pela origem (após retirar a demo)
        descartados INTEGER,     -- linhas removidas por duplicidade sistemática
        soma_descartada REAL,
        duplicidade TEXT,        -- diagnóstico JSON da duplicidade (ou NULL)
        status     TEXT,         -- resultado da ÚLTIMA tentativa: ok | suspeito | erro
        erro       TEXT,         -- motivo, quando status <> ok
        tentado_em TEXT,         -- quando foi a última tentativa
        PRIMARY KEY (fonte, ano, mes)
    );
    CREATE TABLE IF NOT EXISTS historico_reconciliacao (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fonte TEXT, ano INTEGER, mes INTEGER, executado_em TEXT,
        antes_n INTEGER, antes_soma REAL, depois_n INTEGER, depois_soma REAL,
        adicionados INTEGER, removidos INTEGER, alterados INTEGER, descartados INTEGER
    );
    CREATE TABLE IF NOT EXISTS linhas_historico (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fonte TEXT, ano INTEGER, mes INTEGER,
        motivo TEXT,             -- removido | substituido | duplicidade_sistematica
        registrado_em TEXT,
        hash TEXT, repeticao INTEGER,
        conteudo TEXT            -- a linha como estava (JSON)
    );
    CREATE INDEX IF NOT EXISTS ix_linhas_historico_part ON linhas_historico(fonte, ano, mes);"""]
    for fonte, cfg in STREAMS.items():
        defs = ",\n        ".join(
            f"{c} {'REAL' if c == 'valor' else ('INTEGER' if c in ('ano', 'mes') else 'TEXT')}"
            for c in _cols(fonte))
        partes.append(f"""
    CREATE TABLE IF NOT EXISTS {cfg['tabela']} (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        hash TEXT,               -- md5 de TODO o conteúdo da linha
        repeticao INTEGER DEFAULT 1,  -- ordinal entre linhas idênticas mantidas
        {defs},
        UNIQUE (hash, repeticao)
    );
    CREATE INDEX IF NOT EXISTS ix_{cfg['tabela']}_empenho ON {cfg['tabela']}(unidade_gestora, empenho);
    CREATE INDEX IF NOT EXISTS ix_{cfg['tabela']}_ano_mes ON {cfg['tabela']}(ano, mes);""")
    return "\n".join(partes)


# ── HTTP / parsing ────────────────────────────────────────────────────────────
def _http_get(url: str, params: dict, tentativas: int = 4) -> requests.Response:
    return http.get(url, params, tentativas=tentativas, passo=5, timeout=120, headers=HEADERS)


def _data_iso(valor) -> str:
    return str(valor).split("T", 1)[0].strip() if valor else ""


def _hash_linha(fonte: str, item: dict) -> str:
    """Identidade da linha = todo o conteúdo (sem o valor de fora, como na v1)."""
    return hashlib.md5(
        "|".join("" if item.get(c) is None else str(item.get(c)) for c in _cols(fonte))
        .encode("utf-8")).hexdigest()


def _chave_natural(fonte: str, item: dict) -> str:
    return "|".join("" if item.get(c) is None else str(item.get(c)) for c in STREAMS[fonte]["chave"])


def baixar_bruto(fonte: str, ano: int, mes: int, bruto_dir: str | None = None):
    """Devolve o array JSON da origem. Com `bruto_dir`, reusa/guarda a resposta em disco
    (cache reprodutível p/ reconstrução e testes; nunca versionado)."""
    cfg = STREAMS[fonte]
    arq = os.path.join(bruto_dir, f"{fonte}-{ano}-{mes:02d}.json") if bruto_dir else None
    if arq and os.path.exists(arq):
        with open(arq, encoding="utf-8") as f:
            d = json.load(f)
        return d["itens"] if isinstance(d, dict) else d
    r = _http_get(f"{API}/{cfg['endpoint']}", {"ano": ano, "mes": mes})
    try:
        bruto = html.unescape(ET.fromstring(r.content).text or "").strip()
    except ET.ParseError as e:
        raise RespostaInvalida(f"XML SOAP inválido: {e}") from e
    if not bruto:
        dados = []
    else:
        try:
            dados = json.loads(bruto)
        except ValueError as e:
            raise RespostaInvalida(f"JSON embutido inválido: {e}") from e
    if arq:
        os.makedirs(bruto_dir, exist_ok=True)
        tmp = arq + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"status": r.status_code, "n": len(dados) if isinstance(dados, list) else None,
                       "baixado_em": datetime.now().isoformat(timespec="seconds"), "itens": dados},
                      f, ensure_ascii=False)
        os.replace(tmp, arq)
    return dados


def validar_resposta(fonte: str, ano: int, mes: int, dados) -> list[str]:
    """Checa formato e conteúdo ANTES de qualquer normalização. Devolve os problemas
    fatais (lista vazia = válida)."""
    problemas = []
    if not isinstance(dados, list):
        return [f"resposta não é uma lista JSON ({type(dados).__name__})"]
    fora = 0
    prefixo = f"{ano}-{mes:02d}"
    for i, d in enumerate(dados):
        if not isinstance(d, dict):
            problemas.append(f"item {i} não é objeto")
            break
        if UG_EXCLUIR in (d.get("unidade_gestora") or "").upper():
            continue
        faltam = [c for c in OBRIGATORIOS if c not in d]
        if faltam:
            problemas.append(f"item {i} sem campos obrigatórios {faltam}")
            break
        if d.get("valor") is not None:
            try:
                float(d.get("valor"))
            except (TypeError, ValueError):
                problemas.append(f"item {i} com valor não numérico: {d.get('valor')!r}")
                break
        if not _data_iso(d.get("data")).startswith(prefixo):
            fora += 1
    n = max(1, len(dados))
    if fora / n > TOLERANCIA_DATA_FORA:
        problemas.append(f"{fora} de {len(dados)} linhas com data fora de {prefixo}")
    return problemas


def normalizar(fonte: str, ano: int, mes: int, dados: list) -> tuple[list[dict], int]:
    """Converte o array da origem em linhas do banco (sem a entidade-demonstração).
    Devolve (itens, descartados_demo)."""
    cols = _cols(fonte)
    itens, descartados = [], 0
    for d in dados:
        if UG_EXCLUIR in (d.get("unidade_gestora") or "").upper():
            descartados += 1
            continue
        try:
            valor = round(float(d.get("valor")), 2) if d.get("valor") is not None else 0.0
        except (TypeError, ValueError):
            valor = 0.0
        item = {c: d.get(c) for c in cols}
        item["ano"] = int(ano)
        item["mes"] = int(mes)
        item["data"] = _data_iso(d.get("data"))
        item["valor"] = valor
        item["hash"] = _hash_linha(fonte, item)
        itens.append(item)
    return itens, descartados


def coletar_mes(fonte: str, ano: int, mes: int, bruto_dir: str | None = None) -> list[dict]:
    """Baixa, valida e normaliza os registros de um stream/ano/mês (sem tratar
    duplicidade — ver `tratar_duplicidade`). Levanta RespostaInvalida."""
    dados = baixar_bruto(fonte, ano, mes, bruto_dir)
    problemas = validar_resposta(fonte, ano, mes, dados)
    if problemas:
        raise RespostaInvalida("; ".join(problemas))
    itens, descartados = normalizar(fonte, ano, mes, dados)
    if descartados:
        print(f"  {descartados} registros da entidade-demonstração descartados.", file=sys.stderr)
    return itens


# ── Duplicidade sistemática ───────────────────────────────────────────────────
def tratar_duplicidade(itens: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Numera repetições (`repeticao`) e reduz grupos idênticos onde a duplicação é
    sistemática por (unidade gestora, dia). Devolve (efetivos, descartados, diagnóstico).

    diagnóstico = {"identicas": nº de linhas repetidas na origem (além da 1ª),
                   "valor_identicas": soma delas,
                   "sistematica": [{"ug", "data", "fator", "distintas", "descartadas"}, ...],
                   "particao": {"fator", "distintas", "repetidas", "descartadas"} | None}
    """
    por_hash: dict[str, list[dict]] = defaultdict(list)
    for it in itens:
        por_hash[it["hash"]].append(it)
    identicas = sum(len(g) - 1 for g in por_hash.values())
    valor_identicas = round(sum(g[0]["valor"] * (len(g) - 1) for g in por_hash.values()), 2)

    # padrão por (ug, dia): fração de linhas distintas que aparecem ≥ 2×
    grupos_dia: dict[tuple, list[list[dict]]] = defaultdict(list)
    for g in por_hash.values():
        grupos_dia[(g[0]["unidade_gestora"], g[0]["data"])].append(g)
    fator_dia: dict[tuple, int] = {}
    sistematica = []
    for chave, grupos in grupos_dia.items():
        if len(grupos) < DUP_MIN_LINHAS:
            continue
        repetidos = [len(g) for g in grupos if len(g) > 1]
        if len(repetidos) / len(grupos) < DUP_FRACAO:
            continue
        fator = Counter(repetidos).most_common(1)[0][0]
        fator_dia[chave] = fator
        sistematica.append({"ug": chave[0], "data": chave[1], "fator": fator,
                            "distintas": len(grupos), "descartadas": 0})

    # nível (b): a partição inteira
    repetidos_part = [len(g) for g in por_hash.values() if len(g) > 1]
    particao = None
    if (len(repetidos_part) >= DUP_PART_MIN and por_hash
            and len(repetidos_part) / len(por_hash) >= DUP_PART_FRACAO):
        particao = {"fator": Counter(repetidos_part).most_common(1)[0][0], "distintas": len(por_hash),
                    "repetidas": len(repetidos_part), "descartadas": 0}

    # Dentro de um padrão sistemático cada grupo idêntico fica com UMA linha: nos meses
    # limpos de 2025 a taxa de pares idênticos legítimos é < 0,2%, e em 2026-05 apareceram
    # 300 grupos ×4 (subvenções de 4–7/mai) que só se explicam pelo defeito aplicado duas
    # vezes. Grupos com multiplicidade > fator são contados em `multiplas` para revisão.
    efetivos, descartados = [], []
    diag_por_chave = {(s["ug"], s["data"]): s for s in sistematica}
    multiplas = 0
    for g in por_hash.values():
        chave = (g[0]["unidade_gestora"], g[0]["data"])
        manter = len(g)
        if chave in fator_dia:
            manter = 1
            diag_por_chave[chave]["descartadas"] += len(g) - manter
            multiplas += len(g) > fator_dia[chave]
        elif particao and len(g) > 1:
            manter = 1
            particao["descartadas"] += len(g) - manter
            multiplas += len(g) > particao["fator"]
        for i, it in enumerate(g, 1):
            it["repeticao"] = i
            (efetivos if i <= manter else descartados).append(it)
    diag = {"identicas": identicas, "valor_identicas": valor_identicas,
            "sistematica": sorted(sistematica, key=lambda s: (s["ug"], s["data"])), "particao": particao,
            "multiplas": multiplas}
    return efetivos, descartados, diag


# ── Banco ─────────────────────────────────────────────────────────────────────
def _versao_schema(conn) -> int:
    tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "meta" not in tabelas:
        return 1 if tabelas & {"empenhos", "liquidacoes", "pagamentos", "controle_carga"} else 0
    r = conn.execute("SELECT valor FROM meta WHERE chave='schema_versao'").fetchone()
    return int(r[0]) if r else 1


def migrar_v1(conn, db_path: str | None) -> None:
    """Esquema v1 (hash UNIQUE com dedup destrutiva): faz backup do arquivo e recria
    as tabelas vazias — TODAS as partições serão reconciliadas na próxima carga
    (a base v1 perdeu linhas legítimas idênticas e guarda linhas que a origem
    corrigiu; não há como consertá-la sem rebaixar tudo)."""
    if db_path and os.path.exists(db_path):
        bak = f"{db_path}.bak-v1-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(db_path, bak)
        print(f"Esquema v1 detectado: backup em {bak}; tabelas recriadas para reconciliação completa.",
              file=sys.stderr)
    for cfg in STREAMS.values():
        conn.execute(f"DROP TABLE IF EXISTS {cfg['tabela']}")
    conn.execute("DROP TABLE IF EXISTS controle_carga")
    conn.commit()


def abrir_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    if _versao_schema(conn) == 1:
        migrar_v1(conn, None if db_path == ":memory:" else db_path)
    conn.executescript(_schema())
    conn.execute("UPDATE meta SET valor=? WHERE chave='schema_versao'", (str(SCHEMA_VERSAO),))
    conn.commit()
    expurgar_demo(conn)
    return conn


def expurgar_demo(conn: sqlite3.Connection) -> int:
    """Remove da base os registros da entidade-demonstração já gravados em
    cargas antigas (o cache do Actions persiste entre execuções). Idempotente."""
    total = 0
    for cfg in STREAMS.values():
        cur = conn.execute(
            f"DELETE FROM {cfg['tabela']} WHERE UPPER(unidade_gestora) LIKE ?",
            (f"%{UG_EXCLUIR}%",))
        total += cur.rowcount
    if total:
        conn.commit()
        print(f"Expurgo: {total} registros da entidade-demonstração removidos do cache.",
              file=sys.stderr)
    return total


def carregados(conn: sqlite3.Connection) -> set[tuple[str, int, int]]:
    """Partições com conteúdo gravado (independe do resultado da última tentativa)."""
    return {(r[0], r[1], r[2]) for r in conn.execute(
        "SELECT fonte, ano, mes FROM controle_carga WHERE baixado_em IS NOT NULL")}


def _estado_particao(conn, fonte, ano, mes) -> dict:
    t = STREAMS[fonte]["tabela"]
    r = conn.execute(f"SELECT COUNT(*) n, COALESCE(SUM(valor),0) s, COALESCE(SUM(ABS(valor)),0) sa "
                     f"FROM {t} WHERE ano=? AND mes=?", (ano, mes)).fetchone()
    return {"n": r[0], "soma": round(r[1], 2), "soma_abs": round(r[2], 2)}


def validar_particao(conn, fonte, ano, mes, efetivos: list[dict],
                     aceitar_vazio=False, aceitar_reducao=False) -> None:
    """Compara a resposta (já sem duplicidade sistemática) com a partição corrente.
    Levanta ParticaoSuspeita quando a troca parece destruir dados válidos."""
    antes = _estado_particao(conn, fonte, ano, mes)
    if antes["n"] == 0:
        return
    if not efetivos:
        if aceitar_vazio:
            return
        raise ParticaoSuspeita(
            f"resposta vazia para partição com {antes['n']} linhas (R$ {antes['soma']:,.2f}); "
            f"mantida a anterior — use --aceitar-vazio se a exclusão for legítima")
    n = len(efetivos)
    soma_abs = round(sum(abs(it["valor"]) for it in efetivos), 2)
    if n < LIMITE_REDUCAO * antes["n"] or (antes["soma_abs"] and soma_abs < LIMITE_REDUCAO * antes["soma_abs"]):
        if aceitar_reducao:
            return
        raise ParticaoSuspeita(
            f"queda abrupta: {antes['n']} → {n} linhas, |valor| R$ {antes['soma_abs']:,.2f} → "
            f"R$ {soma_abs:,.2f}; mantida a anterior — use --aceitar-reducao se for legítimo")


def _registrar_tentativa(conn, fonte, ano, mes, status, erro=None):
    agora = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO controle_carga (fonte, ano, mes, status, erro, tentado_em) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(fonte, ano, mes) DO UPDATE SET status=excluded.status, erro=excluded.erro, "
        "tentado_em=excluded.tentado_em",
        (fonte, ano, mes, status, erro, agora))
    conn.commit()


def reconciliar(conn, fonte: str, ano: int, mes: int, itens: list[dict],
                aceitar_vazio=False, aceitar_reducao=False) -> dict:
    """Substitui a partição (fonte, ano, mês) pelo conteúdo de `itens` numa transação
    única, preservando o histórico do que saiu. Devolve o resumo gravado em
    `historico_reconciliacao`. Em RespostaInvalida/ParticaoSuspeita nada muda além
    do registro da tentativa em `controle_carga`."""
    cfg = STREAMS[fonte]
    tabela = cfg["tabela"]
    cols = _cols(fonte)
    efetivos, descartados, diag = tratar_duplicidade(itens)
    try:
        validar_particao(conn, fonte, ano, mes, efetivos, aceitar_vazio, aceitar_reducao)
    except ParticaoSuspeita as e:
        _registrar_tentativa(conn, fonte, ano, mes, "suspeito", str(e))
        raise

    agora = datetime.now().isoformat(timespec="seconds")
    antes = _estado_particao(conn, fonte, ano, mes)
    conn.commit()                       # fecha transação implícita, se houver
    conn.execute("BEGIN IMMEDIATE")
    try:
        # o que existe hoje na partição (para o diff e o histórico)
        antigas = {}
        for r in conn.execute(f"SELECT hash, repeticao, {','.join(cols)} FROM {tabela} "
                              f"WHERE ano=? AND mes=?", (ano, mes)):
            antigas[(r[0], r[1])] = dict(zip(cols, r[2:]))
        novas = {(it["hash"], it["repeticao"]): it for it in efetivos}
        removidas = {k: v for k, v in antigas.items() if k not in novas}
        adicionadas = [it for k, it in novas.items() if k not in antigas]
        chaves_novas = Counter(_chave_natural(fonte, it) for it in adicionadas)
        alterados = 0
        for (h, rep), linha in removidas.items():
            motivo = "removido"
            if chaves_novas.get(_chave_natural(fonte, linha)):
                motivo, alterados = "substituido", alterados + 1
            conn.execute(
                "INSERT INTO linhas_historico (fonte, ano, mes, motivo, registrado_em, hash, repeticao, conteudo) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (fonte, ano, mes, motivo, agora, h, rep, json.dumps(linha, ensure_ascii=False)))
        for it in descartados:
            conn.execute(
                "INSERT INTO linhas_historico (fonte, ano, mes, motivo, registrado_em, hash, repeticao, conteudo) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (fonte, ano, mes, "duplicidade_sistematica", agora, it["hash"], it["repeticao"],
                 json.dumps({c: it.get(c) for c in cols}, ensure_ascii=False)))

        conn.execute(f"DELETE FROM {tabela} WHERE ano=? AND mes=?", (ano, mes))
        todas = ["hash", "repeticao"] + cols
        ph = ",".join("?" for _ in todas)
        conn.executemany(f"INSERT INTO {tabela} ({','.join(todas)}) VALUES ({ph})",
                         [[it.get(c) for c in todas] for it in efetivos])

        # conferência: o que ficou no banco tem de bater com a resposta
        depois = _estado_particao(conn, fonte, ano, mes)
        soma_esp = round(sum(it["valor"] for it in efetivos), 2)
        if depois["n"] != len(efetivos) or abs(depois["soma"] - soma_esp) > 0.01:
            raise RuntimeError(f"conferência falhou: banco {depois['n']}/{depois['soma']} "
                               f"× resposta {len(efetivos)}/{soma_esp}")

        resumo = {"fonte": fonte, "ano": ano, "mes": mes, "executado_em": agora,
                  "antes_n": antes["n"], "antes_soma": antes["soma"],
                  "depois_n": depois["n"], "depois_soma": depois["soma"],
                  "adicionados": len(adicionadas), "removidos": len(removidas) - alterados,
                  "alterados": alterados, "descartados": len(descartados)}
        conn.execute(
            "INSERT INTO historico_reconciliacao (fonte, ano, mes, executado_em, antes_n, antes_soma, "
            "depois_n, depois_soma, adicionados, removidos, alterados, descartados) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (fonte, ano, mes, agora, antes["n"], antes["soma"], depois["n"], depois["soma"],
             resumo["adicionados"], resumo["removidos"], alterados, len(descartados)))
        conn.execute(
            "INSERT INTO controle_carga (fonte, ano, mes, registros, soma, baixado_em, brutos, descartados, "
            "soma_descartada, duplicidade, status, erro, tentado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(fonte, ano, mes) DO UPDATE SET registros=excluded.registros, soma=excluded.soma, "
            "baixado_em=excluded.baixado_em, brutos=excluded.brutos, descartados=excluded.descartados, "
            "soma_descartada=excluded.soma_descartada, duplicidade=excluded.duplicidade, "
            "status='ok', erro=NULL, tentado_em=excluded.tentado_em",
            (fonte, ano, mes, depois["n"], depois["soma"], agora, len(itens), len(descartados),
             round(sum(it["valor"] for it in descartados), 2),
             json.dumps(diag, ensure_ascii=False) if (diag["identicas"] or diag["sistematica"] or diag["particao"]) else None,
             "ok", None, agora))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return resumo


def gravar(conn, fonte: str, ano: int, mes: int, itens: list[dict]) -> int:
    """Compatibilidade com o nome antigo: reconcilia e devolve linhas adicionadas."""
    return reconciliar(conn, fonte, ano, mes, itens)["adicionados"]


# ── Orquestração ──────────────────────────────────────────────────────────────
def meses_alvo(arg_ano: int | None, arg_mes: int | None) -> list[tuple[int, int]]:
    hoje = datetime.now()
    anos = [arg_ano] if arg_ano else list(range(ANO_INICIAL, hoje.year + 1))
    pares = []
    for ano in anos:
        for mes in ([arg_mes] if arg_mes else range(1, 13)):
            if ano == hoje.year and mes > hoje.month:
                continue
            pares.append((ano, mes))
    return pares


def main():
    p = argparse.ArgumentParser(description="Crawler de Despesas (Prefeitura de Santos) — execução orçamentária")
    p.add_argument("--ano", type=int, help="Ano específico. Padrão: 2025→ano corrente.")
    p.add_argument("--mes", type=int, help="Mês específico (1-12). Padrão: todos.")
    p.add_argument("--fonte", choices=list(STREAMS), help="Só um stream. Padrão: os três.")
    p.add_argument("--limite", type=int, default=0, help="Máx. de registros a imprimir no dry-run.")
    p.add_argument("--forcar", action="store_true", help="Reconcilia meses já carregados.")
    p.add_argument("--dry-run", action="store_true", help="Não grava no banco (só baixa e resume).")
    p.add_argument("--db", default=DB_PATH, help="Caminho do SQLite (padrão: despesas/despesas.sqlite).")
    p.add_argument("--bruto-dir", help="Diretório-cache das respostas brutas (reusa se existir).")
    p.add_argument("--aceitar-vazio", action="store_true",
                   help="Aceita resposta vazia p/ partição já carregada (exclusão legítima do mês).")
    p.add_argument("--aceitar-reducao", action="store_true",
                   help="Aceita queda abrupta de linhas/valor na partição.")
    p.add_argument("--relatorio", metavar="PATH", help="Grava um JSON com o resultado por partição.")
    args = p.parse_args()

    fontes = [args.fonte] if args.fonte else list(STREAMS)
    conn = None if args.dry_run else abrir_db(args.db)
    ja = carregados(conn) if conn else set()
    total = 0
    resultados = []   # um por (fonte, ano, mes) tentado

    for ano, mes in meses_alvo(args.ano, args.mes):
        for fonte in fontes:
            if conn and (fonte, ano, mes) in ja and not args.forcar:
                print(f"== {fonte} {ano}-{mes:02d}: já carregado (use --forcar) ==", file=sys.stderr)
                continue
            print(f"== {fonte} {ano}-{mes:02d} ==", file=sys.stderr)
            reg = {"fonte": fonte, "ano": ano, "mes": mes, "status": "ok"}
            resultados.append(reg)
            try:
                itens = coletar_mes(fonte, ano, mes, args.bruto_dir)
            except RespostaInvalida as e:
                print(f"  RESPOSTA INVÁLIDA em {fonte} {ano}-{mes:02d}: {e} — partição mantida.",
                      file=sys.stderr)
                reg.update(status="erro", erro=str(e))
                if conn:
                    _registrar_tentativa(conn, fonte, ano, mes, "erro", str(e))
                continue
            except Exception as e:
                print(f"  ERRO em {fonte} {ano}-{mes:02d}: {e} — pulando.", file=sys.stderr)
                reg.update(status="erro", erro=str(e))
                if conn:
                    _registrar_tentativa(conn, fonte, ano, mes, "erro", str(e))
                continue
            soma = round(sum(it["valor"] for it in itens), 2)
            if args.dry_run:
                efetivos, descartados, diag = tratar_duplicidade(itens)
                print(f"  {len(itens)} registros | soma R$ {soma:,.2f} | "
                      f"{len(descartados)} descartados por duplicidade sistemática", file=sys.stderr)
                for it in itens[: (args.limite or 4)]:
                    print(f"    {it['data']} | emp {str(it.get('empenho')):14} | "
                          f"R$ {it['valor']:>12,.2f} | {(it['nome_favorecido'] or '')[:34]}")
            else:
                try:
                    r = reconciliar(conn, fonte, ano, mes, itens,
                                    args.aceitar_vazio, args.aceitar_reducao)
                except ParticaoSuspeita as e:
                    print(f"  SUSPEITO em {fonte} {ano}-{mes:02d}: {e}", file=sys.stderr)
                    reg.update(status="suspeito", erro=str(e))
                    continue
                reg.update({k: r[k] for k in ("antes_n", "depois_n", "adicionados",
                                              "removidos", "alterados", "descartados")})
                print(f"  {len(itens)} registros → {r['depois_n']} efetivos "
                      f"(+{r['adicionados']} −{r['removidos']} ~{r['alterados']} "
                      f"dup {r['descartados']}) | soma R$ {r['depois_soma']:,.2f}", file=sys.stderr)
            total += len(itens)
            time.sleep(PAUSA)

    if conn:
        conn.close()
    sucessos = sum(1 for r in resultados if r["status"] == "ok")
    falhas = [r for r in resultados if r["status"] != "ok"]
    print(f"Concluído: {total} registros processados "
          f"({sucessos} coletas ok, {len(falhas)} com erro/suspeita).", file=sys.stderr)
    if falhas:
        print("Partições NÃO atualizadas (versão anterior mantida):", file=sys.stderr)
        for r in falhas:
            print(f"  - {r['fonte']} {r['ano']}-{r['mes']:02d} [{r['status']}]: {r['erro']}", file=sys.stderr)
    if args.relatorio:
        with open(args.relatorio, "w", encoding="utf-8") as f:
            json.dump({"executado_em": datetime.now().isoformat(timespec="seconds"),
                       "ok": sucessos, "falhas": len(falhas), "particoes": resultados},
                      f, ensure_ascii=False, indent=1)

    # Falha visível: se TUDO que se tentou baixar deu erro, o portal nos barrou
    # (foi o que aconteceu em 2026-07-09, quando o WAF passou a rejeitar o UA) e
    # a base parou por 40 dias com o workflow verde. Sair 1 aborta o pipeline.
    # Falha PARCIAL sai 2: as partições boas foram atualizadas, mas o workflow
    # precisa ficar vermelho — uma coleta boa não pode esconder a que falhou.
    # Nada tentado (cache quente, 0 erros) segue sendo sucesso legítimo.
    if falhas and not sucessos:
        print(f"ERRO FATAL: nenhuma coleta funcionou ({len(falhas)} falhas). "
              f"Portal fora do ar, bloqueio por User-Agent ou API mudou.", file=sys.stderr)
        sys.exit(1)
    if falhas:
        sys.exit(2)


if __name__ == "__main__":
    main()
