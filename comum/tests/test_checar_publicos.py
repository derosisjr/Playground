"""A guarda de campos públicos olha o JSON já publicado — o export sozinho não basta
(em 18/10/2026 o requerimentos-index.json no ar ainda tinha a coluna interna da planilha)."""
import importlib.util
import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "checar_publicos", os.path.join(RAIZ, ".github", "scripts", "checar_publicos.py"))
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


def _gravar(pasta, nome, itens):
    with open(os.path.join(pasta, nome), "w", encoding="utf-8") as f:
        json.dump(itens, f, ensure_ascii=False)


def test_lista_vem_do_export_sem_copia():
    campos = cp.bases()["requerimentos-index.json"]
    assert "numero" in campos and "vence_em" in campos
    assert "status" not in campos  # a coluna interna "Status atual" nunca é pública


def test_campo_interno_e_apontado_com_contagem(tmp_path):
    _gravar(tmp_path, "x.json", [{"numero": "1/2026", "status": "ok (Falar com o Rui)"},
                                 {"numero": "2/2026", "status": ""}, {"numero": "3/2026"}])
    achados = cp.problemas(str(tmp_path), {"x.json": ("numero",)})
    assert len(achados) == 1
    assert "'status' em 2 de 3 itens" in achados[0]


def test_arquivo_limpo_ou_ausente_passa(tmp_path):
    _gravar(tmp_path, "x.json", [{"numero": "1/2026", "ano": 2026}])
    assert cp.problemas(str(tmp_path), {"x.json": ("numero", "ano"), "ausente.json": ("numero",)}) == []


def test_main_sai_1_com_vazamento(tmp_path, monkeypatch):
    _gravar(tmp_path, "requerimentos-index.json", [{"numero": "1/2026", "status": "interno"}])
    monkeypatch.setattr(cp, "bases", lambda raiz: {"requerimentos-index.json": ("numero",)})
    assert cp.main([str(tmp_path)]) == 1
    _gravar(tmp_path, "requerimentos-index.json", [{"numero": "1/2026"}])
    assert cp.main([str(tmp_path)]) == 0


def test_lista_lida_sem_executar_o_modulo(tmp_path):
    fonte = tmp_path / "export.py"
    fonte.write_text('import modulo_que_nao_existe\nCAMPOS_PUBLICOS = ("a", "b")\n', encoding="utf-8")
    assert cp.lista_do_export(str(fonte)) == ("a", "b")


# ── Indicações (out/2026): lista branca de chaves + valores fechados de bairro/região ──
def test_lista_de_indicacoes_vem_do_export():
    campos = cp.bases()["indicacoes-index.json"]
    assert "bairro" in campos and "regiao" in campos and "url_resposta" in campos
    # colunas internas da aba nunca entram (nem com outro nome)
    for interna in ("sta", "a_contento", "prazo", "data_protocolo", "bairro_planilha", "vence_em"):
        assert interna not in campos


def test_indicacoes_publicadas_passam():
    # o arquivo versionado (gerado pelo export) passa nas duas guardas
    regras = cp.valores_permitidos()
    assert "Ponta da Praia" in regras["indicacoes-index.json"]["bairro"]
    assert "Cidade toda" in regras["indicacoes-index.json"]["regiao"]
    arquivo = {"indicacoes-index.json": cp.bases()["indicacoes-index.json"]}
    assert cp.problemas(cp.RAIZ, arquivo) == []
    assert cp.problemas_valores(cp.RAIZ, regras) == []


def test_bairro_cru_e_apontado_sem_mostrar_o_valor(tmp_path):
    _gravar(tmp_path, "indicacoes-index.json", [
        {"numero": "1/2026", "bairro": "RESPOSTA EM 07 MESES", "regiao": ""},
        {"numero": "2/2026", "bairro": "Ponta da Praia", "regiao": ""},
        {"numero": "3/2026", "bairro": "", "regiao": "ORLA DA PRAIA"},
    ])
    regras = {"indicacoes-index.json": cp.valores_permitidos()["indicacoes-index.json"]}
    achados = cp.problemas_valores(str(tmp_path), regras)
    assert len(achados) == 2
    assert "'bairro'" in achados[0] and "nº 1/2026" in achados[0]
    assert "'regiao'" in achados[1] and "nº 3/2026" in achados[1]
    assert not any("07 MESES" in a or "ORLA DA PRAIA" in a for a in achados)  # log público


def test_main_sai_1_com_chave_interna_ou_bairro_cru(tmp_path, monkeypatch):
    # as listas reais (do export e do GeoJSON), com o JSON numa pasta temporária
    campos, regras = cp.bases()["indicacoes-index.json"], cp.valores_permitidos()
    monkeypatch.setattr(cp, "bases", lambda raiz: {"indicacoes-index.json": campos})
    monkeypatch.setattr(cp, "valores_permitidos", lambda raiz: regras)
    _gravar(tmp_path, "indicacoes-index.json", [{"numero": "1/2026", "bairro": "", "sta": "17"}])
    assert cp.main([str(tmp_path)]) == 1
    _gravar(tmp_path, "indicacoes-index.json", [{"numero": "1/2026", "bairro": "ITARARÉ"}])
    assert cp.main([str(tmp_path)]) == 1
    _gravar(tmp_path, "indicacoes-index.json", [{"numero": "1/2026", "bairro": "Gonzaga", "regiao": ""}])
    assert cp.main([str(tmp_path)]) == 0
