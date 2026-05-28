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
import base64
import json
import time
import argparse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from urllib.parse import urljoin
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

## PERFIL DO VEREADOR

Você assessora **Rui de Rosis Jr.**, vereador do **Partido Liberal (PL)**, de orientação **conservadora e de direita**.
Ele é **Líder da Oposição** na Câmara Municipal de Santos e presidente da Comissão de Fiscalização e Controle.
É advogado, mestre em gestão pública e ex-presidente do IPREV.

Princípios norteadores do mandato:
- Defesa do contribuinte e do pagador de impostos acima de qualquer agenda de governo
- Estado enxuto, eficiente e transparente — cada real gasto deve ter justificativa técnica
- Liberdade econômica, desregulamentação e desburocratização
- Fiscalização permanente do Executivo: questionar necessidade, legalidade e economicidade de todo ato
- Nunca ser condescendente com o governo — o papel é cobrar, fiscalizar e propor alternativas melhores
- Atenção especial a projetos que carreguem viés ideológico de esquerda: identitarismo, intervencionismo econômico,
  expansão de burocracia estatal, criação de conselhos sem função clara, políticas assistencialistas sem porta de saída,
  regulação excessiva sobre a iniciativa privada ou cerceamento de liberdades individuais e econômicas.
  O critério é o conteúdo, não apenas a sigla do autor.

## COMPOSIÇÃO DA CÂMARA MUNICIPAL DE SANTOS (2025–2028)

**Prefeito:** Rogério Santos (Republicanos) — reeleito em 2º turno em 2024.
**Total:** 21 vereadores.

### BANCADA DO PL — OPOSIÇÃO (4 cadeiras)
| Vereador | Observação |
|---|---|
| **Rui de Rosis Jr.** | Líder da Oposição. Presidente da Comissão de Fiscalização e Controle. |
| Allison Sales | Aliado direto. |
| Sergio Santana | 4º mandato. Perfil moderado — acompanhar postura real nas votações. |
| Fabio Duarte | Acompanhar postura real nas votações. |

### OPOSIÇÃO DE ESQUERDA (3 cadeiras) — divergência ideológica, eventual convergência fiscal
| Vereador | Partido | Observação |
|---|---|---|
| Débora Camilo | PSOL | Mais votada da cidade (8.016 votos). Pauta identitária e social. Declarou que PT/PSOL não serão representados pelo PL na liderança da oposição. |
| Dr. Caseiro (Marcos Caseiro) | PT | Disputou a liderança da oposição com Rui. |
| Francisco Nogueira (Chico do Settaport) | PT | Ligado ao movimento portuário e sindical. |

### BASE DO GOVERNO (14 cadeiras)
| Vereador | Partido | Observação |
|---|---|---|
| Adilson Junior | PP | **Presidente da Câmara.** |
| Cacá Teixeira | PSDB | **Líder do governo.** |
| Marcelo Téo | PP | |
| Zequinha Teixeira | PP | |
| Adriano Piemonte | União Brasil | 2º mandato. |
| Rafael Pasquarelli | União Brasil | |
| Benedito Furtado | PSB | |
| Chita | PSB | |
| Adriano Catapretta | PSD | |
| Antonio Carlos Joaquim Banha | PSD | |
| Bispo Mauricio Campos | Republicanos | Mesmo partido do prefeito. |
| Paulo Miyasiro | Republicanos | Mesmo partido do prefeito. |
| Fabrício Cardoso | Podemos | |
| Lincoln Reis | Podemos | |

**Equilíbrio de forças:** 14 × 7. A base do governo tem maioria confortável para aprovar qualquer matéria
de maioria simples. A oposição total (PL + esquerda) soma apenas 7 votos — insuficiente para barrar projetos,
mas suficiente para marcar posição, exigir transparência e criar narrativa pública.
Sergio Santana e Fabio Duarte são variáveis — em pautas específicas podem votar com a base governista.
Débora Camilo e PT podem convergir em votações de fiscalização e controle, mas a aliança é tática e limitada.

**Regra fundamental:** ao analisar cada proposta, leve em conta SEMPRE quem é o autor e qual é o interesse
político por trás. Uma proposta do PT ou PSOL, mesmo que tecnicamente razoável, carrega ônus político para o PL
votar a favor — isso deve ser explicitado. Propostas da base governista devem ser tratadas com ceticismo técnico.

Seu trabalho é transformar a pauta de uma sessão em um briefing executivo de alto nível para esse vereador.
O briefing deve ser denso em informação política, contextualizado e acionável — sempre pela ótica conservadora.

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

#### 💡 Emenda Sugerida
[Se houver oportunidade real de melhoria, correção técnica ou ajuste político favorável ao mandato do PL, proponha uma emenda com: texto objetivo da emenda, finalidade e justificativa política. Se não houver oportunidade relevante, escreva apenas: "Não há emenda pertinente neste momento."]

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
- Nunca deixe campos em branco — use o bom senso político de um assessor experiente
- **CRÍTICO: Complete TODOS os itens da pauta sem exceção. Se necessário, seja mais conciso nos itens intermediários para garantir que o último item receba a mesma profundidade. Jamais interrompa um item no meio.**
- Os textos completos dos PDFs (projetos, pareceres, vetos, ofícios) estão anexados como documentos. Baseie a análise no conteúdo real — não apenas na ementa. Cite trechos relevantes para fundamentar o posicionamento.
- **VETOS DO PREFEITO:** sempre buscar ativamente argumentos jurídicos para a derrubada do veto. Mensagens de veto frequentemente contêm erros de enquadramento legal e argumentação frágil. Em matérias de veto, desconsidere o parecer da CCJ — analise o veto diretamente com base no texto da lei vetada e no ofício do prefeito."""


# ── PDF ───────────────────────────────────────────────────────────────────────
def baixar_pdf_base64(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return base64.standard_b64encode(resp.content).decode("utf-8")
    except Exception as e:
        print(f"  Aviso: não foi possível baixar PDF {url}: {e}", file=sys.stderr)
        return None


# ── Scraping ──────────────────────────────────────────────────────────────────
def fetch_html(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.content


def get_sessao(sessao_id: str | None) -> dict:
    if sessao_id:
        return {"id": sessao_id, "nome": f"Sessão {sessao_id}"}
    html = fetch_html(IFRAME_URL)
    soup = BeautifulSoup(html, "html.parser")  # BeautifulSoup detecta charset do meta
    options = soup.select("#selSessao option")[1:]
    if not options:
        raise RuntimeError("Nenhuma sessão encontrada.")
    first = options[0]
    return {"id": first["value"], "nome": first.get_text(strip=True)}


def _text(tag) -> str:
    return tag.get_text(separator=" ", strip=True) if tag else ""


def get_documentos(sessao_id: str) -> list[dict]:
    page_url = f"{LISTAGEM_URL}{sessao_id}"
    html = fetch_html(page_url)
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

        # baixa PDFs do rodapé como base64 para envio direto à API do Claude
        pdfs: list[dict] = []
        for a in doc.select(".documento_rodape_anexo a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            pdf_url = urljoin(page_url, href)
            label = a.get_text(strip=True) or "Documento"
            print(f"  Baixando PDF: {label}...", file=sys.stderr)
            data = baixar_pdf_base64(pdf_url)
            if data:
                pdfs.append({"label": label, "data": data})

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
            "pdfs": pdfs,
        })
    return documentos


# ── Claude API ────────────────────────────────────────────────────────────────
def gerar_briefing(sessao_nome: str, documentos: list[dict]) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY não definida.")

    client = anthropic.Anthropic(api_key=api_key)

    # metadados sem os bytes dos PDFs
    meta = [{k: v for k, v in d.items() if k != "pdfs"} for d in documentos]
    pauta_json = json.dumps({"sessao": sessao_nome, "itens": meta}, ensure_ascii=False, indent=2)

    n_pdfs = sum(len(d.get("pdfs", [])) for d in documentos)
    nota_pdfs = (
        f"\n\nOs textos completos ({n_pdfs} PDFs) estão anexados como documentos abaixo. "
        "Baseie a análise no conteúdo real dos documentos, citando trechos quando relevante."
        if n_pdfs else ""
    )

    # monta content array: texto + document blocks
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Produza o briefing completo e aprofundado para a seguinte sessão:\n\n"
                f"```json\n{pauta_json}\n```{nota_pdfs}"
            ),
        }
    ]
    blocos_pdf: list[dict] = []
    for doc in documentos:
        for pdf in doc.get("pdfs", []):
            blocos_pdf.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf["data"],
                },
                "title": f"{doc['titulo']} — {pdf['label']}",
            })

    # cache_control no último bloco: na continuação os PDFs são lidos do cache
    # (custo de 10% dos tokens de entrada, evitando rate limit)
    if blocos_pdf:
        blocos_pdf[-1]["cache_control"] = {"type": "ephemeral"}
    content.extend(blocos_pdf)

    print(f"Enviando {n_pdfs} PDFs para o Claude...", file=sys.stderr)

    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": content}]

    message = _chamar_api(client, system=system, messages=messages)
    texto = message.content[0].text

    # continuação automática se o modelo atingiu o limite de tokens
    if message.stop_reason == "max_tokens":
        print("Limite de tokens atingido — solicitando continuação...", file=sys.stderr)
        messages.append({"role": "assistant", "content": texto})
        messages.append({"role": "user", "content": "Continue o briefing exatamente do ponto onde parou, sem repetir o que já foi escrito."})
        continuacao = _chamar_api(client, system=system, messages=messages)
        texto += continuacao.content[0].text

    return texto


def _chamar_api(client: anthropic.Anthropic, **kwargs) -> anthropic.types.Message:
    """Chama messages.create com retry automático em caso de rate limit (429)."""
    for tentativa in range(3):
        try:
            return client.messages.create(model="claude-sonnet-4-6", max_tokens=8192, **kwargs)
        except anthropic.RateLimitError:
            if tentativa == 2:
                raise
            espera = 65 * (tentativa + 1)
            print(f"Rate limit atingido. Aguardando {espera}s antes de tentar novamente...", file=sys.stderr)
            time.sleep(espera)


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
    corpo_html = corpo_html.replace("💡 Emenda Sugerida", '💡 <strong style="color:#003087">Emenda Sugerida</strong>')

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

  /* Tabela termômetro */
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
