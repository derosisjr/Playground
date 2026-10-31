"""Mesmo dado = mesmos bytes (2026-10). A recarga diária do ano corrente substitui as
partições no SQLite e muda a ORDEM FÍSICA das linhas; os arquivos de dados/mov/ eram
regravados todo dia sem dado novo (93% das versões de outubro/2026: ~35 MiB/mês no
histórico). Aqui as mesmas linhas entram em ordens diferentes e cada artefato tem de
sair idêntico byte a byte."""
import random

import export
from test_export import add, db

LINHAS = []
for dia in (3, 3, 3, 10):   # três documentos no MESMO dia: o empate é o caso que quebrava
    for fase, tab in (("E", "empenhos"), ("L", "liquidacoes"), ("P", "pagamentos")):
        LINHAS.append((tab, 2026, 2, {"data": f"2026-02-{dia:02d}", "empenho": f"00000{dia}{len(LINHAS)}/2026",
                                      "liquidacao": f"L{len(LINHAS)}", "pagamento": f"P{len(LINHAS)}",
                                      "nome_favorecido": f"FORNECEDOR {len(LINHAS) % 3}",
                                      "documento_favorecido": f"1{len(LINHAS) % 3}.000.000/0001-00",
                                      "fonte_recurso": f"FONTE {len(LINHAS) % 2}"}, 100.0 * (1 + len(LINHAS) % 4)))
# pseudo-empenho (extra sem nº) com fontes diferentes no mesmo grupo: a coluna "solta" do GROUP BY
for fonte in ("01-1100000 - GERAL", "1000508 - CONVENIO"):
    LINHAS.append(("pagamentos", 2026, 2, {"data": "2026-02-05", "empenho": "", "fonte_recurso": fonte,
                                           "tipo_pagamento": "Extra Orçamentário"}, 50.0))
# empenho com dois tipos (Ordinário no original, Estimativo no reforço)
LINHAS.append(("empenhos", 2026, 2, {"data": "2026-02-07", "empenho": "0000777/2026", "tipo_empenho": "Ordinário"}, 10.0))
LINHAS.append(("empenhos", 2026, 2, {"data": "2026-02-07", "empenho": "0000777/2026", "especie": "Reforço",
                                     "tipo_empenho": "Estimativo"}, 5.0))


def _base(ordem):
    conn = db()
    for tab, ano, mes, kw, valor in ordem:
        add(conn, tab, ano, mes, valor, **kw)
    return conn


def _artefatos(conn, raiz, monkeypatch):
    for nome, sub in (("MOV_DIR", "mov"), ("DADOS_DIR", "exe"), ("ESTAGIOS_DIR", "est")):
        (raiz / sub).mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(export, nome, str(raiz / sub))
    execucao, movimento = export.montar_execucao(conn), export.montar_movimento(conn)
    export.exportar_movimento_mensal(movimento)
    export.exportar_detalhe_mensal(execucao)
    export.exportar_estagios(conn, execucao)
    return {p.relative_to(raiz).as_posix(): p.read_bytes() for p in raiz.rglob("*.json")}


def test_mesmo_dado_em_outra_ordem_fisica_grava_os_mesmos_bytes(tmp_path, monkeypatch):
    a = _artefatos(_base(LINHAS), tmp_path / "a", monkeypatch)
    for semente in (1, 2, 3):
        embaralhadas = LINHAS[:]
        random.Random(semente).shuffle(embaralhadas)
        b = _artefatos(_base(embaralhadas), tmp_path / f"b{semente}", monkeypatch)
        assert a.keys() == b.keys() and a, "os mesmos arquivos"
        assert [k for k in a if a[k] != b[k]] == []


def test_movimento_fase_antes_do_desempate_e_coluna_solta_estavel():
    conn = _base(LINHAS)
    fases = [m["fase"] for m in export.montar_movimento(conn) if m["data"] == "2026-02-03"]
    assert fases == sorted(fases, key="ELP".index)   # no mesmo dia, E → L → P como antes
    extra = [r for r in export.montar_execucao(conn) if r["tipo"] == export.T_EXTRA]
    assert [r["fonte_recurso"] for r in extra] == ["1000508 - CONVENIO"]   # MAX(), não a 1ª linha física
