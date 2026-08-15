#!/usr/bin/env python3
"""
E-mail do briefing — Ordem do Dia
=================================

Markdown → HTML estilizado + envio, extraído de `index.py` (2026-08) para servir
aos dois caminhos (legado via API e rotina /schedule via `enviar.py`).

Envio: SMTP Gmail (porta 587); se o ambiente não abrir TCP cru (caso da rotina
/schedule), cai automaticamente para a Gmail API via HTTPS (`gmail_api.py` na
raiz do repo; exige escopo gmail.send no GOOGLE_OAUTH_TOKEN).
"""

import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import markdown as md

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
from gmail_api import enviar_gmail_api  # noqa: E402


def markdown_para_html(texto: str) -> str:
    """Converte markdown para HTML com extensões de tabela e quebras."""
    return md.markdown(
        texto,
        extensions=["tables", "nl2br", "sane_lists"],
    )


def montar_email_html(sessao_nome: str, qtd_itens: int, corpo_md: str, agora: str) -> str:
    corpo_html = markdown_para_html(corpo_md)

    # adiciona classes de estilo aos emojis de posicionamento nas tabelas
    corpo_html = corpo_html.replace("⚠️ A favor", '<span class="badge favor">A favor</span>')
    corpo_html = corpo_html.replace("❌ Contra", '<span class="badge contra">Contra</span>')
    corpo_html = corpo_html.replace("⏸️ Abstenção", '<span class="badge abstencao">Abstenção</span>')
    corpo_html = corpo_html.replace("👁️ Acompanhar", '<span class="badge acompanhar">Acompanhar</span>')
    corpo_html = corpo_html.replace("🔴 Alta", '<span class="pri alta">Alta</span>')
    corpo_html = corpo_html.replace("🟡 Média", '<span class="pri media">Média</span>')
    corpo_html = corpo_html.replace("🟢 Baixa", '<span class="pri baixa">Baixa</span>')
    corpo_html = corpo_html.replace("💡 Emenda Sugerida", '💡 <strong style="color:#003087">Emenda Sugerida</strong>')
    corpo_html = corpo_html.replace("💡 Emenda Protocolável", '💡 <strong style="color:#003087">Emenda Protocolável</strong>')

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Briefing — {sessao_nome}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background: #0D1117;
    color: #1a1a2e;
    font-size: 15px;
    line-height: 1.75;
  }}

  .wrapper {{ max-width: 740px; margin: 0 auto; background: #fff; box-shadow: 0 8px 40px rgba(0,0,0,0.25); }}

  /* ── Faixa dourada superior ── */
  .top-stripe {{
    height: 3px;
    background: linear-gradient(90deg, #C9A84C, #E8D48B, #C9A84C);
  }}

  /* ── Corpo ── */
  .body {{ padding: 40px 44px; }}

  /* Seções h2 */
  .body h2 {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: #0A1628;
    border-bottom: 2px solid #C9A84C;
    padding-bottom: 7px;
    margin: 44px 0 20px;
  }}
  .body h2:first-child {{ margin-top: 0; }}

  /* Item da pauta h3 */
  .body h3 {{
    font-size: 16px;
    font-weight: 600;
    color: #0A1628;
    margin: 40px 0 4px;
    padding: 14px 20px;
    background: #F4F5F7;
    border-left: 4px solid #0A1628;
    border-radius: 0;
    line-height: 1.4;
  }}

  /* Sub-seção h4 */
  .body h4 {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.8px;
    text-transform: uppercase;
    color: #6B7A8D;
    margin: 22px 0 7px;
  }}

  /* Ementa blockquote */
  .body blockquote {{
    border-left: 3px solid #C9A84C;
    padding: 10px 18px;
    margin: 12px 0 18px;
    background: #FDFBF6;
    border-radius: 0;
    font-style: italic;
    color: #4a4a6a;
    font-size: 14px;
    text-align: left;
  }}

  /* Parágrafos */
  .body p {{
    margin: 10px 0;
    color: #374151;
    text-align: justify;
    hyphens: auto;
  }}
  .body ul, .body ol {{ padding-left: 22px; margin: 8px 0; }}
  .body li {{ margin: 5px 0; color: #374151; text-align: justify; }}
  .body strong {{ color: #0A1628; font-weight: 700; }}

  /* Tabelas (cola, termômetro) */
  .body table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    margin: 16px 0 24px;
    overflow: hidden;
  }}
  .body th {{
    background: #0A1628;
    color: #D4CBB8;
    font-weight: 600;
    font-size: 10px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding: 11px 14px;
    text-align: left;
  }}
  .body td {{
    padding: 10px 14px;
    border-bottom: 1px solid #ECEDF0;
    vertical-align: middle;
    text-align: left;
  }}
  .body tr:last-child td {{ border-bottom: none; }}
  .body tr:nth-child(even) td {{ background: #F8F8FA; }}

  /* Badges posicionamento */
  .badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 700;
    white-space: nowrap;
    letter-spacing: 0.3px;
  }}
  .badge.favor {{ background: #E8F5E9; color: #1B5E20; }}
  .badge.contra {{ background: #FFEBEE; color: #B71C1C; }}
  .badge.abstencao {{ background: #FFF8E1; color: #795506; }}
  .badge.acompanhar {{ background: #E3F2FD; color: #0D47A1; }}

  /* Prioridade */
  .pri {{
    display: inline-block;
    padding: 2px 9px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
  }}
  .pri.alta {{ background: #FFEBEE; color: #B71C1C; }}
  .pri.media {{ background: #FFF8E1; color: #795506; }}
  .pri.baixa {{ background: #E8F5E9; color: #1B5E20; }}

  /* Separador */
  .body hr {{
    border: none;
    border-top: 1px solid #ECEDF0;
    margin: 36px 0;
  }}

  /* ── Faixa inferior ── */
  .bottom-stripe {{
    height: 2px;
    background: linear-gradient(90deg, #0A1628, #C9A84C, #0A1628);
  }}

  /* Rodapé */
  .footer {{
    background: #F4F5F7;
    padding: 22px 44px;
    text-align: center;
    font-size: 12px;
    color: #9ca3af;
    line-height: 1.9;
  }}
  .footer a {{ color: #0A1628; text-decoration: none; font-weight: 600; }}
</style>
</head>
<body>
<div class="wrapper">

  <div class="top-stripe"></div>

  <!-- HEADER -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#07111F" style="background:#07111F;">
    <tr>
      <td style="padding:32px 40px 0; background:linear-gradient(160deg,#0D1F3C 0%,#07111F 60%);">

        <!-- Linha 1: PL badge + nome + câmara -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td valign="middle" style="width:58px;">
              <table cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td width="56" height="56" align="center" valign="middle"
                      style="width:56px;height:56px;border:2px solid #C9A84C;border-radius:8px;background:rgba(201,168,76,0.08);font-family:Arial,Helvetica,sans-serif;font-size:17px;font-weight:800;color:#C9A84C;letter-spacing:1.5px;text-align:center;vertical-align:middle;">
                    PL
                  </td>
                </tr>
              </table>
            </td>
            <td valign="middle" style="padding-left:18px;">
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:9px;font-weight:700;letter-spacing:3.5px;text-transform:uppercase;color:#C9A84C;margin-bottom:5px;">PARTIDO LIBERAL</div>
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:20px;font-weight:700;color:#FFFFFF;letter-spacing:-0.3px;line-height:1.15;">Rui de Rosis Jr.</div>
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;color:#4A5A6A;letter-spacing:0.5px;margin-top:3px;">Vereador &nbsp;·&nbsp; C&acirc;mara Municipal de Santos</div>
            </td>
            <td valign="middle" align="right" style="padding-left:20px;">
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:9px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:#2A3A4A;text-align:right;line-height:2;">C&Acirc;MARA<br>MUNICIPAL<br>DE SANTOS</div>
            </td>
          </tr>
        </table>

        <!-- Divisor dourado -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0 20px;">
          <tr>
            <td style="height:1px;background:linear-gradient(90deg,#C9A84C,rgba(201,168,76,0.15));font-size:0;line-height:0;">&nbsp;</td>
          </tr>
        </table>

        <!-- Linha 2: Título -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding-bottom:24px;">
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;font-weight:700;letter-spacing:5px;text-transform:uppercase;color:#C9A84C;margin-bottom:8px;">BRIEFING POL&Iacute;TICO</div>
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:30px;font-weight:300;color:#FFFFFF;letter-spacing:-0.5px;line-height:1.1;">Ordem do Dia</div>
            </td>
          </tr>
        </table>

      </td>
    </tr>

    <!-- Meta-cards: fundo ligeiramente mais escuro -->
    <tr>
      <td style="padding:0 40px;background:#050D18;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid rgba(201,168,76,0.2);">
          <tr>

            <!-- Card: Sessão -->
            <td valign="top" style="padding:18px 20px 18px 0;width:50%;">
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:8px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#3A4A5A;margin-bottom:6px;">SESS&Atilde;O</div>
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#C8D4E0;line-height:1.45;">{sessao_nome}</div>
            </td>

            <!-- Separador vertical -->
            <td style="width:1px;background:rgba(201,168,76,0.12);font-size:0;">&nbsp;</td>

            <!-- Card: Pauta -->
            <td valign="top" align="center" style="padding:18px 20px;width:20%;">
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:8px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#3A4A5A;margin-bottom:6px;">PAUTA</div>
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:28px;font-weight:700;color:#C9A84C;line-height:1;">{qtd_itens}</div>
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;color:#4A5A6A;margin-top:2px;">itens</div>
            </td>

            <!-- Separador vertical -->
            <td style="width:1px;background:rgba(201,168,76,0.12);font-size:0;">&nbsp;</td>

            <!-- Card: Gerado em -->
            <td valign="top" style="padding:18px 0 18px 20px;width:30%;">
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:8px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#3A4A5A;margin-bottom:6px;">GERADO EM</div>
              <div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#C8D4E0;line-height:1.45;">{agora}</div>
            </td>

          </tr>
        </table>
      </td>
    </tr>

    <!-- Faixa dourada inferior do header -->
    <tr>
      <td style="height:3px;background:linear-gradient(90deg,#C9A84C,#E8D48B,#C9A84C);font-size:0;line-height:0;">&nbsp;</td>
    </tr>

  </table>
  <!-- /HEADER -->

  <div class="body">
    {corpo_html}
  </div>

  <div class="bottom-stripe"></div>

  <div class="footer">
    Análise gerada por inteligência artificial para uso interno do gabinete<br>
    <a href="https://www.camarasantos.sp.gov.br/ordem-do-dia">Acessar pauta oficial da Câmara de Santos</a>
  </div>

</div>
</body>
</html>"""


# ── Envio ─────────────────────────────────────────────────────────────────────
def enviar_email(assunto: str, corpo_md: str, sessao_nome: str, qtd_itens: int, agora: str) -> None:
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    gmail_to = os.environ.get("GMAIL_TO")

    if not all([gmail_user, gmail_to]):
        raise EnvironmentError("Defina GMAIL_USER e GMAIL_TO (e GMAIL_APP_PASSWORD para SMTP).")

    destinatarios = [d.strip() for d in gmail_to.split(",")]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = f"Briefing Câmara Santos <{gmail_user}>"
    msg["To"] = ", ".join(destinatarios)

    msg.attach(MIMEText(corpo_md, "plain", "utf-8"))
    corpo_html = montar_email_html(sessao_nome, qtd_itens, corpo_md, agora)
    msg.attach(MIMEText(corpo_html, "html", "utf-8"))

    try:
        if not gmail_password:
            raise OSError("GMAIL_APP_PASSWORD ausente — indo direto para a Gmail API")
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, destinatarios, msg.as_string())
        print(f"E-mail enviado para: {', '.join(destinatarios)}", file=sys.stderr)
    except OSError as e:
        # Ambiente da rotina /schedule não abre TCP cru (porta 587) — só HTTPS via
        # proxy (constatado 2026-07-13 no monitor do DOM). Cai para a Gmail API.
        print(f"Aviso: SMTP indisponível ({e}); tentando Gmail API...", file=sys.stderr)
        token_file = os.path.join(RAIZ, "respostas-executivo", "token.json")
        enviar_gmail_api(msg, destinatarios, token_file=token_file)
