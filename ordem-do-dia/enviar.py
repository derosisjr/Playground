#!/usr/bin/env python3
"""
Envio do briefing — CLI da rotina /schedule
===========================================

Recebe o briefing.md gerado pela skill `briefing-ordem-do-dia` e o envia por
e-mail HTML (SMTP com fallback Gmail API — ver email_briefing.py). Determinístico,
sem IA: a rotina chama depois de gravar /tmp/briefing.md.

Uso:
    python ordem-do-dia/enviar.py --md /tmp/briefing.md --sessao "129ª Sessão Ordinária" --itens 14
    python ordem-do-dia/enviar.py --md /tmp/briefing.md --sessao "..." --itens 14 --dry-run  # imprime o HTML

Variáveis de ambiente: GMAIL_USER, GMAIL_TO (e GMAIL_APP_PASSWORD para SMTP;
sem ela, vai direto pela Gmail API via GOOGLE_OAUTH_TOKEN com escopo gmail.send).
"""

import argparse
import sys
from datetime import datetime

from email_briefing import enviar_email, montar_email_html

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def main():
    p = argparse.ArgumentParser(description="Envia o briefing da Ordem do Dia por e-mail")
    p.add_argument("--md", required=True, help="Arquivo markdown do briefing (gerado pela skill).")
    p.add_argument("--sessao", required=True, help="Nome da sessão (ex.: '129ª Sessão Ordinária').")
    p.add_argument("--itens", required=True, type=int, help="Número de itens da pauta.")
    p.add_argument("--dry-run", action="store_true",
                   help="Não envia: imprime o HTML montado no stdout.")
    args = p.parse_args()

    with open(args.md, encoding="utf-8") as f:
        corpo_md = f.read().strip()
    if not corpo_md:
        print(f"Arquivo vazio: {args.md} — nada a enviar.", file=sys.stderr)
        sys.exit(1)

    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
    if args.dry_run:
        print(montar_email_html(args.sessao, args.itens, corpo_md, agora))
        print(f"[dry-run] HTML montado ({len(corpo_md)} chars de markdown); nada enviado.",
              file=sys.stderr)
        return

    assunto = f"📋 Briefing {args.sessao}"
    enviar_email(assunto, corpo_md, args.sessao, args.itens, agora)


if __name__ == "__main__":
    main()
