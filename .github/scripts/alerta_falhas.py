#!/usr/bin/env python3
"""Abre (ou atualiza) uma issue por workflow que falhou nas últimas horas.

Nenhum workflow avisava quando falhava: o Briefing passou 16 execuções vermelho
(ago–out/2026), Respostas parou de publicar em 09/10 e Preços perdeu uma coleta
inteira em 11/10 sem que ninguém soubesse. A issue gera notificação por e-mail
para quem acompanha o repo.

Uma issue aberta por workflow, título fixo "[falha] <nome>": falhas seguintes
viram comentário na mesma issue; fechar a issue (depois de corrigir) zera o ciclo.
Runs já citadas na issue não são repetidas, então rodar duas vezes não duplica.

Só stdlib + `gh` (já instalado no runner). Variáveis: GH_TOKEN, GITHUB_REPOSITORY,
JANELA_HORAS (padrão 25). Com `--dry-run` só imprime o que faria.
"""

import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

IGNORAR = {"pages build and deployment", "pages-build-deployment", "Alerta de falhas"}
CONCLUSOES = {"failure", "timed_out", "startup_failure", "cancelled"}
PREFIXO = "[falha] "


def gh(*args) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def main() -> int:
    seco = "--dry-run" in sys.argv
    repo = os.environ["GITHUB_REPOSITORY"]
    horas = int(os.environ.get("JANELA_HORAS") or 25)
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = json.loads(gh("run", "list", "--repo", repo, "--limit", "200",
                         "--created", f">={desde}",
                         "--json", "workflowName,conclusion,url,createdAt,event,displayTitle"))
    falhas = defaultdict(list)
    for r in runs:
        if r["workflowName"] in IGNORAR or r.get("conclusion") not in CONCLUSOES:
            continue
        falhas[r["workflowName"]].append(r)
    if not falhas:
        print(f"Nenhuma falha desde {desde}.")
        return 0

    abertas = json.loads(gh("issue", "list", "--repo", repo, "--state", "open", "--limit", "100",
                            "--search", f'"{PREFIXO.strip()}" in:title',
                            "--json", "number,title,body,comments"))
    por_titulo = {i["title"]: i for i in abertas}

    for nome, lista in sorted(falhas.items()):
        titulo = f"{PREFIXO}{nome}"
        issue = por_titulo.get(titulo)
        ja_citadas = ""
        if issue:
            ja_citadas = (issue.get("body") or "") + "".join(c.get("body") or "" for c in issue.get("comments") or [])
        novas = [r for r in sorted(lista, key=lambda r: r["createdAt"]) if r["url"] not in ja_citadas]
        if not novas:
            print(f"{nome}: falhas já registradas na issue #{issue['number']}.")
            continue
        linhas = "\n".join(f"- {r['createdAt'][:16].replace('T', ' ')} UTC · {r['conclusion']} · "
                           f"{r['event']} · {r['url']}" for r in novas)
        if seco:
            destino = f"comentário em #{issue['number']}" if issue else "issue nova"
            print(f"[dry-run] {titulo} ({destino}):\n{linhas}")
        elif issue:
            gh("issue", "comment", str(issue["number"]), "--repo", repo,
               "--body", f"Nova(s) falha(s):\n\n{linhas}")
            print(f"{nome}: comentário na issue #{issue['number']} ({len(novas)} run(s)).")
        else:
            corpo = (f"O workflow **{nome}** falhou:\n\n{linhas}\n\n"
                     "Abra o log da run, corrija a causa e feche esta issue. Enquanto ela estiver "
                     "aberta, falhas novas do mesmo workflow entram como comentário aqui.")
            url = gh("issue", "create", "--repo", repo, "--title", titulo, "--body", corpo).strip()
            print(f"{nome}: issue criada — {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
