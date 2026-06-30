# -*- coding: utf-8 -*-
"""Parser do Regimento Interno: regimento/regimento-fonte.md -> regimento-index.json.

Le o markdown refinado (camada editavel produzida por ocr_para_md.py) e quebra na
hierarquia TITULO -> CAPITULO -> Secao -> Artigo, preservando dentro do artigo os
blocos ordenados (caput / paragrafo / inciso / alinea). Cada artigo carrega o
breadcrumb (titulo/capitulo/secao) para a busca relampago do painel.

Filosofia de ancora-no-inicio-da-linha (como diario-oficial/classificador.py):
so e cabecalho o que aparece no comeco de uma linha. O parser e TOLERANTE a
residuos de OCR — o que nao casar como artigo vira texto do artigo anterior, e
nunca quebra a geracao.

CLI:
  python regimento/parser.py            # gera regimento-index.json
  python regimento/parser.py --dry-run  # so imprime contagens + amostra
"""
import argparse, json, os, re, sys, unicodedata

AQUI = os.path.dirname(__file__)
RAIZ = os.path.dirname(AQUI)
FONTE = os.path.join(AQUI, "regimento-fonte.md")
SAIDA = os.path.join(RAIZ, "regimento-index.json")

# ── Ancoras estruturais (inicio de linha) ────────────────────────────────────
RE_TITULO   = re.compile(r"^T[IÍ]TULO\b(.*)$", re.I)
RE_CAPITULO = re.compile(r"^CAP[IÍ]TULO\b(.*)$", re.I)
RE_SECAO    = re.compile(r"^SE[CÇ][AÃ]O\b(.*)$", re.I)
RE_ARTIGO   = re.compile(r"^Art\.?\s*(\d+)(-[A-Z])?\s*[ºo°]?\s*[\.\-–]?\s*(.*)$")
RE_PARAG    = re.compile(r"^§\s*(\d+)\s*[ºo°]?\s*(.*)$|^Par[aá]grafo\s+[uú]nico\.?\s*(.*)$", re.I)
RE_INCISO   = re.compile(r"^([IVXLC]{1,5}|[Il|]{1,4})\s*[-–]\s*(.*)$")  # romano OCR-tolerante
RE_ALINEA   = re.compile(r"^([a-z])\)\s*(.*)$")

# Romanos lidos pelo OCR como pipe/letra: |->I, ||->II, Il->II, etc.
_ROMANO_FIX = {"|": "I", "||": "II", "|||": "III", "Il": "II", "Ill": "III",
               "l": "I", "ll": "II", "lll": "III"}


def _romano(n: int) -> str:
    tab = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
           (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
           (5, "V"), (4, "IV"), (1, "I")]
    r = ""
    for v, s in tab:
        while n >= v:
            r += s; n -= v
    return r


def _renumerar(blocos):
    """Incisos sao sempre sequenciais; reescreve I, II, III... (corrige romano de OCR),
    resetando o contador a cada caput/paragrafo. Alineas idem (a, b, c...) por inciso."""
    ci = ca = 0
    for b in blocos:
        if b["tipo"] in ("caput", "paragrafo"):
            ci = ca = 0
        elif b["tipo"] == "inciso":
            ci += 1; ca = 0
            b["rotulo"] = _romano(ci)
        elif b["tipo"] == "alinea":
            b["rotulo"] = chr(ord("a") + ca) + ")"
            ca += 1
    return blocos


def _rotulo_artigo(numero: str) -> str:
    """Convencao brasileira: ordinal ate 9 (Art. 1º), cardinal de 10 (Art. 10)."""
    base = numero.split("-")[0]
    if base.isdigit() and int(base) <= 9 and "-" not in numero:
        return f"Art. {numero}º"
    return f"Art. {numero}"


def _norm_busca(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _limpa_rotulo_estrutura(resto: str) -> str:
    """Normaliza o rotulo de TITULO/CAPITULO/Secao: conserta romano de OCR."""
    resto = resto.strip(" .-–\t")
    if not resto:
        return ""
    partes = resto.split(None, 1)
    chave = partes[0]
    fix = _ROMANO_FIX.get(chave)
    if fix:
        partes[0] = fix
    return " ".join(partes).strip()


def parse(texto: str):
    linhas = texto.splitlines()
    artigos = []
    titulo = capitulo = secao = ""
    atual = None  # artigo em construcao

    def fechar():
        if atual and atual["blocos"]:
            artigos.append(atual)

    for raw in linhas:
        ln = raw.strip()
        if not ln or ln.startswith("<!--") or ln.startswith("#"):
            continue

        m = RE_TITULO.match(ln)
        if m:
            fechar(); atual = None
            titulo = "TÍTULO " + _limpa_rotulo_estrutura(m.group(1))
            capitulo = secao = ""
            continue
        m = RE_CAPITULO.match(ln)
        if m:
            fechar(); atual = None
            capitulo = "CAPÍTULO " + _limpa_rotulo_estrutura(m.group(1))
            secao = ""
            continue
        m = RE_SECAO.match(ln)
        if m:
            fechar(); atual = None
            secao = "Seção " + _limpa_rotulo_estrutura(m.group(1))
            continue

        m = RE_ARTIGO.match(ln)
        if m:
            fechar()
            numero = m.group(1) + (m.group(2) or "")   # "23" ou "23-A"
            atual = {
                "id": "art-" + numero.lower(),
                "numero": numero,
                "titulo_sup": titulo,
                "capitulo": capitulo,
                "secao": secao,
                "blocos": [{"tipo": "caput", "rotulo": _rotulo_artigo(numero),
                            "texto": m.group(3).strip()}],
            }
            continue

        # dentro de um artigo: paragrafos / incisos / alineas / continuacao
        if atual is None:
            continue
        mp = RE_PARAG.match(ln)
        if mp:
            if mp.group(1):  # § N
                atual["blocos"].append({"tipo": "paragrafo", "rotulo": f"§ {mp.group(1)}º",
                                        "texto": (mp.group(2) or "").strip()})
            else:            # Paragrafo unico
                atual["blocos"].append({"tipo": "paragrafo", "rotulo": "Parágrafo único",
                                        "texto": (mp.group(3) or "").strip()})
            continue
        mi = RE_INCISO.match(ln)
        if mi and len(ln) > 4:
            rot = _ROMANO_FIX.get(mi.group(1), mi.group(1)).upper()
            atual["blocos"].append({"tipo": "inciso", "rotulo": rot,
                                    "texto": mi.group(2).strip()})
            continue
        ma = RE_ALINEA.match(ln)
        if ma:
            atual["blocos"].append({"tipo": "alinea", "rotulo": f"{ma.group(1)})",
                                    "texto": ma.group(2).strip()})
            continue
        # continuacao do texto do ultimo bloco
        atual["blocos"][-1]["texto"] = (atual["blocos"][-1]["texto"] + " " + ln).strip()

    fechar()

    # campo de busca (sem acento) e limpeza final
    for a in artigos:
        _renumerar(a["blocos"])
        partes = [a["titulo_sup"], a["capitulo"], a["secao"],
                  f"art {a['numero']}", "artigo " + a["numero"]]
        partes += [b["texto"] for b in a["blocos"]]
        a["texto_busca"] = _norm_busca(" ".join(partes))
        a["tags"] = ""
    return artigos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="so imprime contagens")
    ap.add_argument("--fonte", default=FONTE)
    args = ap.parse_args()

    if not os.path.exists(args.fonte):
        sys.exit(f"Fonte nao encontrada: {args.fonte}. Rode regimento/ocr_para_md.py primeiro.")
    texto = open(args.fonte, encoding="utf-8").read()
    artigos = parse(texto)

    bases = sorted({int(a["numero"].split("-")[0]) for a in artigos})
    suf = [a["numero"] for a in artigos if "-" in a["numero"]]
    print(f"Artigos: {len(artigos)} (1 a {bases[-1]}; {len(suf)} com sufixo: {suf})")
    faltam = [n for n in range(1, bases[-1] + 1) if n not in set(bases)]
    if faltam:
        print(f"Sem artigo (revogados/omitidos na fonte compilada): {faltam}")
    if args.dry_run:
        ex = artigos[4]
        print("\n--- amostra ---")
        print(ex["titulo_sup"], "›", ex["capitulo"], "›", ex["secao"])
        for b in ex["blocos"][:4]:
            print(f"  [{b['tipo']}] {b['rotulo']}: {b['texto'][:70]}")
        return

    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(artigos, f, ensure_ascii=False, indent=1)
    print(f"OK: {SAIDA} ({len(artigos)} artigos)")


if __name__ == "__main__":
    main()
