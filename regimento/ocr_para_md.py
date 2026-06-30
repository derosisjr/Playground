# -*- coding: utf-8 -*-
"""OCR do Regimento Interno (PDF escaneado, impressao do leis.org) -> markdown editavel.

O PDF e um scan; nao ha texto extraivel. Renderizamos cada pagina (PyMuPDF, sem
poppler) e passamos no Tesseract (idioma por). Em seguida aplicamos limpezas
DETERMINISTICAS dos erros sistematicos desse scan especifico:
  - remove o cabecalho de impressao "DD/MM/AAAA, HH:MM Regimento Interno - Leis.org"
  - remove rodapes de URL/numeracao de pagina do leis.org
  - restaura o simbolo de paragrafo: o Tesseract le "§" como "8" (ex.: "8 1o")
  - junta palavras hifenizadas na quebra de linha
O resultado vai para regimento/regimento-fonte.md, que e a camada de refino:
editavel a mao antes de rodar o parser.
"""
import os, re, sys
import fitz
import pytesseract
from PIL import Image

TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
pytesseract.pytesseract.tesseract_cmd = TESS
SRC = os.path.expanduser(r"~/Downloads/Regimento Interno de Santos - SP.pdf")
DST = os.path.join(os.path.dirname(__file__), "regimento-fonte.md")
DPI = 350

RE_HEADER = re.compile(r"^\s*\d{2}/\d{2}/\d{4},?\s*\d{1,2}:\d{2}.*Leis\.org.*$", re.I)
RE_URL    = re.compile(r"^\s*https?://\S+.*$", re.I)             # URL leis.org + "12/71"
RE_PAGNUM = re.compile(r"^\s*\d{1,3}\s*/\s*\d{1,3}\s*$")          # "3/71"

def limpar(txt: str) -> str:
    linhas = []
    for ln in txt.splitlines():
        if RE_HEADER.match(ln) or RE_URL.match(ln) or RE_PAGNUM.match(ln):
            continue
        linhas.append(ln.rstrip())
    s = "\n".join(linhas)
    # "Art." lido como "Ar."/"Am."/"An." e "Art.5" sem espaco -> "Art. N"
    s = re.sub(r"(?m)^(?:Art|Ar|Am|An)\.?\s*(\d+)", r"Art. \1", s)
    # OCR dobra o ultimo digito do numero do artigo (32->322, 52->522)
    for errado, certo in {"322": "32", "522": "52"}.items():
        s = re.sub(rf"(?m)^Art\. {errado}\b", f"Art. {certo}", s)
    # "§" lido como "8" no inicio de linha: "8 1o" (ordinal) e "8 10" (numero seco)
    s = re.sub(r"(?m)^\s*8\s+(\d{1,3})(\s*[ºo°\.]|\s)", r"§ \1\2", s)
    s = re.sub(r"(?m)^\s*§\s+", "§ ", s)
    # de-hifenizacao na quebra de linha: "traba-\nlho" -> "trabalho"
    s = re.sub(r"(\w)-\n(\w)", r"\1\2", s)
    # comprime linhas em branco multiplas
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def main():
    doc = fitz.open(SRC)
    n = len(doc)
    partes = []
    for i in range(n):
        pix = doc[i].get_pixmap(dpi=DPI)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        txt = pytesseract.image_to_string(img, lang="por")
        partes.append(limpar(txt))
        sys.stderr.write(f"  pagina {i+1}/{n}\n"); sys.stderr.flush()
    corpo = "\n\n".join(p for p in partes if p)
    corpo = re.sub(r"\n{3,}", "\n\n", corpo)
    with open(DST, "w", encoding="utf-8") as f:
        f.write("<!-- Gerado por regimento/ocr_para_md.py a partir do PDF escaneado.\n")
        f.write("     CAMADA DE REFINO: corrija residuos de OCR aqui; o parser le este arquivo. -->\n\n")
        f.write("# Regimento Interno da Camara Municipal de Santos\n\n")
        f.write(corpo + "\n")
    print(f"OK: {DST} ({len(corpo)} chars, {n} paginas)")

if __name__ == "__main__":
    main()
