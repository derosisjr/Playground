"""Alertas v2 (2026-10): fracionamento por unidade gestora, só empenho ordinário,
limite de manutenção de veículos, etiqueta do PNCP, pago acima do liquidado,
continuidade de id, prioridade de publicação, candidatos e publicidade."""
import gzip
import json
import sqlite3
import uuid

import crawler
import export

PMS = "PREFEITURA MUNICIPAL DE SANTOS"
CAPEP = "CAIXA DE ASSIST. AO SERV.PÚBL. MUNIC. DE SANTOS"
CNPJ_X = "11.222.333/0001-44"          # fornecedor dos cenários de fracionamento


def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(crawler._schema())
    conn.row_factory = sqlite3.Row
    return conn


def add(conn, tabela, ano, mes, valor, **kw):
    base = {"unidade_gestora": PMS, "data": f"{ano}-{mes:02d}-10", "especie": "Original",
            "empenho": f"0000001/{ano}", "elemento_despesa": "33903099000 - OUTROS MATERIAIS DE CONSUMO",
            "subtitulo": "", "funcao": "10 - SAÚDE", "subfuncao": "301", "programa": "P",
            "fonte_recurso": "TESOURO", "grupo_despesa": "33 - OUTRAS DESPESAS CORRENTES",
            "documento_favorecido": CNPJ_X, "nome_favorecido": "FORNECE LTDA",
            "tipo_pagamento": "Orçamentária", "tipo_liquidacao": "Orçamentária", "tipo_empenho": "Ordinário"}
    base.update(kw)
    base.update({"ano": ano, "mes": mes, "valor": valor, "hash": uuid.uuid4().hex})
    cols = ["hash"] + crawler._cols(tabela)
    conn.execute(f"INSERT INTO {tabela} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 [base.get(c) for c in cols])
    conn.commit()


SEM_ESPELHO = {"inicio": None, "cnpj": {}}


def frac(conn, **kw):
    return [a for a in export.candidatos_alertas(conn, espelho=kw.pop("espelho", SEM_ESPELHO), **kw)
            if a["tipo"] == "fracionamento"]


# ── Fracionamento v2 ──────────────────────────────────────────────────────────
def test_fracionamento_soma_por_unidade_gestora():
    conn = db()
    for i, ug in enumerate((PMS, PMS, CAPEP, CAPEP), 1):     # 2 + 2 em UGs diferentes
        add(conn, "empenhos", 2025, i, 50_000.0, empenho=f"000000{i}/2025", unidade_gestora=ug)
    assert frac(conn) == []                                  # a v1 somava as UGs e disparava
    for i in (5, 6):                                         # agora 4 na CAPEP
        add(conn, "empenhos", 2025, i, 50_000.0, empenho=f"000000{i}/2025", unidade_gestora=CAPEP)
    [a] = frac(conn)
    assert a["filtro"]["unidade"] == CAPEP and CAPEP in a["titulo"] and "du=" in a["link"]
    assert "4 empenhos distintos" in a["titulo"]
    # continuidade: o id v1 (sem UG) vai em ids_anteriores
    chave = a["filtro"]["chave"]
    assert a["ids_anteriores"] == [export._id_alerta("fracionamento", chave, a["filtro"]["elemento"], 2025)]
    assert a["id"] != a["ids_anteriores"][0]


def test_fracionamento_so_empenho_ordinario_conta():
    conn = db()
    for i in (1, 2):
        add(conn, "empenhos", 2025, i, 50_000.0, empenho=f"000000{i}/2025")
    for i, t in ((3, "Global"), (4, "Estimativo")):
        add(conn, "empenhos", 2025, i, 50_000.0, empenho=f"000000{i}/2025", tipo_empenho=t)
    assert frac(conn) == []                                  # só 2 ordinários
    for i in (5, 6):                                         # tipo nulo = ordinário
        add(conn, "empenhos", 2025, i, 50_000.0, empenho=f"000000{i}/2025", tipo_empenho=None)
    [a] = frac(conn)
    assert "4 empenhos distintos" in a["titulo"] and len(a["documentos"]) == 4
    assert {d["empenho"] for d in a["documentos"]} == {"0000001/2025", "0000002/2025", "0000005/2025", "0000006/2025"}
    assert "Fora da conta: 2 empenho(s) global(is)/estimativo(s)" in a["detalhe"]
    assert a["valor"] == 200_000.0


def test_fracionamento_manutencao_de_veiculos_usa_limite_do_art_75_I():
    for elem in ("33903919000 - MANUTENÇÃO E CONSERVAÇÃO DE VEÍCULOS", "33903039000 - MATERIAL P/ MANUTENÇÃO DE VEÍCULOS"):
        lim = export._limite_dispensa(2025, elem)
        assert lim["valor"] == export.LIMITES_DISPENSA[2025]["engenharia"] == 125_451.15
        assert "manutenção de veículos" in lim["hipotese"]
        conn = db()
        for i in (1, 2, 3, 4):     # 100 mil: acima do limite de compras, abaixo do art. 75, I
            add(conn, "empenhos", 2025, i, 100_000.0, empenho=f"000000{i}/2025", elemento_despesa=elem)
        [a] = frac(conn)
        assert a["limite"]["valor"] == 125_451.15 and a["valor"] == 400_000.0
    assert export._limite_dispensa(2025, "33903099000 - OUTROS")["valor"] == 62_725.59


def _espelho(tmp_path, contratacoes):
    with gzip.open(tmp_path / "3548500-2025.jsonl.gz", "wt", encoding="utf-8") as f:
        for c in contratacoes:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return export.espelho_pncp(str(tmp_path))


def _contratacao(seq, modalidade, srp, data, ni="11222333000144", situacao="Divulgada no PNCP"):
    return {"ncp": f"58200015000183-1-{seq:06d}/2025", "cnpj": "58200015000183", "ano": 2025, "sequencial": seq,
            "modalidade": modalidade, "srp": srp, "situacao": situacao, "processo": f"{seq}/2025-01",
            "razao_social": "MUNICIPIO DE SANTOS", "objeto": "Registro de preços de material de consumo",
            "data_publicacao": data, "itens": [],
            "resultados": [{"ni_fornecedor": ni, "data_resultado": data, "numero_item": 1}]}


def _cenario_frac():
    conn = db()
    for i in (3, 4, 5, 6):
        add(conn, "empenhos", 2025, i, 50_000.0, empenho=f"000000{i}/2025")
    return conn


def test_etiqueta_pncp_com_espelho_falso(tmp_path):
    esp = _espelho(tmp_path, [_contratacao(7, 6, 1, "2025-01-15")])
    assert esp["inicio"] == "2025-01-15" and "11222333000144" in esp["cnpj"]
    [a] = frac(_cenario_frac(), espelho=esp)
    assert a["etiqueta"] == "provavel_ata" and a["etiqueta_alcance"] == [4, 4]
    assert a["pncp"][0]["link"] == "https://pncp.gov.br/app/editais/58200015000183/2025/7"   # formato de precos/fontes.py
    assert a["pncp"][0]["processo"] == "7/2025-01"
    assert "provável compra por ata" in a["detalhe"] and "desde jan/2025" in a["detalhe"]
    assert "“sem registro” não quer dizer “sem licitação”" in a["detalhe"]


def test_etiqueta_pncp_pregao_sem_srp_dispensa_e_janela(tmp_path):
    for sub, contr, esperado in (
            ("a", [_contratacao(1, 6, 0, "2025-02-01")], "vencedor_pregao"),
            ("b", [_contratacao(2, 8, 0, "2025-02-01")], "dispensa_pncp"),
            ("c", [_contratacao(3, 6, 1, "2022-01-01")], None),                  # fora dos 24 meses
            ("d", [_contratacao(4, 6, 1, "2025-12-01")], None),                  # depois dos empenhos
            ("e", [_contratacao(5, 6, 1, "2025-01-15", situacao="Revogada")], None),
            ("f", [_contratacao(6, 6, 1, "2025-01-15", ni="99888777000166")], None)):  # outro CNPJ
        pasta = tmp_path / sub
        pasta.mkdir()
        [a] = frac(_cenario_frac(), espelho=_espelho(pasta, contr))
        assert a["etiqueta"] == esperado, sub
        if esperado is None:
            assert "Sem registro deste fornecedor no PNCP" in a["detalhe"]
    [a] = frac(_cenario_frac(), espelho=export.espelho_pncp(str(tmp_path / "nao-existe")))
    assert a["etiqueta"] is None and "indisponível" in a["detalhe"]


def test_provavel_ata_publicado_por_ultimo(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "CAP_POR_REGRA", 1)
    conn = _cenario_frac()                       # FORNECE LTDA: provável ata, soma maior
    for i in (3, 4, 5, 6):
        add(conn, "empenhos", 2025, i, 30_000.0, empenho=f"000001{i}/2025", documento_favorecido="55.666.777/0001-88",
            nome_favorecido="SEM ATA LTDA")
    esp = _espelho(tmp_path, [_contratacao(7, 6, 1, "2025-01-15")])
    cands = export.candidatos_alertas(conn, espelho=esp)
    contagem = {}
    pub = [a for a in export.publicar(cands, contagem) if a["tipo"] == "fracionamento"]
    assert [a["filtro"]["favorecido"] for a in pub] == ["SEM ATA LTDA"]
    assert contagem["fracionamento"] == {"candidatos": 2, "publicados": 1}


# ── Pago acima do liquidado ──────────────────────────────────────────────────
def _liquidacao(conn, emp, liq, valor, ano=2025, mes=3, **kw):
    add(conn, "liquidacoes", ano, mes, valor, empenho=emp, liquidacao=liq, **kw)


def _pagamento(conn, emp, liq, pag, valor, ano=2025, mes=4, **kw):
    add(conn, "pagamentos", ano, mes, valor, empenho=emp, liquidacao=liq, pagamento=pag, **kw)


def test_liquidacao_paga_duas_vezes():
    conn = db()
    add(conn, "empenhos", 2025, 2, 10_000.0, empenho="0000010/2025")
    _liquidacao(conn, "0000010/2025", "0000100/2025", 10_000.0)
    _pagamento(conn, "0000010/2025", "0000100/2025", "0001000/2025", 10_000.0)
    _pagamento(conn, "0000010/2025", "0000100/2025", "0001001/2025", 10_000.0, mes=5)
    [x] = export.pago_acima_liquidado(conn)
    assert x["dobro"] and x["excesso"] == 10_000.0 and x["pagamentos"] == 2
    [a] = [a for a in export.alertas(conn) if a["tipo"] == "pago_acima_liquidado"]
    assert a["titulo"].startswith("Liquidação paga duas vezes") and a["classe"] == "anomalia"
    assert a["valor"] == 10_000.0 and a["filtro"]["liquidacao"] == "0000100/2025"
    # documentos e recorte só nos publicados: a liquidação e os dois pagamentos; a ficha do empenho
    assert [d["fase"] for d in a["documentos"]] == ["Liquidação", "Pagamento", "Pagamento"]
    assert "dm=2025-02" in a["link"] and "emp=PREFEITURA" in a["link"]


def test_pago_acima_ignora_extra_rp_processados_empenho_equilibrado_e_ruidos():
    conn = db()
    add(conn, "empenhos", 2025, 2, 30_000.0, empenho="0000020/2025")
    # (a) retenção extra-orçamentária com o mesmo nº de liquidação: não é pagamento do empenho
    _liquidacao(conn, "0000020/2025", "0000200/2025", 10_000.0)
    _pagamento(conn, "0000020/2025", "0000200/2025", "0002000/2025", 9_000.0)
    _pagamento(conn, "0000020/2025", "0000200/2025", "0002001/2025", 1_000.0, tipo_pagamento="Extra Orçamentário",
               nome_favorecido="INSS", documento_favorecido="29.979.036/0001-40")
    # (b) restos a pagar processados apontam liquidação de outro exercício
    _pagamento(conn, "0000020/2025", "0000999/2024", "0002002/2025", 5_000.0,
               tipo_pagamento="Restos a Pagar Processados")
    # (c) nº de liquidação trocado entre parcelas: o empenho inteiro está equilibrado
    _liquidacao(conn, "0000020/2025", "0000201/2025", 10_000.0, mes=4)
    _liquidacao(conn, "0000020/2025", "0000202/2025", 10_000.0, mes=5)
    _pagamento(conn, "0000020/2025", "0000201/2025", "0002003/2025", 15_000.0, mes=5)
    _pagamento(conn, "0000020/2025", "0000202/2025", "0002004/2025", 5_000.0, mes=6)
    assert export.pago_acima_liquidado(conn) == []
    # (d) excesso abaixo de R$ 100
    conn2 = db()
    add(conn2, "empenhos", 2025, 2, 10_000.0, empenho="0000030/2025")
    _liquidacao(conn2, "0000030/2025", "0000300/2025", 10_000.0)
    _pagamento(conn2, "0000030/2025", "0000300/2025", "0003000/2025", 10_050.0)
    assert export.pago_acima_liquidado(conn2) == []
    # (e) ente público (folha/repasse) e (f) partição com duplicidade sistemática
    conn3 = db()
    add(conn3, "empenhos", 2025, 2, 10_000.0, empenho="0000040/2025", nome_favorecido="MUNICÍPIO DE SANTOS",
        documento_favorecido="58.200.015/0001-83")
    _liquidacao(conn3, "0000040/2025", "0000400/2025", 10_000.0, nome_favorecido="MUNICÍPIO DE SANTOS",
                documento_favorecido="58.200.015/0001-83")
    _pagamento(conn3, "0000040/2025", "0000400/2025", "0004000/2025", 20_000.0, nome_favorecido="MUNICÍPIO DE SANTOS",
               documento_favorecido="58.200.015/0001-83")
    add(conn3, "empenhos", 2025, 2, 10_000.0, empenho="0000041/2025")
    _liquidacao(conn3, "0000041/2025", "0000410/2025", 10_000.0)
    _pagamento(conn3, "0000041/2025", "0000410/2025", "0004100/2025", 20_000.0)
    assert [x["empenho"] for x in export.pago_acima_liquidado(conn3)] == ["0000041/2025"]
    assert export.pago_acima_liquidado(conn3, {("pagamentos", 2025, 4)}) == []
    # (g) liquidação só com a anulação na base (original fora): base incompleta, não compara
    conn4 = db()
    add(conn4, "empenhos", 2025, 2, 10_000.0, empenho="0000050/2025")
    _liquidacao(conn4, "0000050/2025", "0000500/2025", -1_000.0, especie="Anulação")
    _pagamento(conn4, "0000050/2025", "0000500/2025", "0005000/2025", 9_000.0)
    assert export.pago_acima_liquidado(conn4) == []


# ── Histórico: continuidade, migração, prioridade e teto ─────────────────────
def test_alerta_v2_herda_primeiro_em_do_id_v1(tmp_path):
    caminho = tmp_path / "estado.json"
    caminho.write_text(json.dumps({"atualizado_em": "2026-10-16", "alertas": {
        "idv1": {"primeiro_em": "2026-09-29", "ultimo_em": "2026-10-16", "tipo": "fracionamento", "titulo": "T"}},
        "resolvidos": {}}), encoding="utf-8")
    a = {"id": "idv2", "ids_anteriores": ["idv1"], "tipo": "fracionamento", "titulo": "T"}
    h = export.aplicar_historico_alertas([a], str(caminho), hoje="2026-10-17")
    assert a["estado"] == "persistente" and a["primeiro_em"] == "2026-09-29"
    assert h["resolvidos_recentes"] == []                  # o id antigo não vira "resolvido"
    gravado = json.loads(caminho.read_text(encoding="utf-8"))
    assert list(gravado["alertas"]) == ["idv2"] and gravado["versao"] == 2
    assert "ultimo_em" not in gravado["alertas"]["idv2"]   # sem diff diário em todas as linhas
    assert gravado["resolvidos"] == {}


def test_migracao_do_estado_v1_nao_chama_candidato_de_novo(tmp_path):
    caminho = tmp_path / "estado.json"
    caminho.write_text(json.dumps({"alertas": {"pub": {"primeiro_em": "2026-09-29", "tipo": "t", "titulo": "P"}},
                                   "resolvidos": {}}), encoding="utf-8")       # v1: só os publicados
    lista = [{"id": "pub", "tipo": "t", "titulo": "P"}, {"id": "fora", "tipo": "t", "titulo": "F"}]
    export.aplicar_historico_alertas(lista, str(caminho), hoje="2026-10-17")
    assert [a["estado"] for a in lista] == ["persistente", "sem_historico"]
    lista2 = [{"id": "pub", "tipo": "t", "titulo": "P"}, {"id": "fora", "tipo": "t", "titulo": "F"},
              {"id": "nova", "tipo": "t", "titulo": "N"}]
    export.aplicar_historico_alertas(lista2, str(caminho), hoje="2026-10-18")
    assert [a["estado"] for a in lista2] == ["persistente", "persistente", "novo"]


def _cand(i, valor, tipo="pico_favorecido", classe="anomalia", sev="media", **kw):
    return {"id": i, "tipo": tipo, "classe": classe, "severidade": sev, "titulo": i, "valor": valor,
            "filtro": {}, "link": "#", **kw}


def test_prioridade_novo_antes_de_persistente(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "CAP_POR_REGRA", 1)
    caminho = str(tmp_path / "estado.json")
    export.aplicar_historico_alertas([_cand("grande", 9e6)], caminho, hoje="2026-10-17")
    cands = [_cand("grande", 9e6), _cand("pequeno", 1e5)]
    export.aplicar_historico_alertas(cands, caminho, hoje="2026-10-18")
    assert [a["id"] for a in export.publicar(cands)] == ["pequeno"]     # novo vence o persistente maior


def test_deslocado_pelo_teto_continua_persistente(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "CAP_POR_REGRA", 1)
    caminho = str(tmp_path / "estado.json")
    export.aplicar_historico_alertas([_cand("velho", 1.0)], caminho, hoje="2026-10-16")
    dia1 = [_cand("velho", 1.0), _cand("maior", 5.0)]
    export.aplicar_historico_alertas(dia1, caminho, hoje="2026-10-17")
    assert [a["id"] for a in export.publicar(dia1)] == ["maior"]          # "velho" saiu pelo teto
    dia2 = [_cand("velho", 1.0), _cand("maior", 5.0)]
    h = export.aplicar_historico_alertas(dia2, caminho, hoje="2026-10-18")
    assert {a["id"]: a["estado"] for a in dia2} == {"velho": "persistente", "maior": "persistente"}
    assert dia2[0]["primeiro_em"] == "2026-10-16" and h["resolvidos_recentes"] == []


def test_teto_global_corta_contexto_primeiro(monkeypatch):
    monkeypatch.setattr(export, "MAX_ALERTAS", 2)
    cands = [_cand("ctx", 9e9, tipo="favorecido_recorrente", classe="contexto", sev="baixa"),
             _cand("an1", 1.0), _cand("inc", 0.0, tipo="dados_taxa", classe="inconsistencia", sev="baixa")]
    assert {a["id"] for a in export.publicar(cands)} == {"an1", "inc"}


def test_candidatos_vao_para_o_arquivo_com_o_que_ficou_de_fora(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "CAP_POR_REGRA", 1)
    cands = [_cand("a", 2.0, filtro={"favorecido": "X", "documento": "1"}), _cand("b", 1.0)]
    pub = export.publicar(cands)
    destino = tmp_path / "cand.json"
    assert export.exportar_candidatos(cands, pub, str(destino)) == 2
    d = json.loads(destino.read_text(encoding="utf-8"))
    linhas = [dict(zip(d["campos"], l)) for l in d["linhas"]]
    assert [(l["id"], l["publicado"]) for l in linhas] == [("a", True), ("b", False)]
    assert linhas[0]["favorecido"] == "X" and "_completar" not in d["campos"]


# ── Publicidade (só agregados) ───────────────────────────────────────────────
def test_publicidade_por_ano_mesmo_periodo_serie_e_favorecidos():
    conn = db()
    prop, legal = "33903988000 - SERVIÇOS DE PROPAGANDA", "33903990000 - SERVIÇOS DE PUBLICIDADE LEGAL"
    for mes in (1, 2, 3, 9):
        add(conn, "pagamentos", 2025, mes, 100.0, elemento_despesa=prop, nome_favorecido="AGENCIA A LTDA",
            documento_favorecido="10.000.000/0001-00")
    add(conn, "pagamentos", 2025, 2, 50.0, elemento_despesa=legal, nome_favorecido="PRODESAN PROGRESSO E DESENVOLVIMENTO DE SANTOS SA",
        documento_favorecido="58.000.000/0001-00")
    for mes in (1, 2):
        add(conn, "pagamentos", 2026, mes, 300.0, elemento_despesa=prop, nome_favorecido="AGENCIA A LTDA",
            documento_favorecido="10.000.000/0001-00")
    add(conn, "pagamentos", 2026, 3, 999.0)                                   # outro elemento: fora
    add(conn, "pagamentos", 2026, 4, 1.0, data="2026-04-30")                  # base "fresca": março completo
    p = export.publicidade(conn, export.preparar_identidades(conn))
    assert p["por_ano"]["2025"] == {"propaganda": 400.0, "legal": 50.0, "total": 450.0, "pagamentos": 5}
    assert p["por_ano"]["2026"]["total"] == 600.0
    c = p["comparacao"]                                                       # jan–mar dos dois anos
    assert (c["ano"], c["mes"], c["atual"], c["anterior"], c["pct"]) == (2026, 3, 600.0, 350.0, 71)
    assert len(p["serie"]) == 16 and p["serie"][3] == {"ano": 2025, "mes": 4, "propaganda": 0.0, "legal": 0.0}
    assert [f["nome"] for f in p["favorecidos"]] == ["AGENCIA A LTDA", "PRODESAN PROGRESSO E DESENVOLVIMENTO DE SANTOS SA"]
    assert p["favorecidos"][1]["legal"] == 50.0 and p["favorecidos"][1].get("ente_publico") is True
    assert export.publicidade(db(), {}) is None


def test_resumo_mes_parcial_singular_e_plural():
    conn = db()
    for mes in range(1, 13):
        add(conn, "pagamentos", 2025, mes, 100.0)
    add(conn, "pagamentos", 2026, 1, 100.0, data="2026-01-31")     # dez/2025 completo, jan/2026 parcial
    indice = export.agregados(conn)
    indice["alertas"] = []
    assert "O mês 2026-01 ainda está incompleto na origem e fica fora" in export.resumo_narrativo(conn, indice)["texto"]
    add(conn, "pagamentos", 2026, 2, 100.0, data="2026-02-10")
    indice = export.agregados(conn)
    indice["alertas"] = []
    t = export.resumo_narrativo(conn, indice)["texto"]
    assert "Os meses 2026-01, 2026-02 ainda estão incompletos na origem e ficam fora" in t
    assert "(s)" not in t.split("Os meses")[1]
