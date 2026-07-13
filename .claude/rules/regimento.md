---
paths:
  - "regimento/**"
  - "regimento.html"
  - "regimento-app.js"
  - "regimento-index.json"
  - "regimento-notas.json"
---

# Base do Regimento Interno (`regimento/` + `regimento.html`)

Consulta **relâmpago** ao Regimento Interno da Câmara de Santos (Resolução nº 16/2019) para uso
**em sessão** — acha o artigo por número ou palavra-chave e, onde houver **jurisprudência/doutrina**
("interpretação conforme"), abre um **menu expansível** ao clicar no artigo. **5º cartão do hub.**
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
🟡 Doutrina; **atalhos** `/` (foca), `Esc` (limpa), `Enter` (abre o 1º). **Sem CI** — o Regimento
muda raramente; OCR+parser rodam local sob demanda. O **PDF-fonte fica fora do repo** (só
`regimento-fonte.md`, os dois JSON e o código são versionados). Fases futuras: precedente interno
(Mesa/questões de ordem) e nota tática (o `tipo` já é extensível); navegação por árvore; edição de
notas no navegador.

## Comandos úteis

```bash
# Regimento Interno — OCR do PDF escaneado -> markdown editavel (so quando trocar o PDF-fonte)
python regimento/ocr_para_md.py            # gera regimento/regimento-fonte.md

# Regimento Interno — parsear o .md -> regimento-index.json
python regimento/parser.py --dry-run       # so contagens + amostra
python regimento/parser.py                 # grava regimento-index.json
```
