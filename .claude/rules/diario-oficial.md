---
paths:
  - "diario-oficial/**"
---

# Monitor do Diário Oficial (`diario-oficial/`)

## Pipeline NOVO — rotina /schedule com IA (2026-07, em validação)

A classificação determinística (abaixo) ficava aquém da skill `dom-santos`; o caminho novo
usa a **cota da assinatura Max** (rotina Claude Code em nuvem via /schedule — sem API key):

```
dom_md.py (PDF→MD limpo) → skill dom-santos (MD→JSON) → publicar.py (JSON→Sheets topo + e-mail)
```

- **`dom_md.py`** baixa a edição (reusa `extrator.baixar_pdf`) e converte com **`pymupdf4llm`**
  (diagnóstico 2026-07-13: +30k chars e 194×170 âncoras vs heurística de coluna; capturou
  TERMOS DE COMPROMISSO que o `extrator.py` perdia). MD com front-matter + `## Página N — SECRETARIA`
  (índice via `extrator.parsear_indice`); limpa `U+FFFD` e masthead. Saída em arquivo temporário —
  **não versionar dados**.
- **`.claude/skills/dom-santos/SKILL.md`** (skill no repo, entra no clone da rotina): classifica os
  atos das categorias-alvo e avalia risco pelos gatilhos de `references/criterios-risco.md`,
  devolvendo JSON no contrato do publicador.
- **`publicar.py`**: dedup **pela planilha** (fonte da verdade — a rotina não persiste nada entre
  execuções; chave `Data DO|Categoria|Tipo de Ato|Nº|Órgão`), **insere no TOPO** (linha 2,
  🔴 > 🟡 > 🟢), grava `Status="Novo"` (coluna de trabalho da equipe, nunca sobrescrita) e envia o
  e-mail (reusa `monitor.enviar_email`) por último, só se houver ato novo.
- **Planilha no formato da skill** (14 colunas, `sheets.COLUNAS`): `Nº · Data DO · Categoria ·
  Tipo de Ato · Órgão/Secretaria · Objeto/Resumo · Valor (R$) · Partes Envolvidas · Base Legal ·
  Nível Atenção · Observações/Irregularidades · Ação Sugerida · Status · Página DO`.
- **Config da rotina** (fora do repo): env `GOOGLE_OAUTH_TOKEN`, `DOM_SHEET_ID`, `GMAIL_USER`,
  `GMAIL_APP_PASSWORD`, `DOM_BRIEFING_TO`; allowlist Custom + `smtp.gmail.com` (googleapis e HTTPS
  público já entram no default). Rotinas não leem secrets do Actions.
- Enquanto em validação, o caminho determinístico (workflow `diario-oficial.yml`) roda em paralelo
  numa planilha de teste; `classificador.py`/`risco.py` ficam como fallback.

```bash
python diario-oficial/dom_md.py --data 2026-06-12 --out /tmp/ed.md   # PDF→MD
python diario-oficial/publicar.py atos.json --dry-run                # conferir sem gravar
```

## Pipeline determinístico (legado, fallback)

Automatiza a varredura diária que os assessores faziam à mão no **Diário Oficial de Santos (DOM)**:
baixa o PDF da edição (`diariooficial.santos.sp.gov.br/edicoes/inicio/download/AAAA-MM-DD`), extrai e
**classifica deterministicamente (sem IA/tokens)** os atos das categorias-alvo — **Contratos e aditivos,
Licitações e dispensas, Convênios e fomento (inclui Terceiro Setor: termos de compromisso/PROMICULT e
**termos de cooperação**), Leis e decretos (inclui **Portarias normativas**), Orçamento (créditos
adicionais) e Fiscal/Tributário (baixa retroativa de inscrição/renúncia de receita)** — e **anexa os atos
novos numa planilha do Google Sheets** (aba única "Atos do DOM", coluna `Categoria` para filtrar). Pessoal
(nomeações/exonerações, **portarias `-P-DEGEPAT`**) fica para fase futura. Pipeline:
`extrator.py` → `classificador.py` → `risco.py` → dedup SQLite → `sheets.py`.
- **`extrator.py`** resolve o **layout multi-coluna** do DOM: detecta 1 vs 2 colunas pela cobertura de
  tinta na faixa central e separa no *gutter* (o `extract_text` ingênuo intercala as colunas); o **índice**
  do PDF mapeia secretaria→página, dando a **secretaria** de cada ato (unidade que falta na Base de Despesas).
- **`classificador.py`** detecta atos por âncora **no início da linha** — removendo antes prefixos de
  cabeçalho (`REPUBLICAÇÃO DO`, `RETIFICAÇÃO DE`, `AUTORIZAÇÃO DE`...) p/ não perder atos republicados —
  e exige **número** no cabeçalho (mata fragmentos de cláusula); leis/decretos/portarias filtrados pelo
  **ano** (portaria de pessoal descartada por `-P-DEGEPAT`/verbo `exonera/nomeia`). **Desfaz a hifenização
  inclusive em MAIÚSCULAS** (`DIS-PENSA`, `HOMOLO-GOU`, `IMPORTÂN-CIA`) e **remove cabeçalho/rodapé de
  página** ("7 Diário Oficial de Santos", masthead) do fluxo — sem isso âncoras/ementas quebravam. O **nº
  do ato** cobre `Nº:`/`N.º`/hífen (`012/2026`, `3524-2026`) e resgata pela **modalidade** no corpo o nº de
  avisos de edital sem nº no cabeçalho (a "Lei Complementar nº 123/2006" citada não é confundida). **Aviso
  de abertura de edital** tem tipo próprio ("Aviso de edital"). **Resultados de licitação** (COMUNICADO com
  verbo `HOMOLOGOU/REVOGOU/DEFERIU/INDEFERIU...`) viram Homologação/…/Deferimento de recurso; na variante
  PRODESAN o nº está no "EDITAL" e o objeto/valor no "COMUNICADO" seguinte (fusão dos dois blocos). Atos
  **sem cabeçalho próprio** (contratação direta **ou ratificação de dispensa** em despacho; **baixa
  retroativa de inscrição** — só anos anteriores = renúncia) são captados por `_atos_por_frase`. Normas
  (Lei/Decreto/Portaria) usam a **ementa em CAIXA-ALTA** (após a linha de data, até o preâmbulo) como
  objeto. **Secretaria**: `UNIDADE:` → **signatário** ("Secretário [Municipal] de X") → **cabeçalho de
  órgão/entidade detectado no meio da página** (`_refinar_secretarias`: COHAB/CET/CAPEP/IPREV/PRODESAN e
  "SECRETARIA DE X"+"ATOS D…", corrige o índice grosso de 1 seção/página) → índice. Crédito aberto por
  Decreto/Lei/Portaria não é duplicado. Dedup por (categoria, número, secretaria). Captura objeto, valor,
  favorecido, processo, `trecho` (texto do ato p/ auditoria) e os campos de risco (`termo`, `valor_num`,
  `retroativo`). `cabecalhos_nao_reconhecidos()` gera o **radar** (cabeçalhos com nº que não casaram âncora
  nem ficaram dentro de bloco capturado, sem intimações/pessoal) — insumo de melhoria contínua no e-mail.
- **`risco.py`** aplica os **gatilhos da skill `dom-santos`** (versionada em `diario-oficial/references/`)
  de forma **determinística, sem IA e sem a Base de Despesas** — só dados do ato + histórico do `diario.sqlite`:
  aditivo ≥3º termo / 2º termo, efeitos retroativos, dispensa/inexig. acima do limite (art. 75), crédito
  extraordinário, OSC repetida/valores idênticos, valor elevado. Gera colunas **Risco** (🔴🟡🟢) e
  **Motivo do risco** (com base legal) — os 🔴 são insumo para a skill redigir requerimentos/representações.
  Limiares legais ficam em constantes no topo de `risco.py` (**verificar anualmente**).
- **`sheets.py`** reusa o OAuth/Sheets do `respostas-executivo` (mesmo `GOOGLE_OAUTH_TOKEN`, escopo Sheets);
  planilha dedicada em **`DOM_SHEET_ID`**. Última coluna **`Trecho`** (~200 chars do ato como saiu no DOM,
  p/ a equipe conferir cada linha sem abrir o PDF); `garantir_aba` **atualiza o cabeçalho** se defasado
  (acrescenta `Trecho` sem mexer nos dados). Formatação por script (cabeçalho navy/dourado, filtro, zebra,
  cores por categoria e risco).
- **E-mail aos assessores:** `monitor.py --email` envia, ao fim do run, um briefing HTML com os atos novos
  (🔴/🟡 no topo, com o motivo/base legal e link p/ a planilha) via Gmail SMTP — só quando há atos novos.
  Traz também o **radar de cabeçalhos não-reconhecidos** (melhoria contínua: a equipe aponta, a âncora
  entra). Destinatários: `DOM_BRIEFING_TO` → `DESPESAS_BRIEFING_TO` → `RESPOSTAS_EMAIL_TO` → `GMAIL_TO`.
- **`.sqlite` no `.gitignore`**, persiste via cache do Actions; `.github/workflows/diario-oficial.yml`
  roda **dias úteis (seg–sex) ~00:17 BRT** (cron `17 3 * * 1-5`, minuto quebrado p/ fugir do
  congestionamento do topo da hora; o DOM sai no fim da noite anterior e não publica sáb/dom) com
  `--dias 3 --email`, e via `workflow_dispatch` (`--data` envia e-mail; `--desde` é backfill sem e-mail). **Só código e referências são versionados** — a saída é o Sheets, não há commit de
  dados. Geração de peças (requerimentos) segue na **skill `dom-santos` no Claude web**; cruzar
  favorecido↔Despesas e nomeações/exonerações ficam p/ fases futuras.

## Comandos úteis

```bash
# Diário Oficial — testar 1 edição sem escrever (imprime atos + risco)
python diario-oficial/monitor.py --data 2026-06-12 --dry-run

# Diário Oficial — depurar a extração de uma página (layout-aware)
python diario-oficial/extrator.py --data 2026-06-12 --pagina 8

# Diário Oficial — gravar no Sheets (precisa DOM_SHEET_ID no ambiente)
DOM_SHEET_ID=... python diario-oficial/monitor.py --data 2026-06-13
DOM_SHEET_ID=... python diario-oficial/monitor.py --desde 2026-06-09 --ate 2026-06-12  # intervalo
```
