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
semanalmente (`--forcar`) para manter situação/tramitação atualizadas e, desde 2026-10, revisita o
**ano anterior** com `--pendentes --limite 300` (e os quatro anos antes dele com `--limite 100` cada): relista o ano e recoleta só os projetos que, no
banco, não estão em **situação final** (`situacao_final()`: `local_atual` na "Divisão de Arquivo
Público" ou situação "Transformado" — o campo `situacao` é "Encaminhado" em 98% dos itens e não
serve; local vazio conta como pendente), os coletados há mais tempo primeiro. Antes, o laço normal
pulava quem já estava no banco e 374 projetos de 2025 fora do arquivo (154 "Aguardando
Pautação") ficavam congelados na última passada do ano. Anos anteriores a esse continuam sem
revisita (em 2024 eram ~100 fora do arquivo). Testes em `proposituras/tests` (no `testes.yml`).
**Só `proposituras-index.json`
e o código são versionados**; `.sqlite` (~68M, pesado por causa da tramitação), `.xlsx` e `.csv`
ficam no `.gitignore` — o `.sqlite` persiste entre execuções do workflow via cache do Actions
(há guarda anti-truncamento no commit). Outros tipos (Indicação, Moção, Ofício, Requerimento) e o
cruzamento propositura→lei sancionada ficam para fases futuras.

## O índice (`proposituras-index.json`) — ordem e campos de tramitação (2026-10, Lote 4)

**Ordem:** data da propositura (mais recente primeiro), depois ano, número **numérico** e `cod`
(ordem total — empate não pode reordenar o arquivo versionado à toa). Antes era `ORDER BY ano
DESC, subtipo, numero` de texto, e a lista abria em "PDL 1, 10, 11…". CSV/XLSX saem na mesma
ordem. As 12 chaves antigas (`cod` … `url_pdf`) continuam iguais e na mesma ordem; o painel,
a paleta Ctrl+K (`comum.js`) e o hub não leem as novas. **Contrato dos acréscimos:**
- `tram` (int 0|1, **em todo item**): 1 = `not situacao_final(local_atual, situacao)` — a
  mesma função do crawler, importada (a regra NÃO muda por causa do painel). Sempre presente:
  `"tram" in p` separa índice novo de antigo no JS.
- `ua` (string, **só com `tram`=1**): data do último andamento em **ISO `aaaa-mm-dd`** (sem
  hora), do despacho de ordem 0 da tramitação (= `data_situacao`); `""` se não há tramitação
  gravada. ISO de propósito: ordena como texto e vira `Date` sem parser; para exibir,
  `ua.split("-").reverse().join("/")` (o `dataBr` de `precos-app.js`).
- `uad` (string, **só com `tram`=1**, junto com `ua`): despacho do último andamento, quebras e
  espaços colapsados, **≤ 80 caracteres** — acima disso cortado na última palavra inteira +
  "…" (`resumir()`); `""` se o despacho é vazio. CAIXA ALTA, às vezes com assinatura.
- `ual` (string, **só com `tram`=1 e só quando acrescenta algo**): local do último andamento
  como a tramitação escreve (CAIXA ALTA, espaços colapsados), omitido quando vazio ou igual a
  `local_atual` sem contar caixa e espaços. Exibir com **`p.ual || p.local_atual`**. Em 08/08:
  847 itens — 815 com `local_atual` vazio e 32 em que o local difere.

Enxugado em 2026-10 (`ua` só em tramitação, `uad` de 120 para 80, `ual` só quando difere): na
base de 08/08 (7.016 itens, 1.745 com `tram`=1) o índice foi de 4,96 MB para **5,23 MB — +270
KB bruto, +64 KB gzip** (era +454 KB / +98 KB com o contrato inicial).

**Chip "em tramitação" do painel = `tram === 1 && local_atual`** (local atual não vazio): 916
itens em 08/08, 860 no índice de 15/10. `tram`=1 sozinho NÃO é "tramitando": a regra é a da
revisita, que trata local vazio como pendente porque revisitar é barato — 829 dos 1.745 (871
dos 1.731 em 15/10) têm `local_atual` vazio e **ficam fora do chip**. Atenção: o critério não
pode ser `p.ual || p.local_atual` — 815 desses 829 TÊM `ual`, que é o local do último andamento
e não um local atual: 226 em "PROPOSITURA TRANSFORMADA" (nas amostras, PL convertido em PLC:
"TRANSFORMAÇÃO DO P.L. Nº 116/2022 NO P.L.C. Nº 25/2023"), 294 com despacho de anexação a outro
projeto (no texto inteiro do despacho) e 309 sem sinal. Afinar `situacao_final()` (o que também
pouparia revisitas) segue como decisão pendente.

Para testar o export sem sobrescrever o índice versionado: `--db` (outro SQLite) e `--saida
<pasta>` (índice, CSV e XLSX vão todos para lá).

## Painel (2026-10, Lote 4)

`proposituras-app.js` usa o contrato acima quando `"tram" in p` (`TEM_TRAM`); no índice antigo
tudo volta ao comportamento anterior. **Atalhos** (chips, na URL como `tram=1`, `mandato=1`,
`seg=1`): "Em tramitação" (`tram === 1 && local_atual`), "Do mandato" (autor exatamente
"Rui Sergio Gomes de Rosis Junior" — o "Rui Sergio Gomes de Rosis" de 2017–24 é outro autor e
NÃO entra) e "Acompanhando" (**neste aparelho**: `localStorage["proposituras:acompanhando"]` =
`{cod: ua visto}`; "☆ Acompanhar" grava o `ua` atual e o selo "andamento novo ✓" aparece quando
o `ua` do índice passa dele — clicar marca como visto). **Ordem** (`ordem=` na URL): mais
recentes (padrão), último andamento, número. **KPIs**: proposituras, em tramitação, aguardando
pautação (`local_atual` com "Aguardando Paut"), do mandato em tramitação. "Último andamento em
DD/MM · local — despacho" sob a ementa. CSV ganha `ultimo_andamento` e `despacho`.

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

# Proposituras — revisita do ano anterior (só fora de situação final), amostra sem gravar
python proposituras/crawler.py --ano 2025 --pendentes --limite 3 --dry-run

# Proposituras — carga de um ano (com tramitação)
python proposituras/crawler.py --ano 2026

# Proposituras — carga inicial completa (todos os anos) + export
python proposituras/crawler.py
python proposituras/export.py

# Proposituras — export de teste, sem tocar o índice versionado
python proposituras/export.py --db caminho/proposituras.sqlite --saida /tmp/prop
```
