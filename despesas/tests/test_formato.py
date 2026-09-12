from formato import brl, compacto, pct, eh_ente_publico, sem_acento


def test_brl():
    assert brl(1234567.89) == "R$ 1.234.567,89"
    assert brl(0) == "R$ 0,00"
    assert brl(None) == "R$ 0,00"


def test_compacto_faixas():
    assert compacto(8_440_000_000) == "R$ 8,44 bi"
    assert compacto(157_000_000) == "R$ 157,0 mi"
    assert compacto(500_000) == "R$ 500 mil"
    assert compacto(123.45) == "R$ 123,45"
    assert compacto(-2_500_000) == "R$ -2,5 mi"


def test_fator():
    from formato import fator
    assert fator(4.3) == "4,3×"
    assert fator(10.94) == "10,9×"


def test_pct():
    assert pct(110, 100) == "▲ 10%"
    assert pct(90, 100) == "▼ 10%"
    assert pct(100, 0) == "—"


def test_sem_acento():
    assert sem_acento("Fundação Câmara") == "FUNDACAO CAMARA"


def test_ente_publico_positivos():
    for nome in [
        "MUNICÍPIO DE SANTOS",
        "PREFEITURA MUNICIPAL DE SANTOS",
        "INSTITUTO DE PREVIDÊNCIA SOCIAL DOS SERVIDORES",
        "CAIXA ECONÔMICA FEDERAL",
        "INSS - Instituto Nacional do Seguro Social",
        "MINISTÉRIO DA FAZENDA",
        "FUNDO PENITENCIARIO",
        "FUNDACAO PARQUE TECNOLOGICO DE SANTOS",
        "CÂMARA MUNICIPAL DE SANTOS",
    ]:
        assert eh_ente_publico(nome), nome


def test_ente_publico_negativos():
    # fornecedores de mercado — inclusive os que quase casam com FUNDO/FUNDAÇÃO
    for nome in [
        "TERRACOM CONSTRUCOES LTDA",
        "ASSOCIAÇÃO FUNDO DE INCENTIVO A PESQUISA - AFIP",
        "FUNDACAO INSTITUTO DE PESQUISAS ECONOMI.FIPE",
        "CAMARA DE DIRIGENTES LOJISTAS",
        "JOSE DA SILVA",
    ]:
        assert not eh_ente_publico(nome), nome


# ── Identidade do favorecido ──────────────────────────────────────────────────
def test_identidade_cnpj_une_grafias():
    from formato import identidade_favorecido
    a = identidade_favorecido("INSTITUTO DE PREVIDÊNCIA SOCIAL", "08.717.299/0001-01")
    b = identidade_favorecido("IPREV - INST. PREV. SOCIAL", "08717299000101")
    assert a == b == ("cnpj:08717299000101", "cnpj")


def test_identidade_cpf_mascarado_nao_une_por_digitos():
    from formato import identidade_favorecido
    a = identidade_favorecido("JOSÉ DA SILVA", "***.158.308-**")
    b = identidade_favorecido("MARIA SOUZA", "***.158.308-**")
    c = identidade_favorecido("Jose  da Silva", "***.158.308-**")   # mesma pessoa, grafia
    assert a != b
    assert a == c == ("cpf:158308|JOSE DA SILVA", "cpf")
    assert identidade_favorecido("FULANO", "") == ("nome:FULANO", "nome")
    assert identidade_favorecido("FULANO", None)[1] == "nome"
    assert identidade_favorecido("X", "123")[1] == "doc"          # documento incompleto


def test_slug_e_nome_exibicao():
    from formato import identidade_favorecido, nome_exibicao, slug_favorecido
    assert slug_favorecido("cnpj:08717299000101") == "08717299000101"
    s = slug_favorecido("cpf:158308|JOSE DA SILVA")
    assert len(s) == 12 and s == slug_favorecido("cpf:158308|JOSE DA SILVA")
    grafias = {"INSTITUTO DE PREVID�NCIA SOCIAL": 3516,
               "INSTITUTO DE PREVIDENCIA SOCIAL": 331, "IPREV - INST. PREV.": 70}
    assert nome_exibicao(grafias) == "INSTITUTO DE PREVIDENCIA SOCIAL"   # sem U+FFFD vence
    assert nome_exibicao({"A LTDA": 1, "B LTDA": 1}) == "A LTDA"          # empate → alfabética
