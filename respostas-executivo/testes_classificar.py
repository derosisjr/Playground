#!/usr/bin/env python3
"""Testes do classificador de respostas do Executivo.

As fixtures são trechos REAIS, extraídos dos PDFs arquivados no Drive — o nome de
cada teste aponta o arquivo de origem, para quem precisar reconferir.

    python -m unittest discover -s respostas-executivo -p "testes_*.py"
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classificar import (  # noqa: E402
    ENCAMINHAMENTO, INDETERMINADO, MERITO, PENDENTE, PRORROGACAO,
    RESPONDIDO, SO_ENCAMINHAMENTO, SO_PRORROGACAO, classificar, situacao,
)

# RESPOSTA_1_4164-2025 (idêntico em 3912, 3915, 4010...): Ofício 512/2025-ALEG/SECC,
# um pedido de prazo em lote citando 18 requerimentos.
PRORROGACAO_LOTE = """GABINETE DO PREFEITO
Ofício nº 512/2025-ALEG/SECC
A Sua Excelência o Senhor ADÍLSON DOS SANTOS JÚNIOR
Santos, 28 de outubro de 2025.
Presidente da Câmara Municipal Santos – SP
Senhor Presidente,
Acerca dos expedientes abaixo relacionados e para ciência do nobre vereador RUI DE ROSIS
JÚNIOR, solicitamos a Vossa Excelência as prorrogações dos prazos por 15 (quinze) dias,
conforme dispõe o artigo 58, inciso XVIII da Lei Orgânica do Município:
Requerimento Processo 004167/2025 859284 004166/2025 859272 004165/2025 859271
004164/2025 859269 004163/2025 859267 004083/2025 858802 004082/2025 858800
Aproveitamos a oportunidade para renovar a Vossa Excelência e seus dignos pares,
protestos de elevada estima e distinta consideração.
Atenciosamente,
“ASSINADO DIGITALMENTE” ROGÉRIO SANTOS Prefeito de Santos
"""

# RESPOSTA_1_1729-2026: ofício-envelope do Gabinete (quebra de linha bagunçada como
# sai do extrator de texto).
ENCAMINHAMENTO_1729 = """GABINETE DO PREFEITO
Ofício n.º 939.872/2026-ALEG/SECC
Santos, 28 de maio de 2026.
A Sua Excelência o Senhor ADÍLSON DOS SANTOS JÚNIOR Presidente da Câmara Municipal
Assunto: Resposta ao requerimento n.º 1729/2026 do nobre vereador Rui de Rosis Júnior.
Senhor Presidente,
Em resposta ao requerimento supracitado, cumpre-nos encaminhar a essa
Casa Legislativa cópia dos esclarecimentos prestados pela Secretaria Municipal de
Finanças e Gestão.
Aproveitamos a oportunidade para renovar a Vossa Excelência e seus
dignos pares, protestos de elevada estima e distinta consideração.
"""

# RESPOSTA_2_2845-2026: mesma fórmula, redação um pouco diferente ("os" em vez de
# "cópia dos") — a regra não pode depender dessa variação.
ENCAMINHAMENTO_2845 = """GABINETE DO PREFEITO
Ofício nº 958.538/2026-ALEG/SECC
Assunto: Resposta ao requerimento nº 2845/2026 do nobre vereador Rui de Rosis Júnior.
Senhor Presidente,
Em resposta ao requerimento supracitado, cumpre-nos encaminhar a essa Casa Legislativa
os esclarecimentos prestados pela Secretaria Municipal das Prefeituras Regionais.
Aproveitamos a oportunidade para renovar a Vossa Excelência e seus dignos pares,
protestos de elevada estima e distinta consideração.
Atenciosamente,
“ASSINADO DIGITALMENTE” AUDREY KLEYS CABRAL DE OLIVEIRA DINAU
Prefeita de Santos Em exercício
RCM Digitally signed by AUDREY KLEYS CABRAL DE OLIVEIRA DINAU:19932027812
Date: 2026.07.01 11:53:55 -03:00 Reason: AUDREY KLEYS CABRAL DE . otnemucode tseda
nigápa mitlúa no ãtse) s(arutanissa) s(ae rboss eõçamrofnis A. etnemlatigido danissai
ofo tnemucode tsEe mrofnie s otnemucoDatlusnoc/cilbup/ppa/mpb/rb.moc.mocel.sotnasmp
.ppa//:sptthe tiso e ssecaa icnêrefnoca rap, osserpmie SOLIVEIRA DINAU:19932027812
"""

# RESPOSTA_1_1017-2026: a armadilha central. O ofício de encaminhamento e a
# resposta da CET estão no MESMO PDF — ofício na 1ª página, conteúdo na 2ª. Se
# olhássemos só a fórmula do ofício, este arquivo (que É a resposta) sumiria da
# contagem. Um em cada 22 ofícios amostrados vem de fato sozinho.
ENCAMINHAMENTO_COM_ANEXO_JUNTO = """SECRETARIA DA CASA CIVIL
Oficio n 916.614/2026-ALEG/SECC
Santos, 25 de maio de 2026.
A Sua Excelência o Senhor ADILSON DOS SANTOS JUNIOR Presidente da Câmara Municipal
Assunto: Resposta à indicação n° 1017/2026 do nobre vereador Rui de Rosis Júnior.
Senhor Presidente,
Em resposta à indicação supracitada, cumpre-nos encaminhar a essa Casa Legislativa os
esclarecimentos prestados pela Companhia de Engenharia de Tráfego de Santos.
Aproveitamos a oportunidade para renovar a Vossa Excelência e seus dignos pares,
protestos de elevada estima e distinta consideração.
Atenciosamente,
RVB - SGCA
Mauro Fernando Zannin Júnior Assessoria de Assuntos Legislativos
Palacio José Bonifacio - Praça Mauá. s/n - 4° andar - Centro - Santos/SP - CEP 11.010-900
Tel.: (13) 3201-5090
CET SANTOS
Referente: Processo 2339-2026 DEALE 245713/2026-31 Assunto: Fiscalização
Informamos que conforme decreto nº 11457 a partir de 26/02/26 iniciamos a
disponibilidade de ativações a partir de 30 minutos na Zona Azul de Santos com valor
proporcional da hora de ativação.
JOSIANE NEGOSEKI C. ROCHA Chefe de Unidade
Santos, 26 de março de 2026
CET- Santos
"""

# RESPOSTA_1_7029-2025: o ofício realmente sozinho, para contraste.
ENCAMINHAMENTO_PURO_CASA_CIVIL = """SECRETARIA DA CASA CIVIL
Oficio n 889.402/2025-ALEG/SECC
A Sua Excelência o Senhor ADILSON DOS SANTOS JUNIOR Presidente da Câmara Municipal
Assunto: Resposta à indicação n° 7029/2025 do nobre vereador Rui de Rosis Júnior.
Senhor Presidente,
Em resposta à indicação supracitada, cumpre-nos encaminhar a essa Casa Legislativa os
esclarecimentos prestados pela Secretaria Municipal de Serviços Públicos.
Aproveitamos a oportunidade para renovar a Vossa Excelência e seus dignos pares,
protestos de elevada estima e distinta consideração.
Atenciosamente,
Mauro Fernando Zannin Júnior Assessoria de Assuntos Legislativos
Palacio José Bonifacio--Praça Mauá, s/n - 4° andar - Centro - Santos/SP - CEP 11.010-900
Tel.: (13) 3201-5090
"""

# RESPOSTA_2_1729-2026: a SEFIN entrega os processos por link. Fala em "prazo de
# 30 dias", mas é prazo de ACESSO ao material — é resposta de mérito.
MERITO_SEFIN = """SECRETARIA MUNICIPAL DE FINANÇAS E GESTÃO
AO DEALE
Santos, 27 de Maio de 2026.
Processo Digital: 939.872 (281177/2026-18) – Requerimento Vereador: Rui de Rossis Jr
Assunto: Solicitação das cópias integrais dos processos administrativos PA 71049/2025-88.
O prazo de acesso será de 30 dias a partir de 27/05/2026.
https://entrega.santos.sp.gov.br/e6334d50fdfa
Atenciosamente, CÍNTIA SILVA DE OLIVEIRA CHEFE DA SEA-CAD
"""

# RESPOSTA_1_2845-2026: resposta item a item da SEPREF.
MERITO_SEPREF = """Santos, 30 de junho de 2026.
RESPOSTA AO PROCESSO DIGITAL Nº 958.538
1 – Quantidade de massa asfáltica dependerá da extensão e diâmetro da área a ser
reparada, o que inviabiliza a resposta.
2 – O cálculo não é feito por metro linear.
3 – Sim
4 – Sim
5 – c) Nenhuma d) Não há registro
6 – Prejudicada a resposta.
Rivaldo Santos — Secretaria Municipal das Prefeituras Regionais
"""

# PEDIDO_2036-2026 (requerimento sobre o aditivo do Teatro Coliseu). Não é resposta,
# mas cita "dilação de prazo" e "prorrogação do prazo" várias vezes: é a armadilha
# que o teto de tamanho tem de barrar, caso um PDF assim caia no classificador.
REQUERIMENTO_COLISEU = """CÂMARA MUNICIPAL DE SANTOS — GABINETE DO VEREADOR RUI DE ROSIS JR.
REQUERIMENTO Nº — COM BASE NO REGIMENTO INTERNO DESTA CASA DE LEIS, REQUEIRO AO
EXCELENTÍSSIMO SENHOR PREFEITO MUNICIPAL QUE SOLICITE AO ÓRGÃO COMPETENTE
INFORMAÇÕES SOBRE O NOVO ADITAMENTO PARA DILAÇÃO DE PRAZO DA OBRA DA ETAPA 2 DO
TEATRO COLISEU
Considerando que as obras de restauração e requalificação do Teatro Coliseu constituem
investimento relevante de recursos públicos, com impacto direto no patrimônio histórico,
cultural e turístico do Município;
Considerando que a denominada "Etapa 2" das obras foi contratada em 04 de outubro de
2024, pelo valor superior a R$ 4.000.000,00, com prazo inicial de execução de 9 meses;
Considerando que, em 17 de outubro de 2025, foi formalizado termo aditivo contratual para
prorrogação do prazo por mais 60 (sessenta) dias, acompanhado de acréscimo de
aproximadamente 20% no valor do contrato;
Considerando que, posteriormente, em 23 de abril de 2026, foi publicada nova prorrogação
de prazo por mais 45 (quarenta e cinco) dias, indicando sucessivas alterações no
cronograma originalmente pactuado;
Considerando que prorrogações reiteradas, especialmente quando acompanhadas de aditivos
financeiros relevantes, podem indicar falhas de planejamento, inadequação de projeto,
insuficiência de estudos prévios ou problemas na execução contratual;
REQUEIRO, após a devida apreciação dos Nobres Pares, que seja oficiado ao Excelentíssimo
Senhor Prefeito Municipal de Santos, para que, por meio da Secretaria competente, no prazo
do Art. 120, parágrafo único da Resolução nº 16, de 26 de julho 2019, informe:
1. Informar qual o percentual atual de execução física da Etapa 2 das obras do Teatro
Coliseu, detalhando os serviços já concluídos e os ainda pendentes.
2. Informar qual a nova previsão oficial de conclusão e entrega da Etapa 2, considerando
as prorrogações já realizadas.
3. Justificar, de forma detalhada e documental, os motivos que ensejaram a prorrogação
de prazo formalizada em outubro de 2025, bem como o acréscimo de aproximadamente 20% no
valor do contrato, indicando: (a) quais serviços adicionais foram incluídos; (b) se tais
serviços eram previsíveis à época da licitação; (c) se houve alteração de projeto ou escopo.
4. Justificar, de forma detalhada, os motivos da nova prorrogação publicada em abril de
2026, indicando: (a) quais fatores impediram o cumprimento do prazo já aditado; (b) se
houve falhas de execução, atraso da contratada ou intercorrências técnicas; (c) quais
medidas foram adotadas pela fiscalização do contrato.
5. Informar se houve aplicação de penalidades à empresa contratada, em razão de atrasos
ou descumprimentos contratuais, anexando documentação comprobatória.
6. Informar se a Administração possui cronograma físico-financeiro atualizado da obra,
encaminhando cópia integral.
7. Esclarecer se, após a conclusão da Etapa 2, o Teatro Coliseu estará apto para
reabertura ao público, ou se ainda haverá necessidade de novas intervenções.
8. Em caso de necessidade de novas etapas, informar: (a) quais etapas adicionais estão
previstas; (b) estimativa de custo; (c) prazo estimado; (d) estágio atual de planejamento
ou licitação.
9. Informar qual o custo total estimado da obra completa do Teatro Coliseu, considerando
todas as etapas já executadas, em execução e planejadas.
10. Esclarecer se foi realizada avaliação interna quanto às causas das sucessivas
prorrogações, bem como se há medidas em curso para evitar novas dilatações de prazo.
Sendo só para o momento, reitero os protestos de elevada estima e distinta consideração,
colocando-me à disposição. Santos, 23 de abril de 2026. Rui De Rosis Jr. Vereador - PL
"""


class TestClassificar(unittest.TestCase):
    def test_prorrogacao_em_lote_oficio_512(self):
        self.assertEqual(classificar(PRORROGACAO_LOTE), PRORROGACAO)

    def test_encaminhamento_1729_2026(self):
        self.assertEqual(classificar(ENCAMINHAMENTO_1729), ENCAMINHAMENTO)

    def test_encaminhamento_2845_2026_variacao_de_redacao(self):
        self.assertEqual(classificar(ENCAMINHAMENTO_2845), ENCAMINHAMENTO)

    def test_encaminhamento_puro_da_casa_civil(self):
        self.assertEqual(classificar(ENCAMINHAMENTO_PURO_CASA_CIVIL), ENCAMINHAMENTO)

    def test_oficio_com_a_resposta_anexada_no_mesmo_pdf_e_merito(self):
        self.assertEqual(classificar(ENCAMINHAMENTO_COM_ANEXO_JUNTO), MERITO)

    def test_merito_sefin_prazo_de_acesso_nao_e_prorrogacao(self):
        self.assertEqual(classificar(MERITO_SEFIN), MERITO)

    def test_merito_sepref_item_a_item(self):
        self.assertEqual(classificar(MERITO_SEPREF), MERITO)

    def test_requerimento_sobre_aditivo_nao_vira_prorrogacao(self):
        self.assertEqual(classificar(REQUERIMENTO_COLISEU), MERITO)

    def test_pdf_sem_camada_de_texto(self):
        self.assertEqual(classificar(""), INDETERMINADO)
        self.assertEqual(classificar("   \n  "), INDETERMINADO)


class TestSituacao(unittest.TestCase):
    def test_sem_resposta(self):
        self.assertEqual(situacao([]), PENDENTE)

    def test_so_prorrogacao_4164_3915_4010(self):
        self.assertEqual(situacao([PRORROGACAO]), SO_PRORROGACAO)

    def test_prorrogacao_seguida_de_resposta_3912(self):
        self.assertEqual(situacao([PRORROGACAO, ENCAMINHAMENTO, MERITO]), RESPONDIDO)

    def test_encaminhamento_mais_merito_1729(self):
        self.assertEqual(situacao([ENCAMINHAMENTO, MERITO]), RESPONDIDO)

    def test_so_encaminhamento(self):
        self.assertEqual(situacao([ENCAMINHAMENTO]), SO_ENCAMINHAMENTO)

    def test_encaminhamento_tem_prioridade_sobre_prorrogacao(self):
        self.assertEqual(situacao([PRORROGACAO, ENCAMINHAMENTO]), SO_ENCAMINHAMENTO)

    def test_indeterminado_conta_como_merito(self):
        self.assertEqual(situacao([PRORROGACAO, INDETERMINADO]), RESPONDIDO)


if __name__ == "__main__":
    unittest.main()
