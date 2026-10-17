"""Export do índice de proposituras: ordem por data, campos de tramitação e --db/--saida.

Sem rede: o banco é um SQLite temporário criado do schema.sql real.
"""
import json
import os
import re
import sqlite3
import sys

import pytest

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AQUI)
import crawler  # noqa: E402
import export  # noqa: E402

ARQUIVO = "Divisão de Arquivo Público"
PAUTA = "Diretoria Legislativa - Aguardando Pautação"
PDL = "Projeto de Decreto Legislativo"
PL = "Projeto de Lei"

# chaves que o painel, a busca Ctrl+K (comum.js) e o hub já leem — não podem sumir
CHAVES_ANTIGAS = ["cod", "tipo", "subtipo", "numero", "ano", "data_propositura",
                  "autor", "ementa", "local_atual", "situacao", "url_detalhes", "url_pdf"]

DESPACHO_LONGO = ("ENCAMINHO PARA PAUTAÇÃO, COM OS PARECERES DAS SEGUINTES COMISSÕES: CCJ E CFO.\n\n"
                  "(ASSINADO DIGITALMENTE)\nJOSÉ LUIZ VERGÍLIO DE CARVALHO\nR.F. 35.335-9\nCHEFE")


def _prop(cod, subtipo, numero, data, local, situacao="Encaminhado", autor="Fulano"):
    return {"cod": cod, "tipo": "Projeto", "subtipo": subtipo, "numero": numero,
            "ano": int(numero.split("/")[1]), "processo": "", "data_propositura": data,
            "autor": autor, "ementa": f"ementa {cod}", "local_atual": local, "situacao": situacao,
            "data_situacao": "", "url_detalhes": f"https://x/detalhes.php?cod={cod}",
            "url_pdf": "", "fonte": "Câmara Municipal de Santos", "data_coleta": "2026-10-17T00:00:00"}


@pytest.fixture
def banco(tmp_path):
    db = tmp_path / "proposituras.sqlite"
    conn = sqlite3.connect(db)
    with open(os.path.join(AQUI, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    props = [
        _prop(1, PDL, "1/2026", "03/02/2026", ARQUIVO),                    # final: arquivado
        _prop(2, PDL, "10/2026", "07/05/2026", PAUTA),                     # em tramitação
        _prop(3, PDL, "2/2026", "07/05/2026", PAUTA),                      # mesma data: 10 antes de 2
        _prop(4, PL, "204/2025", "11/11/2025", "", situacao="Transformado"),  # final: virou norma
        _prop(5, PL, "33/2024", "02/04/2024", ""),                         # local vazio: crawler revisita
        _prop(6, PL, "7/2026", "07/05/2026", "CCJ - Assinatura de Parecer"),  # sem tramitação gravada
    ]
    cols = list(props[0])
    conn.executemany(f"INSERT INTO proposituras ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                     [[p[c] for c in cols] for p in props])
    tramites = [
        # (prop_cod, ordem, data, local, despacho) — ordem 0 = andamento mais recente
        (1, 0, "20/02/2026 09:00:00", "DIVISÃO DE ARQUIVO PÚBLICO", "ARQUIVE-SE."),
        (1, 1, "10/02/2026 09:00:00", "DIRETORIA LEGISLATIVA", "PUBLICADO."),
        (2, 0, "13/10/2026 11:43:50", "DIRETORIA LEGISLATIVA  -  AGUARDANDO PAUTAÇÃO", DESPACHO_LONGO),
        (2, 1, "08/05/2026 10:00:00", "DIVISÃO DE APOIO ÀS COMISSÕES", "PARA PARECER."),
        (3, 0, "01/06/2026 08:00:00", "SECRETARIA LEGISLATIVA", "PARA PAUTAÇÃO."),  # ≠ local_atual
        (4, 0, "15/12/2025 08:00:00", "PROPOSITURA TRANSFORMADA", "LEI Nº 4.700."),
        (5, 0, "05/05/2024 08:00:00", "DIRETORIA LEGISLATIVA", ""),
    ]
    conn.executemany("INSERT INTO tramitacao (prop_cod, ordem, data, local, despacho, url_arquivo) "
                     "VALUES (?, ?, ?, ?, ?, '')", tramites)
    conn.execute("UPDATE proposituras SET data_situacao = (SELECT data FROM tramitacao t "
                 "WHERE t.prop_cod = proposituras.cod AND t.ordem = 0)")
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def indice(banco, tmp_path):
    saida = tmp_path / "saida"
    export.main(["--db", str(banco), "--saida", str(saida)])
    with open(saida / "proposituras-index.json", encoding="utf-8") as f:
        return json.load(f)


def test_ordem_por_data_mais_recente_e_numero_numerico(indice):
    ordem = [(p["subtipo"], p["numero"]) for p in indice]
    # 07/05/2026: PDL 10 antes de PDL 2 (numérico, não texto) e de PL 7 (mesma data, número menor)
    assert ordem == [(PDL, "10/2026"), (PL, "7/2026"), (PDL, "2/2026"), (PDL, "1/2026"),
                     (PL, "204/2025"), (PL, "33/2024")]
    pos = {p["numero"]: i for i, p in enumerate(indice)}
    assert pos["10/2026"] < pos["1/2026"]  # PDL 10 de 07/05 antes de PDL 1 de 03/02


def test_chaves_antigas_presentes_e_tram_em_todos(indice):
    for p in indice:
        assert list(p)[:len(CHAVES_ANTIGAS)] == CHAVES_ANTIGAS
        assert p["tram"] in (0, 1) and isinstance(p["tram"], int)
        assert set(p) - set(CHAVES_ANTIGAS) <= {"tram", "ua", "ual", "uad"}


def test_tram_segue_a_regra_do_crawler(indice):
    for p in indice:
        assert p["tram"] == int(not crawler.situacao_final(p["local_atual"], p["situacao"]))
    tram = {p["numero"]: p["tram"] for p in indice}
    assert tram == {"1/2026": 0, "10/2026": 1, "2/2026": 1, "204/2025": 0, "33/2024": 1, "7/2026": 1}


def test_ultimo_andamento(indice):
    por = {p["numero"]: p for p in indice}
    # ua e uad só nos em tramitação (sempre os dois); ual, além disso, só se acrescenta algo
    for p in indice:
        assert ("ua" in p) == ("uad" in p) == (p["tram"] == 1)
        assert "ual" not in p or p["tram"] == 1
    assert por["10/2026"]["ua"] == "2026-10-13"   # ISO, sem hora, do andamento de ordem 0
    assert por["7/2026"]["ua"] == ""              # em tramitação, sem tramitação gravada
    assert "ua" not in por["1/2026"]              # arquivado: sem ua
    # ual só quando difere de local_atual (sem caixa nem espaços) — o JS faz p.ual || p.local_atual
    assert "ual" not in por["10/2026"]            # "DIRETORIA LEGISLATIVA  -  AGUARDANDO PAUTAÇÃO" = local_atual
    assert por["2/2026"]["ual"] == "SECRETARIA LEGISLATIVA"
    assert por["33/2024"]["ual"] == "DIRETORIA LEGISLATIVA"   # local_atual vazio
    assert "ual" not in por["7/2026"]             # sem tramitação: nada a acrescentar
    assert por["2/2026"]["uad"] == "PARA PAUTAÇÃO."
    assert por["33/2024"]["uad"] == "" and por["7/2026"]["uad"] == ""
    uad = por["10/2026"]["uad"]
    assert len(uad) <= 80 and uad.endswith("…") and "\n" not in uad
    colapsado = " ".join(DESPACHO_LONGO.split())
    corpo = uad[:-1]
    assert colapsado.startswith(corpo)
    assert not colapsado[len(corpo)].isalnum()   # cortou numa fronteira de palavra


@pytest.mark.parametrize("texto,esperado", [
    ("", ""),
    (None, ""),
    ("  A\n\nB  ", "A B"),
    ("X" * 80, "X" * 80),                          # no limite: intacto
    ("PALAVRA " * 20, ("PALAVRA " * 10).strip() + "…"),   # 10 palavras = 79 + "…"
    ("PALAVRAS " * 20, ("PALAVRAS " * 8).strip() + "…"),   # a 9ª não cabe inteira
    ("Y" * 130, "Y" * 79 + "…"),                   # sem espaço: corte seco
], ids=["vazio", "none", "espacos", "no-limite", "fim-de-palavra", "meio-de-palavra", "sem-espaco"])
def test_resumir(texto, esperado):
    r = export.resumir(texto)
    assert r == esperado and len(r) <= 80


def test_saida_nao_toca_o_indice_versionado(banco, tmp_path):
    antes = os.path.getmtime(export.JSON_PATH) if os.path.exists(export.JSON_PATH) else None
    saida = tmp_path / "out"
    export.main(["--db", str(banco), "--saida", str(saida)])
    assert sorted(os.listdir(saida)) == ["proposituras-index.json", "proposituras.csv", "proposituras.xlsx"]
    depois = os.path.getmtime(export.JSON_PATH) if os.path.exists(export.JSON_PATH) else None
    assert antes == depois
    with open(saida / "proposituras-index.json", encoding="utf-8") as f:
        assert re.fullmatch(r"\[\{.*\}\]", f.read(), re.S)  # compacto, uma linha
