#!/usr/bin/env python3
"""
Export da base de Despesas → JSON (agregado), XLSX e CSV
========================================================

Lê `despesas/despesas.sqlite` e gera:
  - despesas-index.json (raiz)   índice AGREGADO consumido pelo painel despesas.html
                                 (séries mensais, top favorecidos, por função/fonte,
                                  alertas fiscais por regras) — único artefato versionado.
  - despesas/despesas.csv        pagamentos completos (análise/Excel; gitignored)
  - despesas/despesas.xlsx       idem, planilha p/ gabinete (gitignored)

O JSON é mantido enxuto: o painel trabalha com agregados; o detalhe linha-a-linha
fica no XLSX/CSV.

Uso:
    python despesas/export.py
"""

import csv
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
DB_PATH = os.path.join(AQUI, "despesas.sqlite")
CSV_PATH = os.path.join(AQUI, "despesas.csv")
XLSX_PATH = os.path.join(AQUI, "despesas.xlsx")
DADOS_DIR = os.path.join(AQUI, "dados")           # detalhe mensal versionado (consumido pelo painel)
JSON_PATH = os.path.join(RAIZ, "despesas-index.json")

COLUNAS = [
    "ano", "mes", "unidade_gestora", "data", "especie", "empenho", "liquidacao",
    "pagamento", "tipo_pagamento", "elemento_despesa", "subtitulo", "funcao",
    "subfuncao", "programa", "fonte_recurso", "grupo_despesa",
    "documento_favorecido", "nome_favorecido", "valor",
]

# ── Limiares dos alertas fiscais (ajuste fino aqui) ───────────────────────────
TOP_FAVORECIDOS = 300           # quantos favorecidos exportar no JSON
ALERTA_FAV_VALOR = 5_000_000    # favorecido acima disso no acumulado → alerta
ALERTA_FAV_MESES = 6            # ...presente em ao menos N meses (recorrência)
ALERTA_CONCENTRACAO_PCT = 40    # favorecido que domina >X% de uma função → alerta
ALERTA_CONCENTRACAO_MIN = 1_000_000   # ...e move ao menos isso (evita ruído)
ALERTA_PICO_K = 2.5             # mês cujo gasto > média + k·desvio → alerta
ALERTA_EXTRA_VALOR = 1_000_000  # pagamento extra-orçamentário acima disso → alerta

# Regras inteligentes adicionais (calibradas sobre a base do mandato)
# Lei 14.133/2021 art. 75 — limite de dispensa (compras/serviços). MANTER atualizado por decreto.
LIMITE_DISPENSA = 59_906        # usado p/ detectar fracionamento
FRAC_MIN_EMPENHOS = 4           # nº mínimo de empenhos < limite no mesmo favorecido+elemento+ano
FRAC_FATOR_TOTAL = 1.5          # ...somando ao menos FATOR×limite
ALERTA_NOVO_MESES = 6           # "novo" = 1ª aparição nos últimos N meses
ALERTA_NOVO_VALOR = 1_000_000   # ...e já acumulou ao menos isso
ALERTA_YOY_FATOR = 3.0          # crescimento anualizado do ano corrente ≥ FATOR× ano anterior
ALERTA_YOY_VALOR = 1_000_000    # ...e move ao menos isso no ano corrente
ALERTA_PF_VALOR = 100_000       # pessoa física (CPF) em elemento sensível acima disso
CAP_POR_REGRA = 15             # teto de alertas por regra nova (não afogar o painel/e-mail)
MAX_ALERTAS = 100              # era 60

# entes internos/governamentais — excluídos de "novo"/"YoY" (não são fornecedores de mercado)
EXCLUIR_ENTE = re.compile(
    r"MUNIC[IÍ]PIO|PREFEITURA|INSTITUTO DE PREVID|C[ÂA]MARA|FUNDO |FUNDA[ÇC][ÃA]O|"
    r"CAIXA DE ASSIST|\bIPS\b|CAPEP|RECEITA|TESOURO", re.I)
# CPF mascarado: sem "/" e com "*"; elementos sensíveis p/ pessoa física
SQL_EH_CPF = "documento_favorecido NOT LIKE '%/%' AND documento_favorecido LIKE '%*%'"
ELEM_SENSIVEIS = ("%LOCA%IM%", "%TERCEIRIZA%", "%INDENIZA%", "%CONSULTORIA%", "%TERCEIRO%F_SICA%")


def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _q(conn, sql, *params):
    return conn.execute(sql, params).fetchall()


# ── Agregações para o painel ──────────────────────────────────────────────────
def agregados(conn) -> dict:
    total = _q(conn, "SELECT COALESCE(SUM(valor),0) s, COUNT(*) n FROM pagamentos")[0]
    anos = _q(conn, "SELECT ano, SUM(valor) s, COUNT(*) n FROM pagamentos GROUP BY ano ORDER BY ano")
    minmax = _q(conn, "SELECT MIN(ano*100+mes) a, MAX(ano*100+mes) b FROM pagamentos")[0]

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
    favorecidos = _q(conn,
        "SELECT nome_favorecido k, documento_favorecido doc, SUM(valor) s, COUNT(*) n, "
        "COUNT(DISTINCT ano*100+mes) meses FROM pagamentos "
        "GROUP BY nome_favorecido, documento_favorecido ORDER BY s DESC LIMIT ?",
        TOP_FAVORECIDOS)

    n_fav = _q(conn, "SELECT COUNT(DISTINCT nome_favorecido) n FROM pagamentos")[0]["n"]

    return {
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "periodo": {"de": per(minmax["a"]) if minmax["a"] else None,
                    "ate": per(minmax["b"]) if minmax["b"] else None},
        "totais": {
            "geral": round(total["s"], 2),
            "pagamentos": total["n"],
            "favorecidos": n_fav,
            "por_ano": {str(r["ano"]): round(r["s"], 2) for r in anos},
        },
        "series_mensais": [{"ano": r["ano"], "mes": r["mes"], "valor": round(r["s"], 2)} for r in series],
        "por_funcao": [{"funcao": r["k"], "valor": round(r["s"], 2), "qtd": r["n"]} for r in por_funcao],
        "por_elemento": [{"elemento": r["k"], "valor": round(r["s"], 2), "qtd": r["n"]} for r in por_elemento],
        "por_fonte": [{"fonte": r["k"], "valor": round(r["s"], 2)} for r in por_fonte],
        "por_unidade": [{"unidade": r["k"], "valor": round(r["s"], 2)} for r in por_unidade],
        "top_favorecidos": [
            {"nome": r["k"], "documento": r["doc"], "valor": round(r["s"], 2),
             "qtd": r["n"], "meses": r["meses"]} for r in favorecidos
        ],
    }


# ── Alertas fiscais por regras ────────────────────────────────────────────────
def alertas(conn) -> list[dict]:
    out = []

    # 1) Favorecido recorrente de alto valor
    for r in _q(conn,
        "SELECT nome_favorecido k, documento_favorecido doc, SUM(valor) s, "
        "COUNT(DISTINCT ano*100+mes) meses FROM pagamentos "
        "GROUP BY nome_favorecido, documento_favorecido "
        "HAVING s >= ? AND meses >= ? ORDER BY s DESC LIMIT ?",
        ALERTA_FAV_VALOR, ALERTA_FAV_MESES, CAP_POR_REGRA):
        out.append({
            "tipo": "favorecido_recorrente",
            "severidade": "alta",
            "titulo": f"Favorecido recorrente de alto valor: {r['k']}",
            "detalhe": f"R$ {r['s']:,.2f} acumulados em {r['meses']} meses.",
            "valor": round(r["s"], 2),
            "filtro": {"favorecido": r["k"]},
        })

    # 2) Concentração: favorecido que domina uma função
    tot_funcao = {r["k"]: r["s"] for r in _q(conn,
        "SELECT COALESCE(NULLIF(funcao,''),'(sem função)') k, SUM(valor) s "
        "FROM pagamentos GROUP BY k")}
    n_conc = 0
    for r in _q(conn,
        "SELECT COALESCE(NULLIF(funcao,''),'(sem função)') f, nome_favorecido k, SUM(valor) s "
        "FROM pagamentos GROUP BY f, nome_favorecido HAVING s >= ? ORDER BY s DESC",
        ALERTA_CONCENTRACAO_MIN):
        base = tot_funcao.get(r["f"], 0) or 1
        pct = 100 * r["s"] / base
        if pct >= ALERTA_CONCENTRACAO_PCT and r["f"] != "(sem função)":
            if n_conc >= CAP_POR_REGRA:
                break
            n_conc += 1
            out.append({
                "tipo": "concentracao",
                "severidade": "media",
                "titulo": f"Concentração: {r['k']} concentra {pct:.0f}% da função {r['f']}",
                "detalhe": f"R$ {r['s']:,.2f} de R$ {base:,.2f} na função.",
                "valor": round(r["s"], 2),
                "filtro": {"favorecido": r["k"], "funcao": r["f"]},
            })

    # 3) Pico mensal (sobre o total geral por mês)
    serie = _q(conn, "SELECT ano, mes, SUM(valor) s FROM pagamentos GROUP BY ano, mes ORDER BY ano, mes")
    vals = [r["s"] for r in serie]
    if len(vals) >= 4:
        media = sum(vals) / len(vals)
        desvio = (sum((v - media) ** 2 for v in vals) / len(vals)) ** 0.5
        limite = media + ALERTA_PICO_K * desvio
        for r in serie:
            if r["s"] > limite:
                out.append({
                    "tipo": "pico_mensal",
                    "severidade": "media",
                    "titulo": f"Pico de gasto em {r['ano']}-{r['mes']:02d}",
                    "detalhe": f"R$ {r['s']:,.2f} (média mensal R$ {media:,.2f}).",
                    "valor": round(r["s"], 2),
                    "filtro": {"ano": r["ano"], "mes": r["mes"]},
                })

    # 4) Extra-orçamentário relevante
    for r in _q(conn,
        "SELECT nome_favorecido k, elemento_despesa e, SUM(valor) s, COUNT(*) n "
        "FROM pagamentos WHERE tipo_pagamento LIKE '%Extra%' "
        "GROUP BY nome_favorecido, elemento_despesa HAVING s >= ? ORDER BY s DESC LIMIT 20",
        ALERTA_EXTRA_VALOR):
        out.append({
            "tipo": "extra_orcamentario",
            "severidade": "baixa",
            "titulo": f"Extra-orçamentário relevante: {r['k']}",
            "detalhe": f"R$ {r['s']:,.2f} em {r['n']} pagamentos — {(r['e'] or '')[:60]}.",
            "valor": round(r["s"], 2),
            "filtro": {"favorecido": r["k"]},
        })

    # 5) Possível fracionamento de despesa (vários empenhos logo abaixo do limite de dispensa)
    n = 0
    for r in _q(conn,
        "SELECT nome_favorecido k, elemento_despesa e, ano, COUNT(*) qt, SUM(valor) s "
        "FROM empenhos WHERE valor < ? AND valor > ? "
        "GROUP BY nome_favorecido, elemento_despesa, ano "
        "HAVING qt >= ? AND s >= ? ORDER BY s DESC",
        LIMITE_DISPENSA, LIMITE_DISPENSA * 0.4, FRAC_MIN_EMPENHOS, LIMITE_DISPENSA * FRAC_FATOR_TOTAL):
        if n >= CAP_POR_REGRA:
            break
        n += 1
        out.append({
            "tipo": "fracionamento",
            "severidade": "alta",
            "titulo": f"Possível fracionamento: {r['qt']} empenhos a {r['k']}",
            "detalhe": (f"R$ {r['s']:,.2f} em {r['qt']} empenhos abaixo de R$ {LIMITE_DISPENSA:,.2f} "
                        f"({r['ano']}) — {(r['e'] or '')[:50]}."),
            "valor": round(r["s"], 2),
            "filtro": {"favorecido": r["k"], "elemento": r["e"], "tipo_doc": "pj"},
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
            "SELECT nome_favorecido k, documento_favorecido doc, SUM(valor) s, "
            "MIN(ano*100+mes) ini FROM pagamentos GROUP BY nome_favorecido, documento_favorecido "
            "HAVING ini >= ? AND s >= ? ORDER BY s DESC",
            corte, ALERTA_NOVO_VALOR):
            if EXCLUIR_ENTE.search(r["k"] or ""):
                continue
            if n >= CAP_POR_REGRA:
                break
            n += 1
            out.append({
                "tipo": "favorecido_novo",
                "severidade": "media",
                "titulo": f"Favorecido novo de alto valor: {r['k']}",
                "detalhe": (f"R$ {r['s']:,.2f} desde {r['ini'] // 100}-{r['ini'] % 100:02d} "
                            f"(1ª aparição na base)."),
                "valor": round(r["s"], 2),
                "filtro": {"favorecido": r["k"]},
            })

    # 7) Crescimento anômalo ano-a-ano (anualizando o ano corrente)
    anos = [r["ano"] for r in _q(conn, "SELECT DISTINCT ano FROM pagamentos ORDER BY ano")]
    if len(anos) >= 2:
        ant, atual = anos[-2], anos[-1]
        meses_dec = _q(conn, "SELECT MAX(mes) m FROM pagamentos WHERE ano = ?", atual)[0]["m"] or 12
        fator_anual = 12.0 / meses_dec
        n = 0
        for r in _q(conn,
            "SELECT nome_favorecido k, "
            "SUM(CASE WHEN ano=? THEN valor ELSE 0 END) v_ant, "
            "SUM(CASE WHEN ano=? THEN valor ELSE 0 END) v_atual "
            "FROM pagamentos GROUP BY nome_favorecido "
            "HAVING v_ant > 0 AND v_atual >= ? ORDER BY v_atual DESC",
            ant, atual, ALERTA_YOY_VALOR):
            if EXCLUIR_ENTE.search(r["k"] or ""):
                continue
            proj = r["v_atual"] * fator_anual
            if proj < ALERTA_YOY_FATOR * r["v_ant"]:
                continue
            if n >= CAP_POR_REGRA:
                break
            n += 1
            out.append({
                "tipo": "crescimento_yoy",
                "severidade": "media",
                "titulo": f"Crescimento anômalo: {r['k']}",
                "detalhe": (f"R$ {r['v_atual']:,.2f} em {atual} (proj. anual R$ {proj:,.2f}) "
                            f"vs R$ {r['v_ant']:,.2f} em {ant} — {proj / r['v_ant']:.1f}×."),
                "valor": round(r["v_atual"], 2),
                "filtro": {"favorecido": r["k"]},
            })

    # 8) Pessoa física (CPF) recebendo em elemento sensível
    cond_elem = " OR ".join(f"elemento_despesa LIKE '{p}'" for p in ELEM_SENSIVEIS)
    n = 0
    for r in _q(conn,
        "SELECT nome_favorecido k, elemento_despesa e, SUM(valor) s, COUNT(*) qt "
        f"FROM pagamentos WHERE ({SQL_EH_CPF}) AND ({cond_elem}) "
        "GROUP BY nome_favorecido, elemento_despesa HAVING s >= ? ORDER BY s DESC",
        ALERTA_PF_VALOR):
        if n >= CAP_POR_REGRA:
            break
        n += 1
        elem_curto = (r["e"] or "").split(" - ", 1)[-1][:40]
        out.append({
            "tipo": "pf_sensivel",
            "severidade": "alta",
            "titulo": f"Pessoa física em {elem_curto}: {r['k']}",
            "detalhe": f"R$ {r['s']:,.2f} em {r['qt']} pagamentos a pessoa física — {(r['e'] or '')[:50]}.",
            "valor": round(r["s"], 2),
            "filtro": {"favorecido": r["k"], "elemento": r["e"], "tipo_doc": "pf"},
        })

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    out.sort(key=lambda a: (ordem.get(a["severidade"], 9), -a["valor"]))
    return out[:MAX_ALERTAS]


# ── Execução por empenho (empenhado / liquidado / pago) ───────────────────────
# Detalhe que o painel carrega sob demanda. Unidade da linha = o EMPENHO; junta os
# três estágios (empenhos+liquidacoes+pagamentos) por (unidade_gestora, empenho).
# Inclui também o que não casa com empenho da base, para não esconder nada:
#   - "Restos a pagar": pagamento cujo empenho é de exercício anterior (fora da base)
#   - "Extra-orçamentário": pagamento sem empenho (retenções/tributos)
CAMPOS_DETALHE = [
    "data", "unidade_gestora", "tipo", "nome_favorecido", "documento_favorecido",
    "funcao", "subfuncao", "programa", "elemento_despesa", "fonte_recurso",
    "grupo_despesa", "empenho", "empenhado", "liquidado", "pago",
]
COLS_NUM = {"empenhado", "liquidado", "pago"}


def montar_execucao(conn) -> list[dict]:
    """Devolve uma linha por empenho (+ restos/extra-orçamentário), com _periodo (AAAAMM)."""
    rows = []
    # 1) Empenhos da base, com liquidado e pago somados por empenho.
    for r in _q(conn, """
        SELECT e.unidade_gestora, e.empenho, e.periodo, e.data, e.favorecido, e.doc,
               e.funcao, e.subfuncao, e.programa, e.elemento, e.fonte, e.grupo,
               e.empenhado,
               COALESCE(l.liquidado, 0) liquidado, COALESCE(p.pago, 0) pago
        FROM (
            SELECT unidade_gestora, empenho, MIN(ano*100+mes) periodo, MIN(data) data,
                   MAX(nome_favorecido) favorecido, MAX(documento_favorecido) doc,
                   MAX(funcao) funcao, MAX(subfuncao) subfuncao, MAX(programa) programa,
                   MAX(elemento_despesa) elemento, MAX(fonte_recurso) fonte,
                   MAX(grupo_despesa) grupo, ROUND(SUM(valor), 2) empenhado
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
                     "unidade_gestora": r["unidade_gestora"], "tipo": "Empenho",
                     "nome_favorecido": r["favorecido"], "documento_favorecido": r["doc"],
                     "funcao": r["funcao"], "subfuncao": r["subfuncao"], "programa": r["programa"],
                     "elemento_despesa": r["elemento"], "fonte_recurso": r["fonte"],
                     "grupo_despesa": r["grupo"], "empenho": r["empenho"],
                     "empenhado": r["empenhado"], "liquidado": r["liquidado"], "pago": r["pago"]})

    # 2) Pagamentos que NÃO casam com empenho da base (restos a pagar / extra-orçamentário).
    for r in _q(conn, """
        SELECT pg.unidade_gestora, pg.empenho, (pg.ano*100+pg.mes) periodo, pg.data,
               pg.nome_favorecido, pg.documento_favorecido, pg.funcao, pg.subfuncao,
               pg.programa, pg.elemento_despesa, pg.fonte_recurso, pg.grupo_despesa,
               ROUND(SUM(pg.valor),2) pago,
               (pg.empenho IS NULL OR pg.empenho = '') sem_emp
        FROM pagamentos pg
        LEFT JOIN (SELECT DISTINCT unidade_gestora, empenho FROM empenhos) e
          ON e.unidade_gestora = pg.unidade_gestora AND e.empenho = pg.empenho
        WHERE e.empenho IS NULL
        GROUP BY pg.unidade_gestora, pg.empenho, pg.ano, pg.mes, pg.data,
                 pg.nome_favorecido, pg.elemento_despesa
    """):
        sem_emp = r["sem_emp"]
        rows.append({"_periodo": r["periodo"], "data": r["data"],
                     "unidade_gestora": r["unidade_gestora"],
                     "tipo": "Extra-orçamentário" if sem_emp else "Restos a pagar",
                     "nome_favorecido": r["nome_favorecido"], "documento_favorecido": r["documento_favorecido"],
                     "funcao": r["funcao"], "subfuncao": r["subfuncao"], "programa": r["programa"],
                     "elemento_despesa": r["elemento_despesa"], "fonte_recurso": r["fonte_recurso"],
                     "grupo_despesa": r["grupo_despesa"], "empenho": r["empenho"] or "",
                     "empenhado": None, "liquidado": None, "pago": r["pago"]})

    rows.sort(key=lambda x: (x["_periodo"], x["data"] or "", -(x["pago"] or 0)))
    return rows


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
    """Grava despesas/dados/AAAA-MM.json (um por mês de competência) e devolve o manifesto."""
    os.makedirs(DADOS_DIR, exist_ok=True)
    por_mes: dict[int, list] = {}
    for r in rows:
        por_mes.setdefault(r["_periodo"], []).append([r.get(c) for c in CAMPOS_DETALHE])

    validos = {f"{p // 100}-{p % 100:02d}.json" for p in por_mes}
    for nome in os.listdir(DADOS_DIR):
        if nome.endswith(".json") and nome not in validos:
            os.remove(os.path.join(DADOS_DIR, nome))

    manifesto = []
    for periodo in sorted(por_mes):
        ano, mes = periodo // 100, periodo % 100
        linhas = por_mes[periodo]
        arquivo = f"{ano}-{mes:02d}.json"
        with open(os.path.join(DADOS_DIR, arquivo), "w", encoding="utf-8") as f:
            json.dump({"campos": CAMPOS_DETALHE, "linhas": linhas},
                      f, ensure_ascii=False, separators=(",", ":"))
        soma_pago = round(sum((l[-1] or 0) for l in linhas), 2)
        manifesto.append({"ano": ano, "mes": mes, "n": len(linhas),
                          "valor": soma_pago, "arquivo": f"despesas/dados/{arquivo}"})
    return manifesto


def main():
    if not os.path.exists(DB_PATH):
        print(f"Banco não encontrado: {DB_PATH}. Rode o crawler primeiro.", file=sys.stderr)
        sys.exit(1)
    conn = conectar()
    indice = agregados(conn)
    indice["alertas"] = alertas(conn)
    execucao = montar_execucao(conn)
    indice["meses"] = exportar_detalhe_mensal(execucao)
    indice["campos_detalhe"] = CAMPOS_DETALHE
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, separators=(",", ":"))

    exportar_csv(execucao)
    try:
        exportar_xlsx(execucao)
        xlsx_msg = os.path.basename(XLSX_PATH)
    except ImportError:
        xlsx_msg = "(openpyxl ausente — XLSX pulado)"
    conn.close()

    print(f"Export concluído: {indice['totais']['pagamentos']} pagamentos (visão caixa), "
          f"{len(execucao)} linhas de execução por empenho, "
          f"R$ {indice['totais']['geral']:,.2f}, {len(indice['alertas'])} alertas, "
          f"{len(indice['meses'])} meses → "
          f"{os.path.basename(JSON_PATH)}, dados/, {os.path.basename(CSV_PATH)}, {xlsx_msg}.", file=sys.stderr)


if __name__ == "__main__":
    main()
