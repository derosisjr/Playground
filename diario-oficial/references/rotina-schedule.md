# Rotina /schedule — Monitor do DOM com IA

> Prompt e checklist de configuração da rotina em nuvem (Claude Code no plano Max).
> A rotina NÃO lê os secrets do GitHub Actions — configurar o env dela à parte.

## Prompt da rotina (colar ao criar via /schedule)

```
Analise a edição de hoje do Diário Oficial de Santos e publique os atos na planilha.

1. Instale as dependências: pip install -r diario-oficial/requirements.txt
2. Para cada dia útil dos últimos 3 dias (cobre atrasos; a dedup evita repetição):
   a. Gere o MD: python diario-oficial/dom_md.py --data AAAA-MM-DD --out /tmp/ed-AAAA-MM-DD.md
      (se o script disser que a edição não existe, pule o dia — sábado/domingo não têm edição)
   b. Leia o MD por inteiro e aplique a skill dom-santos (.claude/skills/dom-santos/SKILL.md):
      classifique TODOS os atos das categorias-alvo, avalie o risco pelos gatilhos de
      diario-oficial/references/criterios-risco.md e grave o JSON no contrato da skill
      em /tmp/atos-AAAA-MM-DD.json
   c. Confira: python diario-oficial/publicar.py /tmp/atos-AAAA-MM-DD.json --dry-run
   d. Publique: python diario-oficial/publicar.py /tmp/atos-AAAA-MM-DD.json
      (dedup pela planilha; insere no topo; envia o e-mail sozinho se houver ato novo)
3. Não commite nada no repositório. Não edite linhas existentes da planilha.
4. Ao final, resuma: edições processadas, atos novos por nível (🔴/🟡/🟢).
```

## Checklist de configuração (uma vez, na UI da rotina)

- **Repo:** derosisjr/Playground, branch master.
- **Cron:** dias úteis de manhã (equivalente ao workflow: seg–sex ~00:17 BRT).
- **Variáveis de ambiente** (mesmos valores dos secrets do Actions — reentrar aqui):
  - `GOOGLE_OAUTH_TOKEN` (JSON do token OAuth, escopo Sheets)
  - `DOM_SHEET_ID` = `1x7W2heNjMh8NQimyWbkjq2Bp59C1qGa3dXg2aPP7a_w` (planilha oficial — decisão
    2026-07-13; a aba "Atos do DOM" foi recriada no formato da skill e a antiga preservada como
    "Atos do DOM (formato antigo)")
  - `GMAIL_USER`, `GMAIL_APP_PASSWORD`
  - `DOM_BRIEFING_TO` (na validação, apontar para o seu e-mail)
- **Rede:** modo Custom com "Also include default list" marcado + domínios extras:
  ```
  diariooficial.santos.sp.gov.br
  smtp.gmail.com
  ```
  (confirmado na 1ª execução, 2026-07-13: o default NÃO libera HTTPS público qualquer —
  o proxy devolveu 403 para o DOM; `*.googleapis.com` passa no default).
- **E-mail:** o ambiente da rotina NÃO abre SMTP (porta 587; Errno 97 mesmo com
  `smtp.gmail.com` na allowlist — só HTTPS via proxy). O `monitor.enviar_email` cai
  automaticamente para a **Gmail API (HTTPS)**, que exige o escopo `gmail.send` no
  `GOOGLE_OAUTH_TOKEN` (regenerar com `respostas-executivo/setup_oauth.py`; o remetente
  passa a ser a conta do token, não `GMAIL_USER`).
- ⚠️ As variáveis ficam **visíveis em texto** para quem edita o ambiente (sem cofre ainda).

## Validação

O ciclo de escrita já foi validado localmente (2026-07-13): inserção no topo, dedup na
reexecução (0 novos) e UTF-8/hyperlink corretos na aba nova.

1. Disparo manual da rotina numa edição conhecida → conferir a aba "Atos do DOM" + e-mail
   (na 1ª rodada, apontar `DOM_BRIEFING_TO` para o seu e-mail).
2. Disparar de novo a MESMA edição → nenhuma linha nova (idempotência pela planilha).
3. Comparar a captura da IA com a aba "(formato antigo)" nas mesmas edições.
4. Estável → desativar o cron do workflow legado (`diario-oficial.yml`).
