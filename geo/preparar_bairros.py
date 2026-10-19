#!/usr/bin/env python3
"""Limites dos bairros de Santos para o mapa de Indicações (`geo/santos-bairros.geojson`).

Fonte: GeoServer público da Prefeitura de Santos (WFS 2.0, EPSG:4326):
  - `santos:bairros` — "Layer de abairramento oficial do município de santos"
    (72 feições, 71 nomes: Barnabé vem duas vezes, com a mesma geometria);
  - `santos:subprefeituras` — as 5 Prefeituras Regionais; só serve para marcar
    quais bairros são da ÁREA CONTINENTAL (o mapa os desenha num recorte à parte).
O serviço não declara licença (Fees/AccessConstraints: NONE) — ver geo/README.md.

Só a biblioteca padrão. O arquivo gerado é versionado; rodar de novo só quando a
Prefeitura mudar o abairramento (e conferir o diff dos nomes: o normalizador
`respostas-executivo/bairros.py` e o teste dele dependem deles).

O que faz:
  1. simplifica cada anel por Douglas–Peucker com tolerância em METROS (projeção
     local equirretangular em lat -23,95: 4 m ≈ 0,000036° de latitude e 0,000039°
     de longitude) — medir em graus direto distorce ~9% entre os eixos;
  2. arredonda as coordenadas a 5 casas (~1 m) e tira pontos repetidos;
  3. junta feições de mesmo `nome` num MultiPolygon (polígono repetido sai);
  4. nome com conectivos em minúscula ("Chico De Paula" → "Chico de Paula"), o resto
     como na fonte;
  5. `area_continental`: a Prefeitura Regional onde cai a maioria dos pontos internos
     amostrados do bairro é a da Área Continental (Barnabé e Bagres são ilhas do
     estuário, mas a Prefeitura os põe nela).
Propriedades de cada feição: `nome`, `cdbairro`, `area_continental`. Sem data dentro
do arquivo de propósito: rodar de novo sobre a mesma fonte dá o mesmo arquivo.

Uso:
  python geo/preparar_bairros.py                 # baixa as duas camadas e grava
  python geo/preparar_bairros.py --dry-run       # baixa e relata, sem gravar
  python geo/preparar_bairros.py --bairros b.geojson --regionais r.geojson   # offline
"""
import argparse
import json
import math
import os
import sys
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.append(RAIZ)  # camada comum do repo (comum/)
from comum.escrita import gravar_texto  # noqa: E402
from comum.formato import sem_acento  # noqa: E402

WFS = ("https://egov.santos.sp.gov.br/geoserver/ows?service=WFS&version=2.0.0"
       "&request=GetFeature&typeNames={camada}&outputFormat=application/json"
       "&srsName=EPSG:4326")
CAMADA_BAIRROS = "santos:bairros"
CAMADA_REGIONAIS = "santos:subprefeituras"
SAIDA = os.path.join(RAIZ, "geo", "santos-bairros.geojson")
UA = {"User-Agent": "Mozilla/5.0 (compatible; GabineteMapaBairros/1.0)"}

LAT0 = -23.95
KX = 111412.84 * math.cos(math.radians(LAT0)) - 93.5 * math.cos(math.radians(3 * LAT0))
KY = 111132.92 - 559.82 * math.cos(math.radians(2 * LAT0))
TOLERANCIA_M = 4.0
CASAS = 5
CONECTIVOS = {"de", "da", "das", "do", "dos", "e"}
GRADE = 24  # amostragem de pontos internos (GRADE-1)² por bairro


def baixar(camada: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(WFS.format(camada=camada), headers=UA),
                                timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def ler(caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def nome_bonito(nome: str) -> str:
    partes = nome.split(" ")
    return " ".join(p.lower() if i and p.lower() in CONECTIVOS else p
                    for i, p in enumerate(partes))


def _dist_seg(p, a, b):
    """Distância (m) do ponto p ao segmento ab — pontos já projetados em metros."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _dp(pts, tol):
    """Douglas–Peucker iterativo numa polilinha aberta; devolve os índices mantidos."""
    manter = [False] * len(pts)
    manter[0] = manter[-1] = True
    pilha = [(0, len(pts) - 1)]
    while pilha:
        i, j = pilha.pop()
        dmax, k = -1.0, -1
        for m in range(i + 1, j):
            d = _dist_seg(pts[m], pts[i], pts[j])
            if d > dmax:
                dmax, k = d, m
        if k != -1 and dmax > tol:
            manter[k] = True
            pilha.append((i, k))
            pilha.append((k, j))
    return [i for i, ok in enumerate(manter) if ok]


def simplificar_anel(anel, tol):
    """Anel fechado: corta no ponto mais distante do 1º e simplifica as duas metades
    (DP num anel com as duas pontas no mesmo ponto não tem segmento de referência)."""
    if len(anel) < 5:
        return anel
    xy = [((x - anel[0][0]) * KX, (y - anel[0][1]) * KY) for x, y in anel]
    k = max(range(len(xy)), key=lambda m: xy[m][0] ** 2 + xy[m][1] ** 2)
    a = _dp(xy[: k + 1], tol)
    b = [k + m for m in _dp(xy[k:], tol)]
    novo = [anel[i] for i in a + b[1:]]
    if len(novo) < 4:  # anel minúsculo: simplificar o apagaria
        return anel
    return novo


def arredondar(anel):
    out = []
    for x, y in anel:
        p = [round(x, CASAS), round(y, CASAS)]
        if not out or p != out[-1]:
            out.append(p)
    if out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else None


def processar_poligono(poli, tol):
    aneis = []
    for anel in poli:
        r = arredondar(simplificar_anel(anel, tol))
        if r is None:
            if not aneis:  # contorno externo degenerado: o polígono inteiro sai
                return None
            continue      # buraco degenerado: some
        aneis.append(r)
    return aneis


def poligonos(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    raise ValueError("geometria inesperada: " + geom["type"])


def contar_vertices(polis):
    return sum(len(anel) for p in polis for anel in p)


# ── Prefeitura Regional de cada bairro ────────────────────────────────────────
def _dentro_anel(x, y, anel):
    dentro = False
    j = len(anel) - 1
    for i in range(len(anel)):
        xi, yi = anel[i]
        xj, yj = anel[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def _dentro(x, y, polis):
    return any(_dentro_anel(x, y, p[0]) and not any(_dentro_anel(x, y, h) for h in p[1:])
               for p in polis)


def regional(polis, regionais) -> tuple[str, float]:
    """(nome da Prefeitura Regional com mais pontos internos do bairro, fração deles)."""
    xs = [x for p in polis for x, _ in p[0]]
    ys = [y for p in polis for _, y in p[0]]
    votos: dict[str, int] = {}
    for a in range(1, GRADE):
        for b in range(1, GRADE):
            x = min(xs) + (max(xs) - min(xs)) * a / GRADE
            y = min(ys) + (max(ys) - min(ys)) * b / GRADE
            if not _dentro(x, y, polis):
                continue
            for nome, rp in regionais:
                if _dentro(x, y, rp):
                    votos[nome] = votos.get(nome, 0) + 1
    if not votos:
        return "", 0.0
    melhor = max(votos, key=votos.get)
    return melhor, votos[melhor] / sum(votos.values())


def eh_continental(nome_regional: str) -> bool:
    return "AREA CONTINENTAL" in sem_acento(nome_regional, caixa="alta")


def preparar(bruto: dict, regionais_brutas: dict) -> tuple[dict, dict]:
    """(FeatureCollection pronta, relatório). Função pura: testável sem rede."""
    por_nome, cods, v_antes = {}, {}, 0
    for f in bruto["features"]:
        nome = nome_bonito(f["properties"]["nome"].strip())
        polis = poligonos(f["geometry"])
        v_antes += contar_vertices(polis)
        lista = por_nome.setdefault(nome, [])
        for p in polis:
            if p not in lista:  # Barnabé: a 2ª cópia é idêntica
                lista.append(p)
        cods.setdefault(nome, []).append(f["properties"].get("cdbairro"))

    regionais = [(f["properties"]["subprefeitura"], poligonos(f["geometry"]))
                 for f in regionais_brutas["features"]]
    feicoes, v_depois, regional_de = [], 0, {}
    for nome in sorted(por_nome, key=lambda s: s.lower()):
        polis = [q for q in (processar_poligono(p, TOLERANCIA_M) for p in por_nome[nome]) if q]
        v_depois += contar_vertices(polis)
        cod = sorted({c for c in cods[nome] if c is not None})
        reg, fracao = regional(polis, regionais)
        regional_de[nome] = (reg, fracao)
        feicoes.append({
            "type": "Feature",
            "properties": {"nome": nome, "cdbairro": cod[0] if len(cod) == 1 else cod,
                           "area_continental": eh_continental(reg)},
            "geometry": {"type": "MultiPolygon", "coordinates": polis},
        })
    relatorio = {
        "feicoes_fonte": len(bruto["features"]), "nomes": len(feicoes),
        "vertices": (v_antes, v_depois),
        "repetidos": {n: c for n, c in cods.items() if len(c) > 1},
        "regional": regional_de,
    }
    return {"type": "FeatureCollection", "features": feicoes}, relatorio


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bairros", help="GeoJSON já baixado de santos:bairros (senão baixa)")
    ap.add_argument("--regionais", help="GeoJSON já baixado de santos:subprefeituras (senão baixa)")
    ap.add_argument("--saida", default=SAIDA)
    ap.add_argument("--dry-run", action="store_true", help="relata sem gravar")
    args = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")  # console do Windows (cp1252)
        except (AttributeError, ValueError):
            pass

    bruto = ler(args.bairros) if args.bairros else baixar(CAMADA_BAIRROS)
    regionais = ler(args.regionais) if args.regionais else baixar(CAMADA_REGIONAIS)
    geo, rel = preparar(bruto, regionais)
    texto = json.dumps(geo, ensure_ascii=False, separators=(",", ":"))

    print(f"feições: {rel['feicoes_fonte']} na fonte → {rel['nomes']} nomes únicos")
    print(f"vértices: {rel['vertices'][0]:,} → {rel['vertices'][1]:,}".replace(",", "."))
    print(f"tamanho: {len(texto.encode('utf-8')) / 1024:.1f} KB (tolerância {TOLERANCIA_M:g} m, "
          f"{CASAS} casas decimais)")
    if rel["repetidos"]:
        print("nomes repetidos na fonte (juntados):", rel["repetidos"])
    cont = [f["properties"]["nome"] for f in geo["features"] if f["properties"]["area_continental"]]
    print(f"área continental ({len(cont)}): {', '.join(cont)}")
    sem = [n for n, (r, _) in rel["regional"].items() if not r]
    if sem:
        print("AVISO: sem Prefeitura Regional (nenhum ponto interno amostrado):", sem)
    duvida = [f"{n} ({fr:.0%})" for n, (r, fr) in rel["regional"].items() if r and fr < 0.9]
    if duvida:
        print("Prefeitura Regional com menos de 90% dos pontos:", ", ".join(duvida))
    if args.dry_run:
        print("--dry-run: nada gravado")
        return 0
    gravar_texto(args.saida, texto)
    print("gravado:", args.saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
