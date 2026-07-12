# -*- coding: utf-8 -*-
"""Apuração da consulta pública — Worker/KV → consulta-resultados.json + relatório.

Baixa os contadores do Worker (endpoint autenticado), grava o
consulta-resultados.json (raiz, versionado — a página exibe a fita de
consenso a partir dele), gera relatório .md por consulta e, com --email,
envia o fechamento aos assessores.

Recorte por bairro só entra no relatório quando o bairro tem N >= 30 votos
(não expor grupos pequenos). Sugestões vão ao relatório para moderação
humana — nunca direto para a página.

Requer no ambiente: CONSULTA_WORKER_URL e CONSULTA_ADMIN_TOKEN.
Uso:
  python consulta/apurar.py prioridades-2026 [--email] [--dry-run]
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, "consulta-resultados.json")
N_MINIMO_BAIRRO = 30


def baixar(consulta: str) -> dict:
    url = os.environ.get("CONSULTA_WORKER_URL", "").rstrip("/")
    token = os.environ.get("CONSULTA_ADMIN_TOKEN", "")
    if not url or not token:
        sys.exit("Defina CONSULTA_WORKER_URL e CONSULTA_ADMIN_TOKEN no ambiente.")
    r = requests.get(f"{url}/resultados", params={"consulta": consulta},
                     headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def apurar(bruto: dict) -> dict:
    """Agrega as chaves voto:<consulta>:<proposta>:<voto>:<bairro> → totais."""
    propostas = defaultdict(lambda: {"sim": 0, "nao": 0, "pular": 0})
    por_bairro = defaultdict(lambda: defaultdict(lambda: {"sim": 0, "nao": 0}))
    votos_bairro = defaultdict(int)
    total = 0
    for chave, n in bruto.get("votos", {}).items():
        try:
            _, _, proposta, voto, bairro = chave.split(":", 4)
        except ValueError:
            continue
        propostas[proposta][voto] += n
        if voto in ("sim", "nao"):
            por_bairro[bairro][proposta][voto] += n
            votos_bairro[bairro] += n
            total += n
    bairros_validos = {b: dict(p) for b, p in por_bairro.items()
                       if votos_bairro[b] >= N_MINIMO_BAIRRO}
    return {
        "apurado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_votos": total,
        "propostas": {p: dict(v) for p, v in propostas.items()},
        "por_bairro": bairros_validos,
        "bairros_abaixo_do_minimo": sorted(
            b for b in votos_bairro if b not in bairros_validos),
    }


def relatorio_md(consulta: str, resultado: dict, sugestoes: list[dict],
                 definicao: dict | None) -> str:
    textos = {p["id"]: p["texto"] for p in (definicao or {}).get("propostas", [])}
    linhas = [f"# Apuração — {consulta}", "",
              f"Apurado em {resultado['apurado_em']} · "
              f"{resultado['total_votos']} votos válidos (sim/não)", "",
              "## Propostas (ordenadas por concordância)", ""]
    def pct(v):
        t = v["sim"] + v["nao"]
        return (v["sim"] / t * 100) if t else 0
    for pid, v in sorted(resultado["propostas"].items(),
                         key=lambda kv: -pct(kv[1])):
        t = v["sim"] + v["nao"]
        linhas.append(f"- **{pct(v):.0f}% concordam** ({t} votos, "
                      f"{v.get('pular', 0)} pularam) — {textos.get(pid, pid)}")
    if resultado["por_bairro"]:
        linhas += ["", f"## Recorte por bairro (N ≥ {N_MINIMO_BAIRRO})", ""]
        for b, props in sorted(resultado["por_bairro"].items()):
            linhas.append(f"### {b}")
            for pid, v in props.items():
                t = v["sim"] + v["nao"]
                linhas.append(f"- {pct(v):.0f}% concordam ({t}) — {textos.get(pid, pid)}")
    if sugestoes:
        linhas += ["", f"## Sugestões recebidas ({len(sugestoes)}) — moderar antes de publicar", ""]
        for s in sugestoes:
            linhas.append(f"- [{s.get('bairro')}] {s.get('texto')}")
    return "\n".join(linhas) + "\n"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Apuração da consulta pública")
    ap.add_argument("consulta")
    ap.add_argument("--email", action="store_true", help="envia relatório aos assessores")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bruto = baixar(args.consulta)
    resultado = apurar(bruto)
    caminho_def = os.path.join(RAIZ, "consulta", "consultas", f"{args.consulta}.json")
    definicao = json.load(open(caminho_def, encoding="utf-8")) \
        if os.path.exists(caminho_def) else None
    md = relatorio_md(args.consulta, resultado, bruto.get("sugestoes", []), definicao)
    print(md)
    if args.dry_run:
        print("[dry-run] nada gravado")
        return

    # publica a fita de consenso (sem sugestões — passam por moderação humana)
    atual = {"consultas": {}}
    if os.path.exists(SAIDA):
        atual = json.load(open(SAIDA, encoding="utf-8"))
    atual["consultas"][args.consulta] = {
        k: resultado[k] for k in ("apurado_em", "total_votos", "propostas", "por_bairro")}
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(atual, f, ensure_ascii=False, separators=(",", ":"))
    caminho_md = os.path.join(RAIZ, "consulta", f"_apuracao-{args.consulta}.md")
    with open(caminho_md, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"gravado: {SAIDA} e {caminho_md}")

    if args.email:
        enviar_email(f"Apuração da consulta pública — {args.consulta}", md)
        print("e-mail enviado.")


def enviar_email(assunto: str, corpo_md: str) -> None:
    """SMTP Gmail no padrão do projeto; destinatários com a cadeia de fallback."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    usuario = os.environ.get("GMAIL_USER")
    senha = os.environ.get("GMAIL_APP_PASSWORD")
    para = (os.environ.get("CONSULTA_EMAIL_TO")
            or os.environ.get("DESPESAS_BRIEFING_TO")
            or os.environ.get("RESPOSTAS_EMAIL_TO")
            or os.environ.get("GMAIL_TO"))
    if not all([usuario, senha, para]):
        raise EnvironmentError("Defina GMAIL_USER, GMAIL_APP_PASSWORD e um destinatário.")
    destinatarios = [d.strip() for d in para.split(",")]
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = assunto, usuario, ", ".join(destinatarios)
    msg.attach(MIMEText(corpo_md, "plain", "utf-8"))
    html = "<pre style='font-family:Menlo,Consolas,monospace'>" + (
        corpo_md.replace("&", "&amp;").replace("<", "&lt;")) + "</pre>"
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(usuario, senha)
        s.sendmail(usuario, destinatarios, msg.as_string())


if __name__ == "__main__":
    main()
