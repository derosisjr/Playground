# Painel de Endividamento (`endividamento/` + `endividamento.html`)

Raio-X da **dívida pública e dos limites da LRF** da Prefeitura de Santos, a partir do
**RGF (Relatório de Gestão Fiscal)** publicado no SICONFI/Tesouro Nacional — a mesma API
`apidatalake.tesouro.gov.br` já usada pelo módulo `indicadores/` (lá, DCA anual; aqui,
`/tt/rgf` quadrimestral). Inspirado no PL 70/2026 de Itanhaém ("Painel Municipal de
Endividamento e Transparência Fiscal"); serve de acompanhamento e de prova de conceito
para propor PL análogo em Santos.

Pipeline padrão da casa: `endividamento/crawler.py` baixa por quadrimestre os anexos
01 (pessoal), 02 (dívida consolidada), 03 (garantias — **Santos publica vazio**, degrada)
e 04 (operações de crédito), filtra pelas contas mapeadas em `fontes.CONTAS`
(**casamento por fragmento de rótulo normalizado** — os rótulos têm numerais romanos e
mudam de grafia entre exercícios) e grava em `endividamento.sqlite`
(`INSERT OR REPLACE`; `controle_carga` por (ano, quadrimestre); quadrimestre não
publicado devolve 0 itens e fica fora do controle → retenta na próxima execução; só o
exercício corrente + anterior são rebaixados). `ANO_INICIAL=2018`.

**Peculiaridades de parsing:** o Anexo 02 traz as 4 colunas do ano inteiro
("SALDO DO EXERCÍCIO ANTERIOR", "Até o 1º/2º/3º Quadrimestre") em cada publicação — o
export usa a coluna do próprio quadrimestre; os Anexos 01/04 usam colunas "Valor" e
"% sobre a RCL Ajustada" (caixa varia: Anexo 04 vem em CAIXA ALTA). Restos a pagar e
disponibilidade de caixa saem da seção Deduções do Anexo 02 (não é preciso o Anexo 05).
Limite de pessoal usado = **54% (Executivo, art. 20 LRF)**, com prudencial 51,3% e
alerta 48,6% — valores lidos do próprio RGF, não hardcoded.

`endividamento/export.py` gera **`endividamento-index.json`** (raiz, minificado):
`serie` quadrimestral (DC, DCL, RCL, %s, pessoal, op. crédito, precatórios vencidos,
RP, caixa, passivo atuarial), `semaforo` (3 mostradores — dívida/pessoal/op. crédito —
com cor verde/amarelo/vermelho pelos **limites oficiais do próprio RGF**), `totais` e
`resumo` narrativo determinístico. Guardas: aborta se RCL < R$ 1 bi ou semáforo
incompleto; o workflow (`endividamento.yml`, cron mensal dia 5) confere série ≥ 10
pontos antes do commit. `.sqlite` gitignored (cache do Actions).

`endividamento.html` + `endividamento-app.js` é o painel público (vanilla + Chart.js):
primeira dobra = **Semáforo Fiscal** (mostradores com farol + medidor até o limite,
estado também em texto/ícone — nunca só cor), número-âncora da dívida bruta, gráficos
de evolução (dívida, % da RCL vs limites tracejados, pessoal, precatórios), tabela
quadrimestral com export CSV e bloco didático "Entenda". Card no Hub (`index.html`)
lê `endividamento-index.json`; entrada em `PAGINAS` no `comum.js`.

**Seção "Serviço da dívida" (cross-módulo):** os credores e o pago em juros/amortização
vêm do bloco `servico_divida` do `despesas-index.json` (gerado por `despesas/export.py`:
grupos de despesa com prefixo 32=juros, 46=amortização; credores agrupados por documento).
O painel busca esse JSON como fonte secundária e a seção some se ele faltar.

**Seção "Dívida das estatais" (curadoria manual):** CET, PRODESAN e COHAB têm
contabilidade societária própria e ficam FORA do RGF/SICONFI. Os números vêm de
`endividamento/estatais.json` (versionado, editado à mão a partir dos balanços
auditados anuais — PRODESAN publica em prodesan.com.br/transparencia; CET/COHAB
ainda sem balanço em formato aberto). O export embute o arquivo no índice como `estatais`.
Atualizar 1×/ano quando os balanços saírem (~abril/maio).

Fora de escopo (decisão de 2026-07): detalhe de precatórios (não vem estruturado do
SICONFI); comparativo com outros municípios.

## Comandos úteis

```bash
# Amostra de um quadrimestre sem gravar
python endividamento/crawler.py --ano 2023 --periodo 3 --dry-run

# Carga completa (2018→corrente) + export
python endividamento/crawler.py
python endividamento/export.py

# Conferir o índice sem gravar
python endividamento/export.py --dry-run
```
