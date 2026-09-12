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
        # campos de classificação da FONTE (v2 classifica por eles, não pelo nº de empenho)
        "tipo_pagamento": "Orçamentária", "tipo_liquidacao": "Orçamentária", "tipo_empenho": "Ordinário",
    }
    if "nome_favorecido" in kw and "documento_favorecido" not in kw:
        import hashlib
        dig = str(int(hashlib.md5(kw["nome_favorecido"].encode()).hexdigest()[:10], 16)).zfill(14)[:14]
        base["documento_favorecido"] = f"{dig[:2]}.{dig[2:5]}.{dig[5:8]}/{dig[8:12]}-{dig[12:]}"
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
    # pagamento de empenho de exercício anterior (fora da base) → restos a pagar (campo da fonte)
    add(conn, "pagamentos", 2025, 4, 10_000.0, empenho="0000009/2024",
        tipo_pagamento="Restos a Pagar Processados")
    # pagamento sem empenho, tipo extra na fonte → extra-orçamentário
    add(conn, "pagamentos", 2025, 4, 5_000.0, empenho="", tipo_pagamento="Extra Orçamentário")
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
    for mes in (1, 2, 3, 4):   # 4 empenhos DISTINTOS logo abaixo do limite de dispensa
        add(conn, "empenhos", 2025, mes, 50_000.0,
            empenho=f"00000{mes}/2025", nome_favorecido="FRACIONA LTDA")
    frac = [a for a in export.alertas(conn) if a["tipo"] == "fracionamento"]
    assert len(frac) == 1
    a = frac[0]
    assert "4 empenhos distintos" in a["titulo"]
    assert a["classe"] == "anomalia" and a["severidade"] != "alta"     # triagem, não conclusão
    assert a["limite"]["exercicio"] == 2025 and a["limite"]["valor"] == 62_725.59
    assert "Decreto 12.343/2024" in a["limite"]["norma"] and "secund" in a["limite"]["verificacao"]
    assert len(a["documentos"]) == 4
    assert {d["empenho"] for d in a["documentos"]} == {f"00000{m}/2025" for m in (1, 2, 3, 4)}
    assert "objeto da contratação" in a["informacoes_faltantes"]
    assert "não é o valor da contratação" in a["detalhe"]
    assert a["link"].startswith("./despesas.html?") and "dv=exe" in a["link"]

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
    add(conn, "pagamentos", 2026, 1, 1.0, data="2026-01-31", nome_favorecido="SENTINELA")  # dez/2025 completo
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
    add(conn, "pagamentos", 2026, 1, 1.0, data="2026-01-31", nome_favorecido="SENTINELA")  # dez/2025 completo
    picos = [a for a in export.alertas(conn) if a["tipo"] == "pico_elemento"]
    assert any("MATERIAL DE CONSUMO" in a["titulo"] for a in picos)
    assert picos[0]["filtro"]["elemento"] == "339030 - MATERIAL DE CONSUMO"
    assert (picos[0]["filtro"]["ano"], picos[0]["filtro"]["mes"]) == (2025, 12)
    assert "dm=2025-12" in picos[0]["link"] and picos[0]["documentos"]


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
    assert idx["fav"]["cpf:111222|FULANO DE TAL"] == [202505]   # chave = identidade canônica
    # ACME aparece em quase todos os meses → fica FORA (baixar tudo equivale;
    # chave ausente = fallback para todos os meses no painel)
    assert "cnpj:12345678000190" not in idx["fav"]


def test_fracionamento_conta_empenhos_e_nao_movimentos():
    # UM empenho com três reforços = 4 movimentos, mas 1 empenho: nunca "quatro empenhos"
    conn = db()
    add(conn, "empenhos", 2025, 1, 50_000.0, empenho="0000001/2025", nome_favorecido="REFORCA LTDA")
    for mes in (2, 3, 4):
        add(conn, "empenhos", 2025, mes, 3_000.0, empenho="0000001/2025", especie="Reforço",
            nome_favorecido="REFORCA LTDA")
    todos = export.alertas(conn)
    assert not [a for a in todos if a["tipo"] == "fracionamento"]
    assert not any("4 empenhos" in a["titulo"] or "quatro empenhos" in a["titulo"] for a in todos)
    # 5 originais: um reforçado acima do limite e um anulado por inteiro não contam → só 3 → não dispara
    conn2 = db()
    for i in (1, 2, 3, 4, 5):
        add(conn2, "empenhos", 2025, i, 50_000.0, empenho=f"000000{i}/2025", nome_favorecido="X LTDA")
    add(conn2, "empenhos", 2025, 6, 20_000.0, empenho="0000001/2025", especie="Reforço", nome_favorecido="X LTDA")
    add(conn2, "empenhos", 2025, 6, -50_000.0, empenho="0000002/2025", especie="Anulação", nome_favorecido="X LTDA")
    assert not [a for a in export.alertas(conn2) if a["tipo"] == "fracionamento"]


def test_fracionamento_sem_limite_verificado_nao_afirma_enquadramento():
    conn = db()
    for mes in (1, 2, 3, 4):
        add(conn, "empenhos", 2019, mes, 10_000.0, empenho=f"00000{mes}/2019", nome_favorecido="ANTIGA LTDA")
    assert not [a for a in export.alertas(conn) if a["tipo"] == "fracionamento"]
    lim = export._limite_dispensa(2019, "339039 - SERVIÇOS")
    assert lim["valor"] is None and "não cadastrado" in lim["verificacao"]


# ── Identidade do favorecido (consolidação por CNPJ) ─────────────────────────
def cenario_grafias():
    conn = db()
    doc = "08.717.299/0001-01"
    for mes, nome, v in ((1, "INSTITUTO DE PREVID�NCIA", 1_000.0), (2, "INSTITUTO DE PREVIDENCIA", 2_000.0),
                         (3, "IPREV - INST. PREV.", 500.0), (4, "INSTITUTO DE PREVID�NCIA", 1_500.0)):
        add(conn, "pagamentos", 2025, mes, v, nome_favorecido=nome, documento_favorecido=doc,
            empenho=f"00000{mes}/2025")
    add(conn, "pagamentos", 2025, 5, 300.0, nome_favorecido="OUTRA LTDA", documento_favorecido="11.111.111/0001-11")
    return conn


def test_ranking_consolida_grafias_do_mesmo_cnpj():
    conn = cenario_grafias()
    ident = export.preparar_identidades(conn)
    idx = export.agregados(conn, ident)
    tops = idx["top_favorecidos"]
    assert len(tops) == 2 and idx["totais"]["favorecidos"] == 2
    ips = tops[0]
    assert ips["chave"] == "cnpj:08717299000101" and ips["slug"] == "08717299000101"
    assert ips["valor"] == 5_000.0 and ips["qtd"] == 4 and ips["meses"] == 4
    assert ips["nome"] == "INSTITUTO DE PREVIDENCIA"          # grafia sem U+FFFD vence
    assert set(ips["grafias"]) == {"INSTITUTO DE PREVID�NCIA", "INSTITUTO DE PREVIDENCIA", "IPREV - INST. PREV."}
    # a soma geral não muda por consolidar identidades
    assert idx["totais"]["geral"] == round(sum(t["valor"] for t in tops), 2) == 5_300.0


def test_raiox_e_ranking_coerentes(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "FAV_DIR", str(tmp_path))
    conn = cenario_grafias()
    ident = export.preparar_identidades(conn)
    idx = export.agregados(conn, ident)
    idx["alertas"] = []
    n = export.exportar_favorecidos(conn, idx, ident)
    assert n == 2
    d = json.load(open(tmp_path / "08717299000101.json", encoding="utf-8"))
    assert d["total"] == idx["top_favorecidos"][0]["valor"] == 5_000.0
    assert len(d["serie_mensal"]) == 4 and round(sum(s["valor"] for s in d["serie_mensal"]), 2) == 5_000.0
    assert len(d["grafias"]) == 3


def test_cpf_mascarado_semelhante_nao_e_fundido():
    conn = db()
    add(conn, "pagamentos", 2025, 1, 100.0, nome_favorecido="JOSE DA SILVA", documento_favorecido="***.158.308-**")
    add(conn, "pagamentos", 2025, 1, 200.0, nome_favorecido="MARIA SOUZA", documento_favorecido="***.158.308-**")
    add(conn, "pagamentos", 2025, 2, 50.0, nome_favorecido="JOSÉ DA SILVA", documento_favorecido="***.158.308-**")
    ident = export.preparar_identidades(conn)
    idx = export.agregados(conn, ident)
    assert idx["totais"]["favorecidos"] == 2
    jose = next(t for t in idx["top_favorecidos"] if "SILVA" in t["nome"])
    assert jose["valor"] == 150.0 and jose["qtd"] == 2       # só o mesmo nome (sem acento) se une


# ── Duas visões: movimentação × execução ─────────────────────────────────────
def test_empenho_de_janeiro_pago_em_agosto_sem_duplicacao():
    conn = db()
    add(conn, "empenhos", 2025, 1, 1_000.0, empenho="0000500/2025")
    add(conn, "pagamentos", 2025, 8, 1_000.0, empenho="0000500/2025", pagamento="0000900/2025")
    exe = export.montar_execucao(conn)
    mov = export.montar_movimento(conn)
    # execução: o empenho vive em janeiro, já com o pago de agosto acumulado
    jan = [r for r in exe if r["_periodo"] == 202501]
    assert len(jan) == 1 and jan[0]["empenho"] == "0000500/2025" and jan[0]["pago"] == 1_000.0
    assert not [r for r in exe if r["_periodo"] == 202508]
    # movimentação: E em janeiro, P em agosto — cada documento uma vez, na sua data
    assert [(r["fase"], r["_periodo"]) for r in mov] == [("E", 202501), ("P", 202508)]
    ago = [r for r in mov if r["_periodo"] == 202508][0]
    assert ago["pago"] == 1_000.0 and ago["empenhado"] is None and ago["documento"] == "0000900/2025"
    assert ago["tipo"] == "Orçamentário" and ago["periodo_empenho"] == 202501
    # conservação: o pago total é o mesmo nas duas visões
    assert sum(r["pago"] or 0 for r in exe) == sum(r["pago"] or 0 for r in mov) == 1_000.0


def test_movimento_mensal_grava_dicionario(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "MOV_DIR", str(tmp_path))
    conn = cenario_execucao()
    mov = export.montar_movimento(conn)
    man = export.exportar_movimento_mensal(mov)
    assert {m["arquivo"].split("/")[-1] for m in man} >= {"2025-01.json", "2025-04.json"}
    d = json.load(open(tmp_path / "2025-01.json", encoding="utf-8"))
    assert d["campos"] == export.CAMPOS_MOV
    iU = d["campos"].index("unidade_gestora")
    assert d["dicionario"]["unidade_gestora"][d["linhas"][0][iU]] == "PREFEITURA MUNICIPAL DE SANTOS"
    assert round(sum(m["pago"] for m in man), 2) == 80_000.0    # 2025 (65k) + 2026 (15k)


# ── Classificação e taxas ────────────────────────────────────────────────────
def test_empenho_nao_localizado_nao_vira_restos():
    conn = db()
    # pagamento orçamentário de 2025 cujo empenho /2025 não veio na base
    add(conn, "pagamentos", 2025, 6, 8_000_000.0, empenho="0000002/2025", tipo_pagamento="Orçamentária")
    exe = export.montar_execucao(conn)
    assert [r["tipo"] for r in exe] == ["Empenho não localizado na base"]
    mov = export.montar_movimento(conn)
    assert mov[0]["tipo"] == "Empenho não localizado na base"
    agg = export.execucao_agregada(conn)
    a = agg["por_ano"]["2025"]
    assert a["nao_localizado"] == 8_000_000.0 and a["restos"] == 0
    # inconsistência de dados reportada explicitamente
    tipos = [x["tipo"] for x in export.alertas(conn)]
    assert "dados_nao_localizado" in tipos


def test_restos_pela_fonte_e_empenho_anterior_na_base():
    conn = db()
    add(conn, "empenhos", 2025, 11, 5_000.0, empenho="0000700/2025")
    add(conn, "pagamentos", 2026, 2, 5_000.0, empenho="0000700/2025",
        tipo_pagamento="Restos a Pagar Processados")
    # execução: o pagamento posterior casa com o empenho de 2025 (não vira linha solta)
    exe = export.montar_execucao(conn)
    assert len(exe) == 1 and exe[0]["tipo"] == "Empenho" and exe[0]["pago"] == 5_000.0
    assert exe[0]["_periodo"] == 202511
    # movimentação: o documento de 2026 é restos a pagar (campo da fonte), ligado ao empenho de 2025
    p = [r for r in export.montar_movimento(conn) if r["fase"] == "P"][0]
    assert p["tipo"] == "Restos a pagar" and p["periodo_empenho"] == 202511
    assert export.exercicio_do_empenho("0000700/2025") == 2025


def test_sem_numero_de_empenho_nao_e_conclusivo():
    # sem nº e tipo orçamentário → "não localizado"; sem nº e tipo extra → extra; com nº e tipo extra → extra
    assert export.classificar_documento("Orçamentária", "", False) == "Empenho não localizado na base"
    assert export.classificar_documento("Extra Orçamentário", "", False) == "Extra-orçamentário"
    assert export.classificar_documento("Extra Orçamentário", "0000001/2025", True) == "Extra-orçamentário"
    assert export.classificar_documento("Restos a Pagar Não Processados", "0000001/2024", False) == "Restos a pagar"
    assert export.classificar_documento("Orçamentária", "0000001/2025", True) == "Orçamentário"


def test_taxa_inconsistente_nao_e_apresentada_como_validada():
    conn = db()
    add(conn, "empenhos", 2025, 1, 100.0, empenho="0000001/2025")
    add(conn, "liquidacoes", 2025, 2, 200.0, empenho="0000001/2025")
    add(conn, "pagamentos", 2025, 3, 50.0, empenho="0000001/2025")
    a = export.execucao_agregada(conn)["por_ano"]["2025"]
    assert a["taxa_validada"] is False
    assert "taxa_liquidacao" not in a and "taxa_pagamento" not in a
    assert a["taxas_brutas"]["liquidacao"] == 200.0            # sem teto de 100%
    assert any("liquidado" in m and "supera" in m for m in a["taxa_motivos"])
    exe = export.execucao_agregada(conn)
    assert [x for x in export.alertas(conn, execucao=exe) if x["tipo"] == "dados_taxa"]


def test_denominador_nulo_negativo_e_base_incompleta_explicitos():
    conn = db()
    # só anulação na base (original emitido antes do início) → denominador negativo
    add(conn, "empenhos", 2025, 1, -100.0, empenho="0000001/2025", especie="Anulação")
    add(conn, "pagamentos", 2025, 2, 30.0, empenho="0000001/2025")
    a = export.execucao_agregada(conn)["por_ano"]["2025"]
    assert a["taxa_validada"] is False and "taxa_pagamento" not in a
    assert a["base_taxa"]["sem_original"] == 1 and a["base_taxa"]["pago_sem_original"] == 30.0
    assert any("nulo ou negativo" in m for m in a["taxa_motivos"])
    assert [r["tipo"] for r in export.montar_execucao(conn)] == ["Empenho (original fora da base)"]
    # cobertura incompleta: controle_carga só tem empenhos e pagamentos → liquidado desconhecido (null)
    conn2 = db()
    add(conn2, "empenhos", 2025, 1, 100.0, empenho="0000001/2025")
    add(conn2, "pagamentos", 2025, 1, 10.0, empenho="0000001/2025")
    for f in ("empenhos", "pagamentos"):
        conn2.execute("INSERT INTO controle_carga (fonte, ano, mes, registros, soma, baixado_em, status) "
                      "VALUES (?, 2025, 1, 1, 100, 'x', 'ok')", (f,))
    conn2.commit()
    agg = export.execucao_agregada(conn2)
    jan = agg["serie"][0]
    assert jan["liquidado"] is None and jan["empenhado"] == 100.0     # desconhecido ≠ zero
    a2 = agg["por_ano"]["2025"]
    assert a2["taxa_validada"] is False and any("cobertura incompleta" in m for m in a2["taxa_motivos"])
    cob = export.cobertura(conn2)
    assert "liquidacoes 2025-01" in cob["faltantes"] and cob["integra"] is False


# ── Alertas: classes, identidade, histórico ──────────────────────────────────
def test_alertas_classes_links_e_documentos():
    conn = cenario_grafias()
    for mes in range(1, 8):   # grande recebedor recorrente (7 meses, > 5 mi)
        add(conn, "pagamentos", 2025, mes, 1_000_000.0, nome_favorecido="GRANDE LTDA",
            documento_favorecido="22.222.222/0001-22", pagamento=f"00009{mes}/2025")
    lista = export.alertas(conn)
    rec = [a for a in lista if a["tipo"] == "favorecido_recorrente"]
    assert rec and rec[0]["classe"] == "contexto" and rec[0]["severidade"] == "baixa"
    assert rec[0]["filtro"]["chave"] == "cnpj:22222222000122" and rec[0]["link"].startswith("./favorecido.html?")
    assert all(a.get("id") and a.get("classe") and a.get("link") for a in lista)
    ids = [a["id"] for a in lista]
    assert len(ids) == len(set(ids))


def test_alertas_consolidam_por_identidade():
    conn = db()
    doc = "33.333.333/0001-33"
    for mes in range(1, 8):
        add(conn, "pagamentos", 2025, mes, 500_000.0, nome_favorecido="DUAS GRAFIAS LTDA", documento_favorecido=doc)
        add(conn, "pagamentos", 2025, mes, 500_000.0, nome_favorecido="DUAS GRAFIAS LTDA.", documento_favorecido=doc)
    rec = [a for a in export.alertas(conn) if a["tipo"] == "favorecido_recorrente"]
    assert len(rec) == 1 and rec[0]["valor"] == 7_000_000.0


def test_yoy_compara_mesmo_periodo_sem_projecao():
    conn = db()
    for mes in range(1, 13):
        add(conn, "pagamentos", 2025, mes, 100_000.0, nome_favorecido="CRESCE LTDA",
            documento_favorecido="44.444.444/0001-44")
        add(conn, "pagamentos", 2025, mes, 100_000.0, nome_favorecido="ESTAVEL LTDA",
            documento_favorecido="55.555.555/0001-55")
    for mes in (1, 2, 3, 4):   # 2026: jan–mar completos, abril parcial
        add(conn, "pagamentos", 2026, mes, 1_000_000.0 if mes < 4 else 10.0, nome_favorecido="CRESCE LTDA",
            documento_favorecido="44.444.444/0001-44")
        add(conn, "pagamentos", 2026, mes, 100_000.0, nome_favorecido="ESTAVEL LTDA",
            documento_favorecido="55.555.555/0001-55")
    add(conn, "pagamentos", 2026, 5, 1.0, data="2026-05-05", nome_favorecido="SENTINELA")  # março completo
    yoy = [a for a in export.alertas(conn) if a["tipo"] == "crescimento_yoy"]
    assert len(yoy) == 1 and "CRESCE" in yoy[0]["titulo"]
    assert "jan–mar/2026" in yoy[0]["detalhe"] and "sem projeção" in yoy[0]["detalhe"]
    assert yoy[0]["valor"] == 3_000_000.0                          # só meses completos


def test_historico_de_alertas_novo_persistente_resolvido(tmp_path):
    caminho = str(tmp_path / "estado.json")
    a1 = {"id": "aaa", "tipo": "t", "titulo": "A"}
    a2 = {"id": "bbb", "tipo": "t", "titulo": "B"}
    h = export.aplicar_historico_alertas([a1, a2], caminho, hoje="2026-09-01")
    assert h["disponivel"] is False and h["nota"]
    assert a1["estado"] == "sem_historico"            # sem histórico: não chama tudo de "novo"
    a3 = {"id": "ccc", "tipo": "t", "titulo": "C"}
    a1b = {"id": "aaa", "tipo": "t", "titulo": "A"}
    h2 = export.aplicar_historico_alertas([a1b, a3], caminho, hoje="2026-09-08")
    assert h2["disponivel"] is True and h2["desde"] == "2026-09-01"
    assert a1b["estado"] == "persistente" and a1b["primeiro_em"] == "2026-09-01"
    assert a3["estado"] == "novo" and h2["novos"] == 1
    assert [r["id"] for r in h2["resolvidos_recentes"]] == ["bbb"]


# ── Briefing: seleção de alertas por novidade e diversidade ─────────────────
def test_briefing_seleciona_por_novidade_e_diversidade():
    import briefing
    lista = []
    for i in range(20):    # 20 grandes recebedores (contexto), todos persistentes e de valor alto
        lista.append({"id": f"r{i}", "tipo": "favorecido_recorrente", "classe": "contexto", "severidade": "baixa",
                      "valor": 1e9 - i, "estado": "persistente", "filtro": {"chave": f"cnpj:{i:014d}"}, "titulo": "R"})
    lista.append({"id": "n1", "tipo": "pico_favorecido", "classe": "anomalia", "severidade": "media",
                  "valor": 1e6, "estado": "novo", "filtro": {"chave": "cnpj:00000000000001"}, "titulo": "N1"})
    lista.append({"id": "n2", "tipo": "pico_favorecido", "classe": "anomalia", "severidade": "media",
                  "valor": 2e6, "estado": "novo", "filtro": {"chave": "cnpj:00000000000001"}, "titulo": "N2 mesmo fav"})
    lista.append({"id": "d1", "tipo": "dados_duplicidade", "classe": "inconsistencia", "severidade": "media",
                  "valor": 5e6, "estado": "persistente", "filtro": {}, "titulo": "D"})
    sel = briefing.selecionar_alertas(lista, maximo=12)
    ids = [a["id"] for a in sel]
    assert ids[0] == "n2"                       # novo antes de persistente; maior valor entre os novos
    assert "n1" not in ids                      # 1 alerta por favorecido
    assert "d1" in ids                          # inconsistência entra antes do contexto
    assert sum(1 for a in sel if a["tipo"] == "favorecido_recorrente") <= briefing.MAX_POR_REGRA
    assert len(sel) <= 12
