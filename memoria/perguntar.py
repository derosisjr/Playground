# -*- coding: utf-8 -*-
"""Pergunte à memória do gabinete — RAG local com citações.

Recupera os trechos mais relevantes do memoria.sqlite (FTS5/BM25) e pede ao
Claude uma resposta baseada SÓ neles, citando [origem, data, link] de cada
afirmação. Sem trecho relevante = resposta dizendo que não há registro.

Uso:
  python memoria/perguntar.py "o que o governo respondeu sobre a fila da saúde?"
  python memoria/perguntar.py --sem-ia "iluminação led"      # só os trechos
  python memoria/perguntar.py --n 30 "contratos PRODESAN"
Requer ANTHROPIC_API_KEY no ambiente (exceto com --sem-ia).
"""
import argparse
import os
import re
import sqlite3
import sys
import time
import unicodedata

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memoria.sqlite")
MODELO = "claude-sonnet-4-6"
TRECHO_MAX = 1500  # chars de cada documento enviados ao modelo

SYSTEM = """Você é o assistente de memória do gabinete do vereador Rui de Rosis Jr.
(Câmara de Santos). Responda à pergunta usando EXCLUSIVAMENTE os trechos
fornecidos — não use conhecimento externo. Regras:
- Cite a fonte de cada afirmação no formato [#N — origem, data].
- Se os trechos não respondem, diga claramente que não há registro no acervo
  e sugira 1-2 termos de busca alternativos.
- Seja direto e factual; português brasileiro; sem opinião política.
- Ao final, liste as fontes citadas com título e link (quando houver)."""


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c)).lower().strip()


def buscar(conn, pergunta: str, n: int) -> list[dict]:
    """Top-N trechos por BM25; consulta FTS montada com OR dos termos."""
    termos = [t for t in re.findall(r"\w+", _sem_acento(pergunta)) if len(t) > 2]
    if not termos:
        return []
    consulta = " OR ".join(f'"{t}"' for t in termos)
    linhas = conn.execute(
        "SELECT d.id, d.origem, d.titulo, d.data, d.url, d.texto, bm25(docs_fts) r "
        "FROM docs_fts JOIN documentos d ON d.rowid = docs_fts.rowid "
        "WHERE docs_fts MATCH ? ORDER BY r LIMIT ?", (consulta, n)).fetchall()
    return [dict(r) for r in linhas]


def _trecho(texto: str, pergunta: str) -> str:
    """Janela do texto centrada na 1ª ocorrência do termo mais raro."""
    alvo = _sem_acento(texto)
    for t in sorted(re.findall(r"\w+", _sem_acento(pergunta)), key=len, reverse=True):
        i = alvo.find(t)
        if i >= 0:
            ini = max(0, i - TRECHO_MAX // 3)
            return ("…" if ini else "") + texto[ini:ini + TRECHO_MAX]
    return texto[:TRECHO_MAX]


def perguntar_ia(pergunta: str, docs: list[dict]) -> str:
    import anthropic
    cliente = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    contexto = "\n\n".join(
        f"[#{i+1} — {d['origem']}, {d['data'] or 's/ data'}]\n"
        f"Título: {d['titulo']}\nLink: {d['url'] or '(sem link)'}\n"
        f"Trecho: {_trecho(d['texto'] or '', pergunta)}"
        for i, d in enumerate(docs))
    for tentativa in range(3):
        try:
            resp = cliente.messages.create(
                model=MODELO, max_tokens=2000, system=SYSTEM,
                messages=[{"role": "user", "content":
                           f"TRECHOS DO ACERVO:\n\n{contexto}\n\n"
                           f"PERGUNTA: {pergunta}"}])
            return resp.content[0].text
        except anthropic.RateLimitError:
            time.sleep(65 * (tentativa + 1))
    raise RuntimeError("rate limit persistente na API")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Pergunte à memória do gabinete")
    ap.add_argument("pergunta")
    ap.add_argument("--n", type=int, default=20, help="trechos recuperados (padrão 20)")
    ap.add_argument("--sem-ia", action="store_true", help="só lista os trechos")
    args = ap.parse_args()

    if not os.path.exists(BASE):
        sys.exit("memoria.sqlite não existe — rode python memoria/indexar.py antes.")
    conn = sqlite3.connect(BASE)
    conn.row_factory = sqlite3.Row
    docs = buscar(conn, args.pergunta, args.n)
    if not docs:
        sys.exit("Nenhum documento relevante no acervo para esses termos.")

    if args.sem_ia:
        for i, d in enumerate(docs, 1):
            print(f"[#{i} — {d['origem']}, {d['data'] or 's/ data'}] {d['titulo']}")
            print(f"   {(_trecho(d['texto'] or '', args.pergunta))[:200]}")
            if d["url"]:
                print(f"   {d['url']}")
        return

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY não definido — use --sem-ia para busca simples.")
    print(perguntar_ia(args.pergunta, docs))


if __name__ == "__main__":
    main()
