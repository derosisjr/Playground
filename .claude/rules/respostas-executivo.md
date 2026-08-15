---
paths:
  - "respostas-executivo/**"
  - "requerimentos.html"
  - "requerimentos-app.js"
---

# Respostas do Executivo (`respostas-executivo/index.py`)

Automação que varre a busca pública de "Respostas do Executivo" endereçadas ao vereador
(sem e-mail), baixa os PDFs do pedido original e da resposta do prefeito, organiza-os no
Google Drive (uma subpasta por item) e registra cada item numa planilha de controle.

## Arquitetura da Automação

- **Fonte de dados:** `busca_documento_pub/filtro_resultado.php?pesquisa_resposta_executivo[ano]=AAAA&pesquisa_resposta_executivo[autor]=282` (paginada via `&limite=N`, 20/página). Páginas em ISO-8859-1. **As respostas ficam arquivadas no ano de ENVIO da propositura**, não no ano da resposta — por isso a rotina varre, por padrão, **de 2025 (`ANO_INICIAL`, 1º ano do mandato) até o ano corrente** (`--ano` aceita lista, ex.: `2025,2026`).
- **Página canônica:** o link "Mais detalhes" de cada resultado aponta para `detalhes.php?cod=...` do pedido original — contém tipo, número, processo, data, ementa, PDF do pedido e a seção "Resposta anexada" com os PDFs do prefeito.
- **Arquivamento:** Google Drive via OAuth do próprio usuário (`google-api-python-client`), uma subpasta por item (`Tipo Número`). Token gerado por `setup_oauth.py` (1x); lido de `token.json` (local) ou do secret `GOOGLE_OAUTH_TOKEN` (CI).
- **Registro:** Google Sheets; duas abas (`indicações`/`requerimentos`), roteamento por tipo. Para cada item localiza a linha existente pelo número e **atualiza** as colunas `Resposta` (hyperlink para a subpasta do Drive), `Data da resposta`, `Situação da resposta` e `Data da resposta de mérito`; se o número não existir, **anexa** linha nova; se a situação já for `respondido` e não houver PDF novo, **pula** (ver `ABAS`/`carregar_planilha` em `index.py`). Pastas no Drive: `REQUERIMENTO_<nº>` / `INDICACAO_<nº>`.
- **Log diário:** aba `Log diário` (criada automaticamente; `garantir_aba_log` completa o cabeçalho se faltar coluna) recebe uma linha por resposta processada (data, tipo, número, assunto, data da resposta, link, situação). Com `--email`, envia também um resumo HTML via Gmail SMTP (secrets `GMAIL_*`) — só quando há novidades, distinguindo mérito de trâmite.
- **Agendamento:** GitHub Actions (`.github/workflows/respostas-executivo.yml`), cron `31 8 * * 1-5` (05h31 BRT, dias úteis).
- **Painel de Requerimentos & Respostas (`requerimentos.html` + `requerimentos-app.js`):** cartão "Requerimentos" na seção Bases de dados do hub. `respostas-executivo/export.py` lê a aba `requerimentos` da planilha (via Sheets API, reusando `_google_services`/`_idx_header` de `index.py`) e gera `requerimentos-index.json` na raiz — array com número, ano, assunto, datas, situação, `respondido` e `url_resposta`. **A coluna `Resposta` é uma fórmula `=HYPERLINK(...)`**, então o export lê com `valueRenderOption="FORMULA"` e extrai a URL do Drive por regex. O painel (vanilla, sem acento, paginado) tem busca + filtros de ano/situação e link para a pasta no Drive (exige login do gabinete) ou badge "Pendente". O JSON é gerado e commitado pelo passo final do `respostas-executivo.yml` (com guarda anti-base-vazia). `--dry-run` no export imprime contagens sem gravar.

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

## Comandos úteis

```bash
# Respostas do Executivo — testar scraping sem escrever (Drive/Sheets)
python respostas-executivo/index.py --dry-run --limite 3

# Respostas do Executivo — rodar de verdade (ano corrente)
python respostas-executivo/index.py

# Respostas do Executivo — ano específico
python respostas-executivo/index.py --ano 2026

# Classificador — testes com PDFs reais como fixture
python -m unittest discover -s respostas-executivo -p "testes_*.py"

# Backfill da classificação (relatório sem gravar; depois de verdade)
python respostas-executivo/reclassificar.py --dry-run
python respostas-executivo/reclassificar.py
```
