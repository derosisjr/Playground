---
paths:
  - "regimento/**"
  - "regimento.html"
  - "regimento.css"
  - "regimento-app.js"
  - "regimento-index.json"
  - "regimento-notas.json"
  - "lei-organica.html"
  - "lei-organica-index.json"
  - "ordem-do-dia/references/lei-organica-santos.md"
---

# Base do Regimento Interno (`regimento/` + `regimento.html`)

Consulta **relâmpago** ao Regimento Interno da Câmara de Santos (Resolução nº 16/2019) para uso
**em sessão** — acha o artigo por número ou palavra-chave e, onde houver **jurisprudência/doutrina**
("interpretação conforme"), abre um **menu expansível** ao clicar no artigo. **7º cartão do hub.**
A fonte oficial só existe como **PDF escaneado** (impressão do leis.org; sem texto extraível) e os
sites digitais (leis.org, leismunicipais) estão atrás de Cloudflare — então o texto vem de **OCR**:
`regimento/ocr_para_md.py` renderiza as 71 páginas com **PyMuPDF** (sem poppler) + **Tesseract**
(`lang=por`, binário em `C:\Program Files\Tesseract-OCR`) e aplica limpezas **determinísticas** dos
erros sistemáticos desse scan (remove cabeçalho/rodapé "…Leis.org"; `§` lido como `8`; `Art.` lido
como `Ar.`/`Am.`; OCR dobra o último dígito do nº do artigo: `322`→`32`, `522`→`52`), gravando
**`regimento/regimento-fonte.md`** — a **camada de refino editável** (corrija resíduos de OCR aqui
antes de reparsear). `regimento/parser.py` lê esse `.md` e gera **`regimento-index.json`** (raiz,
versionado): array de artigos com breadcrumb (`titulo_sup`/`capitulo`/`secao`) e **blocos ordenados**
(caput/§/inciso/alínea); incisos são **renumerados sequencialmente** (I, II, III…) para corrigir os
romanos do OCR; suporta artigos `-A` (23-A, 79-A…). **191 artigos (1–187, sem lacunas; 32 e 52
recuperados do erro de dígito)**. As **notas** ("interpretação conforme") ficam num arquivo
**separado e curado à mão**, `regimento-notas.json` (raiz, versionado): dicionário `id do artigo →
[{tipo: jurisprudencia|doutrina, fonte, texto, url}]` — separado de propósito para que **reparsear o
Regimento nunca apague as notas** (o painel mescla por `id` no cliente; degrada se faltarem).
`regimento.html`+`regimento-app.js` é o painel (vanilla, sem build): busca com autofocus, sem acento,
**prioriza nº de artigo** (`art 79`, `artigo 23-A`); card expansível com badges 🔵 Jurisprudência /
🟡 Doutrina; **atalhos** `/` (foca), `Esc` (limpa), `Enter` (abre o 1º). **Sem CI de dados** — o
Regimento muda raramente; OCR+parser rodam local sob demanda (os testes do parser rodam no
`testes.yml`, ver abaixo). O **PDF-fonte fica fora do repo** (só `regimento-fonte.md`, os dois JSON
e o código são versionados). Fases futuras: precedente interno (Mesa/questões de ordem) e nota
tática (o `tipo` já é extensível); navegação por árvore; edição de notas no navegador.

**Para a sessão (2026-10).** Cada artigo tem **"Copiar link"** (`#art-N`) e **"Copiar citação"**
("Regimento Interno da Câmara Municipal de Santos (Resolução nº 16/2019), Art. N: «caput +
parágrafos»") via `Comum.copiar`, em cor apagada (opacidade derrubava o contraste). O texto do
topo só fala em "interpretação conforme" quando `regimento-notas.json` tem alguma nota (hoje, 0).

**Leitor compartilhado (2026-10, M3).** `regimento-app.js` (v5) abre as duas leis: a página
escolhe pelo `data-doc` do `<main>` (sem atributo = Regimento; `lom` = Lei Orgânica) e o objeto
`DOCS` no topo do app guarda índice, notas curadas, prefixo da citação e o que é só da LOM
(`dispositivos`). O `<style>` do `regimento.html` virou **`regimento.css`** (movido sem mudança;
as regras da LOM ficam no fim) — o Regimento renderiza idêntico (capturas antes/depois iguais
pixel a pixel, fora o link novo). A linha de dicas sob a busca liga as duas páginas
("Lei Orgânica →" / "Regimento Interno →"). `#art-N` também é tratado no `hashchange`: a busca
Ctrl+K abre `./regimento.html#art-79` e, na própria página, isso só trocava o hash (o artigo podia
nem estar na lista).

# Lei Orgânica do Município (`regimento/lei_organica.py` + `lei-organica.html`) — 2026-10, M3

**8º cartão do hub** (logo depois do Regimento; tag "Câmara · Lei Orgânica"). Fonte **única**:
`ordem-do-dia/references/lei-organica-santos.md` — camada de texto do PDF oficial (Legis da
Prefeitura, doc. 9596, `https://egov.santos.sp.gov.br/legis/documents/9596`, baixado em
2026-08-10; **sem OCR**), a mesma que a skill do briefing da Ordem do Dia lê. Mexeu no `.md`?
Regere o índice (o teste `test_indice_publicado_em_dia` falha se o publicado não bater).

**Parser.** `regimento/parser.py` virou `parse(texto, opcoes)`; `Opcoes` (dataclass) lista o que
muda de uma lei para outra e **o padrão (`REGIMENTO`) é o Regimento byte a byte** — teste dourado
`regimento/tests/test_regimento_dourado.py` regera o índice de `regimento-fonte.md` e compara com o
`regimento-index.json` publicado (objeto e formato em disco). As opções da LOM
(`lei_organica.OPCOES`):
- **rótulos com a pontuação oficial**: "Art. 1º", "Art. 10.", "Art. 56-A.", "§ 1º", "§ 10.",
  "§ 2º-A.", "Parágrafo único.", "XVIII –", "a)" — e **sem renumerar incisos** (não é OCR;
  renumerar esconderia inciso fora de ordem). O painel tira a pontuação para citar;
- aceita "Artigo 59.", "Art. 56 O…" (sem ponto), "Art. 21.Compete", "§2º-B.", "§ 4º-A O…",
  "§ 1º - As…", "Parágrafo Único.O…", rótulo sozinho na linha ("IX –", "a)", "Art. 167.");
- **descarta** o front-matter YAML, os nºs de página (linhas só com 1–89) e tudo a partir de
  "Sala das Sessões" (assinaturas); palavra partida no hífen junta sem espaço ("reunir-" + "se-ão");
- **notas de emenda**: no PDF cada uma vem depois de um marcador U+F0B7 (o "" da fonte Symbol)
  — 151 marcadores, 151 notas. A nota sai do texto e vai para **`notas`** do artigo:
  `[{"bloco": i, "texto": "Inciso com redação dada pela Emenda…"}]`, `i` = índice do bloco que
  ela **segue** no PDF (posição, não interpretação: "Artigo com redação…" depois do último inciso
  fica presa a esse inciso). Nota logo depois de um cabeçalho ("Título com denominação alterada…",
  "Seção alterada…") fica com o 1º artigo da seção e `bloco: null`. `conferir()` aborta a gravação
  se alguma nota não tiver cara de nota (`RE_NOTA`) ou se algum texto de artigo tiver;
- nome do Título/Capítulo/Seção vem nas linhas de baixo → "TÍTULO I — DISPOSIÇÕES PRELIMINARES";
  "DISPOSIÇÕES GERAIS"/"PRINCÍPIOS GERAIS" depois do nome de um capítulo viram seção sem número;
- **Disposições Transitórias** (Título cujo nome tem "TRANSITÓRIA"): numeração recomeça em 1 →
  `"adt": true`, id **`adt-art-N`** (âncora `#adt-art-N`) e o termo "adt" no `texto_busca`.

`lei-organica-index.json` (raiz, minificado por `comum/escrita.py` `gravar_json`, ~0,5 MB /
93 KB gzip): **mesmo esquema do `regimento-index.json` + `notas` e `adt` em todo artigo**; as notas
também entram no `texto_busca` ("emenda 89" acha os artigos que ela alterou). **Contagens (fonte de
2026-08-10): 256 artigos no corpo (1–253 + 56-A, 58-A, 63-A; 83 e 244 "REVOGADO."), 21 nas
Disposições Transitórias, 151 notas, 68 artigos do corpo com nota**; 403 incisos, 255
parágrafos, 88 alíneas.

**Página `lei-organica.html`** (`<main data-doc="lom">`, mesmo `regimento.css`/`regimento-app.js`):
hero "Câmara · Lei Orgânica" / "Lei Orgânica do Município" com o link do Legis; busca igual à do
Regimento, mais:
- **dispositivo na busca**: "58 XVIII", "art. 58, inciso XVIII", "73 § 4º-A", "4 parágrafo único",
  "58 XII a" marcam o bloco (`.bloco.alvo`, com as alíneas/incisos abaixo dele), rolam até ele no
  Enter ou com `?q=` na URL, e o artigo ganha o botão **"Copiar citação: art. 58, XVIII"**;
- **citação**: "Lei Orgânica do Município de Santos, art. 58, XVIII: «prestar, à Câmara…»" (artigo
  inteiro: "…, art. 58: «Compete… I – … XXVIII – …; Parágrafo único. …»"; alínea `art. 58, XII,
  “a”`; ADT "…, Disposições Transitórias, art. 17, I: «…»"). Só texto da lei — nunca as notas.
  O Regimento continua com "Art. N" maiúsculo (comportamento publicado; alinhar é decisão à parte);
- **notas de emenda** como notas de rodapé: número discreto (`sup.nota-ref`) no ponto do PDF e a
  lista "Notas de alteração" no pé do artigo, em cor apagada;
- "adt 5" / "transitórias 5" restringe o número às Disposições Transitórias; `#adt-art-N` abre lá.
- Requerimentos: o "(art. 58, XVIII)" do rodapé é link para `lei-organica.html#art-58`.

[Verificar] — achados no texto do PDF (mantidos como estão, é o texto oficial extraído):
"TÍTULO VIII" aparece duas vezes (Disposições Gerais e Disposições Transitórias; não há
"TÍTULO VII"); art. 185 tem um "VI –" depois do § 3º (sem incisos I–V); art. 136 está no texto mas
a nota diz "foi revogado pela Emenda nº 28/1995"; erros de digitação do próprio PDF ("comceder",
"emviar", "comtrato", "Dário Oficial", "posposta orçamentária", "combate à população", "Legislação
que terá início" no art. 13); notas com data trocada (Emenda nº 57/2010 "DOM de 11/04/1996"; "18 de
outubro de 193"; "DOM de 20/102004") e "Parágrafo acrescido pela Lei Orgânica nº 85" (é Emenda).
Marcas "(NR)"/"(AC)" ficam no texto (estão no PDF). Preâmbulo e assinaturas ficam de fora.

**Testes** (`regimento/tests/`, passo próprio no `testes.yml`, que agora também dispara com
`regimento/**`, os dois índices e o `.md` da LOM): dourado do Regimento; contagens da LOM, ids
únicos, art. 58 XVIII com "quinze dias", notas presas e nunca no texto, rótulos dos casos do PDF,
seção sem número, índice publicado em dia com a fonte, opções num texto sintético.

## Comandos úteis

```bash
# Regimento Interno — OCR do PDF escaneado -> markdown editavel (so quando trocar o PDF-fonte)
python regimento/ocr_para_md.py            # gera regimento/regimento-fonte.md

# Regimento Interno — parsear o .md -> regimento-index.json
python regimento/parser.py --dry-run       # so contagens + amostra
python regimento/parser.py                 # grava regimento-index.json

# Lei Orgânica — .md da Ordem do Dia -> lei-organica-index.json (aborta se conferir() achar problema)
python regimento/lei_organica.py --dry-run # contagens + art. 58 XVIII e suas notas
python regimento/lei_organica.py           # grava lei-organica-index.json

python -m pytest regimento/tests -q        # dourado do Regimento + Lei Orgânica
```
