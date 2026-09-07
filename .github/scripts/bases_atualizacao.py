#!/usr/bin/env python3
"""Gera `bases-atualizacao.json`: quando cada base mudou de verdade.

Por que existe: o hub mostra "atualizado há N dias" em cada cartão. Quando o JSON
da base carrega data própria (`atualizado_em`/`gerado_em`) tudo bem, mas os índices
em formato de array (proposituras, legis, requerimentos, regimento) não têm onde
guardar isso, e o hub caía no cabeçalho `Last-Modified`. No GitHub Pages esse
cabeçalho é a **hora do deploy**, idêntica para todos os arquivos — então bases
paradas há dois meses anunciavam "atualizado hoje".

A data real é a do último commit que tocou o arquivo. Este script a extrai do git.

ATENÇÃO: exige histórico completo. O `actions/checkout` usa `fetch-depth: 1` por
padrão, e aí `git log` enxerga um commit só; o workflow precisa de `fetch-depth: 0`.

Uso:
    python .github/scripts/bases_atualizacao.py            # grava na raiz do repo
    python .github/scripts/bases_atualizacao.py --dry-run  # imprime, não grava
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SAIDA = RAIZ / "bases-atualizacao.json"
if str(RAIZ) not in sys.path:
    sys.path.append(str(RAIZ))  # camada comum do repo (comum/)
from comum.escrita import gravar_texto  # noqa: E402

# padrões de arquivo cuja data de alteração o hub exibe
PADROES = ["*-index.json", "consulta/consultas/*.json"]


def alvos():
    """Caminhos relativos à raiz, ordenados, sem duplicatas."""
    achados = set()
    for p in PADROES:
        achados.update(a.relative_to(RAIZ).as_posix()
                       for a in RAIZ.glob(p) if a.is_file())
    return sorted(achados)


def data_do_commit(rel):
    """ISO-8601 UTC do último commit que tocou o arquivo; None se desconhecido."""
    try:
        r = subprocess.run(
            ["git", "-C", str(RAIZ), "log", "-1", "--format=%aI", "--", rel],
            capture_output=True, text=True, check=True, timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        print(f"  aviso: git log falhou em {rel}: {e}", file=sys.stderr)
        return None
    bruto = r.stdout.strip()
    if not bruto:
        # arquivo não versionado, ou histórico raso (fetch-depth: 1)
        return None
    return datetime.fromisoformat(bruto).astimezone(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _ler_json(rel):
    with open(RAIZ / rel, encoding="utf-8") as f:
        return json.load(f)


def contagens():
    """Contagens que o hub exibia lendo os índices INTEIROS só para um `d.length`:
    proposituras 4,9 MB, legis 1,3 MB, regimento 0,4 MB, requerimentos 0,25 MB —
    ~0,85 MB gzip por visita nova, mais o parse na main thread. Aqui custam um
    json.load no CI; no hub, poucas centenas de bytes. Chave = nome do arquivo
    (como em `bases`). Falha em um índice só tira a chave dele: o hub cai no fetch."""
    out = {}
    try:
        out["proposituras-index.json"] = {"n": len(_ler_json("proposituras-index.json"))}
    except (OSError, ValueError) as e:
        print(f"  aviso: contagem de proposituras falhou: {e}", file=sys.stderr)
    try:
        normas = _ler_json("legis-index.json")
        leis = [n for n in normas if str(n.get("tipo", "")).lower().startswith("lei")]

        def chave(n):  # mesma regra que o hub usava: ano, depois o número só com dígitos
            digitos = "".join(ch for ch in str(n.get("numero", "")) if ch.isdigit())
            return (n.get("ano") or 0, int(digitos) if digitos else 0)
        ult = max(leis, key=chave) if leis else None
        out["legis-index.json"] = {"n": len(normas)}
        if ult:
            out["legis-index.json"]["ultima_lei"] = {"numero": ult.get("numero"), "ano": ult.get("ano")}
    except (OSError, ValueError) as e:
        print(f"  aviso: contagem de legis falhou: {e}", file=sys.stderr)
    try:
        out["regimento-index.json"] = {"n": len(_ler_json("regimento-index.json"))}
    except (OSError, ValueError) as e:
        print(f"  aviso: contagem do regimento falhou: {e}", file=sys.stderr)
    try:
        reqs = _ler_json("requerimentos-index.json")
        out["requerimentos-index.json"] = {
            "n": len(reqs), "respondidos": sum(1 for r in reqs if r.get("respondido"))}
    except (OSError, ValueError) as e:
        print(f"  aviso: contagem de requerimentos falhou: {e}", file=sys.stderr)
    return out


def montar():
    bases, sem_data = {}, []
    for rel in alvos():
        dt = data_do_commit(rel)
        if dt:
            bases[rel] = dt
        else:
            sem_data.append(rel)
    return bases, sem_data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="imprime sem gravar")
    args = ap.parse_args()

    bases, sem_data = montar()
    if not bases:
        # histórico raso ou repo sem git: não publicar arquivo vazio, que faria
        # o hub esconder o frescor de todos os cartões
        print("ABORTANDO: nenhuma data obtida (histórico raso? falta fetch-depth: 0)",
              file=sys.stderr)
        return 1

    doc = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds")
                             .replace("+00:00", "Z"),
        "bases": bases,
        "contagens": contagens(),
    }
    texto = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"

    for rel, dt in bases.items():
        print(f"  {rel:34} {dt}")
    for rel, c in doc["contagens"].items():
        print(f"  {rel:34} {c}")
    for rel in sem_data:
        print(f"  {rel:34} (sem data — ignorado)")

    if args.dry_run:
        print(f"\n--dry-run: {len(texto)} bytes NÃO gravados em {SAIDA.name}")
        return 0

    gravar_texto(SAIDA, texto)
    print(f"\ngravado {SAIDA.name} ({len(texto)} bytes, {len(bases)} bases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
