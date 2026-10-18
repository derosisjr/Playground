#!/usr/bin/env python3
"""Guarda de CAMPOS PÚBLICOS: os JSON já publicados só têm as chaves da lista branca.

Por que existe: o export de Requerimentos aborta se aparecer campo fora de
`CAMPOS_PUBLICOS` — mas isso só vale para o arquivo que ELE gera. Quando o export
não roda, o arquivo publicado continua o antigo: o passo era pulado sempre que o
crawler da Câmara falhava, e em 18/10/2026, dois dias depois da correção, o
`requerimentos-index.json` no ar ainda trazia a coluna interna "Status atual" da
planilha ("ok (Falar com o Rui)", "não sei se cabe reiterar"…) em 437 de 623
linhas. Esta guarda olha o que está commitado, não o que o export faria.

A lista de cada base é LIDA do próprio export (nunca copiada aqui) — pela árvore
sintática do arquivo, sem importá-lo: o export puxa `index` → `comum.http` →
`requests`, e o workflow diário roda só com a biblioteca padrão.
Roda no Testes (PR/push) e no workflow diário.

Uso:
    python .github/scripts/checar_publicos.py [raiz]   # sai 1 se achar campo fora da lista
"""

import ast
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def lista_do_export(caminho: str, nome: str = "CAMPOS_PUBLICOS") -> tuple[str, ...]:
    """O valor literal de `nome = (...)` no módulo, sem executá-lo."""
    with open(caminho, encoding="utf-8") as f:
        arvore = ast.parse(f.read(), caminho)
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(isinstance(a, ast.Name) and a.id == nome for a in no.targets):
            return tuple(ast.literal_eval(no.value))
    raise LookupError(f"{nome} não encontrado em {caminho}")


def bases(raiz: str = RAIZ) -> dict[str, tuple[str, ...]]:
    """{arquivo publicado: campos permitidos} — a lista branca de cada export."""
    return {
        "requerimentos-index.json": lista_do_export(os.path.join(raiz, "respostas-executivo", "export.py")),
    }


def problemas(raiz: str, permitidos_por_arquivo: dict[str, tuple[str, ...]]) -> list[str]:
    """Uma linha por arquivo com chave fora da lista (arquivo ausente não é problema)."""
    saida = []
    for arquivo, permitidos in permitidos_por_arquivo.items():
        caminho = os.path.join(raiz, arquivo)
        if not os.path.exists(caminho):
            continue
        with open(caminho, encoding="utf-8") as f:
            itens = json.load(f)
        fora: dict[str, int] = {}
        for item in itens:
            for chave in set(item) - set(permitidos):
                fora[chave] = fora.get(chave, 0) + 1
        if fora:
            detalhe = ", ".join(f"{k!r} em {n} de {len(itens)} itens" for k, n in sorted(fora.items()))
            saida.append(f"{arquivo}: campos fora da lista branca — {detalhe}")
    return saida


def main(argv: list[str] | None = None) -> int:
    raiz = (argv or sys.argv[1:] or [RAIZ])[0]
    achados = problemas(raiz, bases(raiz))
    for linha in achados:
        print(f"ERRO: {linha}", file=sys.stderr)
    if achados:
        print("Regere o arquivo pelo export da base (ele só grava campos da lista).", file=sys.stderr)
        return 1
    print("OK: os JSON publicados só têm campos da lista branca.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
