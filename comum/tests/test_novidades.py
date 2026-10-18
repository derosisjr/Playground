"""Feed de novidades: o que cada transição entre o retrato da véspera e o índice de hoje
vira (ou não vira) no novidades.json."""
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
_spec = importlib.util.spec_from_file_location(
    "novidades", os.path.join(RAIZ, ".github", "scripts", "novidades.py"))
nv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv)

INDICES = {"req": "requerimentos-index.json", "prop": "proposituras-index.json",
           "legis": "legis-index.json", "desp": "despesas-index.json"}


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    monkeypatch.setattr(nv, "RAIZ", Path(tmp_path))
    return Path(tmp_path)


def dia(d, m=10):
    return datetime(2026, m, d, 12, 0, tzinfo=timezone.utc)


def escrever(raiz, **indices):
    for k, obj in indices.items():
        (raiz / INDICES[k]).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def rodar(raiz, quando, **indices):
    escrever(raiz, **indices)
    return nv.executar(quando)


def req(numero, situacao="pendente", merito="", **extra):
    return {"numero": numero, "ano": 2026, "data_sessao": "01/10/2026", "data_resposta": "",
            "assunto": "Oficiar ao Executivo solicitando, nos termos do artigo 58, informações sobre a poda",
            "data_resposta_merito": merito, "situacao": situacao,
            "respondido": situacao == "respondido", "url_resposta": "", **extra}


def prop(cod, numero, **extra):
    return {"cod": cod, "tipo": "Projeto", "subtipo": "Projeto de Lei", "numero": numero, "ano": 2026,
            "data_propositura": "01/10/2026", "autor": "Fulano de Tal",
            "ementa": "Dispõe sobre a arborização urbana.", "local_atual": "Comissão de Justiça",
            "situacao": "Encaminhado", "url_detalhes": "", "url_pdf": "", **extra}


def norma(id_, numero, situacao=""):
    return {"id": id_, "tipo": "Lei ordinária", "numero": numero, "ano": 2026, "data_norma": "05/10/2026",
            "titulo": f"Lei n.º {numero}, de 05 de outubro", "ementa": "ATENÇÃO ÀS DOENÇAS RARAS",
            "tags": "", "situacao": situacao, "url_legis": "", "url_pdf": ""}


def desp(alertas, mes=(2026, 9), valor=347832018.74):
    return {"alertas": [{"id": i, "classe": c, "titulo": t} for i, c, t in alertas],
            "resumo": {"mes_ref": {"ano": mes[0], "mes": mes[1], "valor": valor}}}


def chaves(eventos):
    return [e["chave"] for e in eventos]


def test_primeira_execucao_so_grava_retrato(raiz):
    doc, situacao, novos = rodar(raiz, dia(10), req=[req("1/2026")], prop=[prop(100, "1/2026")],
                                 legis=[norma(1, "4.800")], desp=desp([("a1", "anomalia", "Pico")]))
    assert novos == [] and doc["eventos"] == []
    assert set(doc["retrato"]) == {"versao", "requerimentos", "proposituras", "legis", "despesas"}
    assert all(s.startswith("retrato inicial") for s in situacao.values())
    assert json.loads((raiz / "novidades.json").read_text(encoding="utf-8")) == doc


def test_resposta_por_situacao_ou_por_data_de_merito(raiz):
    rodar(raiz, dia(10), req=[req("10/2026"), req("11/2026"), req("12/2026", "respondido", "01/10/2026")])
    doc, _, novos = rodar(raiz, dia(11), req=[
        req("10/2026", "respondido", "10/10/2026", secretaria="SMS"),
        req("11/2026", merito="10/10/2026"),               # situação atrasada, mas já tem mérito
        req("12/2026", "respondido", "01/10/2026")])
    assert chaves(novos) == ["requerimentos:resposta:10/2026", "requerimentos:resposta:11/2026"]
    ev = doc["eventos"][0]
    assert list(ev) == ["visto_em", "base", "tipo", "titulo", "chave", "link"]   # ordem do contrato
    assert ev["visto_em"] == "2026-10-11" and ev["tipo"] == "resposta" and ev["base"] == "requerimentos"
    assert ev["link"] == "requerimentos.html?n=10%2F2026"
    assert ev["titulo"] == "Requerimento 10/2026 (SMS) respondido — Informações sobre a poda"
    _, _, novos = rodar(raiz, dia(12))                    # nada mudou: nada novo
    assert novos == []


def test_prorrogacao(raiz):
    rodar(raiz, dia(10), req=[req("20/2026")])
    _, _, novos = rodar(raiz, dia(11), req=[req("20/2026", "so_prorrogacao")])
    assert [(e["tipo"], e["titulo"]) for e in novos] == [
        ("prorrogacao", "Requerimento 20/2026: Prefeitura pediu mais prazo — Informações sobre a poda")]
    _, _, novos = rodar(raiz, dia(12))
    assert novos == []


def test_vencido_so_uma_vez_e_nunca_no_dia_em_que_o_campo_chega(raiz):
    rodar(raiz, dia(10), req=[req("1/2026"), req("2/2026")])                  # índice sem vence_em
    _, _, novos = rodar(raiz, dia(11), req=[req("1/2026", vence_em="01/10/2026"),
                                            req("2/2026", vence_em="12/10/2026")])
    assert novos == []                                    # 1/2026 já vencido quando o campo chegou
    _, _, novos = rodar(raiz, dia(13))
    assert chaves(novos) == ["requerimentos:vencido:2/2026"]
    assert novos[0]["titulo"].startswith("Requerimento 2/2026 sem resposta no prazo")
    # prorrogação empurra o prazo; quando ele vence de novo, o feed não repete
    _, _, novos = rodar(raiz, dia(14), req=[req("1/2026", vence_em="01/10/2026"),
                                            req("2/2026", "so_prorrogacao", vence_em="27/10/2026")])
    assert [e["tipo"] for e in novos] == ["prorrogacao"]
    doc, _, novos = rodar(raiz, dia(28))
    assert novos == []
    assert sum(e["tipo"] == "vencido" for e in doc["eventos"]) == 1


def test_propositura_nova_e_andamento(raiz):
    rodar(raiz, dia(10), prop=[prop(100, "1/2026", tram=1, ua="2026-10-01"), prop(101, "2/2026", tram=0)])
    doc, _, novos = rodar(raiz, dia(11), prop=[
        prop(105, "3/2026", tram=1, ua="2026-10-11", autor=nv.AUTOR_MANDATO),
        prop(100, "1/2026", tram=1, ua="2026-10-09", ual="COMISSÃO DE FINANÇAS"),
        prop(101, "2/2026", tram=0)])
    por_chave = {e["chave"]: e for e in novos}
    assert set(por_chave) == {"proposituras:nova:105", "proposituras:andamento:100:2026-10-09"}
    nova = por_chave["proposituras:nova:105"]
    assert list(nova)[-2:] == ["link", "mandato"] and nova["mandato"] is True
    assert nova["link"] == "proposituras.html?cod=105"
    assert nova["titulo"] == (f"Nova propositura: Projeto de Lei 3/2026 ({nv.AUTOR_MANDATO}) — "
                              "Dispõe sobre a arborização urbana.")
    andou = por_chave["proposituras:andamento:100:2026-10-09"]
    assert "mandato" not in andou
    assert andou["titulo"].startswith("Projeto de Lei 1/2026: novo andamento (COMISSÃO DE FINANÇAS)")
    # data igual ou mais antiga não é andamento; entrar/sair de tramitação também não
    _, _, novos = rodar(raiz, dia(12), prop=[
        prop(105, "3/2026", tram=0, autor=nv.AUTOR_MANDATO),
        prop(100, "1/2026", tram=1, ua="2026-10-02"),
        prop(101, "2/2026", tram=1, ua="2026-10-12")])
    assert novos == []
    # índice parcial num dia e completo no outro: quem volta não "estreia" de novo
    _, _, novos = rodar(raiz, dia(13), prop=[prop(100, "1/2026", tram=1, ua="2026-10-02")])
    assert novos == []
    _, _, novos = rodar(raiz, dia(14), prop=[prop(105, "3/2026", tram=0), prop(101, "2/2026", tram=0),
                                             prop(100, "1/2026", tram=1, ua="2026-10-02")])
    assert novos == []


def test_carga_retroativa_abaixo_do_piso_nao_e_novidade(raiz):
    # piso = menor cod do ano corrente e do anterior; só dali para cima o retrato guarda
    doc, _, _ = rodar(raiz, dia(10), prop=[prop(500, "1/2025", ano=2025), prop(400, "9/2024", ano=2024)])
    assert doc["retrato"]["proposituras"] == {"piso": 500, "ids": [500]}
    _, _, novos = rodar(raiz, dia(11), prop=[prop(600, "2/2026"), prop(500, "1/2025", ano=2025),
                                             prop(450, "3/2023", ano=2023), prop(400, "9/2024", ano=2024)])
    assert chaves(novos) == ["proposituras:nova:600"]


def test_andamento_ignorado_enquanto_o_indice_nao_traz_ua(raiz):
    rodar(raiz, dia(10), prop=[prop(100, "1/2026"), prop(101, "2/2026")])     # formato de hoje
    _, _, novos = rodar(raiz, dia(11), prop=[prop(100, "1/2026", local_atual="Plenário"),
                                             prop(101, "2/2026")])
    assert novos == []
    doc, _, novos = rodar(raiz, dia(12), prop=[prop(100, "1/2026", tram=1, ua="2026-10-12"),
                                               prop(101, "2/2026", tram=0)])
    assert novos == []                                    # o ua chegou: só vira retrato
    assert "tram" in doc["retrato"]["proposituras"]
    _, _, novos = rodar(raiz, dia(13), prop=[prop(100, "1/2026", tram=1, ua="2026-10-13"),
                                             prop(101, "2/2026", tram=0)])
    assert chaves(novos) == ["proposituras:andamento:100:2026-10-13"]


def test_norma_nova_e_revogada(raiz):
    rodar(raiz, dia(10), legis=[norma(1, "4.800"), norma(2, "4.801", "alterada")])
    _, _, novos = rodar(raiz, dia(11), legis=[norma(3, "4.804"), norma(1, "4.800", "revogada parcialmente"),
                                              norma(2, "4.801", "alterada")])
    assert [(e["tipo"], e["titulo"], e["link"]) for e in novos] == [
        ("nova", "Nova norma: Lei n.º 4.804, de 05 de outubro de 2026 — ATENÇÃO ÀS DOENÇAS RARAS",
         "legis.html?id=3"),
        ("revogada", "Norma revogada parcialmente: Lei n.º 4.800, de 05 de outubro de 2026",
         "legis.html?id=1")]
    # índice parcial (norma 1 sumiu) e depois completo: nada é "nova" nem "revogada" de novo
    _, _, novos = rodar(raiz, dia(12), legis=[norma(3, "4.804"), norma(2, "4.801", "alterada")])
    assert novos == []
    _, _, novos = rodar(raiz, dia(13), legis=[norma(3, "4.804"), norma(1, "4.800", "revogada parcialmente"),
                                              norma(2, "4.801", "alterada")])
    assert novos == []


def test_alerta_novo_resolvido_e_mes_fechado(raiz):
    rodar(raiz, dia(10), desp=desp([("a1", "anomalia", "Pico de gasto"), ("c1", "contexto", "Recorrente")],
                                   mes=(2026, 8)))
    _, _, novos = rodar(raiz, dia(11), desp=desp([("a2", "inconsistencia", "Duplicidade na origem"),
                                                  ("c2", "contexto", "Outro recorrente")]))
    assert [(e["tipo"], e["chave"], e["titulo"], e["link"]) for e in novos] == [
        ("alerta", "despesas:alerta:a2", "Novo alerta de despesas — Duplicidade na origem",
         "despesas.html#alertas"),
        ("alerta_resolvido", "despesas:alerta_resolvido:a1", "Alerta de despesas encerrado — Pico de gasto",
         "despesas.html#alertas"),
        ("mes_fechado", "despesas:mes_fechado:2026-09",
         "Mês fechado: a Prefeitura pagou R$ 347,8 mi em setembro de 2026", "despesas.html")]
    # mês de referência que recua (correção na origem) e volta: nada de novo no feed
    _, _, novos = rodar(raiz, dia(12), desp=desp([("a2", "inconsistencia", "Duplicidade na origem")],
                                                 mes=(2026, 8)))
    assert novos == []
    _, _, novos = rodar(raiz, dia(13), desp=desp([("a2", "inconsistencia", "Duplicidade na origem")]))
    assert novos == []


def test_janela_de_60_dias_teto_e_primeiro_registro_vale():
    hoje = date(2026, 10, 17)
    antigos = [{"visto_em": (hoje - timedelta(days=n)).isoformat(), "chave": f"x:{n}"} for n in (59, 60)]
    out, entraram = nv.mesclar(antigos, [{"chave": "x:59", "tipo": "repetido"}], hoje)
    assert out == [antigos[0]] and entraram == []   # 60 dias atrás sai; chave repetida não entra
    muitos = [{"visto_em": (hoje - timedelta(days=n % 50)).isoformat(), "chave": f"y:{n}"}
              for n in range(450)]
    out, entraram = nv.mesclar(muitos, [{"chave": "z:1"}], hoje)
    assert len(out) == nv.TETO_EVENTOS and out[0] == entraram[0] == {"visto_em": "2026-10-17", "chave": "z:1"}
    datas = [e["visto_em"] for e in out]
    assert datas == sorted(datas, reverse=True)
    assert min(datas) > min(e["visto_em"] for e in muitos)       # cortou os mais antigos


def test_base_ausente_ou_ilegivel_nao_apaga_eventos_nem_retrato(raiz, capsys):
    rodar(raiz, dia(10), req=[req("10/2026")])
    doc, _, _ = rodar(raiz, dia(11), req=[req("10/2026", "respondido", "10/10/2026")])
    retrato = doc["retrato"]["requerimentos"]
    (raiz / INDICES["req"]).unlink()
    doc, situacao, _ = nv.executar(dia(12))
    assert chaves(doc["eventos"]) == ["requerimentos:resposta:10/2026"]
    assert doc["retrato"]["requerimentos"] == retrato and situacao["requerimentos"].startswith("pulada")
    assert "aviso: requerimentos pulada" in capsys.readouterr().err
    (raiz / INDICES["req"]).write_text("{quebrado", encoding="utf-8")
    doc, _, _ = nv.executar(dia(13))
    assert chaves(doc["eventos"]) == ["requerimentos:resposta:10/2026"]
    doc, _, novos = rodar(raiz, dia(14), req=[req("10/2026", "respondido", "10/10/2026")])
    assert novos == [] and len(doc["eventos"]) == 1


def test_surto_refaz_retrato_sem_publicar(raiz, capsys):
    rodar(raiz, dia(10), legis=[norma(1, "1")])
    n = nv.LIMITE_SURTO + 2                               # LIMITE_SURTO + 1 normas novas de uma vez
    doc, situacao, novos = rodar(raiz, dia(11), legis=[norma(i, str(i)) for i in range(1, n + 1)])
    assert novos == [] and doc["eventos"] == [] and situacao["legis"].startswith("surto")
    assert f"legis gerou {n - 1} eventos" in capsys.readouterr().err
    _, _, novos = rodar(raiz, dia(12), legis=[norma(i, str(i)) for i in range(1, n + 2)])
    assert chaves(novos) == [f"legis:nova:{n + 1}"]       # o retrato absorveu a carga


def test_retrato_incompativel_recomeca_a_base_sem_eventos(raiz, capsys):
    rodar(raiz, dia(10), prop=[prop(100, "1/2026")], req=[req("1/2026")])
    salvo = json.loads((raiz / "novidades.json").read_text(encoding="utf-8"))
    salvo["retrato"]["proposituras"]["ids"] = ["lixo"]
    salvo["retrato"]["requerimentos"]["pendentes"]["1/2026"] = ["pendente"]   # lista curta
    (raiz / "novidades.json").write_text(json.dumps(salvo), encoding="utf-8")
    _, situacao, novos = rodar(raiz, dia(11), prop=[prop(100, "1/2026"), prop(101, "2/2026")],
                               req=[req("1/2026", "respondido", "10/10/2026")])
    assert novos == []
    assert situacao["proposituras"].startswith("retrato inicial")
    assert situacao["requerimentos"].startswith("retrato inicial")
    err = capsys.readouterr().err
    assert "retrato de proposituras incompatível" in err and "retrato de requerimentos incompatível" in err


def test_assunto_curto_tira_a_formula_do_oficio():
    assert nv._assunto_curto("Oficiar ao Executivo solicitando, em meio digital ou físico, a cópia "
                             "integral do contrato") == "A cópia integral do contrato"
    assert nv._assunto_curto("Oficiar ao Executivo para que informe, nos termos do artigo 58, se há "
                             "fila") == "Informe se há fila"
    assert nv._assunto_curto("Combate à Dengue") == "Combate à Dengue"


def test_deltas_ida_e_volta():
    assert nv._deltas({300, 5, 1}) == [1, 4, 295]
    assert nv._de_deltas(nv._deltas({300, 5, 1})) == [1, 5, 300]
