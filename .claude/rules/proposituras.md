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

## A parada silenciosa de jun–ago/2026 (não repetir)

**Sintoma:** o índice ficou congelado em 07/06 por dois meses. O workflow rodava toda segunda e
terminava com *success* — nada de vermelho no Actions.

**Causa:** o GitHub apaga cache sem acesso há 7 dias, e o cron era semanal — o intervalo batia
exatamente na janela de despejo. Perdido o cache, o banco foi recriado **vazio**; como o workflow
chamava o crawler com `--ano` do ano corrente, ele só reenchia 2026 (~300 itens). O export
reescreve o índice inteiro a partir do banco, a guarda `N < 6000` barrava o commit — e ao fim do
run o banco truncado era **salvo de volta no cache**. Laço fechado: 260 → 280 → 299 → 317 → 323
itens, abortando toda semana. O `exit 0` da guarda escondia tudo.

**Por que só aqui:** despesas, endividamento e indicadores chamam o crawler **sem `--ano`**, então
refazem o histórico sozinhos após um cache miss; legis tem o `.sqlite` versionado no git. Esta era
a única base com banco fora do git **e** crawl limitado a um ano.

**Correções (2026-08):** o workflow conta as linhas do banco restaurado e dispara carga completa se
vier abaixo de 6000 (`timeout-minutes: 120`, a recarga leva ~1h); o cron passou a rodar 2×/semana
(seg e qui) só para manter o cache dentro da janela de 7 dias; e a guarda saiu de `exit 0` para
`exit 1` — o mesmo foi feito nas guardas de despesas, endividamento, indicadores e
respostas-executivo. Regra geral: **guarda que aborta não pode sair com `exit 0`**.

Ao mexer em qualquer workflow com `.sqlite` em cache, verificar as duas propriedades juntas —
*o banco está fora do git?* e *o crawl reconstrói o histórico sozinho?* Se a resposta for
"sim" e "não", a base para em silêncio no primeiro despejo de cache.

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
