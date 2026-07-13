---
paths:
  - "proposituras/**"
  - "proposituras.html"
  - "proposituras-app.js"
---

# Base de Proposituras (`proposituras/` + `proposituras.html`)

Índice pesquisável das **proposituras da Câmara** (estágio anterior à lei), a partir da busca
pública de documentos legislativos. Nesta fase indexa **só o tipo "Projeto"** (Projeto de Lei,
PL Complementar, Projeto de Decreto Legislativo, Resolução, Emenda à LOM). `proposituras/crawler.py`
varre `filtro.php` (form `pesquisa_autor`, `tipo=4`) por ano, coletando **metadados + situação**
(número, ano, autor, ementa, local atual, situação + link do PDF) num SQLite, e consulta
`detalhes.php?cod=` por item para o **histórico de tramitação** (tabela `tramitacao` 1:N);
`proposituras/export.py` gera `proposituras.xlsx`/`proposituras.csv`/`proposituras-index.json`;
`proposituras.html`+`proposituras-app.js` é o painel (vanilla/CDN) com filtros subtipo/ano/autor/
situação/palavra-chave. Páginas em **ISO-8859-1** (`from_encoding="iso-8859-1"`). PK = `cod`.
Carga inicial completa roda local; `.github/workflows/proposituras.yml` reprocessa o ano corrente
semanalmente (`--forcar`) para manter situação/tramitação atualizadas. **Só `proposituras-index.json`
e o código são versionados**; `.sqlite` (~68M, pesado por causa da tramitação), `.xlsx` e `.csv`
ficam no `.gitignore` — o `.sqlite` persiste entre execuções do workflow via cache do Actions
(há guarda anti-truncamento no commit). Outros tipos (Indicação, Moção, Ofício, Requerimento) e o
cruzamento propositura→lei sancionada ficam para fases futuras.

## Comandos úteis

```bash
# Proposituras — amostra sem gravar
python proposituras/crawler.py --ano 2026 --limite 5 --dry-run

# Proposituras — carga de um ano (com tramitação)
python proposituras/crawler.py --ano 2026

# Proposituras — carga inicial completa (todos os anos) + export
python proposituras/crawler.py
python proposituras/export.py
```
