# Rotina /schedule — Briefing da Ordem do Dia com IA

> Prompt e checklist de configuração da rotina em nuvem (Claude Code no plano Max).
> A rotina NÃO lê os secrets do GitHub Actions — configurar o env dela à parte.
> Molde: `diario-oficial/references/rotina-schedule.md` (as descobertas de rede/e-mail
> de 2026-07-13 valem aqui também).

## Prompt da rotina (colar ao criar via /schedule)

```
Gere o briefing da sessão mais recente da Câmara de Santos e envie por e-mail.

1. Instale as dependências: pip install -r ordem-do-dia/requirements.txt
2. Gere o MD da pauta:
   python ordem-do-dia/pauta_md.py --out /tmp/pauta.md --anexos-dir /tmp/anexos
   (se o script disser que não há sessão nova ou a pauta está vazia, encerre sem enviar nada)
3. Aplique a skill briefing-ordem-do-dia (.claude/skills/briefing-ordem-do-dia/SKILL.md):
   triagem por risco, análise item a item dos consequentes com os roteiros por tipo de
   matéria, cola de plenário e passe de verificação. Saída: /tmp/briefing.md
4. Envie o e-mail (use o nome da sessão e o nº de itens do front-matter de /tmp/pauta.md):
   python ordem-do-dia/enviar.py --md /tmp/briefing.md --sessao "<nome>" --itens <n>
5. Não commite nada no repositório.
6. Ao final, resuma: sessão, itens consequentes × triviais, recomendações contrárias,
   vícios jurídicos apontados.
```

## Checklist de configuração (uma vez, na UI da rotina)

- **Repo:** derosisjr/Playground, branch master.
- **Cron:** segunda e quarta ~19h BRT (equivalente ao workflow legado: `0 22 * * 1,3` UTC).
- **Modelo:** o mais potente disponível (Opus 5) — conferir se a UI da rotina permite fixar;
  a qualidade da análise jurídica depende disso.
- **Variáveis de ambiente** (reentrar aqui — a rotina não lê secrets do Actions):
  - `GOOGLE_OAUTH_TOKEN` (JSON do token OAuth com o escopo **gmail.send**;
    regenerar com `respostas-executivo/setup_oauth.py` se faltar)
  - `GMAIL_USER` (remetente nominal; o remetente efetivo via Gmail API é a conta do token)
  - `GMAIL_TO` (destinatários, separados por vírgula — na validação, apontar para o seu)
- **Rede:** modo Custom com "Also include default list" marcado + domínio extra:
  ```
  administrativo.camarasantos.sp.gov.br
  ```
  (o default NÃO libera HTTPS público qualquer — no DOM o proxy devolveu 403;
  `*.googleapis.com` passa no default.)
- **E-mail:** o ambiente da rotina NÃO abre SMTP (porta 587) — o `enviar.py` cai
  automaticamente para a **Gmail API (HTTPS)**, que exige o escopo `gmail.send` no
  `GOOGLE_OAUTH_TOKEN`. Sem `GMAIL_APP_PASSWORD` no env, vai direto pela API (esperado).
- ⚠️ As variáveis ficam **visíveis em texto** para quem edita o ambiente (sem cofre ainda).
- 🔒 O briefing contém posicionamento de voto e o repositório é público — **nunca**
  gravar briefing/pauta no repo (o prompt da rotina já proíbe commit). A única saída
  é o e-mail.

## Validação

1. Disparo manual da rotina numa sessão conhecida, com `GMAIL_TO` apontando para o seu
   e-mail → conferir: cola de plenário no topo, triagem plausível, artigos citados
   conferíveis nos textos de referência.
2. Comparar com o último briefing do caminho legado (qualidade, tamanho, ausência de
   fabricação — o "Histórico Legislativo" do formato antigo não existe mais).
3. Estável → comentar o bloco `schedule:` do workflow legado (`ordem-do-dia.yml`),
   mantendo `workflow_dispatch` + `ANTHROPIC_API_KEY` como socorro manual.
