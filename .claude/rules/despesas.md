---
paths:
  - "despesas/**"
  - "despesas.html"
  - "despesas-app.js"
  - "favorecido.html"
  - "favorecido-app.js"
  - "retrospectiva.html"
  - "retrospectiva-app.js"
  - "favorecidos/**"
  - "explorador.html"
  - "explorador-app.js"
  - "explorador-worker.js"
---

# Base de Despesas (`despesas/` + `despesas.html`)

Consolidação da **execução da despesa da Prefeitura de Santos** (empenhado→liquidado→pago), a partir
da API pública do Portal da Transparência. `despesas/crawler.py` baixa **três endpoints** do
`transparencia.asmx`, cada um um estágio: `json_empenhos` (empenhado), `json_liquidacoes` (liquidado)
e `json_pagamentos` (pago) — todos `?ano=&mes=`, **um mês por requisição**; a resposta é um
**XML SOAP `<string>` com array JSON embutido como texto** (extrai `.text`, `html.unescape`,
`json.loads`) e é a **fotografia completa do mês** na origem (não há campo de versão nem de
exclusão). Cada estágio vai para sua tabela (`empenhos`/`liquidacoes`/`pagamentos`). **Atenção:** os
campos `empenho`/`liquidacao`/`pagamento` são **números de documento**, não valores — o valor de cada
estágio é a coluna `valor`. Os campos **`tipo_pagamento`/`tipo_liquidacao`** (`Orçamentária`, `Extra
Orçamentário`, `Restos a Pagar Processados/Não Processados`) são a classificação DA FONTE e mandam
na classificação das linhas (abaixo).
**A API devolve misturada a entidade-demo da plataforma Portal TP** ("PREFEITURA MUNICIPAL
DEMONSTRAÇÃO", dados de um município de Rondônia — R$ 696 mi em 2025 detectados no levantamento de
2026-07): o crawler descarta na coleta (`UG_EXCLUIR="DEMONSTRA"`) e **expurga do cache** a cada
execução (`expurgar_demo()` em `abrir_db`). **A origem muda a largura dos códigos sem aviso**: desde 2026-09-30 os nºs de empenho/liquidação/pagamento vêm com 8 dígitos e, desde 2026-08, o `grupo_despesa` com 11 — `normalizar()` devolve tudo à largura histórica (`numero_documento`, `codigo_grupo`), senão o casamento `UG|nº` por texto exato quebra (72% de "não localizado" em out/2026). `verificar.py` falha se um mês passar de 25% do pago sem empenho localizado. **A API NÃO expõe unidade orçamentária (secretaria)**; o
único campo de unidade é `unidade_gestora` (a entidade: Prefeitura, CAPEP, IPS, fundações). O recorte
por órgão usa **`funcao`** como proxy de área/secretaria.

## Reconciliação por partição (esquema v2 do SQLite, 2026-09)

Até 2026-09 a gravação era `INSERT OR IGNORE` por hash das colunas-chave (com o valor): um
pagamento corrigido de 100 → 80 virava 180, linhas removidas da origem ficavam para sempre e
linhas legítimas idênticas (lotes de depósitos judiciais) eram descartadas. Agora **cada recarga
substitui a partição `(fonte, ano, mês)` inteira numa transação** (`reconciliar()`), depois de
validar a resposta: estrutura (lista de objetos, campos obrigatórios, datas dentro do mês,
`valor` numérico — `RespostaInvalida` mantém a partição); **resposta vazia** para partição que já
tinha linhas e **queda abrupta** (< `LIMITE_REDUCAO`=70% das linhas ou do |valor|) são
`ParticaoSuspeita` — mantém a anterior salvo `--aceitar-vazio`/`--aceitar-reducao`; após gravar,
conta e soma o banco contra a resposta (divergência → ROLLBACK). O que saiu ou mudou vai para
**`linhas_historico`** (motivo `removido`/`substituido`/`duplicidade_sistematica`, conteúdo em
JSON) e cada execução deixa uma linha em **`historico_reconciliacao`**; `controle_carga` guarda por
partição registros/soma/brutos/descartados/`status` da última tentativa (`ok`/`suspeito`/`erro`)
e `erro`. Identidade da linha = `hash` md5 de TODO o conteúdo + `repeticao` (ordinal entre
idênticas) — `UNIQUE(hash, repeticao)`. **Esquema v1 detectado (sem tabela `meta`) → backup
`despesas.sqlite.bak-v1-*` e tabelas recriadas: todas as partições são rebaixadas** (é o que o
cache do Actions faz na 1ª execução após o merge; ~63 requisições).
**Códigos de saída:** 0 ok · 1 nenhuma coleta funcionou (aborta o pipeline) · **2 falha parcial**
(as partições boas foram atualizadas; o workflow publica e termina vermelho no passo final,
com a lista no resumo do job). `--bruto-dir DIR` guarda/reusa as respostas brutas (cache
reprodutível para reconstrução e testes); `--db X` usa outro banco (candidato).

**Duplicidade sistemática da origem.** A granularidade exposta não distingue linhas idênticas
legítimas (um lote de depósitos judiciais tem itens de valor igual; anulações com valor 0
repetidas) de defeito. Em 2026-09 a API passou a devolver lotes inteiros de jan–mai/2026
repetidos (×2) — 32–54% das linhas de um dia, R$ 130 mi só em pagamentos de 2026-05. Regra
(`tratar_duplicidade`, dois níveis): **(a)** por (unidade gestora, dia), ≥ 90% das linhas distintas
repetidas; **(b)** pela partição, ≥ 50 linhas distintas repetidas e ≥ 5% das distintas (nos meses
limpos de 2025 a taxa fica entre 0,02% e 3%). Dentro do padrão cada grupo idêntico fica com **uma
linha** (pares legítimos são < 0,2% nos meses limpos; em 2026-05 havia 300 grupos ×4 que só o
defeito explica — contados em `multiplas` no diagnóstico); fora desses padrões **todas** as linhas são mantidas. O
descarte fica em `controle_carga.descartados/soma_descartada/duplicidade`, em `linhas_historico`,
no bloco `cobertura` do índice e vira alerta de classe **inconsistência de dados** — nunca é
silencioso.

## Mês incompleto na origem — conciliação com o TCE-SP (2026-10)

A API da Prefeitura publicou **jan/2025 pela metade** sem aviso: R$ 69 mi empenhados e 1.166
pagamentos (R$ 12,7 mi) no portal, contra R$ 2,93 bi empenhados no TCE-SP — os empenhos globais do
ano. Fev/2025 também veio parcial (liquidado sem restos 13,5% abaixo). Conferido ao vivo em
2026-10-30: a origem ainda devolve o mesmo — é lacuna da Prefeitura, não do crawler. Sem marcar,
o "Em resumo" dizia "+27% sobre 2025" (mar–set comparável: +11%), 3 alertas de crescimento eram
artefato (Correios, Cortinas JF, Tarara), 7 meses viravam "fora do padrão" no gráfico, a
publicidade "+71%" (comparável: +49%), o fim de exercício inflava (liquidado 1,64× → 1,48×) e a
retrospectiva chamava janeiro de "mês mais leve".
- **`despesas/tce.py`** baixa `transparencia.tce.sp.gov.br/api/json/despesas/santos/{ano}/{mes}`
  (sem token; o que o município enviou ao AUDESP) e grava **`despesas/conciliacao-tce.json`**
  (versionado, `indent=1`, só muda quando um número do TCE muda — cada mês leva `obtido_em`). Por
  execução: meses sem referência + os 3 mais recentes (`--todos` rebaixa tudo). Totais sem a
  **Câmara** (não está no portal da Prefeitura): empenhado líquido = Empenhado + Reforço −
  Anulação; Valor Liquidado; Valor Pago (estornos negativos somados). TCE fora do ar: mantém o
  estado e o workflow segue (`|| echo ::warning`).
- **`export.conciliacao_tce` / `cobertura_conciliada`** (export E briefing usam a mesma): por mês,
  base × TCE no **empenhado** e no **liquidado sem restos a pagar** (o TCE conta só o do
  exercício — jan/2026 parecia 30% "acima" até tirar os R$ 92 mi de restos). Calibração (2025-03 a
  2026-08): empenhado bate ao centavo; liquidado ≤ 2,87%. **Base abaixo além de `TCE_LIMITE` 5% (e
  de `TCE_PISO` R$ 1 mi) = `incompleto`**; acima = `acima` (só informativo + aviso no `verificar`);
  sem dado no TCE = `sem_referencia` (o TCE recebe com ~1–2 meses de atraso); posterior ao último
  mês completo = `parcial`. O "Valor Pago" fica registrado mas não entra (difere 6–16% do pago sem
  extra nos meses íntegros — outra semântica). Índice: `cobertura.conciliacao_tce` (mês a mês) e
  **`cobertura.incompletos_origem`** (["2025-01", "2025-02"]).
- **Só marca, não preenche** (decisão do usuário, 2026-10-30): o mês incompleto sai do acumulado
  do ano (`resumo.yoy` ganha `periodo` "mar–set" e `excluidos`), da média de 12 meses, do
  destaque de função, do crescimento YoY (mesma janela), dos picos (mensal e locais), do fim de
  exercício (`meses_excluidos`; dezembro incompleto tira o ano), da comparação da publicidade
  (`comparacao.periodo`), do valor mensal típico de PF (e o "início dentro da base" conta do 1º
  mês íntegro); o ano não tem % de anulação (`anulacoes.por_ano[ano].incompleto_origem`) e a taxa
  de execução não é validada (motivo declarado). Alerta **`dados_incompleto_origem`**
  (inconsistência, média, sem teto) com os números dos dois lados.
- Painel: `mesIncompleto()` — "†" no eixo, trecho tracejado com ponto vazado (`dividirParciais`
  aceita meses fora da conta em qualquer posição; com só parciais no fim, a saída é a de antes),
  nota com a prova na dica (portal × TCE), fora da média dos desvios e da média móvel;
  calendário/diário com a mesma hachura/clareamento dos parciais e fora dos quintis da régua;
  card, hero e retrospectiva escrevem o período comparável. `verificar.py` (bloco 8): incompleto
  fora do acumulado e do fim de exercício e sempre com alerta.

## Identidade do favorecido (2026-09)

O Portal TP grafa o mesmo CNPJ de várias formas ("INSTITUTO DE PREVIDÊNCIA…", "INSTITUTO DE
PREVIDENCIA…", "IPREV - INST. PREV…"); o ranking agrupava por nome+documento e o dossiê por
documento, então o CNPJ 08.717.299/0001-01 tinha duas entradas (R$ 1,80 bi somadas) e um raio-X
com R$ 366 mi. **`formato.identidade_favorecido(nome, doc)`** dá a chave canônica: CNPJ completo →
`cnpj:<14 dígitos>`; CPF mascarado → `cpf:<dígitos visíveis>|<NOME NORMALIZADO>` (conservador:
dígitos parciais não unem pessoas — só o mesmo nome sem acento/caixa/espaços); documento atípico
→ `doc:…|nome`; sem documento → `nome:<NOME>`. `nome_exibicao()` escolhe a grafia
deterministicamente (sem U+FFFD > mais lançamentos > mais longa > alfabética) e o dossiê guarda
`grafias`. `slug_favorecido()`: CNPJ = 14 dígitos (**links `?f=<cnpj>` antigos continuam
válidos**); demais = md5 curto da chave (slugs de PF mudaram em 2026-09). O export cria a temp
table `fav_ident(nome, doc, chave)` e agrega **tudo** por identidade: ranking (`top_favorecidos`
com `chave`/`slug`/`grafias`), `totais.favorecidos` (identidades; `grafias_favorecidos` = nomes),
dossiês, `anos_detalhe`, alertas (`filtro.chave`), credores da dívida, `pf-resumo.json` e
`indice-favorecidos.json` (`versao: 2`, chaves = identidade; tem `fav` (meses da execução) e
`mov` (meses da movimentação)). **`Comum.identidadeFavorecido`/`nomeNormalizado` (comum.js) é o
espelho em JS** — o painel, a ficha e o raio-X filtram por ela; mudar um lado exige mudar o outro.
A consolidação **não altera a soma geral** (teste `test_ranking_consolida_grafias_do_mesmo_cnpj`).

## Duas visões: movimentação × execução (2026-09)

- **Movimentação no período** — cada lançamento conta no mês da SUA data. É a visão do Visão
  geral (séries mensais = pagamentos pela data do pagamento), da tríade `execucao.serie` (cada
  estágio pela própria data) e da aba Detalhamento em `?dv=mov`, alimentada por
  **`despesas/dados/mov/AAAA-MM.json`** (um documento E/L/P por linha, `campos_movimento`, colunas
  textuais codificadas por `dicionario` → ~2 MB/mês; `meses_movimento` no índice).
- **Execução dos empenhos** — uma linha por empenho no mês em que foi emitido, com liquidado/pago
  acumulados até a data da base (**`despesas/dados/AAAA-MM.json`**, `campos_detalhe`, `meses`).
  Aba Detalhamento em `?dv=exe` — **links antigos sem `dv` são execução**, o comportamento que
  sempre tiveram. Um empenho de janeiro pago em agosto aparece na movimentação de agosto e na
  execução de janeiro, nunca nos dois (teste `test_empenho_de_janeiro_pago_em_agosto_sem_duplicacao`).
  Título, filtros (`fase`/`especie` só em `mov`), colunas padrão, CSV (nome do arquivo + coluna
  "Recorte") e link citável carregam a visão. A ficha do empenho na movimentação acha os estágios
  pelo `periodo_empenho` da linha. O índice grava `conservacao` (pago da base = execução =
  movimentação) e o `verificar.py` confere.

## Cubo do Explorador de pagamentos (M9, 2026-10)

`exportar_cubos(movimento, ident)` grava **`despesas/dados/cubo/AAAA.json`**: os PAGAMENTOS do
ano — a fase P da movimentação, as mesmas linhas de `dados/mov/`, no mês da partição (= pela data do
pagamento) — agregados por mês × unidade gestora × tipo × favorecido × função × subfunção ×
programa × elemento × fonte × grupo, com `pago` (soma em centavos inteiros → 2 casas exatas) e `n`
(nº de documentos). É a tabela que o `explorador.html` monta num SQLite no navegador (página em
`site-frontend.md`).
- Contrato: `{"versao": 1, "ano", "campos": ["mes", "unidade_gestora", "tipo", "favorecido",
  "funcao", "subfuncao", "programa", "elemento_despesa", "fonte_recurso", "grupo_despesa", "pago",
  "n"], "campos_favorecido": ["chave", "nome", "documento"], "dicionario": {campo: [valores]},
  "linhas": [[…]]}` — as colunas 1 a 9 são índices no dicionário do campo; vazio da origem = `null`
  (o extra-orçamentário não tem função/subfunção/programa); o favorecido é a **identidade**:
  `[chave de formato.identidade_favorecido, nome de exibição do ranking, documento como a origem
  publica]` (o JS não recalcula a chave; agrupar só por nome junta homônimos e só pelo CPF mascarado
  junta pessoas).
- Inclui extra-orçamentário (pelo `tipo`) e anulações (negativas): o pago do ano é o de
  `totais.por_ano` e o de cada mês, o de `series_mensais`.
- **Determinístico**: linhas por (mês, −valor, texto), dicionários pela 1ª aparição (os maiores
  valores ganham índices curtos), JSON compacto; só regrava se os bytes mudaram. O ano fechado não
  vira diff diário — muda quando o dado muda (inclusive o nome de exibição de um favorecido cuja
  grafia dominante troca com o ano novo).
- Privacidade: nada além do que `dados/mov/` e `nomes-favorecidos.json` já publicam (mesmos nomes,
  CPF mascarado como na origem; a chave `cpf:…|NOME` é a mesma dos índices leves).
- Tamanho (base de 2026-10-16): 2025 = 38.506 linhas, 1,95 MB (514 KB gzip); 2026 = 29.702 linhas,
  1,60 MB (436 KB gzip); ~1 s no export.
- Manifesto no índice: **`cubos: [{ano, arquivo, linhas, bytes, gzip, pago, n}]`** (~270 bytes; o
  hub baixa o índice inteiro, por isso nada além disso). `gzip` = estimativa do download (nível 6).
- `verificar.py` (`verificar_cubos`): todo ano de `totais.por_ano` tem cubo; o arquivo existe com as
  linhas e os bytes do manifesto; índices dentro do dicionário; pago = `totais.por_ano` = manifesto;
  por mês = `series_mensais`. Índice sem `cubos` (export anterior) não é falha. Testes em
  `despesas/tests/test_cubo.py` (conservação, grafias do mesmo CNPJ, bytes determinísticos, ida e
  volta do dicionário, verificação). O workflow já commita `despesas/dados` — os cubos vão juntos.

## Classificação das linhas e taxas (2026-09)

`classificar_documento(tipo_fonte, empenho, na_base)`: **Extra-orçamentário** e **Restos a pagar**
vêm do campo da fonte (`tipo_pagamento`/`tipo_liquidacao`), com ou sem nº de empenho; orçamentário
com empenho na base → **Orçamentário**; orçamentário cujo empenho não veio no endpoint (ou sem nº)
→ **Empenho não localizado na base** (R$ 277 mi em 2025 — todos com nº `/2025`: originais de
jan–fev/2025, meses incompletos na origem; a v1 chamava isso de "restos" e esta rule, até
2026-10, atribuía a "globais de dez do exercício anterior" — errado). Empenho com só anulações/reforços na base →
**Empenho (original fora da base)**. A ausência de nº, sozinha, não é conclusiva; o exercício do nº
(`exercicio_do_empenho`), sozinho, também não. Na execução, liquidações/pagamentos não casados com
nº viram um pseudo-empenho por (UG, nº, tipo) no mês do 1º documento. `execucao.serie` traz
`restos`/`extra`/`nao_localizado` e **`null` = estágio sem partição carregada** (desconhecido ≠ 0).
**Taxa de execução por ano do empenho** (`por_ano`): calculada só sobre empenhos **com original na
base** (`base_taxa`: `cobertura_pct`, `sem_original`, `pago_sem_original`); publicada como
`taxa_liquidacao`/`taxa_pagamento` (**`taxa_validada: true`**) apenas quando a cobertura dos 3
estágios do ano é completa, o denominador > 0 e liquidado ≤ empenhado ≥ pago; senão
`taxa_motivos` + `taxas_brutas` (sem teto de 100%) e alerta `dados_taxa`. Em 2025 a taxa cobre
~45% do empenhado (R$ 3,5 bi pagos por 1.632 empenhos sem original ficam fora — todos `/2025`,
originais de jan/2025, mês incompleto na origem): desde 2026-10 a taxa de 2025 não é validada.

## Export, índice e cobertura

`despesas/export.py` gera: (a) **`despesas-index.json`** (`versao_export: 2`): agregados de
movimentação (totais, séries, por função/elemento/fonte/unidade, top-300 por identidade), bloco
**`cobertura`** (partição a partição: registros, soma, brutos, descartados, duplicidade, status,
erro; `faltantes`, `com_erro`, `duplicidade_sistematica`, `integra`), **`execucao`**, **alertas**,
`alertas_historico`, `resumo` (com `meses_parciais`), `anos_detalhe`, `meses`, `meses_movimento`,
`limites_dispensa`, `conservacao`; (b) detalhe mensal (execução) e (c) movimentação mensal; (d)
`despesas/arvore.json` (treemap) e `despesas/servico-divida.json` (recorte `servico_divida` p/ o
painel de Endividamento, só regrava se o dado mudou); (e) índices leves em `dados/` (`elementos.json`, `pf-resumo.json`,
`indice-favorecidos.json`); (f) `dados/estagios/AAAA-MM.json` (documentos E/L/P por `"UG|empenho"`,
particionado pelo mês da linha de execução; espécie omitida quando "Original"); (g) dossiês
`favorecidos/<slug>.json`; (h) **`despesas/alertas-estado.json`** (histórico de alertas, `versao: 2`);
(i) **`despesas/alertas-candidatos.json`** (todos os casos das regras, `campos`+`linhas`; CSV no
painel); (j) **`despesas/historico/alteracoes-AAAA.jsonl.gz`** (alterações da origem, só-acréscimo —
ver Lote 2). `--db X --saida DIR` gera tudo num diretório candidato sem tocar no repo (copia do
repo o estado dos alertas e a pasta `historico/`, que só crescem). **Mês completo** =
último cujo fim está a mais de `DEFASAGEM_DIAS`=15 da data mais recente da base (o portal publica
com semanas de atraso); meses posteriores ficam fora de YoY, picos e resumo, e o resumo os declara.
`despesas/formato.py` é a camada comum do módulo: `brl`/`compacto`/`pct`, `eh_ente_publico()`
(revisada no Lote 2 — ver abaixo) e a identidade. **`despesas/verificar.py`** (no workflow, no lugar
da guarda "total > R$ 4 bi", que ficou como sanidade) confere cobertura, conservação, manifestos ×
arquivos, série × movimentação e ranking × dossiês; **`despesas/comparar.py`** compara dois
conjuntos de artefatos (e duas bases) e explica as diferenças por causa.

## Gravação estável — mesmo dado, mesmos bytes (2026-10)

Medido em 2026-10-30 (clone espelho recompactado como o do GitHub): o repositório (82 MiB) crescia
**~58 MiB/mês, 66% em `despesas/dados/mov/`**, e 93% das versões diárias desses arquivos em
outubro **não tinham dado novo** (jan, mar e jun/2026: 33 regravações, zero mudança). Causa: a
recarga do ano corrente (`--forcar`) substitui as partições no SQLite e muda a ORDEM FÍSICA; o
export ordenava só por (mês, data, fase) e o empate — e o dicionário pela 1ª aparição — seguia a
ordem física. Também saíam da ordem física: colunas "soltas" do `GROUP BY` dos pseudo-empenhos
(`fonte_recurso` de uma linha arbitrária), o tipo do empenho nos estágios, os últimos pagamentos
do dossiê e os documentos dos alertas (`LIMIT` com empate). Agora toda ordenação é **total pelo
conteúdo** (desempate por todas as colunas), coluna fora do `GROUP BY` vai com `MAX()` e as
consultas com `LIMIT` desempatam por documento. Teste: `test_gravacao_estavel.py` — as mesmas
linhas inseridas em ordens diferentes têm de gravar os mesmos bytes (falha sem a correção). Na
base real, uma cópia do SQLite com a ordem física embaralhada exporta tudo idêntico, salvo os
carimbos `atualizado_em` (dossiês, árvore e candidatos já usam `gravar_json_se_mudou`). As
alternativas cogitadas (Pages via Actions com os dados fora do histórico; commit semanal dos
dados pesados) ficaram desnecessárias — retomar só se o crescimento voltar.

## Alertas (regras determinísticas, 2026-09)

Cada alerta tem **`id` estável** (sha1 de tipo+identidade+recorte), **`classe`** — `contexto`
(escala/recorrência: grande recebedor recorrente, extra-orçamentário, concentração de ente
público — severidade baixa, **não é achado**), `anomalia` (a conferir: fracionamento, favorecido
novo, crescimento no mesmo período, PF em elemento sensível, picos, concentração privada) e
`inconsistencia` (dados: `dados_duplicidade` por mês, `dados_particao`, `dados_cobertura`,
`dados_taxa`, `dados_nao_localizado`) —, `filtro` (com `chave`), **`link`** para o recorte
(raio-X ou Detalhamento já filtrado) e **`documentos`** que acionaram a regra. Crescimento YoY
compara **jan–M do último mês completo nos dois anos** (sem projeção anualizada); picos usam só
meses completos e suprimem elementos de calendário (`ELEM_SAZONAIS`). **Fracionamento** =
triagem: conta **empenhos distintos** (UG+nº) pelo valor líquido (original+reforços−anulações;
1 empenho com 3 reforços nunca vira "4 empenhos"), abaixo do limite **do exercício** em
`LIMITES_DISPENSA` (art. 75 da Lei 14.133 — 2025: Decreto 12.343/2024, 2026: Decreto 12.807/2025;
valores conferidos só em fontes secundárias, o Planalto estava inacessível em 2026-09-12 — a
tabela registra a `verificacao`; ano sem limite cadastrado não dispara), hipótese presumida pelo
elemento (obras/engenharia × compras); o texto diz que o empenho não é o contrato e lista o que
falta (objeto, modalidade, processo, contrato). **Histórico**: `aplicar_historico_alertas` marca
`estado` `novo`/`persistente` (ou `sem_historico` na 1ª execução — não chama tudo de novo),
`primeiro_em`, e move os que sumiram para `resolvidos` em `alertas-estado.json` (versionado,
commitado pelo workflow).

**Contagem e tetos (Lote D2, 2026-09-30).** "A conferir" = classe ≠ `contexto` (anomalias +
inconsistências) — a MESMA conta no badge da aba, no hub (`index.html`), no "Em resumo"
(`resumo.alertas_ativos`) e no card do raio-X; a retrospectiva mostra só `anomalia`. Os tetos
(`CAP_POR_REGRA`=15, `MAX_ALERTAS`=120) são declarados: `alertas(…, contagem=dict)` preenche
**`alertas_regras`** no índice (`{tipo: {candidatos, publicados}}` — em 2026-09: fracionamento 378,
favorecido_recorrente 105, extra 57, pf_sensivel 42) e o painel escreve "os N maiores de M casos".
**`pf_sensivel` é severidade média** (era alta; aluguel mensal de imóvel de PF é o caso típico —
decisão do usuário: os nomes continuam públicos). Dentro da regra, os 15 publicados são escolhidos por **prioridade** (`_prioridade_pf`): valor mensal típico (mediana de 3 meses nas pontas da série) com reajuste ≥ 5 p.p. acima do IPCA do intervalo (`precos/ipca.json`), depois pagamentos iniciados dentro da base, depois valor; o índice leva `reajuste`/`reajuste_ipca` e o detalhe diz "reajuste acima da inflação ou imóvel novo". **Links por identidade**: alertas de favorecido
levam `dfav=<chave>` (filtro do Detalhamento por `Comum.identidadeFavorecido`, pega todas as
grafias do CNPJ — `dq=<nome>` perdia "IPREV - INST. PREV…") e `dm` só com os meses em que o
recorte tem pagamento (`meses_pag`); fracionamento usa os meses de emissão dos empenhos. Na aba:
classe padrão "A conferir", regra com ≥ 3 alertas vira grupo recolhível, filtros na URL
(`ac`/`at`/`as`; `ac=todas` = todas as classes) e aba no hash via `replaceState` em
`selecionarAba` (+ `hashchange`) — Voltar depois de abrir um recorte restaura aba e filtros.

## Painel, raio-X, retrospectiva

`despesas.html`+`despesas-app.js` (vanilla + ECharts via `Comum.grafico` desde o M7 — ver abaixo):
abas Visão geral (movimentação; bloco de execução com taxa validada ou motivo + razões brutas;
glossário com os tipos e as duas visões; linha de **cobertura** no rodapé), Alertas (filtro por
classe/tipo/severidade, nota de histórico, badge NOVO, documentos em `<details>`, clique → `link`),
Favorecidos (ranking por identidade, "N grafias na origem"; o nome abre o raio-X) e
**Detalhamento** (seletor de visão exe/mov; estado completo na URL `dv/dm/dq/df/del/dfa/des/…`
via `Comum.gravarParams`; facetas, chips, métrica ativa, colunas por visão, agrupar com subtotais,
ficha do empenho com estágios, CSV com recorte). `favorecido.html` (raio-X) tem duas rotas:
`?f=<slug>` (dossiê pré-computado do top-300, com `grafias`) e `?doc=&nome=` (qualquer
favorecido; com CNPJ consolida todas as grafias; só nome casa pelo nome normalizado); a seção
"Lançamentos de execução" é **execução por empenho** — o pago segue o favorecido do empenho, por
isso difere do total recebido (retenções pagas ao IPS sob empenhos da folha, p. ex.); o texto da
página diz isso. `retrospectiva.html` usa só o índice. **Meses parciais** (`resumo.meses_parciais`,
posteriores ao último mês completo): no painel ficam tracejados e marcados com `*` nas séries, fora
do ponto de anomalia e da média móvel; o card do ano mostra `resumo.yoy` (jan–mês de referência) e
"Último mês completo" no Detalhamento = `resumo.mes_ref`; na retrospectiva saem da série, do
total e do "mês mais leve". Os arquivos `dados/mov/` são decodificados por `decodificarParte`
ao baixar (dicionário é por arquivo). Assets versionados: `despesas-app.js?v=25` (com `defer`),
`retrospectiva-app.js?v=9`, `favorecido-app.js?v=11` (com `defer`), `comum.js?v=22`, `comum.css?v=12` (bump em todas as páginas ao
mudar). Carga padrão =
mandato (2025→ano corrente, `ANO_INICIAL=2025`). `.sqlite`/`.xlsx`/`.csv`, `_backup/`,
`_candidato/`, `_bruto/` e `*.sqlite.bak-*` no `.gitignore`.

**UI do painel (Lote D3, 2026-09-30).** Cards: total do período, acumulado jan–M (YoY), **último
mês completo** vs média de 12 meses (`resumo.mes_ref`/`delta_media_pct` — o hub usa o mesmo mês)
e **alertas a conferir** (link → `#alertas`). O app carrega com `defer`; biblioteca de gráficos
fora do ar = aviso com "Tentar de novo" em cada gráfico (camada comum) e `renderGraficosSeguro`
segura dado inesperado num gráfico — abas/alertas/tabelas seguem funcionando. Manifestos `meses`/
`meses_movimento` trazem **`bytes`** por arquivo → `sel-info` mostra "download ≈ X MB" (só o que
não está em `DET_PARTES`). `carregarPartes` usa `allSettled` + `r.ok`; a falha nomeia os meses e
oferece "Tentar de novo" (`Comum.estadoErro`) baixando só o que faltou. Facetas: `indicesBase()`
roda a busca/faixa/identidade UMA vez por filtragem. Favorecidos: modo **"Fornecedores
privados"** (flag `ente_publico` no `top_favorecidos` e lista `entes_publicos` de chaves no
índice — a heurística continua só em `formato.eh_ente_publico`), busca sem resultado oferece o
raio-X na base inteira (o ranking é só o top-300), nome do favorecido = link do raio-X (a ficha
modal saiu no Lote 2; a linha inteira também abre),
cabeçalhos com `<button>` + `aria-sort`, toggles com `aria-pressed` (`marcarAlternancia`). O mapa
do gasto (treemap) **não baixa sozinho**: `irParaDetalhe` marca os meses da movimentação e deixa
o filtro pendente (`detPendente`) até "Carregar dados". CSV sai com vírgula decimal, fase por
extenso e período AAAA-MM. Modo escuro: textos em `var(--ink)` e vermelhos/âmbar claros
(≥ 4,5:1). Service worker: dados de despesas network-first (`sw.js`, `CACHE` v3).

**Gráficos em ECharts (M7, 2026-10).** Os 11 gráficos do painel (mensal, execução, anulações,
publicidade, programa, funções, fonte, ano × ano, mapa, unidade gestora, cidades pares) saíram do
Chart.js 4.4.1 + `chartjs-chart-treemap` para `Comum.grafico` (ver `site-frontend.md`): contêiner
`<div class="grafico">` com altura no CSS (`.box .grafico` 300 px; mapa 400/320 px; rosca 420 px até
640 px), desenho sob demanda (aba oculta desenha ao aparecer), tema/celular/CDN na camada comum, a
descrição e a tabela oculta de cada gráfico no `acessivel`. Paridade de comportamento, com estes
detalhes:
- **Meses parciais**: `dividirParciais()` parte a linha em duas séries com o MESMO nome (a legenda
  liga/desliga as duas) — meses completos + trecho tracejado do último completo aos parciais (ponto
  vazado); `*` no eixo; na dica, "(parcial)" e a nota. Pontos fora do padrão (±25% da média dos 12
  meses anteriores) em `vermelho`/`amarelo` do tema, maiores. Legendas seguem clicáveis (como no
  Chart.js: esconder o empenhado reescala o eixo da execução); linha sem marcador tira o ponto da
  legenda com `itemStyle: { opacity: 0 }` no item da legenda.
- **Eixo dos meses**: todos os rótulos no desktop (`interval: 0` + `hideOverlap`), um a cada 4 no
  celular. **Barras deitadas** (`opcaoBarrasDeitadas`, `dependeDaLargura`): `eixoValor()` escolhe
  passo redondo e teto justo pelo espaço útil (o padrão do ECharts esticava o teto e encavalava
  rótulos na caixa estreita) e a margem direita para o rótulo do teto, centrado no traço (o
  `containLabel` não o conta); abaixo de ~140 px úteis só "R$ 0" e o teto têm rótulo; nome longo
  cortado com "…" (230–280 px; 120–140 no celular), inteiro na dica.
- **Cores** só de `Comum.paleta()`; a rosca usa `coresCategorias()` (navy/dourado do tema + as 6
  categóricas que o painel já tinha; a 8ª, vermelha, é a das anulações); ano anterior e cidades pares
  em `ref`; empenhado em #93a0b3 nos dois temas (`cinzaLinha`).
- **Mapa do gasto**: a navegação é a trilha HTML `#mapa-trilha` (botões; o foco fica no nível
  escolhido); o ECharts desenha só o nível atual (`nodeClick: false`, sem a trilha nativa) e o clique
  numa área chama `abrirNoMapa()` — com filhos desce um nível; elemento (≠ "Demais elementos") →
  `irParaDetalhe({funcao, elemento_despesa})`, o mesmo filtro pendente de antes; senão, toast. Rótulo
  só onde cabe inteiro: `retangulosMapa()` reproduz o "squarified" do ECharts (conferido: 0 px de
  diferença nos 85 níveis) e `rotuloMapa()` mede o texto — normal, compacto ou nome em 2 linhas.
  `RAZAO_MAPA` = 1,4 (a áurea espichava as áreas médias e tirava o nome de Assistência social e
  Previdência). O espaço entre as áreas é `itemStyle.borderColor` (padrão branco: no escuro virava
  grade branca) = `card`.
- **Dica**: valor com centavos (`brlc`, como antes) e as notas de antes ("Mês parcial — …", "+X% vs
  média 12m — fora do padrão, ver aba Alertas.", "sem base no ano anterior"/"+X% vs AAAA", "R$ … no
  total" nas vistas % e por habitante, "Deste nível" no mapa).

**Pago por dia, calendário e caminho do dinheiro (M8, 2026-10 — os três aprovados na vitrine de
ECharts).** Dados: `exportar_graficos_movimento()` grava, das MESMAS linhas de pagamento (fase P) de
`montar_movimento` que vão para `dados/mov/`, dois arquivos em `despesas/dados/` (o workflow já os
publica com a pasta), sem carimbo de hora e tudo ordenado — mesmo dado = mesmos bytes (teste com as
linhas embaralhadas). O índice leva só o manifesto **`dados_graficos`** (`{calendario|fluxo:
{arquivo, bytes}}`, ~150 bytes): **sem ele o painel nem baixa** (índice anterior ao 1º export com
os arquivos → nada de 404 no console).
- **`dados/calendario.json`** (~15 KB): `{"versao":1,"campos":["dia","pago","n","anulacoes"],"ate",
  "redatados":{n,pago},"linhas":[["2025-01-02",1907.94,2,0],…]}` — pago líquido (centavos), nº de
  documentos de pagamento (anulações inclusas; Σn = `totais.pagamentos`) e quantos são anulações, só
  dias com documento. O dia conta **dentro do mês da partição** (`_dia_pagamento`), como a série
  mensal: a origem traz pagamentos com a data de outro ano no mesmo mês (23, R$ 174 mil, todos
  extra-orçamentários — 25/04/2024 na partição abr/2025), contados no mesmo dia do mês consultado
  (`redatados`); dia inexistente no mês vai para o último.
- **`dados/fluxo.json`** (~41 KB): `{"versao":1,"anos":{"2026":{"extra",
  "todos":{total,nos,ligacoes},"privados":{…}}}}` — por ano da partição, **sem o extra-orçamentário**
  (`extra` = o que ficou fora, igual a `execucao.por_ano[ano].extra`), grupo da fonte (prefixo AUDESP;
  91–98 juntos em "9x", exercícios anteriores; nomes em `GRUPOS_FONTE`, 03/06/07/08/9x lidos da tabela
  AUDESP e conferidos com as fontes da base [Verificar]) → função (pelo código, grafia por
  `nome_exibicao`) → favorecido **por identidade** (nome por `nome_exibicao`, `documento`, `link` do
  raio-X por `_link_fav`: `?f=` se há dossiê, senão `?doc=&nome=`; `ente_publico` em "todos").
  `FLUXO_TOPOS` = 8/10/15 + nó "Demais" (`inclui` ou `qtd`); "Demais" de um só vira o próprio nó.
  "privados" tira as identidades de `entes_publicos` (a mesma `formato.eh_ente_publico`). Ids
  estáveis (`g:01`, `f:10`, `v:<slug>`), ligações `[de, para, valor]` (≤ ~130 por recorte; líquida
  negativa fica no arquivo e o painel não a desenha).
- **`verificar.py`** (bloco 4b): calendário somado por mês = `series_mensais` em todo mês, Σn =
  `totais.pagamentos`, dias válidos/únicos/em ordem, `ate` = último dia; caminho: anos = anos da base,
  `extra` = execução, "todos" = pago do ano − extra, cada nível e cada camada de ligações somam o
  total, cada nó entrega/recebe o próprio valor, "privados" ≤ "todos" e sem ente público; manifesto ×
  bytes. Testes: `despesas/tests/test_calendario_fluxo.py`.
- **Mensal | Diário** (`#pago-escala`, `aria-pressed`, `?pago=dia`): o MESMO contêiner `#ch-mensal`
  troca de definição (`desenharMensal`: `DEF_MENSAL` = o gráfico do M7, intocado — conferido pixel a
  pixel — ou `defDiario()`). Diário = barras por dia em eixo de tempo, mês parcial mais claro e faixa
  "mês parcial*", régua (slider) começando nos últimos 120 dias; arrastar o gráfico desloca a janela.
  **O zoom de roda do ECharts captura a roda mesmo sem o Ctrl** (a página parava de rolar sobre o
  gráfico): o `inside` tem `zoomLock` e o **Ctrl + roda** (e a pinça do trackpad) é da página
  (`wheel` no contêiner → `dispatchAction`). No toque o `inside` fica desligado (só a régua). A janela
  (`janelaDiario`) sobrevive à troca de tema e de escala; sem o arquivo, "Diário" fica desabilitado
  (sem manifesto) ou avisa por toast e fica no Mensal (falha de rede).
- **Calendário** (`#box-calendario`, logo abaixo do pago por mês): um bloco por ano (no celular,
  semestres), cor = faixa entre os quintis dos dias com pagamento (`visualMap` por peças — um estilo
  por dia custava ~25% mais), sem pagamento em `neutro`, dia ainda sem dado com a cor do cartão; mês
  parcial hachurado numa série à parte com UMA hachura (hachura por dia dobrava o custo). Altura
  reservada no CSS com unidades de contêiner (`.cal-area { container-type: inline-size }`, `cqw`,
  `--anos`) pela mesma conta de `medidasCalendario` — o desenho não empurra a página. Legenda HTML
  (`#cal-legenda`) com as faixas em R$, nascida com textos de reserva do mesmo formato (ocultos).
- **Caminho do dinheiro** (`#box-caminho`, depois do mapa): Sankey com ano (`select`, `?caminho=`) e
  "Todos | Só fornecedores privados" (`?so=privados`); rótulos cortados pela largura medida
  (`rotulosCaminho`), nome do favorecido por `nomeLegivel` (cópia da do raio-X — candidata à camada
  comum); clique num favorecido → `link`; "Demais" → toast. ~900 px de largura mínima (780 no
  celular): a caixa rola na horizontal (`.rolagem-x`, `role=region`, entra no Tab só quando rola), a
  página não.
- **Acessível**: tabela oculta do Diário e do calendário **por mês** (total, documentos, maior dia —
  ~470 linhas de dias seriam navegáveis só uma a uma; o dia a dia está no Detalhamento); a do caminho
  lista as ligações (de, para, pago).
- **Sem o arquivo**: com o manifesto ausente, aviso "disponível a partir da próxima atualização" no
  lugar do gráfico — a caixa recolhe fora da tela; na tela mantém a altura (CLS zero); fetch que
  falha → `estadoErro` com "Tentar de novo"; CDN fora → o erro da camada comum, como os demais.
- **Custo** (CPU 4×, máquina compartilhada — medir intercalado): nada dos três é desenhado na carga
  (fetch + tabelas ocultas ~30 ms); ao entrar na tela o calendário bloqueia ~0,4 s e o caminho ~0,3 s
  (o mapa 0,25–0,35 s, fonte + funções 0,3–0,4 s); clicar em "Diário" ~0,25 s.

**Raio-X (Lote D4, 2026-09-30).** O dossiê (`favorecidos/<slug>.json`) ganhou `por_elemento`
(com `participacao_pct` = fatia do favorecido em todo o pago no elemento), `por_unidade`,
`por_tipo`, `primeiro_pagamento`/`ultimo_pagamento`, `ultimos_pagamentos[].pagamento/empenho`,
`grafias_detalhe` (total/qtd/período por nome da origem — a página marca **"outro nome"** quando
os nomes não dividem metade das palavras: troca de razão social, p. ex. SABINO → OPUS) e
`ente_publico`. O export materializa os pagamentos do top-300 numa temp table indexada
(`pag_top`) — as consultas por favorecido refaziam o join com `fav_ident` na tabela inteira (o
dossiê levava 180 s; agora ~5 s; export completo ~70 s). `dados/nomes-favorecidos.json` (chave →
[nome, documento] de todas as identidades) deixa a rota `?nome=` achar quem está fora do top-300.
Página: cards com o **ano da base** (não o último ano do favorecido) e o período de presença;
série com todos os meses (lacunas = 0) e meses parciais claros; composição (elemento/UG/tipo);
**consultas externas** só para CNPJ privado — link do Portal da Transparência federal
(pessoa-jurídica: sanções CEIS/CNEP, contratos federais) e botão que consulta o cadastro da
Receita via **BrasilAPI** no navegador (abertura, situação, CNAE, sócios), com sinal quando a
empresa abriu < 12 meses antes do 1º pagamento da base (PNCP ficou de fora: o site recusou
conexão na verificação, link não validado); lançamentos de execução **sob demanda** acima de
~3 MB (botão com meses e MB), progresso e "Tentar de novo"; **faixa de conciliação** recebido ×
pago sob empenhos dele × diferença, com as causas; "← Voltar" (history.back se veio do site) e
ponte para o Detalhamento com `dfav` + meses em que recebeu. Rota `?doc=&nome=`: resolve a
identidade (CNPJ → redireciona para `?f=` se houver dossiê; CPF mascarado sem nome → pede o
nome; nome ambíguo → lista para escolher) e monta o dossiê com os **pagamentos reais** da
movimentação (fase P, pela data do pagamento) + alertas do índice pela `chave`.

**Análises (Lote D5, 2026-09-30).** No índice: **`prazos_pagamento`** (`prazos_pagamento()`: pagamento
orçamentário — inclui restos a pagar, exclui extra — casado com a liquidação por UG + empenho + nº
da liquidação (MIN(data) das liquidações não anuladas); por ano: mediana, p90 e faixas (antes da
liquidação / ≤ 1 / 2–7 / 8–30 / 31–90 / > 90 dias); fornecedores com ≥ 10 pagamentos e ≥ R$ 1 mi,
entes públicos fora: 10 mais rápidos e 10 mais lentos. Em 2025–26: mediana 6–7 dias, p90 21 dias);
**`anulacoes`** (série mensal, por ano com % do empenhado, top 15 favorecidos; anulado > empenhado
na base = `original_fora_da_base`, sem %); **`fim_de_exercicio`** (dezembro × média jan–nov de
empenhado novo, liquidado, pago e anulado, só anos com dezembro completo — dez/2025: liquidado
1,64×, anulado 5,9×); **`por_funcao_orcamentario`** (base do "De cada R$ 100" e do recibo — sem
o extra-orçamentário, R$ 1,2 bi que só transita pelo caixa); **`por_programa`** (PPA, top 15, não
é secretaria); **`por_fonte`** junta o extra-orçamentário numa linha (`FONTE_EXTRA`: a origem o
grava sem o prefixo AUDESP do grupo de fonte e parecia fonte duplicada). Regras novas
**`prazo_rapido`** (mediana ≤ 1 dia com a geral ≥ 5) e **`prazo_lento`** (mediana ≥ 60 dias) —
anomalia média, triagem do art. 141 da Lei 14.133. `formato.eh_ente_publico` passou a incluir
CET-Santos, PRODESAN, COHAB e SECRETARIA (a COHAB com 100% de Habitação era "anomalia") e a
excluir a SABESP (privatizada em jul/2024). Export completo ~110 s (prazos ~22 s). Retrospectiva:
`anos_detalhe[ano].top_fornecedores` (top 5 sem entes públicos) numa lista à parte, entes marcados
na lista geral, comparação com o mesmo período do ano anterior (`resumo.yoy`), gráfico com
`Comum.chartAcessivel` e redesenho no resize.

## Alertas v2, histórico versionado e publicidade (Lote 2, 2026-10)

**Fracionamento v2** (`candidatos_alertas`, regra 5): agrupa por **(unidade gestora, favorecido,
elemento, exercício do empenho)** — o art. 75, § 1º, I da Lei 14.133 soma o despendido no exercício
pela mesma UG (a v1 somava UGs: 2+2 em UGs diferentes disparava). Só **empenho ordinário** conta
(tipo vazio = ordinário); global/estimativo (em geral ligados a contrato) ficam fora da conta e
aparecem só no detalhe ("Fora da conta: N…"); empenho sem o original na base (exercício incerto)
fica fora. **Manutenção de veículos** (33903919 serviço e 33903039 peças) usa o limite do art. 75, I
(coluna `engenharia` de `LIMITES_DISPENSA`; o § 7º — pequenas compras de manutenção fora da soma —
não é aplicado, [Verificar]). **Etiqueta do PNCP**: `espelho_pncp()` lê `precos/espelho/3548500-*.jsonl.gz`
(stdlib, cache por processo); por empenho, numa janela de **24 meses antes** (ata vale 1 ano + 1,
art. 84): CNPJ vencedor de pregão com SRP → `provavel_ata`; pregão sem SRP → `vencedor_pregao`; só
dispensa → `dispensa_pncp`. O alerta leva `etiqueta`, `etiqueta_alcance` [k de n empenhos] e
`pncp` (nº de controle, processo, objeto, link `pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}`); o texto
ressalva que o espelho cobre só pregão eletrônico e dispensa publicados desde jan/2025 ("sem
registro" ≠ "sem licitação"). Contratação revogada/anulada/suspensa não conta. **Continuidade**:
id v2 = sha1(fracionamento, UG, chave, elemento, ano) e `ids_anteriores` = o id v1 (sem UG).
Em 2026-10-17 (base fresca): 392 → 343 candidatos; 151 com `provavel_ata`, 12 `vencedor_pregao`, 4
`dispensa_pncp`; nenhum `provavel_ata` publicado (vão por último).

**`pago_acima_liquidado`** (anomalia média — classe pendente de decisão do usuário): por (UG,
empenho, nº da liquidação), soma dos pagamentos > valor da liquidação, direto no SQLite
(`pago_acima_liquidado()`; `CAMPOS_MOV` intocado). Fora: extra-orçamentário (retenções com o mesmo
nº) e "Restos a Pagar Processados" (nº de liquidação de outro exercício). Exige: liquidação na base
com o original e saldo > 0; pagamento orçamentário com o empenho original na base; favorecido que
não é ente público; excesso ≥ `PAGO_ACIMA_MIN` (R$ 100) na liquidação **e no empenho inteiro**
(excesso só na liquidação = nº trocado entre parcelas); nenhuma partição envolvida com erro ou
duplicidade sistemática. Linhas idênticas NÃO são deduplicadas (há estornos repetidos legítimos).
"Exatamente o dobro com ≥ 2 pagamentos distintos" → título "Liquidação paga duas vezes". Funil em
2026-10-17: 4.396 empenhos com pago > liquidado (todos os tipos, R$ 164 mi) → 1.276 sem extra (R$ 124
mi) → 1.521 liquidações (orçamentária + RP não processados, R$ 68,4 mi), das quais 1.389 sem a
liquidação na base (R$ 62,2 mi — lacuna da origem), 32 sem original/saldo ≤ 0, 53 orçamentárias sem
empenho original, 11 de ente público (folha/previdência), 20 com o empenho equilibrado, 6 em partição
duplicada → **9 publicadas** (R$ 86,9 mil; nenhum "dobro"). Documentos: a liquidação e os pagamentos;
link: execução com `emp=UG|nº` (abre a ficha do empenho).

**Candidatos × publicados** (`candidatos_alertas()` → `aplicar_historico_alertas()` sobre TODOS →
`publicar()`; `alertas()` mantém assinatura e retorno = publicados, sem histórico — briefing e testes
antigos). Ordem dentro da regra (`_prioridade_publicacao`): **novo antes de persistente** (sem
histórico empata com persistente), depois a prioridade própria (valor; pf_sensivel por
`_prioridade_pf`; prazo_lento pela mediana), `provavel_ata` por último; teto `CAP_POR_REGRA`=15
(`CAP_ESPECIAL` extra=20; `SEM_TETO` pico_mensal e dados_*); teto global `MAX_ALERTAS`=120 corta
**contexto** primeiro. Documentos e links caros (`_completar`) só para os publicados. Um alerta
deslocado pelo teto continua no estado (não vira "resolvido" nem volta "novo"). **`alertas-estado.json`
`versao: 2`** guarda todos os candidatos, sem `ultimo_em` (mudava ~680 linhas/dia; ninguém lia); na
migração de um estado v1 (só publicados), candidato fora dele fica `sem_historico` por um dia. O
índice: `alertas_regras` conta candidatos de toda regra; `alertas_historico.novos/persistentes` =
publicados, `alertas_historico.candidatos` = todos.

**Histórico versionado de alterações** (`exportar_historico_alteracoes`): `linhas_historico` do SQLite
(motivos `removido`/`substituido`; duplicidade fica de fora — já está na cobertura) vai para
`despesas/historico/alteracoes-AAAA.jsonl.gz` (AAAA = ano da partição), **só-acréscimo**: lê o
versionado, acrescenta o que falta (chave hash+repetição+motivo+registrado_em), nunca apaga — o SQLite
do cache pode ser despejado. Descarta o **artefato de largura** (7→8 dígitos em 2026-09-30 e a volta
depois da correção): linha cuja forma normalizada (`crawler.numero_documento`/`codigo_grupo` + hash)
ainda está na partição. Campos enxutos: `em f p m h r ug emp liq pag data esp valor fav doc elem tipo`.
gzip com `mtime=0` (mesmo conteúdo = mesmos bytes).

**Ente público (revisão)** — `formato.eh_ente_publico`, na ordem: exceções públicas explícitas
(PRODESAN, COHAB, CET-Santos); guarda de forma **privada** (começa com Associação/Federação/Sindicato,
contém "Fundação de Apoio", LTDA/EIRELI/ME/EPP) + exceções nominais (AFIP, FIPE, FGV, SABESP);
FUNDAÇÃO só pela lista curada `FUNDACOES_PUBLICAS` (FAMS, Pró-Esporte/FUPES, FUNAP, FUB, FUNAPE);
FUNDO só com qualificador público (municipal/estadual/nacional/federal/penitenciário/
previdenciário/social de solidariedade); "ESTADO DE SÃO PAULO" só com marcador estatal antes
(governo, secretaria, polícia, bombeiros, companhia…). **Judiciário** (decisão do usuário,
2026-10-20): todo TRIBUNAL — menos arbitral e de justiça desportiva, privados — e a Justiça
Federal/do Trabalho/Eleitoral/Militar. "SÃO PAULO TRIBUNAL DE JUSTIÇA" (R$ 116 mi no mandato) não
tinha "ESTADO DE SÃO PAULO" depois do marcador e contava como fornecedor privado ("Só fornecedores
privados" do caminho do dinheiro e da aba Favorecidos); mudaram 6 identidades (TJ-SP, TRT-2, TRT-15,
TRF-3, STJ, Justiça Federal) e saíram os falsos alertas de pico (TJ-SP, jul/2025) e de crescimento
(TRT-2) e o candidato de fracionamento (sentenças pagas ao TRT-2). Saíram de `entes_publicos` (13 identidades em
2026-10-17): AFIP, ANEPREM, FAP-UNIFESP, FUSP, SETTAPORT, FCTH, FEAS, FUNDIC, Federação de Tênis de
Mesa, Associação de Lutas, associações de secretários/secretarias e APRECESP. **Pendentes de decisão
do usuário** (`FUNDACOES_DUVIDOSAS`, seguem como ente até lá): Pinacoteca Benedito Calixto, CENEP,
Parque Tecnológico (também é UG da base) e SP-PREVCOM. O JS não replica a heurística (usa a flag e
`entes_publicos` do índice).

**Publicidade (só agregados — decisão do usuário: nenhum sinal sobre empresas)**: bloco
`publicidade` do índice (`publicidade()`), elementos 33903988 (propaganda) e 33903990 (publicidade
legal), pela data do pagamento (inclui restos): `por_ano`, `comparacao` (jan–M do último mês completo
× mesmo período do ano anterior), `serie` mensal (lacuna = 0) e top 10 `favorecidos` por identidade.
Caixa `#box-publicidade` na Visão geral (padrão do `box-prazos`; gráfico de barras empilhadas com
tabela oculta, mês parcial mais claro).

**Painel (Lote 2)**: filtro de severidade só com os valores presentes; cartão do alerta com
"Abrir o recorte"/"Abrir o raio-X", **"Raio-X do favorecido"** (quando o recorte é o Detalhamento),
links do **PNCP** quando há etiqueta e **"Copiar rascunho de requerimento"** (classes ≠ contexto):
texto determinístico montado no navegador só com os campos do alerta (título, detalhe entre aspas,
valor, documentos, link do recorte) + pedidos por regra (`PEDIDOS_POR_TIPO`), base legal "art. 58,
XVIII da Lei Orgânica" e "art. 121 do Regimento Interno [Verificar]" (requerimento de informação não
admite sugestão ou conselho); cópia com fallback (`execCommand`) e `Comum.toast`. O clique no
cartão ignora `a`, `button` e os documentos. A linha do teto oferece **"Baixar os N casos (CSV)"**
(lê `despesas/alertas-candidatos.json`).

## Benchmark cidades pares (`despesas/benchmark.py`)

Compara a despesa **por função** de Santos com pares paulistas (Jundiaí, Piracicaba, Mogi das
Cruzes, Bauru + São José dos Campos) na **DCA Anexo I-E do SICONFI** (mesma API
`apidatalake.tesouro.gov.br` do endividamento; competência anual consolidada — NÃO bate com a visão
caixa do painel). Gera `despesas/benchmark.json` (versionado, ~8 KB) com pago/liquidado por função e
**populações do Censo 2022 embutidas** — a mesma base de `Comum.POP_SANTOS` (unificado em 418.608
em 2026-07). O painel divide por habitante e narra "X% acima/abaixo da
mediana dos pares". Workflow próprio (`benchmark-despesas.yml`, cron mensal dia 6 — a DCA sai ~abril;
recua um exercício se o atual não estiver publicado p/ ≥4 entes).

## Briefing semanal de despesas (`despesas/briefing.py`)

Canal *push* para os assessores: e-mail HTML semanal com o panorama das despesas, **só informativo**
(determinístico, **sem Claude/tokens**). Lê o `despesas.sqlite` e reusa `conectar()`/`alertas()`/
`preparar_identidades()` de `export.py` (via `import export`) + o padrão SMTP de `ordem-do-dia/index.py`.
A "semana" = os 7 dias que terminam na **data de pagamento mais recente** da base menos a
defasagem; o pago da semana é comparado à **média semanal do ano** e, quando fica abaixo da metade,
o card avisa "provável defasagem do portal". Seções: cards, execução (taxa validada ou motivo),
avisos (último mês completo, partições faltantes/duplicadas), **alertas selecionados por novidade e
diversidade** (`selecionar_alertas`: novos antes de persistentes, inconsistência/anomalia antes
de contexto, ≤ 2 por regra e 1 por favorecido, 12 no total; sem histórico o e-mail diz isso),
gasto por função, favorecidos por identidade (fornecedores × entes públicos), maiores pagamentos
e empenhos novos. CLI: `--dry-run`, `--salvar PATH`, `--semana N`, `--defasagem N`, `--db X`.
Destinatários: **`DESPESAS_BRIEFING_TO`** → **`RESPOSTAS_EMAIL_TO`** → **`GMAIL_TO`**. Agendamento:
passo final do `despesas.yml` às segundas (`date +%u = 1`) ou `workflow_dispatch` com
`forcar_briefing=true`.

## Workflow (`.github/workflows/despesas.yml`)

Testes → cache do `.sqlite` → crawler (partições sem carga; depois `--ano corrente --forcar`, ou
tudo com `reconciliar_tudo=true`) com tratamento dos códigos 1 (aborta) e 2 (publica e falha no
fim, lista no `GITHUB_STEP_SUMMARY`) → **`tce.py`** (conciliação com o TCE-SP; falha vira aviso) →
`export.py` → **`verificar.py --tolerar-erros`** → commit de
`despesas-index.json despesas/dados despesas/arvore.json despesas/alertas-estado.json despesas/alertas-candidatos.json despesas/historico despesas/servico-divida.json despesas/conciliacao-tce.json favorecidos`
(o export cria `despesas/historico/` mesmo vazia — `git add` de pasta inexistente derruba o passo)
→ briefing → passo "Falha parcial" (vermelho se alguma partição não atualizou).

## Recuperação e reconciliação da base (procedimento)

1. **Backup**: `despesas/_backup/despesas.sqlite.v1-AAAAMMDD` (cópia do SQLite antes de migrar;
   o crawler também grava `despesas.sqlite.bak-v1-*` ao migrar).
2. **Respostas brutas**: `python despesas/crawler.py --db despesas/_candidato/despesas.sqlite
   --bruto-dir despesas/_bruto --relatorio despesas/_candidato/relatorio-carga.json` baixa (ou
   reusa) as 63 fotografias e reconcilia num banco candidato — nada toca no repo.
3. **Candidato**: `python despesas/export.py --db despesas/_candidato/despesas.sqlite --saida
   despesas/_candidato` e `python despesas/verificar.py --raiz despesas/_candidato`.
4. **Comparação**: `python despesas/comparar.py --antes . --depois despesas/_candidato --db-antes
   despesas/_backup/… --db-depois despesas/_candidato/despesas.sqlite --saida
   despesas/_candidato/comparacao.md` — por ano/mês/unidade/estágio e linha a linha, com as causas
   (correção/exclusão na origem, mês novo, duplicidade, reclassificação, apresentação).
5. **Publicação**: só depois de revisar a comparação. Ou o workflow (cache migra e rebaixa tudo),
   ou localmente `python despesas/export.py` com a base candidata copiada para
   `despesas/despesas.sqlite` — nunca com um SQLite antigo/incompleto. **Validação do software
   (testes) ≠ conciliação com a fonte oficial**: os totais publicados são o que a API devolveu,
   com as regras acima aplicadas e declaradas.

## Comandos úteis

```bash
# Despesas — amostra de um mês sem gravar
python despesas/crawler.py --ano 2026 --mes 6 --dry-run

# Despesas — carga/reconciliação de um ano (ou mês específico com --mes)
python despesas/crawler.py --ano 2026 --forcar

# Despesas — carga do mandato (2025→corrente) + export + verificação
python despesas/crawler.py
python despesas/export.py
python despesas/verificar.py

# Despesas — briefing semanal (preview sem enviar)
python despesas/briefing.py --dry-run
python despesas/briefing.py --salvar despesas/_briefing.html  # abrir no navegador

# Despesas — testes (parsing, reconciliação, identidade, visões, alertas)
python -m pytest despesas/tests -q

# Benchmark cidades pares (SICONFI/DCA) — conferir sem gravar
python despesas/benchmark.py --dry-run

# Conciliação com o TCE-SP (mês incompleto na origem) — conferir sem gravar / rebaixar tudo
python despesas/tce.py --dry-run
python despesas/tce.py --todos
```

**Cuidado ao testar localmente:** `export.py` sem `--saida` sobrescreve artefatos VERSIONADOS
(`despesas-index.json`, `dados/`, `favorecidos/`, `arvore.json`, `alertas-estado.json`,
`alertas-candidatos.json`, e ACRESCENTA a `historico/`) com o
`.sqlite` local — que costuma estar desatualizado (o fresco vive no cache do Actions). Use
`--db/--saida` para candidatos; depois de testar sem eles, `git restore` e apague os gerados
não rastreados; o workflow diário regenera tudo com a base fresca.
