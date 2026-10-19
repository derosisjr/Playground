# -*- coding: utf-8 -*-
"""Lei Orgânica do Município de Santos -> lei-organica-index.json (raiz).

Fonte ÚNICA: ordem-do-dia/references/lei-organica-santos.md — texto da camada de texto
do PDF oficial (Legis da Prefeitura, doc. 9596), sem OCR; a skill do briefing da Ordem
do Dia lê o mesmo arquivo. Este script não edita a fonte: só a lê.

Reusa o parser do Regimento (`regimento/parser.py`, `parse(texto, opcoes)`) com as
particularidades deste PDF:
- front-matter YAML e linhas que são só o número da página (1–89) saem antes;
- rótulos com a pontuação oficial: "Art. 1º", "Art. 10.", "Art. 56-A.", "§ 1º",
  "§ 10.", "§ 2º-A.", "Parágrafo único.", "XVIII –", "a)" — e SEM renumerar incisos
  (o texto não vem de OCR; renumerar esconderia inciso revogado ou fora de ordem);
- "Artigo 59." e "Art. 56 O…" (sem pontuação) também abrem artigo;
- notas de emenda ("Inciso com redação dada pela Emenda à Lei Orgânica nº …"): no PDF
  cada uma vem depois de um marcador (U+F0B7, o "" da fonte Symbol). Elas saem do
  texto e vão para `notas` do artigo — [{"bloco": i, "texto": …}], onde `i` é o índice
  do bloco que a nota SEGUE no PDF (null quando ela vem logo depois de um cabeçalho,
  como "Título com denominação alterada…": fica com o 1º artigo da seção);
- nome de Título/Capítulo/Seção vem nas linhas de baixo ("TÍTULO I" / "DISPOSIÇÕES
  PRELIMINARES") e vira "TÍTULO I — DISPOSIÇÕES PRELIMINARES"; "DISPOSIÇÕES GERAIS" /
  "PRINCÍPIOS GERAIS" depois do nome de um capítulo viram seção sem número;
- Disposições Transitórias: a numeração recomeça em 1; esses artigos levam
  `"adt": true` e id `adt-art-N` (âncora #adt-art-N) para não colidir com o corpo;
- o texto termina em "Sala das Sessões…" (assinaturas ficam de fora).
Mesmo esquema do regimento-index.json (o painel é o mesmo, regimento-app.js), mais
`notas` e `adt` em todo artigo.

CLI:
  python regimento/lei_organica.py --dry-run   # contagens + conferências, não grava
  python regimento/lei_organica.py             # grava lei-organica-index.json
"""
import argparse
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
if RAIZ not in sys.path:
    sys.path.append(RAIZ)  # raiz do repo: comum/ e regimento/
from comum.escrita import gravar_json  # noqa: E402
from comum.saida import configurar_stdio  # noqa: E402
from regimento.parser import Opcoes, parse as parse_lei  # noqa: E402

FONTE = os.path.join(RAIZ, "ordem-do-dia", "references", "lei-organica-santos.md")
SAIDA = os.path.join(RAIZ, "lei-organica-index.json")

MARCADOR_NOTA = ""  # "" (fonte Symbol) antes de cada nota de emenda no PDF

# O que é nota de alteração pelo SENTIDO — só para conferir o marcador: toda nota
# tem de casar, e nenhum texto de artigo pode casar (ver conferir()).
RE_NOTA = re.compile(
    r"\b(?:reda[cç][aã]o|revogad[oa]s?|acrescid[oa]s?|acrescentad[oa]s?|alterad[oa]s?"
    r"|renumerad[oa]s?|suprimid[oa]s?)\b.*?\b(?:pela|conforme)\s+(?:Emenda|Lei\s+Org[aâ]nica)"
    r"|^Esta\s+Emenda\b|\bconforme\s+Emenda\b", re.I)


def _rotulo_artigo(numero: str) -> str:
    """Ordinal até 9 ("Art. 1º"); cardinal com ponto a partir de 10 ("Art. 10.");
    com letra, ponto ("Art. 56-A.") — como no texto oficial."""
    base = numero.split("-")[0]
    if "-" not in numero and int(base) <= 9:
        return f"Art. {numero}º"
    return f"Art. {numero}."


def _rotulo_paragrafo(num: str, sufixo: str = "") -> str:
    """"§ 1º", "§ 10.", "§ 2º-A." — mesma regra do artigo."""
    n = int(num)
    base = f"§ {num}º" if n <= 9 else f"§ {num}"
    if sufixo:
        return f"{base}-{sufixo}."
    return base if n <= 9 else base + "."


OPCOES = Opcoes(
    # "Art. 1º O…", "Art. 10. O…", "Art. 21.Compete…", "Art. 56 O…", "Art. 56-A. …",
    # "Artigo 59. A…", "Art. 83 – REVOGADO.", "Art. 167." (texto na linha de baixo)
    re_artigo=re.compile(r"^Art(?:igo)?\.?\s*(\d+)(-[A-Z])?\s*[ºo°]?\s*[\.\-–]?\s*(.*)$"),
    # "§ 1º", "§ 6o", "§ 10.", "§ 2º-A.", "§2º-B.", "§ 4º-A O…", "§ 1º - As…",
    # "Parágrafo Único." / "Parágrafo único.O…". Sem re.I: com ele o [ºo°] engolia o
    # "O" de "§ 1 O…" e a letra do sufixo casaria minúscula.
    re_paragrafo=re.compile(
        r"^§\s*(?P<num>\d+)\s*[ºo°]?(?:-(?P<suf>[A-Z])\b)?\s*[\.\-–]?\s*(?P<texto>.*)$"
        r"|^(?i:par[aá]grafo\s+[uú]nico)\.?\s*(?P<unico>.*)$"),
    # romano estrito (I a LXXXIX): "CIVIL – …" não é inciso; "IX –" sozinho na linha é
    re_inciso=re.compile(r"^((?=[IVXLC])(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))\s*[-–]\s*(.*)$"),
    inciso_min=0,
    renumerar=False,
    rotulo_artigo=_rotulo_artigo,
    rotulo_paragrafo=_rotulo_paragrafo,
    rotulo_unico="Parágrafo único.",
    rotulo_inciso=lambda r: f"{r} –",
    ignorar=re.compile(r"^\s*\d{1,3}\s*$"),       # número de página do PDF
    fim=re.compile(r"^Sala das Sess[õo]es\b"),     # daqui em diante, assinaturas
    marcadores_nota=MARCADOR_NOTA,
    nomes_estrutura=True,
    subtitulos=frozenset({"DISPOSIÇÕES GERAIS", "PRINCÍPIOS GERAIS"}),
    re_transitorias=re.compile(r"TRANSIT[ÓO]RIA", re.I),
    juntar_hifen=True,
)


def sem_front_matter(texto: str) -> str:
    """Tira o bloco YAML do topo (--- … ---): metadados do download, não da lei."""
    if texto.startswith("---"):
        fim = texto.find("\n---", 3)
        if fim != -1:
            return texto[fim + 4:]
    return texto


def _espacos(s: str) -> str:
    return " ".join(s.split())


def parse(texto: str):
    """Texto do .md (com front-matter) -> lista de artigos (esquema do Regimento + notas/adt)."""
    artigos = parse_lei(sem_front_matter(texto), OPCOES)
    for a in artigos:  # espaço duplo do PDF ("será de  até dois") não é texto
        for b in a["blocos"]:
            b["texto"] = _espacos(b["texto"])
        for n in a["notas"]:
            n["texto"] = _espacos(n["texto"])
    return artigos


def _ordem(numero: str):
    base, _, suf = numero.partition("-")
    return int(base), suf


def conferir(artigos) -> list:
    """Problemas que impedem publicar (lista vazia = ok)."""
    problemas = []
    ids = [a["id"] for a in artigos]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        problemas.append(f"ids repetidos: {repetidos}")
    for grupo, nome in ((False, "corpo"), (True, "Disposições Transitórias")):
        nums = [_ordem(a["numero"]) for a in artigos if a["adt"] is grupo]
        fora = [f"{a}-{b}" for a, b in zip(nums, nums[1:]) if b <= a]
        if fora:
            problemas.append(f"{nome}: numeração fora de ordem em {fora}")
        if nums and nums[0] != (1, ""):
            problemas.append(f"{nome}: não começa no art. 1")
    corpo = [a for a in artigos if not a["adt"]]
    if any(a["adt"] for a in artigos[:len(corpo)]):
        problemas.append("artigo das Disposições Transitórias no meio do corpo")
    for a in artigos:
        if not a["blocos"][0]["texto"]:
            problemas.append(f"{a['id']}: caput vazio")
        for b in a["blocos"]:
            if RE_NOTA.search(b["texto"]) or MARCADOR_NOTA in b["texto"]:
                problemas.append(f"{a['id']} {b['rotulo']}: nota de emenda dentro do texto")
        for n in a["notas"]:
            if not RE_NOTA.search(n["texto"]):
                problemas.append(f"{a['id']}: nota sem cara de nota: {n['texto'][:60]}")
            if n["bloco"] is not None and not 0 <= n["bloco"] < len(a["blocos"]):
                problemas.append(f"{a['id']}: nota presa a bloco inexistente ({n['bloco']})")
    return problemas


def resumo(artigos) -> dict:
    corpo = [a for a in artigos if not a["adt"]]
    return {
        "corpo": len(corpo),
        "adt": len(artigos) - len(corpo),
        "notas": sum(len(a["notas"]) for a in artigos),
        "corpo_alterados": sum(1 for a in corpo if a["notas"]),
        "com_sufixo": [a["numero"] for a in corpo if "-" in a["numero"]],
    }


def main():
    configurar_stdio()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="só contagens e conferências")
    ap.add_argument("--fonte", default=FONTE)
    args = ap.parse_args()

    with open(args.fonte, encoding="utf-8") as f:
        artigos = parse(f.read())
    r = resumo(artigos)
    print(f"Artigos: {r['corpo']} no corpo (com letra: {', '.join(r['com_sufixo'])}) "
          f"+ {r['adt']} nas Disposições Transitórias")
    print(f"Notas de emenda: {r['notas']} (artigos do corpo com nota: {r['corpo_alterados']})")
    problemas = conferir(artigos)
    for p in problemas:
        print("PROBLEMA:", p)
    if problemas:
        return 1
    if args.dry_run:
        a = next(x for x in artigos if x["id"] == "art-58")
        print("\n--- amostra: art. 58 ---")
        print(a["titulo_sup"], "›", a["capitulo"], "›", a["secao"])
        for b in a["blocos"]:
            if b["rotulo"].startswith("XVIII"):
                print(f"  {b['rotulo']} {b['texto']}")
        for n in a["notas"]:
            print(f"  [nota após o bloco {n['bloco']}] {n['texto']}")
        return 0
    gravar_json(SAIDA, artigos, separators=(",", ":"))
    print(f"OK: {SAIDA} ({len(artigos)} artigos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
