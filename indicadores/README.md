# Custo por Resultado (`indicadores/` + `indicadores.html`)

Painel público com 3 temas para Santos e 5 municípios paulistas de porte similar
(SJC, Ribeirão Preto, Sorocaba, Mauá, Diadema), série 2019+:

- **Saúde / Educação** (modo *tesoura*): **gasto liquidado por função**
  (Tesouro/SICONFI, DCA Anexo I-E) × **indicadores de resultado** — mortalidade
  infantil (IBGE/Registro Civil), IDEB (INEP), e da rede municipal matrículas em
  creche e alunos por docente (IBGE/Censo Escolar). Onde a API do IBGE fornece,
  o gráfico mostra a **tendência da média do Estado de SP** (tracejada) e a tabela
  traz a coluna **Média SP** (não há IDEB estadual nessa base).
- **Fiscal** (modo *série*): receita tributária própria/hab, autonomia fiscal
  (% da receita corrente que é arrecadação própria), investimento/hab e despesa
  com pessoal/hab — todos do SICONFI (DCA anexos I-C receita e I-D despesa por
  categoria). Uma linha por município, Santos em destaque.

Pipeline: `fontes.py` (registro de APIs verificadas) → `crawler.py` (→
`indicadores.sqlite`, gitignored, idempotente) → `export.py` (→
`indicadores-index.json` na raiz, versionado) → `indicadores.html` +
`indicadores-app.js` (abas Saúde/Educação; gráfico-assinatura "tesoura" com as
séries em base 100 e a área entre elas sombreada; tabela de comparáveis com
posição de Santos; CSV).

```bash
python indicadores/crawler.py --fonte dca --ano 2023 --dry-run      # amostra (gasto/função)
python indicadores/crawler.py --fonte fiscal --ano 2023 --dry-run   # amostra (receita/despesa)
python indicadores/crawler.py                                       # carga completa (dca+fiscal+ibge+pop)
python indicadores/export.py                                        # gera o índice (3 temas)
```

CI: `.github/workflows/indicadores.yml` — mensal (dia 3), cache do sqlite,
guarda anti-truncamento (não publica índice incompleto). Fontes toleram falha
individual (IBGE às vezes é lento a partir dos runners do GitHub; a base
mantém a carga anterior).

Decisões: valores **correntes** (sem deflator; anotado no rodapé); indicadores
mostrados no **último ano divulgado**, nunca interpolados; a série de gasto usa
**só o SICONFI** (metodologia idêntica entre municípios — a Base de Despesas
local cobre outra visão, caixa/mandato). Referência **média SP** só nos
indicadores IBGE que a expõem (mortalidade infantil, creche, alunos/docente; o
IDEB via IBGE não tem série estadual). Fora do escopo por decisão do gabinete:
mínimos constitucionais (15%/25%), municípios adicionais, tema Economia. Fase
futura documentada em `fontes.py`: DATASUS/TABNET (internações sensíveis),
e-Gestor (cobertura AB) e segurança (SSP-SP), que exigem POST em formulário /
agregação registro a registro.
