"""Bairro oficial (ou região) a partir da coluna "Bairro" da aba de indicações.

A coluna é texto livre da assessoria — 47 grafias em out/2026 ("JOSÉ MENINO" e "JOSE
MENINO", "JD. CASTELO", "PONTA DA P´RAIA", "SANTA MARIA - ZN") — e às vezes nem é
bairro: "POPULAÇÃO DE RUA", "CET" e até anotação interna do gabinete ("RESPOSTA EM 07
MESES"). Por isso o índice público NUNCA leva o texto da planilha: só o nome oficial
do bairro (o do GeoJSON da Prefeitura, `geo/santos-bairros.geojson`) ou uma região
maior que um bairro (Orla, Zona Noroeste…). O que não for reconhecido fica vazio,
sem adivinhar.
"""

import functools
import json
import os
import re

from comum.formato import sem_acento

GEOJSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "geo", "santos-bairros.geojson")

# Lugar real, mas maior que um bairro: vai para `regiao` e nunca é repartido entre os
# bairros do mapa. A chave já vem sem acento, em maiúsculas (ver `chave`). O valor é o
# rótulo publicado — .github/scripts/checar_publicos.py lê este dicionário.
REGIOES = {
    "ORLA": "Orla",
    "ORLA DA PRAIA": "Orla",
    "ZONA NOROESTE": "Zona Noroeste",
    "ZN": "Zona Noroeste",
    "MORROS": "Morros",
    "AREA CONTINENTAL": "Área Continental",
    # a Prefeitura Regional da Região Central Histórica cobre Centro, Valongo, Paquetá,
    # Vila Nova, Vila Mathias, Chinês e as áreas de porto vizinhas
    "CENTRO HISTORICO": "Centro Histórico",
    "GERAL": "Cidade toda",
}
# grafia → nome oficial do GeoJSON (nome popular ou erro de digitação)
SINONIMOS = {
    "VILA MATIAS": "Vila Mathias",
    "JARDIM CASTELO": "Castelo",          # nome popular; o oficial é "Castelo"
    "JARDIM SAO MANOEL": "São Manoel",    # idem
    "JARDIM SAO MANUEL": "São Manoel",
    "SAO MANUEL": "São Manoel",
    "PONTA DA PARAIA": "Ponta da Praia",  # erro de digitação
    "APARTECIDA": "Aparecida",            # erro de digitação
}
RE_MORRO = re.compile(r"^MORRO (?:DO|DA|DOS|DAS|DE) (.+)$")


def chave(texto) -> str:
    """Maiúsculas, sem acento nem pontuação. O acento solto ("PONTA DA P´RAIA") e o
    apóstrofo saem ANTES: virando espaço, partiriam a palavra ao meio."""
    s = re.sub(r"[´`'’‘]", "", str(texto or ""))
    s = sem_acento(s, forma="NFD", caixa="alta")
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", s).split())


@functools.lru_cache(maxsize=1)
def oficiais() -> tuple[str, ...]:
    """Nomes oficiais dos bairros, na ordem do GeoJSON."""
    with open(GEOJSON, encoding="utf-8") as f:
        return tuple(ft["properties"]["nome"] for ft in json.load(f)["features"])


@functools.lru_cache(maxsize=1)
def _por_chave() -> dict[str, str]:
    return {chave(n): n for n in oficiais()}


def canonico(texto) -> tuple[str | None, str | None]:
    """(bairro oficial, None) | (None, região) | (None, None) quando não dá para afirmar."""
    k = chave(texto)
    if not k:
        return None, None
    if k in REGIOES:
        return None, REGIOES[k]
    if k.endswith(" ZN"):  # "SANTA MARIA - ZN": a sigla só diz a região do bairro
        k = k[:-3].strip()
    k = re.sub(r"^JD\b", "JARDIM", k)
    nomes = _por_chave()
    if k in nomes:
        return nomes[k], None
    if k in SINONIMOS:
        return SINONIMOS[k], None
    m = RE_MORRO.match(k)  # "MORRO DO SÃO BENTO" → "Morro São Bento", se existir
    if m and chave("Morro " + m[1]) in nomes:
        return nomes[chave("Morro " + m[1])], None
    return None, None
