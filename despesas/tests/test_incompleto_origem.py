"""Mês incompleto na origem (conciliação com o TCE-SP, 2026-10): jan/2025 tem R$ 69 mi
empenhados no portal e R$ 2,93 bi no TCE. O mês é MARCADO — sai das comparações e vira
alerta de dados — e nunca preenchido com o dado do Tribunal."""
from datetime import date

import export
import tce
import verificar
from test_export import add, db

CRESCE = {"nome_favorecido": "CRESCE EM JANEIRO LTDA", "documento_favorecido": "44.444.444/0001-44"}
ESTAVEL = {"nome_favorecido": "ESTAVEL LTDA", "documento_favorecido": "55.555.555/0001-55"}


# ── tce.py: totais do mês e estado versionado ─────────────────────────────────
def test_totais_mes_sem_camara_valores_br_e_anulacao():
    itens = [
        {"orgao": "PREFEITURA MUNICIPAL DE SANTOS", "evento": "Empenhado", "vl_despesa": "1.000,50"},
        {"orgao": "PREFEITURA MUNICIPAL DE SANTOS", "evento": "Reforço", "vl_despesa": "100,00"},
        {"orgao": "FUNDAÇÃO PRÓ-ESPORTE DE SANTOS", "evento": "Anulação", "vl_despesa": "50,50"},
        {"orgao": "PREFEITURA MUNICIPAL DE SANTOS", "evento": "Valor Liquidado", "vl_despesa": "800,00"},
        {"orgao": "PREFEITURA MUNICIPAL DE SANTOS", "evento": "Valor Liquidado", "vl_despesa": "-10,00"},
        {"orgao": "PREFEITURA MUNICIPAL DE SANTOS", "evento": "Valor Pago", "vl_despesa": "700,00"},
        {"orgao": "CÂMARA MUNICIPAL DE SANTOS", "evento": "Empenhado", "vl_despesa": "9.999,00"},
    ]
    t = tce.totais_mes(itens)
    assert t == {"empenhado": 1050.0, "liquidado": 790.0, "pago": 700.0, "registros": 6}
    assert tce.totais_mes([{"orgao": "X", "evento": "Estorno", "vl_despesa": "1,00"}])["outros"] == 1


def test_meses_alvo_faltantes_e_recentes():
    estado = {"meses": {f"2025-{m:02d}": {} for m in range(1, 8)}}
    alvo = tce.meses_alvo(estado, False, date(2025, 10, 15))
    assert alvo == [(2025, 5), (2025, 6), (2025, 7), (2025, 8), (2025, 9)]   # 3 recentes + 2 sem referência
    assert len(tce.meses_alvo(estado, True, date(2025, 10, 15))) == 9       # jan–set (out = corrente)


def test_atualizar_sem_mudanca_mantem_obtido_em_e_falha_mantem_anterior(monkeypatch):
    itens = [{"orgao": "P", "evento": "Empenhado", "vl_despesa": "10,00"}]
    estado = {"versao": 1, "meses": {"2025-01": {**tce.totais_mes(itens), "obtido_em": "2026-01-01"}}}

    def baixar(ano, mes):
        if mes == 2:
            raise OSError("fora do ar")
        return itens if mes == 1 else []

    monkeypatch.setattr(tce, "baixar", baixar)
    monkeypatch.setattr(tce, "PAUSA", 0)
    novo, msgs = tce.atualizar(estado, [(2025, 1), (2025, 2), (2025, 3)], date(2026, 10, 30))
    assert novo["meses"] == estado["meses"]                      # mesmo valor = mesmo arquivo
    assert any("2025-02: falha" in m for m in msgs) and any("2025-03: sem dados" in m for m in msgs)


# ── export: conciliação e marcação ────────────────────────────────────────────
def cenario():
    """2025 e 2026 com jan/2025 incompleto na origem (TCE muito acima da base)."""
    conn = db()
    for ano in (2025, 2026):
        for mes in range(1, 13 if ano == 2025 else 4):
            add(conn, "empenhos", ano, mes, 1_000.0, empenho=f"{mes:07d}/{ano}")
            add(conn, "liquidacoes", ano, mes, 800.0, empenho=f"{mes:07d}/{ano}")
            add(conn, "pagamentos", ano, mes, 100_000.0, **ESTAVEL)
    add(conn, "liquidacoes", 2025, 3, 5_000.0, tipo_liquidacao="Restos à Pagar")   # o TCE não conta restos
    add(conn, "pagamentos", 2026, 1, 900_000.0, **CRESCE)    # cresce só em jan/2026 (jan/2025 faltou)
    add(conn, "pagamentos", 2025, 3, 100_000.0, **CRESCE)
    add(conn, "pagamentos", 2026, 3, 120_000.0, **CRESCE)
    add(conn, "pagamentos", 2026, 5, 1.0, data="2026-05-05")   # base "fresca": mar/2026 completo
    add(conn, "empenhos", 2026, 5, 10.0, data="2026-05-05", empenho="0000005/2026")
    tce_meses = {f"{a}-{m:02d}": {"empenhado": 1_000.0, "liquidado": 800.0, "pago": 0, "obtido_em": "2026-10-30"}
                 for a in (2025, 2026) for m in range(1, 13 if a == 2025 else 3)}
    tce_meses["2025-01"] = {"empenhado": 3_000_000.0, "liquidado": 2_500_000.0, "pago": 0, "obtido_em": "2026-10-30"}
    return conn, tce_meses


def _cob(conn, tce_meses):
    cob = export.cobertura(conn)
    cob["conciliacao_tce"] = export.conciliacao_tce(conn, tce_meses)
    cob["incompletos_origem"] = cob["conciliacao_tce"]["incompletos"]
    return cob


def test_conciliacao_status_por_mes_e_restos_fora():
    conn, tce_meses = cenario()
    conc = export.conciliacao_tce(conn, tce_meses)
    st = {m["periodo"]: m["status"] for m in conc["meses"]}
    assert conc["incompletos"] == ["2025-01"] and conc["acima"] == []
    assert st["2025-03"] == "ok"                 # a liquidação de restos não conta contra o TCE
    assert st["2026-03"] == "sem_referencia"     # o TCE ainda não recebeu o mês
    assert st["2026-05"] == "parcial"            # posterior ao último mês completo
    jan = next(m for m in conc["meses"] if m["periodo"] == "2025-01")
    assert jan["dif_pct"]["empenhado"] < -99 and jan["tce"]["empenhado"] == 3_000_000.0
    # sem arquivo do TCE: nada é marcado (sem referência ≠ incompleto)
    assert export.conciliacao_tce(conn, {})["incompletos"] == []


def test_resumo_compara_so_meses_comparaveis():
    conn, tce_meses = cenario()
    indice = export.agregados(conn)
    indice["cobertura"] = _cob(conn, tce_meses)
    indice["alertas"] = []
    r = export.resumo_narrativo(conn, indice)
    assert r["yoy"]["periodo"] == "fev–mar" and r["yoy"]["excluidos"] == ["2025-01"]
    assert r["yoy"]["atual"] == 320_000.0 and r["yoy"]["anterior"] == 300_000.0
    assert "No acumulado comparável de 2026 (fev–mar)" in r["texto"]
    assert "Jan/2025 foi publicado incompleto pela Prefeitura (conferido com o TCE-SP)" in r["texto"]


def test_crescimento_e_pico_ignoram_mes_incompleto():
    conn, tce_meses = cenario()
    sem = [a for a in export.alertas(conn) if a["tipo"] == "crescimento_yoy"]
    assert [a["titulo"] for a in sem] == ["Crescimento no mesmo período: CRESCE EM JANEIRO LTDA"]   # jan–mar: 10×
    com = export.alertas(conn, cob=_cob(conn, tce_meses))
    assert not [a for a in com if a["tipo"] == "crescimento_yoy"]     # fev–mar: 120 mil × 100 mil
    assert not [a for a in com if a["tipo"] == "pico_mensal" and a["filtro"] == {"ano": 2025, "mes": 1}]


def test_alerta_de_dados_e_taxa_nao_validada():
    conn, tce_meses = cenario()
    cob = _cob(conn, tce_meses)
    al = [a for a in export.alertas(conn, cob=cob) if a["tipo"] == "dados_incompleto_origem"]
    assert len(al) == 1 and al[0]["classe"] == export.CLASSE_INCONSISTENCIA
    assert "jan/2025" in al[0]["titulo"] and "R$ 3.000.000,00" in al[0]["detalhe"]
    exe = export.execucao_agregada(conn, cob)
    assert exe["por_ano"]["2025"]["taxa_validada"] is False
    assert "jan/2025 incompleto na origem" in exe["por_ano"]["2025"]["taxa_motivos"][0]
    assert not any("incompleto" in m for m in exe["por_ano"]["2026"].get("taxa_motivos", []))


def test_fim_de_exercicio_media_sem_mes_incompleto():
    conn, tce_meses = cenario()
    f = export.fim_de_exercicio(conn, _cob(conn, tce_meses))["2025"]
    assert f["meses_excluidos"] == ["2025-01"]
    assert f["pago"]["media_jan_nov"] == 110_000.0     # fev–nov (mar tem o pagamento do CRESCE)
    assert "meses_excluidos" not in export.fim_de_exercicio(conn)["2025"]


# ── verificar.py ──────────────────────────────────────────────────────────────
def test_verificar_conciliacao_aponta_mes_incompleto_comparado():
    idx = {"cobertura": {"incompletos_origem": ["2025-01"],
                         "conciliacao_tce": {"meses": [{"periodo": "2025-01", "status": "incompleto"}], "acima": []}},
           "resumo": {"mes_ref": {"ano": 2026, "mes": 3}, "yoy": {"pct": 10}},
           "fim_de_exercicio": {"2025": {}}, "alertas": []}
    falhas = verificar.verificar_conciliacao(idx)
    assert any("acumulado do ano compara" in f for f in falhas)
    assert any("fim de exercício 2025" in f for f in falhas)
    assert any("sem alerta de dados" in f for f in falhas)
    idx["resumo"]["yoy"]["excluidos"] = ["2025-01"]
    idx["fim_de_exercicio"]["2025"]["meses_excluidos"] = ["2025-01"]
    idx["alertas"] = [{"tipo": "dados_incompleto_origem", "filtro": {"ano": 2025, "mes": 1}}]
    assert verificar.verificar_conciliacao(idx) == []
    assert verificar.verificar_conciliacao({}) == []      # índice anterior à conciliação
