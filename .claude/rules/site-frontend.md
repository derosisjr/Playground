---
paths:
  - "*.html"
  - "*-app.js"
  - "comum.css"
  - "comum.js"
  - "explorador-worker.js"
---

# Camada comum do site (`comum.css` + `comum.js`)

Compartilhada por todas as páginas (sem build): tokens navy/gold, **topbar fixa** de navegação
entre painéis (`Comum.topbar("<pagina>.html")`; o hub não a usa; inclui Indicadores e Escuta Pública),
**busca universal Ctrl+K/"/"** (paleta sobre 10 fontes — regimento, lei orgânica, proposituras, legislação,
requerimentos, indicações, favorecidos, endividamento, indicadores, preço comparado — carregadas sob demanda — as pequenas na 1ª abertura; as grandes (proposituras ~5 MB, legislação, `despesas-index.json`, Lei Orgânica ~0,5 MB) só quando a busca chega a 3 caracteres ou na própria página da base, com "carregando…" no grupo e `role=status` p/ leitor de tela; "art 79" lista o artigo do Regimento e o da Lei Orgânica, o Regimento primeiro; "lom 58"/"lei orgânica 58" só a Lei Orgânica (Disposições Transitórias entram pelo texto, não pelo número); no Regimento e na Lei Orgânica o
"/" continua focando a busca local; input é combobox ARIA com `aria-activedescendant` e aviso de
fonte fora do ar), **estado na URL** (`lerParams`/`gravarParams` — filtros e
busca viram links compartilháveis em todos os painéis; `#art-N` no Regimento e na Lei Orgânica —
`#adt-art-N` nas Disposições Transitórias —, `#alertas` etc. nas abas de despesas), `exportarCsv` (dialeto Excel pt-BR `;`+BOM; **número vira vírgula decimal** — passe número, não string de `toFixed`), **modo escuro** (toggle na
topbar/hub, persiste em localStorage, default `prefers-color-scheme`; snippet inline anti-flash no
`<head>` de cada página; `html[data-tema="escuro"]` no comum.css vence os `:root` locais por
especificidade; os gráficos repintam no evento **`temamudou`** sem reload — os do ECharts pela
camada comum (`Comum.grafico`); o Preço comparado, último com Chart.js, via `definirCores()` +
`Chart.getChart(id)?.destroy()`) e `POP_SANTOS`
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
  que abre a lista com o nome e as seções dos cartões (inclui "O ano em gastos" e "Lei Orgânica",
  fora da faixa — rótulo `null` em `PAGINAS`);
  foco vai para a página atual, Esc fecha e devolve o foco, clique fora fecha. **Indicações**
  (out/2026) também ficou fora da faixa (rótulo `null`): medido, a faixa ocupa os 986 px inteiros
  e "Indicações" pediria +94 px em qualquer largura; chega-se a ela pelo menu, pelo cartão do hub
  e pela alternância "Requerimentos | Indicações" no topo das duas páginas.
- **Ctrl+K**: links pela **chave estável** — proposituras `?cod=`, legislação `?id=`,
  requerimentos e indicações `?n=` (cada painel mostra só o item, com aviso `.foco` e "Ver a lista inteira";
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

**Direção visual "Noturno" (M2, out/2026 — escolha do usuário entre 3 previews: Gazeta, Noturno,
Painel).** A linguagem da Retrospectiva levada a todos os topos, **no comum.css**:
- `header.hero`: navy mais profundo (`--navy-2` → `#060e1a`) com brilho dourado à direita, trama de
  losangos em todo o topo (`::before`, opacidade .85, sem máscara) e o fio dourado (`::after`);
  `header.hero .hero-in` com padding vertical maior; `header.hero h1` em clamp(34–60 px). Até então
  cada painel repetia a trama e o título de 34 px no `<style>` local — **não recriar** essas regras
  na página. Exceções conscientes, redefinidas no `<style>` local com o mesmo seletor: Raio-X
  (`header.hero h1` 21–28 px, nome do favorecido) e Escuta (28–38 px, coluna de 640 px). O hub tem
  título próprio (40–76 px, `max-width: 12em` = 2 linhas) e régua com números de 22–31 px e entrada
  escalonada.
- `.eyebrow` em `--gold`, tracking .3em, fio de 34 px; `.hero-num .grande` 44–92 px.
- **Despesas: "Em resumo" dentro do topo escuro**, depois da manchete (`header.hero .resumo-box`).
  No celular recolhe em 5 linhas com "Ler o resumo inteiro" (`#resumo-mais`, no HTML desde o início;
  some se o texto couber) — a reserva `.resumo-reserva` acompanha (5 linhas no celular).
- **"Sobre este painel" no HTML** dos painéis com `com-manchete` (`.sobre-painel`, só aparece no
  celular): criado por JS ele chegava depois da 1ª pintura e empurrava a página; `recolherHero()`
  reaproveita o botão pronto. A frase do número reserva 3 linhas no celular. CLS no celular:
  Despesas 0,05 → 0,02, Requerimentos 0,07 → 0,005, Semáforo 0,07 → 0,02.
- **Cartões do hub**: a origem vai numa **faixa navy no topo** (`.cartao-topo` com margem negativa
  igual ao padding do cartão; `#060e1a` no escuro), tag em mono `--gold-bright`; barra lateral
  dourada mantida. Grade uniforme conferida (mesma altura por fileira).

**Gráficos: Apache ECharts 6.1.0 via `Comum.grafico` (M4, out/2026 — aprovado pelo usuário).**
Todo gráfico novo passa por esta camada; **não usar Chart.js em página nova** (Despesas migrou no
M7, out/2026; resta só o Preço comparado, cujo item ficou para depois).
- `Comum.grafico(idOuEl, { opcao(p, largura) → option, acessivel: {descricao, cabecalhos, linhas},
  altura?(largura), eventos?(chart), dependeDaLargura?, renderer? })`. Contêiner =
  `<div class="grafico" id="…">` no HTML (altura por `--altura-grafico`, reservada desde a 1ª
  pintura); chamar de novo com o mesmo alvo atualiza (filtro, dado novo).
- **Carga sob demanda**: a biblioteca (~370 KB gzip, cdnjs com SRI) só vem quando o 1º gráfico chega
  a 300 px da tela, e cada gráfico só é desenhado ao se aproximar (IntersectionObserver) e depois das
  fontes web (`quandoFonte`). Avaliar o ECharts custa 5–10× o Chart.js; tirar o Chart.js síncrono do
  `<head>` baixou o bloqueio da thread principal (CPU 4×) no Semáforo de 4,6 s para 2,8 s.
- `Comum.paleta()` = cores do tema atual (tokens; `serie` navy/#9fb6d9, `ouro`/`ouroLinha`,
  `verde/amarelo/vermelho` do ramp, `rampa` de 5 dourados, `celular`); temas `gabinete-claro/escuro`
  e locale pt-BR próprio registrados na carga (o do pacote tem erros). **Número sempre pelos
  formatadores da casa** (`compactoEixo`, `brl`, `pct`) — o padrão do ECharts escreve "1,000".
- Tabela oculta (`chartAcessivel`) entra na hora, sem esperar a biblioteca; repinta sozinho no
  `temamudou` e ao cruzar 640 px; CDN fora do ar → `estadoErro` com "Tentar de novo" no lugar do
  gráfico (o resto da página segue). Dica padrão: `Comum.dicaGrafico(titulo, [[cor, rótulo, valor,
  "p"?]], nota, alerta)` (classes `.ec-dica*` no comum.css, texto escapado).
- Padrões já resolvidos (Semáforo, `opcaoQuadrimestral`): **eixo x numérico** para a quebra contábil
  ficar ENTRE dois pontos (markLine em i − 0,5) com pílula horizontal no trecho mais vazio; limites
  lidos do `semaforo` do índice (não fixos no JS) com rótulo sobre a linha; eixo que desce abaixo de
  zero quando há negativo (DCL); teto do eixo arredondado. Tesoura (Custo por Resultado): faixa =
  série base invisível + diferença empilhada, com os cruzamentos inseridos.
- Padrões do Radar de Despesas (M7, detalhes em `despesas.md`): trecho parcial = 2ª série com o
  MESMO nome (a legenda liga/desliga as duas); linha sem marcador → `itemStyle: { opacity: 0 }` no
  item da `legend.data` (o ECharts desenha um ponto no ícone mesmo com `symbol: "none"`); eixo de
  categoria com todos os rótulos = `interval: 0` + `hideOverlap`; barras deitadas em caixa estreita
  com passo e teto calculados (`eixoValor`); treemap: o espaço entre as áreas é
  `itemStyle.borderColor` (padrão branco — no escuro vira grade) e, para rótulo só onde cabe, o
  layout "squarified" pode ser reproduzido antes de desenhar (`retangulosMapa`).
- A nota em destaque de `Comum.dicaGrafico(…, alerta)` usa `.ec-dica-alerta`, com prefixo: com a
  classe solta `alerta` ela herdava o cartão de alerta do Raio-X e do Despesas (borda, padding, fundo).
  Classe nova dentro da dica leva o prefixo `ec-dica-`.
- Armadilhas medidas no M8 (Despesas, `despesas.md`): o `dataZoom` **inside captura a roda do mouse
  mesmo com `zoomOnMouseWheel: "ctrl"`** (o controlador liga a roda e decide depois) — a página para
  de rolar sobre o gráfico; use `zoomLock: true` (só arrasto) e trate o Ctrl + roda na página. Cor
  por faixa em centenas de itens: `visualMap` por peças, não `itemStyle` por item; `decal` (hachura)
  com cor própria por item dobra o custo — uma série à parte com uma hachura só.

**Indicações & Respostas (`indicacoes.html` + `indicacoes-app.js`, M5, out/2026 — protótipo
aprovado pelo usuário, público).** Irmã de Requerimentos: topo Noturno com manchete (sem
resposta de mérito na base inteira), KPIs, filtros `q`/`ano`/`sit` + `bairro`/`regiao`/`n` na
URL, `Comum.paginador`, CSV só com campos públicos (+ dias até a resposta), compartilhar e
imprimir. Dados: `indicacoes-index.json` e `geo/santos-bairros.geojson` (contrato e privacidade
em `respostas-executivo.md`). **Nunca falar em prazo**: indicação não tem prazo legal.
- **Mapa por `Comum.grafico`** (série `map`): `echarts.registerMap` dentro do `opcao`, uma vez
  (a biblioteca só existe quando o mapa vai ser desenhado); duas séries — a ilha (caixa do
  `enquadrar`, alinhada ao topo) e a área continental (`area_continental` do GeoJSON) num recorte
  no canto sudoeste, que vira faixa sob a ilha abaixo de 560 px. Rampa de 5 classes de
  `Comum.paleta().rampa` por quebras naturais sobre a raiz da contagem; zero = `p.neutro`. Divisa
  entre bairros `p.card` no claro e `p.linha` no escuro (o neutro some no fundo navy).
- **Rótulos** seletivos (os 5 maiores — 3 no celular — ou só o escolhido): dentro da forma no
  ponto mais perto do polo de inacessibilidade, senão fora com linha-guia (`graphic`). A posição é
  calculada pela projeção própria (`projecao`), que reproduz a do ECharts — conferida contra
  `convertToPixel` (< 0,25 px) sem zoom, com zoom e depois de arrastar. Zoom pelos botões (×1,6,
  até 8×; arrastar só aproximado); o centro arrastado é guardado no evento `georoam`, porque o
  `notMerge` da camada comum apagaria o estado do ECharts no redesenho seguinte.
- **Altura fixa por faixa** (540/460/380 px via `--altura-grafico`): a camada só redesenha quando a
  LARGURA muda.
- Clique no bairro → `?bairro=` (2º clique limpa); chips das regiões e de "Sem bairro
  reconhecível" → `?regiao=<slug>`; a tabela "Bairro | Indicações | Respondidas | Mediana" (ordenável
  e clicável) é o equivalente acessível do mapa, e a descrição + tabela oculta vão no `acessivel`.
  Nota de cobertura em palavras ("362 de 562 num bairro do mapa…; a contagem mostra onde o
  mandato pediu, não a necessidade de cada bairro").
- **CLS** (medido: 0,017 a 1366, 0,023 a 980, 0,001 a 390): KPIs com `min-height` do subtítulo de 2
  linhas, frase da manchete que cabe nas 2 linhas reservadas no desktop, reservas da nota, legenda e
  chips, e **`.mais[hidden] { display: none }`** — o `display: block` do botão vencia o `[hidden]`:
  ele aparecia na lista vazia e saltava para o fim dela, e o salto inflava o CLS a 0,4 em parte
  das cargas. (Requerimentos, Proposituras e Legislação têm o mesmo `.mais` sem a regra: o botão
  fica visível mesmo sem mais nada a mostrar — não corrigido aqui.)
- **Alternância "Requerimentos | Indicações"** (`.hero-topo` + `nav.alterna` no comum.css): a
  etiqueta à esquerda e a alternância à direita no topo das duas páginas; no celular desce.

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

**Geometria em duas seções (2026-08):** "Bases de dados" com **9 cartões** (Despesas,
Endividamento, Preço comparado — 7º, entrou em 2026-08-09 —, Proposituras, Legislação,
Requerimentos, Indicações — logo depois de Requerimentos, 2026-10, M5 —, Regimento, **Lei Orgânica** —
2026-10, M3, logo depois do Regimento) + "Leituras e participação" com 3 (Custo por Resultado, O ano
em gastos, Escuta pública). Com 9 cartões a seção fica **3×3** a 3 colunas (cartões próprios para
Indicações e Lei Orgânica, decisões D4/D5 do usuário em 2026-10): sumiu a fileira incompleta, que
tinha sido aceita em 2026-08 (registro em `precos.md`). A 2 colunas são 4 fileiras cheias e 1
cartão na última — custo aceito; não "corrigir" movendo cartões.
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
  em formato de array (proposituras, legis, requerimentos, regimento, lei orgânica), que não têm onde
  guardar data.
- **Contagens leves (`contagens` no `bases-atualizacao.json`)** substituem o download dos índices
  grandes. `contagemOuIndice(arquivo, completa)` só aceita a contagem se ela trouxer tudo o que o
  hub usa (senão baixa o índice): requerimentos exige `classificada` (mesma regra de
  `baseClassificada()` do painel) — sem ela o rótulo errava para "com retorno" num número que já
  era só mérito (out/2026); o cartão fala em "N sem resposta de mérito", não "pendentes" (pendente é
  só uma das situações), mais o prazo da Lei Orgânica vencido (`fora_do_prazo` da contagem leve, ou
  `vence_em` do índice inteiro): "monitorados · 87 sem resposta de mérito, todos fora do prazo" —
  medido em ≤ 2 linhas a 1366/980/390 px. `regimento-notas.json` → `artigos_com_nota`: o cartão do Regimento só fala
  de notas quando há alguma. `lei-organica-index.json` → `{n, alterados, adt}`: o cartão da Lei
  Orgânica mostra os artigos do **corpo** (256; as Disposições Transitórias recomeçam no art. 1) e
  "artigos · 68 alterados por emenda" (artigos com nota de emenda) — 1 linha a 1366/980/390 px. Sem
  a chave (antes do 1º `bases-atualizacao.yml` depois do merge) o hub baixa o índice inteiro.
  Indicações (`n`, `respondidos`, `por_situacao`; a contagem leve só vale com `respondidos`):
  "monitoradas · N sem resposta de mérito" — **sem prazo**: indicação não tem o prazo legal do
  requerimento; medido em ≤ 2 linhas a 1366/980/390 px.
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

# Explorador de pagamentos — `explorador.html` (M9, out/2026)

Tabela dinâmica e SQL de leitura sobre os pagamentos da Prefeitura, no navegador: a página
(`explorador-app.js`) monta o SQL e desenha; um **Web Worker de módulo** (`explorador-worker.js`,
mesma origem) baixa o cubo do ano (`despesas/dados/cubo/AAAA.json`, contrato em `despesas.md`),
monta e consulta num SQLite em memória. Sem cartão no hub: entra pelo menu "Painéis" (`PAGINAS`
com rótulo `null` na faixa, seção "Bases de dados", logo depois do Radar — `comum.js?v=24`), por um
link discreto no Detalhamento do Radar de Despesas e pela busca Ctrl+K (fonte de despesas).
- **Topo Noturno** (eyebrow "Prefeitura · Explorador de pagamentos", `.base-de` do
  `despesas-index.json`); "Sobre este painel" já no HTML (o texto passa de 3 linhas até 600 px).
  Do índice a página usa só `cubos`, `top_favorecidos` (slug do dossiê), `resumo.meses_parciais`
  (`*` no mês), `meses_movimento` (tamanho do download do Detalhamento) e `dados_ate`; índice sem
  `cubos` → aviso "ainda não tem dados publicados".
- **Biblioteca e integridade**: `@sqlite.org/sqlite-wasm@3.53.4-build1` (versão exata, publicada no
  npm em 2026-09-08) do jsDelivr. `import()` não aceita SRI, então o worker baixa `dist/index.mjs` e
  `dist/sqlite3.wasm` com **`fetch(url, { integrity: "sha384-…" })`** — o navegador recusa arquivo
  diferente (hashes do .tgz do npm, que confere com o `integrity` do registro; o jsDelivr serve os
  mesmos bytes) —, importa o módulo de um Blob URL e passa o .wasm como `wasmBinary` (`locateFile`
  só evita resolver caminho relativo a `blob:`). O `/+esm` do jsDelivr (gerado, ~70 KB) não tem hash
  conferível; o arquivo do pacote custa ~50 KB a mais no download. Trocar de versão = versão e os
  dois hashes juntos.
- **Montagem**: o JSON vai inteiro para o SQLite (`jsonb` uma vez + `json_each`; cada linha vira
  jsonb numa CTE materializada antes das extrações; dicionários juntados por chave) — ~210–270 ms
  para 29,7 mil linhas, contra 0,9 s com bind por linha no M0. Confere linhas e pago com o
  manifesto. Tabela `pagamentos` (ano, mes, periodo, unidade_gestora, tipo, chave_favorecido,
  favorecido, documento, funcao, subfuncao, programa, elemento, fonte, grupo, pago, n); cada linha
  soma documentos — `SUM(n)` conta pagamentos. O download do cubo corre junto com o da biblioteca.
- **Tabela dinâmica**: linhas (11 dimensões), colunas opcionais (mês e ano em ordem; as demais com as
  8 maiores + "Demais"), medida pago | nº | % do total, 10/20/50 maiores + "Demais" (mês e ano mostram
  todos os períodos), filtros em chips (dimensão + busca sem acento com sugestões — combobox ARIA;
  valores da mesma dimensão = OU; sugestões sob os outros filtros), anos por botões ("+ 2025 · ≈
  0,5 MB" pelo `gzip` do manifesto; vários anos na mesma tabela). **A consulta que monta a tabela é a
  mesma de "Ver SQL"**; o total = soma das linhas (inclusive "Demais"); o resumo do topo vem de uma
  consulta independente. Cabeçalhos `<button>` com `aria-sort` ("Demais" fica no fim); `.tabela-resp`
  no celular (1ª célula = título do cartão); matriz com valores compactos sem "R$" (exato no `title`
  e no CSV); área rolável só ganha `tabindex`/`role=region` quando rola. Gráfico por `Comum.grafico`
  (barras deitadas até 20; mês/ano em pé; com colunas, empilhadas com o tempo no eixo x e 6 séries +
  "Outros"; celular sem eixo, valor na ponta). CSV por `Comum.exportarCsv` (números como número,
  coluna "Recorte"). Status `role=status` de altura fixa ("Baixando…", "Montando…", "Pronto em 0,6 s").
- **URL**: `anos`, `l`, `c`, `m`, `top`, `f1…fN` (`dim:valor`; valor vazio = sem valor na origem), `o`
  (coluna:direção), `sql=1` (painel aberto), `q` (consulta executada; roda ao abrir o link).
- **Clique**: favorecido → `favorecido.html?f=<slug>` (top-300) ou `?doc=&nome=`; demais → Detalhamento
  `despesas.html?dv=mov&dm=<meses|ano>&dfa=P&<DET_URL>=…#detalhe` (mesmas chaves de `irParaDetalhe` /
  `_link_detalhe`; filtro com mais de um valor fica de fora e o `title` do link diz, com o tamanho do
  download). "(sem função)" e "Demais" sem link (o Detalhamento não filtra o vazio).
- **Guarda do SQL** (no worker): só `SELECT`/`WITH` (comentários iniciais ignorados), **um comando**
  (contado com `sqlite3_prepare_v3` + tail — o `prepare` do oo1 ignoraria o resto em silêncio),
  `sqlite3_stmt_readonly`, `PRAGMA query_only=1` (só a carga o desliga), `hard_heap_limit` 256 MB e
  `SQLITE_LIMIT_LENGTH` 16 MB; até 5.000 linhas (200 por vez), texto > 2.000 caracteres cortado,
  resultado só por `textContent`. **10 s** na página: termina o worker, cria outro e recarrega os anos
  (~0,5 s no teste); consultas da própria página têm rede de 30 s; init > 45 s = falha.
- **Falha** (CDN fora, hash diferente, sem worker de módulo — detectado pelo getter de `type` no
  próprio worker — ou sem WebAssembly): aviso `role=alert` + "Baixar o cubo de AAAA (CSV)" montado em
  JS puro do JSON + link para o Detalhamento + "Tentar de novo".
- **Medido** (Chromium, servidor local, CDN real, base de 2026-10-16): pronto em 0,5–0,8 s frio e
  0,4–0,7 s quente; a thread do worker faz ~420 ms de trabalho sem nenhuma tarefa longa na página por
  causa dele (a 4×, as longas são layout/fontes — iguais às de outras páginas —, o JSON do índice, o
  desenho da tabela e a avaliação do ECharts). O CPU 4× do CDP não desacelera o worker. CLS 0,0002
  (390) e ≤ 0,011 (1366). axe 4.10.2 sem violações (tabela, matriz, filtro, SQL, falha × 1366/390 ×
  claro/escuro). WebKit 26.4 ok. `sw.js`: `explorador.html` no NUCLEO; os cubos caem em
  `DADOS_COERENTES` (rede primeiro); o CDN não passa pelo SW (cache HTTP, `immutable`).
