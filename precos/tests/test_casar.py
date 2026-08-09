# -*- coding: utf-8 -*-
"""Gates do casamento — cada teste prova que um item ERRADO é rejeitado.

A ferramenta publica acusação de preço com o nome do gabinete: o custo de um
falso positivo é muito maior que o de um falso negativo. Por isso quase todo
teste aqui é um caso que DEVE ser descartado.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import casar  # noqa: E402
import crawler  # noqa: E402

NCP_SANTOS = "58200015000183-1-000002/2026"
NCP_PAR = "44959021000104-1-000003/2026"

COLS_ITEM = ("ncp,numero_item,descricao,descricao_norm,material_ou_servico,quantidade,"
             "unidade_medida,unidade_norm,fator_canonico,valor_unitario_estimado,"
             "situacao_item,tem_resultado,catalogo_codigo,resultado_status")


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(crawler.SCHEMA)
    c.execute("INSERT INTO contratacao(ncp,ibge,cnpj,ano,sequencial,modalidade,srp,"
              "itens_status) VALUES (?,?,?,?,?,?,?,'ok')",
              (NCP_SANTOS, "3548500", "58200015000183", 2026, 2, 6, 0))
    c.execute("INSERT INTO contratacao(ncp,ibge,cnpj,ano,sequencial,modalidade,srp,"
              "itens_status) VALUES (?,?,?,?,?,?,?,'ok')",
              (NCP_PAR, "3518701", "44959021000104", 2026, 3, 6, 0))
    _item(c, NCP_SANTOS, 1, "PLACAS DE METALON COM LONA IMPRESSA", "M", 600, "MT2", "m2", 1.0)
    # âncora com preço adjudicado → a comparação roda na base 'homologado'
    _resultado(c, NCP_SANTOS, 1, 210.0, data="2026-04-10")
    return c


def _item(c, ncp, n, desc, ms, qtd, un, un_norm, fator, situacao="Homologado",
          tem_res=1, catalogo=None):
    import texto
    c.execute(f"INSERT INTO item({COLS_ITEM}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'ok')",
              (ncp, n, desc, texto.normalizar(desc), ms, qtd, un, un_norm, fator,
               100.0, situacao, tem_res, catalogo))


def _resultado(c, ncp, n, valor, data="2026-03-02", ordem=1, situacao="Homologado"):
    c.execute("INSERT INTO resultado VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (ncp, n, 1, valor, valor, 1, "11111111000111", "FORN LTDA", "ME",
               data, situacao, ordem))


def _consulta(**over):
    q = {
        "slug": "teste", "titulo": "Teste",
        "santos": {"numero_controle_pncp": NCP_SANTOS, "itens": [1]},
        "unidade_canonica": "m2",
        "termos": {"obrigatorios": ["placa"], "algum_de": [["metalon", "chapa"]],
                   "excluir": ["sinalizacao viaria"]},
        "material_ou_servico": None, "srp": None, "numeros": [],
        "faixa_quantidade": None, "janela_meses": 36, "modalidades": [6],
        "cidades": None, "correcao": "nenhuma", "revisao": {},
    }
    q.update(over)
    return q


def _motivo(conn, n):
    return conn.execute(
        "SELECT motivo_rejeicao FROM casamento WHERE numero_item=? AND ncp=?",
        (n, NCP_PAR)).fetchone()[0]


def test_item_equivalente_e_aceito(conn):
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA IMPRESSA INSTALADA",
          "M", 500, "M2", "m2", 1.0)
    _resultado(conn, NCP_PAR, 1, 152.0)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 1 and r["com_preco"] == 1


def test_unidade_desconhecida_rejeita(conn):
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA", "M", 5, "XPTO", None, None)
    _resultado(conn, NCP_PAR, 1, 999.0)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "unidade_desconhecida"


def test_unidade_verba_rejeita_mesmo_com_texto_perfeito(conn):
    """VERBA esconde a quantidade: R$/verba não é preço unitário comparável."""
    _item(conn, NCP_PAR, 1, "PLACAS DE METALON COM LONA IMPRESSA", "M", 1, "VERBA",
          None, None)
    _resultado(conn, NCP_PAR, 1, 480000.0)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "unidade_desconhecida"


def test_familia_errada_rejeita(conn):
    """Placa vendida por unidade não entra numa comparação por m²."""
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA", "M", 30, "UN", "un", 1.0)
    _resultado(conn, NCP_PAR, 1, 320.0)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "unidade_desconhecida"


def test_termo_excluido_rejeita(conn):
    _item(conn, NCP_PAR, 1, "PLACA DE SINALIZACAO VIARIA EM CHAPA GALVANIZADA",
          "M", 100, "M2", "m2", 1.0)
    _resultado(conn, NCP_PAR, 1, 88.0)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 0
    assert _motivo(conn, 1).startswith("termo_excluido")


def test_sem_termo_obrigatorio_rejeita(conn):
    _item(conn, NCP_PAR, 1, "LONA IMPRESSA EM METALON", "M", 100, "M2", "m2", 1.0)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "sem_termo_obrigatorio"


def test_sem_termo_do_grupo_rejeita(conn):
    _item(conn, NCP_PAR, 1, "PLACA DE GESSO PARA FORRO", "M", 100, "M2", "m2", 1.0)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "sem_termo_do_grupo"


def test_natureza_diferente_rejeita(conn):
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA", "S", 100, "M2", "m2", 1.0)
    r = casar.casar(conn, _consulta(material_ou_servico="M"))
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "natureza_diferente"


def test_situacao_cancelada_rejeita(conn):
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA", "M", 100, "M2", "m2", 1.0,
          situacao="Cancelado")
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "situacao_invalida"


def test_fora_da_janela_rejeita(conn):
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA", "M", 100, "M2", "m2", 1.0)
    _resultado(conn, NCP_PAR, 1, 152.0, data="2019-01-10")
    r = casar.casar(conn, _consulta(janela_meses=36))
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "fora_da_janela"


def test_quantidade_fora_da_faixa_rejeita(conn):
    """Lote 100× maior tem outro custo marginal — não é o mesmo mercado."""
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA", "M", 60000, "M2", "m2", 1.0)
    _resultado(conn, NCP_PAR, 1, 40.0)
    r = casar.casar(conn, _consulta(faixa_quantidade=[0.2, 5.0]))
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "quantidade_fora_da_faixa"


def test_srp_pode_ser_excluido(conn):
    conn.execute("UPDATE contratacao SET srp=1 WHERE ncp=?", (NCP_PAR,))
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA", "M", 100, "M2", "m2", 1.0)
    _resultado(conn, NCP_PAR, 1, 152.0)
    r = casar.casar(conn, _consulta(srp="excluir"))
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "srp_incompativel"


def test_confianca_baixa_nao_entra_na_mediana(conn):
    """Passa os gates, mas o resto da descrição não tem nada a ver."""
    _item(conn, NCP_PAR, 1,
          "PLACA METALON ORTOPEDICA CIRURGICA TITANIO ESTERIL DESCARTAVEL BLOQUEADA",
          "M", 100, "M2", "m2", 1.0)
    _resultado(conn, NCP_PAR, 1, 1500.0)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "confianca_baixa"


def test_descricao_generica_e_descartada_com_motivo_proprio(conn):
    """O PNCP tem itens catalogados só como "Seringa": nada a verificar."""
    _item(conn, NCP_PAR, 1, "PLACA METALON", "M", 500, "M2", "m2", 1.0)
    _resultado(conn, NCP_PAR, 1, 152.0)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "descricao_generica"


def test_conversao_de_unidade_rebaixa_para_media(conn):
    _item(conn, NCP_PAR, 1, "PLACAS DE METALON COM LONA IMPRESSA", "M", 5000, "CM2",
          "m2", 0.0001)
    _resultado(conn, NCP_PAR, 1, 0.0152)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 1
    assert conn.execute("SELECT confianca FROM casamento WHERE ncp=?",
                        (NCP_PAR,)).fetchone()[0] == "media"


def test_preco_convertido_para_unidade_canonica(conn):
    """1 cm² a R$ 0,0152 é R$ 152,00/m² — a conversão precisa dividir pelo fator."""
    _item(conn, NCP_PAR, 1, "PLACAS DE METALON COM LONA IMPRESSA", "M", 5000, "CM2",
          "m2", 0.0001)
    _resultado(conn, NCP_PAR, 1, 0.0152)
    ok, _, fator, preco, *_ = casar._gates(
        _consulta(), dict(conn.execute("SELECT * FROM item WHERE ncp=?",
                                       (NCP_PAR,)).fetchone()),
        dict(conn.execute("SELECT * FROM item WHERE ncp=?", (NCP_SANTOS,)).fetchone()),
        1.0, conn)
    assert ok and abs(preco - 152.0) < 1e-6


def test_curadoria_rejeita_vence_o_algoritmo(conn):
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA IMPRESSA", "M", 500, "M2",
          "m2", 1.0)
    _resultado(conn, NCP_PAR, 1, 152.0)
    q = _consulta(revisao={"rejeitados": [f"{NCP_PAR}#1"]})
    r = casar.casar(conn, q)
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "curadoria_rejeitou"


def test_curadoria_confirmar_nao_ressuscita_item_reprovado(conn):
    """A assimetria que torna a curadoria auditável: confirmar só promove confiança."""
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA", "M", 5, "XPTO", None, None)
    _resultado(conn, NCP_PAR, 1, 999.0)
    q = _consulta(revisao={"confirmados": [f"{NCP_PAR}#1"]})
    r = casar.casar(conn, q)
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "unidade_desconhecida"


def test_resultado_cancelado_nao_vira_preco(conn):
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA IMPRESSA", "M", 500, "M2",
          "m2", 1.0)
    _resultado(conn, NCP_PAR, 1, 152.0, situacao="Cancelado")
    assert casar.preco_homologado(conn, NCP_PAR, 1) is None


def test_vencedor_e_o_primeiro_classificado(conn):
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA IMPRESSA", "M", 500, "M2",
          "m2", 1.0)
    conn.execute("INSERT INTO resultado VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (NCP_PAR, 1, 2, 300.0, 300.0, 1, "2", "SEGUNDO", "ME",
                  "2026-03-02", "Homologado", 2))
    conn.execute("INSERT INTO resultado VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (NCP_PAR, 1, 1, 152.0, 152.0, 1, "1", "PRIMEIRO", "ME",
                  "2026-03-02", "Homologado", 1))
    assert casar.preco_homologado(conn, NCP_PAR, 1)[0] == 152.0


def test_ancora_com_unidade_nao_conversivel_aborta_a_comparacao(conn):
    """Cair em fator 1 aqui publicaria o preço da CAIXA como preço da UNIDADE."""
    conn.execute("UPDATE item SET unidade_medida='CX' WHERE ncp=?", (NCP_SANTOS,))
    r = casar.casar(conn, _consulta(unidade_canonica="un"))
    assert "não converte" in r.get("erro", "")


def test_conversoes_extra_resolve_a_ancora(conn):
    """Escape curado: a quantidade está na descrição ('caixa com 100'), não na unidade."""
    conn.execute("UPDATE item SET unidade_medida='CX' WHERE ncp=?", (NCP_SANTOS,))
    q = _consulta(unidade_canonica="un", conversoes_extra={"CX": 100})
    assert casar.fator_para_canonica(q, "CX") == 100
    r = casar.casar(conn, q)
    assert "erro" not in r


def test_base_homologado_quando_ancora_tem_resultado(conn):
    assert casar.base_da_ancora(
        conn, dict(conn.execute("SELECT * FROM item WHERE ncp=?",
                                (NCP_SANTOS,)).fetchone())) == "homologado"


def test_base_estimado_nao_usa_homologado_dos_pares(conn):
    """Âncora sem adjudicação → comparação inteira na base 'estimado'.

    O estimado é teto de edital; o homologado é preço de mercado. Cruzar os dois
    inventaria uma economia que não existe.
    """
    conn.execute("DELETE FROM resultado WHERE ncp=?", (NCP_SANTOS,))
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA IMPRESSA", "M", 500, "M2",
          "m2", 1.0)
    _resultado(conn, NCP_PAR, 1, 1.0)      # homologado baratíssimo: deve ser IGNORADO
    r = casar.casar(conn, _consulta())
    assert r["base"] == "estimado"
    assert r["aceitos_detalhe"][0]["_preco"] == 100.0   # o estimado do item, não o R$ 1


def test_item_sem_resultado_rejeitado_na_base_homologado(conn):
    _item(conn, NCP_PAR, 1, "PLACA EM METALON COM LONA IMPRESSA", "M", 500, "M2",
          "m2", 1.0, tem_res=0)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 0
    assert _motivo(conn, 1) == "sem_resultado_publicado"


def test_outlier_grosseiro_sai_da_coorte(conn):
    for i, preco in enumerate([150.0, 155.0, 160.0, 148.0, 9000.0], start=1):
        _item(conn, NCP_PAR, i, "PLACAS DE METALON COM LONA IMPRESSA", "M", 500,
              "M2", "m2", 1.0)
        _resultado(conn, NCP_PAR, i, preco)
    r = casar.casar(conn, _consulta())
    assert r["aceitos"] == 4
    assert _motivo(conn, 5) == "outlier"
