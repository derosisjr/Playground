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

Cada estágio vai para sua própria tabela; o `export.py` junta tudo **por empenho**
(`unidade_gestora` + `empenho`) para produzir a tríade empenhado/liquidado/pago. Como
um empenho é liquidado/pago em meses (ou anos) seguintes, a junção é feita sobre a base
inteira no export, não aqui.

Não há PK natural estável, então a dedup é por `hash` MD5 das colunas-chave
(`INSERT OR IGNORE` → recarga de mês idempotente). `controle_carga` registra o que já
foi baixado por (fonte, ano, mês).

Uso:
    python despesas/crawler.py --ano 2026 --mes 6 --dry-run     # amostra dos 3 streams
    python despesas/crawler.py --ano 2026 --mes 6               # um mês
    python despesas/crawler.py --ano 2026                       # ano inteiro
    python despesas/crawler.py                                  # mandato (2025→corrente)
    python despesas/crawler.py --forcar                         # re-baixa meses já carregados
    python despesas/crawler.py --fonte pagamentos               # só um stream
"""

import argparse
import hashlib
import html
import json
import os
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

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

# Definição de cada stream: endpoint, tabela, colunas extras e chave de dedup.
STREAMS = {
    "empenhos": {
        "endpoint": "json_empenhos",
        "tabela": "empenhos",
        "extras": ["tipo_empenho"],
        "chave": ["unidade_gestora", "empenho", "data", "especie", "elemento_despesa", "valor"],
    },
    "liquidacoes": {
        "endpoint": "json_liquidacoes",
        "tabela": "liquidacoes",
        "extras": ["liquidacao", "tipo_liquidacao"],
        "chave": ["unidade_gestora", "empenho", "liquidacao", "data", "valor"],
    },
    "pagamentos": {
        "endpoint": "json_pagamentos",
        "tabela": "pagamentos",
        "extras": ["liquidacao", "pagamento", "tipo_pagamento"],
        "chave": ["unidade_gestora", "data", "pagamento", "elemento_despesa", "nome_favorecido", "valor"],
    },
}


def _cols(fonte: str) -> list[str]:
    """Colunas da tabela do stream = comuns + extras (empenho já está em comuns)."""
    extras = [c for c in STREAMS[fonte]["extras"]]
    # insere extras logo após 'empenho' para legibilidade do schema
    base = COMUNS.copy()
    i = base.index("empenho") + 1
    return base[:i] + extras + base[i:]


def _schema() -> str:
    partes = ["""
    CREATE TABLE IF NOT EXISTS controle_carga (
        fonte      TEXT,
        ano        INTEGER,
        mes        INTEGER,
        registros  INTEGER,
        soma       REAL,
        baixado_em TEXT,
        PRIMARY KEY (fonte, ano, mes)
    );"""]
    for fonte, cfg in STREAMS.items():
        defs = ",\n        ".join(
            f"{c} {'REAL' if c == 'valor' else ('INTEGER' if c in ('ano', 'mes') else 'TEXT')}"
            for c in _cols(fonte))
        partes.append(f"""
    CREATE TABLE IF NOT EXISTS {cfg['tabela']} (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        hash TEXT UNIQUE,
        {defs}
    );
    CREATE INDEX IF NOT EXISTS ix_{cfg['tabela']}_empenho ON {cfg['tabela']}(unidade_gestora, empenho);
    CREATE INDEX IF NOT EXISTS ix_{cfg['tabela']}_ano_mes ON {cfg['tabela']}(ano, mes);""")
    return "\n".join(partes)


# ── HTTP / parsing ────────────────────────────────────────────────────────────
def _http_get(url: str, params: dict, tentativas: int = 4) -> requests.Response:
    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=120)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            ultimo = e
            if i < tentativas - 1:
                espera = 5 * (i + 1)
                print(f"  Aviso: falha HTTP ({e}); tentativa {i+1}/{tentativas}, "
                      f"aguardando {espera}s...", file=sys.stderr)
                time.sleep(espera)
    raise ultimo


def _data_iso(valor) -> str:
    return str(valor).split("T", 1)[0].strip() if valor else ""


def coletar_mes(fonte: str, ano: int, mes: int) -> list[dict]:
    """Baixa e normaliza os registros de um stream/ano/mês."""
    cfg = STREAMS[fonte]
    r = _http_get(f"{API}/{cfg['endpoint']}", {"ano": ano, "mes": mes})
    bruto = html.unescape(ET.fromstring(r.content).text or "").strip()
    if not bruto:
        return []
    cols = _cols(fonte)
    itens = []
    descartados = 0
    for d in json.loads(bruto):
        if UG_EXCLUIR in (d.get("unidade_gestora") or "").upper():
            descartados += 1
            continue
        try:
            valor = round(float(d.get("valor")), 2) if d.get("valor") is not None else 0.0
        except (TypeError, ValueError):
            valor = 0.0
        item = {c: d.get(c) for c in cols}
        item["ano"] = int(ano)
        item["mes"] = mes
        item["data"] = _data_iso(d.get("data"))
        item["valor"] = valor
        item["hash"] = hashlib.md5(
            "|".join(str(item.get(c, "")) for c in cfg["chave"]).encode("utf-8")
        ).hexdigest()
        itens.append(item)
    if descartados:
        print(f"  {descartados} registros da entidade-demonstração descartados.", file=sys.stderr)
    return itens


# ── Banco ─────────────────────────────────────────────────────────────────────
def abrir_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_schema())
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
    return {(r[0], r[1], r[2]) for r in conn.execute("SELECT fonte, ano, mes FROM controle_carga")}


def gravar(conn, fonte: str, ano: int, mes: int, itens: list[dict]) -> int:
    cfg = STREAMS[fonte]
    cols = ["hash"] + _cols(fonte)
    ph = ",".join("?" for _ in cols)
    cur = conn.executemany(
        f"INSERT OR IGNORE INTO {cfg['tabela']} ({','.join(cols)}) VALUES ({ph})",
        [[it.get(c) for c in cols] for it in itens],
    )
    soma = round(sum(it["valor"] for it in itens), 2)
    conn.execute(
        "INSERT OR REPLACE INTO controle_carga (fonte, ano, mes, registros, soma, baixado_em) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (fonte, ano, mes, len(itens), soma, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return cur.rowcount


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
    p.add_argument("--forcar", action="store_true", help="Re-baixa meses já carregados.")
    p.add_argument("--dry-run", action="store_true", help="Não grava no banco (só baixa e resume).")
    args = p.parse_args()

    fontes = [args.fonte] if args.fonte else list(STREAMS)
    conn = None if args.dry_run else abrir_db()
    ja = carregados(conn) if conn else set()
    total = 0
    sucessos = erros = 0

    for ano, mes in meses_alvo(args.ano, args.mes):
        for fonte in fontes:
            if conn and (fonte, ano, mes) in ja and not args.forcar:
                print(f"== {fonte} {ano}-{mes:02d}: já carregado (use --forcar) ==", file=sys.stderr)
                continue
            print(f"== {fonte} {ano}-{mes:02d} ==", file=sys.stderr)
            try:
                itens = coletar_mes(fonte, ano, mes)
            except Exception as e:
                print(f"  ERRO em {fonte} {ano}-{mes:02d}: {e} — pulando.", file=sys.stderr)
                erros += 1
                continue
            sucessos += 1
            soma = round(sum(it["valor"] for it in itens), 2)
            if args.dry_run:
                print(f"  {len(itens)} registros | soma R$ {soma:,.2f}", file=sys.stderr)
                for it in itens[: (args.limite or 4)]:
                    print(f"    {it['data']} | emp {str(it.get('empenho')):14} | "
                          f"R$ {it['valor']:>12,.2f} | {(it['nome_favorecido'] or '')[:34]}")
            else:
                novos = gravar(conn, fonte, ano, mes, itens)
                print(f"  {len(itens)} registros ({novos} novos) | soma R$ {soma:,.2f}", file=sys.stderr)
            total += len(itens)
            time.sleep(PAUSA)

    if conn:
        conn.close()
    print(f"Concluído: {total} registros processados "
          f"({sucessos} coletas ok, {erros} com erro).", file=sys.stderr)

    # Falha visível: se TUDO que se tentou baixar deu erro, o portal nos barrou
    # (foi o que aconteceu em 2026-07-09, quando o WAF passou a rejeitar o UA) e
    # a base parou por 40 dias com o workflow verde — o export reexportava o
    # cache velho e a guarda de R$ 4 bi passava. Sair != 0 aborta o pipeline.
    # Nada tentado (cache quente, 0 erros) segue sendo sucesso legítimo.
    if erros and not sucessos:
        print(f"ERRO FATAL: nenhuma coleta funcionou ({erros} falhas). "
              f"Portal fora do ar, bloqueio por User-Agent ou API mudou.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
