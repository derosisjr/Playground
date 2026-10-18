# -*- coding: utf-8 -*-
"""Export do Legis: ordem por data, número tirado do título, ementas.json e --db/--saida.

Sem rede: o banco é um SQLite temporário criado do schema.sql real. Os títulos são
reais (variantes do "nº" que o regex do crawler, n\\.?º, não reconhece).
"""
import json
import os
import sqlite3

import pytest

import export

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LO, LC, DEC = "Lei ordinária", "Lei complementar", "Decreto"

# chaves do legis-index.json que o painel, a busca Ctrl+K (comum.js), o hub
# (bases_atualizacao.py) e a triagem já leem — o índice não ganha nem perde chave
CHAVES = ["id", "tipo", "numero", "ano", "data_norma", "titulo", "ementa",
          "tags", "situacao", "url_legis", "url_pdf"]

NORMAS = [
    # id, tipo, numero, ano, data_norma, titulo, descricao, situacao, revogada_por
    (11841, DEC, "", 2026, "05/03/2026", "Decreto n.° 11.161, de 05 de março",
     "DISPÕE SOBRE O HORÁRIO DE FUNCIONAMENTO.", "", None),
    (11895, LO, "", 2026, "15/04/2026", "Lei n. 4.742, de 15 de abril", "", "", None),
    (12100, LO, "4.804", 2026, "10/10/2026", "Lei n.º 4.804, de 10 de outubro",
     "INSTITUI O PROGRAMA X.", "", None),
    (12062, DEC, "", 2026, "", "Decreto n.° 11.308, de 1º de setembro", "", "", None),  # sem data
    (10690, LO, "999", 2024, "14/05/2024", "Lei n.º 999, de 14 de maio", "", "", None),
    (10691, LO, "1.000", 2024, "14/05/2024", "Lei n.º 1.000, de 14 de maio", "", "", None),
    (7005, LO, "", 2018, "", "Lei nº. 3.441 de 29 de agosto", "", "revogada", 12100),
    (4797, LO, "", 2014, "10/04/2014", "Lei n,º 2.981, de 10 de abril", "  ", "", None),
    (7424, LC, "", 2019, "06/06/2019", "Lei Complementar n. º 1.041, de 06 de junho", None, "", None),
    (10897, LC, "", 2024, "30/09/2024", "Lei Complementar n° 1.280, de 30 de setembro", "", "", None),
    (9596, "Lei Orgânica", "", None, "", "LEI ORGÂNICA DO MUNICÍPIO", "", "", None),
    (54, "Consolidação", "", None, "",
     'ITBI - Imposto sobre Transmissão de Bens Imóveis por Ato Oneroso " inter vivos"', "", "", None),
]


@pytest.fixture
def banco(tmp_path):
    db = tmp_path / "legis.sqlite"
    conn = sqlite3.connect(db)
    with open(os.path.join(AQUI, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.executemany(
        "INSERT INTO normas (id, tipo, numero, ano, data_norma, titulo, ementa, descricao, tags, "
        "situacao, revogada_por, url_legis, url_pdf, fonte, data_coleta) "
        "VALUES (?, ?, ?, ?, ?, ?, '', ?, '', ?, ?, ?, ?, 'Legis', '2026-10-12T00:00:00')",
        [(i, t, n, a, d, ti, de, s, r, f"https://x/legis/documents/{i}",
          f"https://x/legis/documents/{i}/download") for i, t, n, a, d, ti, de, s, r in NORMAS])
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def saida(banco, tmp_path):
    pasta = tmp_path / "saida"
    export.main(["--db", str(banco), "--saida", str(pasta)])
    return pasta


def _ler(caminho):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("titulo,esperado", [
    ("Decreto n.° 11.161, de 05 de março", "11.161"),
    ("Lei n,º 2.981, de 10 de abril", "2.981"),
    ("Lei nº. 3.441 de 29 de agosto", "3.441"),
    ("Lei Complementar n. º 1.041, de 06 de junho", "1.041"),
    ("Lei Complementar n° 1.280, de 30 de setembro", "1.280"),
    ("Lei n. 4.742, de 15 de abril", "4.742"),
    ("Decreto n.° 11.308, de 1º de setembro", "11.308"),
    ("LEI ORGÂNICA DO MUNICÍPIO", ""),
    ('ITBI - Imposto sobre Transmissão de Bens Imóveis por Ato Oneroso " inter vivos"', ""),
    ("Estatuto dos Funcionários Públicos Municipais de Santos", ""),
    ("", ""),
    (None, ""),
])
def test_numero_do_titulo(titulo, esperado):
    assert export.numero_do_titulo(titulo) == esperado


def test_numero_ausente_vem_do_titulo(saida):
    por = {n["id"]: n for n in _ler(saida / "legis-index.json")}
    assert por[11841]["numero"] == "11.161"
    assert por[7005]["numero"] == "3.441"
    assert por[7424]["numero"] == "1.041"
    assert por[12100]["numero"] == "4.804"   # número do banco não é tocado
    assert por[9596]["numero"] == "" and por[54]["numero"] == ""


def test_ordem_por_data_da_norma_mais_recente_primeiro(saida):
    ids = [n["id"] for n in _ler(saida / "legis-index.json")]
    assert ids == [
        12100, 11895, 11841,   # 10/10, 15/04, 05/03/2026
        12062,                 # 2026 sem data: fim do próprio ano
        10897,                 # 30/09/2024
        10691, 10690,          # 14/05/2024: 1.000 antes de 999 (numérico, não texto)
        7424, 7005, 4797,      # 2019, 2018 (sem data), 2014
        9596, 54,              # sem ano: no fim
    ]


def test_chaves_do_indice_inalteradas(saida):
    for n in _ler(saida / "legis-index.json"):
        extras = ["revogada_por"] if n["id"] == 7005 else []
        assert list(n) == CHAVES + extras
        assert "descricao" not in n
    por = {n["id"]: n for n in _ler(saida / "legis-index.json")}
    assert por[7005]["revogada_por"] == 12100


def test_ementas_json(saida):
    texto = (saida / "ementas.json").read_text(encoding="utf-8")
    ementas = json.loads(texto)
    # só quem tem ementa oficial; chave = id (string), em ordem crescente de id
    assert ementas == {"11841": "DISPÕE SOBRE O HORÁRIO DE FUNCIONAMENTO.",
                       "12100": "INSTITUI O PROGRAMA X."}
    assert list(ementas) == sorted(ementas, key=int)
    assert "\n" not in texto and ", " not in texto   # compacto, como o índice


def test_saida_nao_toca_os_arquivos_versionados(banco, tmp_path):
    vigiados = [export.JSON_PATH, export.EMENTAS_PATH]
    antes = [os.path.getmtime(p) if os.path.exists(p) else None for p in vigiados]
    pasta = tmp_path / "out"
    export.main(["--db", str(banco), "--saida", str(pasta)])
    assert sorted(os.listdir(pasta)) == ["ementas.json", "legis-index.json", "legis.csv", "legis.xlsx"]
    assert [os.path.getmtime(p) if os.path.exists(p) else None for p in vigiados] == antes
