# Playground — Ferramentas Parlamentares · Câmara de Santos

## Contexto do Projeto

Ferramentas de suporte ao gabinete de um vereador da Câmara Municipal de Santos (SP).
Stack: HTML/CSS/JS vanilla (frontend) + Python (automações).

## Aplicações

### Radar de Pauta (`index.html` + `app.js`)
Transforma texto de pauta legislativa em briefing político com classificação por prioridade,
tags temáticas e sugestão de discurso para plenário.

### Radar de Gastos (`gastos.html` + `gastos-app.js`)
Dashboard de análise de gastos municipais a partir de CSV exportado da Prefeitura de Santos.
Usa Chart.js para visualizações e PapaParse para leitura de CSV.

### Briefing Ordem do Dia (`ordem-do-dia/index.py`)
Automação que acessa o site da Câmara, extrai os itens da pauta via scraping e gera
um briefing aprofundado com Claude API, entregue por e-mail HTML toda segunda e quarta às 23h.

## Arquitetura da Automação (ordem-do-dia)

- **Fonte de dados:** `https://administrativo.camarasantos.sp.gov.br/dispositivo/ideCustom/legislativo/ordem_dia_eletronica/publico/`
- **API de sessões:** `listagem.php?codigo=SESSION_ID` (HTML com `.documento` divs)
- **IA:** Claude Sonnet via `@anthropic-ai/sdk` (Python SDK)
- **Entrega:** Gmail SMTP com e-mail HTML estilizado
- **Agendamento:** GitHub Actions (`.github/workflows/ordem-do-dia.yml`), cron `0 2 * * 2,4`

## Secrets do GitHub Actions

| Secret | Descrição |
|---|---|
| `ANTHROPIC_API_KEY` | API do Claude |
| `GMAIL_USER` | Conta Gmail remetente |
| `GMAIL_APP_PASSWORD` | App Password de 16 dígitos |
| `GMAIL_TO` | Destinatário(s) do briefing |

## Convenções

- Frontend: sem build tools, sem npm, CDN direto no HTML
- Python: sem virtualenv, dependências em `requirements.txt`
- Português brasileiro em todo o código (comentários, variáveis, UI)
- Commits em português

## Comandos úteis

```bash
# Rodar briefing manualmente
python ordem-do-dia/index.py

# Rodar para sessão específica
python ordem-do-dia/index.py --sessao 1278

# Disparar workflow no GitHub
gh workflow run "Briefing Ordem do Dia" --repo derosisjr/Playground
```
