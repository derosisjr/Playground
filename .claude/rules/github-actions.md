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
| `RESPOSTAS_EMAIL_TO` | Destinatário(s) do resumo de respostas do Executivo — assessores (fallback de `DOM_BRIEFING_TO`/`DESPESAS_BRIEFING_TO`; cai em `GMAIL_TO`) |

# Padrões dos workflows

Os workflows de base (`despesas`, `legis`, `proposituras`, `respostas-executivo`,
`indicadores`, `endividamento`, `benchmark-despesas`, `precos` — este com irmão
`precos-backfill` de disparo manual) commitam pela composite action
**`.github/actions/commitar`** (entradas `caminhos`, `mensagem`, `sem-mudancas`, `com-data`), que
faz `git add`/`commit` e, antes do `push`, **`git pull --rebase --autostash` com 3 tentativas**.
Usam `actions/checkout@v5` **sem `fetch-depth`** (histórico raso, 1 commit — o pull traz só o que
falta). Não há `concurrency:` geral: os workflows tocam arquivos distintos e o rebase resolve a
corrida; a exceção é o par `precos`/`precos-backfill`, que escreve o mesmo `precos/espelho` e por
isso divide o grupo `concurrency: precos-espelho`. Não há workflow com gatilho `on: push`, por isso
ninguém precisa de `[skip ci]`.

Consequências a respeitar ao mexer neles:
- **Nunca fazer dois workflows escreverem o mesmo arquivo** (fora do par serializado acima). Os
  crons se sobrepõem (segunda: legis 07:17, proposituras 07:37, despesas 07:41, respostas 08:31
  UTC; domingo: precos 10:07 por até 3 h, atravessando o `bases-atualizacao` das 12:00) e cada um
  leva dezenas de minutos. Até 2026-09 não havia rebase e o push perdedor era rejeitado ("fetch
  first"): num cron diário custava um dia; no semanal de Preços custou **4 semanas seguidas**
  (17/08–06/09, base congelada em 10/08). Com o rebase a corrida é inofensiva **porque os arquivos
  são distintos**; um arquivo compartilhado vira conflito de rebase e a action falha de propósito
  (nunca `--force`).
- **Todo índice é gravado de forma atômica** por `comum/escrita.py` (`gravar_json`/`gravar_bytes`:
  temporário `.tmp-*` na mesma pasta + `os.replace`; `.tmp-*` está no `.gitignore`). Motivo: o
  timeout de passo corta o processo no meio (Preços faz isso de propósito) e um `open(..., "w")`
  interrompido deixaria arquivo truncado que o `if: always()` commitaria. `gravar_json_se_mudou`
  ignora `atualizado_em` para os dossiês de favorecidos e a árvore não virarem diff diário sem
  dado novo (eram 290 arquivos/dia).
- **Quem precisa de `git log` precisa de `fetch-depth: 0` explícito.** É o caso de
  `bases-atualizacao.yml` (cron 12:00 UTC, fora do bloco 04:00–08:30), que gera
  `bases-atualizacao.json` com a data real de cada base — ver `.claude/rules/site-frontend.md`.
- O Pages publica **direto do branch `master`, raiz** (não há workflow de deploy), então qualquer
  arquivo commitado na raiz é servido assim que o commit chega.
- **Guarda que aborta o commit sai com `exit 1`, nunca `exit 0`.** Com `exit 0` o job fica verde e
  a base para em silêncio — foi assim que Proposituras ficou 2 meses congelada sem ninguém notar
  (ver `.claude/rules/proposituras.md`). Corrigido em despesas, endividamento, indicadores,
  proposituras e respostas-executivo em 2026-08; legis ganhou guarda de volume (≥ 3.000) e o
  crawler passou a sair 1 quando toda chamada falha, em 2026-09.
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
