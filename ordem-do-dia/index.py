"""
Ordem do Dia — Câmara Municipal de Santos
Gera um briefing político da sessão mais recente (ou de uma sessão específica)
usando web scraping + Claude API.

Uso:
    python index.py                        # sessão mais recente
    python index.py --sessao 1278          # sessão específica
    python index.py --output briefing.md   # salva em arquivo
    python index.py --email                # envia por e-mail (requer vars de ambiente)

Variáveis de ambiente para e-mail:
    GMAIL_USER        conta Gmail remetente (ex: gabinete@gmail.com)
    GMAIL_APP_PASSWORD  App Password de 16 dígitos (não a senha normal)
    GMAIL_TO          destinatário(s), separados por vírgula
"""

import sys
import os
import json
import argparse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import anthropic

BASE_URL = "https://administrativo.camarasantos.sp.gov.br"
IFRAME_URL = f"{BASE_URL}/dispositivo/ideCustom/legislativo/ordem_dia_eletronica/publico/"
LISTAGEM_URL = f"{IFRAME_URL}listagem.php?codigo="

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OrdemDoDiaBot/1.0)"}

SYSTEM_PROMPT = """Você é um assessor político especializado em legislação municipal brasileira, \
com experiência em Câmaras Municipais do estado de São Paulo.

Sua tarefa é analisar a pauta de uma sessão da Câmara Municipal de Santos e produzir um **briefing \
executivo** para o vereador.

Para **cada item da pauta** inclua:
- Resumo claro da proposta (máximo 2 linhas)
- Leitura política (quem se beneficia, interesses envolvidos, contexto)
- Impacto para a população de Santos
- Posicionamento sugerido: **A favor** / **Contra** / **Abstenção** / **Acompanhar**
- Pontos de atenção ou riscos

Ao final, inclua:
- **Sumário executivo** com os destaques da sessão
- **Agenda política** (itens que exigem mais atenção ou negociação)

Use formatação markdown limpa. Seja direto e objetivo — o vereador precisa se preparar em minutos."""


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def get_sessao(sessao_id: str | None) -> dict:
    """Retorna {'id': str, 'nome': str} da sessão alvo."""
    if sessao_id:
        return {"id": sessao_id, "nome": f"Sessão {sessao_id}"}

    html = fetch_html(IFRAME_URL)
    soup = BeautifulSoup(html, "html.parser")
    options = soup.select("#selSessao option")[1:]  # pula "Selecione"
    if not options:
        raise RuntimeError("Nenhuma sessão encontrada no dropdown.")

    first = options[0]
    return {"id": first["value"], "nome": first.get_text(strip=True)}


def _text(tag) -> str:
    return tag.get_text(separator=" ", strip=True) if tag else ""


def get_documentos(sessao_id: str) -> list[dict]:
    html = fetch_html(f"{LISTAGEM_URL}{sessao_id}")
    soup = BeautifulSoup(html, "html.parser")
    documentos = []

    for doc in soup.select(".documento"):
        # título e processo
        titulo = _text(doc.select_one(".titulo_documento a"))
        processo = _text(doc.select_one(".titulo_documento_processo a"))

        # tipo de discussão e quórum
        spans = [s.get_text(strip=True) for s in doc.select(".documento_corpo_esquerdo span")]
        tipo_discussao = spans[0] if len(spans) > 0 else ""
        quorum = spans[1] if len(spans) > 1 else ""

        # campos da tabela (Autor, Ementa, Histórico, Discussão)
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

        # rótulos dos anexos
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


def gerar_briefing(sessao_nome: str, documentos: list[dict]) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("Variável ANTHROPIC_API_KEY não definida.")

    client = anthropic.Anthropic(api_key=api_key)
    pauta_json = json.dumps({"sessao": sessao_nome, "itens": documentos}, ensure_ascii=False, indent=2)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Analise a seguinte pauta e produza o briefing:\n\n```json\n{pauta_json}\n```",
            }
        ],
    )

    return message.content[0].text


def enviar_email(assunto: str, corpo_markdown: str) -> None:
    """Envia o briefing por e-mail via Gmail SMTP."""
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    gmail_to = os.environ.get("GMAIL_TO")

    if not all([gmail_user, gmail_password, gmail_to]):
        raise EnvironmentError(
            "Defina GMAIL_USER, GMAIL_APP_PASSWORD e GMAIL_TO para enviar e-mail."
        )

    destinatarios = [d.strip() for d in gmail_to.split(",")]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = gmail_user
    msg["To"] = ", ".join(destinatarios)

    # versão texto puro
    msg.attach(MIMEText(corpo_markdown, "plain", "utf-8"))

    # versão HTML simples (markdown → HTML básico)
    corpo_html = corpo_markdown.replace("\n", "<br>").replace("**", "<strong>", 1)
    corpo_html = f"<html><body><pre style='font-family:Arial,sans-serif;white-space:pre-wrap'>{corpo_markdown}</pre></body></html>"
    msg.attach(MIMEText(corpo_html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, destinatarios, msg.as_string())

    print(f"E-mail enviado para: {', '.join(destinatarios)}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Briefing da Ordem do Dia — Câmara de Santos")
    parser.add_argument("--sessao", help="ID da sessão (ex: 1278). Padrão: sessão mais recente.")
    parser.add_argument("--output", help="Caminho do arquivo de saída (.md). Padrão: stdout.")
    parser.add_argument("--email", action="store_true", help="Envia o briefing por e-mail via Gmail.")
    args = parser.parse_args()

    print("Buscando sessão...", file=sys.stderr)
    sessao = get_sessao(args.sessao)
    print(f"Sessão: {sessao['nome']} (ID: {sessao['id']})", file=sys.stderr)

    print("Carregando documentos da pauta...", file=sys.stderr)
    documentos = get_documentos(sessao["id"])
    print(f"{len(documentos)} item(ns) encontrado(s).", file=sys.stderr)

    if not documentos:
        print("Nenhum documento encontrado para esta sessão.", file=sys.stderr)
        return

    print("Gerando briefing com Claude...", file=sys.stderr)
    briefing = gerar_briefing(sessao["nome"], documentos)

    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    cabecalho = (
        f"---\n"
        f"Gerado em: {agora}\n"
        f"Sessão: {sessao['nome']}\n"
        f"Total de itens: {len(documentos)}\n"
        f"---\n\n"
    )
    relatorio = cabecalho + briefing

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(relatorio)
        print(f"Relatório salvo em: {args.output}", file=sys.stderr)

    if args.email:
        assunto = f"📋 Ordem do Dia — {sessao['nome']}"
        enviar_email(assunto, relatorio)

    if not args.output and not args.email:
        print(relatorio)


if __name__ == "__main__":
    main()
