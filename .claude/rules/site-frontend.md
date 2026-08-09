---
paths:
  - "*.html"
  - "*-app.js"
  - "comum.css"
  - "comum.js"
---

# Camada comum do site (`comum.css` + `comum.js`)

Compartilhada por todas as páginas (sem build): tokens navy/gold, **topbar fixa** de navegação
entre painéis (`Comum.topbar("<pagina>.html")`; o hub não a usa; inclui Indicadores e Escuta Pública),
**busca universal Ctrl+K/"/"** (paleta sobre 7 fontes — regimento, proposituras, legislação,
requerimentos, favorecidos, endividamento, indicadores — carregadas sob demanda; "art 79" abre o artigo direto; no Regimento o
"/" continua focando a busca local; input é combobox ARIA com `aria-activedescendant` e aviso de
fonte fora do ar), **estado na URL** (`lerParams`/`gravarParams` — filtros e
busca viram links compartilháveis em todos os painéis; `#art-N` no regimento, `#alertas` etc. nas
abas de despesas), `exportarCsv` (dialeto Excel pt-BR `;`+BOM), **modo escuro** (toggle na
topbar/hub, persiste em localStorage, default `prefers-color-scheme`; snippet inline anti-flash no
`<head>` de cada página; `html[data-tema="escuro"]` no comum.css vence os `:root` locais por
especificidade; páginas com Chart.js escutam o evento **`temamudou`** e repintam os gráficos em
memória via `definirCores()` + `Chart.getChart(id)?.destroy()` — SEM reload) e `POP_SANTOS`
(**418.608**, Censo 2022 definitivo do IBGE — unificado em 2026-07 com o benchmark de despesas; era
433.656). Favicon SVG + `og.png` + meta OG/Twitter em todas as páginas.

Também na camada comum (2026-07): **tokens de raio** `--r-sm/--r-md/--r-lg` (10/14/16px — não usar
raio fixo novo), `.sr-only`, **`Comum.chartAcessivel(canvas, descricao, cabecalhos, linhas)`**
(role=img + tabela oculta — usar em TODO gráfico novo), **`Comum.toast(msg)`** (no lugar de
`alert()`), **`Comum.estadoErro(alvo, msg, aoTentar)`** (erro de fetch com "Tentar de novo" — o
alvo deve ser um contêiner que o render de sucesso reconstrói), skeletons `.skel` (base clara no
comum; cartões-skeleton estáticos nos `#stats` dos painéis), e **PWA** (`manifest.json` + `sw.js`:
network-first p/ estáticos, stale-while-revalidate p/ `*.json` ignorando `?v=`; registrado no
comum.js; bump de `CACHE` no sw.js se mudar a estratégia). Assets versionados com `?v=N` nos
`<link>`/`<script>` — incrementar ao alterar comum.css/js ou um app.js.

# Hub / Página inicial (`index.html`)

Porta de entrada do site (GitHub Pages serve da raiz). Página estática (navy/gold, sem build) em
**grade uniforme de cartões** — decisão do usuário (2026-07): bento grid e sparkline nos cartões
foram testados e REJEITADOS; o layout calmo e simétrico é intocável, inovação de apresentação vai
para páginas dedicadas. Hero com **régua de indicadores** (pago no mês, alertas ativos → `#alertas`,
% requerimentos respondidos, data da base). (Os antigos Radar de Pauta e Radar de Gastos foram
removidos em 2026-07: o Briefing Ordem do Dia e a Base de Despesas cobrem os mesmos casos de uso
com dados automáticos.)

**Geometria em duas seções (2026-08):** "Bases de dados" com 6 cartões (Despesas, Endividamento,
Proposituras, Legislação, Requerimentos, Regimento) + "Leituras e participação" com 3 (Custo por
Resultado, O ano em gastos, Escuta pública) — 3+3 e 3 em três colunas, sem a **última linha órfã**
que os 7 cartões produziam. Retrospectiva e escuta pública, antes um `<p>` com emoji abaixo da
grade, viraram cartões. Em 2 colunas (~668–988px) a seção 2 fica 2+1; é o custo aceito.

**Anatomia do cartão (2026-08).** Todos trazem número "ao vivo" + frescor ("atualizado há N dias"
via Last-Modified) dos `*-index.json`, degradando para "—" se falhar. Regras que valem para
qualquer mexida ali:
- **Número em 34px FIXO** (não `clamp(_,3vw,_)`: a caixa útil do cartão é quase constante — 288px a
  3 colunas, 294px a 2 — porque a `.shell` trava em 1120px; amarrar à viewport encolhe o número
  justamente onde o cartão é mais largo). O `R$` vira `<small>` (qualificador); **`bi`/`mi` NÃO
  encolhem** — são ordem de grandeza.
- **Montado com nós, nunca `innerHTML`** (`setNum()`): rótulos vêm de JSON de crawler.
- **Contador crescente** ao carregar (`contar()`), com duas travas obrigatórias: escala fixada pelo
  valor final (senão atravessa "R$ 84.400"→"R$ 8,4 mi"→"R$ 8,44 bi" mudando de largura 78×/s) e
  clamp com **piso** em `(t-t0)/dur` (o rAF entrega o timestamp do início do quadro, que pode
  preceder o `performance.now()` → primeiro quadro negativo). O gate `quandoVisivel()` espera o dado
  E o cartão assentado, com `setTimeout` de rede; o `setNum` só roda depois, senão o cartão mostra a
  resposta e rebobina.
- **Pill de estado (`.selo`) só onde há estado real**: Semáforo Fiscal (verde "limites ok" / âmbar
  "N em atenção", de `d.semaforo`) e Escuta pública (campo `ativa` de
  `consulta/consultas/prioridades-2026.json`, que também dá o nº de propostas). Despesas e
  Requerimentos **não** têm pill — os números já estão na régua do hero, na mesma tela.
- A pill fica **no fluxo** (`.cartao-topo` flex), nunca absoluta: a tag mais longa mede 271px em
  286px de caixa. Onde há selo, a tag trunca (`.tem-selo`) em vez de quebrar — se quebrar, o `h2`
  desce só nesse cartão e desalinha a fileira.
- **Ramp semântico** copiado verbatim de `endividamento.html:33-41` (com o override em
  `html[data-tema="escuro"] body`), medido em 4,78–7,60:1 nos dois temas. Não criar cor nova.
- `.lbl` com `line-height` explícito + `min-height` de exatamente 2 linhas e `.quando` por
  `visibility` (não `hidden`) — as duas reservas mantêm a régua do `.stat` alinhada na fileira.
- **Um só dispositivo de acento**: barra dourada de 3px à esquerda via `::before` (não
  `border-left`, que o `.cartao:hover { border-color }` atropelaria). É **ornamento** — cor
  semântica nela falharia a WCAG 1.4.11 (dourado sobre `--card` dá 2,25:1).
- **Sem numeração decorativa**: os antigos `01–09` saíram (a ordem não era sequência real), junto
  com o `isolation:isolate` que os sustentava e a bolinha dourada do `.quando`, que tinha forma de
  LED de status sem codificar nada.
- **Exceção de raio consciente:** o `.cartao` usa `border-radius: 4px` e não `--r-md` (14px) — os
  4px agudos são o que faz o cartão ler como documento. Se um dia subir, a barra lateral precisa de
  `border-radius: var(--r-md) 0 0 var(--r-md)`, senão o `overflow:hidden` a deforma.
- Os `*-index.json` são buscados com `fetch(url, { cache: "no-cache" })` — **nunca** com
  `?v=Date.now()`, que torna a URL única e rebaixa toda visita a download inteiro (eram ~6,6 MB por
  carga; com revalidação condicional a 2ª visita responde 304).
- **Frescor ("atualizado há N dias"): NÃO confiar no `Last-Modified`.** No GitHub Pages esse
  cabeçalho é a hora do **deploy**, idêntica para todos os arquivos — antes disso, bases paradas há
  2 meses anunciavam "atualizado hoje". A data real vem de **`bases-atualizacao.json`** (raiz, ~440
  bytes), gerado por `.github/scripts/bases_atualizacao.py` a partir de `git log -1 --format=%aI`.
  Precedência no `stat()`: data dentro do próprio JSON (`atualizado_em`/`gerado_em`) > git >
  `Last-Modified`. O 5º argumento de `stat()` é a chave nesse índice — obrigatório para os índices
  em formato de array (proposituras, legis, requerimentos, regimento), que não têm onde guardar data.

Previews locais do hub vão em `_preview-*.html` na raiz (gitignored, servidos por
`python -m http.server`), nunca no scratchpad: por `file://` o `fetch` dos JSON é bloqueado por CORS.
