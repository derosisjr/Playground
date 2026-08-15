"""
Ordem do Dia — Câmara Municipal de Santos (caminho legado, via API)
Gera um briefing político aprofundado da sessão mais recente (ou de uma sessão
específica) usando web scraping + Claude API, entregue por e-mail em HTML.

Desde 2026-08 este é o caminho de SOCORRO MANUAL (workflow_dispatch): a geração
regular migrou para a rotina /schedule (skill briefing-ordem-do-dia, cota Max,
sem API key) — ver references/rotina-schedule.md. A coleta vive em coleta.py e
o e-mail em email_briefing.py, compartilhados pelos dois caminhos; o prompt de
sistema é montado em runtime a partir de references/briefing-system-prompt.md +
.claude/rules/perfil-politico.md + references/composicao-camara.md (fonte única
com a skill).

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
import json
import time
import argparse
from datetime import datetime
import anthropic

from coleta import get_sessao, get_documentos
from email_briefing import enviar_email

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)


# ── Prompt (fonte única com a skill briefing-ordem-do-dia) ────────────────────
def carregar_system_prompt() -> str:
    """Monta o prompt de sistema a partir dos arquivos-fonte.

    references/briefing-system-prompt.md traz os marcadores [[PERFIL_DO_VEREADOR]]
    e [[COMPOSICAO_DA_CAMARA]], preenchidos aqui com os arquivos que envelhecem
    sozinhos (perfil político do mandato e composição da legislatura)."""
    def _ler(caminho: str) -> str:
        with open(caminho, encoding="utf-8") as f:
            return f.read().strip()

    base = _ler(os.path.join(AQUI, "references", "briefing-system-prompt.md"))
    perfil = _ler(os.path.join(RAIZ, ".claude", "rules", "perfil-politico.md"))
    composicao = _ler(os.path.join(AQUI, "references", "composicao-camara.md"))
    return (base
            .replace("[[PERFIL_DO_VEREADOR]]", perfil)
            .replace("[[COMPOSICAO_DA_CAMARA]]", composicao))


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
        f"\n\nOs textos completos ({n_pdfs} documentos) estão anexados abaixo "
        "(texto extraído ou PDF). Baseie a análise no conteúdo real dos documentos, "
        "citando trechos quando relevante."
        if n_pdfs else ""
    )

    # monta content array: prompt + blocos de texto (PDFs extraídos) + document blocks (escaneados)
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
    n_texto = n_escaneado = total_chars = 0
    for doc in documentos:
        for pdf in doc.get("pdfs", []):
            if "texto" in pdf:
                n_texto += 1
                total_chars += len(pdf["texto"])
                blocos_pdf.append({
                    "type": "text",
                    "text": f"### DOCUMENTO ANEXO: {doc['titulo']} — {pdf['label']}\n\n{pdf['texto']}",
                })
            else:
                n_escaneado += 1
                blocos_pdf.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf["data"],
                    },
                    "title": f"{doc['titulo']} — {pdf['label']}",
                })

    # cache_control no último bloco: no retry pós-429 os anexos são lidos do cache
    # (custo de 10% dos tokens de entrada)
    if blocos_pdf:
        blocos_pdf[-1]["cache_control"] = {"type": "ephemeral"}
    content.extend(blocos_pdf)

    print(
        f"Enviando {n_pdfs} anexos para o Claude "
        f"({n_texto} como texto ≈{total_chars // 4} tokens, {n_escaneado} como PDF base64)...",
        file=sys.stderr,
    )

    system = [{"type": "text", "text": carregar_system_prompt(),
               "cache_control": {"type": "ephemeral"}}]
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
    """Chama a API com streaming e retry automático em caso de rate limit (429).

    Usa streaming + max_tokens alto para o briefing caber numa única resposta:
    a continuação reenviaria todos os PDFs e estouraria o limite de ITPM (30k/min),
    pois tokens lidos do cache também contam para o rate limit. Streaming evita o
    timeout de HTTP em respostas longas (recomendado para max_tokens alto)."""
    for tentativa in range(3):
        try:
            with client.messages.stream(model="claude-sonnet-4-6", max_tokens=32000, **kwargs) as stream:
                return stream.get_final_message()
        except anthropic.RateLimitError:
            if tentativa == 2:
                raise
            espera = 65 * (tentativa + 1)
            print(f"Rate limit atingido. Aguardando {espera}s antes de tentar novamente...", file=sys.stderr)
            time.sleep(espera)


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
