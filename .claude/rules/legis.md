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
é o painel (vanilla/CDN) com filtros tipo/ano/tema/situação/palavra-chave. Texto integral
fica para fase futura. Páginas em latin-1 com campos UTF-8 embutidos (ementa/tags) — ver
`_fix` em `crawler.py`. Carga inicial completa roda local; `.github/workflows/legis.yml` faz a
atualização incremental semanal (ano corrente + revisita, abaixo), com `pytest legis/tests`
antes do crawl.

**Situação das normas (2026-10) — INFERIDA, nunca afirmada como fato.** O Legis NÃO publica
situação: a página de uma lei revogada não tem marca nenhuma (conferido nas Leis 2.182/2004 e
2.490/2007 e na LC 543/2005, todas revogadas expressamente); não há filtro de situação nem
vínculos entre normas. O que o Legis publica é a **ementa oficial** (`<p class="descricao">`,
coluna `descricao` — o campo `ementa` antigo são os badges/palavras-chave), e a revogadora
diz o que faz nela ("REVOGA A LEI Nº 2.182, DE 06 DE JANEIRO DE 2004"). `legis/revogacoes.py`
(sem rede) extrai os vínculos e o crawler grava `situacao` = `revogada` | `revogada
parcialmente` | `alterada` | `''` (sem registro) e `revogada_por` (id da revogadora mais
recente), recalculados **no banco todo ao fim de toda execução** (`--so-situacao` recalcula sem
rede). Alvo só é marcado se existir no banco com mesmo tipo+número (+ano, quando a ementa
traz; sem ano, só número único) e não for posterior à origem. **Não pega**: revogação só no
corpo do texto, revogação tácita ("revogadas as disposições em contrário"), alvos fora da
cobertura (leis ordinárias < 1999, decretos < 2026 — a carga de decretos só tem 2026) e
repristinação. `''` NÃO é "vigente" — o painel diz "sem revogação/alteração registrada".
A busca textual do Legis (`/legis/search?query=`) acha cláusulas do corpo ("Fica revogada a
Lei nº…"), mas é OR por relevância e o trecho devolvido nem sempre contém a cláusula — testado
e descartado como fonte automática (2026-10).

**Revisita incremental.** Normas já gravadas não eram reprocessadas sem `--forcar`. Agora
`--revisitar N` reprocessa, além das novas, as N de `data_coleta` mais antiga (o workflow usa
1000 ≈ 7 min a ~0,4 s/página; input `revisitar` no dispatch). É o que preenche a `descricao`
das ~3,9 mil normas anteriores a 2026-10 — a base inteira gira em ~4 semanas — e pega ementas
corrigidas no Legis. Migração do sqlite é só `ALTER TABLE ADD COLUMN` (`abrir_db`), e o
`upsert` virou `ON CONFLICT DO UPDATE` (o `INSERT OR REPLACE` apagava `situacao`). O
`descricao` engorda o sqlite versionado (~+0,9 MB na base toda); NÃO vai para o
`legis-index.json` (só `situacao` e, onde houver, `revogada_por`) — vai para `legis/ementas.json`
(abaixo).

**Índice e ementas (2026-10, Lote 4).** O `legis-index.json` sai em ordem de **data da norma**
(mais recente primeiro; depois número numérico e `id` — ordem total, sem diff à toa). Sem
`data_norma`, a norma vai para o fim do próprio ano; sem ano (Lei Orgânica, Códigos,
Consolidações), para o fim. São 59 sem data em 2026-10: 8 sem ano, 21 com dia ordinal ("de 1º
de setembro") e o resto sem vírgula antes do "de" ("Lei nº 2.088 de 12 de março") ou com erro
de digitação ("jeneiro", "27de") — o regex de data do crawler (`,\s*de\s+(\d{1,2})\s+de`) não
lê nenhum desses. **Número ausente é tirado do título** (`numero_do_titulo`): o regex do crawler (`n\.?º`)
não reconhece "n.°", "n,º", "nº.", "n. º", "n°" e "n." — 62 das 66 normas sem número
resolvidas (as 4 restantes não têm número no título); vale no índice, CSV e XLSX, mas NÃO no
banco — logo `revogacoes.py` ainda não casa revogação com essas 62 (corrigir na origem é o
regex do crawler). As chaves do índice não mudaram (o hub calcula `ultima_lei` dele:
continua 4.804/2026). **`legis/ementas.json`** = `{"<id>": descricao}` só das normas com ementa
oficial, em ordem crescente de id, compacto: 2.003 de 3.915 em 2026-10-12 (356 KB bruto,
64 KB gzip; deve ~dobrar quando a revisita cobrir a base). É o que preenche as 3.294 normas com
`ementa` (badges) vazia no índice — 1.633 já têm ementa oficial. O painel busca sob demanda
(`./legis/ementas.json`; 404 até o primeiro workflow depois do merge — tratar a ausência).
O `legis.yml` comita o arquivo junto do índice e a guarda de integridade aborta (`exit 1`)
se ele cair abaixo de **1.500** ementas (descricao perdida ou HTML do Legis mudado — a
revisita regravaria vazio). Para testar sem sobrescrever os versionados: `python
legis/export.py --db <sqlite> --saida <pasta>` (os quatro arquivos vão para a pasta).

Análises derivadas (rodam local, sem CI): `legis/triagem_revogacao.py` gera
`triagem-revogacao.xlsx` (gitignored) com candidatas a revogação; `legis/posturas/` guarda
os scripts `gerar_*.py` + CSVs-fonte da análise do Código de Posturas (saídas `.docx`/`.xlsx`
gitignored — derivadas).
