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
**busca universal Ctrl+K/"/"** (paleta sobre 8 fontes — regimento, proposituras, legislação,
requerimentos, favorecidos, endividamento, indicadores, preço comparado — carregadas sob demanda — as pequenas na 1ª abertura; as grandes (proposituras ~5 MB, legislação, `despesas-index.json`) só quando a busca chega a 3 caracteres ou na própria página da base, com "carregando…" no grupo e `role=status` p/ leitor de tela; "art 79" abre o artigo direto; no Regimento o
"/" continua focando a busca local; input é combobox ARIA com `aria-activedescendant` e aviso de
fonte fora do ar), **estado na URL** (`lerParams`/`gravarParams` — filtros e
busca viram links compartilháveis em todos os painéis; `#art-N` no regimento, `#alertas` etc. nas
abas de despesas), `exportarCsv` (dialeto Excel pt-BR `;`+BOM; **número vira vírgula decimal** — passe número, não string de `toFixed`), **modo escuro** (toggle na
topbar/hub, persiste em localStorage, default `prefers-color-scheme`; snippet inline anti-flash no
`<head>` de cada página; `html[data-tema="escuro"]` no comum.css vence os `:root` locais por
especificidade; páginas com Chart.js escutam o evento **`temamudou`** e repintam os gráficos em
memória via `definirCores()` + `Chart.getChart(id)?.destroy()` — SEM reload) e `POP_SANTOS`
(**418.608**, Censo 2022 definitivo do IBGE — unificado em 2026-07 com o benchmark de despesas; era
433.656). Favicon SVG + `og.png` + meta OG/Twitter em todas as páginas.

Também na camada comum (2026-07): **tokens de raio** `--r-sm/--r-md/--r-lg` (10/14/16px — não usar
raio fixo novo), `.sr-only` (`table.sr-only` vai para `left:-10000px`: tabela ignora width 1px e gerava rolagem horizontal no celular), **`Comum.chartAcessivel(canvas, descricao, cabecalhos, linhas)`**
(role=img + tabela oculta — usar em TODO gráfico novo), **`Comum.toast(msg)`** (no lugar de
`alert()`), **`Comum.estadoErro(alvo, msg, aoTentar)`** (erro de fetch com "Tentar de novo" — o
alvo deve ser um contêiner que o render de sucesso reconstrói), **`Comum.copiar(texto, aviso)`**
(área de transferência com reserva em textarea+execCommand e toast; devolve true/false — rascunhos,
listas e citações), skeletons `.skel` (base clara no
comum; cartões-skeleton estáticos nos `#stats` dos painéis), e **PWA** (`manifest.json` + `sw.js`:
network-first p/ estáticos e p/ os dados de despesas (`despesas-index.json`, `despesas/**`, `favorecidos/**` — índice e meses do mesmo export), stale-while-revalidate p/ os demais `*.json` ignorando `?v=`; registrado no
comum.js; desde a v4 (2026-10) são dois caches — estáticos, onde gravar um arquivo apaga as
outras `?v=`/query do mesmo caminho, e dados `*.json`, com teto de 60 entradas descartando as
mais antigas; bump do sufixo `-vN` dos nomes no sw.js se mudar a estratégia). Assets versionados com `?v=N` nos
`<link>`/`<script>` — incrementar ao alterar comum.css/js ou um app.js.

**UX transversal (Lote 3, out/2026).**
- **Topbar**: `PAGINAS` = [arquivo, rótulo da faixa, nome do cartão no hub, seção]. A faixa do
  desktop **não tem folga** (986 px medidos para 10 itens; os nomes completos dos cartões pediriam
  ~1.260 px) — rótulos curtos, nome do cartão no `title`; "Endividamento" virou "Semáforo
  Fiscal" (+15 px, cabe a 1280). **Até 640 px** a faixa mostra só "Início" + botão **"Painéis"**,
  que abre a lista com o nome e as seções dos cartões (inclui "O ano em gastos", fora da faixa);
  foco vai para a página atual, Esc fecha e devolve o foco, clique fora fecha.
- **Ctrl+K**: links pela **chave estável** — proposituras `?cod=`, legislação `?id=`,
  requerimentos `?n=` (cada painel mostra só o item, com aviso `.foco` e "Ver a lista inteira";
  mexer em filtro sai do foco). O documento entra na busca do ranking; a fonte `documentos`
  (`despesas/dados/nomes-favorecidos.json`, todos os favorecidos, ~0,7 MB) só entra com ≥ 8
  dígitos, e busca que é só CPF/CNPJ não baixa proposituras/legislação. CNPJ completo → item
  "Abrir o raio-X do CNPJ" (`favorecido.html?doc=`) no topo.
- **Barra de ações**: botões `data-acao="compartilhar|imprimir"` tratados por delegação no
  comum.js; **`Comum.compartilhar()`** = folha do sistema em tela de toque, senão copia o link
  (os filtros já estão na URL). `.acoes` quebra linha (5 botões no celular).
- **Impressão**: `@media print` no comum.css (some topbar/filtros/botões, cores claras mesmo no
  escuro, cabeçalho de tabela repetido, sem quebra dentro de linha); no `beforeprint` todo
  `Comum.paginador` mostra até 2.000 linhas e uma linha `.so-impressao` põe data, URL e o aviso de
  corte. A tabela responsiva (`.tabela-resp`) virou `@media screen and (max-width: 760px)` — a
  folha A4 (~700 px úteis) caía no layout de cartões.
- **"Base atualizada em…"**: `<p class="base-de" data-base="<índice>">` no hero dos painéis,
  preenchido pelo comum.js a partir do `bases-atualizacao.json` (altura reservada).
- **Dados novos**: o `sw.js` compara a resposta revalidada (tamanho, depois SHA-256) com a que
  serviu do cache e manda `postMessage({tipo:"dados-novos"})`; o comum.js mostra a faixa
  `.faixa-dados-novos` (role=status) com "Atualizar".
- **Celular/CLS**: até 600 px o `.hero-sub` fica em 3 linhas com "Sobre este painel ▾"; tabela vazia
  reserva `60vh` (`.tabela-wrap:has(tbody:empty)`) — CLS das listas caiu de 0,34–0,39 para
  0,001–0,021. Elemento que aparece depois do dado (ex.: resumo por secretaria) nasce visível com
  "carregando…", senão empurra a página.

**Acabamento visual (Lote 6, out/2026).**
- **Topo dos painéis = cartão do hub**: o `.eyebrow` repete a `.tag` do cartão ("Prefeitura ·
  Execução orçamentária", "Câmara · Proposituras"…) e o `<h1>` é o nome do cartão ("Radar de
  Despesas", não "… — Prefeitura de Santos"). Páginas sem cartão seguem o padrão "Origem ·
  assunto" (Raio-X: "Prefeitura · Raio-X do favorecido"; Novidades: "Gabinete ·
  Acompanhamento"). O `<title>` não mudou. Painel novo: copiar a tag do cartão.
- **Número-manchete (`.hero-num`)** no comum.css (era cópia no Semáforo e no Preço comparado):
  `.grande` (Plex Mono dourado) + `.contexto`. Abre Despesas (acumulado do ano, de
  `resumo.yoy`), Requerimentos (sem resposta de mérito na base inteira, com "todos fora do
  prazo" quando o índice traz `vence_em`) e o Semáforo. Nasce com **esqueleto em linhas
  inline** (`inline-block` + `<br>`: mesma altura e linha de base do texto; em bloco o contexto
  pulava) e some se o fetch falhar. `header.hero.com-manchete`: **até 600 px o número substitui
  o parágrafo** (`.hero-sub` oculto, "Sobre este painel ▾" vai para depois do número). O Preço
  comparado ficou de fora de propósito (decisão do usuário: o item dele ficou para depois).
- **`Comum.quandoFonte(faces, fn, ms=2500)`**: escreve texto grande em fonte web só com a face
  carregada (`document.fonts.load`, teto de 2,5 s). Pintado com a reserva (Georgia), o parágrafo
  troca de linha quando a Fraunces chega — trechos pulam de linha e o CLS chegava a 0,3–0,4 (a
  métrica pesa o deslocamento horizontal). `Comum.FACES_MANCHETE` = faces do `.hero-num`.
  Medição: sem as fontes web (rota abortada no Playwright) antes e depois davam o mesmo CLS.
- **"Em resumo" (`.resumo-box`) no comum.css**, estilo da manchete do Custo por Resultado:
  Fraunces 20 px (18 até 900, 16 até 600), números em negrito por **`Comum.destacarNumeros`**
  (escapa e marca R$/%; devolve HTML), largura inteira. A borda dourada é `.box.resumo-box` —
  o `.box` local vem depois e redefinia a borda. Em Despesas a caixa fica acima das abas e nasce
  visível com `.resumo-reserva` (altura de um mês típico por faixa de largura).
- **Subtítulo dos KPIs (`.stats .stat .sub`) em até 2 linhas** (era 1, com reticências); onde o
  painel põe `title`, o texto inteiro fica nele.
- **Eixos em R$: `Comum.compactoEixo`** ("R$ 600 mi", "R$ 1,5 bi"); tooltip segue com `compacto`.
- **Hub no celular** (até 640 px, 1 coluna): `.desc` em 2 linhas e respiros menores; grade,
  número de 34 px e desktop intocados (posição dos 10 cartões a 1366 conferida igual) —
  4.577 → 3.619 px a 390.
- Custo por Resultado: coluna de 1180 px como os demais (o Regimento segue estreito, é leitura)
  e linha do indicador em navy (`#07111f`; `#9fb6d9` no escuro), no lugar do azul `#1d6fb8`.
- **Raio-X do favorecido**: o nome do portal (caixa alta) é exibido por `nomeLegivel()`
  (`favorecido-app.js`, só exibição): iniciais maiúsculas, conectivos em minúscula, siglas e
  formas societárias intactas (lista `SIGLAS`, palavra sem vogal, romano); nome que já tem
  minúscula fica como está; o original vai no `title` do `<h1>` e nas grafias. Título 21–28 px.

**Visor de PDF embutido (2026-09): `Comum.visorPdf(url, titulo)`.** Diálogo acessível (foco
preso, Esc fecha, foco devolvido) que renderiza o PDF com **PDF.js 6** (ESM do cdnjs, carregado
sob demanda no 1º clique; worker cross-origin resolvido pelo próprio PDF.js), página a página
conforme a rolagem, com "Abrir ↗" sempre disponível; se a biblioteca não carregar, cai num
`<iframe>` com o visualizador nativo. **Só funciona com PDF servido inline e com CORS**: a Câmara
(`administrativo.camarasantos.sp.gov.br`, proposituras) manda `Access-Control-Allow-Origin: *` e
renderiza em canvas. **Legislação NÃO usa**: o Legis da Prefeitura (`egov.santos.sp.gov.br`) manda
`Content-Disposition: attachment` sem CORS — nem PDF.js nem `<iframe>` exibem, o link segue direto
(testado em 2026-09). **Requerimentos NÃO usa**: o link é pasta do Drive. O DOM é inline sem CORS
(só iframe). Proposituras intercepta o clique simples em `a.pdf` (`abrirPdfNoVisor`);
Ctrl/⌘/Shift/botão do meio seguem para a nova aba.

# Hub / Página inicial (`index.html`)

Porta de entrada do site (GitHub Pages serve da raiz). Página estática (navy/gold, sem build) em
**grade uniforme de cartões** — decisão do usuário (2026-07): bento grid e sparkline nos cartões
foram testados e REJEITADOS; o layout calmo e simétrico é intocável, inovação de apresentação vai
para páginas dedicadas. Hero com **régua de indicadores** (pago no mês, alertas a conferir
→ `#alertas` com "· N novos" quando `estado === "novo"` — o total sozinho parecia novidade todo dia —,
% requerimentos respondidos, data da base). (Os antigos Radar de Pauta e Radar de Gastos foram
removidos em 2026-07: o Briefing Ordem do Dia e a Base de Despesas cobrem os mesmos casos de uso
com dados automáticos.)

**Geometria em duas seções (2026-08):** "Bases de dados" com **7 cartões** (Despesas,
Endividamento, Preço comparado — 7º, entrou em 2026-08-09 —, Proposituras, Legislação,
Requerimentos, Regimento) + "Leituras e participação" com 3 (Custo por Resultado, O ano em
gastos, Escuta pública). A **linha órfã que o 7º cartão produz foi aceita por decisão do
usuário em 2026-08** (registrada também em `precos.md`) — não "corrigir" movendo cartões.
Retrospectiva e escuta pública, antes um `<p>` com emoji abaixo da grade, viraram cartões.
Em 2 colunas (~668–988px) a seção 2 fica 2+1; é o custo aceito.

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
- **Contagens leves (`contagens` no `bases-atualizacao.json`)** substituem o download dos índices
  grandes. `contagemOuIndice(arquivo, completa)` só aceita a contagem se ela trouxer tudo o que o
  hub usa (senão baixa o índice): requerimentos exige `classificada` (mesma regra de
  `baseClassificada()` do painel) — sem ela o rótulo errava para "com retorno" num número que já
  era só mérito (out/2026); o cartão fala em "N sem resposta de mérito", não "pendentes" (pendente é
  só uma das situações), mais o prazo da Lei Orgânica vencido (`fora_do_prazo` da contagem leve, ou
  `vence_em` do índice inteiro): "monitorados · 87 sem resposta de mérito, todos fora do prazo" —
  medido em ≤ 2 linhas a 1366/980/390 px. `regimento-notas.json` → `artigos_com_nota`: o cartão do Regimento só fala
  de notas quando há alguma.
- **Texto do cartão não promete o que a página não entrega**: as `.desc` são estáticas (trocar por
  JS mudaria a altura da fileira); o que depende de estado vai em rótulo/CTA — a Escuta pública
  diz "Ver consulta" e só vira "Participar" com a consulta aberta.

Previews locais do hub vão em `_preview-*.html` na raiz (gitignored, servidos por
`python -m http.server`), nunca no scratchpad: por `file://` o `fetch` dos JSON é bloqueado por CORS.

# Novidades (feed) — `novidades.json` (2026-10, Lote 5)

O que mudou nas bases desde a véspera, para a página `novidades.html` e o hub. Gerado
1×/dia por `.github/scripts/novidades.py` (só stdlib + `comum/`) no `bases-atualizacao.yml`
(12:00 UTC, mesmo commit do `bases-atualizacao.json` — único workflow que escreve o arquivo;
nunca editar à mão). Compara cada índice com um **retrato** compacto da passada anterior,
guardado no próprio arquivo. Testes: `comum/tests/test_novidades.py`.

`{"gerado_em": "2026-10-20T12:00:03Z", "eventos": [...], "retrato": {...}}` — a página lê só
`gerado_em` e `eventos`; `retrato` é estado interno do gerador (~15–30 KB; o arquivo inteiro
mede ~130–140 KB com o feed cheio). Cada evento: `visto_em`, `base`, `tipo`, `titulo`, `chave`,
`link` e, só em proposituras do vereador, `"mandato": true`.
- `eventos` do mais novo para o mais antigo; só os últimos **60 dias**, no máximo **400**.
- `visto_em` (aaaa-mm-dd, UTC) = dia em que o pipeline VIU a mudança, não a data do fato na
  origem (proposituras roda 2×/semana; legislação, 1×).
- `base` → `tipo`: `requerimentos` → `resposta` (ganhou mérito: situação "respondido" ou
  `data_resposta_merito`) | `prorrogacao` (virou "so_prorrogacao") | `vencido` (sem mérito e
  `vence_em` passou; 1× por pedido); `proposituras` → `nova` | `andamento` (`ua` mais recente
  num projeto que JÁ tramitava — entrar/sair de tramitação não conta); `legis` → `nova` |
  `revogada` (situação passou a conter "revog", inclui "revogada parcialmente"); `despesas` →
  `alerta` | `alerta_resolvido` (alerta a conferir — classe ≠ contexto — apareceu/sumiu) |
  `mes_fechado` (`resumo.mes_ref` avançou).
- `titulo`: frase pronta em pt-BR, ≤ 140 caracteres, feita de texto de crawler — montar com
  `textContent`, nunca `innerHTML`.
- `chave`: estável e única no feed (`<base>:<tipo>:<id>`; andamento acrescenta `:<ua>`) — serve
  de key e de "já visto" (localStorage). Transição repetida dentro da janela não gera evento.
- `link` relativo: `requerimentos.html?n=<número codificado>`, `proposituras.html?cod=<cod>`,
  `legis.html?id=<id>`, `despesas.html#alertas` (alertas), `despesas.html` (mês) — `n`, `cod` e
  `id` são lidos pelos painéis desde os Lotes 1 e 3 (mostram só o item, com "Ver a lista inteira").
- `mandato`: autor exatamente "Rui Sergio Gomes de Rosis Junior"; requerimentos são todos do
  mandato por construção (vêm da planilha do gabinete).
- Feed quieto não é defeito: na 1ª execução, no dia em que um campo novo chega a um índice
  (`vence_em`, `ua`) e num surto (> 200 eventos de uma base numa passada = troca de formato ou
  carga em massa) o gerador só refaz o retrato. Cod/id abaixo do **piso** (menor id do ano
  corrente e do anterior) é carga retroativa e não vira "nova".
- Buscar com `fetch("novidades.json", { cache: "no-cache" })`. O `sw.js` o trata como o
  `bases-atualizacao.json` (**rede primeiro**, cache só offline) — em stale-while-revalidate a
  1ª visita do dia mostraria o feed da véspera.

**Página `novidades.html` + `novidades-app.js`** (no menu "Painéis" do celular, seção
"Acompanhamento"; fora da faixa do desktop, que não tem folga): eventos agrupados pelo dia em que
apareceram, chips por base e "Só do mandato" (requerimentos + proposituras com `mandato`), na URL
(`base=`, `mandato=1`). **Última visita** neste aparelho: `localStorage["novidades:visto_ate"]` =
`visto_em` do evento mais recente visto; o que vier depois ganha o selo "novo". **Hub**: linha
`.novidades-linha` sob a régua (fora da grade) que nasce com "Novidades das bases →" numa linha
só (o número chega depois sem mudar a altura do hero) e vira "N novidades desde a última visita →"
(mesma chave) ou, para quem nunca abriu a página, "N novidades nos últimos 7 dias →".
