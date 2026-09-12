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
execução (`expurgar_demo()` em `abrir_db`). **A API NÃO expõe unidade orçamentária (secretaria)**; o
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

## Classificação das linhas e taxas (2026-09)

`classificar_documento(tipo_fonte, empenho, na_base)`: **Extra-orçamentário** e **Restos a pagar**
vêm do campo da fonte (`tipo_pagamento`/`tipo_liquidacao`), com ou sem nº de empenho; orçamentário
com empenho na base → **Orçamentário**; orçamentário cujo empenho não veio no endpoint (ou sem nº)
→ **Empenho não localizado na base** (R$ 277 mi em 2025 — em geral globais emitidos em dez do
exercício anterior; a v1 chamava isso de "restos"). Empenho com só anulações/reforços na base →
**Empenho (original fora da base)**. A ausência de nº, sozinha, não é conclusiva; o exercício do nº
(`exercicio_do_empenho`), sozinho, também não. Na execução, liquidações/pagamentos não casados com
nº viram um pseudo-empenho por (UG, nº, tipo) no mês do 1º documento. `execucao.serie` traz
`restos`/`extra`/`nao_localizado` e **`null` = estágio sem partição carregada** (desconhecido ≠ 0).
**Taxa de execução por ano do empenho** (`por_ano`): calculada só sobre empenhos **com original na
base** (`base_taxa`: `cobertura_pct`, `sem_original`, `pago_sem_original`); publicada como
`taxa_liquidacao`/`taxa_pagamento` (**`taxa_validada: true`**) apenas quando a cobertura dos 3
estágios do ano é completa, o denominador > 0 e liquidado ≤ empenhado ≥ pago; senão
`taxa_motivos` + `taxas_brutas` (sem teto de 100%) e alerta `dados_taxa`. Em 2025 a taxa cobre
~45% do empenhado (R$ 3,5 bi pagos por 1.632 empenhos sem original ficam fora) — o painel diz isso.

## Export, índice e cobertura

`despesas/export.py` gera: (a) **`despesas-index.json`** (`versao_export: 2`): agregados de
movimentação (totais, séries, por função/elemento/fonte/unidade, top-300 por identidade), bloco
**`cobertura`** (partição a partição: registros, soma, brutos, descartados, duplicidade, status,
erro; `faltantes`, `com_erro`, `duplicidade_sistematica`, `integra`), **`execucao`**, **alertas**,
`alertas_historico`, `resumo` (com `meses_parciais`), `anos_detalhe`, `meses`, `meses_movimento`,
`limites_dispensa`, `conservacao`; (b) detalhe mensal (execução) e (c) movimentação mensal; (d)
`despesas/arvore.json` (treemap); (e) índices leves em `dados/` (`elementos.json`, `pf-resumo.json`,
`indice-favorecidos.json`); (f) `dados/estagios/AAAA-MM.json` (documentos E/L/P por `"UG|empenho"`,
particionado pelo mês da linha de execução; espécie omitida quando "Original"); (g) dossiês
`favorecidos/<slug>.json`; (h) **`despesas/alertas-estado.json`** (histórico de alertas).
`--db X --saida DIR` gera tudo num diretório candidato sem tocar no repo. **Mês completo** =
último cujo fim está a mais de `DEFASAGEM_DIAS`=15 da data mais recente da base (o portal publica
com semanas de atraso); meses posteriores ficam fora de YoY, picos e resumo, e o resumo os declara.
`despesas/formato.py` é a camada comum do módulo: `brl`/`compacto`/`pct`, `eh_ente_publico()`
(exceções privadas AFIP/FIPE/FGV) e a identidade. **`despesas/verificar.py`** (no workflow, no lugar
da guarda "total > R$ 4 bi", que ficou como sanidade) confere cobertura, conservação, manifestos ×
arquivos, série × movimentação e ranking × dossiês; **`despesas/comparar.py`** compara dois
conjuntos de artefatos (e duas bases) e explica as diferenças por causa.

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
commitado pelo workflow). Hub e retrospectiva contam alta/média como antes.

## Painel, raio-X, retrospectiva

`despesas.html`+`despesas-app.js` (vanilla + Chart.js e plugin `chartjs-chart-treemap` via CDN):
abas Visão geral (movimentação; bloco de execução com taxa validada ou motivo + razões brutas;
glossário com os tipos e as duas visões; linha de **cobertura** no rodapé), Alertas (filtro por
classe/tipo/severidade, nota de histórico, badge NOVO, documentos em `<details>`, clique → `link`),
Favorecidos (ranking por identidade, "N grafias na origem", ficha filtra pela identidade) e
**Detalhamento** (seletor de visão exe/mov; estado completo na URL `dv/dm/dq/df/del/dfa/des/…`
via `Comum.gravarParams`; facetas, chips, métrica ativa, colunas por visão, agrupar com subtotais,
ficha do empenho com estágios, CSV com recorte). `favorecido.html` (raio-X) tem duas rotas:
`?f=<slug>` (dossiê pré-computado do top-300, com `grafias`) e `?doc=&nome=` (qualquer
favorecido; com CNPJ consolida todas as grafias; só nome casa pelo nome normalizado); a seção
"Lançamentos de execução" é **execução por empenho** — o pago segue o favorecido do empenho, por
isso difere do total recebido (retenções pagas ao IPS sob empenhos da folha, p. ex.); o texto da
página diz isso. `retrospectiva.html` usa só o índice. Assets versionados: `despesas-app.js?v=14`,
`favorecido-app.js?v=7`, `comum.js?v=9` (bump em todas as páginas ao mudar). Carga padrão =
mandato (2025→ano corrente, `ANO_INICIAL=2025`). `.sqlite`/`.xlsx`/`.csv`, `_backup/`,
`_candidato/`, `_bruto/` e `*.sqlite.bak-*` no `.gitignore`.

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
fim, lista no `GITHUB_STEP_SUMMARY`) → `export.py` → **`verificar.py --tolerar-erros`** → commit de
`despesas-index.json despesas/dados despesas/arvore.json despesas/alertas-estado.json favorecidos`
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
```

**Cuidado ao testar localmente:** `export.py` sem `--saida` sobrescreve artefatos VERSIONADOS
(`despesas-index.json`, `dados/`, `favorecidos/`, `arvore.json`, `alertas-estado.json`) com o
`.sqlite` local — que costuma estar desatualizado (o fresco vive no cache do Actions). Use
`--db/--saida` para candidatos; depois de testar sem eles, `git restore` e apague os gerados
não rastreados; o workflow diário regenera tudo com a base fresca.
