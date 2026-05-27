"""
Ordem do Dia — Câmara Municipal de Santos
Gera um briefing político aprofundado da sessão mais recente (ou de uma sessão
específica) usando web scraping + Claude API, entregue por e-mail em HTML.

Uso:
    python index.py                        # sessão mais recente
    python index.py --sessao 1278          # sessão específica
    python index.py --output briefing.md   # salva markdown em arquivo
    python index.py --email                # envia e-mail HTML

Variáveis de ambiente:
    ANTHROPIC_API_KEY   chave da API do Claude
    GMAIL_USER          conta Gmail remetente
    GMAIL_APP_PASSWORD  App Password de 16 dígitos
    GMAIL_TO            destinatário(s), separados por vírgula
"""

import sys
import os
import re
import json
import argparse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import anthropic
import markdown as md

BASE_URL = "https://administrativo.camarasantos.sp.gov.br"
IFRAME_URL = f"{BASE_URL}/dispositivo/ideCustom/legislativo/ordem_dia_eletronica/publico/"
LISTAGEM_URL = f"{IFRAME_URL}listagem.php?codigo="
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OrdemDoDiaBot/1.0)"}

# ── Prompt aprofundado ────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Você é um assessor político sênior especializado em legislação municipal brasileira,
com profundo conhecimento das dinâmicas da Câmara Municipal de Santos (SP) e da política local do litoral paulista.

Seu trabalho é transformar a pauta de uma sessão em um briefing executivo de alto nível para um vereador.
O briefing deve ser denso em informação política, contextualizado e acionável.

## FORMATO DE SAÍDA OBRIGATÓRIO

Produza EXATAMENTE nesta estrutura markdown:

---

## SUMÁRIO EXECUTIVO

[3 a 4 parágrafos com: leitura geral da sessão, temas dominantes, equilíbrio de forças, nível de atenção requerido e tom político do dia.]

---

## TERMÔMETRO DA SESSÃO

| # | Proposta | Autor | Fase | Posicionamento | Prioridade |
|---|----------|-------|------|----------------|------------|
[uma linha por item com: número, nome curto, autor, fase, ⚠️ A favor / ❌ Contra / ⏸️ Abstenção / 👁️ Acompanhar, 🔴 Alta / 🟡 Média / 🟢 Baixa]

---

## ANÁLISE DETALHADA

[Para CADA item da pauta, use exatamente este bloco:]

### [número]. [Tipo] Nº [número] — [título descritivo curto]

> **[Ementa resumida em uma linha]**

**Autor:** [nome] | **Fase:** [fase] | **Quórum:** [quórum] | **Processo:** [número]

#### Contexto e Análise Política
[2 a 3 parágrafos: Por que esta proposta existe agora? Que problema resolve ou cria? Quais interesses políticos e econômicos estão em jogo? Há pressão de algum grupo? Qual o histórico deste tema em Santos?]

#### Quem Ganha, Quem Perde
- **Beneficiados:** [grupos, segmentos, territórios]
- **Prejudicados ou em risco:** [grupos, segmentos, territórios]
- **Aliados naturais para o vereador:** [partidos, vereadores, entidades]

#### Histórico Legislativo
[Pareceres das comissões, emendas apresentadas, discussões anteriores, conexão com outras propostas em tramitação]

#### Riscos e Oportunidades
- **Risco:** [risco concreto se votar a favor ou contra]
- **Oportunidade:** [como capitalizar politicamente]

#### Como Falar com os Eleitores
[1 parágrafo: linguagem simples para explicar o voto ao eleitorado, evitando juridiquês]

#### ⚖️ Posicionamento Sugerido
**[OPÇÃO EM MAIÚSCULAS]** — [justificativa política em 2 linhas, considerando agenda do vereador e contexto da Câmara]

---

## AGENDA POLÍTICA

[Lista dos 3 a 5 pontos que exigem ação ou atenção especial antes ou durante a sessão: negociações necessárias, riscos de constrangimento, oportunidades de protagonismo, itens para monitorar de perto]

---

## COMUNICAÇÃO PÓS-SESSÃO

[Sugestão de 2 a 3 linhas para post em redes sociais ou nota à imprensa, independente do resultado da votação]

---

Regras:
- Seja direto e use linguagem política afiada, não burocrática
- Considere sempre o contexto de Santos: cidade portuária, turismo, servidores públicos, baixada santista
- Se não tiver informação suficiente para algum campo, escreva o que for razoável inferir do contexto municipal
- Nunca deixe campos em branco — use o bom senso político de um assessor experiente"""


# ── Scraping ──────────────────────────────────────────────────────────────────
def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def get_sessao(sessao_id: str | None) -> dict:
    if sessao_id:
        return {"id": sessao_id, "nome": f"Sessão {sessao_id}"}
    html = fetch_html(IFRAME_URL)
    soup = BeautifulSoup(html, "html.parser")
    options = soup.select("#selSessao option")[1:]
    if not options:
        raise RuntimeError("Nenhuma sessão encontrada.")
    first = options[0]
    return {"id": first["value"], "nome": first.get_text(strip=True)}


def _text(tag) -> str:
    return tag.get_text(separator=" ", strip=True) if tag else ""


def get_documentos(sessao_id: str) -> list[dict]:
    html = fetch_html(f"{LISTAGEM_URL}{sessao_id}")
    soup = BeautifulSoup(html, "html.parser")
    documentos = []
    for doc in soup.select(".documento"):
        titulo = _text(doc.select_one(".titulo_documento a"))
        processo = _text(doc.select_one(".titulo_documento_processo a"))
        spans = [s.get_text(strip=True) for s in doc.select(".documento_corpo_esquerdo span")]
        tipo_discussao = spans[0] if spans else ""
        quorum = spans[1] if len(spans) > 1 else ""
        campos: dict[str, str] = {}
        for row in doc.select(".documento_corpo_direito tr"):
            th = row.find("th")
            if not th:
                continue
            chave = th.get_text(strip=True).rstrip(":")
            tds = row.find_all("td")
            if tds:
                valor = tds[0].get_text(separator=" ", strip=True)
                if valor:
                    campos[chave] = valor
        anexos = [
            s.get_text(strip=True)
            for s in doc.select(".documento_rodape_anexo span")
            if s.get_text(strip=True)
        ]
        if not titulo:
            continue
        documentos.append({
            "titulo": titulo,
            "processo": processo,
            "tipoDiscussao": tipo_discussao,
            "quorum": quorum,
            "autor": campos.get("Autor", ""),
            "ementa": campos.get("Ementa", ""),
            "historico": campos.get("Histórico", ""),
            "discussao": campos.get("Discussão", ""),
            "anexos": anexos,
        })
    return documentos


# ── Claude API ────────────────────────────────────────────────────────────────
def gerar_briefing(sessao_nome: str, documentos: list[dict]) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY não definida.")

    client = anthropic.Anthropic(api_key=api_key)
    pauta_json = json.dumps(
        {"sessao": sessao_nome, "itens": documentos},
        ensure_ascii=False, indent=2
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": (
                f"Produza o briefing completo e aprofundado para a seguinte sessão:\n\n"
                f"```json\n{pauta_json}\n```"
            ),
        }],
    )
    return message.content[0].text


# ── HTML do e-mail ────────────────────────────────────────────────────────────
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

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Briefing — {sessao_nome}</title>
<style>
  /* Reset e base */
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background: #f0f2f5;
    color: #1a1a2e;
    font-size: 15px;
    line-height: 1.7;
  }}

  /* Container */
  .wrapper {{ max-width: 720px; margin: 0 auto; background: #fff; }}

  /* Cabeçalho */
  .header {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
    padding: 40px 40px 32px;
    color: #fff;
  }}
  .header-label {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: #e94560;
    margin-bottom: 10px;
  }}
  .header h1 {{
    font-size: 22px;
    font-weight: 700;
    line-height: 1.3;
    color: #fff;
    margin-bottom: 16px;
  }}
  .header-meta {{
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
  }}
  .meta-pill {{
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 12px;
    color: #cdd6f4;
    font-weight: 500;
  }}

  /* Corpo */
  .body {{ padding: 36px 40px; }}

  /* Seções */
  .body h2 {{
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #e94560;
    border-bottom: 2px solid #e94560;
    padding-bottom: 8px;
    margin: 40px 0 20px;
  }}
  .body h2:first-child {{ margin-top: 0; }}

  /* Sub-seções por item */
  .body h3 {{
    font-size: 17px;
    font-weight: 700;
    color: #0f3460;
    margin: 36px 0 4px;
    padding: 16px 20px;
    background: #f8f9ff;
    border-left: 4px solid #0f3460;
    border-radius: 0 8px 8px 0;
    line-height: 1.4;
  }}

  .body h4 {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: #6b7280;
    margin: 24px 0 8px;
  }}

  /* Blockquote (ementa resumida) */
  .body blockquote {{
    border-left: 3px solid #e94560;
    padding: 10px 18px;
    margin: 12px 0 20px;
    background: #fff5f7;
    border-radius: 0 6px 6px 0;
    font-style: italic;
    color: #4a4a6a;
    font-size: 14px;
  }}

  /* Parágrafos e listas */
  .body p {{ margin: 10px 0; color: #374151; }}
  .body ul, .body ol {{ padding-left: 22px; margin: 8px 0; }}
  .body li {{ margin: 5px 0; color: #374151; }}
  .body strong {{ color: #1a1a2e; font-weight: 700; }}

  /* Tabela termômetro */
  .body table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    margin: 16px 0;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  }}
  .body th {{
    background: #1a1a2e;
    color: #cdd6f4;
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 11px 14px;
    text-align: left;
  }}
  .body td {{
    padding: 10px 14px;
    border-bottom: 1px solid #f0f0f5;
    vertical-align: middle;
  }}
  .body tr:last-child td {{ border-bottom: none; }}
  .body tr:nth-child(even) td {{ background: #fafafa; }}

  /* Badges posicionamento */
  .badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    white-space: nowrap;
  }}
  .badge.favor {{ background: #dcfce7; color: #166534; }}
  .badge.contra {{ background: #fee2e2; color: #991b1b; }}
  .badge.abstencao {{ background: #fef9c3; color: #854d0e; }}
  .badge.acompanhar {{ background: #e0f2fe; color: #075985; }}

  /* Prioridade */
  .pri {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
  }}
  .pri.alta {{ background: #fde8e8; color: #c0392b; }}
  .pri.media {{ background: #fef3cd; color: #856404; }}
  .pri.baixa {{ background: #d4edda; color: #155724; }}

  /* Bloco de posicionamento */
  .body p strong:only-child {{ display: block; }}

  /* Separador */
  .body hr {{
    border: none;
    border-top: 1px solid #e5e7eb;
    margin: 32px 0;
  }}

  /* Rodapé */
  .footer {{
    background: #f8f9ff;
    border-top: 1px solid #e5e7eb;
    padding: 24px 40px;
    text-align: center;
    font-size: 12px;
    color: #9ca3af;
    line-height: 1.8;
  }}
  .footer a {{ color: #0f3460; text-decoration: none; }}
</style>
</head>
<body>
<div class="wrapper">

  <div class="header">
    <div class="header-label">Câmara Municipal de Santos</div>
    <h1>Briefing da Ordem do Dia</h1>
    <div class="header-meta">
      <span class="meta-pill">📅 {sessao_nome}</span>
      <span class="meta-pill">📋 {qtd_itens} itens na pauta</span>
      <span class="meta-pill">🕐 Gerado às {agora}</span>
    </div>
  </div>

  <div class="body">
    {corpo_html}
  </div>

  <div class="footer">
    Gerado automaticamente por IA · Câmara Municipal de Santos<br>
    <a href="https://www.camarasantos.sp.gov.br/ordem-do-dia">Ver pauta oficial</a>
  </div>

</div>
</body>
</html>"""


# ── Envio de e-mail ───────────────────────────────────────────────────────────
def enviar_email(assunto: str, corpo_md: str, sessao_nome: str, qtd_itens: int, agora: str) -> None:
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    gmail_to = os.environ.get("GMAIL_TO")

    if not all([gmail_user, gmail_password, gmail_to]):
        raise EnvironmentError("Defina GMAIL_USER, GMAIL_APP_PASSWORD e GMAIL_TO.")

    destinatarios = [d.strip() for d in gmail_to.split(",")]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = f"Briefing Câmara Santos <{gmail_user}>"
    msg["To"] = ", ".join(destinatarios)

    msg.attach(MIMEText(corpo_md, "plain", "utf-8"))
    corpo_html = montar_email_html(sessao_nome, qtd_itens, corpo_md, agora)
    msg.attach(MIMEText(corpo_html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, destinatarios, msg.as_string())

    print(f"E-mail enviado para: {', '.join(destinatarios)}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Briefing Ordem do Dia — Câmara de Santos")
    parser.add_argument("--sessao", help="ID da sessão. Padrão: mais recente.")
    parser.add_argument("--output", help="Arquivo de saída .md.")
    parser.add_argument("--email", action="store_true", help="Envia por e-mail.")
    args = parser.parse_args()

    print("Buscando sessão...", file=sys.stderr)
    sessao = get_sessao(args.sessao)
    print(f"Sessão: {sessao['nome']} (ID: {sessao['id']})", file=sys.stderr)

    print("Carregando documentos...", file=sys.stderr)
    documentos = get_documentos(sessao["id"])
    print(f"{len(documentos)} item(ns) encontrado(s).", file=sys.stderr)

    if not documentos:
        print("Nenhum documento encontrado.", file=sys.stderr)
        return

    print("Gerando briefing com Claude...", file=sys.stderr)
    briefing = gerar_briefing(sessao["nome"], documentos)

    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(f"# Briefing — {sessao['nome']}\n\n")
            f.write(f"*Gerado em {agora} · {len(documentos)} itens*\n\n---\n\n")
            f.write(briefing)
        print(f"Relatório salvo em: {args.output}", file=sys.stderr)

    if args.email:
        assunto = f"📋 Briefing {sessao['nome']}"
        enviar_email(assunto, briefing, sessao["nome"], len(documentos), agora)

    if not args.output and not args.email:
        print(briefing)


if __name__ == "__main__":
    main()
