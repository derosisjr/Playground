---
paths:
  - "*.html"
  - "*-app.js"
  - "comum.css"
  - "comum.js"
---

# Camada comum do site (`comum.css` + `comum.js`)

Compartilhada por todas as páginas (sem build): tokens navy/gold, **topbar fixa** de navegação
entre painéis (`Comum.topbar("<pagina>.html")`; o hub não a usa), **busca universal Ctrl+K/"/"**
(paleta sobre as 5 bases, carregadas sob demanda; "art 79" abre o artigo direto; no Regimento o
"/" continua focando a busca local), **estado na URL** (`lerParams`/`gravarParams` — filtros e
busca viram links compartilháveis em todos os painéis; `#art-N` no regimento, `#alertas` etc. nas
abas de despesas), `exportarCsv` (dialeto Excel pt-BR `;`+BOM), **modo escuro** (toggle na
topbar/hub, persiste em localStorage, default `prefers-color-scheme`; snippet inline anti-flash no
`<head>` de cada página; `html[data-tema="escuro"]` no comum.css vence os `:root` locais por
especificidade; páginas com Chart.js recarregam no toggle) e `POP_SANTOS` (433.656, IBGE 2022,
para per capita). Favicon SVG + `og.png` + meta OG/Twitter em todas as páginas.

# Hub / Página inicial (`index.html`)

Porta de entrada do site (GitHub Pages serve da raiz). Página estática (navy/gold, sem build) em
**bento grid**: cartão de Despesas 2×2 com sparkline (canvas puro), tile de **alertas fiscais ao
vivo**, e cartões de Proposituras/Legislação/Requerimentos/Regimento com números "ao vivo" +
frescor ("atualizado há N dias" via Last-Modified) lidos dos `*-index.json` (degrada se falhar).
Hero com **régua de indicadores** (pago no mês, alertas ativos → `#alertas`, % requerimentos
respondidos, data da base). Link para a retrospectiva abaixo da grade. (Os antigos Radar de Pauta
e Radar de Gastos foram removidos em 2026-07: o Briefing Ordem do Dia e a Base de Despesas cobrem
os mesmos casos de uso com dados automáticos.)
