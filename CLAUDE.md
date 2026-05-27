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

## Arquitetura da Automação (ordem-do-dia)

- **Fonte de dados:** `https://administrativo.camarasantos.sp.gov.br/dispositivo/ideCustom/legislativo/ordem_dia_eletronica/publico/`
- **API de sessões:** `listagem.php?codigo=SESSION_ID` (HTML com `.documento` divs)
- **IA:** Claude Sonnet via `@anthropic-ai/sdk` (Python SDK)
- **Entrega:** Gmail SMTP com e-mail HTML estilizado
- **Agendamento:** GitHub Actions (`.github/workflows/ordem-do-dia.yml`), cron `0 2 * * 2,4`

## Secrets do GitHub Actions

| Secret | Descrição |
|---|---|
| `ANTHROPIC_API_KEY` | API do Claude |
| `GMAIL_USER` | Conta Gmail remetente |
| `GMAIL_APP_PASSWORD` | App Password de 16 dígitos |
| `GMAIL_TO` | Destinatário(s) do briefing |

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
```
## PERFIL POLÍTICO DO MANDATO

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
