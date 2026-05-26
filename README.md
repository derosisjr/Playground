# Radar de Pauta do Gabinete

MVP estatico para transformar a pauta de uma sessao legislativa em briefing politico rapido para gabinete parlamentar.

## O que ja faz

- Recebe pauta colada em texto
- Importa arquivo `.txt`
- Identifica projetos, requerimentos, indicacoes e mocoes
- Classifica urgencia e tipo de impacto
- Sinaliza itens de fiscalizacao, territorio e saude
- Gera visao executiva e falas base para plenario

## Como usar

1. Abra `index.html` no navegador.
2. Clique em `Carregar pauta de exemplo` ou cole uma pauta real.
3. Ajuste `Nome do vereador` e `Prioridades do mandato`.
4. Clique em `Gerar briefing`.

## Estrutura

- `index.html`: interface principal
- `styles.css`: identidade visual
- `app.js`: parser, classificacao e briefing

## Proximos passos recomendados

- Conectar upload de PDF com extracao de texto
- Integrar com OpenAI API para resumo e fala mais sofisticados
- Salvar historico de sessoes e posicionamentos
- Exportar briefing em PDF ou WhatsApp
- Adicionar painel de votacoes e acompanhamento pos-sessao
