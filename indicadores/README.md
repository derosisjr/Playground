# Custo por Resultado (`indicadores/` + `indicadores.html`)

Painel público que cruza o **gasto liquidado por função** (Tesouro/SICONFI, DCA
Anexo I-E) com **indicadores de resultado** (IBGE: mortalidade infantil; INEP:
IDEB rede municipal), per capita, de Santos e 5 municípios paulistas de porte
similar (SJC, Ribeirão Preto, Sorocaba, Mauá, Diadema). Série 2019+.

Pipeline: `fontes.py` (registro de APIs verificadas) → `crawler.py` (→
`indicadores.sqlite`, gitignored, idempotente) → `export.py` (→
`indicadores-index.json` na raiz, versionado) → `indicadores.html` +
`indicadores-app.js` (abas Saúde/Educação; gráfico-assinatura "tesoura" com as
séries em base 100 e a área entre elas sombreada; tabela de comparáveis com
posição de Santos; CSV).

```bash
python indicadores/crawler.py --fonte dca --ano 2023 --dry-run   # amostra
python indicadores/crawler.py                                    # carga completa
python indicadores/export.py                                     # gera o índice
```

CI: `.github/workflows/indicadores.yml` — mensal (dia 3), cache do sqlite,
guarda anti-truncamento (não publica índice incompleto). Fontes toleram falha
individual (IBGE às vezes é lento a partir dos runners do GitHub; a base
mantém a carga anterior).

Decisões: valores **correntes** (sem deflator; anotado no rodapé); indicadores
mostrados no **último ano divulgado**, nunca interpolados; a série de gasto usa
**só o SICONFI** (metodologia idêntica entre municípios — a Base de Despesas
local cobre outra visão, caixa/mandato). Fase 2 documentada em `fontes.py`:
DATASUS/TABNET (internações sensíveis) e e-Gestor (cobertura AB), que exigem
POST em formulário.
