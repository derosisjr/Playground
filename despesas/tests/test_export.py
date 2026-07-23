import json
import os
import sqlite3
import uuid

import crawler
import export


# ── Base sintética ────────────────────────────────────────────────────────────
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(crawler._schema())
    conn.row_factory = sqlite3.Row
    return conn


def add(conn, tabela, ano, mes, valor, **kw):
    base = {
        "unidade_gestora": "PREFEITURA MUNICIPAL DE SANTOS",
        "data": f"{ano}-{mes:02d}-10",
        "especie": "Original",
        "empenho": "0000001/%d" % ano,
        "elemento_despesa": "339039 - OUTROS SERVIÇOS",
        "subtitulo": "",
        "funcao": "10 - SAÚDE",
        "subfuncao": "301 - Atenção Básica",
        "programa": "Programa X",
        "fonte_recurso": "TESOURO",
        "grupo_despesa": "33 - OUTRAS DESPESAS CORRENTES",
        "documento_favorecido": "12.345.678/0001-90",
        "nome_favorecido": "ACME SERVIÇOS LTDA",
    }
    base.update(kw)
    base.update({"ano": ano, "mes": mes, "valor": valor, "hash": uuid.uuid4().hex})
    cols = ["hash"] + crawler._cols(tabela)
    conn.execute(f"INSERT INTO {tabela} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 [base.get(c) for c in cols])
    conn.commit()


def cenario_execucao():
    """2025 íntegro (empenho E1 com anulação, liquidação e pagamento parciais,
    + restos a pagar e extra-orçamentário); 2026 com base de empenhos furada
    (pago casado > empenhado)."""
    conn = db()
    e1 = {"empenho": "0000100/2025"}
    add(conn, "empenhos", 2025, 1, 100_000.0, **e1)
    add(conn, "empenhos", 2025, 2, -20_000.0, especie="Anulação", **e1)
    add(conn, "liquidacoes", 2025, 3, 60_000.0, **e1)
    add(conn, "pagamentos", 2025, 3, 50_000.0, **e1)
    # pagamento de empenho de exercício anterior (fora da base) → restos a pagar
    add(conn, "pagamentos", 2025, 4, 10_000.0, empenho="0000009/2024")
    # pagamento sem empenho → extra-orçamentário
    add(conn, "pagamentos", 2025, 4, 5_000.0, empenho="")
    # 2026: só um reforço na base, mas pagamento casado maior → base incompleta
    e2 = {"empenho": "0000200/2026"}
    add(conn, "empenhos", 2026, 1, 10_000.0, **e2)
    add(conn, "pagamentos", 2026, 2, 15_000.0, **e2)
    return conn


# ── Execução agregada (tríade) ────────────────────────────────────────────────
def test_execucao_serie_liquida_anulacoes():
    conn = cenario_execucao()
    exe = export.execucao_agregada(conn)
    jan = next(l for l in exe["serie"] if (l["ano"], l["mes"]) == (2025, 1))
    fev = next(l for l in exe["serie"] if (l["ano"], l["mes"]) == (2025, 2))
    assert jan["empenhado"] == 100_000.0
    assert fev["empenhado"] == -20_000.0     # anulação vem negativa da API
    a25 = exe["por_ano"]["2025"]
    assert a25["empenhado"] == 80_000.0      # líquido
    assert a25["pago"] == 65_000.0
    assert a25["restos"] == 10_000.0
    assert a25["extra"] == 5_000.0


def test_execucao_taxas_so_com_base_integra():
    conn = cenario_execucao()
    exe = export.execucao_agregada(conn)
    a25, a26 = exe["por_ano"]["2025"], exe["por_ano"]["2026"]
    assert a25["taxa_liquidacao"] == 75.0    # 60k / 80k
    assert a25["taxa_pagamento"] == 62.5     # 50k / 80k
    assert "taxa_pagamento" not in a26       # pago casado (15k) > empenhado (10k)
    assert a26["empenho_incompleto"] is True


def test_montar_execucao_classifica_tipos():
    conn = cenario_execucao()
    tipos = {r["tipo"] for r in export.montar_execucao(conn)}
    assert {"Empenho", "Restos a pagar", "Extra-orçamentário"} <= tipos


def test_resumo_narrativo_cita_taxa_e_restos():
    conn = cenario_execucao()
    indice = export.agregados(conn)
    indice["execucao"] = export.execucao_agregada(conn)
    indice["alertas"] = []
    resumo = export.resumo_narrativo(conn, indice)
    # a referência é 2026 (último mês da série): ano sem taxa → nada de % inventado
    assert "%" not in resumo["texto"].split("Do empenhado")[-1] or "pago" in resumo["texto"]


# ── Alertas por regras ────────────────────────────────────────────────────────
def test_alerta_fracionamento():
    conn = db()
    for mes in (1, 2, 3, 4):   # 4 empenhos logo abaixo do limite de dispensa
        add(conn, "empenhos", 2025, mes, 50_000.0,
            empenho=f"00000{mes}/2025", nome_favorecido="FRACIONA LTDA")
    tipos = [a["tipo"] for a in export.alertas(conn)]
    assert "fracionamento" in tipos

    conn2 = db()
    for mes in (1, 2, 3):      # só 3 → não dispara
        add(conn2, "empenhos", 2025, mes, 50_000.0,
            empenho=f"00000{mes}/2025", nome_favorecido="FRACIONA LTDA")
    assert "fracionamento" not in [a["tipo"] for a in export.alertas(conn2)]


def test_alerta_favorecido_novo_exclui_ente_publico():
    conn = db()
    # 12 meses de histórico p/ ancorar a janela de "novo"
    for mes in range(1, 13):
        add(conn, "pagamentos", 2025, mes, 1_000.0, nome_favorecido="ANTIGA LTDA")
    add(conn, "pagamentos", 2025, 12, 2_000_000.0, nome_favorecido="NOVA EMPRESA LTDA")
    add(conn, "pagamentos", 2025, 12, 2_000_000.0, nome_favorecido="PREFEITURA DE CUBATÃO")
    novos = [a["titulo"] for a in export.alertas(conn) if a["tipo"] == "favorecido_novo"]
    assert any("NOVA EMPRESA" in t for t in novos)
    assert not any("PREFEITURA" in t for t in novos)


def test_alerta_pico_favorecido_zscore():
    conn = db()
    # 11 meses estáveis (~100 mil) + 1 mês explosivo (2 mi) p/ o mesmo favorecido
    for mes in range(1, 12):
        add(conn, "pagamentos", 2025, mes, 100_000.0, nome_favorecido="OSCILANTE LTDA")
    add(conn, "pagamentos", 2025, 12, 2_000_000.0, nome_favorecido="OSCILANTE LTDA")
    # ente público com o mesmo padrão NÃO dispara
    for mes in range(1, 12):
        add(conn, "pagamentos", 2025, mes, 100_000.0, nome_favorecido="PREFEITURA DE CUBATÃO")
    add(conn, "pagamentos", 2025, 12, 2_000_000.0, nome_favorecido="PREFEITURA DE CUBATÃO")
    picos = [a for a in export.alertas(conn) if a["tipo"] == "pico_favorecido"]
    assert any("OSCILANTE" in a["titulo"] and "2025-12" in a["titulo"] for a in picos)
    assert not any("PREFEITURA" in a["titulo"] for a in picos)


def test_alerta_pico_favorecido_ignora_serie_estavel():
    conn = db()
    for mes in range(1, 13):   # série alta porém estável → sem pico
        add(conn, "pagamentos", 2025, mes, 2_000_000.0, nome_favorecido="ESTAVEL LTDA")
    assert not [a for a in export.alertas(conn) if a["tipo"] == "pico_favorecido"]


def test_alerta_pico_elemento_ignora_sazonais():
    conn = db()
    # 13º explode em dezembro TODO ano — pico de calendário, não achado fiscal
    for mes in range(1, 12):
        add(conn, "pagamentos", 2025, mes, 500_000.0,
            elemento_despesa="319013 - 13º SALÁRIO")
    add(conn, "pagamentos", 2025, 12, 40_000_000.0,
        elemento_despesa="319013 - 13º SALÁRIO")
    assert not [a for a in export.alertas(conn) if a["tipo"] == "pico_elemento"]


def test_alerta_pico_elemento_zscore():
    conn = db()
    for mes in range(1, 12):
        add(conn, "pagamentos", 2025, mes, 500_000.0,
            elemento_despesa="339030 - MATERIAL DE CONSUMO")
    add(conn, "pagamentos", 2025, 12, 12_000_000.0,
        elemento_despesa="339030 - MATERIAL DE CONSUMO")
    picos = [a for a in export.alertas(conn) if a["tipo"] == "pico_elemento"]
    assert any("MATERIAL DE CONSUMO" in a["titulo"] for a in picos)
    assert picos[0]["filtro"] == {"elemento": "339030 - MATERIAL DE CONSUMO"}


# ── Árvore e índices leves ────────────────────────────────────────────────────
def test_exportar_arvore_agrupa_cauda(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "ARVORE_PATH", str(tmp_path / "arvore.json"))
    conn = db()
    for i in range(export.TOP_ELEM_ARVORE + 3):   # 13 elementos na mesma subfunção
        add(conn, "pagamentos", 2025, 1, 1_000.0 * (i + 1),
            elemento_despesa=f"3390{i:02d} - ELEMENTO {i}")
    export.exportar_arvore(conn, {"atualizado_em": "t", "totais": {"geral": 1}})
    d = json.load(open(tmp_path / "arvore.json", encoding="utf-8"))
    folhas = d["arvore"][0]["f"][0]["f"]
    assert len(folhas) == export.TOP_ELEM_ARVORE + 1
    assert folhas[-1]["n"] == "Demais elementos"
    soma = round(sum(x["v"] for x in folhas), 2)
    assert soma == d["arvore"][0]["f"][0]["v"]    # nada se perde no agrupamento


def test_exportar_estagios(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "ESTAGIOS_DIR", str(tmp_path))
    conn = cenario_execucao()
    rows = export.montar_execucao(conn)
    n = export.exportar_estagios(conn, rows)
    assert n >= 2

    # partição: E1 (empenho jan/2025) vive no arquivo do período do empenho
    jan = json.load(open(tmp_path / "2025-01.json", encoding="utf-8"))
    k = "PREFEITURA MUNICIPAL DE SANTOS|0000100/2025"
    assert k in jan
    # espécie omitida quando "Original" (tupla de 4); explícita nas anulações
    fases = [(e[0], e[3], e[4] if len(e) > 4 else "Original") for e in jan[k]["e"]]
    assert ("E", -20_000.0, "Anulação") in fases
    assert ("E", 100_000.0, "Original") in fases
    assert ("L", 60_000.0, "Original") in fases
    assert ("P", 50_000.0, "Original") in fases
    assert all(len(e) == 4 for e in jan[k]["e"] if (len(e) < 5))  # compactação ativa

    # restos a pagar: a chave do empenho antigo vive no mês do PAGAMENTO,
    # com os próprios pagamentos como eventos
    abr = json.load(open(tmp_path / "2025-04.json", encoding="utf-8"))
    kr = "PREFEITURA MUNICIPAL DE SANTOS|0000009/2024"
    assert kr in abr
    assert [e[0] for e in abr[kr]["e"]] == ["P"]

    # extra-orçamentário (sem nº de empenho) fica FORA dos estágios
    for arq in tmp_path.glob("*.json"):
        d = json.load(open(arq, encoding="utf-8"))
        assert not any(ch.endswith("|") for ch in d)


def test_exportar_estagios_tipo_empenho(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "ESTAGIOS_DIR", str(tmp_path))
    conn = db()
    add(conn, "empenhos", 2025, 1, 10_000.0, empenho="0000300/2025", tipo_empenho="Global")
    rows = export.montar_execucao(conn)
    export.exportar_estagios(conn, rows)
    d = json.load(open(tmp_path / "2025-01.json", encoding="utf-8"))
    assert d["PREFEITURA MUNICIPAL DE SANTOS|0000300/2025"]["t"] == "Global"


def test_indices_leves(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "DADOS_DIR", str(tmp_path))
    conn = cenario_execucao()
    add(conn, "pagamentos", 2025, 5, 90_000.0, empenho="",
        documento_favorecido="***.111.222-**", nome_favorecido="FULANO DE TAL",
        elemento_despesa="339036 - PESSOA FÍSICA")
    rows = export.montar_execucao(conn)
    export.exportar_indices_leves(rows)

    el = json.load(open(tmp_path / "elementos.json", encoding="utf-8"))
    assert "339036 - PESSOA FÍSICA" in el["pf"]
    assert "339036 - PESSOA FÍSICA" not in el["pj"]

    pf = json.load(open(tmp_path / "pf-resumo.json", encoding="utf-8"))
    assert pf["itens"][0]["nome"] == "FULANO DE TAL"
    assert pf["itens"][0]["valor"] == 90_000.0

    idx = json.load(open(tmp_path / "indice-favorecidos.json", encoding="utf-8"))
    # PF pontual entra no índice (chave = dígitos do CPF mascarado) com seu mês
    assert idx["fav"]["111222"] == [202505]
    # ACME aparece em quase todos os meses → fica FORA (baixar tudo equivale;
    # chave ausente = fallback para todos os meses no painel)
    assert "12345678000190" not in idx["fav"]
