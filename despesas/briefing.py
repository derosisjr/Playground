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

Secrets/ambiente:
    GMAIL_USER            conta Gmail remetente
    GMAIL_APP_PASSWORD    App Password de 16 dígitos
    DESPESAS_BRIEFING_TO  destinatários (vírgula); se ausente, usa GMAIL_TO

Uso:
    python despesas/briefing.py --dry-run                       # imprime, não envia
    python despesas/briefing.py --salvar despesas/_briefing.html  # preview HTML
    python despesas/briefing.py                                 # envia por e-mail
    python despesas/briefing.py --semana 7                      # tamanho da janela (dias)
"""

import argparse
import os
import smtplib
import sys
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import export  # mesmo diretório: reusa conectar(), alertas(), _q()

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PAINEL_URL = "https://derosisjr.github.io/Playground/despesas.html"
NAVY, GOLD, MUTED, LINE = "#07111f", "#c9a84c", "#667085", "#e4e7ec"
RED, AMBER, SLATE = "#b42318", "#b54708", "#475467"
TOP = 10


# ── Formatação ────────────────────────────────────────────────────────────────
def brl(v) -> str:
    return "R$ " + f"{(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def compacto(v) -> str:
    v = v or 0
    a = abs(v)
    if a >= 1e9:
        return "R$ " + f"{v/1e9:.2f}".replace(".", ",") + " bi"
    if a >= 1e6:
        return "R$ " + f"{v/1e6:.1f}".replace(".", ",") + " mi"
    if a >= 1e3:
        return "R$ " + f"{v/1e3:.0f}".replace(".", ",") + " mil"
    return brl(v)


def pct(novo, velho) -> str:
    if not velho:
        return "—"
    p = 100 * (novo - velho) / velho
    seta = "▲" if p > 0 else ("▼" if p < 0 else "•")
    return f"{seta} {abs(p):.0f}%"


def data_br(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso or ""


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

    favorecidos = q(
        "SELECT nome_favorecido k, ROUND(SUM(valor),2) s, COUNT(*) n FROM pagamentos "
        "WHERE data BETWEEN ? AND ? GROUP BY nome_favorecido ORDER BY s DESC LIMIT ?",
        ini, fim, TOP)
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
        "favorecidos": favorecidos, "pagamentos": pagamentos,
        "funcoes": funcoes, "empenhos": empenhos,
        "alertas": export.alertas(conn),
    }


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
    cards = (
        _card("Pago na semana", compacto(d["semana"]),
              f"{pct(d['semana'], d['media_semanal'])} vs. média semanal do ano") +
        _card(f"Mês {d['mes_nome']}", compacto(d["mes_atual"]),
              f"{pct(d['mes_atual'], d['mes_ly'])} vs. ano anterior") +
        _card(f"Acumulado {d['ano']}", compacto(d["ano_atual"]),
              f"{pct(d['ano_atual'], d['ano_ly'])} vs. ano anterior")
    )

    # alertas (alta/média)
    cor = {"alta": RED, "media": AMBER, "baixa": SLATE}
    relevantes = [a for a in d["alertas"] if a["severidade"] in ("alta", "media")][:12]
    if relevantes:
        itens = ""
        for a in relevantes:
            c = cor.get(a["severidade"], SLATE)
            itens += (
                f'<tr><td style="padding:8px 10px;border-top:1px solid {LINE}">'
                f'<span style="display:inline-block;font-size:10px;font-weight:700;'
                f'text-transform:uppercase;color:#fff;background:{c};border-radius:6px;'
                f'padding:1px 6px;margin-right:8px">{esc(a["severidade"])}</span>'
                f'<strong style="color:{NAVY};font-size:13px">{esc(a["titulo"])}</strong>'
                f'<div style="color:{MUTED};font-size:12px;margin-top:2px">{esc(a["detalhe"])}</div>'
                f'</td><td align="right" style="padding:8px 10px;border-top:1px solid {LINE};'
                f'font-size:13px;color:{NAVY};white-space:nowrap">{brl(a["valor"])}</td></tr>')
        bloco_alertas = (
            f'<h3 style="font-size:15px;color:{NAVY};margin:26px 0 8px">'
            f'Alertas fiscais vigentes ({len(relevantes)})</h3>'
            f'<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="border-collapse:collapse;border:1px solid {LINE};border-radius:10px;'
            f'overflow:hidden">{itens}</table>')
    else:
        bloco_alertas = ""

    t_fav = _tabela("Maiores favorecidos da semana",
                    [("Favorecido", "left"), ("Pagamentos", "right"), ("Total", "right")],
                    [[(esc(r["k"]), "left"), (str(r["n"]), "right"), (brl(r["s"]), "right")]
                     for r in d["favorecidos"]])
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
        f"Pago na semana: {brl(d['semana'])} ({pct(d['semana'], d['media_semanal'])} vs. média semanal)",
        f"Mês {d['mes_nome']}: {brl(d['mes_atual'])} | Acumulado {d['ano']}: {brl(d['ano_atual'])}",
        "",
        "Maiores favorecidos da semana:",
    ]
    for r in d["favorecidos"]:
        linhas.append(f"  - {r['k']}: {brl(r['s'])}")
    linhas += ["", f"Painel: {PAINEL_URL}"]
    return "\n".join(linhas)


# ── Envio ─────────────────────────────────────────────────────────────────────
def enviar_email(assunto: str, html: str, texto: str) -> None:
    user = os.environ.get("GMAIL_USER")
    senha = os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("DESPESAS_BRIEFING_TO") or os.environ.get("GMAIL_TO")
    if not all([user, senha, to]):
        raise EnvironmentError("Defina GMAIL_USER, GMAIL_APP_PASSWORD e DESPESAS_BRIEFING_TO (ou GMAIL_TO).")
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
    args = p.parse_args()

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
