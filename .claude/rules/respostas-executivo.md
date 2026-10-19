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
- **Registro:** Google Sheets; duas abas (`indicações`/`requerimentos`), roteamento por tipo. Para cada item localiza a linha existente pelo número e **atualiza** as colunas `Resposta` (hyperlink para a subpasta do Drive), `Data da resposta`, `Situação da resposta` e `Data da resposta de mérito`; se o número não existir, **anexa** linha nova, posicionando cada valor pelo **cabeçalho real** da aba (`montar_linha`; nunca `values().append` pela ordem de `ABAS`, que deslocava colunas e criava linhas-fantasma com data no Número); item que já tem Resposta e não ganhou PDF novo **não vai ao log nem ao e-mail** — no máximo grava a reclassificação em silêncio. Antes de ler, `garantir_colunas` cria as colunas de classificação que faltarem: sem elas a situação nunca era gravada e ~576 itens saíam todo dia como "resposta nova" (out/2026). Ver `ABAS`/`carregar_planilha` em `index.py`. Pastas no Drive: `REQUERIMENTO_<nº>` / `INDICACAO_<nº>`.
- **Log diário:** aba `Log diário` (criada automaticamente; `garantir_aba_log` completa o cabeçalho se faltar coluna) recebe uma linha por resposta processada (data, tipo, número, assunto, data da resposta, link, situação). Com `--email`, envia também um resumo HTML via Gmail SMTP (secrets `GMAIL_*`) — só quando há novidades, distinguindo mérito de trâmite.
- **Agendamento:** GitHub Actions (`.github/workflows/respostas-executivo.yml`), cron `31 8 * * 1-5` (05h31 BRT, dias úteis).
- **Painel de Requerimentos & Respostas (`requerimentos.html` + `requerimentos-app.js`):** cartão "Requerimentos" na seção Bases de dados do hub. `respostas-executivo/export.py` lê a aba `requerimentos` da planilha (via Sheets API, reusando `_google_services`/`_idx_header` de `index.py`) e gera `requerimentos-index.json` na raiz — array com número, ano, assunto, datas, situação, `respondido` e `url_resposta`. **O índice é público: só saem as chaves de `CAMPOS_PUBLICOS` (`export.py`)** e o `main()` aborta com exit 1 se aparecer outra. A coluna interna "Status atual" da planilha **não vai ao site** — até out/2026 ela era publicada e exibida como "Situação", vazando anotações do gabinete ("ok (Falar com o Rui)", "não sei se cabe reiterar", links de entrega de documentos). A coluna "Situação" do painel mostra os rótulos públicos da classificação (`SITUACAO_ROTULO` em `requerimentos-app.js`, espelho de `classificar.ROTULOS`). Linha cujo Número não casa `^\d{1,5}/\d{4}$` (ex.: data, como as linhas-fantasma de set/2026) é descartada com aviso. A lógica de montagem vive em `montar_itens()` (testável sem Google: `testes_export.py`). **A coluna `Resposta` é uma fórmula `=HYPERLINK(...)`**, então o export lê com `valueRenderOption="FORMULA"` e extrai a URL do Drive por regex. O painel (vanilla, sem acento, paginado) tem busca + filtros de ano/situação e link para a pasta no Drive (exige login do gabinete) ou badge "Pendente". O JSON é gerado e commitado pelo passo final do `respostas-executivo.yml` (com guarda anti-base-vazia). **O export roda mesmo se o crawler falhar** (`if: !cancelled() && testes ok`; só lê a planilha): até out/2026 ele era pulado quando a Câmara recusava conexão, e o JSON no ar ficou dias com a coluna interna depois da correção. **`.github/scripts/checar_publicos.py`** confere o JSON JÁ PUBLICADO contra a lista branca (lida do `export.py` pela árvore sintática, sem importar — o export puxa `requests`) no `testes.yml` e no `bases-atualizacao.yml` diário; base nova com dado da planilha entra no dicionário `bases()`. `--dry-run` no export imprime contagens sem gravar.

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
situação além de `respondido`/`pendente` **e** nenhuma `data_resposta_merito`, o export está no
fallback "tem pasta no Drive" — e o painel (`baseClassificada()` em `requerimentos-app.js`) **não
fala em mérito**: rotula "com algum retorno da Prefeitura (inclui prorrogações; classificação de
mérito pendente)", troca o texto do topo, os rótulos do filtro e some com os filtros de trâmite.
Basta uma linha classificada para voltar à métrica de mérito.

## Comandos úteis

```bash
# Respostas do Executivo — testar scraping sem escrever (Drive/Sheets)
python respostas-executivo/index.py --dry-run --limite 3

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
