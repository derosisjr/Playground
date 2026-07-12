# Daily Digestor — radar externo de inteligência do mandato

Radar diário que, toda manhã, entrega ao gabinete um **digest curado** do que acontece **fora** e
importa ao mandato: imprensa sobre Santos, políticas públicas & govtech, legislação nacional/
internacional aplicável e artigos científicos de interesse (economia, administração pública, política,
gestão, govtech).

Diferente dos monitores internos (DOM, Despesas, Respostas), que vigiam fontes fixas do município e
rodam determinísticos no GitHub Actions, o Digestor **varre o mundo aberto** e **cura por relevância**
no tom do perfil político (defesa do contribuinte, Estado enxuto, govtech, ceticismo com viés de
esquerda).

## Como roda — sem custo de API medido, sem PC ligado

O Digestor **não é** um script Python nem um workflow do Actions. É uma **routine agendada do Claude
Code** (`/schedule`) que executa **na nuvem, usando o plano da assinatura** — portanto **não** consome
`ANTHROPIC_API_KEY` (token de API medido) e **não** exige o computador ligado.

O agente é o cérebro: pesquisa (WebSearch/WebFetch/Firecrawl + APIs de papers), deduplica, cura, redige
e envia o e-mail. Os **artefatos duráveis** ficam versionados aqui no repo.

## Arquivos

| Arquivo | O quê |
|---|---|
| `PROMPT.md` | **Comportamento canônico** da routine (o pipeline completo). Edite para mudar o funcionamento. |
| `fontes.md` | **Fontes, temas, tetos e destinatários.** Edite para ajustar o radar (o dia a dia mora aqui). |
| `vistos.json` | Estado de **dedup** (hashes de itens já enviados). Commitado a cada run; podado a 30 dias. |
| `edicoes/AAAA-MM-DD.html` | Arquivo de cada edição (base da futura página pública). |

## Ajustar o radar

- **Adicionar/remover fonte ou tema, mudar tetos, trocar destinatário:** edite `fontes.md`.
- **Mudar o formato do e-mail, as regras de relevância ou o pipeline:** edite `PROMPT.md`.
- Não é preciso mexer em código — a routine relê estes arquivos a cada execução.

## Registrar / operar a routine

Use a skill **`/schedule`** do Claude Code:

- **Criar:** `/schedule` apontando para `digestor/PROMPT.md`, cron **dias úteis ~06h30 BRT**
  (segunda usa janela de 72h para cobrir o fim de semana).
- **Rodar agora (teste):** disparo manual da routine (run-now) com instrução **"seco / dry-run"**
  (imprime candidatos e resumo, não envia, não commita).
- **Pausar/editar/listar:** pelo próprio `/schedule`.

### Pré-requisitos de setup
- **Gmail (MCP)** conectado à conta (envio/rascunho do digest). Destinatário em `fontes.md`.
- **Escrita no repo** pela routine (para commitar `vistos.json`/`edicoes`). Sem push, o estado pode ir
  para um Gist, ou a routine opera na janela 24–72h sem estado (aceitando repetição de borda).
- **Firecrawl** é opcional — onde RSS/WebSearch bastarem, dispensa `FIRECRAWL_API_KEY`.

## Rollout recomendado
1. Rodar **seco** 1–2 vezes e conferir candidatos + resumo executivo.
2. Ligar a routine gerando **rascunho no Gmail** por 3–5 dias (revisão humana).
3. Só então autorizar **auto-envio**.

## Salvaguardas
- **Fair use:** links + trechos curtos; nunca texto integral. Papers: metadados + abstract abertos.
- **Grounding:** o resumo afirma só o que está no texto coletado (reduz alucinação).
- **Fato × opinião:** resumo factual e atribuído à fonte; "por que importa" é a leitura do gabinete,
  rotulada à parte.

## Fase 2 (futuro)
Ampliar fontes internacionais via Firecrawl; **página interna navegável** (`digest.html` + índice dos
`edicoes/*`, card no hub) com histórico pesquisável.
