"""Sigla da secretaria indicada pelo gabinete na planilha (coluna "Secretaria").

A coluna é texto livre digitado pela assessoria ("COMUNICAÇÃO" e "SECOM", "SAÚDE" e
"SMS", "NÃO SEI", "#NAME?"...). Para o índice público só vai sigla reconhecível,
com os sinônimos unificados; o resto fica vazio — e o painel conta isso como "sem
secretaria indicada", sem adivinhar.
"""

import re

from comum.formato import sem_acento

# grafia normalizada (maiúscula, sem acento) → sigla publicada
SINONIMOS = {
    "COMUNICACAO": "SECOM",
    "SAUDE": "SMS",
    "POLI PONTA DA PRAIA": "SMS",  # policlínica: rede municipal de saúde
    "SED'S": "SEDS",
    "SED S": "SEDS",  # "SED´S": o NFKD transforma o acento agudo solto em espaço
    "SETUR": "SECTUR",
}
# não é secretaria: dúvida da assessoria, erro de fórmula, rótulo genérico ou
# nome de fornecedor (ex.: a agência de publicidade)
INVALIDAS = {"", "NAO SEI", "#NAME?", "GERAL", "EMPRESAS", "SEMPRE"}
RE_SIGLA = re.compile(r"^[A-Z][A-Z ]{1,24}$")


def canonica(texto: str) -> str:
    """Sigla publicada ('' quando não dá para afirmar qual secretaria é)."""
    bruto = sem_acento(str(texto or ""), forma="NFKD", caixa="alta").strip()
    bruto = re.sub(r"\s+", " ", bruto)
    if bruto in INVALIDAS:
        return ""
    # "SEDS/SEDUC" e "SEDUC/SEDS" são o mesmo par
    partes = sorted({SINONIMOS.get(p.strip(), p.strip()) for p in bruto.split("/") if p.strip()})
    if not partes or not all(RE_SIGLA.match(p) for p in partes):
        return ""
    return "/".join(partes)
