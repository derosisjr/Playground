"""Ente público × fornecedor (revisão de 2026-10), com os NOMES REAIS da base que a
regra antiga classificava errado. Os casos antigos seguem em test_formato.py."""
from formato import FUNDACOES_DUVIDOSAS, eh_ente_publico


def test_nomes_reais_privados_que_eram_contados_como_ente():
    for nome in [
        "ASSOCIAÇÃO FUNDO DE INCENTIVO À PESQUISA",                                      # AFIP sem a sigla
        "FEDERACAO DE TENIS DE MESA DO ESTADO DE SAO PAULO",
        "ASSOCIAÇAO DE LUTAS DO ESTADO DE SAO PAULO",
        "FUNDACAO SETTAPORT DE RESPONSABILIDADE SOCIAL E INT.PORTO C",
        "FUNDACAO DE APOIO A UNIVERSIDADE DE SAO PAULO",                                  # FUSP
        "FUNDAÇÃO DE APOIO A UNIVERSIDADE FEDERAL DE SÃO PAULO",                          # FAP-UNIFESP
        "FUNDACAO CENTRO TECNOLOGICO DE HIDRAULICA-FCTH",
        "ASSOCIACAO NACIONAL DE ENTIDADES DE PREVIDENCIA DE ESTADOS E MUNICIPIOS - ANEPREM",
        "ASSOCIAÇAO DOS SECRETARIOS MUNICIPAIS DE ESPORTE E LAZER DO ESTADO DE SÃO PAULO",
        "ASSOCIACAO DAS SECRETARIAS MUNICIPAIS DE FINANCAS DO ESTADO DE SAO PAULO",
        "ASSOCIACAO DAS PREFEITURAS DAS CIDADES ESTANCIA DO ESTADO DE SAO PAULO",
        "FUNDIC - FUNDO PARA O DESENVOLVIMENTO DAS CIENCIAS DA CONTRUÇÃO",                # FUNDO sem qualificador público
        "SINDICATO DOS SERVIDORES MUNICIPAIS DE SANTOS",
        "COMERCIAL ESTADO DE SAO PAULO LTDA",                                            # forma privada vence
        "XYZ SERVICOS MUNICIPAIS - ME",
        "PUXE COMUNICACAO EIRELI",
    ]:
        assert not eh_ente_publico(nome), nome


def test_nomes_reais_publicos_continuam_ente():
    for nome in [
        "FUNDO NACIONAL DE SAUDE/MINISTERIO DA SAUDE",
        "FUNDO ESTADUAL DE ASSISTENCIA SOCIAL",
        "FUNDO PREVIDENCIARIO DOS SERVIDORES PUBLICOS DE PRAIA GRANDE - FPGPREV",
        "FUNDO DE PREVIDENCIA SOCIAL DO MUNICIPIO DE OLINDA FUNDPREV",
        "FUPES - FUNDAÇÃO PRO ESPORTE SANTOS",
        "FUNDACAO PRO-ESPORTE DE SANTOS",
        "FUNDACAO ARQUIVO E MEMORIA DE SANTOS",
        'FUNDACAO "PROF.DR.MANOEL PEDRO PIMENTEL"- FUNAP',
        "FUNDAÇÃO UNIVERSIDADE DE BRASILIA",
        "Fundacao de Aposentadorias e Pensoes dos Servidores do Estado de Pernambuco",
        "CORPO DE BOMBEIROS DA POLICIA MILITAR DO ESTADO DE SÃO PAULO",
        "CETESB COMPANHIA AMBIENTAL DO ESTADO DE SÃO PAULO",
        "COMPANHIA DE PROCESSAMENTO DE DADOS DO ESTADO DE SAO PAULO - PRODESP",
        "COMPANHIA DE DESENVOLVIMENTO HABITACIONAL E URBANO DO ESTADO DE SAO PAULO-CDHU",
        "SAO PAULO SECRETARIA DA SEGURANCA PUBLICA",
        "GOVERNO DO ESTADO DE SAO PAULO",
        # exceções explícitas: estatais do município
        "PRODESAN PROGRESSO E DESENVOLVIMENTO DE SANTOS SA",
        "COHAB CIA HABITACAO DA BAIXADA SANTISTA",
        "CET - COMPANHIA DE ENGENHARIA DE TRAFEGO DE S",
    ]:
        assert eh_ente_publico(nome), nome


def test_fundacoes_duvidosas_seguem_como_ente_ate_decisao():
    # pendentes de decisão do usuário (2026-10): mantêm o comportamento anterior
    assert len(FUNDACOES_DUVIDOSAS) == 4
    for nome in ["FUNDACAO PINACOTECA BENEDITO CALIXTO", "FUNDACAO CENTRO DE EXCELENCIA PORTUARIA DE SANTOS - CENEP-SANTOS",
                 "FUNDACAO PARQUE TECNOLOGICO DE SANTOS",
                 "FUNDAÇÃO DE PREVIDENCIA COMPLEMENTAR DO ESTADO DE SAO PAULO"]:
        assert eh_ente_publico(nome), nome
