---
paths:
  - "precos/**"
  - "precos.html"
  - "precos-app.js"
  - "precos-index.json"
---

# Preço comparado (`precos/` + `precos.html`)

Compara o **preço unitário** que a Prefeitura de Santos pagou com o pago por municípios
vizinhos e de porte semelhante, item a item, a partir do **PNCP** (Portal Nacional de
Contratações Públicas). Responde a pergunta que a Base de Despesas não alcança: `despesas/`
sabe *quanto* e *para quem*, mas a API do Portal TP não expõe contrato, item, quantidade nem
preço unitário — só empenho/liquidação/pagamento.

**O fluxo é dirigido pela curadoria, não pela varredura.** A porta de entrada é o **item**:
`achar.py "papel a4"` lista o que Santos comprou, com preço e um teto de pares comparáveis, e
gera o rascunho da consulta; o curador escreve os termos e revisa. A ferramenta então procura
equivalentes no espelho local das cidades-par. Não há busca livre pelo visitante do painel —
cada comparação publicada passou por revisão humana. (Até 2026-08 a entrada era pelo
`numeroControlePNCP`, que obrigava a descobrir o número do pregão antes de qualquer coisa.)

## Fonte: três endpoints do PNCP (verificados em 2026-08-08)

```
GET /api/consulta/v1/contratacoes/publicacao   # listagem; exige codigoModalidadeContratacao
GET /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens          # descrição, qtd, unidade, estimado
GET /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{n}/resultados  # HOMOLOGADO + fornecedor
```

Armadilhas descobertas na verificação, todas tratadas em `fontes.py`:
- **`codigoMunicipioIbge` filtra pela localização da UNIDADE, não pela esfera** — consultar
  Guarujá devolve a Secretaria da Segurança Pública do estado (Bombeiros/GBMAR). O filtro
  correto é `esferaId == "M"` (`fontes.municipal()`), que também abraça autarquias e fundações
  municipais sem curar CNPJ à mão.
- **Paginar é obrigatório**: 16 registros vieram em 2 páginas no tamanho default. Usamos
  `tamanhoPagina=50` e sempre lemos `totalPaginas`.
- **`catalogoCodigoItem` e `ncmNbsCodigo` vêm NULOS** nas compras municipais — não existe
  CATMAT/CATSER para casar itens entre cidades. Daí todo o aparato de casamento textual.
- **204/404 são respostas normais** (mês sem contratação, compra sem itens): tratá-las como
  erro abortaria a cidade inteira.
- Rajada de consultas derruba `/api/consulta/` (500, depois timeout, voltando sozinho em
  minutos) enquanto `/api/pncp/` segue saudável — por isso `PAUSA=0.5` e backoff 15/30/45/60 s.

## Pipeline em 3 tiers (a ordem é obrigatória)

`crawler --itens` → `casar` → `crawler --resultados` → `casar` (2ª passada) → `export`

| Tier | O quê | Custo |
|---|---|---|
| 1 | listagem por (cidade, mês, modalidade) | ~360 chamadas |
| 2 | itens, 1 chamada por contratação | ~milhares, amortizado por `--orcamento` |
| 3 | resultados, 1 chamada por item | **completo para Santos** · **puxado para as pares** |

**O Tier 3 é assimétrico de propósito** (decisão de 2026-08):

- **Cidades-par: puxado.** `casar.py` roda de graça sobre o texto já espelhado e só então
  marca quais itens merecem a chamada. Sem isso seriam ~260 mil requisições para responder a
  uma pergunta sobre 6 itens. Filtros em cascata: casou → `temResultado=1` →
  `resultado_status='nao_pedido'`.
- **Santos: completo** (`crawler.py --resultados --santos`, ~3,8 mil chamadas). Aqui a
  varredura não é especulativa — o espelho de Santos já está 100% mapeado, então completar os
  preços é fechar uma conta conhecida. É o que permite **escolher um item e ter a comparação
  na hora**, sem esperar rede, e o que torna o `achar.py` útil de verdade.

**Escopo enxuto (decisão de 2026-08):** modalidades **6** (pregão eletrônico) e **8** (dispensa),
de **2025-01** em diante, 9 cidades-par — Guarujá, São Vicente, Praia Grande, Cubatão, Jundiaí,
Piracicaba, Mogi das Cruzes, Bauru e São José dos Campos (códigos IBGE conferidos contra a API
do IBGE). Ampliar é seguro (o `controle_listagem` refaz só o que falta) mas multiplica o backfill.

## Persistência: o espelho é a fonte da verdade

`precos/espelho/<ibge>-<ano>.jsonl.gz` é **versionado**; `precos.sqlite` é derivado e
gitignored, reconstruído por `reconstruir.py` em <1 min. Motivo: o cache do Actions expira em
7 dias e o backfill custa horas — um cache miss congelaria a base em silêncio (a armadilha
registrada em `.claude/rules/github-actions.md`). O gzip é gravado com `mtime=0`, senão cada
execução produziria diff só pelo timestamp do cabeçalho. Teto de 20 MB, com aborto no workflow.

## Descoberta (`achar.py`) — 100% offline

`python precos/achar.py papel a4` acha os itens de Santos, ranqueados, com preço, unidade,
avisos e um **teto de pares comparáveis**. Não faz nenhuma requisição: o espelho já tem os
5,5 mil itens de Santos e os preços deles (Tier 3 completo).

**O ranqueamento por posição é indispensável.** Buscar `agulha` sem ranquear devolve cinco
máquinas de costura entre os oito primeiros de 119 resultados — e até um fogão industrial,
porque a palavra aparece no fundo do spec. As descrições do PNCP são `TÍTULO -
Especificação: <spec longo>`: o produto está no começo. Níveis: rel 3 = nos 4 primeiros
tokens · rel 2 = nos primeiros 90 caracteres · rel 1 = nos primeiros 240 · rel 0 = fundo do
spec (só com `--tudo`).

**O funil é TETO, não previsão.** `A texto → B unidade → C com preço → D cidades`, sem
aplicar `excluir`, confiança nem outlier — esses só existem depois que o curador escreve os
termos. Calibrado contra a comparação publicada: com os termos curados da agulha dá
`7 → 7 → 4 · 3 cidades`, exatamente os 4 aceitos do `casar.py`. Teto **acima de 40 é mau
sinal**, não bom: significa termo genérico demais, e o veredicto diz isso.

**A quebra "perdidos na unidade" é o que mais rende**: mostra qual `conversoes_extra`
destravaria a comparação (no caso `papel a4`, 27 dos 37 candidatos morrem na unidade).

**O que `achar.py` deliberadamente NÃO faz:**
- **não sugere termos.** Testado e descartado: ordenar os tokens por raridade sugere `chico`,
  `gema`, `rabello` para "perito para apuração de imóveis na Travessa Gema Rabello, bairro
  Chico de Paula" — nome de rua e de bairro são sempre os tokens mais raros. O rascunho nasce
  com `termos` **vazios**, e o curador escreve.
- **não publica.** Rascunho sai com `publicada: false` e `--gravar` recusa sobrescrever.

**Armadilha da contagem de embalagem:** a descrição de um item vendido por `UNI` costuma citar
"caixa com 100 unidades" — que é só a embalagem de entrega. Propor `conversoes_extra` ali
dividiria o preço por 100. Por isso a contagem **só vale quando a unidade cobrada É a
embalagem** (`CX`, `Frasco`, `Resma`); em unidade desconhecida o número é reportado no bloco
`revisar`, sem virar fator.

**Efeito colateral:** todo arquivo em `consultas/`, inclusive rascunho, é lido por
`crawler.carregar_santos()` e `casar.py --todas` — o que puxa Tier 3 do que casar. É pouco
(~2-3 chamadas + os resultados dos pares que casaram) e são exatamente os dados de que a
curadoria precisa, mas não é grátis.

## Casamento determinístico (`casar.py`) — rejeitar é o padrão

Cadeia de gates booleanos; o **primeiro que falha** rejeita e grava o motivo. O jaccard entra
depois, e só para graduar confiança — nunca para admitir item que um gate reprovou.

Gates, em ordem: situação do item → material×serviço → termos obrigatórios → grupos `algum_de`
→ termos de exclusão → **unidade** → specs numéricas → faixa de quantidade → SRP → resultado
publicado → preço > 0 → janela temporal → outlier (2ª passada, mediana/6 a mediana×6).

**O gate de unidade é o coração:** `unidades.py` só converte dentro da mesma família, e
`VERBA`/`LOTE`/`GLOBAL`/`SERVIÇO`/`OUTRAS UNIDADES` são mapeadas para a família `opaco`, que não
converte para nada — são rótulos que escondem a quantidade real. Unidade fora da tabela **nunca
é adivinhada**.

Decisão de 2026-08, tirada da auditoria do espelho real (95% das unidades reconhecidas):
**embalagem sem quantidade declarada ganha família própria** — `CX`, `FRS`, `AMP`, `LTA`,
`Comprimido`, `Bloco` etc. só casam com a mesma embalagem e **nunca viram `un`**, porque uma
caixa pode ter 10 ou 100 itens e o edital costuma não dizer. Com a quantidade declarada
(`CX C/100`, `Embalagem 500,00 G`, `FRASCO 500ML`) o parser converte normalmente. Armadilha
vizinha: **`LT` é litro, `LTA` é lata** — não unificar. Quantidade zero (`FRASCO 0ML`, de
edital mal digitado) é rejeitada na fonte, senão viraria divisão por zero no preço unitário.

**Ao mexer em `unidades.py` ou `texto.py`, rode `crawler.py --renormalizar`**: os itens já
espelhados guardam o resultado da tabela antiga. O casamento recalcula o fator na hora e não
depende dessas colunas, mas elas alimentam as consultas de auditoria. **Depois, rode
`casar.py --todas` + `export.py` e confira que as comparações publicadas não mudaram** — a
renormalização reescreve o espelho versionado e pode mexer no que já está no ar.

**Duas correções de 2026-08, encontradas ao construir o `achar.py`:**

1. `texto.normalizar` aplicava as abreviações com barra (`p/ c/ s/ n/`) via `replace` cru,
   sem fronteira de palavra: `criticos/graves` virava `critico **sem** graves`, `MS/ANVISA`
   virava `m sem anvisa`. Atingia **2% das descrições** — inventava tokens raros e apagava os
   certos. Agora exige início-de-string ou espaço antes.
2. `unidades.normalizar_unidade` caía no fallback de primeira palavra e ignorava a contagem:
   `Pacote 100,00 FL` → `("un", 1)`, publicando o preço do pacote como preço da folha (erro
   de até 1000×), e `CX COM 5.000 UND` lia 5 em vez de 5.000. Agora: `_CONTAGEM_EMBUTIDA`
   entende a unidade de fornecimento padronizada do PNCP; `_quantidade()` decide milhar ×
   decimal **por posição** (três dígitos após o ponto = milhar), porque `normalizar` já
   igualou `5,000` e `5.000`; e o fallback **recusa** quando há número solto > 1 na string —
   contagem presente mas ilegível nunca vira fator 1. Cuidado ao mexer: `m2`/`m3` têm dígito
   no NOME e precisam continuar passando (por isso a checagem é de número *solto*).

Reconhecimento de unidade após as correções: **92%** dos 17.261 itens. O que sobra é
majoritariamente lixo de cadastro (`COM`, `1`, `-`, `EXAME`) ou abreviação ambígua
(`PEC`, `MET`, `FA`, `CAP`) que seria chute interpretar.

**Base única, sempre.** `base_da_ancora()` decide `homologado` (se Santos já tem adjudicação) ou
`estimado`, e a base vale para TODA a comparação. Cruzar estimado (teto de edital) com
homologado (preço de mercado) é o erro mais fácil e mais indefensável deste painel.

**Assimetria da curadoria:** `revisao.confirmados` só PROMOVE confiança de item que já passou
por todos os gates; `revisao.rejeitados` sempre vence. Não existe caminho para ressuscitar um
item reprovado sem editar as regras da própria consulta — o que aparece no diff do git.
Coberto por teste (`test_curadoria_confirmar_nao_ressuscita_item_reprovado`).

Confiança = jaccard sobre os tokens que **não** são termos da consulta (senão mediria a própria
consulta): alta ≥0,60 sem conversão de unidade; média 0,35–0,60 ou com conversão; **baixa fica
fora da mediana**. `texto.py` não faz stemming de propósito — em pt-BR aproxima palavras que não
são a mesma coisa ("papel"/"papelaria") e o falso positivo entra silencioso.

## Estatística e saída

`export.py` publica mediana, mín, máx, `n` e `n_cidades` — **nunca média nem desvio-padrão**
(com 5–15 observações seria teatro); quartis só com `n ≥ 8`. Com `n < 3` a comparação vira
`modo: "referencias_pontuais"`: sem manchete, sem `delta_pct`. A extrapolação "se tivesse pago a
mediana" só aparece com `n ≥ 5` **e** `n_cidades ≥ 3`, rotulada como projeção aritmética.
Preço **nominal e corrigido lado a lado** (IPCA de `ipca.py`, SIDRA/IBGE t1737 v2266 com
fallback SGS/BCB 433) — corrigir em silêncio seria tão desonesto quanto ignorar a inflação; o
último IPCA publicado defasa ~1 mês, então a base de correção nunca é "hoje".

Saída: **`precos-index.json`** (raiz, manifesto leve) + **`precos/dados/<slug>.json`** (um shard
por comparação, baixado só ao abrir). Toda observação carrega a **URL da fonte no PNCP** — o
export aborta se faltar. Cada comparação publica o denominador ("avaliados 214 · 9 comparáveis ·
205 descartados" com motivos agregados): sem o denominador, é indistinguível de cherry-picking.

**A lista muda de forma com o volume (decisão de 2026-08):** até **12** comparações é grade de
cartões; acima disso vira **tabela ordenável** com busca, filtro por tema/cidade/faixa de
diferença e estado na URL (`?q=&tema=&cidade=&dif=`), no padrão do Detalhamento de Despesas. A
barra de filtros só aparece a partir de 4 comparações — antes disso é ruído. No mobile o CSS já
converte a tabela em linhas empilhadas (`data-label`), então **não há checagem de viewport no JS**
(criaria bug no redimensionamento). Na coluna de diferença a notação é sempre `×` (`1,13×`,
`2,88×`): alternar entre "+13%" e "2,1×" na mesma coluna atrapalha a varredura; a frase por
extenso fica no cartão e no detalhe, onde há uma comparação de cada vez.

Cada consulta declara **`tema`** (Saúde, Educação, Limpeza, Obras, Administrativo…), agregado em
`indice.temas` — é o filtro que a lista usa quando cresce. Campo barato de adicionar agora e caro
de retroagir com dezenas de consultas escritas. A entrada do índice é **enxuta**: `descricao`,
`objeto`, `processo`, `modalidade` e `orgao` do item de Santos ficam só no shard (38% menor por
entrada; ~177 KB projetados para 200 comparações). O índice é baixado pelo cartão do hub e pela
paleta ⌘K em toda visita — peso ali é peso pago por todo visitante.

`precos.html` + `precos-app.js` (vanilla + Chart.js): lista de comparações com farol
**textual+ícone** (nunca só cor), detalhe em `?c=<slug>` (link citável via `Comum.gravarParams`)
com ficha do item de Santos, gráfico de dispersão preço×data com linha da mediana
(`Comum.chartAcessivel` obrigatório, repinta no evento `temamudou`), tabela ordenável com CSV,
`<details>` dos descartes e o bloco fixo **"o que estes números não provam"** — sem ele a
ferramenta é indefensável.

Cartão no Hub em "Bases de dados" (7º — a **linha órfã foi aceita por decisão do usuário em
2026-08**; não "corrigir" movendo cartões). Entrada em `PAGINAS` e na busca Ctrl+K do `comum.js`.

## Comandos úteis

```bash
# Descoberta: achar o item de Santos que vira âncora (offline, sem rede)
python precos/achar.py papel a4
python precos/achar.py agulha --limite 15 --ano 2026 --tudo
python precos/achar.py agulha 40 12 --item 1          # tokens + vizinhos p/ exclusões
python precos/achar.py agulha 40 12 --rascunho 1 --gravar --tema Saúde

# Preços de Santos completos (resumível; repetir até a fila zerar)
python precos/crawler.py --resultados --santos --orcamento 1500

# Tier 1 — amostra de uma célula sem gravar
python precos/crawler.py --listagem --cidade 3518701 --ano 2026 --mes 1 --modalidade 6 --dry-run

# Backfill (resumível: rode quantas vezes precisar)
python precos/crawler.py --listagem
python precos/crawler.py --itens --orcamento 2000
# --prioridade sobe na fila quem tem o termo no objeto (é ORDEM, não filtro)
python precos/crawler.py --itens --orcamento 500 --prioridade "generos alimenticios"

# Depois de mexer em unidades.py/texto.py (não faz requisição)
python precos/crawler.py --renormalizar

# Âncoras de Santos das consultas curadas
python precos/crawler.py --santos

# Tela de curadoria: o que casou, o que foi descartado e por quê
python precos/casar.py --slug placas-visuais-2026 --revisar

# Pipeline completo (a ordem importa)
python precos/casar.py --todas && python precos/crawler.py --resultados \
  && python precos/casar.py --todas && python precos/export.py --dry-run

# Reconstruir o sqlite a partir do espelho versionado
python precos/reconstruir.py

# Testes (gates de rejeição, unidades, normalização)
python -m pytest precos/tests -q
```

**Cuidado ao testar localmente:** `export.py` sobrescreve artefatos VERSIONADOS
(`precos-index.json`, `precos/dados/`) e o crawler reescreve `precos/espelho/`. Depois de
testar, `git restore` neles se a carga local estiver parcial — o espelho fresco vive no
repositório, não na sua máquina.
