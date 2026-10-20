---
paths:
  - "respostas-executivo/**"
  - "requerimentos.html"
  - "requerimentos-app.js"
  - "indicacoes.html"
  - "indicacoes-app.js"
  - "geo/**"
---

# Respostas do Executivo (`respostas-executivo/index.py`)

Automação que varre a busca pública de "Respostas do Executivo" endereçadas ao vereador
(sem e-mail), baixa os PDFs do pedido original e da resposta do prefeito, organiza-os no
Google Drive (uma subpasta por item) e registra cada item numa planilha de controle.

## Arquitetura da Automação

- **Fonte de dados:** `busca_documento_pub/filtro_resultado.php?pesquisa_resposta_executivo[ano]=AAAA&pesquisa_resposta_executivo[autor]=282` (paginada via `&limite=N`, 20/página). Páginas em ISO-8859-1. **As respostas ficam arquivadas no ano de ENVIO da propositura**, não no ano da resposta — por isso a rotina varre, por padrão, **de 2025 (`ANO_INICIAL`, 1º ano do mandato) até o ano corrente** (`--ano` aceita lista, ex.: `2025,2026`).
- **Página canônica:** o link "Mais detalhes" de cada resultado aponta para `detalhes.php?cod=...` do pedido original — contém tipo, número, processo, data, ementa, PDF do pedido e a seção "Resposta anexada" com os PDFs do prefeito.
- **Arquivamento:** Google Drive via OAuth do próprio usuário (`google-api-python-client`), uma subpasta por item (`Tipo Número`). Token gerado por `setup_oauth.py` (1x); lido de `token.json` (local) ou do secret `GOOGLE_OAUTH_TOKEN` (CI).
- **Registro:** Google Sheets; duas abas (`indicações`/`requerimentos`), roteamento por tipo. Cada item vira uma entrada do **plano de escrita** (`planilha.Escrita` para a linha existente, só nas colunas `Resposta`, `Data da resposta`, `Situação da resposta` e `Data da resposta de mérito`; `planilha.NovaLinha` se o número não existir), aplicado por `planilha.aplicar` — ver "Escrita planejada e falha à vista (R3)". Item que já tem Resposta e não ganhou resposta nova **não vai ao log nem ao e-mail** e só tem célula vazia preenchida. Antes de ler, `garantir_colunas` cria as colunas de classificação que faltarem: sem elas a situação nunca era gravada e ~576 itens saíam todo dia como "resposta nova" (out/2026). Ver `ABAS`/`carregar_planilha` em `index.py`. Pastas no Drive: `REQUERIMENTO_<nº>` / `INDICACAO_<nº>`.
- **Log diário:** aba `Log diário` (criada automaticamente; `garantir_aba_log` completa o cabeçalho se faltar coluna) recebe uma linha por aviso (data, tipo, número, assunto, data da resposta, link, situação). Com `--email`, envia também um resumo HTML via Gmail SMTP (secrets `GMAIL_*`; destinatários em `RESPOSTAS_EMAIL_TO`, reserva `GMAIL_TO`) — só quando há novidades, distinguindo mérito de trâmite. `--email` sem as credenciais é falha (sai 2).
- **Agendamento:** GitHub Actions (`.github/workflows/respostas-executivo.yml`), cron `31 8 * * 1-5` (05h31 BRT) e `31 14 * * 1-5` (11h31 BRT, para o dia em que a Câmara recusou conexão de manhã), dias úteis; `concurrency: planilha-controle` (uma execução por vez). O GitHub atrasa o agendamento: em out/2026 a das 08:31 UTC começava entre 13h e 18h UTC.
- **Painel de Requerimentos & Respostas (`requerimentos.html` + `requerimentos-app.js`):** cartão "Requerimentos" na seção Bases de dados do hub. `respostas-executivo/export.py` lê a aba `requerimentos` da planilha (via Sheets API, reusando `_google_services`/`_idx_header` de `index.py`) e gera `requerimentos-index.json` na raiz — array com número, ano, assunto, datas, situação, `respondido` e `url_resposta`. **O índice é público: só saem as chaves de `CAMPOS_PUBLICOS` (`export.py`)** e o `main()` aborta com exit 1 se aparecer outra. A coluna interna "Status atual" da planilha **não vai ao site** — até out/2026 ela era publicada e exibida como "Situação", vazando anotações do gabinete ("ok (Falar com o Rui)", "não sei se cabe reiterar", links de entrega de documentos). A coluna "Situação" do painel mostra os rótulos públicos da classificação (`SITUACAO_ROTULO` em `requerimentos-app.js`, espelho de `classificar.ROTULOS`). Linha cujo Número não casa `^\d{1,5}/\d{4}$` (ex.: data, como as linhas-fantasma de set/2026) é descartada com aviso. A lógica de montagem vive em `montar_itens()` (testável sem Google: `testes_export.py`). **A coluna `Resposta` é uma fórmula `=HYPERLINK(...)`**, então o export lê com `valueRenderOption="FORMULA"` e extrai a URL do Drive por regex. O painel (vanilla, sem acento, paginado) tem busca + filtros de ano/situação e link para a pasta no Drive (exige login do gabinete) ou badge "Pendente". O JSON é gerado e commitado pelo passo final do `respostas-executivo.yml` (com guarda anti-base-vazia). **O export roda mesmo se o crawler falhar** (`if: !cancelled() && testes ok`; só lê a planilha): até out/2026 ele era pulado quando a Câmara recusava conexão, e o JSON no ar ficou dias com a coluna interna depois da correção. **`.github/scripts/checar_publicos.py`** confere o JSON JÁ PUBLICADO contra a lista branca (lida do `export.py` pela árvore sintática, sem importar — o export puxa `requests`) no `testes.yml` e no `bases-atualizacao.yml` diário; base nova com dado da planilha entra no dicionário `bases()`. `--dry-run` no export imprime contagens sem gravar.

## Diagnóstico somente leitura e regras de escrita (R0, out/2026)

**Regra do usuário (20/10/2026): nada que a equipe escreve à mão é apagado ou sobrescrito, em
nenhuma linha.** O robô só preenche célula vazia das colunas dele (ou atualiza as de resposta
quando chega documento novo), grava só valor (nunca formato), não apaga nem ordena linha, não
mexe em nota/comentário e trata coluna sem título com conteúdo como da equipe.

- **`planilha.py`**: `numero_canonico()` ("0845/2026" → "845/2026"; None para o que não é
  nº/aaaa) — a chave de um pedido em todo o módulo; `somente_leitura(cliente)` embrulha o
  cliente do Sheets/Drive e levanta `EscritaBloqueada` em qualquer método que grave
  (`METODOS_ESCRITA`, lista fechada). Obrigatório em diagnóstico, simulação e `--dry-run`.
- **`camara.py`**: listagem pública por autor (`filtro.php?pesquisa_autor[...]`, tipo 1 =
  Requerimento, 3 = Indicação; 20/página, latin-1). **A numeração dos requerimentos é por
  subtipo** ("Requerimento Nº 10/2025" ≠ "Requerimento de Homenagem Nº 10/2025"). Fixtures em
  `fixtures/camara/*.htm` (`.htm`: o `checar_versoes` varre `*.html`).
- **`diagnostico.py`** (`--detalhe` local, `--json`, `--sem-camara`, `--sem-drive`): mapa das
  colunas (com dono), números fora do padrão, grupos repetidos e, nas repetidas, conteúdo da
  equipe/nota/comentário; pastas sem situação ou sem PDF de resposta; picos do `Log diário` por
  tipo; conciliação com a Câmara. Saída padrão só com contagens.

**Retrato de 19/10/2026** (base para comparar os lotes seguintes):
- `requerimentos`: 625 linhas, 0 repetidas, 587 com pasta (5 sem situação). Colunas da equipe
  preenchidas: Secretaria, Status atual, **Situação** (manual, 28), observação. "Prazo",
  "Ordem" e "Data do Protocolo na PMS" estão vazias (criadas em 12/10).
- `indicações`: 887 linhas, 562 números; **318 pares + 3 trios** (324 linhas a mais), 321
  "limpas" e 3 com "sta" diferente nas duas linhas. **"Data do Protocolo na PMS" (357) e "Prazo"
  (362) são preenchidas pela equipe nesta aba.** Nenhuma nota nem comentário na planilha.
- **Origem das repetidas: 20/08/2026** — 321 indicações no `Log diário` num só dia (leitura da
  aba falhou, mapa vazio, toda indicação já respondida virou "linha nova").
- Câmara × planilha: faltam **127 requerimentos** (116 aprovados, 7 sem votação, 4
  encaminhados) e **281 indicações** (todas encaminhadas). Na planilha: 1/2026 e 5/2026 são
  "Requerimento de Convite"; 6680/2025 e 6995/2025 não são indicações do autor.
- **Moção 19/2026 caiu na pasta e na linha do Requerimento 19/2026**: tudo que não é indicação
  vai para `requerimentos` e para a pasta `REQUERIMENTO_<nº>` (`aba_do_item`, `processar_item`).
- `Log diário`: 19.317 linhas (~570 requerimentos/dia até 12/10, o reprocessamento já corrigido).

## Correções do robô (R1 e R2, out/2026)

- **Só requerimento e indicação vão às abas** (`aba_do_item` devolve None para moção, convite,
  homenagem…; o item conta como "fora das abas", não como falha). Título sem tipo (layout da
  Câmara mudou) e número fora do padrão contam como falha.
- **"Respondido" falso:** o PDF já arquivado é rebaixado só para classificar. Se a Câmara não
  o entrega, vale a cópia do Drive (`baixar_drive`); sem nenhuma das duas, o item fica **sem
  veredito nesta passada** — antes virava INDETERMINADO, que conta como mérito, e o item nunca
  mais era reclassificado. A "falha segura" continua só para PDF lido sem camada de texto.
- **Só PDF de verdade** (`_eh_pdf`: `%PDF` no início): página de erro em HTML não sobe ao Drive.
- **Sem nenhum PDF de resposta arquivado, nada vai à planilha** (`processar_item` devolve
  `sem_pdf`; o item conta como falha e é tentado de novo na execução seguinte).
- **`carregar_planilha` aborta** (RuntimeError, nada gravado) se não ler uma aba, se ela vier
  com menos de `MIN_LINHAS` (100) linhas ou sem a coluna do número — o mapa vazio de 20/08/2026
  criou as 321 linhas repetidas. Chave = `numero_canonico`; número repetido: vale a última
  linha (a que o robô mantém) e o total vai para o aviso.
- **Leitura sem limite de coluna** (`'aba'` em vez de `A1:Z`, também no export e no
  reclassificar) e `_col_letra` além de Z.
- **`garantir_colunas`** põe a coluna nova depois da última coluna com QUALQUER conteúdo
  (coluna sem título com anotação é da equipe), grava só as células novas do cabeçalho e
  acrescenta colunas à grade se faltar (`appendDimension`).
- **Export de requerimentos:** pasta no Drive sem veredito sai como **`a_classificar`** (painel:
  "Resposta a classificar"), não mais "respondido" — 5 itens em 19/10/2026 (2611, 3611, 3688,
  5313/2025 e 3272/2026); continuam na conta do prazo.

## Escrita planejada e falha à vista (R3, out/2026)

- **Motor (`planilha.aplicar`)**: o laço não grava célula a célula; acumula `Escrita`/`NovaLinha`
  e aplica a cada `LOTE_ITENS` (50) itens ou `LOTE_SEG` (8 min) e no `finally`. Na hora de
  gravar **relê a aba** e resolve cada escrita **pelo número** (a equipe pode inserir/mover linha
  durante os 25 min da varredura). Garantias com teste (`testes_plano.py`): só colunas do robô
  (`COLUNAS_RESPOSTA`, + `COLUNAS_CRIACAO` em linha nova; outra coluna → `EscritaProibida` antes
  de gravar qualquer coisa); em linha existente só preenche **célula vazia** — sobrescrever exige
  `resposta_nova` e vale só para as 4 colunas de resposta; valor vazio nunca é gravado (seria
  limpar); linha nova entra depois da última linha com conteúdo e recebe **só as células do robô**
  (número sempre canônico); uma só chamada `values.batchUpdate` (valores, nunca formato). Célula
  do robô já preenchida com outro valor vira **divergência** (contada no log), não é sobrescrita —
  inclusive a "Data da resposta" acertada à mão, que antes era regravada a cada execução.
  **Data é comparada pelo valor** (`UNFORMATTED_VALUE`, nº de série — `_chave_data_celula`), não
  pelo texto: 93 células de `requerimentos` e 167 de `indicações` exibem m/d/aaaa ("5/20/2026" =
  20/05), e comparar o texto deu 96 divergências falsas no 1º `--planejar` da produção (20/10).
- **Novidade e aviso**: novidade = PDF de resposta arquivado agora **ou a marca de aviso
  pendente na subpasta** (`appProperties` `aviso=pendente`, invisível para a equipe; gravada
  ANTES de subir a resposta). Vai ao log/e-mail o item com mudança real gravada (linha nova,
  primeira resposta, resposta nova) ou com a marca. A marca vira `avisado` só depois que o log
  e o e-mail deram certo: execução que cai no meio (timeout, erro) deixa a marca e a seguinte
  avisa — antes, o e-mail dessas respostas se perdia para sempre. Se o log deu certo e o e-mail
  não, a linha do log se repete na próxima (preferível a perder o aviso).
- **Retentativa** (`_executar`: rede, 429, 5xx) em **toda** chamada ao Drive e ao Sheets, via
  `planilha.com_retentativa` no `main` (o baixador de PDF do Drive recebe a requisição
  desembrulhada com `planilha.desembrulhar`).
- **Orçamento** `--orcamento-min` (28): a varredura para e grava, registra o log e manda o
  e-mail antes do timeout de 35 min do job. O passo principal levava 8–23 min em out/2026.
- **Códigos de saída**: 1 = busca vazia em todos os anos (layout da Câmara) ou planilha
  ilegível; 2 = item com erro, lote não gravado, log/e-mail/marca que falhou ou orçamento
  esgotado. Contagens (nunca texto da planilha nem mensagem de erro) em `GITHUB_STEP_SUMMARY`.
- **`--planejar`**: Drive e Sheets sob `somente_leitura`; `processar_item(simular=True)` lê
  pastas e PDFs mas não cria pasta, não sobe, não apaga cópia repetida nem marca; `aplicar(...,
  gravar=False)` faz a conta contra a planilha de agora. Imprime só contagens.
- **Workflow**: inputs `planilha` (`producao`|`teste` → secrets `SHEET_ID_TESTE`/
  `DRIVE_FOLDER_ID_TESTE`; sem e-mail e sem export/commit) e `planejar` (sem export/commit).
- **`--forcar`/`--cods`** avisam mesmo sem mudança (testar/reenviar e-mail), mas **não
  sobrescrevem** nada preenchido.

## Auditoria dos "respondido" (R1c) e mescla das indicações repetidas (R4), out/2026

- **`reclassificar.py --comparar`** (só leitura; plano em `%TEMP%/reclassificar-plano.json` com
  hash) revê pelas cópias do Drive cada linha "respondido" (a última de cada número) e lista as
  que são só trâmite/pendente; pasta com **dois arquivos PEDIDO_** (documentos de dois pedidos,
  ex.: Moção 19/2026 na pasta do Requerimento 19/2026) é recalculada pela página da Câmara do
  pedido certo (`camara.listar_autor` → `index.processar_item(simular=True)`).
  **`--aplicar-divergentes <hash>`** grava só essa lista via `planilha.aplicar`, só nos itens que
  estão como na simulação; quem deixa de ser "respondido" perde a data de mérito
  (`Escrita.limpar`, que exige coluna de resposta e correção autorizada). O backfill sem flag
  agora **só preenche célula vazia** (antes regravava a situação de todo mundo).
- **`mesclar_indicacoes.py`** (simula por padrão; `--detalhe` local; `--aplicar <hash>`): por
  número repetido, fica a 1ª linha (a da equipe, onde a equipe a pôs), que recebe nas colunas do
  robô os valores da linha oficial (`export.linha_oficial`), a ementa na coluna nova do robô
  **"Ementa (Câmara)"** e, em célula vazia, valor da equipe que só exista na outra linha; sai a
  outra linha só se estiver limpa. **Conflito não é mexido**: coluna da equipe diferente, coluna
  do robô com outro valor na linha que fica ("SIM" digitado na Resposta), data da sessão
  diferente, nota na linha que sairia, ou item publicado que mudaria (o export é refeito com o
  grupo mesclado). `--aplicar`: refaz a simulação e exige o mesmo hash (conteúdo, não posição);
  recusa planilha com comentário aberto; **duplica a aba e confere a cópia** antes de tudo;
  grava valores (USER_ENTERED) e apaga, num único `spreadsheets.batchUpdate` de baixo para cima,
  só as linhas que continuam idênticas às da simulação. Produção em 20/10/2026: 321 grupos →
  317 limpos; 4 conflitos para a equipe (trios 7238/2025, 7438/2025, 845/2026 com "sta"
  diferente; 7441/2025 com sessão 27/11 × 25/11).
- **Export de indicações** lê "Ementa (Câmara)" e a prefere ao "Assunto" (resumo da equipe): o
  texto publicado não muda com a mescla.

## Pré-cadastro (R5, out/2026)

- **`precadastro.py`** + `camara.listar_autor(..., parar=)`: a linha de cada pedido do mandato
  entra na planilha assim que é protocolado (antes só com resposta; em 19/10/2026 faltavam 127
  requerimentos e 281 indicações). Requerimentos: só o subtipo "Requerimento"; indicações: todas.
  Linha nova (via `planilha.NovaLinha`): Número canônico, Assunto (= ementa; a equipe pode
  encurtar), **"Ementa (Câmara)"**, Data da Sessão e **"Situação na Câmara"** — Secretaria,
  Bairro e observações seguem com a equipe.
- **"Situação na Câmara"** é o espelho da listagem ("-" = não votado, "Aprovado",
  "Encaminhado") e a única coluna que o robô **regrava** quando muda (`COLUNAS_ESPELHO` no
  motor). **Prazo da LOM só depois do envio**: `prazos.enviado()` — vazio (linha antiga) ou
  Aprovado/Encaminhado = enviado; senão o export de requerimentos sai sem `vence_em` (não conta
  "fora do prazo"). O export de requerimentos também prefere "Ementa (Câmara)" ao "Assunto".
- **No robô diário** (`index.executar_precadastro`, antes da busca de respostas — a resposta de
  pedido novo já acha a linha): liga com a variável do repositório **`PRECADASTRO_ATIVO=true`**
  (env no workflow); desligado, só conta ("Pré-cadastro … (desligado: só contado)" no resumo).
  Ligado, `garantir_colunas` cria as 2 colunas novas. Varredura: para depois de 2 páginas
  seguidas sem pedido novo nem situação mudada; completa às segundas e na 1ª vez (espelho vazio).
  Pedido novo vai ao `Log diário` (coluna nova **"Origem"**: `resposta` | `pré-cadastro`) e ao
  e-mail, na seção "N pedido(s) novo(s) — completar Secretaria e Bairro".
- **CLI**: `precadastro.py` (simula + **conciliação**: números da planilha que na Câmara são de
  outro subtipo — 1/2026 e 5/2026 são "Requerimento de Convite" — ou não são do autor, com o
  provável número certo pela ementa; `--detalhe` lista, só localmente) e `--aplicar` (1ª carga).
- **Impacto público**: os pendentes sobem (requerimentos sem mérito ~87 → ~210; indicações
  ~190 → ~470) — são pedidos que nunca tinham sido cadastrados. A assessoria para de digitar
  linhas novas.

## Cobrança do Executivo — prazo da Lei Orgânica (out/2026)

- **Regra (`prazos.py`)**: LOM art. 58, XVIII — informações "dentro de quinze dias (...), salvo
  prorrogação, a seu pedido e por igual período" (texto conferido no Legis, doc. 9596).
  `vence_em` = sessão + 15 dias corridos (+15 se `so_prorrogacao`); vazio para respondido. Conta
  da **data da sessão**: a planilha não registra o protocolo na Prefeitura (as colunas "Data do
  Protocolo na PMS" e "Prazo" existem e estão vazias) — o painel diz isso na nota de método. Em
  17/10/2026: 0 de 530 respostas de mérito em ≤15 dias, 116 em ≤30, mediana 43; 87 sem mérito,
  todos vencidos.
- **Secretaria (`secretarias.py`)**: sigla da coluna "Secretaria" da planilha (texto livre da
  assessoria, ~75% preenchida), com sinônimos unificados (COMUNICAÇÃO→SECOM, SAÚDE→SMS,
  SED´S→SEDS) e o que não é secretaria esvaziado ("NÃO SEI", "#NAME?", "GERAL", "EMPRESAS", nome
  de fornecedor). Atenção ao NFKD: o acento agudo solto vira espaço ("SED S").
- **Desdobramentos**: `cita` = pedidos anteriores citados no assunto ("Resposta ao requerimento
  210/2025 - …"), só os que existem na base; o painel monta a volta ("desdobrado em").
- **Tempo até a resposta, por secretaria** (M6, out/2026): dentro de "Atraso por secretaria", um ponto
  por pedido (ECharts via `Comum.grafico`, dispersão com `jitter` do v6): cheio = respondido (dias da
  sessão ao mérito), vazado = sem mérito (idade); eixo **logarítmico** com marcos (15/30 d, 2/3/6
  meses, 1 ano — na linear o espalhamento desistia de ~140 pontos); linhas de 15 e 30 dias; traço
  dourado = mediana; segue o filtro de ano e a regra de cobertura; clique no ponto = foco `?n=`.
- **Painel**: número-manchete no topo (sem resposta de mérito na base inteira — os KPIs abaixo
  seguem o filtro; "todos fora do prazo de 15 dias da Lei Orgânica" só com `vence_em` no
  índice); KPIs com mediana (não média) e "N de M em até 15 dias"; coluna Prazo em texto
  ("há 555 dias · venceu em…"); filtros `prazo` (fora / respondidos depois de 15 / em até 15),
  `sec` e `ordem` (mais recentes = padrão, mais atrasados, número) na URL; `?n=` mostra um pedido
  e os que o desdobram; "Copiar reiteração" (texto-base, revisar antes de protocolar) e "Copiar
  lista de cobrança" via `Comum.copiar`; **resumo público por secretaria** (decisão do usuário,
  17/10) só com cobertura ≥ 50% no ano filtrado, siglas com < 5 pedidos agrupadas em "Outras".
  Índice antigo (sem `vence_em`) degrada: filtros de prazo/secretaria e o resumo somem.
- **`garantir_colunas` só cria as colunas de classificação** (as que a automação grava). Antes
  completava todas as de `ABAS` e, em 12/10/2026, criou "Ordem", "Prazo" e "Data do Protocolo na
  PMS" vazias no fim da aba — podem ser apagadas à mão sem que voltem.

## Indicações & Respostas — export, bairros e mapa (out/2026, M5)

- **Export** (`export.py --indicacoes [--dry-run]`, mesma planilha, aba `indicações`) →
  `indicacoes-index.json` na raiz. Lista branca **`CAMPOS_PUBLICOS_INDICACOES`** (`numero`, `ano`,
  `assunto`, as 3 datas, `situacao`, `respondido`, `url_resposta`, `bairro`, `regiao`); `main`
  sai 1 com chave fora dela **ou com CPF/e-mail no assunto** (`dados_pessoais`; telefone só
  avisa). O export só lê as colunas de `COLUNAS_INDICACOES`: **"sta", "A contento" (anotações
  como "pediu número"), "Prazo" e "Data do Protocolo na PMS" nunca saem de `linhas_indicacoes`**.
  O caminho de requerimentos ficou byte a byte igual (conferido contra o `HEAD` anterior).
- **Linhas repetidas**: 887 linhas → **562 indicações** (out/2026; 318 números com 2 linhas, 3
  com 3, 1 linha sem número descartada). A linha da assessoria (resumo curto + bairro, datas
  exibidas em M/D) e a que o robô anexou depois (ementa da Câmara, datas dd/mm, mérito) são a
  mesma indicação. `linha_oficial`: a última com data de mérito; senão a última com a sessão no
  formato do robô (`_formato_robo`: exibida dd/mm/aaaa); senão a última da aba (o robô anexa no
  fim). Texto e datas: da oficial, depois das outras na ordem da aba. Bairro: o 1º texto que o
  normalizador reconhece. Situação: a mais forte entre as linhas (respondido > só encaminhamento
  > só prorrogação > pendente); sem nenhuma, **`a_classificar`** se há sinal de documento (pasta
  no Drive, "SIM" na coluna Resposta, data de resposta) — senão `pendente`. A situação publicada
  sai sempre desse vocabulário (texto estranho na coluna é ignorado). Número com zero à
  esquerda é normalizado ("0845/2026" → "845/2026").
- **Datas**: a planilha é pt_BR — o nº de série (UNFORMATTED) é o mesmo nas duas linhas; vale
  ele. Texto só se for dd/mm/aaaa válido; ano com um dígito a mais ("18/03/82025") é consertado
  quando bate com o ano do número. Divergência entre linhas (7441/2025: 27/11 × 25/11): vale a
  do robô.
- **Bairro** (`bairros.py`, modelo `secretarias.py`): a coluna é texto livre e já trouxe
  anotação interna ("RESPOSTA EM 07 MESES") — **o texto cru nunca é publicado**. `canonico(t)` →
  (nome oficial do GeoJSON, região) ou (None, None): sem acento/caixa/pontuação, acento solto
  ("P´RAIA"), "JD."→Jardim, sufixo "- ZN", "Morro do X"→"Morro X" se existir, `SINONIMOS`
  (Jardim Castelo → Castelo, Apartecida → Aparecida…) e `REGIOES` (Orla, Zona Noroeste, Morros,
  Área Continental, Centro Histórico, "GERAL" = Cidade toda; nunca repartidas entre bairros).
  Não reconhecidos ficam vazios: Itararé (São Vicente), CET, Morro do Ilhéu (só há "Ilhéu
  Alto"), População de rua. Out/2026: 362 num bairro do mapa (64%, 29 bairros), 34 em região,
  166 sem bairro reconhecível. Testes com as 47 grafias reais: `testes_bairros.py`.
- **Geo** (`geo/preparar_bairros.py`, só stdlib; `geo/README.md`): GeoServer da Prefeitura,
  camadas `santos:bairros` (72 feições, 71 nomes) e `santos:subprefeituras` (marca
  `area_continental`: 11 bairros, inclusive as ilhas de Barnabé e Bagres); Douglas–Peucker de
  4 m, 5 casas, ~113 KB; licença não declarada pelo serviço [Verificar]. Rodar de novo só se a
  Prefeitura mudar o abairramento — os nomes alimentam o normalizador e a guarda.
- **Log público**: o `--dry-run` local lista as grafias não reconhecidas e os resumos
  descartados da assessoria; a execução normal (workflow) só imprime contagens — o log do
  Actions de repo público é público.
- **Guarda** (`.github/scripts/checar_publicos.py`): além das chaves, confere os VALORES de
  `bairro` (nomes do GeoJSON) e `regiao` (`REGIOES` lido pela árvore sintática) e aponta só o
  número dos itens, nunca o valor.
- **Workflow**: passo próprio "Exportar indicacoes-index.json" (mesmas condições do de
  requerimentos, guarda anti-vazio com exit 1); o commit leva só o arquivo cujo passo deu certo.
  Fora da guarda de frescor de propósito (`ISENTAS` em `frescor_bases.py`): as respostas a
  indicações vêm em lotes espaçados (51 dias sem nenhuma em 18/10/2026).
- **Sem prazo legal**: indicação não tem o prazo do requerimento (LOM art. 58, XVIII) — o painel
  e o hub nunca falam em "fora do prazo"; `so_prorrogacao` vira "Pedido de prorrogação".

## Nem todo anexo é resposta (`classificar.py`)

A Prefeitura manda três coisas pelo mesmo canal "Resposta anexada", e contar as três
como resposta inflava o painel (era 92% de respondidos):

1. **Pedido de prorrogação de prazo** — ofício do Gabinete pedindo mais 15 dias (art. 58,
   XVIII da LOM). Vem **em lote**: um único ofício citando dezenas de requerimentos,
   arquivado dentro da pasta de cada um. O Ofício 512/2025 sozinho cobriu 18 itens.
2. **Ofício de encaminhamento** — "cumpre-nos encaminhar a essa Casa Legislativa os
   esclarecimentos prestados pela Secretaria X". É o envelope.
3. **Resposta de mérito** — o que de fato responde.

`classificar.py` decide pelo texto do PDF (regex, sem IA — os documentos são formulários
fixos). Armadilhas que a regra já cobre, todas confirmadas em PDFs reais:

- **A ordem do nome não vale como critério**: em `1729/2026` o ofício é o `RESPOSTA_1`,
  em `2845/2026` é o `RESPOSTA_2`.
- **Ofício e resposta costumam vir NO MESMO PDF** (ofício na 1ª página, conteúdo na 2ª) —
  em 22 amostras, 21 eram assim. Por isso a regra corta o texto na fórmula de fecho
  ("...distinta consideração"), remove o rodapé e mede o que sobra: ofício puro deixa
  ~50 caracteres, ofício com anexo deixa 400+. Sem essa medida, quase toda resposta
  sumiria da contagem.
- **Resposta de mérito fala em prazo**: a SEFIN entrega processos por link dizendo "o prazo
  de acesso será de 30 dias" — não é prorrogação. E respostas sobre aditivos de obra citam
  "prorrogação do prazo" no corpo; o teto de tamanho (`LIMITE_TRAMITE`) barra o falso positivo.
- **Falha segura**: PDF sem camada de texto vira `indeterminado` e **conta como mérito**.
  Nunca rebaixar um item por não conseguir ler o arquivo.

Situações agregadas: `respondido` · `so_prorrogacao` · `so_encaminhamento` · `pendente`.
Quando só há trâmite, `so_encaminhamento` tem prioridade — indica anexo faltando, que vale
conferir à mão. **Nada é apagado do Drive**: o pedido de prorrogação é prova de
descumprimento do art. 58, e apagá-lo faria o crawler rebaixar o mesmo PDF no dia seguinte,
disparando alerta falso de "resposta nova".

**Custo**: classificar rebaixa o PDF. Por isso o crawler só reclassifica itens cuja situação
ainda não é `respondido` (`classificar_tudo` em `processar_item`), e o backfill pula
qualquer arquivo ≥ 1 MB (anexo grande nunca é ofício — os observados têm 112–200 KB).

`reclassificar.py` é o backfill, uso pontual: varre as subpastas do Drive (não depende do
site) e preenche `Situação da resposta`. Tem cache versionado — **incrementar `CACHE_VERSAO`
ao mudar qualquer regra**, senão a rodada seguinte reaproveita veredictos obsoletos.
A `Data da resposta de mérito` **não** é preenchida por ele: a data de recebimento vem da
página da Câmara, não do Drive. Quem preenche é o crawler — e, nos itens que o backfill já
marcou como respondidos, só com `index.py --forcar` (que liga `classificar_tudo` para todo
mundo; rodada longa, ~1h). Enquanto a coluna estiver vazia o painel cai em `Data da
resposta`, que na prática coincide na maioria dos casos (o bloco mais recente costuma ser
justamente o de mérito).

**Painel sem classificação na base (2026-10):** enquanto nenhuma linha do índice tiver
situação além de `respondido`/`pendente` **e** nenhuma `data_resposta_merito`, a base não foi
classificada (desde R1, pasta sem veredito sai `a_classificar`, que já conta como classificada) —
e o painel (`baseClassificada()` em `requerimentos-app.js`) **não
fala em mérito**: rotula "com algum retorno da Prefeitura (inclui prorrogações; classificação de
mérito pendente)", troca o texto do topo, os rótulos do filtro e some com os filtros de trâmite.
Basta uma linha classificada para voltar à métrica de mérito.

## Comandos úteis

```bash
# Respostas do Executivo — testar scraping sem escrever (Drive/Sheets)
python respostas-executivo/index.py --dry-run --limite 3

# Respostas do Executivo — o que seria gravado, lendo Drive e planilha (só leitura, em código)
python respostas-executivo/index.py --planejar

# Respostas do Executivo — rodar de verdade (ano corrente)
python respostas-executivo/index.py

# Respostas do Executivo — ano específico
python respostas-executivo/index.py --ano 2026

# Classificador, exports e bairros — testes (PDFs reais como fixture; sem Google)
python -m unittest discover -s respostas-executivo -p "testes_*.py"

# Indicações — contagens e detalhe (grafias não reconhecidas) sem gravar; depois de verdade
python respostas-executivo/export.py --indicacoes --dry-run
python respostas-executivo/export.py --indicacoes

# Limites dos bairros (só se a Prefeitura mudar o abairramento)
python geo/preparar_bairros.py --dry-run

# Backfill da classificação (relatório sem gravar; depois de verdade)
python respostas-executivo/reclassificar.py --dry-run
python respostas-executivo/reclassificar.py
```
