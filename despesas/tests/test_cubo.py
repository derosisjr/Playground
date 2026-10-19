"""Cubo do Explorador de pagamentos (despesas/dados/cubo/AAAA.json, 2026-10): conservação
do pago por ano (inclusive extra-orçamentário), favorecido por IDENTIDADE (grafias do mesmo
CNPJ numa linha só; CPF mascarado parecido não se funde), bytes determinísticos e ida e
volta do dicionário. Base sintética, como em test_export.py."""
import json
import random
import sqlite3
import uuid

import crawler
import export
import verificar

PMS = "PREFEITURA MUNICIPAL DE SANTOS"
CNPJ_IPS = "08.717.299/0001-01"


def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(crawler._schema())
    conn.row_factory = sqlite3.Row
    return conn


def add(conn, tabela, ano, mes, valor, **kw):
    base = {"unidade_gestora": PMS, "data": f"{ano}-{mes:02d}-10", "especie": "Original",
            "empenho": f"0000001/{ano}", "elemento_despesa": "33903999000 - OUTROS SERVIÇOS",
            "subtitulo": "", "funcao": "10 - SAÚDE", "subfuncao": "301 - ATENÇÃO BÁSICA",
            "programa": "0001 - PROGRAMA X", "fonte_recurso": "01-1100000 - GERAL",
            "grupo_despesa": "33 - OUTRAS DESPESAS CORRENTES",
            "documento_favorecido": "12.345.678/0001-90", "nome_favorecido": "ACME SERVIÇOS LTDA",
            "tipo_pagamento": "Orçamentária", "tipo_liquidacao": "Orçamentária", "tipo_empenho": "Ordinário"}
    base.update(kw)
    base.update({"ano": ano, "mes": mes, "valor": valor, "hash": uuid.uuid4().hex})
    cols = ["hash"] + crawler._cols(tabela)
    conn.execute(f"INSERT INTO {tabela} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 [base.get(c) for c in cols])
    conn.commit()


def cenario(ordem=None):
    """2025 e 2026: orçamentário, restos, extra-orçamentário sem função, anulação negativa,
    o mesmo CNPJ com três grafias e dois CPFs mascarados parecidos. `ordem` embaralha a
    ordem de inserção (o rowid muda; o cubo não pode mudar)."""
    linhas = [
        ("empenhos", 2025, 1, 900.0, {"empenho": "0000010/2025"}),
        ("pagamentos", 2025, 1, 100.10, {"empenho": "0000010/2025"}),
        ("pagamentos", 2025, 1, 200.20, {"empenho": "0000010/2025"}),           # mesma célula: soma
        ("pagamentos", 2025, 2, -50.05, {"empenho": "0000010/2025", "especie": "Anulação"}),
        ("pagamentos", 2025, 3, 10_000.0, {"empenho": "0000009/2024", "tipo_pagamento": "Restos a Pagar Processados"}),
        ("pagamentos", 2025, 3, 333.33, {"empenho": "", "tipo_pagamento": "Extra Orçamentário",
                                         "funcao": None, "subfuncao": None, "programa": None, "grupo_despesa": None,
                                         "fonte_recurso": "1100000 - GERAL"}),
        # o mesmo CNPJ grafado de três formas (o ranking consolida — o cubo também)
        ("pagamentos", 2025, 4, 1_000.0, {"nome_favorecido": "INSTITUTO DE PREVIDENCIA", "documento_favorecido": CNPJ_IPS,
                                          "empenho": "0000077/2024", "tipo_pagamento": "Restos a Pagar Processados"}),
        ("pagamentos", 2025, 4, 2_000.0, {"nome_favorecido": "INSTITUTO DE PREVIDÊNCIA", "documento_favorecido": CNPJ_IPS,
                                          "empenho": "0000077/2024", "tipo_pagamento": "Restos a Pagar Processados"}),
        ("pagamentos", 2025, 4, 500.0, {"nome_favorecido": "IPREV - INST. PREV.", "documento_favorecido": "08717299000101",
                                        "empenho": "0000077/2024", "tipo_pagamento": "Restos a Pagar Processados"}),
        ("pagamentos", 2025, 4, 2_500.0, {"nome_favorecido": "INSTITUTO DE PREVIDENCIA", "documento_favorecido": CNPJ_IPS,
                                          "empenho": "0000077/2024", "tipo_pagamento": "Restos a Pagar Processados"}),
        # CPF mascarado: mesmos dígitos visíveis, nomes diferentes → pessoas diferentes
        ("pagamentos", 2025, 5, 700.0, {"nome_favorecido": "JOSE DA SILVA", "documento_favorecido": "***.158.308-**",
                                        "empenho": "0000010/2025"}),
        ("pagamentos", 2025, 5, 300.0, {"nome_favorecido": "MARIA SOUZA", "documento_favorecido": "***.158.308-**",
                                        "empenho": "0000010/2025"}),
        ("pagamentos", 2025, 6, 70.0, {"nome_favorecido": "JOSÉ DA SILVA", "documento_favorecido": "***.158.308-**",
                                       "empenho": "0000010/2025"}),
        ("empenhos", 2026, 1, 5_000.0, {"empenho": "0000020/2026"}),
        ("pagamentos", 2026, 2, 1_234.56, {"empenho": "0000020/2026"}),
        ("pagamentos", 2026, 2, 0.01, {"empenho": "0000099/2026"}),               # empenho não localizado
        ("liquidacoes", 2026, 2, 1_234.56, {"empenho": "0000020/2026"}),          # fase L: fora do cubo
    ]
    if ordem is not None:
        random.Random(ordem).shuffle(linhas)
    conn = db()
    for tabela, ano, mes, valor, kw in linhas:
        add(conn, tabela, ano, mes, valor, **kw)
    return conn


def gerar(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(export, "DADOS_DIR", str(tmp_path))
    ident = export.preparar_identidades(conn)
    mov = export.montar_movimento(conn)
    return export.exportar_cubos(mov, ident), ident


def ler(tmp_path, ano):
    return json.loads((tmp_path / "cubo" / f"{ano}.json").read_text(encoding="utf-8"))


def decodificar(cubo):
    """Ida e volta do dicionário (o que o explorador faz ao montar a tabela)."""
    C = cubo["campos"]
    out = []
    for lin in cubo["linhas"]:
        o = dict(zip(C, lin))
        for c, valores in cubo["dicionario"].items():
            o[c] = valores[lin[C.index(c)]]
        out.append(o)
    return out


def test_conservacao_do_pago_por_ano_com_extra_e_tipos(tmp_path, monkeypatch):
    conn = cenario()
    man, _ = gerar(conn, tmp_path, monkeypatch)
    por_ano = {str(r["ano"]): round(r["s"], 2) for r in conn.execute(
        "SELECT ano, SUM(valor) s FROM pagamentos GROUP BY ano")}
    n_ano = {r["ano"]: r["n"] for r in conn.execute("SELECT ano, COUNT(*) n FROM pagamentos GROUP BY ano")}
    assert [m["ano"] for m in man] == [2025, 2026]
    for m in man:
        cubo = ler(tmp_path, m["ano"])
        linhas = decodificar(cubo)
        assert m["pago"] == por_ano[str(m["ano"])] == round(sum(l["pago"] for l in linhas), 2)
        assert m["n"] == n_ano[m["ano"]] == sum(l["n"] for l in linhas)     # documentos, não linhas do cubo
        assert m["linhas"] == len(cubo["linhas"]) and m["arquivo"] == f"despesas/dados/cubo/{m['ano']}.json"
        assert m["bytes"] == (tmp_path / "cubo" / f"{m['ano']}.json").stat().st_size and 0 < m["gzip"] < m["bytes"]
    tipos = {l["tipo"] for l in decodificar(ler(tmp_path, 2025))}
    assert tipos == {"Orçamentário", "Restos a pagar", "Extra-orçamentário"}
    assert {l["tipo"] for l in decodificar(ler(tmp_path, 2026))} == {"Orçamentário", "Empenho não localizado na base"}
    extra = [l for l in decodificar(ler(tmp_path, 2025)) if l["tipo"] == "Extra-orçamentário"]
    assert extra == [dict(extra[0], funcao=None, subfuncao=None, programa=None, grupo_despesa=None, pago=333.33, n=1)]
    # a mesma célula soma (100,10 + 200,20) e a anulação entra negativa no mês dela
    jan = [l for l in decodificar(ler(tmp_path, 2025)) if l["mes"] == 1]
    assert len(jan) == 1 and jan[0]["pago"] == 300.3 and jan[0]["n"] == 2
    fev = [l for l in decodificar(ler(tmp_path, 2025)) if l["mes"] == 2]
    assert fev[0]["pago"] == -50.05


def test_favorecido_por_identidade_consolida_grafias(tmp_path, monkeypatch):
    conn = cenario()
    _, ident = gerar(conn, tmp_path, monkeypatch)
    cubo = ler(tmp_path, 2025)
    assert cubo["campos_favorecido"] == ["chave", "nome", "documento"]
    favs = [tuple(f) for f in cubo["dicionario"]["favorecido"]]
    ips = [f for f in favs if f[0] == "cnpj:08717299000101"]
    # uma identidade, com o nome e o documento de exibição do ranking (grafia mais frequente)
    assert ips == [("cnpj:08717299000101", ident["cnpj:08717299000101"]["nome"],
                    ident["cnpj:08717299000101"]["documento"])]
    assert ips[0][1:] == ("INSTITUTO DE PREVIDENCIA", CNPJ_IPS)
    # a chave publicada é a do formato.identidade_favorecido (a mesma do índice e dos dossiês)
    for chave, nome, doc in favs:
        assert export.identidade_favorecido(nome, doc)[0] == chave
    abril = [l for l in decodificar(cubo) if l["mes"] == 4]
    assert len(abril) == 1 and abril[0]["pago"] == 6_000.0 and abril[0]["n"] == 4
    # CPF mascarado: dígitos parciais não unem pessoas (José ≠ Maria; José com e sem acento = 1)
    cpfs = sorted(f for f in favs if "*" in f[2])
    assert [f[1] for f in cpfs] == ["JOSE DA SILVA", "MARIA SOUZA"]
    assert [f[0] for f in cpfs] == ["cpf:158308|JOSE DA SILVA", "cpf:158308|MARIA SOUZA"]
    jose = [l for l in decodificar(cubo) if l["favorecido"][1] == "JOSE DA SILVA"]
    assert round(sum(l["pago"] for l in jose), 2) == 770.0
    # o documento sai como a origem publica (mascarado) — nada além do que dados/mov/ já mostra
    assert all(f[2] == "***.158.308-**" for f in cpfs)


def test_bytes_deterministicos_independem_da_ordem_de_insercao(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    gerar(cenario(), a, monkeypatch)
    gerar(cenario(ordem=7), b, monkeypatch)
    for ano in (2025, 2026):
        assert (a / "cubo" / f"{ano}.json").read_bytes() == (b / "cubo" / f"{ano}.json").read_bytes()
    # 2ª execução com o mesmo dado: não regrava (os bytes já são os mesmos)
    arq = a / "cubo" / "2025.json"
    antes = arq.stat().st_mtime_ns
    import os
    os.utime(arq, ns=(antes - 10_000_000_000, antes - 10_000_000_000))
    gerar(cenario(ordem=3), a, monkeypatch)
    assert arq.stat().st_mtime_ns == antes - 10_000_000_000


def test_dicionario_ida_e_volta_e_ano_removido(tmp_path, monkeypatch):
    conn = cenario()
    gerar(conn, tmp_path, monkeypatch)
    cubo = ler(tmp_path, 2026)
    assert cubo["versao"] == 1 and cubo["ano"] == 2026 and cubo["campos"] == export.CAMPOS_CUBO
    assert set(cubo["dicionario"]) == set(export.CUBO_DICIONARIO)
    # todo índice aponta para dentro do dicionário e decodifica para o valor da origem
    for lin in cubo["linhas"]:
        for c, valores in cubo["dicionario"].items():
            assert 0 <= lin[cubo["campos"].index(c)] < len(valores)
    linhas = sorted(decodificar(cubo), key=lambda l: -l["pago"])
    assert [(l["mes"], l["tipo"], l["funcao"], l["elemento_despesa"], l["pago"], l["n"]) for l in linhas] == [
        (2, "Orçamentário", "10 - SAÚDE", "33903999000 - OUTROS SERVIÇOS", 1234.56, 1),
        (2, "Empenho não localizado na base", "10 - SAÚDE", "33903999000 - OUTROS SERVIÇOS", 0.01, 1)]
    assert linhas[0]["unidade_gestora"] == PMS
    assert linhas[0]["favorecido"] == ["cnpj:12345678000190", "ACME SERVIÇOS LTDA", "12.345.678/0001-90"]
    # valor inteiro sai como inteiro; centavos exatos (sem 0.30000000000000004)
    assert all(isinstance(l[-2], (int, float)) for l in ler(tmp_path, 2025)["linhas"])
    assert '"linhas":[[' in (tmp_path / "cubo" / "2025.json").read_text(encoding="utf-8")
    # ano que sumiu da base sai da pasta
    conn.execute("DELETE FROM pagamentos WHERE ano = 2026")
    conn.commit()
    man, _ = gerar(conn, tmp_path, monkeypatch)
    assert [m["ano"] for m in man] == [2025] and not (tmp_path / "cubo" / "2026.json").exists()


def test_verificar_confere_cubos_contra_indice(tmp_path, monkeypatch):
    conn = cenario()
    dados = tmp_path / "despesas" / "dados"
    dados.mkdir(parents=True)
    man, _ = gerar(conn, dados, monkeypatch)
    idx = {"totais": {"por_ano": {str(r["ano"]): round(r["s"], 2) for r in conn.execute(
               "SELECT ano, SUM(valor) s FROM pagamentos GROUP BY ano")}},
           "series_mensais": [{"ano": r["ano"], "mes": r["mes"], "valor": round(r["s"], 2)} for r in conn.execute(
               "SELECT ano, mes, SUM(valor) s FROM pagamentos GROUP BY ano, mes")],
           "cubos": man}
    assert verificar.verificar_cubos(str(tmp_path), idx) == []
    # pago adulterado no arquivo → conservação e série mensal acusam
    arq = dados / "cubo" / "2025.json"
    cubo = json.loads(arq.read_text(encoding="utf-8"))
    cubo["linhas"][0][-2] += 10
    arq.write_text(json.dumps(cubo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    falhas = verificar.verificar_cubos(str(tmp_path), idx)
    assert any("2025" in f and "índice" in f for f in falhas) and any("série" in f for f in falhas)
    # ano do índice sem cubo, e manifesto com arquivo ausente
    falhas = verificar.verificar_cubos(str(tmp_path), dict(idx, cubos=[m for m in man if m["ano"] == 2026]))
    assert any("sem cubo" in f for f in falhas)
    (dados / "cubo" / "2026.json").unlink()
    assert any("ausente" in f for f in verificar.verificar_cubos(str(tmp_path), idx))
    # índice antigo (sem `cubos`): não é falha — o explorador ainda não foi publicado
    assert verificar.verificar_cubos(str(tmp_path), {"totais": idx["totais"]}) == []
