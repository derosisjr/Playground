# Fontes e temas do Daily Digestor

> Este arquivo é lido pela routine a cada execução. **Edite aqui** para ajustar o radar
> (adicionar/remover fontes, mudar temas, mexer nos tetos) — **sem precisar tocar no `PROMPT.md`**.
> Prefira **RSS/WebSearch** (gratuitos) e só use scraping mais fundo (Firecrawl) quando necessário.

## Parâmetros gerais

- **Janela de coleta:** últimas 24h (segunda-feira: últimas 72h, para cobrir o fim de semana).
- **Teto por fonte:** no máximo **8 candidatos** por fonte por dia (controle de custo/plano).
- **Teto por categoria no e-mail final:** até **6 itens** por categoria (os mais relevantes).
- **Idiomas:** português e inglês. Resumir sempre em **português**.
- **Corte de relevância:** só entra no e-mail o que for 🔴 ou 🟡 (ver escala no `PROMPT.md`).
  Itens ⚪ (contexto) só aparecem se a categoria estiver vazia e houver espaço.

---

## 1. Santos na imprensa

Notícias sobre a cidade de Santos, a Câmara, a Prefeitura e a região da Baixada Santista.

- **Google News (RSS):** `https://news.google.com/rss/search?q=%22Santos%22+(prefeitura+OR+c%C3%A2mara+OR+vereador+OR+or%C3%A7amento)&hl=pt-BR&gl=BR&ceid=BR:pt-419`
- **Google News (RSS) — fiscal/gastos:** `https://news.google.com/rss/search?q=%22Prefeitura+de+Santos%22+(licita%C3%A7%C3%A3o+OR+contrato+OR+gasto+OR+d%C3%ADvida+OR+imposto)&hl=pt-BR&gl=BR&ceid=BR:pt-419`
- **A Tribuna (Santos):** https://www.atribuna.com.br/ — buscar por "Santos", "Câmara", "Prefeitura".
- **Diário do Litoral:** https://www.diariodolitoral.com.br/
- **G1 Santos e Região:** https://g1.globo.com/sp/santos-regiao/
- **Câmara Municipal de Santos (notícias/pauta):** https://www.camarasantos.sp.gov.br/

**Prioridade do mandato:** gasto público, licitações/contratos, tributos e taxas, dívida, obras,
transparência, decisões da Câmara, atos do Executivo que afetem o contribuinte.

---

## 2. Políticas públicas & govtech

Tendências, casos e boas práticas — Brasil e referências internacionais.

- **Nacionais / think tanks:** República.org, IMDS (Instituto Mobilidade e Desenvolvimento Social),
  FGV (EAESP/DAPP), Insper, Instituto Millenium, Instituto Liberal, CLP (Líderes Públicos).
- **Transparência/controle:** TCE-SP (notícias e jurisprudência), Portal da Transparência (novidades),
  Open Knowledge Brasil.
- **Internacionais (busca em inglês):** OECD (govtech, public finance), Bloomberg Cities / Bloomberg
  Philanthropies, Apolitical, GovTech (govtech.com), World Bank GovTech, Data-Smart City Solutions
  (Harvard Ash Center), Reinventing Government.

**Prioridade do mandato:** eficiência do gasto, redução de burocracia, digitalização de serviços,
transparência de dados, liberdade econômica, casos de contenção fiscal e resultados por real gasto.

---

## 3. Legislação aplicável (nacional e internacional)

Novas normas, projetos e decisões relevantes ao mandato municipal.

- **Nacional:** Câmara dos Deputados e Senado (novos PLs por tema fiscal/municipal), Planalto
  (leis/decretos sancionados), STF/STJ (decisões que afetem municípios), TCU (acórdãos-referência).
- **Buscas temáticas:** "responsabilidade fiscal município", "Lei 14.133 licitações município",
  "transparência dados abertos municípios", "reforma administrativa municipal".
- **Internacional (comparado, busca em inglês):** legislação municipal de transparência, orçamento
  participativo, open contracting, fiscal rules — como referência para proposituras.

**Prioridade do mandato:** o que possa virar propositura, emenda, requerimento ou argumento de
fiscalização em Santos. Sempre indicar a aplicabilidade prática ao município.

---

## 4. Da academia (papers)

Artigos científicos recentes em economia, administração pública, ciência política, gestão e govtech.

- **arXiv:** categorias `econ.GN` (economia geral), `cs.CY` (computers & society / govtech),
  `stat.AP`. API: `http://export.arxiv.org/api/query?search_query=...`
- **Semantic Scholar (API aberta):** `https://api.semanticscholar.org/graph/v1/paper/search?query=...`
  — temas: "public finance municipality", "government transparency", "public administration efficiency",
  "govtech", "fiscal rules local government".
- **SciELO (Brasil):** https://search.scielo.org/ — administração pública, gestão, economia do setor
  público.
- **SSRN:** economia pública, government/political science (via busca).
- Usar a skill **firecrawl-research-index** quando a busca simples não achar os papers certos.

**Prioridade do mandato:** evidência aplicável a políticas municipais, controle de gastos, eficiência,
transparência e govtech. Resumir o **achado prático** em 1 linha; linkar o original (não republicar).

---

## Destinatários do e-mail

- **Para:** rrosis@gmail.com
- **Assunto:** `Radar do Mandato — {DD/MM}`
- **Envio:** **auto-envio autorizado** (destinatário é o próprio vereador). Sem etapa de rascunho.
