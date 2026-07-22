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
