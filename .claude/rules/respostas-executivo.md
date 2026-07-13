---
paths:
  - "respostas-executivo/**"
  - "requerimentos.html"
  - "requerimentos-app.js"
---

# Respostas do Executivo (`respostas-executivo/index.py`)

Automação que varre a busca pública de "Respostas do Executivo" endereçadas ao vereador
(sem e-mail), baixa os PDFs do pedido original e da resposta do prefeito, organiza-os no
Google Drive (uma subpasta por item) e registra cada item numa planilha de controle.

## Arquitetura da Automação

- **Fonte de dados:** `busca_documento_pub/filtro_resultado.php?pesquisa_resposta_executivo[ano]=AAAA&pesquisa_resposta_executivo[autor]=282` (paginada via `&limite=N`, 20/página). Páginas em ISO-8859-1. **As respostas ficam arquivadas no ano de ENVIO da propositura**, não no ano da resposta — por isso a rotina varre, por padrão, **de 2025 (`ANO_INICIAL`, 1º ano do mandato) até o ano corrente** (`--ano` aceita lista, ex.: `2025,2026`).
- **Página canônica:** o link "Mais detalhes" de cada resultado aponta para `detalhes.php?cod=...` do pedido original — contém tipo, número, processo, data, ementa, PDF do pedido e a seção "Resposta anexada" com os PDFs do prefeito.
- **Arquivamento:** Google Drive via OAuth do próprio usuário (`google-api-python-client`), uma subpasta por item (`Tipo Número`). Token gerado por `setup_oauth.py` (1x); lido de `token.json` (local) ou do secret `GOOGLE_OAUTH_TOKEN` (CI).
- **Registro:** Google Sheets; duas abas (`indicações`/`requerimentos`), roteamento por tipo. Para cada item localiza a linha existente pelo número e **atualiza** as colunas `Resposta` (hyperlink para a subpasta do Drive) e `Data da resposta`; se o número não existir, **anexa** linha nova; se a resposta já estiver preenchida, **pula** (ver `ABAS`/`carregar_planilha` em `index.py`). Pastas no Drive: `REQUERIMENTO_<nº>` / `INDICACAO_<nº>`.
- **Log diário:** aba `Log diário` (criada automaticamente) recebe uma linha por resposta processada (data, tipo, número, assunto, data da resposta, link). Com `--email`, envia também um resumo HTML via Gmail SMTP (secrets `GMAIL_*`) — só quando há novidades.
- **Agendamento:** GitHub Actions (`.github/workflows/respostas-executivo.yml`), cron `0 9 * * 1-5` (06h BRT, dias úteis).
- **Painel de Requerimentos & Respostas (`requerimentos.html` + `requerimentos-app.js`):** 4º cartão do hub. `respostas-executivo/export.py` lê a aba `requerimentos` da planilha (via Sheets API, reusando `_google_services`/`_idx_header` de `index.py`) e gera `requerimentos-index.json` na raiz — array com número, ano, assunto, datas, situação, `respondido` e `url_resposta`. **A coluna `Resposta` é uma fórmula `=HYPERLINK(...)`**, então o export lê com `valueRenderOption="FORMULA"` e extrai a URL do Drive por regex. O painel (vanilla, sem acento, paginado) tem busca + filtros de ano/situação e link para a pasta no Drive (exige login do gabinete) ou badge "Pendente". O JSON é gerado e commitado pelo passo final do `respostas-executivo.yml` (com guarda anti-base-vazia). `--dry-run` no export imprime contagens sem gravar.

## Comandos úteis

```bash
# Respostas do Executivo — testar scraping sem escrever (Drive/Sheets)
python respostas-executivo/index.py --dry-run --limite 3

# Respostas do Executivo — rodar de verdade (ano corrente)
python respostas-executivo/index.py

# Respostas do Executivo — ano específico
python respostas-executivo/index.py --ano 2026
```
