"""Outras operações da API do portal (2026-10): contratos e convênios (raio-X, fracionamento,
ranking), emendas, ordem cronológica — e o orçamento × execução do RREO (SICONFI)."""
import json
import random
from datetime import date

import export
import instrumentos
import orcamento
from test_export import add, db

CNPJ = "11.222.333/0001-81"
CNPJ_DIG = "11222333000181"


# ── instrumentos.py ───────────────────────────────────────────────────────────
def _api(respostas):
    """operacao() falsa: devolve a lista do (op, ano[, mes]) pedido."""
    return lambda op, **q: respostas.get((op, q.get("ano"), q.get("mes")), [])


def test_contratos_so_cnpj_pf_contado_emergencial_incluido(monkeypatch):
    monkeypatch.setattr(instrumentos, "ANO_CONTRATOS", 2026)
    longo = "Objeto " + "x" * 400
    monkeypatch.setattr(instrumentos, "operacao", _api({
        ("json_contratos", 2026, None): [
            {"contrato": "1/2026", "processo": "P1", "assinatura": "2026-02-03T00:00:00",
             "documento_favorecido": CNPJ, "valor": "1000.5", "situacao": "Vigente", "categoria": "Diversos",
             "objeto": longo},
            {"contrato": "2/2026", "documento_favorecido": "***.123.456-**", "objeto": "Locação de imóvel"},
            {"contrato": "3/2026", "documento_favorecido": "1", "objeto": "Lixo da origem"}],
        ("json_contratos_emergenciais", 2026, None): [
            {"contrato": "9/2026", "processo": "P9", "assinatura": "2026-09-04T00:00:00", "documento": CNPJ,
             "valor": "23820.0", "modalidade": "Dispensa Nº 1/2026", "inicio": "2026-09-04T00:00:00",
             "termino": "2026-12-04T00:00:00", "objeto": "Reparo emergencial"}],
    }))
    por_cnpj, resumo = instrumentos.coletar_contratos(date(2026, 10, 30))
    assert list(por_cnpj) == [CNPJ_DIG]
    c, e = por_cnpj[CNPJ_DIG]
    assert c[2] == "2026-02-03" and c[3] == 1000.5 and len(c[6]) == instrumentos.OBJETO_MAX and c[6].endswith("…")
    assert e[7] == "emergencial" and "vigência 2026-09-04 a 2026-12-04" in e[4]
    assert resumo == {"desde": 2026, "por_ano": {"2026": 3}, "pf_omitidos": 1, "sem_documento": 1}


def test_fatias_por_prefixo_mesmo_dado_mesmos_bytes(tmp_path):
    contratos = {CNPJ_DIG: [["2/2025", "P2", "2025-01-02", 1.0, "", "", "a", "contrato"],
                            ["1/2026", "P1", "2026-02-03", 2.0, "", "", "b", "contrato"]],
                 "99000000000100": [["7/2024", "P7", "2024-07-07", 3.0, "", "", "c", "contrato"]]}
    convenios = {CNPJ_DIG: [["C1", "2025-05-05", 10.0, "Concedido", "termo"]]}
    instrumentos.gravar_fatias(instrumentos._ordenar(contratos, convenios), str(tmp_path / "a"))
    embaralhado = {k: random.Random(3).sample(v, len(v)) for k, v in reversed(list(contratos.items()))}
    instrumentos.gravar_fatias(instrumentos._ordenar(embaralhado, convenios), str(tmp_path / "b"))
    for nome in ("11.json", "99.json"):
        assert (tmp_path / "a" / nome).read_bytes() == (tmp_path / "b" / nome).read_bytes()
    f = json.loads((tmp_path / "a" / "11.json").read_text(encoding="utf-8"))
    assert [l[0] for l in f["cnpj"][CNPJ_DIG]["c"]] == ["1/2026", "2/2025"]      # mais recente primeiro
    assert f["cnpj"][CNPJ_DIG]["v"][0][0] == "C1"
    # fatia que deixou de existir é apagada
    instrumentos.gravar_fatias(instrumentos._ordenar({CNPJ_DIG: contratos[CNPJ_DIG]}, {}), str(tmp_path / "a"))
    assert sorted(p.name for p in (tmp_path / "a").iterdir()) == ["11.json"]


def test_emendas_ordenadas_e_resumo(monkeypatch):
    monkeypatch.setattr(instrumentos, "ANO_INICIAL", 2026)
    monkeypatch.setattr(instrumentos, "operacao", _api({("json_emendas_parlamentares", 2026, None): [
        {"numero": "2", "origem": "Municipal", "autor": "B", "descricao": "Praça", "valor": "100.0"},
        {"numero": "1", "origem": "Municipal", "autor": None, "descricao": "EMENDA 1", "valor": "50.0"},
        {"numero": "3", "origem": "Federal", "autor": "A", "descricao": "Academia", "valor": "10.0"}]}))
    anos, resumo = instrumentos.coletar_emendas(date(2026, 10, 30))
    assert [l[2] for l in anos["2026"]] == ["A", "B", None]          # sem autor por último
    assert resumo["2026"] == {"emendas": 3, "valor": 160.0, "por_origem": {"Federal": 1, "Municipal": 2},
                              "sem_autor": 1}


def test_arquivos_do_portal_ficam_fora_da_pasta_do_export():
    # exportar_detalhe_mensal apaga todo .json de despesas/dados/ que não é dele: o que o
    # instrumentos.py grava lá sumiria no export seguinte (e o commit apagaria do repo)
    import os
    dados = os.path.normcase(os.path.abspath(export.DADOS_DIR)) + os.sep
    for caminho in (instrumentos.CONTRATOS_DIR, instrumentos.EMENDAS_PATH, instrumentos.RESUMO_PATH,
                    export.CONTRATOS_DIR):
        assert not os.path.normcase(os.path.abspath(caminho)).startswith(dados), caminho
    assert os.path.normcase(export.CONTRATOS_DIR) == os.path.normcase(instrumentos.CONTRATOS_DIR)


def test_ordem_cronologica_desde_so_muda_com_o_estado():
    hoje = date(2026, 11, 2)
    ant = {"registros": {"2025": 0, "2026": 0}, "desde": "2026-10-30"}
    assert instrumentos.estado_ordem({"2025": 0, "2026": 0}, ant, hoje)["desde"] == "2026-10-30"
    assert instrumentos.estado_ordem({"2025": 0, "2026": 12}, ant, hoje)["desde"] == "2026-11-02"
    assert instrumentos.estado_ordem({"2026": 0}, None, hoje)["pagina_conferida_em"] == instrumentos.PAGINA_OC_CONFERIDA


# ── orcamento.py (RREO Anexo 02) ──────────────────────────────────────────────
def test_rreo_soma_funcoes_exceto_intra_mais_intra_e_ignora_subfuncao():
    def item(conta, coluna, valor, cod="RREO2TotalDespesas"):
        return {"conta": conta, "coluna": coluna, "valor": valor, "cod_conta": cod}
    itens = [item("DESPESAS (EXCETO INTRA-ORÇAMENTÁRIAS) (I)", "DOTAÇÃO ATUALIZADA (a)", 999.0),
             item("Saúde", "DOTAÇÃO ATUALIZADA (a)", 100.0), item("Atenção Básica", "DOTAÇÃO ATUALIZADA (a)", 60.0),
             item("Saúde", "DOTAÇÃO ATUALIZADA (a)", 10.0, "RREO2TotalDespesasIntra"),
             item("Saúde", "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)", 55.0),
             item("Saúde", "% (d/total d)", 20.0),
             item("FU10 - Administração Geral", "DOTAÇÃO ATUALIZADA (a)", 5.0),
             item("Educação", "DOTAÇÃO INICIAL", 80.0), item("Educação", "DOTAÇÃO ATUALIZADA (a)", 90.0)]
    fns = orcamento.por_funcao(itens)
    assert [f["codigo"] for f in fns] == ["10", "12"]          # pela dotação atualizada
    assert fns[0]["dotacao_atualizada"] == 110.0 and fns[0]["liquidado"] == 55.0
    assert fns[1]["dotacao_inicial"] == 80.0


# ── export: contratos no ranking, no dossiê e no fracionamento ────────────────
def _fatias(tmp_path, contratos):
    instrumentos.gravar_fatias(instrumentos._ordenar(contratos, {}), str(tmp_path))
    return export.contratos_portal(str(tmp_path))


def test_contratos_no_ranking_e_no_dossie(tmp_path, monkeypatch):
    ctr = _fatias(tmp_path / "ctr", {CNPJ_DIG: [["1/2025", "P1", "2025-01-10", 9.0, "", "", "Serviço", "contrato"]]})
    conn = db()
    add(conn, "pagamentos", 2025, 3, 500.0, nome_favorecido="COM CONTRATO LTDA", documento_favorecido=CNPJ)
    add(conn, "pagamentos", 2025, 3, 400.0, nome_favorecido="SEM CONTRATO LTDA", documento_favorecido="22.333.444/0001-55")
    add(conn, "pagamentos", 2025, 3, 300.0, nome_favorecido="PESSOA", documento_favorecido="***.111.222-**")
    ident = export.preparar_identidades(conn)
    idx = export.agregados(conn, ident, ctr)
    por = {f["nome"]: f for f in idx["top_favorecidos"]}
    assert (por["COM CONTRATO LTDA"]["contratos"], por["COM CONTRATO LTDA"]["convenios"]) == (1, 0)
    assert por["SEM CONTRATO LTDA"]["contratos"] == 0                 # CNPJ conferido, nada publicado
    assert "contratos" not in por["PESSOA"]                           # CPF: sem contagem
    assert "contratos" not in export.agregados(conn, ident)["top_favorecidos"][0]   # sem os arquivos
    monkeypatch.setattr(export, "FAV_DIR", str(tmp_path / "fav"))
    idx["alertas"] = []
    export.exportar_favorecidos(conn, idx, ident, ctr)
    d = json.loads((tmp_path / "fav" / f"{CNPJ_DIG}.json").read_text(encoding="utf-8"))
    assert d["contratos_total"] == 1 and d["contratos"][0]["objeto"] == "Serviço" and d["convenios"] == []


def test_fracionamento_com_contrato_publicado_vai_para_o_fim(tmp_path):
    conn = db()
    for mes in (3, 4, 5, 6):
        add(conn, "empenhos", 2025, mes, 50_000.0, empenho=f"00000{mes}/2025",
            nome_favorecido="CONTRATADA LTDA", documento_favorecido=CNPJ)
        add(conn, "empenhos", 2025, mes, 40_000.0, empenho=f"00001{mes}/2025",
            nome_favorecido="SEM NADA LTDA", documento_favorecido="22.333.444/0001-55")
    # contrato assinado antes dos empenhos (na janela) e outro DEPOIS (não conta)
    ctr = _fatias(tmp_path, {CNPJ_DIG: [["10/2025", "P10", "2025-02-01", 300_000.0, "Vigente", "", "Obra X", "contrato"],
                                        ["11/2025", "P11", "2025-12-01", 1.0, "", "", "Depois", "contrato"]]})
    cands = [a for a in export.candidatos_alertas(conn, cob={"particoes": [], "faltantes": [], "com_erro": []},
                                                  espelho={}, contratos=ctr) if a["tipo"] == "fracionamento"]
    com = next(a for a in cands if "CONTRATADA" in a["titulo"])
    sem = next(a for a in cands if "SEM NADA" in a["titulo"])
    assert com["contrato"]["contrato"] == "10/2025" and com["contrato_alcance"] == [4, 4]
    assert "Portal: há contrato publicado com este CNPJ" in com["detalhe"] and "01/02/2025" in com["detalhe"]
    assert "contrato" not in sem
    assert export._prioridade_publicacao(com) > export._prioridade_publicacao(sem)   # com contrato: fim da fila
    # sem os arquivos do portal (export antigo), nada muda
    sem_arq = [a for a in export.candidatos_alertas(conn, cob={"particoes": [], "faltantes": [], "com_erro": []},
                                                    espelho={}, contratos={}) if a["tipo"] == "fracionamento"]
    assert not any("contrato" in a for a in sem_arq)


def test_instrumentos_no_indice(tmp_path, monkeypatch):
    resumo = tmp_path / "instrumentos.json"
    resumo.write_text(json.dumps({"versao": 1, "ordem_cronologica": {"registros": {"2026": 0}}}), encoding="utf-8")
    monkeypatch.setattr(export, "INSTRUMENTOS_PATH", str(resumo))
    ins = export.instrumentos_indice()
    assert ins["ordem_cronologica"]["registros"] == {"2026": 0} and "versao" not in ins
    monkeypatch.setattr(export, "INSTRUMENTOS_PATH", str(tmp_path / "nao-existe.json"))
    assert export.instrumentos_indice() is None
