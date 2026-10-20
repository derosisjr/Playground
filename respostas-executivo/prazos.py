"""Prazo da Lei Orgânica para o Executivo responder a requerimentos.

LOM de Santos, art. 58, XVIII — compete ao Prefeito "prestar, à Câmara,
obrigatoriamente, dentro de quinze dias, informações sobre qualquer matéria
solicitada (...), salvo prorrogação, a seu pedido e por igual período" (texto
conferido no Legis, documento 9596, em 2026-10-17).

A data de protocolo na Prefeitura não é registrada na planilha (a coluna existe e
está vazia): o prazo conta da data da SESSÃO que aprovou o requerimento, em dias
corridos — o painel diz isso na nota de método. O painel (`requerimentos-app.js`)
espelha PRAZO_DIAS para classificar as respostas já recebidas.
"""

import re
from datetime import date, datetime, timedelta

PRAZO_DIAS = 15
PRORROGACAO_DIAS = 15  # "por igual período"


def data_br(s) -> date | None:
    """'dd/mm/aaaa' → date (None se vazio ou inválido)."""
    try:
        return datetime.strptime(str(s).strip(), "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def vence_em(data_sessao: str, situacao: str) -> str:
    """Data-limite (dd/mm/aaaa) de quem ainda não tem resposta de mérito; '' para
    respondido ou sem data. Com pedido de prorrogação o prazo vai a 15 + 15."""
    if situacao == "respondido":
        return ""
    inicio = data_br(data_sessao)
    if not inicio:
        return ""
    dias = PRAZO_DIAS + (PRORROGACAO_DIAS if situacao == "so_prorrogacao" else 0)
    return (inicio + timedelta(days=dias)).strftime("%d/%m/%Y")


def enviado(situacao_camara: str) -> bool:
    """O pedido já saiu da Câmara para a Prefeitura? O prazo da LOM só corre depois disso.
    "Situação na Câmara" (espelho da listagem, pré-cadastro R5): "Aprovado"/"Encaminhado" =
    sim; "-" (ainda não votado) ou outra coisa = não. Vazio = linha anterior ao
    pré-cadastro, sem o dado: conta como enviado (era assim antes)."""
    s = (situacao_camara or "").strip().lower()
    return not s or s.startswith(("aprovad", "encaminhad"))


def fora_do_prazo(item: dict, hoje: date) -> bool:
    """Sem resposta de mérito e com o prazo (já com a prorrogação, se houve) vencido."""
    limite = data_br(item.get("vence_em"))
    return item.get("situacao") != "respondido" and limite is not None and hoje > limite


# "Resposta ao requerimento 210/2025 - …", "Requerimento nº 1.022/2025", e até o
# "rrequerimento" digitado na planilha — o número citado é o de um pedido anterior
# do mandato que este desdobra ou cobra.
RE_CITA = re.compile(
    r"requerimento\w*\s*(?:n\s*[º°o.]*\s*)?(\d[\d.]{0,6})\s*/\s*(\d{4})", re.IGNORECASE)


def citados(assunto: str) -> list[str]:
    """Números ('210/2025') de requerimentos citados no assunto, na ordem, sem repetir."""
    vistos: list[str] = []
    for num, ano in RE_CITA.findall(assunto or ""):
        digitos = num.replace(".", "")
        if not digitos.isdigit() or len(digitos) > 5:
            continue
        n = f"{int(digitos)}/{ano}"
        if n not in vistos:
            vistos.append(n)
    return vistos
