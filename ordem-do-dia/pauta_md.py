#!/usr/bin/env python3
"""
Pauta → Markdown (insumo da análise com IA)
===========================================

Baixa a pauta de uma sessão da Ordem do Dia (a mais recente, por padrão) e a
converte em **um Markdown por sessão**, com os anexos: PDFs com camada de texto
entram inline (texto extraído local); PDFs escaneados são gravados em disco e
referenciados no MD, para o agente ler direto com a ferramenta Read — substitui
o bloco base64 do caminho legado, sem custo de API.

O MD é o insumo da rotina /schedule: a skill `briefing-ordem-do-dia` lê este
arquivo e produz o briefing. Espelha o `diario-oficial/dom_md.py`.
Saída em arquivo temporário — **não versionar dados**.

Uso:
    python ordem-do-dia/pauta_md.py                                   # sessão mais recente, stdout
    python ordem-do-dia/pauta_md.py --sessao 1287 --out /tmp/p.md --anexos-dir /tmp/anexos
"""

import argparse
import re
import sys
from datetime import datetime

from coleta import get_sessao, get_documentos

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def pauta_para_md(sessao: dict, documentos: list[dict]) -> str:
    """Converte a pauta inteira num único Markdown com front-matter e seções por item."""
    partes = [
        "---",
        f"sessao: {sessao['nome']}",
        f"sessao_id: {sessao['id']}",
        f"gerado_em: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"n_itens: {len(documentos)}",
        "---",
        "",
        f"# Pauta — {sessao['nome']}",
        "",
    ]
    for i, doc in enumerate(documentos, 1):
        # o título da Câmara já vem numerado ("1. Projeto de Lei...") — não duplicar
        titulo = re.sub(r"^\d+\.\s*", "", doc["titulo"])
        partes.append(f"\n## {i}. {titulo}\n")
        campos = [
            ("Processo", doc.get("processo")),
            ("Autor", doc.get("autor")),
            ("Tipo de discussão", doc.get("tipoDiscussao")),
            ("Quórum", doc.get("quorum")),
            ("Ementa", doc.get("ementa")),
            ("Histórico", doc.get("historico")),
            ("Discussão", doc.get("discussao")),
        ]
        for rotulo, valor in campos:
            if valor:
                partes.append(f"**{rotulo}:** {valor}")
        for pdf in doc.get("pdfs", []):
            if "texto" in pdf:
                partes.append(f"\n### DOCUMENTO ANEXO: {doc['titulo']} — {pdf['label']}\n")
                partes.append(pdf["texto"])
            elif "arquivo" in pdf:
                partes.append(
                    f"\n> ANEXO ESCANEADO (ler com Read): {pdf['arquivo']}\n"
                    f"> ({doc['titulo']} — {pdf['label']})"
                )
            else:  # base64 (sem --anexos-dir): não embutir no MD
                partes.append(
                    f"\n> ANEXO ESCANEADO NÃO GRAVADO — rode com --anexos-dir "
                    f"({doc['titulo']} — {pdf['label']})"
                )
    return "\n".join(partes) + "\n"


def main():
    p = argparse.ArgumentParser(description="Pauta da Ordem do Dia → Markdown (insumo da IA)")
    p.add_argument("--sessao", help="ID da sessão. Padrão: mais recente.")
    p.add_argument("--out", help="Arquivo de saída (padrão: stdout).")
    p.add_argument("--anexos-dir",
                   help="Diretório para gravar PDFs escaneados (referenciados no MD). "
                        "Sem ele, anexos escaneados são apenas apontados como indisponíveis.")
    args = p.parse_args()

    print("Buscando sessão...", file=sys.stderr)
    sessao = get_sessao(args.sessao)
    print(f"Sessão: {sessao['nome']} (ID: {sessao['id']})", file=sys.stderr)

    print("Carregando documentos...", file=sys.stderr)
    documentos = get_documentos(sessao["id"], dir_anexos=args.anexos_dir)
    if not documentos:
        print("Nenhum documento encontrado — sem sessão nova ou pauta vazia.", file=sys.stderr)
        sys.exit(1)

    n_texto = sum(1 for d in documentos for a in d.get("pdfs", []) if "texto" in a)
    n_escaneado = sum(1 for d in documentos for a in d.get("pdfs", []) if "arquivo" in a)
    total_chars = sum(len(a["texto"]) for d in documentos for a in d.get("pdfs", []) if "texto" in a)
    print(f"{len(documentos)} item(ns); anexos: {n_texto} como texto "
          f"({total_chars} chars ≈{total_chars // 4} tokens), {n_escaneado} escaneado(s) em disco.",
          file=sys.stderr)

    md = pauta_para_md(sessao, documentos)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"Gravado: {args.out} ({len(md) / 1000:.0f} kB)", file=sys.stderr)
    else:
        print(md)


if __name__ == "__main__":
    main()
