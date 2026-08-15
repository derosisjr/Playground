#!/usr/bin/env python3
"""
Envio de e-mail via Gmail API (HTTPS) — módulo comum
====================================================

Consolidação (2026-08): o fallback nasceu no `diario-oficial/monitor.py` — o
ambiente da rotina /schedule não abre TCP cru na porta 587 (só HTTPS via proxy;
constatado 2026-07-13, Errno 97) — e passou a ser usado também pelo briefing da
Ordem do Dia (`ordem-do-dia/email_briefing.py`).

Token: `GOOGLE_OAUTH_TOKEN` (JSON no env) ou um `token.json` em disco (caminho
passado pelo chamador). Exige o escopo `gmail.send` — regenerar com
`respostas-executivo/setup_oauth.py` se faltar. O remetente efetivo passa a ser
a conta do token, não o header From.
"""

import base64
import json
import os
import sys


def enviar_gmail_api(msg, destinatarios: list[str], token_file: str | None = None) -> None:
    """Envia a mensagem MIME pela Gmail API (HTTPS). Remetente = conta do token."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    raw_token = os.environ.get("GOOGLE_OAUTH_TOKEN")
    if raw_token:
        info = json.loads(raw_token)
    elif token_file and os.path.exists(token_file):
        with open(token_file, encoding="utf-8") as f:
            info = json.load(f)
    else:
        raise EnvironmentError("Sem GOOGLE_OAUTH_TOKEN para o fallback Gmail API.")
    escopos = info.get("scopes", [])
    if "https://www.googleapis.com/auth/gmail.send" not in escopos:
        raise EnvironmentError(
            "Token OAuth sem o escopo gmail.send — regenerar com setup_oauth.py "
            "(respostas-executivo) e atualizar o token na rotina/secret.")
    creds = Credentials.from_authorized_user_info(info, escopos)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    corpo = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")}
    gmail.users().messages().send(userId="me", body=corpo).execute(num_retries=4)
    print(f"E-mail enviado via Gmail API para {', '.join(destinatarios)}.", file=sys.stderr)
