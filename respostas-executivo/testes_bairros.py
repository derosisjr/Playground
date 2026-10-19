#!/usr/bin/env python3
"""Testes do normalizador de bairros (bairros.py) e do GeoJSON que ele usa.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import importlib.util
import json
import os
import sys
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
if RAIZ not in sys.path:
    sys.path.append(RAIZ)  # comum/
import bairros  # noqa: E402

# As 47 grafias da coluna "Bairro" da aba de indicações em 18/10/2026 (todas as que
# aparecem na planilha), com o que o índice público pode levar de cada uma.
GRAFIAS = {
    "PONTA DA PRAIA": ("Ponta da Praia", None),
    "JOSÉ MENINO": ("José Menino", None),
    "BOQUEIRÃO": ("Boqueirão", None),
    "EMBARÉ": ("Embaré", None),
    "CENTRO": ("Centro", None),
    "APARECIDA": ("Aparecida", None),
    "VILA MATHIAS": ("Vila Mathias", None),
    "GONZAGA": ("Gonzaga", None),
    "VILA BELMIRO": ("Vila Belmiro", None),
    "GERAL": (None, "Cidade toda"),
    "MARAPÉ": ("Marapé", None),
    "CAMPO GRANDE": ("Campo Grande", None),
    "JOSE MENINO": ("José Menino", None),
    "PAQUETÁ": ("Paquetá", None),
    "ENCRUZILHADA": ("Encruzilhada", None),
    "ORLA": (None, "Orla"),
    "CANELEIRA": ("Caneleira", None),
    "VILA NOVA": ("Vila Nova", None),
    "ZONA NOROESTE": (None, "Zona Noroeste"),
    "MACUCO": ("Macuco", None),
    "JABAQUARA": ("Jabaquara", None),
    "ITARARÉ": (None, None),               # é de São Vicente (divisa com o José Menino)
    "MORRO DO SÃO BENTO": ("Morro São Bento", None),
    "ORLA DA PRAIA": (None, "Orla"),
    "POMPÉIA": ("Pompéia", None),
    "SANTA MARIA": ("Santa Maria", None),
    "VILA GILDA": ("Vila Gilda", None),
    "ALEMOA": ("Alemoa", None),
    "APARTECIDA": ("Aparecida", None),
    "AREIA BRANCA": ("Areia Branca", None),
    "BOM RETIRO - ZN": ("Bom Retiro", None),
    "BOQUEIRAO": ("Boqueirão", None),
    "CENTRO HISTÓRICO": (None, "Centro Histórico"),
    "CET": (None, None),                   # órgão (Companhia de Engenharia de Tráfego)
    "CHICO DE PAULA": ("Chico de Paula", None),
    "JARDIM CASTELO": ("Castelo", None),
    "JD. CASTELO": ("Castelo", None),
    "JD. SÃO MANOEL": ("São Manoel", None),
    "MORRO DA PENHA": ("Morro Penha", None),
    "MORRO DO ILHÉU": (None, None),        # o GeoJSON só tem "Ilhéu Alto": não adivinhar
    "POMPEIA": ("Pompéia", None),
    "PONTA DA P´RAIA": ("Ponta da Praia", None),
    "POPULAÇÃO DE RUA": (None, None),      # público, não lugar
    "RESPOSTA EM 07 MESES": (None, None),  # anotação interna: nunca vira bairro nem região
    "SABOÓ": ("Saboó", None),
    "SANTA MARIA - ZN": ("Santa Maria", None),
    "SÃO MANOEL": ("São Manoel", None),
}


def _geojson():
    with open(bairros.GEOJSON, encoding="utf-8") as f:
        return json.load(f)


class TestNormalizador(unittest.TestCase):
    def test_as_47_grafias_reais(self):
        self.assertEqual(len(GRAFIAS), 47)
        for bruto, esperado in GRAFIAS.items():
            with self.subTest(bruto=bruto):
                self.assertEqual(bairros.canonico(bruto), esperado)

    def test_vazio_e_espacos(self):
        for v in ("", "   ", None, "-", "."):
            self.assertEqual(bairros.canonico(v), (None, None))
        self.assertEqual(bairros.canonico("  ponta   da praia "), ("Ponta da Praia", None))

    def test_nunca_devolve_texto_fora_das_listas(self):
        # o que sai é sempre um nome do GeoJSON ou um rótulo de região — nunca o texto
        # da planilha (grafias inventadas incluídas)
        oficiais, regioes = set(bairros.oficiais()), set(bairros.REGIOES.values())
        for bruto in list(GRAFIAS) + ["ver com o Rui", "Rua X, 123", "ZN", "JD. NOVO - ZN"]:
            b, r = bairros.canonico(bruto)
            self.assertTrue(b is None or b in oficiais, (bruto, b))
            self.assertTrue(r is None or r in regioes, (bruto, r))
            self.assertFalse(b and r, bruto)

    def test_nomes_usados_existem_no_geojson(self):
        oficiais = set(bairros.oficiais())
        for nome in bairros.SINONIMOS.values():
            self.assertIn(nome, oficiais)
        for bruto, (b, _) in GRAFIAS.items():
            if b:
                self.assertIn(b, oficiais, bruto)
        # região não pode ter nome de bairro (o painel as trata como coisas distintas)
        self.assertFalse(set(bairros.REGIOES.values()) & oficiais)


class TestGeoJSON(unittest.TestCase):
    def test_propriedades_e_nomes(self):
        geo = _geojson()
        nomes = [f["properties"]["nome"] for f in geo["features"]]
        self.assertEqual(len(nomes), 71)
        self.assertEqual(len(set(nomes)), 71)
        for f in geo["features"]:
            self.assertEqual(set(f["properties"]), {"nome", "cdbairro", "area_continental"})
            self.assertEqual(f["geometry"]["type"], "MultiPolygon")
        continentais = {f["properties"]["nome"] for f in geo["features"]
                        if f["properties"]["area_continental"]}
        self.assertEqual(continentais, {
            "Bagres", "Barnabé", "Cabuçú-Caetê", "Caruara", "Guarapá", "Iriri",
            "Monte Cabrão", "Nossa Senhora das Neves", "Piaçaguera", "Quilombo", "Trindade"})

    def test_preparar_sem_rede(self):
        spec = importlib.util.spec_from_file_location(
            "preparar_bairros", os.path.join(RAIZ, "geo", "preparar_bairros.py"))
        pb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pb)
        q = lambda x, y, d=0.01: [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]  # noqa: E731
        bruto = {"features": [
            {"properties": {"nome": "Chico De Paula", "cdbairro": 7},
             "geometry": {"type": "Polygon", "coordinates": q(0, 0)}},
            {"properties": {"nome": "Ilha", "cdbairro": 9},
             "geometry": {"type": "Polygon", "coordinates": q(5, 5)}},
            {"properties": {"nome": "Ilha", "cdbairro": 9},  # repetida, como Barnabé
             "geometry": {"type": "Polygon", "coordinates": q(5, 5)}},
        ]}
        regionais = {"features": [
            {"properties": {"subprefeitura": "PREFEITURA REGIONAL DA ÁREA CONTINENTAL"},
             "geometry": {"type": "Polygon", "coordinates": q(4, 4, 3)}},
            {"properties": {"subprefeitura": "PREFEITURA REGIONAL DOS MORROS"},
             "geometry": {"type": "Polygon", "coordinates": q(-1, -1, 3)}},
        ]}
        geo, rel = pb.preparar(bruto, regionais)
        props = [f["properties"] for f in geo["features"]]
        self.assertEqual(props, [
            {"nome": "Chico de Paula", "cdbairro": 7, "area_continental": False},
            {"nome": "Ilha", "cdbairro": 9, "area_continental": True},
        ])
        self.assertEqual(len(geo["features"][1]["geometry"]["coordinates"]), 1)  # cópia sai
        self.assertEqual(rel["repetidos"], {"Ilha": [9, 9]})


if __name__ == "__main__":
    unittest.main()
