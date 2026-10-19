"""Calendário de pagamentos e caminho do dinheiro (M8, 2026-10): dados/calendario.json e
dados/fluxo.json saem das mesmas linhas de pagamento da movimentação e conservam a série
mensal e o pago de cada ano; o verificar.py confere."""
import json
import random
import sqlite3
import uuid

import crawler
import export
import verificar

IPREV = ("INSTITUTO DE PREVIDÊNCIA SOCIAL DOS SERVIDORES PÚBLICOS MUNICIPAIS DE SANTOS", "08.717.299/0001-01")
ACME = "12.345.678/0001-90"


def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(crawler._schema())
    conn.row_factory = sqlite3.Row
    return conn


def pag(conn, ano, mes, dia, valor, **kw):
    base = {"unidade_gestora": "PREFEITURA MUNICIPAL DE SANTOS", "data": f"{ano}-{mes:02d}-{dia:02d}",
            "especie": "Original", "empenho": "", "pagamento": uuid.uuid4().hex[:8],
            "elemento_despesa": "339039 - OUTROS SERVIÇOS", "subtitulo": "", "funcao": "10 - SAÚDE",
            "subfuncao": "301 - Atenção Básica", "programa": "P", "fonte_recurso": "01-1100000 - GERAL",
            "grupo_despesa": "33 - OUTRAS DESPESAS CORRENTES", "documento_favorecido": ACME,
            "nome_favorecido": "ACME SERVIÇOS LTDA", "tipo_pagamento": "Orçamentária"}
    base.update(kw)
    base.update({"ano": ano, "mes": mes, "valor": valor, "hash": uuid.uuid4().hex})
    cols = ["hash"] + crawler._cols("pagamentos")
    conn.execute(f"INSERT INTO pagamentos ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 [base.get(c) for c in cols])


def cenario():
    """Dois anos; um CNPJ com duas grafias; um ente público (IPREV); extra-orçamentário com e
    sem função; uma anulação; um pagamento com a data de outro ano na partição de abr/2025."""
    conn = db()
    pag(conn, 2025, 3, 3, 1_000.0)
    pag(conn, 2025, 3, 3, 500.0, nome_favorecido="ACME SERVICOS LTDA")       # outra grafia, mesmo CNPJ
    pag(conn, 2025, 3, 3, 250.0)
    pag(conn, 2025, 3, 4, -200.0, especie="Anulação")
    pag(conn, 2025, 3, 4, 3_000.0, nome_favorecido=IPREV[0], documento_favorecido=IPREV[1],
        funcao="09 - PREVIDÊNCIA SOCIAL", fonte_recurso="04-6050000 - RPPS")
    pag(conn, 2025, 4, 10, 800.0, nome_favorecido="BETA OBRAS LTDA", documento_favorecido="22.222.222/0001-22",
        funcao="15 - URBANISMO", fonte_recurso="05-3000027 - MAC")
    pag(conn, 2025, 4, 10, 120.0, funcao="", tipo_pagamento="Extra Orçamentário", fonte_recurso="1100000 - GERAL")
    pag(conn, 2025, 4, 10, 30.0, data="2024-04-25", tipo_pagamento="Extra Orçamentário")   # data de outro ano
    pag(conn, 2026, 1, 5, 400.0, nome_favorecido="GAMA LTDA", documento_favorecido="33.333.333/0001-33",
        fonte_recurso="91-3100000 - SAÚDE - GERAL")
    pag(conn, 2026, 1, 5, 2_000.0, nome_favorecido=IPREV[0], documento_favorecido=IPREV[1],
        funcao="09 - PREVIDÊNCIA SOCIAL", fonte_recurso="04-6050000 - RPPS")
    pag(conn, 2026, 1, 6, 600.0, fonte_recurso="02-2610000 - FUNDEB", funcao="12 - EDUCAÇÃO")
    conn.commit()
    return conn


def montar(conn):
    ident = export.preparar_identidades(conn)
    idx = export.agregados(conn, ident)
    idx["execucao"] = export.execucao_agregada(conn)
    idx["entes_publicos"] = sorted(k for k, o in ident.items() if export.eh_ente_publico(o["nome"]))
    return ident, idx, export.montar_movimento(conn)


def test_dia_fica_no_mes_da_particao():
    r = {"_periodo": 202502, "data": "2024-02-29"}
    assert export._dia_pagamento(r) == "2025-02-28"            # 29/02 não existe em 2025
    assert export._dia_pagamento({"_periodo": 202504, "data": "2024-04-25"}) == "2025-04-25"
    assert export._dia_pagamento({"_periodo": 202512, "data": ""}) == "2025-12-01"
    assert export._dia_pagamento({"_periodo": 202601, "data": "2026-01-31"}) == "2026-01-31"


def test_calendario_conserva_com_a_serie_e_os_pagamentos():
    _, idx, mov = montar(cenario())
    cal = export.calendario_pagamentos(mov)
    assert cal["campos"] == ["dia", "pago", "n", "anulacoes"]
    dias = [l[0] for l in cal["linhas"]]
    assert dias == sorted(set(dias)) and cal["ate"] == "2026-01-06"
    por_mes = {}
    for dia, pago, _, _ in cal["linhas"]:
        por_mes[dia[:7]] = round(por_mes.get(dia[:7], 0) + pago, 2)
    assert por_mes == {f"{s['ano']}-{s['mes']:02d}": s["valor"] for s in idx["series_mensais"]}
    assert sum(l[2] for l in cal["linhas"]) == idx["totais"]["pagamentos"] == 11
    d = {l[0]: l for l in cal["linhas"]}
    assert d["2025-03-04"] == ["2025-03-04", 2_800.0, 2, 1]      # pagamento − anulação; 1 anulação
    assert d["2025-04-25"][1:3] == [30.0, 1]                      # data de 2024 → mês da partição
    assert cal["redatados"] == {"n": 1, "pago": 30.0}


def test_caminho_sem_extra_e_niveis_conservam():
    ident, idx, mov = montar(cenario())
    fx = export.fluxo_dinheiro(mov, ident, idx)
    assert sorted(fx["anos"]) == ["2025", "2026"]
    a25 = fx["anos"]["2025"]
    e25 = idx["execucao"]["por_ano"]["2025"]
    assert a25["extra"] == e25["extra"] == 150.0
    assert a25["todos"]["total"] == round(e25["pago"] - e25["extra"], 2) == 5_350.0
    for ano, a in fx["anos"].items():
        for var in ("todos", "privados"):
            s = a[var]
            for nivel in (0, 1, 2):
                assert round(sum(n["valor"] for n in s["nos"] if n["nivel"] == nivel), 2) == s["total"], (ano, var, nivel)
            ids = {n["id"]: n for n in s["nos"]}
            for no in s["nos"]:
                sai = round(sum(v for de, _, v in s["ligacoes"] if de == no["id"]), 2)
                chega = round(sum(v for _, para, v in s["ligacoes"] if para == no["id"]), 2)
                assert no["nivel"] == 2 or sai == no["valor"], no
                assert no["nivel"] == 0 or chega == no["valor"], no
            assert all(ids[b]["nivel"] == ids[a_]["nivel"] + 1 for a_, b, _ in s["ligacoes"])
    # o extra-orçamentário (com e sem função) não vira nó nem ligação
    nomes = [n["nome"] for a in fx["anos"].values() for s in a.values() if isinstance(s, dict) for n in s["nos"]]
    assert "(sem função)" not in nomes and not any("Extra" in n for n in nomes)
    grupos = {n["id"]: n for n in a25["todos"]["nos"] if n["nivel"] == 0}
    assert grupos["g:01"]["nome"] == "Tesouro municipal" and grupos["g:01"]["fontes"][0] == ["01-1100000 - GERAL", 1_550.0]
    assert "g:9x" in {n["id"] for n in fx["anos"]["2026"]["todos"]["nos"]}   # 91 = exercícios anteriores


def test_caminho_demais_e_demais_de_um_so(monkeypatch):
    monkeypatch.setattr(export, "FLUXO_TOPOS", (1, 1, 2))
    linhas = [("01", "10", "10 - SAÚDE", "cnpj:1", "01-1 - A", 500.0), ("02", "10", "10 - SAÚDE", "cnpj:2", "02-1 - B", 300.0),
              ("05", "12", "12 - EDUCAÇÃO", "cnpj:3", "05-1 - C", 200.0), ("05", "12", "12 - EDUCAÇÃO", "cnpj:4", "05-1 - C", 100.0)]
    s = export._sankey(linhas, {}, set(), set())
    por_nivel = {k: [n for n in s["nos"] if n["nivel"] == k] for k in (0, 1, 2)}
    assert [n["id"] for n in por_nivel[0]] == ["g:01", "g:demais"]
    assert por_nivel[0][1]["inclui"] == ["Transferências estaduais", "Transferências federais"]
    assert por_nivel[0][1]["valor"] == 600.0
    # sobra UMA função fora do topo: aparece com o próprio nome, sem "Demais funções"
    assert [n["id"] for n in por_nivel[1]] == ["f:10", "f:12"]
    v = por_nivel[2]
    assert [n["id"] for n in v][-1] == "v:demais" and v[-1]["qtd"] == 2 and v[-1]["valor"] == 300.0
    assert ["g:demais", "f:10", 300.0] in s["ligacoes"] and ["f:12", "v:demais", 300.0] in s["ligacoes"]
    assert s["total"] == 1_100.0


def test_privados_tira_so_o_ente_publico():
    ident, idx, mov = montar(cenario())
    fx = export.fluxo_dinheiro(mov, ident, idx)
    todos, priv = fx["anos"]["2025"]["todos"], fx["anos"]["2025"]["privados"]
    iprev = next(n for n in todos["nos"] if n["nivel"] == 2 and n["nome"].startswith("INSTITUTO DE PREVID"))
    assert iprev.get("ente_publico") is True and iprev["valor"] == 3_000.0
    assert not [n for n in priv["nos"] if "PREVID" in n["nome"] or n.get("ente_publico")]
    assert priv["total"] == round(todos["total"] - iprev["valor"], 2) == 2_350.0
    assert "f:09" not in {n["id"] for n in priv["nos"]}           # previdência só tinha o IPREV


def test_grafias_do_mesmo_cnpj_viram_um_no_com_link_do_raiox():
    ident, idx, mov = montar(cenario())
    sem_dossie = export.fluxo_dinheiro(mov, ident, {"entes_publicos": idx["entes_publicos"], "top_favorecidos": []})
    acme = [n for n in sem_dossie["anos"]["2025"]["todos"]["nos"] if n["id"] == "v:12345678000190"]
    assert len(acme) == 1 and acme[0]["valor"] == 1_550.0          # 1.000 + 500 + 250 − 200 (anulação)
    assert acme[0]["nome"] == "ACME SERVIÇOS LTDA"                  # a grafia com mais lançamentos
    assert acme[0]["link"].startswith("./favorecido.html?doc=12.345.678/0001-90&nome=ACME")
    com_dossie = export.fluxo_dinheiro(mov, ident, idx)            # top_favorecidos do índice = dossiês
    acme = next(n for n in com_dossie["anos"]["2025"]["todos"]["nos"] if n["id"] == "v:12345678000190")
    assert acme["link"] == "./favorecido.html?f=12345678000190"


def test_mesmos_dados_mesmos_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "DADOS_DIR", str(tmp_path))
    ident, idx, mov = montar(cenario())
    man = export.exportar_graficos_movimento(mov, ident, idx)
    antes = {k: (tmp_path / f"{k}.json").read_bytes() for k in ("calendario", "fluxo")}
    assert {k: m["bytes"] for k, m in man.items()} == {k: len(b) for k, b in antes.items()}
    assert man["calendario"]["arquivo"] == "despesas/dados/calendario.json"
    embaralhado = mov[:]
    random.Random(7).shuffle(embaralhado)                          # outra ordem das linhas, mesmo dado
    export.exportar_graficos_movimento(embaralhado, ident, idx)
    assert {k: (tmp_path / f"{k}.json").read_bytes() for k in ("calendario", "fluxo")} == antes
    assert b"atualizado_em" not in antes["fluxo"] + antes["calendario"]


def test_verificar_aceita_o_export_e_aponta_divergencia(tmp_path, monkeypatch):
    dados = tmp_path / "despesas" / "dados"
    monkeypatch.setattr(export, "DADOS_DIR", str(dados))
    ident, idx, mov = montar(cenario())
    idx["dados_graficos"] = export.exportar_graficos_movimento(mov, ident, idx)
    assert verificar.verificar_calendario(str(tmp_path), idx) == []
    assert verificar.verificar_fluxo(str(tmp_path), idx) == []

    cal = json.loads((dados / "calendario.json").read_text(encoding="utf-8"))
    cal["linhas"][0][1] += 10.0                                     # um dia a mais que a série
    (dados / "calendario.json").write_text(json.dumps(cal), encoding="utf-8")
    falhas = verificar.verificar_calendario(str(tmp_path), idx)
    assert any("calendário 2025-03" in f for f in falhas) and any("bytes" in f for f in falhas)

    fx = json.loads((dados / "fluxo.json").read_text(encoding="utf-8"))
    fx["anos"]["2025"]["todos"]["ligacoes"].pop()                   # some uma ligação
    fx["anos"]["2025"]["privados"]["nos"].append({"id": "v:08717299000101", "nivel": 2, "nome": IPREV[0], "valor": 0})
    (dados / "fluxo.json").write_text(json.dumps(fx), encoding="utf-8")
    falhas = verificar.verificar_fluxo(str(tmp_path), idx)
    assert any("caminho 2025 (todos)" in f and "recebe" in f for f in falhas)
    assert any("ente público entre os privados" in f for f in falhas)

    sem = {k: v for k, v in idx.items() if k != "dados_graficos"}
    assert "dados_graficos.calendario" in verificar.verificar_calendario(str(tmp_path), sem)[0]
