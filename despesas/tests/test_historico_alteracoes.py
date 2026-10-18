"""Histórico versionado de alterações da origem (despesas/historico/alteracoes-AAAA.jsonl.gz):
só-acréscimo (sobrevive ao despejo do cache do SQLite), só removido/substituído, e sem o
artefato de largura do nº do empenho (7→8 dígitos em 2026-09-30)."""
import gzip
import json
import sqlite3

import crawler
import export


def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(crawler._schema())
    return conn


def item(i, valor=100.0, empenho=None):
    return {"unidade_gestora": "PREFEITURA MUNICIPAL DE SANTOS", "data": "2026-09-10T00:00:00",
            "especie": "Original", "empenho": empenho or f"{i:07d}/2026", "liquidacao": f"{i:07d}/2026",
            "pagamento": f"{i:07d}/2026", "tipo_pagamento": "Orçamentária",
            "elemento_despesa": "33903999000 - OUTROS", "subtitulo": "", "funcao": "10 - SAÚDE",
            "subfuncao": "301", "programa": "P", "fonte_recurso": "TESOURO",
            "grupo_despesa": "330000000000 - OUTRAS DESPESAS CORRENTES",
            "documento_favorecido": "12.345.678/0001-90", "nome_favorecido": f"FORNECEDOR {i} LTDA", "valor": valor}


def base(*fora, **trocas):
    """10 linhas (a validação do crawler barra queda > 30%), menos `fora`, com valores trocados."""
    return [item(i, valor=trocas.get(f"v{i}", 100.0)) for i in range(1, 11) if i not in fora]


def carga(conn, dados):
    itens, _ = crawler.normalizar("pagamentos", 2026, 9, dados)
    return crawler.reconciliar(conn, "pagamentos", 2026, 9, itens)


def historico(conn, motivo, linha, em="2026-09-30T07:00:00"):
    cols = crawler._cols("pagamentos")
    conteudo = {c: linha.get(c) for c in cols}
    conteudo.update(ano=2026, mes=9, data="2026-09-10")
    conn.execute("INSERT INTO linhas_historico (fonte, ano, mes, motivo, registrado_em, hash, repeticao, conteudo) "
                 "VALUES ('pagamentos', 2026, 9, ?, ?, ?, 1, ?)",
                 (motivo, em, crawler._hash_linha("pagamentos", conteudo), json.dumps(conteudo, ensure_ascii=False)))
    conn.commit()


def ler(pasta, ano="2026"):
    with gzip.open(pasta / f"alteracoes-{ano}.jsonl.gz", "rt", encoding="utf-8") as f:
        return [json.loads(ln) for ln in f.read().splitlines() if ln.strip()]


def test_reconciliacao_real_gera_removido_e_substituido(tmp_path):
    conn = db()
    carga(conn, base())
    carga(conn, base(3, v2=80.0))                        # 3 sumiu, 2 corrigido 100 → 80
    assert export.exportar_historico_alteracoes(conn, str(tmp_path)) == {"2026": 2}
    linhas = ler(tmp_path)
    assert sorted((l["m"], l["pag"], l["valor"]) for l in linhas) == [
        ("removido", "0000003/2026", 100.0), ("substituido", "0000002/2026", 100.0)]
    enxuto = linhas[0]
    assert {"em", "f", "p", "m", "h", "r", "ug", "emp", "valor", "fav"} <= set(enxuto)
    assert "funcao" not in enxuto and "programa" not in enxuto and enxuto["p"] == "2026-09"


def test_duplicidade_e_artefato_de_largura_ficam_de_fora(tmp_path):
    conn = db()
    carga(conn, base())
    # a mesma linha com o nº de 8 dígitos (como a origem mandou em 2026-09-30): a forma
    # normalizada ainda está na base → artefato, não alteração
    oito = item(1, empenho="00000001/2026")
    oito.update(liquidacao="00000001/2026", pagamento="00000001/2026", data="2026-09-10")
    historico(conn, "removido", oito)
    # a de 7 dígitos removida no dia da troca e que voltou depois da correção: idem
    sete = dict(item(2), data="2026-09-10")
    historico(conn, "removido", sete, em="2026-09-30T07:05:00")
    historico(conn, "duplicidade_sistematica", dict(item(9), data="2026-09-10"))
    real = dict(item(17), data="2026-09-10")                       # sumiu de verdade
    historico(conn, "removido", real)
    assert export.exportar_historico_alteracoes(conn, str(tmp_path)) == {"2026": 1}
    assert [l["pag"] for l in ler(tmp_path)] == ["0000017/2026"]


def test_so_acrescimo_sobrevive_ao_despejo_do_cache(tmp_path):
    conn = db()
    carga(conn, base())
    carga(conn, base(2))                                            # 2 removido
    export.exportar_historico_alteracoes(conn, str(tmp_path))
    bruto = (tmp_path / "alteracoes-2026.jsonl.gz").read_bytes()
    # rodar de novo com o mesmo SQLite não duplica nem regrava
    assert export.exportar_historico_alteracoes(conn, str(tmp_path)) == {}
    assert (tmp_path / "alteracoes-2026.jsonl.gz").read_bytes() == bruto
    # cache despejado: SQLite novo, sem o histórico antigo — o versionado mantém o que tinha
    novo = db()
    carga(novo, base(2))
    carga(novo, base(2, 5))                                         # 5 removido no SQLite novo
    assert export.exportar_historico_alteracoes(novo, str(tmp_path)) == {"2026": 1}
    assert sorted(l["pag"] for l in ler(tmp_path)) == ["0000002/2026", "0000005/2026"]
    # gzip sem carimbo de hora: o mesmo conteúdo dá os mesmos bytes
    with gzip.open(tmp_path / "alteracoes-2026.jsonl.gz", "rb") as f:
        assert f.read().decode("utf-8").count("\n") == 2
    assert (tmp_path / "alteracoes-2026.jsonl.gz").read_bytes()[4:8] == b"\x00\x00\x00\x00"   # mtime=0


def test_base_sem_tabela_de_historico_nao_quebra(tmp_path):
    conn = sqlite3.connect(":memory:")
    assert export.exportar_historico_alteracoes(conn, str(tmp_path)) == {}
