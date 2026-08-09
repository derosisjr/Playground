---
paths:
  - ".github/**"
---

# Secrets do GitHub Actions

| Secret | Descrição |
|---|---|
| `ANTHROPIC_API_KEY` | API do Claude (ordem-do-dia) |
| `GMAIL_USER` | Conta Gmail remetente (ordem-do-dia) |
| `GMAIL_APP_PASSWORD` | App Password de 16 dígitos (ordem-do-dia) |
| `GMAIL_TO` | Destinatário(s) do briefing (ordem-do-dia; fallback do briefing de despesas) |
| `DESPESAS_BRIEFING_TO` | Destinatário(s) do briefing semanal de despesas — assessores (opcional; cai em `GMAIL_TO`) |
| `GOOGLE_OAUTH_TOKEN` | JSON do token OAuth Drive+Sheets, gerado por `setup_oauth.py` (respostas-executivo) |
| `SHEET_ID` | ID da planilha de controle (respostas-executivo) |
| `DRIVE_FOLDER_ID` | ID da pasta-raiz no Drive (respostas-executivo) |
| `DOM_SHEET_ID` | ID da planilha dedicada do Monitor do Diário Oficial (reusa `GOOGLE_OAUTH_TOKEN`) |
| `DOM_BRIEFING_TO` | Destinatário(s) do e-mail diário do DOM — assessores (opcional; cai em `DESPESAS_BRIEFING_TO`) |

# Padrões dos workflows

Os 7 workflows de base (`despesas`, `legis`, `proposituras`, `respostas-executivo`,
`indicadores`, `endividamento`, `benchmark-despesas`) repetem o mesmo bloco manual de
`git add`/`commit`/`push` (sem `git-auto-commit-action`), usam `actions/checkout@v5` **sem
`fetch-depth`** (portanto histórico raso, 1 commit) e **não têm `concurrency:` nem `pull` antes do
push**. Não há workflow com gatilho `on: push`, por isso ninguém precisa de `[skip ci]`.

Consequências a respeitar ao mexer neles:
- **Nunca fazer dois workflows escreverem o mesmo arquivo.** Os crons são escalonados no minuto,
  mas na segunda-feira quatro rodam em sequência apertada (legis 07:17, proposituras 07:37,
  despesas 07:41, respostas 08:31 UTC) e cada um pode levar dezenas de minutos. Hoje as colisões
  são inofensivas porque tocam arquivos distintos — o push perdedor só falha e refaz no dia
  seguinte. Um arquivo compartilhado transformaria isso em perda de dados.
- **Quem precisa de `git log` precisa de `fetch-depth: 0` explícito.** É o caso de
  `bases-atualizacao.yml` (cron 12:00 UTC, fora do bloco 04:00–08:30), que gera
  `bases-atualizacao.json` com a data real de cada base — ver `.claude/rules/site-frontend.md`.
- O Pages publica **direto do branch `master`, raiz** (não há workflow de deploy), então qualquer
  arquivo commitado na raiz é servido assim que o commit chega.
- **Guarda que aborta o commit sai com `exit 1`, nunca `exit 0`.** Com `exit 0` o job fica verde e
  a base para em silêncio — foi assim que Proposituras ficou 2 meses congelada sem ninguém notar
  (ver `.claude/rules/proposituras.md`). Corrigido em despesas, endividamento, indicadores,
  proposituras e respostas-executivo em 2026-08.
- **`.sqlite` em cache do Actions só é seguro se o crawl reconstruir o histórico sozinho.** O
  GitHub apaga cache sem acesso há 7 dias; cron semanal fica na corda bamba. Antes de mexer,
  conferir as duas propriedades juntas: *banco fora do git?* e *crawl limitado a um ano?* Se sim e
  sim, um despejo de cache congela a base para sempre. Hoje: despesas/endividamento/indicadores
  chamam o crawler sem `--ano` (autocuram), legis versiona o `.sqlite`, e proposituras ganhou um
  passo explícito de recarga quando o banco vem parcial.

# Comandos úteis

```bash
# Disparar workflow no GitHub
gh workflow run "Briefing Ordem do Dia" --repo derosisjr/Playground
```
