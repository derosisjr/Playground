"""Reconciliação por partição (crawler v2): recarga idempotente, correções,
exclusões, respostas suspeitas/inválidas, interrupção e duplicidade sistemática."""
import json
import sqlite3

import pytest

import crawler


class Conexao(sqlite3.Connection):
    """Subclasse só para o monkeypatch de métodos nos testes de interrupção."""


def db():
    conn = sqlite3.connect(":memory:", factory=Conexao)
    conn.executescript(crawler._schema())
    return conn


def item(i, valor=100.0, **kw):
    base = {
        "unidade_gestora": "PREFEITURA MUNICIPAL DE SANTOS",
        "data": "2026-03-10T00:00:00", "especie": "Original",
        "empenho": f"{i:07d}/2026", "liquidacao": f"{i:07d}/2026", "pagamento": f"{i:07d}/2026",
        "tipo_pagamento": "Orçamentária",
        "elemento_despesa": "339039 - OUTROS SERVIÇOS", "subtitulo": "",
        "funcao": "10 - SAÚDE", "subfuncao": "301 - Atenção Básica", "programa": "P",
        "fonte_recurso": "TESOURO", "grupo_despesa": "33 - OUTRAS DESPESAS CORRENTES",
        "documento_favorecido": "12.345.678/0001-90", "nome_favorecido": f"FORNECEDOR {i} LTDA",
        "valor": valor,
    }
    base.update(kw)
    return base


def carga(conn, dados, **kw):
    itens, _ = crawler.normalizar("pagamentos", 2026, 3, dados)
    return crawler.reconciliar(conn, "pagamentos", 2026, 3, itens, **kw)


def estado(conn):
    r = conn.execute("SELECT COUNT(*), COALESCE(SUM(valor),0) FROM pagamentos WHERE ano=2026 AND mes=3").fetchone()
    return r[0], round(r[1], 2)


def test_recarga_identica_e_idempotente():
    conn = db()
    dados = [item(i) for i in range(10)]
    r1 = carga(conn, dados)
    r2 = carga(conn, dados)
    assert (r1["adicionados"], r1["removidos"]) == (10, 0)
    assert (r2["adicionados"], r2["removidos"], r2["alterados"]) == (0, 0, 0)
    assert estado(conn) == (10, 1000.0)
    assert conn.execute("SELECT COUNT(*) FROM linhas_historico").fetchone()[0] == 0


def test_correcao_de_valor_100_para_80_resulta_em_80():
    conn = db()
    dados = [item(i) for i in range(10)]
    carga(conn, dados)
    dados[0]["valor"] = 80.0
    r = carga(conn, dados)
    assert r["alterados"] == 1 and r["adicionados"] == 1 and r["removidos"] == 0
    assert estado(conn) == (10, 980.0)          # e não 1080 (v1 somava as duas versões)
    v = conn.execute("SELECT valor FROM pagamentos WHERE pagamento='0000000/2026'").fetchall()
    assert v == [(80.0,)]
    # histórico separado guarda a versão anterior sem duplicar a visão corrente
    h = conn.execute("SELECT motivo, conteudo FROM linhas_historico").fetchall()
    assert len(h) == 1 and h[0][0] == "substituido"
    assert json.loads(h[0][1])["valor"] == 100.0


def test_correcao_de_classificacao_e_aplicada():
    conn = db()
    dados = [item(i) for i in range(10)]
    carga(conn, dados)
    dados[3]["elemento_despesa"] = "339030 - MATERIAL DE CONSUMO"
    dados[3]["funcao"] = "12 - EDUCAÇÃO"
    carga(conn, dados)
    r = conn.execute("SELECT elemento_despesa, funcao FROM pagamentos WHERE pagamento='0000003/2026'").fetchall()
    assert r == [("339030 - MATERIAL DE CONSUMO", "12 - EDUCAÇÃO")]
    assert estado(conn)[0] == 10


def test_exclusao_legitima_e_refletida():
    conn = db()
    dados = [item(i) for i in range(10)]
    carga(conn, dados)
    r = carga(conn, dados[1:])              # a origem retirou um lançamento
    assert r["removidos"] == 1
    assert estado(conn) == (9, 900.0)
    h = conn.execute("SELECT motivo, conteudo FROM linhas_historico").fetchall()
    assert h[0][0] == "removido" and json.loads(h[0][1])["pagamento"] == "0000000/2026"


def test_resposta_vazia_suspeita_nao_apaga_dados():
    conn = db()
    carga(conn, [item(i) for i in range(10)])
    with pytest.raises(crawler.ParticaoSuspeita):
        carga(conn, [])
    assert estado(conn) == (10, 1000.0)
    st = conn.execute("SELECT status, registros FROM controle_carga").fetchone()
    assert st == ("suspeito", 10)          # tentativa registrada, conteúdo intacto
    # a exclusão explícita de todo o mês exige a bandeira
    carga(conn, [], aceitar_vazio=True)
    assert estado(conn) == (0, 0.0)


def test_queda_abrupta_e_suspeita_salvo_bandeira():
    conn = db()
    dados = [item(i) for i in range(10)]
    carga(conn, dados)
    with pytest.raises(crawler.ParticaoSuspeita):
        carga(conn, dados[:5])
    assert estado(conn) == (10, 1000.0)
    carga(conn, dados[:5], aceitar_reducao=True)
    assert estado(conn) == (5, 500.0)


def test_resposta_invalida_e_rejeitada_antes_de_gravar():
    assert crawler.validar_resposta("pagamentos", 2026, 3, {"erro": "x"})
    assert crawler.validar_resposta("pagamentos", 2026, 3, [{"valor": 1}])            # sem UG/data
    assert crawler.validar_resposta("pagamentos", 2026, 3, [item(1, valor="abc")])
    fora = [item(i, data="2026-04-01T00:00:00") for i in range(5)] + [item(9)]
    assert crawler.validar_resposta("pagamentos", 2026, 3, fora)                     # datas de abril
    assert crawler.validar_resposta("pagamentos", 2026, 3, [item(i) for i in range(5)]) == []
    assert crawler.validar_resposta("pagamentos", 2026, 3, []) == []                  # vazia é válida


def test_interrupcao_nao_deixa_particao_parcial(monkeypatch):
    conn = db()
    dados = [item(i) for i in range(10)]
    carga(conn, dados)
    original = conn.executemany

    def explode(*a, **k):
        raise RuntimeError("queda no meio da gravação")
    monkeypatch.setattr(conn, "executemany", explode)
    with pytest.raises(RuntimeError):
        carga(conn, dados[1:] + [item(99, valor=5.0)])
    monkeypatch.setattr(conn, "executemany", original)
    assert estado(conn) == (10, 1000.0)                        # versão anterior íntegra
    assert conn.execute("SELECT COUNT(*) FROM linhas_historico").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM historico_reconciliacao").fetchone()[0] == 1
    assert not conn.in_transaction


def test_conferencia_pos_gravacao_aborta_em_divergencia(monkeypatch):
    conn = db()
    carga(conn, [item(i) for i in range(3)])
    real = crawler._estado_particao
    chamadas = []

    def falso(c, fonte, ano, mes):
        chamadas.append(1)
        r = real(c, fonte, ano, mes)
        # 1ª = validação, 2ª = "antes", 3ª = conferência pós-gravação → diverge
        return dict(r, n=r["n"] + 1) if len(chamadas) >= 3 else r
    monkeypatch.setattr(crawler, "_estado_particao", falso)
    with pytest.raises(RuntimeError):
        carga(conn, [item(i, valor=100.0, subtitulo="x") for i in range(3)])
    monkeypatch.setattr(crawler, "_estado_particao", real)
    assert estado(conn) == (3, 300.0)


def test_linhas_identicas_esporadicas_sao_mantidas():
    # lote de depósitos judiciais: mesmo documento, dois itens de valor igual
    dados = [item(i) for i in range(10)] + [item(3), item(3)]
    itens, _ = crawler.normalizar("pagamentos", 2026, 3, dados)
    efetivos, descartados, diag = crawler.tratar_duplicidade(itens)
    assert len(efetivos) == 12 and not descartados
    assert diag["identicas"] == 2 and diag["sistematica"] == []
    conn = db()
    r = crawler.reconciliar(conn, "pagamentos", 2026, 3, itens)
    assert estado(conn) == (12, 1200.0)
    assert r["descartados"] == 0


def test_duplicidade_sistematica_da_origem_e_reduzida_e_registrada():
    # toda a UG Prefeitura do dia devolvida 2× (defeito observado em jan–mai/2026),
    # inclusive um grupo ×4 (fica 1 linha e conta em `multiplas`); outra UG sem
    # duplicação fica intacta
    base = [item(i) for i in range(10)] + [item(3)]
    outra = [item(50 + i, unidade_gestora="CAPEP") for i in range(3)]
    dados = base + base + outra
    itens, _ = crawler.normalizar("pagamentos", 2026, 3, dados)
    efetivos, descartados, diag = crawler.tratar_duplicidade(itens)
    assert len(efetivos) == 13 and len(descartados) == 12
    assert diag["sistematica"][0]["fator"] == 2 and diag["sistematica"][0]["descartadas"] == 12
    assert diag["multiplas"] == 1
    assert sum(1 for e in efetivos if e["pagamento"] == "0000003/2026") == 1
    conn = db()
    r = crawler.reconciliar(conn, "pagamentos", 2026, 3, itens)
    assert r["descartados"] == 12 and estado(conn) == (13, 1300.0)
    cc = conn.execute("SELECT brutos, registros, descartados, duplicidade FROM controle_carga").fetchone()
    assert (cc[0], cc[1], cc[2]) == (25, 13, 12)
    assert json.loads(cc[3])["sistematica"][0]["ug"] == "PREFEITURA MUNICIPAL DE SANTOS"
    assert conn.execute("SELECT COUNT(*) FROM linhas_historico WHERE motivo='duplicidade_sistematica'").fetchone()[0] == 12
    # a origem corrigir a duplicação NÃO dispara a guarda de queda abrupta (o par legítimo
    # volta a aparecer, já que o mês deixa de ser sistemático)
    itens2, _ = crawler.normalizar("pagamentos", 2026, 3, base + outra)
    r2 = crawler.reconciliar(conn, "pagamentos", 2026, 3, itens2)
    assert (r2["adicionados"], r2["removidos"]) == (1, 0) and estado(conn) == (14, 1400.0)


def test_migracao_v1_recria_tabelas():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE controle_carga (fonte TEXT, ano INTEGER, mes INTEGER, registros INTEGER,
            soma REAL, baixado_em TEXT, PRIMARY KEY (fonte, ano, mes));
        CREATE TABLE pagamentos (id INTEGER PRIMARY KEY, hash TEXT UNIQUE, ano INTEGER, mes INTEGER,
            unidade_gestora TEXT, valor REAL);
        INSERT INTO pagamentos VALUES (1, 'h', 2025, 1, 'PMS', 10);
        INSERT INTO controle_carga VALUES ('pagamentos', 2025, 1, 1, 10, 'x');""")
    assert crawler._versao_schema(conn) == 1
    crawler.migrar_v1(conn, None)
    conn.executescript(crawler._schema())
    assert crawler._versao_schema(conn) == 2
    assert crawler.carregados(conn) == set()      # tudo será reconciliado de novo
    assert conn.execute("SELECT COUNT(*) FROM pagamentos").fetchone()[0] == 0


def test_duplicidade_sistematica_por_particao_atravessa_dias():
    # padrão de jan–mai/2026: lotes repetidos espalhados por vários dias (32–54% das
    # linhas de cada dia), sem nenhum dia inteiramente duplicado
    dados = []
    for i in range(300):
        dia = 1 + (i % 10)
        dados.append(item(i, data=f"2026-03-{dia:02d}T00:00:00"))
    repetidos = [d for d in dados if int(d["pagamento"][:7]) % 3 == 0]    # 100 de 300 (33%)
    dados = dados + repetidos
    itens, _ = crawler.normalizar("pagamentos", 2026, 3, dados)
    efetivos, descartados, diag = crawler.tratar_duplicidade(itens)
    assert diag["sistematica"] == []                      # nenhum dia passa de 90%
    assert diag["particao"] and diag["particao"]["fator"] == 2 and diag["particao"]["descartadas"] == 100
    assert len(efetivos) == 300 and len(descartados) == 100
    # abaixo do piso (poucas repetições) nada é descartado
    poucos = [item(i) for i in range(300)] + [item(i) for i in range(10)]
    itens2, _ = crawler.normalizar("pagamentos", 2026, 3, poucos)
    ef2, desc2, diag2 = crawler.tratar_duplicidade(itens2)
    assert diag2["particao"] is None and len(ef2) == 310 and not desc2
