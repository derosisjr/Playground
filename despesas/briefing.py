#!/usr/bin/env python3
"""
Briefing Semanal de Despesas — Prefeitura de Santos (e-mail para os assessores)
===============================================================================

Lê `despesas/despesas.sqlite` e envia um e-mail HTML com o panorama da semana:
quanto foi pago, para quem, em quê, o que variou e quais alertas fiscais estão
vigentes — com links para o painel. É só informativo (sem IA, sem custo de
tokens): tudo é calculado de forma determinística a partir da base.

Janela ("semana") = os 7 dias que terminam na data de pagamento MAIS RECENTE da
base (robusto à defasagem do portal); compara com os 7 dias anteriores.

Reusa `conectar`/`alertas` de `export.py` e o padrão SMTP de `ordem-do-dia`.

Alertas no briefing (2026-09): os favorecidos são consolidados por identidade
(CNPJ), e a seleção dos 12 alertas prioriza NOVIDADE (alertas novos segundo
despesas/alertas-estado.json) e DIVERSIDADE (no máximo 2 por regra e 1 por
favorecido; inconsistências de dados e anomalias antes de contexto), em vez de
repetir os maiores recebedores. Sem histórico, o e-mail diz isso em vez de
chamar todo alerta de novo. Meses ainda incompletos na origem são declarados.

Secrets/ambiente:
    GMAIL_USER            conta Gmail remetente
    GMAIL_APP_PASSWORD    App Password de 16 dígitos
    DESPESAS_BRIEFING_TO  destinatários (vírgula). Se ausente, usa RESPOSTAS_EMAIL_TO
                          (mesma lista do requerimentos) e, por fim, GMAIL_TO.

Uso:
    python despesas/briefing.py --dry-run                       # imprime, não envia
    python despesas/briefing.py --salvar despesas/_briefing.html  # preview HTML
    python despesas/briefing.py                                 # envia por e-mail
    python despesas/briefing.py --semana 7                      # tamanho da janela (dias)
    python despesas/briefing.py --db X.sqlite --dry-run         # outra base (candidato)
"""

import argparse
import os
import smtplib
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz do repo: comum/
from comum.saida import configurar_stdio  # noqa: E402
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import export  # mesmo diretório: reusa conectar(), alertas(), _q()
from formato import brl, compacto, pct, eh_ente_publico  # formatação/classificação únicas

configurar_stdio()

PAINEL_URL = "https://derosisjr.github.io/Playground/despesas.html"
NAVY, GOLD, MUTED, LINE = "#07111f", "#c9a84c", "#667085", "#e4e7ec"
RED, AMBER, SLATE = "#b42318", "#b54708", "#475467"
TOP = 10
MAX_ALERTAS_BRIEFING = 12
MAX_POR_REGRA = 2          # diversidade: no máximo N alertas da mesma regra


# ── Formatação ────────────────────────────────────────────────────────────────
def data_br(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso or ""


# Repasses/retenções a entes públicos têm natureza distinta de pagamento a
# fornecedor. Nada é filtrado; só separado em tabelas próprias. A heurística
# (por nome do favorecido) é a única de formato.eh_ente_publico.

# ── Coleta dos dados da semana ────────────────────────────────────────────────
def coletar(conn, dias: int, defasagem: int) -> dict:
    q = lambda sql, *p: export._q(conn, sql, *p)

    maxd = q("SELECT MAX(data) m FROM pagamentos WHERE data <> ''")[0]["m"]
    if not maxd:
        return {"vazio": True}
    # Recua a janela `defasagem` dias para fugir da borda incompleta: o portal
    # publica pagamentos com ~1 semana de atraso, então os dias mais recentes
    # ainda estão se preenchendo. Reportamos a última semana já "assentada".
    fim_d = datetime.strptime(maxd[:10], "%Y-%m-%d").date() - timedelta(days=defasagem)
    ini_d = fim_d - timedelta(days=dias - 1)
    ini_ant = ini_d - timedelta(days=dias)
    fim_ant = ini_d - timedelta(days=1)
    ini, fim = ini_d.isoformat(), fim_d.isoformat()
    ini_a, fim_a = ini_ant.isoformat(), fim_ant.isoformat()

    def soma_pago(d1, d2):
        return q("SELECT COALESCE(SUM(valor),0) s FROM pagamentos WHERE data BETWEEN ? AND ?",
                 d1, d2)[0]["s"]

    semana = soma_pago(ini, fim)
    semana_ant = soma_pago(ini_a, fim_a)

    # acumulado do mês e do ano (até a data fim), com comparação ao ano anterior
    ano, mes = fim_d.year, fim_d.month
    mes_ini = date(ano, mes, 1).isoformat()
    ano_ini = date(ano, 1, 1).isoformat()
    mes_atual = soma_pago(mes_ini, fim)
    ano_atual = soma_pago(ano_ini, fim)
    # média semanal do ano (baseline estável, já que pagamentos são irregulares)
    semanas_decorridas = max(1, ((fim_d - date(ano, 1, 1)).days + 1) / 7)
    media_semanal = ano_atual / semanas_decorridas
    # mesmo período do ano anterior
    try:
        fim_ly = fim_d.replace(year=ano - 1).isoformat()
    except ValueError:  # 29/02
        fim_ly = date(ano - 1, fim_d.month, 28).isoformat()
    mes_ly = soma_pago(date(ano - 1, mes, 1).isoformat(), fim_ly)
    ano_ly = soma_pago(date(ano - 1, 1, 1).isoformat(), fim_ly)

    ident = export.preparar_identidades(conn)
    nome = lambda chave: export._fav_campos(ident, chave)["nome"]  # noqa: E731
    todos_fav = [{"k": nome(r["k"]), "chave": r["k"], "s": r["s"], "n": r["n"]} for r in q(
        f"SELECT fi.chave k, ROUND(SUM(p.valor),2) s, COUNT(*) n FROM pagamentos p "
        f"{export.FAV_JOIN.format(t='p')} WHERE p.data BETWEEN ? AND ? GROUP BY fi.chave ORDER BY s DESC",
        ini, fim)]
    fav_publico = [r for r in todos_fav if eh_ente_publico(r["k"])]
    fav_demais = [r for r in todos_fav if not eh_ente_publico(r["k"])]
    total_publico = round(sum(r["s"] for r in fav_publico), 2)
    total_demais = round(sum(r["s"] for r in fav_demais), 2)
    pagamentos = q(
        "SELECT data, nome_favorecido k, elemento_despesa e, ROUND(valor,2) v FROM pagamentos "
        "WHERE data BETWEEN ? AND ? ORDER BY valor DESC LIMIT ?", ini, fim, TOP)
    funcoes = q(
        "SELECT COALESCE(NULLIF(funcao,''),'(sem função)') k, ROUND(SUM(valor),2) s FROM pagamentos "
        "WHERE data BETWEEN ? AND ? GROUP BY k ORDER BY s DESC LIMIT ?", ini, fim, TOP)
    empenhos = q(
        "SELECT data, nome_favorecido k, elemento_despesa e, ROUND(SUM(valor),2) s FROM empenhos "
        "WHERE data BETWEEN ? AND ? GROUP BY unidade_gestora, empenho "
        "ORDER BY s DESC LIMIT ?", ini, fim, TOP)

    return {
        "vazio": False,
        "ini": ini, "fim": fim, "dias": dias,
        "semana": semana, "semana_ant": semana_ant, "media_semanal": media_semanal,
        "mes_atual": mes_atual, "mes_ly": mes_ly, "mes_nome": fim_d.strftime("%m/%Y"),
        "ano_atual": ano_atual, "ano_ly": ano_ly, "ano": ano,
        "fav_publico": fav_publico[:TOP], "fav_demais": fav_demais[:TOP],
        "total_publico": total_publico, "total_demais": total_demais,
        "pagamentos": pagamentos, "funcoes": funcoes, "empenhos": empenhos,
        "alertas": selecionar_alertas(_todos := alertas_com_historico(conn, ident)),
        "alertas_total": _todos,
        "historico": HISTORICO_INFO,
        "execucao": export.execucao_agregada(conn)["por_ano"].get(str(ano)),
        "mes_completo": export._mes_completo_ate(conn),
        "cobertura": export.cobertura(conn),
    }


HISTORICO_INFO = {"disponivel": False, "nota": ""}


def alertas_com_historico(conn, ident) -> list[dict]:
    """Alertas do export com o estado (novo/persistente) lido do arquivo de histórico,
    SEM regravá-lo (quem grava é o export, no pipeline)."""
    import json
    cob = export.cobertura(conn)
    lista = export.alertas(conn, ident, cob, export.execucao_agregada(conn, cob))
    estado = {}
    try:
        with open(export.ALERTAS_ESTADO_PATH, encoding="utf-8") as f:
            estado = json.load(f).get("alertas") or {}
    except (OSError, ValueError):
        estado = {}
    HISTORICO_INFO["disponivel"] = bool(estado)
    for a in lista:
        h = estado.get(a["id"])
        a["estado"] = "persistente" if h else ("novo" if estado else "sem_historico")
        a["primeiro_em"] = h.get("primeiro_em") if h else None
    HISTORICO_INFO["nota"] = ("" if estado else
                              "Sem histórico anterior de alertas: não é possível dizer quais são novos.")
    return lista


def selecionar_alertas(lista: list[dict], maximo: int = MAX_ALERTAS_BRIEFING) -> list[dict]:
    """Prioriza novidade e diversidade: novos antes de persistentes; inconsistências de
    dados e anomalias antes de contexto; no máximo MAX_POR_REGRA por regra e 1 por
    favorecido (identidade). Os grandes recebedores recorrentes (contexto) entram só
    se sobrar espaço."""
    ordem_classe = {"inconsistencia": 0, "anomalia": 1, "contexto": 2}
    ordem_estado = {"novo": 0, "sem_historico": 1, "persistente": 2}
    ordem_sev = {"alta": 0, "media": 1, "baixa": 2}
    cand = sorted(lista, key=lambda a: (ordem_estado.get(a.get("estado"), 9),
                                        ordem_classe.get(a.get("classe"), 9),
                                        ordem_sev.get(a.get("severidade"), 9), -(a.get("valor") or 0)))
    out, por_regra, por_fav = [], {}, set()
    for a in cand:
        chave = (a.get("filtro") or {}).get("chave")
        if por_regra.get(a["tipo"], 0) >= MAX_POR_REGRA or (chave and chave in por_fav):
            continue
        out.append(a)
        por_regra[a["tipo"]] = por_regra.get(a["tipo"], 0) + 1
        if chave:
            por_fav.add(chave)
        if len(out) >= maximo:
            break
    return out


# ── Render HTML (e-mail-safe: tabelas, CSS inline) ────────────────────────────
def esc(s) -> str:
    s = "" if s is None else str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _card(rotulo, valor, sub) -> str:
    return (f'<td style="padding:8px;border:1px solid {LINE};border-radius:10px;'
            f'background:#fff;vertical-align:top">'
            f'<div style="color:{MUTED};font-size:11px;text-transform:uppercase;'
            f'letter-spacing:.06em;font-weight:700">{esc(rotulo)}</div>'
            f'<div style="font-size:22px;font-weight:700;color:{NAVY};margin-top:3px">{esc(valor)}</div>'
            f'<div style="color:{MUTED};font-size:12px;margin-top:2px">{esc(sub)}</div></td>')


def _tabela(titulo, cabec, linhas) -> str:
    ths = "".join(
        f'<th align="{a}" style="background:{NAVY};color:#fff;padding:8px 10px;'
        f'font-size:12px;text-align:{a}">{esc(t)}</th>' for t, a in cabec)
    trs = ""
    for i, cells in enumerate(linhas):
        bg = "#ffffff" if i % 2 == 0 else "#f7f8fa"
        tds = "".join(
            f'<td align="{a}" style="padding:7px 10px;border-top:1px solid {LINE};'
            f'font-size:13px;color:{NAVY};text-align:{a}">{c}</td>' for c, a in cells)
        trs += f'<tr style="background:{bg}">{tds}</tr>'
    return (f'<h3 style="font-size:15px;color:{NAVY};margin:26px 0 8px">{esc(titulo)}</h3>'
            f'<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="border-collapse:collapse;border:1px solid {LINE};border-radius:10px;'
            f'overflow:hidden"><tr>{ths}</tr>{trs}</table>')


def montar_html(d: dict) -> str:
    if d["vazio"]:
        return "<p>Sem dados de pagamentos na base.</p>"

    periodo = f"{data_br(d['ini'])} a {data_br(d['fim'])}"
    # semana muito abaixo da média = quase sempre defasagem do portal, não queda de gasto
    aviso_semana = (" · provável defasagem do portal: semana ainda incompleta na origem"
                    if d["media_semanal"] and d["semana"] < 0.5 * d["media_semanal"] else "")
    cards = (
        _card("Pago na semana", compacto(d["semana"]),
              f"{pct(d['semana'], d['media_semanal'])} vs. média semanal do ano{aviso_semana}") +
        _card(f"Mês {d['mes_nome']}", compacto(d["mes_atual"]),
              f"{pct(d['mes_atual'], d['mes_ly'])} vs. ano anterior") +
        _card(f"Acumulado {d['ano']}", compacto(d["ano_atual"]),
              f"{pct(d['ano_atual'], d['ano_ly'])} vs. ano anterior")
    )

    # alertas: seleção por novidade e diversidade (ver selecionar_alertas)
    cor = {"alta": RED, "media": AMBER, "baixa": SLATE}
    classe_rot = {"contexto": "contexto", "anomalia": "conferir", "inconsistencia": "dados"}
    relevantes = d["alertas"]
    if relevantes:
        itens = ""
        for a in relevantes:
            c = cor.get(a["severidade"], SLATE)
            estado = a.get("estado")
            tag_estado = (f'<span style="display:inline-block;font-size:10px;font-weight:700;'
                          f'color:{NAVY};background:#fdf1cf;border-radius:6px;padding:1px 6px;'
                          f'margin-right:8px">NOVO</span>' if estado == "novo" else "")
            link = PAINEL_URL.replace("despesas.html", "") + a["link"].lstrip("./") if a.get("link") else PAINEL_URL
            itens += (
                f'<tr><td style="padding:8px 10px;border-top:1px solid {LINE}">'
                f'<span style="display:inline-block;font-size:10px;font-weight:700;'
                f'text-transform:uppercase;color:#fff;background:{c};border-radius:6px;'
                f'padding:1px 6px;margin-right:8px">{esc(a["severidade"])}</span>'
                f'<span style="display:inline-block;font-size:10px;font-weight:700;'
                f'text-transform:uppercase;color:{SLATE};border:1px solid {LINE};border-radius:6px;'
                f'padding:1px 6px;margin-right:8px">{esc(classe_rot.get(a.get("classe"), ""))}</span>'
                f'{tag_estado}'
                f'<strong style="color:{NAVY};font-size:13px">{esc(a["titulo"])}</strong>'
                f'<div style="color:{MUTED};font-size:12px;margin-top:2px">{esc(a["detalhe"])} '
                f'<a href="{esc(link)}" style="color:{NAVY}">abrir o recorte</a></div>'
                f'</td><td align="right" style="padding:8px 10px;border-top:1px solid {LINE};'
                f'font-size:13px;color:{NAVY};white-space:nowrap">{brl(a["valor"]) if a.get("valor") else ""}</td></tr>')
        hist = d.get("historico") or {}
        nota_hist = (esc(hist["nota"]) if hist.get("nota") else
                     "Alertas marcados NOVO não constavam do histórico anterior.")
        bloco_alertas = (
            f'<h3 style="font-size:15px;color:{NAVY};margin:26px 0 8px">'
            f'Alertas para conferir ({len(relevantes)} de {len(d["alertas_total"])} vigentes — '
            f'seleção por novidade e diversidade)</h3>'
            f'<p style="color:{MUTED};font-size:12px;margin:0 0 8px">{nota_hist} Classes: '
            f'<em>dados</em> = inconsistência na origem/cobertura; <em>conferir</em> = padrão que '
            f'merece requerimento; <em>contexto</em> = escala/recorrência, não achado. Nenhum alerta '
            f'é conclusão de irregularidade.</p>'
            f'<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="border-collapse:collapse;border:1px solid {LINE};border-radius:10px;'
            f'overflow:hidden">{itens}</table>')
    else:
        bloco_alertas = ""

    def _tab_fav(titulo, linhas):
        return _tabela(titulo,
                       [("Favorecido", "left"), ("Pagamentos", "right"), ("Total", "right")],
                       [[(esc(r["k"]), "left"), (str(r["n"]), "right"), (brl(r["s"]), "right")]
                        for r in linhas]) if linhas else ""

    # execução do exercício (tríade do export): taxa só quando a base do ano é íntegra
    exe = d.get("execucao")
    if exe:
        pedacos = [f"empenhado <strong>{compacto(exe['empenhado'])}</strong>",
                   f"liquidado <strong>{compacto(exe['liquidado'])}</strong>",
                   f"pago <strong>{compacto(exe['pago'])}</strong>"]
        if exe.get("taxa_pagamento") is not None:
            bt = exe.get("base_taxa") or {}
            cob = f" (sobre {bt['cobertura_pct']}% do empenhado, com original na base)" if bt.get("cobertura_pct") else ""
            pedacos.append(f"dos empenhos do ano{cob}, <strong>{exe['taxa_liquidacao']:.0f}%</strong> "
                           f"liquidado e <strong>{exe['taxa_pagamento']:.0f}%</strong> pago")
        elif exe.get("taxa_motivos"):
            pedacos.append(f"taxa de execução não validada ({esc(exe['taxa_motivos'][0])})")
        bloco_exe = (
            f'<div style="margin:16px 0 0;padding:12px 14px;background:#fff;'
            f'border:1px solid {LINE};border-radius:10px;font-size:13px;color:{NAVY}">'
            f'<strong>Execução {d["ano"]}:</strong> ' + " · ".join(pedacos) + '</div>')
    else:
        bloco_exe = ""

    # meses incompletos na origem (o portal publica com defasagem): declarados, não escondidos
    mc = d.get("mes_completo")
    cob = d.get("cobertura") or {}
    avisos = []
    if mc:
        avisos.append(f"Último mês completo na base: {mc[1]:02d}/{mc[0]}; meses posteriores ainda "
                      f"estão se preenchendo e não entram em comparações mensais.")
    if cob.get("faltantes"):
        avisos.append(f"{len(cob['faltantes'])} partição(ões) sem carga: {', '.join(cob['faltantes'][:4])}.")
    if cob.get("duplicidade_sistematica"):
        avisos.append(f"{len(cob['duplicidade_sistematica'])} partição(ões) vieram da origem em duplicidade "
                      f"sistemática (linhas idênticas contadas uma vez).")
    bloco_avisos = (f'<p style="color:{MUTED};font-size:12px;margin:12px 0 0">{esc(" ".join(avisos))}</p>'
                    if avisos else "")
    sem = d["semana"] or 1
    split = (
        f'<div style="margin:24px 0 0;padding:12px 14px;background:#fff;'
        f'border:1px solid {LINE};border-radius:10px;font-size:13px;color:{NAVY}">'
        f'<strong>Divisão da semana:</strong> '
        f'<span style="color:{SLATE}">fornecedores/terceiros</span> '
        f'<strong>{brl(d["total_demais"])}</strong> ({100*d["total_demais"]/sem:.0f}%) · '
        f'<span style="color:{SLATE}">repasses a entes públicos</span> '
        f'<strong>{brl(d["total_publico"])}</strong> ({100*d["total_publico"]/sem:.0f}%)</div>')
    t_fav = (split +
             _tab_fav("Maiores fornecedores e terceiros da semana", d["fav_demais"]) +
             _tab_fav("Maiores repasses a entes públicos (transferências/retenções)", d["fav_publico"]))
    t_pag = _tabela("Maiores pagamentos individuais",
                    [("Data", "left"), ("Favorecido", "left"), ("Elemento", "left"), ("Valor", "right")],
                    [[(data_br(r["data"]), "left"), (esc(r["k"]), "left"),
                      (esc((r["e"] or "")[:46]), "left"), (brl(r["v"]), "right")]
                     for r in d["pagamentos"]])
    t_fun = _tabela("Para onde foi o dinheiro (por função)",
                    [("Função / área", "left"), ("Pago na semana", "right")],
                    [[(esc(r["k"]), "left"), (brl(r["s"]), "right")] for r in d["funcoes"]])
    t_emp = _tabela("Maiores empenhos novos (compromissos assumidos)",
                    [("Data", "left"), ("Favorecido", "left"), ("Elemento", "left"), ("Empenhado", "right")],
                    [[(data_br(r["data"]), "left"), (esc(r["k"]), "left"),
                      (esc((r["e"] or "")[:46]), "left"), (brl(r["s"]), "right")]
                     for r in d["empenhos"]])

    gerado = datetime.now().strftime("%d/%m/%Y %H:%M")
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;background:#f4f5f7;font-family:Arial,Helvetica,sans-serif;color:{NAVY}">
<table width="100%" cellspacing="0" cellpadding="0" style="background:#f4f5f7"><tr><td align="center">
<table width="660" cellspacing="0" cellpadding="0" style="max-width:660px;width:100%">
  <tr><td style="background:{NAVY};border-top:3px solid {GOLD};padding:22px 24px">
    <div style="color:{GOLD};font-size:11px;letter-spacing:.12em;text-transform:uppercase;
      font-weight:700">Gabinete Rui de Rosis Jr. — Fiscalização do Executivo</div>
    <div style="color:#fff;font-size:22px;font-weight:800;margin-top:4px">
      Briefing Semanal de Despesas</div>
    <div style="color:#c7cfdb;font-size:13px;margin-top:6px">
      Prefeitura de Santos · período {periodo}</div>
  </td></tr>
  <tr><td style="padding:20px 24px">
    <table width="100%" cellspacing="8" cellpadding="0"><tr>{cards}</tr></table>
    {bloco_exe}
    {bloco_avisos}
    {bloco_alertas}
    {t_fun}
    {t_fav}
    {t_pag}
    {t_emp}
    <div style="margin:28px 0 6px">
      <a href="{PAINEL_URL}" style="display:inline-block;background:{NAVY};color:#fff;
        text-decoration:none;padding:11px 20px;border-radius:8px;font-size:14px;font-weight:700">
        Abrir o painel completo →</a></div>
    <p style="color:{MUTED};font-size:11px;line-height:1.5;margin-top:18px">
      Fonte: Portal da Transparência da Prefeitura de Santos. Valores de <strong>pagamentos</strong>
      (caixa); empenhos = compromissos assumidos. Caráter informativo e não oficial — confira sempre
      o portal. Janela de {d['dias']} dias da última semana já consolidada (recuada ~1 semana, pois o
      portal publica pagamentos com defasagem). Gerado em {gerado}.</p>
  </td></tr>
</table></td></tr></table></body></html>"""


def montar_texto(d: dict) -> str:
    if d["vazio"]:
        return "Sem dados de pagamentos na base."
    linhas = [
        f"Briefing Semanal de Despesas — Prefeitura de Santos",
        f"Período: {data_br(d['ini'])} a {data_br(d['fim'])}",
        "",
        f"Pago na semana: {brl(d['semana'])} ({pct(d['semana'], d['media_semanal'])} vs. média semanal)"
        + (" — provável defasagem do portal: semana ainda incompleta na origem"
           if d["media_semanal"] and d["semana"] < 0.5 * d["media_semanal"] else ""),
        f"Mês {d['mes_nome']}: {brl(d['mes_atual'])} | Acumulado {d['ano']}: {brl(d['ano_atual'])}",
        f"Fornecedores/terceiros: {brl(d['total_demais'])} | Entes públicos: {brl(d['total_publico'])}",
    ]
    exe = d.get("execucao")
    if exe:
        linha_exe = (f"Execução {d['ano']}: empenhado {brl(exe['empenhado'])} | "
                     f"liquidado {brl(exe['liquidado'])} | pago {brl(exe['pago'])}")
        if exe.get("taxa_pagamento") is not None:
            linha_exe += (f" | {exe['taxa_liquidacao']:.0f}% liq. / "
                          f"{exe['taxa_pagamento']:.0f}% pago dos empenhos do ano")
        linhas.append(linha_exe)
    hist = d.get("historico") or {}
    if d.get("alertas"):
        linhas += ["", f"Alertas para conferir ({len(d['alertas'])} de {len(d['alertas_total'])}):"]
        if hist.get("nota"):
            linhas.append(f"  ({hist['nota']})")
        for a in d["alertas"]:
            tag = "[NOVO] " if a.get("estado") == "novo" else ""
            linhas.append(f"  - {tag}[{a.get('classe', '')}/{a['severidade']}] {a['titulo']}")
    mc = d.get("mes_completo")
    if mc:
        linhas += ["", f"Último mês completo na base: {mc[1]:02d}/{mc[0]} (meses posteriores ainda incompletos)."]
    linhas += [
        "",
        "Maiores fornecedores e terceiros da semana:",
    ]
    for r in d["fav_demais"]:
        linhas.append(f"  - {r['k']}: {brl(r['s'])}")
    linhas += ["", "Maiores repasses a entes públicos:"]
    for r in d["fav_publico"]:
        linhas.append(f"  - {r['k']}: {brl(r['s'])}")
    linhas += ["", f"Painel: {PAINEL_URL}"]
    return "\n".join(linhas)


# ── Envio ─────────────────────────────────────────────────────────────────────
def enviar_email(assunto: str, html: str, texto: str) -> None:
    user = os.environ.get("GMAIL_USER")
    senha = os.environ.get("GMAIL_APP_PASSWORD")
    # destinatários: lista dedicada → mesma lista do requerimentos → fallback geral
    to = (os.environ.get("DESPESAS_BRIEFING_TO") or os.environ.get("RESPOSTAS_EMAIL_TO")
          or os.environ.get("GMAIL_TO"))
    if not all([user, senha, to]):
        raise EnvironmentError("Defina GMAIL_USER, GMAIL_APP_PASSWORD e "
                               "DESPESAS_BRIEFING_TO (ou RESPOSTAS_EMAIL_TO / GMAIL_TO).")
    destinatarios = [x.strip() for x in to.split(",") if x.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = f"Radar de Despesas — Gabinete <{user}>"
    msg["To"] = ", ".join(destinatarios)
    msg.attach(MIMEText(texto, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(user, senha)
        server.sendmail(user, destinatarios, msg.as_string())
    print(f"E-mail enviado para: {', '.join(destinatarios)}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description="Briefing Semanal de Despesas (Prefeitura de Santos)")
    p.add_argument("--semana", type=int, default=7, help="Tamanho da janela em dias (padrão 7).")
    p.add_argument("--defasagem", type=int, default=7,
                   help="Dias recuados da data mais recente p/ fugir da borda incompleta (padrão 7).")
    p.add_argument("--dry-run", action="store_true", help="Calcula e imprime; não envia.")
    p.add_argument("--salvar", metavar="PATH", help="Grava o HTML no arquivo (preview); não envia.")
    p.add_argument("--db", help="SQLite alternativo (padrão: despesas/despesas.sqlite).")
    args = p.parse_args()
    if args.db:
        export.DB_PATH = args.db

    if not os.path.exists(export.DB_PATH):
        print(f"Banco não encontrado: {export.DB_PATH}. Rode o crawler primeiro.", file=sys.stderr)
        sys.exit(1)

    conn = export.conectar()
    dados = coletar(conn, args.semana, args.defasagem)
    conn.close()

    if dados["vazio"]:
        print("Sem dados — nada a enviar.", file=sys.stderr)
        return

    html = montar_html(dados)
    texto = montar_texto(dados)
    assunto = (f"Despesas Santos · {data_br(dados['ini'])}–{data_br(dados['fim'])} · "
               f"{compacto(dados['semana'])} pagos")

    if args.salvar:
        with open(args.salvar, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"HTML salvo em {args.salvar}", file=sys.stderr)
    if args.dry_run:
        print(texto)
        print(f"\n[dry-run] Assunto: {assunto}", file=sys.stderr)
        return
    if args.salvar:
        return
    enviar_email(assunto, html, texto)


if __name__ == "__main__":
    main()
