---
paths:
  - "ordem-do-dia/**"
---

# Briefing Ordem do Dia (`ordem-do-dia/`)

Briefing político-jurídico da pauta das sessões da Câmara de Santos, por e-mail HTML,
antes de cada sessão (segunda e quarta ~19h BRT).

## Pipeline NOVO — rotina /schedule com IA (2026-08, em validação)

Mesma migração do Monitor do DOM: a inteligência sai do Python (API paga) e vai para uma
**skill executada por rotina Claude Code em nuvem** (cota Max, sem API key). O Python fica
com o determinístico:

```
pauta_md.py (scraping+PDF→MD) → skill briefing-ordem-do-dia (MD→briefing.md)
    → enviar.py (e-mail HTML)
```

- **`coleta.py`** — scraping da pauta + download/extração de PDFs (extraído do `index.py`;
  usado pelos dois caminhos). Com `dir_anexos`, PDF escaneado vai para disco (o agente lê
  com Read); sem, vira base64 (caminho legado/API-OCR).
- **`pauta_md.py`** — pauta → um Markdown com front-matter, `## N. <título>` por item e
  anexos inline (`### DOCUMENTO ANEXO: ...`) ou referenciados (`> ANEXO ESCANEADO ...`).
  Saída em arquivo temporário — **não versionar dados**.
- **`.claude/skills/briefing-ordem-do-dia/SKILL.md`** — triagem consequente×trivial
  (profundidade proporcional ao risco), análise item a item com **roteiros por tipo de
  matéria** (`references/roteiros/`: veto, criação de despesa, crédito adicional, obrigação
  ao setor privado, honorífico, genérico), ordem de leitura anti-ancoragem (projeto ANTES
  dos pareceres; em veto, ignora o parecer da CCJ), advogado do diabo interno, **cola de
  plenário** (1 página imprimível no topo do e-mail) e **passe de verificação** final.
  Regra de ouro: verdade antes de completude — fato carrega origem; sem fonte, [Verificar].
- **Prompt = fonte única**: `references/briefing-system-prompt.md` (com marcadores
  `[[PERFIL_DO_VEREADOR]]` ← `.claude/rules/perfil-politico.md` e `[[COMPOSICAO_DA_CAMARA]]`
  ← `references/composicao-camara.md`), lido em runtime pelo `index.py` legado e pela skill.
  A composição da legislatura atualiza-se em `composicao-camara.md` sem tocar no prompt.
- **`references/lei-organica-santos.md`** — texto da Lei Orgânica (baixado do Legis/egov,
  camada de texto, sem OCR): a análise jurídica só cita artigo **conferido** ali (ou no
  `regimento-index.json`); senão, [Verificar].
- **`enviar.py`/`email_briefing.py`** — e-mail HTML (template movido do `index.py`); SMTP
  com fallback **Gmail API** via `gmail_api.py` (raiz — módulo comum com o monitor do DOM;
  o ambiente das rotinas não abre a porta 587).
- **Config da rotina**: `references/rotina-schedule.md` (prompt literal + checklist:
  allowlist `administrativo.camarasantos.sp.gov.br`, token com gmail.send,
  `GMAIL_USER`, `GMAIL_TO`; modelo Opus 5).
- 🔒 Repo é público e o briefing traz posicionamento de voto: **nunca** commitar
  briefing/pauta — o e-mail é a única saída (planilha de acompanhamento foi avaliada
  e removida por decisão de 2026-08-10).

```bash
python ordem-do-dia/pauta_md.py --sessao 1287 --out /tmp/p.md --anexos-dir /tmp/anexos
python ordem-do-dia/enviar.py --md /tmp/briefing.md --sessao "129ª Sessão" --itens 14 --dry-run
```

## Caminho legado (fallback manual, via API)

`index.py` — scraping (via `coleta.py`) + chamada única à Claude API
(`claude-sonnet-4-6`, streaming, `max_tokens=32000`, prompt caching, retry em 429,
continuação automática) + e-mail (via `email_briefing.py`). Precisa de
`ANTHROPIC_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `GMAIL_TO`.

- **Fonte de dados:** `https://administrativo.camarasantos.sp.gov.br/dispositivo/ideCustom/legislativo/ordem_dia_eletronica/publico/`
  (sessões no `<select id="selSessao">`; itens em `listagem.php?codigo=SESSION_ID`, divs `.documento`).
- **Agendamento:** `.github/workflows/ordem-do-dia.yml`, cron `0 22 * * 1,3` (19h BRT,
  seg e qua) enquanto a rotina está em validação; depois de estável, o cron é comentado e
  fica só o `workflow_dispatch` (mesmo padrão do `diario-oficial.yml`).

```bash
python ordem-do-dia/index.py                  # sessão mais recente (stdout)
python ordem-do-dia/index.py --sessao 1278 --output briefing.md
```
