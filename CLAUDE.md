# Playground — Ferramentas Parlamentares · Câmara de Santos

## Contexto do Projeto

Ferramentas de suporte ao gabinete de um vereador da Câmara Municipal de Santos (SP).
Stack: HTML/CSS/JS vanilla (frontend) + Python (automações).

## Aplicações

### Radar de Pauta (`index.html` + `app.js`)
Transforma texto de pauta legislativa em briefing político com classificação por prioridade,
tags temáticas e sugestão de discurso para plenário.

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
| `GMAIL_TO` | Destinatário(s) do briefing (ordem-do-dia) |
| `GOOGLE_OAUTH_TOKEN` | JSON do token OAuth Drive+Sheets, gerado por `setup_oauth.py` (respostas-executivo) |
| `SHEET_ID` | ID da planilha de controle (respostas-executivo) |
| `DRIVE_FOLDER_ID` | ID da pasta-raiz no Drive (respostas-executivo) |

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