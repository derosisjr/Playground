#!/usr/bin/env python3
"""Guarda de CACHE-BUSTING: todo .js/.css local carregado por HTML tem `?v=N`, e a
mesma URL tem a MESMA versão em todas as páginas.

Por que existe: o GitHub Pages serve com cache e o service worker guarda os
estáticos. Um `<script src="./x-app.js">` sem `?v=` fica preso na versão antiga
do navegador depois do deploy; e `comum.js?v=11` numa página com `?v=10` noutra
faz o visitante rodar duas versões da camada comum conforme a porta de entrada
(a convenção — subir N em TODAS as páginas — dependia só de memória).

Só a biblioteca padrão. Considera os HTML versionados (`git ls-files`); fora de
um repositório git, varre a árvore ignorando pastas ocultas e `_preview-*`.

Uso:
    python .github/scripts/checar_versoes.py     # sai 1 se achar problema
"""

import os
import subprocess
import sys
from collections import defaultdict
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IGNORAR_PASTAS = {"node_modules", "REQUERIMENTOS", "magda-annichino"}


class _Assets(HTMLParser):
    """Coleta (linha, url) de <script src> e <link rel=stylesheet|modulepreload href>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.achados = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("src"):
            self.achados.append((self.getpos()[0], a["src"]))
        elif tag == "link" and a.get("href"):
            rel = (a.get("rel") or "").lower().split()
            if "stylesheet" in rel or "modulepreload" in rel or "preload" in rel:
                self.achados.append((self.getpos()[0], a["href"]))


def listar_html():
    try:
        saida = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.html"], cwd=RAIZ,
            capture_output=True, check=True,
        ).stdout.decode("utf-8")
        arquivos = [p for p in saida.split("\0") if p]
        if arquivos:
            return sorted(arquivos)
    except (OSError, subprocess.CalledProcessError):
        pass
    arquivos = []
    for pasta, subpastas, nomes in os.walk(RAIZ):
        subpastas[:] = [s for s in subpastas if not s.startswith(".") and s not in IGNORAR_PASTAS]
        for n in nomes:
            if n.endswith(".html") and not n.startswith("_preview-"):
                arquivos.append(os.path.relpath(os.path.join(pasta, n), RAIZ).replace(os.sep, "/"))
    return sorted(arquivos)


def checar():
    problemas = []
    versoes = defaultdict(lambda: defaultdict(list))  # caminho -> versão -> [página:linha]
    for pagina in listar_html():
        with open(os.path.join(RAIZ, pagina), encoding="utf-8") as f:
            parser = _Assets()
            parser.feed(f.read())
        base = os.path.dirname(pagina)
        for linha, url in parser.achados:
            partes = urlsplit(url)
            if partes.scheme or partes.netloc or url.startswith("data:"):
                continue  # CDN / externo: versionado pela própria URL
            if not partes.path.endswith((".js", ".css")):
                continue
            caminho = os.path.normpath(os.path.join(base, partes.path)).replace(os.sep, "/")
            onde = f"{pagina}:{linha}"
            if not os.path.isfile(os.path.join(RAIZ, caminho)):
                problemas.append(f"{onde}: {url} aponta para arquivo inexistente ({caminho})")
                continue
            v = parse_qs(partes.query).get("v")
            if not v or not v[0].strip():
                problemas.append(f"{onde}: {url} sem ?v= (cache-busting)")
                continue
            versoes[caminho][v[0]].append(onde)
    for caminho, por_versao in sorted(versoes.items()):
        if len(por_versao) > 1:
            detalhe = "; ".join(f"v={v} em {', '.join(locais)}" for v, locais in sorted(por_versao.items()))
            problemas.append(f"{caminho} com versões diferentes entre páginas: {detalhe}")
    return problemas, versoes


def main():
    problemas, versoes = checar()
    if problemas:
        print("Cache-busting inconsistente:")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print(f"OK: {len(versoes)} asset(s) local(is) com ?v= coerente entre as páginas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
