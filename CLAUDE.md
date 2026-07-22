# Playground — Ferramentas Parlamentares · Câmara de Santos

## Contexto do Projeto

Ferramentas de suporte ao gabinete de um vereador da Câmara Municipal de Santos (SP).
Stack: HTML/CSS/JS vanilla (frontend, GitHub Pages serve da raiz) + Python (automações
via GitHub Actions).

## Convenções

- Frontend: sem build tools, sem npm, CDN direto no HTML
- Python: sem virtualenv, dependências em `requirements.txt`
- Português brasileiro em todo o código (comentários, variáveis, UI)
- Commits em português

## Conduta do assistente

- Em pedido ambíguo, não escolha em silêncio: apresente as interpretações
  possíveis e pergunte. Uma boa pergunta economiza cinco rodadas de correção.
- Transforme tarefa vaga em critério verificável antes de começar
  ("conserte o bug" → "teste que reproduz o bug, depois fazê-lo passar").
- Implemente o mínimo que resolve. Sem features além do pedido, sem
  abstração para código de uso único.
- Mudanças cirúrgicas: toque só no que o pedido exige. Não "melhore" código,
  comentários ou formatação vizinhos; remova só o que a sua mudança deixou
  órfão, não código morto pré-existente.
  - Exceção: trabalho de **consolidação declarado como tal** (promover código
    duplicado à camada comum, unificar tokens/utilitários) pode tocar muitos
    arquivos de uma vez — desde que a fase faça só isso e cada página seja
    testada. Sem essa válvula, "cirúrgico" vira fábrica de duplicação.
- Antes de declarar pronto, rode/teste e mostre a evidência.
- Sem dado concreto, diga "não sei" ou marque [Verificar] — nunca apresente
  inferência como fato.

## Índice de aplicações

A documentação detalhada de cada área vive em `.claude/rules/` (carrega automaticamente ao
trabalhar nos arquivos correspondentes):

| Área | O que é | Detalhes |
|---|---|---|
| Camada comum + Hub | `comum.css`/`comum.js`, `index.html` e padrões dos painéis | `.claude/rules/site-frontend.md` |
| Base de Despesas | Execução da despesa da Prefeitura (crawler+painel+briefing) | `.claude/rules/despesas.md` |
| Painel de Endividamento | Dívida e limites da LRF via SICONFI/RGF (crawler+painel) | `.claude/rules/endividamento.md` |
| Monitor do Diário Oficial | Varredura diária do DOM → Google Sheets + e-mail | `.claude/rules/diario-oficial.md` |
| Briefing Ordem do Dia | Pauta da Câmara → briefing com Claude API por e-mail | `.claude/rules/ordem-do-dia.md` |
| Respostas do Executivo | Respostas a requerimentos → Drive + Sheets + painel | `.claude/rules/respostas-executivo.md` |
| Base de Proposituras | Índice dos projetos da Câmara (crawler+painel) | `.claude/rules/proposituras.md` |
| Base de Legislação | Índice da legislação municipal (crawler+painel) | `.claude/rules/legis.md` |
| Regimento Interno | Consulta rápida ao Regimento (OCR+parser+painel) | `.claude/rules/regimento.md` |
| GitHub Actions | Tabela de secrets e padrões dos workflows | `.claude/rules/github-actions.md` |

Módulos ainda sem documentação: `consulta/`, `indicadores/`, `memoria/`, `workers/`,
`digestor/`, `REQUERIMENTOS/`, `magda-annichino/`.

**Pró-Gestão RPPS** (produto, domínio distinto): vive em repo próprio —
`c:\Users\r_ros\OneDrive\Documentos\progestao-rpps` (github.com/derosisjr/progestao-rpps),
única fonte da verdade, com `CLAUDE.md` próprio. Qualquer trabalho no Pró-Gestão é feito lá.

## Análises do mandato

Análises do trabalho legislativo (pauta/ordem do dia, atos do DOM, gastos, requerimentos,
vetos) seguem `.claude/rules/perfil-politico.md`. Ao produzir análise legislativa sem ter
lido arquivos dessas áreas (ex.: pauta colada no chat), leia esse arquivo primeiro.
