---
paths:
  - "despesas/**"
  - "despesas.html"
  - "despesas-app.js"
  - "favorecido.html"
  - "favorecido-app.js"
  - "retrospectiva.html"
  - "retrospectiva-app.js"
  - "favorecidos/**"
---

# Base de Despesas (`despesas/` + `despesas.html`)

Consolidação da **execução da despesa da Prefeitura de Santos** (empenhado→liquidado→pago), a partir
da API pública do Portal da Transparência. `despesas/crawler.py` baixa **três endpoints** do
`transparencia.asmx`, cada um um estágio: `json_empenhos` (empenhado), `json_liquidacoes` (liquidado)
e `json_pagamentos` (pago) — todos `?ano=&mes=`, **um mês por requisição**; a resposta é um
**XML SOAP `<string>` com array JSON embutido como texto** (extrai `.text`, `html.unescape`,
`json.loads`). Cada estágio vai para sua tabela (`empenhos`/`liquidacoes`/`pagamentos`); a dedup é por
**`hash` MD5 das colunas-chave** (`INSERT OR IGNORE` → recarga idempotente); `controle_carga`
registra (fonte, ano, mês) já baixados. **Atenção:** os campos `empenho`/`liquidacao`/`pagamento` são
**números de documento**, não valores — o valor de cada estágio é a coluna `valor`. **A API NÃO expõe
unidade orçamentária (secretaria)**; o único campo de unidade é `unidade_gestora` (a entidade:
Prefeitura, CAPEP, IPS, fundações). O recorte por órgão usa **`funcao`** como proxy de área/secretaria.
`despesas/export.py` gera: (a) **`despesas-index.json` AGREGADO** na visão de **caixa/pago**
(totais, séries mensais, por função/elemento/fonte/unidade, top-300 favorecidos) + **alertas fiscais
por regras** (limiares no topo do arquivo); (b) **detalhe por empenho** — junta os 3 estágios por
(`unidade_gestora`,`empenho`) em `montar_execucao()` produzindo a tríade **empenhado/liquidado/pago**
por empenho, e inclui o que não casa (`Restos a pagar` = empenho de exercício anterior fora da base;
`Extra-orçamentário` = pagamento sem empenho) para não esconder nada; grava um arquivo por mês de
competência em `despesas/dados/AAAA-MM.json` (compacto `{campos, linhas}`, arrays-of-arrays; manifesto
na chave `meses`, campos em `campos_detalhe`) — **estes `dados/*.json` SÃO versionados** (Pages serve
sob demanda). `despesas.html`+`despesas-app.js` é o painel (vanilla + Chart.js via CDN) com abas
Visão geral/Alertas/Favorecidos (base pago) e **Detalhamento** (execução por empenho: seleciona 1+
meses ou ano inteiro, tabela com empenhado/liquidado/pago, busca sem acento, **filtros estruturados**
por tipo/unidade/função/fonte/grupo, ordenação, paginação e exportar CSV do filtro). Carga padrão =
**mandato (2025→ano corrente, `ANO_INICIAL=2025`)**. **`despesas-index.json`, `despesas/dados/*.json`
e o código são versionados**; `.sqlite`/`.xlsx`/`.csv` no `.gitignore` — o `.sqlite` persiste via cache
do Actions e `.github/workflows/despesas.yml` reprocessa o ano corrente diariamente (`--forcar`), com
guarda anti-truncamento (aborta commit se total < 50mi). (Substituiu o antigo Radar de Gastos por
upload de CSV, removido em 2026-07.) Unidade orçamentária real (outra fonte),
cruzamento favorecido↔licitações e IA sobre os alertas ficam para fases futuras.

## Briefing semanal de despesas (`despesas/briefing.py`)

Canal *push* para os assessores: e-mail HTML semanal com o panorama das despesas, **só informativo**
(determinístico, **sem Claude/tokens**). Lê o `despesas.sqlite` e reusa `conectar()`/`alertas()` de
`export.py` (via `import export`) + o padrão SMTP de `ordem-do-dia/index.py`. A "semana" = os 7 dias
que terminam na **data de pagamento mais recente** da base (robusto à defasagem do portal); o pago da
semana é comparado à **média semanal do ano** (baseline estável, já que pagamentos são irregulares).
Seções: cards (semana/mês/ano com variação YoY), alertas vigentes (alta/média), gasto por função, top
favorecidos, maiores pagamentos individuais e maiores empenhos novos, com link para o painel. CLI:
`--dry-run` (imprime, não envia), `--salvar PATH` (preview HTML), `--semana N`. Destinatários:
**`DESPESAS_BRIEFING_TO`** → **`RESPOSTAS_EMAIL_TO`** (mesma lista do requerimentos) → **`GMAIL_TO`**.
Agendamento: passo final do
`despesas.yml` que roda **às segundas** (`date +%u = 1`) após o crawl+export — ou via
`workflow_dispatch` com input `forcar_briefing=true`. Geração de minutas/IA e outros canais
(WhatsApp/Telegram) ficam para fases futuras.

## Raio-X do favorecido (`favorecido.html`) e Retrospectiva (`retrospectiva.html`)

Páginas-satélite da Base de Despesas, ambas 100% estáticas: o **raio-X** (`?f=<slug>`) mostra o
dossiê de um favorecido do top-300 (série mensal, funções, últimos 50 pagamentos, alertas) a partir
de `favorecidos/<slug>.json` pré-computados pelo export (slug = CNPJ ou hash curto p/ CPF
mascarado; linkado pela ficha modal do painel e pela paleta Ctrl+K); a **retrospectiva** conta o
ano em scrollytelling (IntersectionObserver, canvas puro, `?ano=`) usando só o `despesas-index.json`
(inclui `resumo` narrativo determinístico e `anos_detalhe` com top funções/favorecidos por ano,
ambos gerados pelo export — o mês corrente parcial fica fora da série).

## Comandos úteis

```bash
# Despesas — amostra de um mês sem gravar
python despesas/crawler.py --ano 2026 --mes 6 --dry-run

# Despesas — carga de um ano (ou mês específico com --mes)
python despesas/crawler.py --ano 2026

# Despesas — carga do mandato (2025→corrente) + export
python despesas/crawler.py
python despesas/export.py

# Despesas — briefing semanal (preview sem enviar)
python despesas/briefing.py --dry-run
python despesas/briefing.py --salvar despesas/_briefing.html  # abrir no navegador
```
