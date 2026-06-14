#!/usr/bin/env python3
"""
Extrator do Diário Oficial de Santos (DOM)
==========================================

Baixa o PDF diário do DOM e devolve, página a página, o **texto em ordem de
leitura** + a **secretaria** responsável (herdada do índice).

Fonte:
    https://diariooficial.santos.sp.gov.br/edicoes/inicio/download/AAAA-MM-DD

Desafios resolvidos aqui (o resto do pipeline depende disto):

  1. **Layout multi-coluna.** O DOM é majoritariamente de DUAS colunas com um
     "gutter" central (~x=378 numa página de 737pt). A extração linha-a-linha
     ingênua (`extract_text`) INTERCALA as colunas — um ato da coluna esquerda
     se mistura com outro da direita. Aqui cada página é classificada como
     1-coluna (full-width) ou 2-colunas pela **cobertura de tinta na faixa
     central** (`_cobertura_centro`): páginas full-width têm muitas linhas
     cruzando o centro (~0.4+), as de 2 colunas quase nenhuma (~0.02). Em 2
     colunas, as palavras são separadas pelo centro do gutter e lê-se a coluna
     esquerda inteira e depois a direita — cada ato fica contíguo.

  2. **Secretaria por página.** O índice (1ªs páginas) mapeia
     `SEÇÃO ......... <página impressa>`. Cada página carrega seu número impresso
     no cabeçalho ("113 Diário Oficial de Santos"). Casando os dois, todo ato
     herda a secretaria/órgão — justamente a unidade que falta na Base de Despesas.

  3. **Artefato `\\uFFFD`.** O PDF usa U+FFFD como separador/fim de frase; é
     trocado por ponto.

Uso (verificação):
    python diario-oficial/extrator.py --data 2026-06-12            # imprime índice + texto
    python diario-oficial/extrator.py --data 2026-06-12 --pagina 9 # só uma página
"""

import argparse
import io
import re
import sys
import time

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

BASE_URL = "https://diariooficial.santos.sp.gov.br"
DOWNLOAD_URL = f"{BASE_URL}/edicoes/inicio/download"  # /AAAA-MM-DD
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DiarioOficialBot/1.0)"}

# Heurística de coluna: fração de linhas com tinta na faixa central acima da qual
# a página é tratada como coluna única (full-width). Calibrado em edições reais:
# full-width ~0.30–0.56; duas colunas ~0.01–0.02.
LIMIAR_FULLWIDTH = 0.15


# ── HTTP ──────────────────────────────────────────────────────────────────────
def _http_get(url: str, timeout: int = 120, tentativas: int = 4) -> requests.Response:
    """GET com retry/backoff (mesmo padrão dos outros crawlers do projeto)."""
    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            ultimo = e
            if i < tentativas - 1:
                espera = 5 * (i + 1)
                print(f"  Aviso: falha HTTP ({e}); tentativa {i+1}/{tentativas}, "
                      f"aguardando {espera}s...", file=sys.stderr)
                time.sleep(espera)
    raise ultimo


def url_edicao(data_iso: str) -> str:
    return f"{DOWNLOAD_URL}/{data_iso}"


def baixar_pdf(data_iso: str) -> bytes | None:
    """Baixa o PDF da edição de `data_iso` (AAAA-MM-DD). None se não existir."""
    r = _http_get(url_edicao(data_iso))
    ct = r.headers.get("Content-Type", "")
    if "pdf" not in ct.lower() and not r.content[:4] == b"%PDF":
        return None
    return r.content


# ── Texto / layout ────────────────────────────────────────────────────────────
def _limpar(texto: str) -> str:
    return texto.replace("�", ".")


def _linhas(words: list[dict]) -> list[tuple[float, str]]:
    """Agrupa words numa mesma faixa horizontal (linha) e devolve (top, texto)."""
    ordenadas = sorted(words, key=lambda w: (round(w["top"] / 3), w["x0"]))
    linhas: list[tuple[float, list[str]]] = []
    y = None
    for w in ordenadas:
        if y is None or abs(w["top"] - y) > 4:
            linhas.append((w["top"], [w["text"]]))
            y = w["top"]
        else:
            linhas[-1][1].append(w["text"])
    return [(top, " ".join(parts)) for top, parts in linhas]


def _cobertura_centro(words: list[dict], largura: float) -> float:
    """Fração das linhas de texto que têm alguma palavra cobrindo o centro da
    página. Alta → coluna única; baixa → duas colunas."""
    g = largura / 2
    bandas: dict[int, list[dict]] = {}
    for w in words:
        bandas.setdefault(round(w["top"] / 3), []).append(w)
    if not bandas:
        return 0.0
    cob = sum(
        1 for ws in bandas.values()
        if any(w["x0"] < g - 4 and w["x1"] > g + 4 for w in ws)
    )
    return cob / len(bandas)


def _gutter(words: list[dict], largura: float) -> float:
    """x de menor ocupação na banda central — o vão entre as duas colunas."""
    ini, fim = int(largura * 0.42), int(largura * 0.58)
    ocup = {x: 0 for x in range(ini, fim)}
    for w in words:
        for x in range(max(int(w["x0"]), ini), min(int(w["x1"]) + 1, fim)):
            ocup[x] += 1
    return float(min(ocup, key=ocup.get)) if ocup else largura / 2


def texto_pagina(page) -> str:
    """Texto da página em ordem de leitura, tratando 1 ou 2 colunas."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    if not words:
        return ""
    if _cobertura_centro(words, page.width) > LIMIAR_FULLWIDTH:
        linhas = _linhas(words)
        return _limpar("\n".join(t for _, t in linhas))
    g = _gutter(words, page.width)
    esq = [w for w in words if (w["x0"] + w["x1"]) / 2 < g]
    dire = [w for w in words if (w["x0"] + w["x1"]) / 2 >= g]
    blocos = []
    for col in (esq, dire):
        blocos.extend(t for _, t in _linhas(col))
    return _limpar("\n".join(blocos))


# ── Índice (secretaria ↔ página) ──────────────────────────────────────────────
_RE_INDICE = re.compile(r"^(.+?)[\s.…•·.�]{2,}\s*(\d{1,3})\s*$")
_RE_PAG_IMPRESSA = (
    re.compile(r"(?:^|\n)\s*(\d{1,3})\s+Diário Oficial de Santos"),
    re.compile(r"Diário Oficial de Santos\s*[•·]?\s*(\d{1,3})\b"),
)


def parsear_indice(pdf, max_paginas: int = 3) -> list[tuple[int, str]]:
    """Lê o índice das primeiras páginas → lista ordenada (pagina_impressa, seção)."""
    bruto = "\n".join(
        _limpar(pdf.pages[i].extract_text() or "")
        for i in range(min(max_paginas, len(pdf.pages)))
    )
    entradas: list[tuple[int, str]] = []
    for ln in bruto.splitlines():
        m = _RE_INDICE.match(ln.strip())
        if not m:
            continue
        secao = re.sub(r"\s+", " ", m.group(1)).strip(" .…·•")
        if len(secao) < 4 or secao.isdigit():
            continue
        entradas.append((int(m.group(2)), secao))
    # dedup mantendo a 1ª ocorrência de cada página, ordenado por página
    vistos, limpas = set(), []
    for pag, secao in sorted(entradas):
        if pag in vistos:
            continue
        vistos.add(pag)
        limpas.append((pag, secao))
    return limpas


def pagina_impressa(page, fallback: int) -> int:
    """Número impresso no cabeçalho da página; fallback = índice no PDF + 1."""
    t = page.extract_text() or ""
    cabeca = "\n".join(t.splitlines()[:6])
    for rx in _RE_PAG_IMPRESSA:
        m = rx.search(cabeca)
        if m:
            return int(m.group(1))
    return fallback


def secretaria_de(pag_impressa: int, indice: list[tuple[int, str]]) -> str:
    """Seção cuja faixa de páginas contém `pag_impressa`."""
    atual = ""
    for pag, secao in indice:
        if pag <= pag_impressa:
            atual = secao
        else:
            break
    return atual


# ── API de alto nível ─────────────────────────────────────────────────────────
def extrair_edicao(pdf_bytes: bytes) -> list[dict]:
    """Devolve uma lista de páginas: {pdf_idx, pagina, secretaria, texto}."""
    import pdfplumber

    paginas = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        indice = parsear_indice(pdf)
        for i, page in enumerate(pdf.pages):
            pag = pagina_impressa(page, i + 1)
            paginas.append({
                "pdf_idx": i,
                "pagina": pag,
                "secretaria": secretaria_de(pag, indice),
                "texto": texto_pagina(page),
            })
    return paginas


# ── CLI (verificação) ─────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Extrator do Diário Oficial de Santos")
    p.add_argument("--data", required=True, help="Data da edição (AAAA-MM-DD).")
    p.add_argument("--pagina", type=int, help="Só esta página (número do PDF, 1-based).")
    args = p.parse_args()

    pdf_bytes = baixar_pdf(args.data)
    if not pdf_bytes:
        print(f"Edição de {args.data} não encontrada.", file=sys.stderr)
        sys.exit(1)

    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        indice = parsear_indice(pdf)
        print(f"== ÍNDICE ({len(indice)} seções) ==", file=sys.stderr)
        for pag, secao in indice:
            print(f"  p.{pag:>3}  {secao}", file=sys.stderr)
        print(f"== {len(pdf.pages)} páginas ==", file=sys.stderr)
        for i, page in enumerate(pdf.pages):
            if args.pagina and i + 1 != args.pagina:
                continue
            pag = pagina_impressa(page, i + 1)
            sec = secretaria_de(pag, indice)
            print(f"\n----- PDF p.{i+1} | impressa {pag} | {sec} -----")
            print(texto_pagina(page))


if __name__ == "__main__":
    main()
