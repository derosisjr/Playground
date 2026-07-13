#!/usr/bin/env python3
"""
DOM → Markdown limpo (insumo da análise com IA)
===============================================

Baixa o PDF da edição do Diário Oficial de Santos e converte em **um Markdown
por edição**, fiel ao layout (2 colunas resolvidas pelo `pymupdf4llm`, não pela
heurística caseira do `extrator.py`). O MD é o insumo da rotina /schedule: a IA
(skill `dom-santos`) lê este arquivo e devolve os atos classificados em JSON.

Escolha da lib (diagnóstico 2026-07-13, edição 2026-06-12): `pymupdf4llm`
capturou +30k chars e 194×170 âncoras de atos vs o extrator atual — incluindo
TERMOS DE COMPROMISSO (Terceiro Setor) que a heurística de coluna perdia.

Limpezas aplicadas (o resto fica para a IA, que lê markdown com ruído leve):
  - `U+FFFD` → "." (o PDF do DOM usa U+FFFD como separador/fim de frase);
  - masthead/cabeçalho de página ("7 Diário Oficial de Santos", data da edição)
    removidos do fluxo;
  - front-matter com data/URL + seção por página com a secretaria (herdada do
    índice das primeiras páginas, mesmo mecanismo do `extrator.py`).

Uso:
    python diario-oficial/dom_md.py --data 2026-06-12                # imprime no stdout
    python diario-oficial/dom_md.py --data 2026-06-12 --out ed.md    # grava em arquivo
"""

import argparse
import re
import sys

import extrator  # download + índice secretaria→página (já sólidos)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Masthead/cabeçalho/rodapé de página no fluxo do texto (mesma família de padrões
# do classificador): "7 Diário Oficial de Santos", "Diário Oficial de Santos 7",
# e a linha de data da edição ("12 de junho de 2026").
_RE_MASTHEAD = re.compile(
    r"^\s*#*\s*\**\s*(?:\d{1,3}\s+)?Di[áa]rio Oficial de Santos(?:\s*[•·]?\s*\d{1,3})?\s*\**\s*$",
    re.I,
)
_RE_DATA_EDICAO = re.compile(
    r"^\s*#*\s*\**\s*(?:santos\s*,\s*)?\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}\s*\**\s*$", re.I
)
# Variante combinada numa linha só: "12 de junho de 2026 **2** Diário Oficial de Santos"
# (data + nº da página em negrito + masthead, como o pymupdf4llm emite o cabeçalho).
_RE_MASTHEAD_COMBINADO = re.compile(
    r"^\s*\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}\s*\**\s*\d{1,3}\s*\**\s*Di[áa]rio Oficial de Santos\s*\**\s*$",
    re.I,
)


def _limpar_pagina(md: str) -> str:
    """Limpezas determinísticas leves numa página de markdown."""
    md = md.replace("�", ".")
    linhas = [
        l for l in md.splitlines()
        if not _RE_MASTHEAD.match(l) and not _RE_DATA_EDICAO.match(l)
        and not _RE_MASTHEAD_COMBINADO.match(l)
    ]
    # colapsa linhas em branco consecutivas
    out, branco = [], False
    for l in linhas:
        if l.strip():
            out.append(l)
            branco = False
        elif not branco:
            out.append("")
            branco = True
    return "\n".join(out).strip()


_RE_PAG_IMPRESSA_TXT = re.compile(
    r"\b(\d{1,3})\b[*\s]+Di[áa]rio Oficial de Santos", re.I
)


def _pagina_impressa(md: str, fallback: int) -> int:
    """Número impresso no cabeçalho, lido do próprio markdown da página."""
    m = _RE_PAG_IMPRESSA_TXT.search(md[:400])
    return int(m.group(1)) if m else fallback


def edicao_para_md(data_iso: str, pdf_bytes: bytes) -> str:
    """Converte a edição inteira num único Markdown com front-matter e seções por página."""
    import io

    import pymupdf
    import pymupdf4llm

    # índice secretaria→página: reusa o parser do extrator (barato e confiável)
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        indice = extrator.parsear_indice(pdf)

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    chunks = pymupdf4llm.to_markdown(doc, page_chunks=True, show_progress=False)

    partes = [
        "---",
        f"edicao: {data_iso}",
        f"url: {extrator.url_edicao(data_iso)}",
        f"paginas: {len(chunks)}",
        "---",
        "",
        f"# Diário Oficial de Santos — edição de {data_iso}",
        "",
    ]
    for i, c in enumerate(chunks):
        bruto = c.get("text", "")
        pag = _pagina_impressa(bruto, i + 1)
        secretaria = extrator.secretaria_de(pag, indice)
        corpo = _limpar_pagina(bruto)
        if not corpo:
            continue
        rotulo = f" — {secretaria}" if secretaria else ""
        partes.append(f"\n## Página {pag}{rotulo}\n")
        partes.append(corpo)
    return "\n".join(partes) + "\n"


def gerar(data_iso: str) -> str | None:
    """Baixa a edição e devolve o Markdown; None se a edição não existir."""
    pdf_bytes = extrator.baixar_pdf(data_iso)
    if not pdf_bytes:
        return None
    return edicao_para_md(data_iso, pdf_bytes)


def main():
    p = argparse.ArgumentParser(description="DOM → Markdown limpo (insumo da IA)")
    p.add_argument("--data", required=True, help="Data da edição (AAAA-MM-DD).")
    p.add_argument("--out", help="Arquivo de saída (padrão: stdout).")
    args = p.parse_args()

    md = gerar(args.data)
    if md is None:
        print(f"Edição de {args.data} não encontrada.", file=sys.stderr)
        sys.exit(1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"Gravado: {args.out} ({len(md)/1000:.0f} kB)", file=sys.stderr)
    else:
        print(md)


if __name__ == "__main__":
    main()
