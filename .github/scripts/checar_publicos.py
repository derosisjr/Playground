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

Indicações (out/2026) têm também campos de VALOR fechado: a coluna "Bairro" da
planilha é texto livre e já trouxe anotação interna ("RESPOSTA EM 07 MESES"), então o
`bairro` publicado só pode ser um nome do GeoJSON da Prefeitura e a `regiao` um rótulo
de `respostas-executivo/bairros.py` (REGIOES) — chave certa com valor cru também vaza.

Uso:
    python .github/scripts/checar_publicos.py [raiz]   # sai 1 se achar campo fora da lista
"""

import ast
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def literal_do_modulo(caminho: str, nome: str):
    """O valor literal de `nome = ...` no módulo, sem executá-lo."""
    with open(caminho, encoding="utf-8") as f:
        arvore = ast.parse(f.read(), caminho)
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(isinstance(a, ast.Name) and a.id == nome for a in no.targets):
            return ast.literal_eval(no.value)
    raise LookupError(f"{nome} não encontrado em {caminho}")


def lista_do_export(caminho: str, nome: str = "CAMPOS_PUBLICOS") -> tuple[str, ...]:
    """O valor literal de `nome = (...)` no módulo, sem executá-lo."""
    return tuple(literal_do_modulo(caminho, nome))


def bases(raiz: str = RAIZ) -> dict[str, tuple[str, ...]]:
    """{arquivo publicado: campos permitidos} — a lista branca de cada export."""
    export = os.path.join(raiz, "respostas-executivo", "export.py")
    return {
        "requerimentos-index.json": lista_do_export(export),
        "indicacoes-index.json": lista_do_export(export, "CAMPOS_PUBLICOS_INDICACOES"),
    }


def valores_permitidos(raiz: str = RAIZ) -> dict[str, dict[str, set]]:
    """{arquivo publicado: {campo: valores aceitos}} para os campos de valor fechado —
    lidos das fontes do export (GeoJSON dos bairros e REGIOES de bairros.py), nunca
    copiados aqui. Só para arquivo publicado: sem ele não há o que conferir."""
    regras = {}
    if os.path.exists(os.path.join(raiz, "indicacoes-index.json")):
        with open(os.path.join(raiz, "geo", "santos-bairros.geojson"), encoding="utf-8") as f:
            nomes = {ft["properties"]["nome"] for ft in json.load(f)["features"]}
        regioes = literal_do_modulo(os.path.join(raiz, "respostas-executivo", "bairros.py"), "REGIOES")
        regras["indicacoes-index.json"] = {"bairro": nomes | {""}, "regiao": set(regioes.values()) | {""}}
    return regras


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


def problemas_valores(raiz: str, regras: dict[str, dict[str, set]]) -> list[str]:
    """Uma linha por campo com valor fora da lista fechada. Aponta o NÚMERO dos itens,
    nunca o valor: o log do Actions é público e o valor pode ser a anotação interna."""
    saida = []
    for arquivo, campos in regras.items():
        caminho = os.path.join(raiz, arquivo)
        if not os.path.exists(caminho):
            continue
        with open(caminho, encoding="utf-8") as f:
            itens = json.load(f)
        for campo, aceitos in sorted(campos.items()):
            ruins = [str(i.get("numero", "?")) for i in itens if campo in i and i[campo] not in aceitos]
            if ruins:
                exemplos = ", ".join(ruins[:5]) + (" …" if len(ruins) > 5 else "")
                saida.append(f"{arquivo}: {campo!r} fora da lista fechada em {len(ruins)} de "
                             f"{len(itens)} itens (nº {exemplos})")
    return saida


def main(argv: list[str] | None = None) -> int:
    raiz = (argv or sys.argv[1:] or [RAIZ])[0]
    achados = problemas(raiz, bases(raiz)) + problemas_valores(raiz, valores_permitidos(raiz))
    for linha in achados:
        print(f"ERRO: {linha}", file=sys.stderr)
    if achados:
        print("Regere o arquivo pelo export da base (ele só grava campos e valores das listas).",
              file=sys.stderr)
        return 1
    print("OK: os JSON publicados só têm campos da lista branca (e valores das listas fechadas).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
