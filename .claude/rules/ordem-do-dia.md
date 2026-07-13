---
paths:
  - "ordem-do-dia/**"
---

# Briefing Ordem do Dia (`ordem-do-dia/index.py`)

Automação que acessa o site da Câmara, extrai os itens da pauta via scraping e gera
um briefing aprofundado com Claude API, entregue por e-mail HTML toda segunda e quarta às 23h.

## Arquitetura da Automação

- **Fonte de dados:** `https://administrativo.camarasantos.sp.gov.br/dispositivo/ideCustom/legislativo/ordem_dia_eletronica/publico/`
- **API de sessões:** `listagem.php?codigo=SESSION_ID` (HTML com `.documento` divs)
- **IA:** Claude Sonnet via `@anthropic-ai/sdk` (Python SDK)
- **Entrega:** Gmail SMTP com e-mail HTML estilizado
- **Agendamento:** GitHub Actions (`.github/workflows/ordem-do-dia.yml`), cron `0 2 * * 2,4`

## Comandos úteis

```bash
# Rodar briefing manualmente
python ordem-do-dia/index.py

# Rodar para sessão específica
python ordem-do-dia/index.py --sessao 1278
```
