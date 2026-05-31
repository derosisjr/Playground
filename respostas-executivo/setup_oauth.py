#!/usr/bin/env python3
"""
Setup OAuth — Respostas do Executivo
=====================================

Gera o token OAuth (token.json) que permite ao index.py acessar o seu Google
Drive e a sua Planilha *como você* (sem conta de serviço, sem problema de cota,
sem e-mail). Rode UMA única vez.

Pré-requisito — criar um OAuth Client (grátis):
  1. https://console.cloud.google.com → crie/selecione um projeto.
  2. APIs e Serviços → Biblioteca → habilite "Google Drive API" e "Google Sheets API".
  3. APIs e Serviços → Tela de permissão OAuth → tipo "Externo" → preencha o
     mínimo → em "Usuários de teste" adicione o seu próprio e-mail (rrosis@gmail.com).
  4. APIs e Serviços → Credenciais → Criar credenciais → ID do cliente OAuth →
     tipo "App para computador" (Desktop). Baixe o JSON e salve como
     `client_secret.json` nesta pasta (respostas-executivo/).

Uso:
    python respostas-executivo/setup_oauth.py

Abre o navegador para você autorizar. Ao final grava `token.json` nesta pasta e
imprime o conteúdo a ser colado no secret GOOGLE_OAUTH_TOKEN do GitHub Actions.
"""

import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
AQUI = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET = os.path.join(AQUI, "client_secret.json")
TOKEN_FILE = os.path.join(AQUI, "token.json")


def main():
    if not os.path.exists(CLIENT_SECRET):
        print(
            f"Arquivo não encontrado: {CLIENT_SECRET}\n"
            "Baixe o JSON do OAuth Client (tipo 'App para computador') do Google "
            "Cloud e salve como client_secret.json nesta pasta. Veja o cabeçalho "
            "deste script para o passo a passo.",
            file=sys.stderr,
        )
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print(f"\n✅ Token gravado em {TOKEN_FILE}\n")
    print("Para o GitHub Actions, copie TODO o conteúdo abaixo para o secret "
          "GOOGLE_OAUTH_TOKEN:\n")
    print(creds.to_json())


if __name__ == "__main__":
    main()
