# Playground — Ferramentas Parlamentares · Câmara de Santos

## Contexto do Projeto

Ferramentas de suporte ao gabinete de um vereador da Câmara Municipal de Santos (SP).
Stack: HTML/CSS/JS vanilla (frontend) + Python (automações).

## Aplicações

### Hub / Página inicial (`index.html`)
Porta de entrada do site (GitHub Pages serve da raiz). Página estática autocontida (navy/gold,
sem build) com cartões para os 3 bancos pesquisáveis — **Despesas, Proposituras e Legislação** —
cada um com um número "ao vivo" lido via `fetch` do respectivo `*-index.json` (degrada se falhar).
Rodapé "Outras ferramentas" linka Pauta e Gastos. Cada painel tem um link "← Início" de volta ao hub.

### Radar de Pauta (`pauta.html` + `app.js`)
Transforma texto de pauta legislativa em briefing político com classificação por prioridade,
tags temáticas e sugestão de discurso para plenário. (Antes era o `index.html`; movido para
`pauta.html` quando o hub virou a página inicial — `app.js`/`styles.css` seguem na raiz.)

### Radar de Gastos (`gastos.html` + `gastos-app.js`)
Dashboard de análise de gastos municipais a partir de CSV exportado da Prefeitura de Santos.
Usa Chart.js para visualizações e PapaParse para leitura de CSV.

### Briefing Ordem do Dia (`ordem-do-dia/index.py`)
Automação que acessa o site da Câmara, extrai os itens da pauta via scraping e gera
um briefing aprofundado com Claude API, entregue por e-mail HTML toda segunda e quarta às 23h.

### Respostas do Executivo (`respostas-executivo/index.py`)
Automação que varre a busca pública de "Respostas do Executivo" endereçadas ao vereador
(sem e-mail), baixa os PDFs do pedido original e da resposta do prefeito, organiza-os no
Google Drive (uma subpasta por item) e registra cada item numa planilha de controle.

### Base de Legislação (`legis/` + `legis.html`)
Índice pesquisável da legislação municipal de Santos a partir do **Legis da Prefeitura**
(`egov.santos.sp.gov.br/legis`). `legis/crawler.py` varre tópicos→anos→documentos coletando
**só metadados** (tipo, número, ano, data, ementa, tags + link do PDF oficial) num SQLite;
`legis/export.py` gera `legis.xlsx`/`legis.csv`/`legis-index.json`; `legis.html`+`legis-app.js`
é o painel (vanilla/CDN) com filtros tipo/ano/tema/palavra-chave. Texto integral, situação
(vigente/revogada) e relacionamentos ficam para fases futuras. Páginas em latin-1 com campos
UTF-8 embutidos (ementa/tags) — ver `_fix` em `crawler.py`. Carga inicial completa roda local;
`.github/workflows/legis.yml` faz a atualização incremental semanal (ano corrente).

### Base de Proposituras (`proposituras/` + `proposituras.html`)
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
semanalmente (`--forcar`) para manter situação/tramitação atualizadas. **Só `proposituras-index.json`
e o código são versionados**; `.sqlite` (~68M, pesado por causa da tramitação), `.xlsx` e `.csv`
ficam no `.gitignore` — o `.sqlite` persiste entre execuções do workflow via cache do Actions
(há guarda anti-truncamento no commit). Outros tipos (Indicação, Moção, Ofício, Requerimento) e o
cruzamento propositura→lei sancionada ficam para fases futuras.

### Base de Despesas (`despesas/` + `despesas.html`)
Consolidação da **execução da despesa da Prefeitura de Santos** (empenhado→liquidado→pago), a partir
da API pública do Portal da Transparência. `despesas/crawler.py` baixa **três endpoints** do
`transparencia.asmx`, cada um um estágio: `json_empenhos` (empenhado), `json_liquidacoes` (liquidado)
e `json_pagamentos` (pago) — todos `?ano=&mes=`, **um mês por requisição**; a resposta é um
**XML SOAP `<string>` com array JSON embutido como texto** (extrai `.text`, `html.unescape`,
`json.loads`). Cada estágio vai para sua tabela (`empenhos`/`liquidacoes`/`pagamentos`); a dedup é por
**`hash` MD5 das colunas-chave** (`INSERT OR IGNORE` → recarga idempotente); `controle_carga`
registra (fonte, ano, mês) já baixados. **Atenção:** os campos `empenho`/`liquidacao`/`pagamento` são
**números de documento**, não valores — o valor de cada estágio é a coluna `valor`. **A API NÃO expõe
unidade orçamentária (secretaria)**; o único campo de unidade é `unidade_gestora` (a entidade:
Prefeitura, CAPEP, IPS, fundações). O recorte por órgão usa **`funcao`** como proxy de área/secretaria.
`despesas/export.py` gera: (a) **`despesas-index.json` AGREGADO** na visão de **caixa/pago**
(totais, séries mensais, por função/elemento/fonte/unidade, top-300 favorecidos) + **alertas fiscais
por regras** (limiares no topo do arquivo); (b) **detalhe por empenho** — junta os 3 estágios por
(`unidade_gestora`,`empenho`) em `montar_execucao()` produzindo a tríade **empenhado/liquidado/pago**
por empenho, e inclui o que não casa (`Restos a pagar` = empenho de exercício anterior fora da base;
`Extra-orçamentário` = pagamento sem empenho) para não esconder nada; grava um arquivo por mês de
competência em `despesas/dados/AAAA-MM.json` (compacto `{campos, linhas}`, arrays-of-arrays; manifesto
na chave `meses`, campos em `campos_detalhe`) — **estes `dados/*.json` SÃO versionados** (Pages serve
sob demanda). `despesas.html`+`despesas-app.js` é o painel (vanilla + Chart.js via CDN) com abas
Visão geral/Alertas/Favorecidos (base pago) e **Detalhamento** (execução por empenho: seleciona 1+
meses ou ano inteiro, tabela com empenhado/liquidado/pago, busca sem acento, **filtros estruturados**
por tipo/unidade/função/fonte/grupo, ordenação, paginação e exportar CSV do filtro). Carga padrão =
**mandato (2025→ano corrente, `ANO_INICIAL=2025`)**. **`despesas-index.json`, `despesas/dados/*.json`
e o código são versionados**; `.sqlite`/`.xlsx`/`.csv` no `.gitignore` — o `.sqlite` persiste via cache
do Actions e `.github/workflows/despesas.yml` reprocessa o ano corrente diariamente (`--forcar`), com
guarda anti-truncamento (aborta commit se total < 50mi). **Independente** do antigo Radar de Gastos
(`gastos.html`, por upload de CSV), que segue intacto. Unidade orçamentária real (outra fonte),
cruzamento favorecido↔licitações e IA sobre os alertas ficam para fases futuras.

#### Briefing semanal de despesas (`despesas/briefing.py`)
Canal *push* para os assessores: e-mail HTML semanal com o panorama das despesas, **só informativo**
(determinístico, **sem Claude/tokens**). Lê o `despesas.sqlite` e reusa `conectar()`/`alertas()` de
`export.py` (via `import export`) + o padrão SMTP de `ordem-do-dia/index.py`. A "semana" = os 7 dias
que terminam na **data de pagamento mais recente** da base (robusto à defasagem do portal); o pago da
semana é comparado à **média semanal do ano** (baseline estável, já que pagamentos são irregulares).
Seções: cards (semana/mês/ano com variação YoY), alertas vigentes (alta/média), gasto por função, top
favorecidos, maiores pagamentos individuais e maiores empenhos novos, com link para o painel. CLI:
`--dry-run` (imprime, não envia), `--salvar PATH` (preview HTML), `--semana N`. Destinatários:
**`DESPESAS_BRIEFING_TO`** → **`RESPOSTAS_EMAIL_TO`** (mesma lista do requerimentos) → **`GMAIL_TO`**.
Agendamento: passo final do
`despesas.yml` que roda **às segundas** (`date +%u = 1`) após o crawl+export — ou via
`workflow_dispatch` com input `forcar_briefing=true`. Geração de minutas/IA e outros canais
(WhatsApp/Telegram) ficam para fases futuras.

### Monitor do Diário Oficial (`diario-oficial/`)
Automatiza a varredura diária que os assessores faziam à mão no **Diário Oficial de Santos (DOM)**:
baixa o PDF da edição (`diariooficial.santos.sp.gov.br/edicoes/inicio/download/AAAA-MM-DD`), extrai e
**classifica deterministicamente (sem IA/tokens)** os atos das categorias-alvo — **Contratos e aditivos,
Licitações e dispensas, Convênios e fomento (inclui Terceiro Setor: termos de compromisso/PROMICULT),
Leis e decretos, Orçamento (créditos adicionais) e Fiscal/Tributário (baixa retroativa de inscrição/
renúncia de receita)** — e **anexa os atos novos numa planilha do Google Sheets** (aba única "Atos do
DOM", coluna `Categoria` para filtrar). Pessoal (nomeações/exonerações) fica para fase futura. Pipeline:
`extrator.py` → `classificador.py` → `risco.py` → dedup SQLite → `sheets.py`.
- **`extrator.py`** resolve o **layout multi-coluna** do DOM: detecta 1 vs 2 colunas pela cobertura de
  tinta na faixa central e separa no *gutter* (o `extract_text` ingênuo intercala as colunas); o **índice**
  do PDF mapeia secretaria→página, dando a **secretaria** de cada ato (unidade que falta na Base de Despesas).
- **`classificador.py`** detecta atos por âncora **no início da linha** — removendo antes prefixos de
  cabeçalho (`REPUBLICAÇÃO DO`, `RETIFICAÇÃO DE`, `AUTORIZAÇÃO DE`...) p/ não perder atos republicados —
  e exige **número** no cabeçalho (mata fragmentos de cláusula); leis/decretos filtrados pelo **ano**.
  **Homologações de pregão** saem como "COMUNICADO ... HOMOLOGOU" (âncora-sentinela `COMUNICADO` com guarda
  de verbo de resultado + nº de modalidade); na variante PRODESAN o nº está no "EDITAL" e o objeto/valor no
  "COMUNICADO" seguinte (fusão dos dois blocos). Atos **sem cabeçalho próprio** (contratação direta por
  inexigibilidade em despacho; **baixa retroativa de inscrição** — só anos anteriores ao da edição = renúncia)
  são captados por `_atos_por_frase` no texto corrido. Secretaria vem de `UNIDADE:` → **signatário**
  ("Secretário Municipal de X") → índice. Crédito aberto por Decreto/Lei não é duplicado (já é a norma).
  Dedup por (categoria, número, secretaria). Captura objeto, valor, favorecido, processo, e os campos de
  risco: `termo` (nº do aditivo), `valor_num`, `retroativo`.
- **`risco.py`** aplica os **gatilhos da skill `dom-santos`** (versionada em `diario-oficial/references/`)
  de forma **determinística, sem IA e sem a Base de Despesas** — só dados do ato + histórico do `diario.sqlite`:
  aditivo ≥3º termo / 2º termo, efeitos retroativos, dispensa/inexig. acima do limite (art. 75), crédito
  extraordinário, OSC repetida/valores idênticos, valor elevado. Gera colunas **Risco** (🔴🟡🟢) e
  **Motivo do risco** (com base legal) — os 🔴 são insumo para a skill redigir requerimentos/representações.
  Limiares legais ficam em constantes no topo de `risco.py` (**verificar anualmente**).
- **`sheets.py`** reusa o OAuth/Sheets do `respostas-executivo` (mesmo `GOOGLE_OAUTH_TOKEN`, escopo Sheets);
  planilha dedicada em **`DOM_SHEET_ID`**. Formatação aplicada por script (cabeçalho navy/dourado, filtro,
  zebra, cores por categoria e por nível de risco).
- **E-mail aos assessores:** `monitor.py --email` envia, ao fim do run, um briefing HTML com os atos novos
  (🔴/🟡 no topo, com o motivo/base legal e link p/ a planilha) via Gmail SMTP — só quando há atos novos.
  Destinatários: `DOM_BRIEFING_TO` → `DESPESAS_BRIEFING_TO` → `RESPOSTAS_EMAIL_TO` → `GMAIL_TO`.
- **`.sqlite` no `.gitignore`**, persiste via cache do Actions; `.github/workflows/diario-oficial.yml`
  roda **dias úteis (seg–sex) ~00:17 BRT** (cron `17 3 * * 1-5`, minuto quebrado p/ fugir do
  congestionamento do topo da hora; o DOM sai no fim da noite anterior e não publica sáb/dom) com
  `--dias 3 --email`, e via `workflow_dispatch` (`--data` envia e-mail; `--desde` é backfill sem e-mail). **Só código e referências são versionados** — a saída é o Sheets, não há commit de
  dados. Geração de peças (requerimentos) segue na **skill `dom-santos` no Claude web**; cruzar
  favorecido↔Despesas e nomeações/exonerações ficam p/ fases futuras.

## Arquitetura da Automação (ordem-do-dia)

- **Fonte de dados:** `https://administrativo.camarasantos.sp.gov.br/dispositivo/ideCustom/legislativo/ordem_dia_eletronica/publico/`
- **API de sessões:** `listagem.php?codigo=SESSION_ID` (HTML com `.documento` divs)
- **IA:** Claude Sonnet via `@anthropic-ai/sdk` (Python SDK)
- **Entrega:** Gmail SMTP com e-mail HTML estilizado
- **Agendamento:** GitHub Actions (`.github/workflows/ordem-do-dia.yml`), cron `0 2 * * 2,4`

## Arquitetura da Automação (respostas-executivo)

- **Fonte de dados:** `busca_documento_pub/filtro_resultado.php?pesquisa_resposta_executivo[ano]=AAAA&pesquisa_resposta_executivo[autor]=282` (paginada via `&limite=N`, 20/página). Páginas em ISO-8859-1. **As respostas ficam arquivadas no ano de ENVIO da propositura**, não no ano da resposta — por isso a rotina varre, por padrão, **de 2025 (`ANO_INICIAL`, 1º ano do mandato) até o ano corrente** (`--ano` aceita lista, ex.: `2025,2026`).
- **Página canônica:** o link "Mais detalhes" de cada resultado aponta para `detalhes.php?cod=...` do pedido original — contém tipo, número, processo, data, ementa, PDF do pedido e a seção "Resposta anexada" com os PDFs do prefeito.
- **Arquivamento:** Google Drive via OAuth do próprio usuário (`google-api-python-client`), uma subpasta por item (`Tipo Número`). Token gerado por `setup_oauth.py` (1x); lido de `token.json` (local) ou do secret `GOOGLE_OAUTH_TOKEN` (CI).
- **Registro:** Google Sheets; duas abas (`indicações`/`requerimentos`), roteamento por tipo. Para cada item localiza a linha existente pelo número e **atualiza** as colunas `Resposta` (hyperlink para a subpasta do Drive) e `Data da resposta`; se o número não existir, **anexa** linha nova; se a resposta já estiver preenchida, **pula** (ver `ABAS`/`carregar_planilha` em `index.py`). Pastas no Drive: `REQUERIMENTO_<nº>` / `INDICACAO_<nº>`.
- **Log diário:** aba `Log diário` (criada automaticamente) recebe uma linha por resposta processada (data, tipo, número, assunto, data da resposta, link). Com `--email`, envia também um resumo HTML via Gmail SMTP (secrets `GMAIL_*`) — só quando há novidades.
- **Agendamento:** GitHub Actions (`.github/workflows/respostas-executivo.yml`), cron `0 9 * * 1-5` (06h BRT, dias úteis).

## Secrets do GitHub Actions

| Secret | Descrição |
|---|---|
| `ANTHROPIC_API_KEY` | API do Claude (ordem-do-dia) |
| `GMAIL_USER` | Conta Gmail remetente (ordem-do-dia) |
| `GMAIL_APP_PASSWORD` | App Password de 16 dígitos (ordem-do-dia) |
| `GMAIL_TO` | Destinatário(s) do briefing (ordem-do-dia; fallback do briefing de despesas) |
| `DESPESAS_BRIEFING_TO` | Destinatário(s) do briefing semanal de despesas — assessores (opcional; cai em `GMAIL_TO`) |
| `GOOGLE_OAUTH_TOKEN` | JSON do token OAuth Drive+Sheets, gerado por `setup_oauth.py` (respostas-executivo) |
| `SHEET_ID` | ID da planilha de controle (respostas-executivo) |
| `DRIVE_FOLDER_ID` | ID da pasta-raiz no Drive (respostas-executivo) |
| `DOM_SHEET_ID` | ID da planilha dedicada do Monitor do Diário Oficial (reusa `GOOGLE_OAUTH_TOKEN`) |
| `DOM_BRIEFING_TO` | Destinatário(s) do e-mail diário do DOM — assessores (opcional; cai em `DESPESAS_BRIEFING_TO`) |

## Convenções

- Frontend: sem build tools, sem npm, CDN direto no HTML
- Python: sem virtualenv, dependências em `requirements.txt`
- Português brasileiro em todo o código (comentários, variáveis, UI)
- Commits em português

## Comandos úteis

```bash
# Rodar briefing manualmente
python ordem-do-dia/index.py

# Rodar para sessão específica
python ordem-do-dia/index.py --sessao 1278

# Disparar workflow no GitHub
gh workflow run "Briefing Ordem do Dia" --repo derosisjr/Playground

# Respostas do Executivo — testar scraping sem escrever (Drive/Sheets)
python respostas-executivo/index.py --dry-run --limite 3

# Respostas do Executivo — rodar de verdade (ano corrente)
python respostas-executivo/index.py

# Respostas do Executivo — ano específico
python respostas-executivo/index.py --ano 2026

# Proposituras — amostra sem gravar
python proposituras/crawler.py --ano 2026 --limite 5 --dry-run

# Proposituras — carga de um ano (com tramitação)
python proposituras/crawler.py --ano 2026

# Proposituras — carga inicial completa (todos os anos) + export
python proposituras/crawler.py
python proposituras/export.py

# Despesas — amostra de um mês sem gravar
python despesas/crawler.py --ano 2026 --mes 6 --dry-run

# Despesas — carga de um ano (ou mês específico com --mes)
python despesas/crawler.py --ano 2026

# Despesas — carga do mandato (2025→corrente) + export
python despesas/crawler.py
python despesas/export.py

# Despesas — briefing semanal (preview sem enviar)
python despesas/briefing.py --dry-run
python despesas/briefing.py --salvar despesas/_briefing.html  # abrir no navegador

# Diário Oficial — testar 1 edição sem escrever (imprime atos + risco)
python diario-oficial/monitor.py --data 2026-06-12 --dry-run

# Diário Oficial — depurar a extração de uma página (layout-aware)
python diario-oficial/extrator.py --data 2026-06-12 --pagina 8

# Diário Oficial — gravar no Sheets (precisa DOM_SHEET_ID no ambiente)
DOM_SHEET_ID=... python diario-oficial/monitor.py --data 2026-06-13
DOM_SHEET_ID=... python diario-oficial/monitor.py --desde 2026-06-09 --ate 2026-06-12  # intervalo
```
## PERFIL POLÍTICO DO MANDATO

Rui de Rosis Jr.
Vereador de oposição ao governo municipal. De direita, filiado ao Partido Liberal (PL).

### POSICIONAMENTO
- Defesa do contribuinte e do pagador de impostos acima de qualquer agenda de governo.
- Estado enxuto, eficiente e transparente. Cada real gasto deve ter justificativa técnica.
- Liberdade econômica, desregulamentação e desburocratização.
- Fiscalização permanente do Executivo: questionar necessidade, legalidade e economicidade de todo ato.
- Nunca ser condescendente com o governo. O papel é cobrar, fiscalizar e propor alternativas melhores.
- Atenção especial a projetos de autoria do PT e do PSOL, ou de qualquer partido, que carreguem viés ideológico de esquerda: identitarismo, intervencionismo econômico, expansão de burocracia estatal, criação de conselhos ou órgãos sem função clara, políticas assistencialistas sem porta de saída, regulação excessiva sobre a iniciativa privada ou cerceamento de liberdades individuais e econômicas. Analisar com rigor redobrado independentemente do autor — o critério é o conteúdo, não apenas a sigla.

### COMO ISSO DEVE REFLETIR NO RELATÓRIO DA ORDEM DO DIA

1. PROJETOS DO EXECUTIVO: tratar com desconfiança técnica, não com hostilidade cega. Analisar impacto fiscal real, fonte de custeio, necessidade comprovada. Se o projeto cria despesa, exigir clareza sobre quanto custa e de onde sai o dinheiro. Nunca recomendar voto favorável automático só porque "as comissões aprovaram" — comissões com maioria governista aprovam qualquer coisa.

2. IMPACTO FISCAL: é o critério número um. Todo projeto que cria ou amplia gasto público deve ser analisado com rigor. Perguntar sempre: isso é necessário? Existe alternativa mais barata? O contribuinte está sendo protegido?

3. TRANSPARÊNCIA E CONTROLE: projetos que aumentam transparência, publicidade de dados e prestação de contas devem ser apoiados com entusiasmo. Essa é a nossa bandeira.

4. PROJETOS SIMBÓLICOS E HONORÍFICOS: votar a favor quando não houver custo ao erário e o homenageado não for controverso. Não gastar capital político com obstrução a homenagens consensuais.

5. SELOS, CERTIFICAÇÕES E PROGRAMAS VOLUNTÁRIOS: avaliar se criam burocracia desnecessária, se o município tem estrutura para gerir, se não é legislação para inglês ver. Preferir soluções de mercado a soluções de governo.

6. PROJETOS COM VIÉS IDEOLÓGICO DE ESQUERDA: identificar e sinalizar no relatório quando uma matéria — independentemente do partido autor — se enquadrar no espectro de esquerda. Isso inclui: linguagem identitária, criação de obrigações ao setor privado sem contrapartida, expansão do aparelho estatal, políticas de cotas ou reservas sem critério de mérito, instrumentos de controle social que restrinjam liberdade de expressão ou de empresa. Nesses casos, o relatório deve detalhar o viés identificado, o impacto prático e recomendar posicionamento contrário ou emendas que neutralizem o conteúdo ideológico preservando eventual mérito técnico.

7. TOM DO RELATÓRIO: técnico, direto, sem bajulação ao governo e sem panfletagem. Apontar problemas com dados e base legal. Quando o projeto for bom, dizer que é bom — mas explicar por quê, não apenas seguir o rebanho. Quando for ruim, dizer que é ruim e fundamentar.

8. SUGESTÃO DE EMENDAS: sempre que um projeto tiver mérito mas apresentar falhas (falta de fonte de custeio, prazo irreal, ausência de controle, discricionariedade excessiva ao Executivo), sugerir emendas concretas em vez de simplesmente votar contra.

9. LINGUAGEM PARA ELEITORES: quando incluir sugestão de fala para eleitores, usar tom de quem defende o bolso do cidadão e cobra eficiência do governo. Nunca usar tom de quem coopera com o governo. Mesmo votando a favor de um projeto do Executivo, o enquadramento é "aprovei porque é bom para o cidadão", nunca "aprovei porque o prefeito propôs".

10. NÃO TRATAR INFERÊNCIA COMO FATO: se não há dado concreto no texto do projeto, marcar como [Verificar] ou [Sem informação no texto]. Nunca presumir que "as comissões avaliaram" significa que está tudo certo.

11. POSICIONAMENTO SUGERIDO: sempre justificar com argumento fiscal, jurídico ou de eficiência. Nunca justificar com "é politicamente seguro" ou "não gera desgaste". O mandato não busca conforto político, busca resultado para o contribuinte.

12. VETOS DO PREFEITO: sempre buscar argumentos para a derrubada do veto, caso viável juridicamente. As mensagens de veto costumam ter erros juridicos e de enquadramento. Em caso de veto, desconsiderar o parecer da ccj.