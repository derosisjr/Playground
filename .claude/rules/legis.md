---
paths:
  - "legis/**"
  - "legis.html"
  - "legis-app.js"
---

# Base de Legislação (`legis/` + `legis.html`)

Índice pesquisável da legislação municipal de Santos a partir do **Legis da Prefeitura**
(`egov.santos.sp.gov.br/legis`). `legis/crawler.py` varre tópicos→anos→documentos coletando
**só metadados** (tipo, número, ano, data, ementa, tags + link do PDF oficial) num SQLite;
`legis/export.py` gera `legis.xlsx`/`legis.csv`/`legis-index.json`; `legis.html`+`legis-app.js`
é o painel (vanilla/CDN) com filtros tipo/ano/tema/palavra-chave. Texto integral, situação
(vigente/revogada) e relacionamentos ficam para fases futuras. Páginas em latin-1 com campos
UTF-8 embutidos (ementa/tags) — ver `_fix` em `crawler.py`. Carga inicial completa roda local;
`.github/workflows/legis.yml` faz a atualização incremental semanal (ano corrente).
