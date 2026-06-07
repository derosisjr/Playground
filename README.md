# Ferramentas do Gabinete — Câmara de Santos

Conjunto de painéis de transparência e fiscalização do gabinete (Rui de Rosis Jr., PL). A página
inicial (`index.html`) é um **hub** que reúne os 3 bancos pesquisáveis — **Despesas**, **Proposituras**
e **Legislação**. Veja o `CLAUDE.md` para a visão completa das aplicações e automações.

Publicado em: https://derosisjr.github.io/Playground/

---

## Radar de Pauta (`pauta.html`)

MVP estatico para transformar a pauta de uma sessao legislativa em briefing politico rapido para gabinete parlamentar.

## O que ja faz

- Recebe pauta colada em texto
- Importa arquivo `.txt`
- Identifica projetos, requerimentos, indicacoes e mocoes
- Classifica urgencia e tipo de impacto
- Sinaliza itens de fiscalizacao, territorio e saude
- Gera visao executiva e falas base para plenario

## Como usar

1. Abra `pauta.html` no navegador (ou clique no hub em `index.html`).
2. Clique em `Carregar pauta de exemplo` ou cole uma pauta real.
3. Ajuste `Nome do vereador` e `Prioridades do mandato`.
4. Clique em `Gerar briefing`.

## Estrutura

- `pauta.html`: interface principal
- `styles.css`: identidade visual
- `app.js`: parser, classificacao e briefing

## Proximos passos recomendados

- Conectar upload de PDF com extracao de texto
- Integrar com OpenAI API para resumo e fala mais sofisticados
- Salvar historico de sessoes e posicionamentos
- Exportar briefing em PDF ou WhatsApp
- Adicionar painel de votacoes e acompanhamento pos-sessao
