#!/usr/bin/env python3
"""
Monitor do Diário Oficial de Santos — captura automática de atos
================================================================

Automatiza a varredura diária que os assessores fazem à mão: baixa o PDF do DOM,
extrai e **classifica deterministicamente** (sem IA) os atos das categorias-alvo —
Contratos e aditivos, Licitações e dispensas (inclui homologações publicadas como
"COMUNICADO"), Convênios e fomento (inclui Terceiro Setor: termos de compromisso),
Leis e decretos, Orçamento (créditos adicionais) e Fiscal/Tributário (baixa
retroativa de inscrição/renúncia de receita) — e **anexa os atos novos numa planilha
do Google Sheets** (aba única "Atos do DOM", coluna Categoria para filtrar).
Pessoal (nomeações/exonerações) fica fora desta fase.

Pipeline:  extrator.py  →  classificador.py  →  dedup SQLite  →  sheets.py

Dedup/idempotência (padrão do `despesas/crawler.py`):
  - `controle_carga(data_edicao PK)` registra as edições já processadas.
  - `atos(hash UNIQUE)` — MD5 de (data|categoria|tipo|numero|favorecido); `INSERT
    OR IGNORE` garante que reprocessar uma edição não duplica linhas na planilha.

O `.sqlite` NÃO é versionado — persiste entre execuções do GitHub Actions via cache.

Variáveis de ambiente (secrets):
    GOOGLE_OAUTH_TOKEN   token OAuth (mesmo do respostas-executivo; escopo Sheets)
    DOM_SHEET_ID         ID da planilha de destino (dedicada ao DOM)

Uso:
    python diario-oficial/monitor.py --dry-run            # última edição, imprime, não grava
    python diario-oficial/monitor.py --data 2026-06-12    # uma edição específica
    python diario-oficial/monitor.py --desde 2026-06-01   # intervalo (carga retroativa)
    python diario-oficial/monitor.py                      # edições novas desde o último run
    python diario-oficial/monitor.py --data 2026-06-12 --forcar   # reprocessa edição já vista
"""

import argparse
import hashlib
import os
import smtplib
import sqlite3
import sys
from html import escape as _esc
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import extrator
import classificador
import risco as risco_mod
import sheets as gsheets

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(AQUI, "diario.sqlite")

# Mapeia cada campo do ato (classificador) para a coluna da planilha (sheets.COLUNAS).
# "Data DO" e "Edição" entram no monitor; o resto vem do ato.
SCHEMA = """
CREATE TABLE IF NOT EXISTS controle_carga (
    data_edicao  TEXT PRIMARY KEY,
    n_atos       INTEGER,
    processado_em TEXT
);
CREATE TABLE IF NOT EXISTS atos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hash        TEXT UNIQUE,
    data_edicao TEXT,
    categoria   TEXT,
    tipo        TEXT,
    numero      TEXT,
    secretaria  TEXT,
    favorecido  TEXT,
    valor_num   REAL
);
CREATE INDEX IF NOT EXISTS ix_atos_data ON atos(data_edicao);
CREATE INDEX IF NOT EXISTS ix_atos_fav ON atos(favorecido);
"""


def abrir_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def _hash(data_edicao: str, ato: dict) -> str:
    chave = "|".join([
        data_edicao, ato["categoria"], ato["tipo"],
        ato.get("numero", ""), ato.get("favorecido", "")[:60],
        ato.get("objeto", "")[:40],
    ])
    return hashlib.md5(chave.encode("utf-8")).hexdigest()


def edicoes_processadas(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT data_edicao FROM controle_carga")}


def datas_intervalo(desde: str, ate: str) -> list[str]:
    d0 = datetime.strptime(desde, "%Y-%m-%d").date()
    d1 = datetime.strptime(ate, "%Y-%m-%d").date()
    out = []
    d = d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def linha_planilha(data_edicao: str, ato: dict, sep: str) -> list:
    """Monta a linha na ordem de gsheets.COLUNAS (formato da skill dom-santos).
    'Data DO' é o hyperlink que exibe a data e linka o PDF da edição."""
    data_cell = gsheets.hyperlink(extrator.url_edicao(data_edicao), data_edicao, sep)
    return [
        ato.get("numero", ""), data_cell, ato.get("categoria", ""),
        ato.get("tipo", ""), ato.get("secretaria", ""), ato.get("objeto", ""),
        ato.get("valor", ""), ato.get("favorecido", ""), "",
        ato.get("risco", ""), ato.get("motivo", ""), "",
        "Novo", ato.get("pagina", ""),
    ]


def processar_edicao(data_edicao: str) -> tuple[list[dict], list[dict]]:
    """Baixa, extrai e classifica uma edição. Devolve (atos, cabeçalhos_não_reconhecidos).
    ([], []) se a edição não existir."""
    pdf = extrator.baixar_pdf(data_edicao)
    if not pdf:
        print(f"  {data_edicao}: edição não encontrada.", file=sys.stderr)
        return [], []
    paginas = extrator.extrair_edicao(pdf)
    ano = int(data_edicao[:4]) if data_edicao[:4].isdigit() else None
    atos = classificador.classificar(paginas, ano_edicao=ano)
    radar = classificador.cabecalhos_nao_reconhecidos(paginas)
    return atos, radar


# ── E-mail aos assessores ──────────────────────────────────────────────────────
_COR_RISCO = {"🔴": "#C0392B", "🟡": "#B7950B", "🟢": "#1E8449"}


def _linha_email(a: dict, sheet_id: str) -> str:
    cor = _COR_RISCO.get(a.get("risco", ""), "#555")
    url = extrator.url_edicao(a.get("data_edicao", ""))
    val = _esc(a.get("valor", ""))
    # campos raspados do DOM entram escapados (um '<'/'&' solto quebraria o HTML)
    return (
        "<tr>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee;font-size:18px'>{a.get('risco','')}</td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee'>{_esc(a.get('categoria',''))}<br>"
        f"<span style='color:#888;font-size:12px'>{_esc(a.get('tipo',''))}</span></td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee'>{_esc(a.get('secretaria',''))}</td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee'>{_esc((a.get('objeto','') or '')[:160])}"
        f"<br><span style='color:#888;font-size:12px'>nº {_esc(a.get('numero',''))} · "
        f"<a href='{url}'>edição {_esc(a.get('data_edicao',''))}</a></span></td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee;white-space:nowrap'>{val}</td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee;color:{cor}'>{_esc(a.get('motivo',''))}</td>"
        "</tr>"
    )


def _bloco_radar_html(radar: list[dict]) -> str:
    """Seção discreta com os cabeçalhos não-reconhecidos (melhoria contínua)."""
    if not radar:
        return ""
    itens = "".join(
        f"<li style='margin:2px 0'>p.{c.get('pagina','')} "
        f"<span style='color:#888'>({_esc(c.get('data_edicao',''))})</span> — {_esc(c.get('linha',''))}</li>"
        for c in radar[:15]
    )
    return (
        "<div style='margin-top:22px;padding:12px 14px;background:#F7F4EC;"
        "border-left:3px solid #C9A84C;border-radius:4px'>"
        "<p style='margin:0 0 6px;font-weight:600;color:#07111F'>Cabeçalhos não classificados "
        f"— ajude a melhorar o monitor ({len(radar)})</p>"
        "<p style='margin:0 0 8px;color:#666;font-size:12px'>Linhas que parecem cabeçalho de ato "
        "e não foram capturadas. Se alguma for um ato relevante, avise para virar regra.</p>"
        f"<ul style='margin:0;padding-left:18px;font-size:13px;color:#333'>{itens}</ul></div>"
    )


def montar_email_html(novos: list[dict], sheet_id: str, radar: list[dict] | None = None) -> str:
    n_r = sum(1 for a in novos if a.get("risco") == "🔴")
    n_a = sum(1 for a in novos if a.get("risco") == "🟡")
    # ordena por gravidade (🔴 > 🟡 > 🟢)
    ordem = {"🔴": 0, "🟡": 1, "🟢": 2}
    dest = sorted(novos, key=lambda a: ordem.get(a.get("risco", "🟢"), 3))
    # no corpo, prioriza os acionáveis; verdes resumidos no rodapé
    acionaveis = [a for a in dest if a.get("risco") in ("🔴", "🟡")]
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    linhas = "".join(_linha_email(a, sheet_id) for a in acionaveis)
    bloco_acionaveis = (
        "<table style='border-collapse:collapse;width:100%;font-size:14px'>"
        "<thead><tr style='background:#07111F;color:#fff'>"
        "<th style='padding:8px'>Risco</th><th style='padding:8px;text-align:left'>Categoria</th>"
        "<th style='padding:8px;text-align:left'>Secretaria</th><th style='padding:8px;text-align:left'>Objeto</th>"
        "<th style='padding:8px;text-align:left'>Valor</th><th style='padding:8px;text-align:left'>Motivo</th>"
        "</tr></thead><tbody>" + linhas + "</tbody></table>"
        if acionaveis else
        "<p style='color:#1E8449'>Nenhum ato de risco (🔴/🟡) nesta atualização — apenas itens regulares (🟢).</p>"
    )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0A1628">
<div style="max-width:900px;margin:0 auto">
  <div style="border-top:3px solid #C9A84C;padding:16px 0">
    <h2 style="margin:0;color:#07111F">Diário Oficial de Santos — atos novos</h2>
    <p style="color:#555;margin:6px 0 0">
      {len(novos)} ato(s) capturado(s) · <b style="color:#C0392B">{n_r} 🔴</b> ·
      <b style="color:#B7950B">{n_a} 🟡</b> · {len(novos)-n_r-n_a} 🟢
    </p>
  </div>
  {bloco_acionaveis}
  {_bloco_radar_html(radar or [])}
  <p style="margin-top:18px">
    <a href="{sheet_url}" style="background:#0A1628;color:#fff;padding:10px 16px;
       text-decoration:none;border-radius:4px">Abrir a planilha completa</a>
  </p>
  <p style="color:#888;font-size:12px;margin-top:16px">
    Gerado automaticamente pelo Monitor do Diário Oficial — Gabinete Ver. Rui de Rosis Jr.
    Triagem de risco determinística; conferir o ato antes de qualquer providência.
  </p>
</div></body></html>"""


def enviar_email(novos: list[dict], sheet_id: str, radar: list[dict] | None = None) -> None:
    user = os.environ.get("GMAIL_USER")
    senha = os.environ.get("GMAIL_APP_PASSWORD")
    # destinatários: lista própria do DOM → assessores (despesas) → respostas → geral
    para = (os.environ.get("DOM_BRIEFING_TO") or os.environ.get("DESPESAS_BRIEFING_TO")
            or os.environ.get("RESPOSTAS_EMAIL_TO") or os.environ.get("GMAIL_TO"))
    if not all([user, senha, para]):
        print("Aviso: GMAIL_USER/GMAIL_APP_PASSWORD/destinatário não definidos; "
              "e-mail não enviado.", file=sys.stderr)
        return
    destinatarios = [d.strip() for d in para.split(",") if d.strip()]
    n_r = sum(1 for a in novos if a.get("risco") == "🔴")
    msg = MIMEMultipart("alternative")
    selo = f"{n_r} 🔴 · " if n_r else ""
    msg["Subject"] = f"DOM Santos — {selo}{len(novos)} ato(s) novo(s)"
    msg["From"] = f"Monitor do Diário Oficial <{user}>"
    msg["To"] = ", ".join(destinatarios)
    resumo = "\n".join(
        f"- {a.get('risco','')} {a.get('categoria','')}/{a.get('tipo','')} nº {a.get('numero','')}: "
        f"{(a.get('objeto','') or '')[:80]}" + (f" [{a['motivo']}]" if a.get("motivo") else "")
        for a in novos if a.get("risco") in ("🔴", "🟡")
    ) or "Sem atos de risco nesta atualização."
    msg.attach(MIMEText(resumo, "plain", "utf-8"))
    msg.attach(MIMEText(montar_email_html(novos, sheet_id, radar), "html", "utf-8"))
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(user, senha)
        server.sendmail(user, destinatarios, msg.as_string())
    print(f"E-mail enviado para {', '.join(destinatarios)}.", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description="Monitor do Diário Oficial de Santos")
    p.add_argument("--data", help="Edição específica (AAAA-MM-DD).")
    p.add_argument("--desde", help="Início de um intervalo (AAAA-MM-DD); até hoje ou --ate.")
    p.add_argument("--ate", help="Fim do intervalo (AAAA-MM-DD). Padrão: hoje.")
    p.add_argument("--dias", type=int, default=7,
                   help="Sem --data/--desde: varre os últimos N dias (padrão 7).")
    p.add_argument("--forcar", action="store_true", help="Reprocessa edição já registrada.")
    p.add_argument("--dry-run", action="store_true",
                   help="Não grava no SQLite nem no Sheets; imprime os atos.")
    p.add_argument("--email", action="store_true",
                   help="Envia e-mail aos assessores com os atos novos (se houver).")
    p.add_argument("--limite", type=int, default=0, help="Máx. de atos a imprimir no dry-run.")
    args = p.parse_args()

    hoje = datetime.now().date()
    if args.data:
        datas = [args.data]
    elif args.desde:
        datas = datas_intervalo(args.desde, args.ate or hoje.isoformat())
    else:
        datas = datas_intervalo((hoje - timedelta(days=args.dias - 1)).isoformat(),
                                hoje.isoformat())

    conn = None if args.dry_run else abrir_db()
    ja = edicoes_processadas(conn) if conn else set()

    sheets = sheet_id = sep = None
    if not args.dry_run:
        sheet_id = os.environ.get("DOM_SHEET_ID", "")
        if not sheet_id:
            raise EnvironmentError("Defina DOM_SHEET_ID (planilha de destino).")
        sheets = gsheets.conectar_sheets()
        gsheets.garantir_aba(sheets, sheet_id)
        sep = gsheets.separador_formula(sheets, sheet_id)

    total_novos = 0
    novos_atos: list[dict] = []  # atos novos do run inteiro (para o e-mail)
    radar_run: list[dict] = []   # cabeçalhos não-reconhecidos do run (para o e-mail)
    for data_edicao in datas:
        if conn and data_edicao in ja and not args.forcar:
            continue
        atos, radar = processar_edicao(data_edicao)
        if not atos and not radar:
            continue
        for c in radar:
            c["data_edicao"] = data_edicao
        radar_run.extend(radar)

        # avalia risco (usa conn p/ gatilhos cross-edição; no dry-run vai sem histórico)
        for a, r in zip(atos, risco_mod.avaliar(atos, conn)):
            a["risco"], a["motivo"] = r["risco"], r["motivo"]

        if args.dry_run:
            print(f"== {data_edicao}: {len(atos)} atos ==", file=sys.stderr)
            import collections
            for k, v in collections.Counter(a["risco"] for a in atos).items():
                print(f"   {v}  {k}", file=sys.stderr)
            for a in atos[:(args.limite or 8)]:
                print(f"   {a['risco']} [{a['tipo']}] nº {a['numero']} | "
                      f"{a['secretaria'][:20]} | {a['objeto'][:40]} | {a['motivo'][:60]}")
            if radar:
                print(f"   -- {len(radar)} cabeçalho(s) não-reconhecido(s) (radar) --")
                for c in radar[:15]:
                    print(f"      p{c['pagina']}: {c['linha']}")
            continue

        # dedup via SQLite → linhas novas para a aba única
        linhas_novas: list[list] = []
        for a in atos:
            h = _hash(data_edicao, a)
            cur = conn.execute(
                "INSERT OR IGNORE INTO atos (hash, data_edicao, categoria, tipo, numero, secretaria, favorecido, valor_num) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (h, data_edicao, a["categoria"], a["tipo"], a.get("numero", ""),
                 a.get("secretaria", ""), a.get("favorecido", ""), a.get("valor_num")),
            )
            if cur.rowcount:  # inserido = ato novo
                linhas_novas.append(linha_planilha(data_edicao, a, sep))
                a["data_edicao"] = data_edicao
                novos_atos.append(a)
        gsheets.anexar_linhas(sheets, sheet_id, linhas_novas)
        novos = len(linhas_novas)
        conn.execute(
            "INSERT OR REPLACE INTO controle_carga (data_edicao, n_atos, processado_em) VALUES (?,?,?)",
            (data_edicao, len(atos), datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        total_novos += novos
        print(f"== {data_edicao}: {len(atos)} atos ({novos} novos na planilha) ==", file=sys.stderr)

    if conn:
        conn.close()
    print(f"Concluído: {total_novos} atos novos.", file=sys.stderr)

    if args.email and not args.dry_run:
        if novos_atos:
            enviar_email(novos_atos, sheet_id, radar_run)
        else:
            print("Sem atos novos — e-mail não enviado.", file=sys.stderr)


if __name__ == "__main__":
    main()
