# -*- coding: utf-8 -*-
"""Unidade de medida canônica — o gate mais importante do casamento.

`unidadeMedida` no PNCP é texto livre: a mesma coisa aparece como `M2`, `MT2`,
`M²`, `METRO QUADRADO`, `MTS2`. Comparar R$/m² com R$/unidade produz um número
espetacularmente errado e indefensável, então a regra é dura:

    **unidade que não está nesta tabela nunca é adivinhada — o item é rejeitado.**

Conversão só acontece DENTRO de uma família (comprimento, área, volume, massa,
contagem, tempo). `VERBA`, `LOTE`, `GLOBAL` e `SERVIÇO` são deliberadamente
mapeados para a família `opaco`, que não converte para nada: são rótulos que
escondem a quantidade real e nunca devem virar preço unitário comparável.

`fator` = quanto da unidade canônica cabe em 1 da unidade informada.
Preço por unidade canônica = preço informado ÷ fator.
Ex.: caixa com 100 unidades → fator 100 → R$ 250,00/caixa = R$ 2,50/unidade.
"""
import re

from texto import normalizar

# unidade canônica → família. Duas canônicas de famílias diferentes nunca casam.
FAMILIA = {
    "un": "contagem",
    "m": "comprimento", "m2": "area", "m3": "volume", "l": "volume",
    "kg": "massa",
    "mes": "tempo_mes", "dia": "tempo_dia", "hora": "tempo_hora",
    # Embalagens SEM quantidade declarada ganham cada uma a sua família e nunca
    # convertem para `un`: "caixa" só compara com "caixa". Uma caixa pode ter 10
    # ou 100 unidades, e o edital costuma não dizer — supor seria inventar.
    # (Com a quantidade declarada — "CX C/100" — o parser converte para `un`.)
    "caixa": "caixa", "frasco": "frasco", "comprimido": "comprimido",
    "ampola": "ampola", "lata": "lata", "pote": "pote", "rolo": "rolo",
    "envelope": "envelope", "tubo": "tubo", "galao": "galao", "saco": "saco",
    "bloco": "bloco",
    "resma": "resma",          # 500 folhas, mas o edital raramente diz — família própria
    "opaco": "opaco",
}

# sinônimo normalizado → (canônica, fator)
_TABELA = {
    # contagem
    "un": ("un", 1), "und": ("un", 1), "unid": ("un", 1), "unidade": ("un", 1),
    "unidades": ("un", 1), "ud": ("un", 1), "uni": ("un", 1),
    "pc": ("un", 1), "pca": ("un", 1), "peca": ("un", 1), "pecas": ("un", 1),
    "pct": ("un", 1), "pacote": ("un", 1),
    "cj": ("un", 1), "conjunto": ("un", 1), "kit": ("un", 1), "jogo": ("un", 1),
    "par": ("un", 2), "pares": ("un", 2),
    "duzia": ("un", 12), "dz": ("un", 12),
    "cento": ("un", 100), "centena": ("un", 100), "dezena": ("un", 10),
    "milheiro": ("un", 1000), "mil": ("un", 1000),
    # comprimento
    "m": ("m", 1), "mt": ("m", 1), "metro": ("m", 1), "metros": ("m", 1),
    "ml": ("m", 1), "metro linear": ("m", 1),   # ML = metro linear em obras
    "cm": ("m", 0.01), "centimetro": ("m", 0.01),
    "mm": ("m", 0.001), "milimetro": ("m", 0.001),
    "km": ("m", 1000), "quilometro": ("m", 1000),
    # área
    "m2": ("m2", 1), "mt2": ("m2", 1), "mts2": ("m2", 1),
    "metro quadrado": ("m2", 1), "metros quadrados": ("m2", 1),
    "metroquadrado": ("m2", 1),   # sem espaço, como o PNCP às vezes devolve
    "cm2": ("m2", 0.0001),
    # volume
    "m3": ("m3", 1), "mt3": ("m3", 1), "metro cubico": ("m3", 1),
    "l": ("l", 1), "lt": ("l", 1), "litro": ("l", 1), "litros": ("l", 1),
    # massa
    "kg": ("kg", 1), "quilo": ("kg", 1), "quilograma": ("kg", 1),
    "kilograma": ("kg", 1), "kilo": ("kg", 1),   # grafia com K aparece no PNCP
    "g": ("kg", 0.001), "grama": ("kg", 0.001), "gr": ("kg", 0.001),
    "t": ("kg", 1000), "ton": ("kg", 1000), "tonelada": ("kg", 1000),
    # embalagens sem quantidade declarada (família própria — ver FAMILIA)
    "cx": ("caixa", 1), "caixa": ("caixa", 1),
    "fr": ("frasco", 1), "frs": ("frasco", 1), "frasco": ("frasco", 1),
    "comprimido": ("comprimido", 1), "cp": ("comprimido", 1),
    "comp": ("comprimido", 1), "cpr": ("comprimido", 1),
    "amp": ("ampola", 1), "ampola": ("ampola", 1),
    # "lt" NÃO entra aqui: já significa litro acima, e litro é muito mais comum
    "lta": ("lata", 1), "lata": ("lata", 1),
    "pt": ("pote", 1), "pote": ("pote", 1),
    "rl": ("rolo", 1), "rol": ("rolo", 1), "rolo": ("rolo", 1),
    "fra": ("frasco", 1),
    "bloco": ("bloco", 1), "bl": ("bloco", 1),
    "env": ("envelope", 1), "envelope": ("envelope", 1),
    "tb": ("tubo", 1), "tubo": ("tubo", 1), "bisnaga": ("tubo", 1),
    "gl": ("galao", 1), "galao": ("galao", 1), "balde": ("galao", 1),
    "sc": ("saco", 1), "saco": ("saco", 1), "fardo": ("saco", 1),
    # tempo (cada um é sua própria família: mês de locação ≠ 30 diárias)
    "mes": ("mes", 1), "meses": ("mes", 1), "mensal": ("mes", 1),
    "dia": ("dia", 1), "dias": ("dia", 1), "diaria": ("dia", 1),
    "hora": ("hora", 1), "horas": ("hora", 1), "h": ("hora", 1),
    # papel
    "resma": ("resma", 1), "resmas": ("resma", 1),
    # opacas — reconhecidas para poder REJEITAR com motivo claro
    "verba": ("opaco", 1), "vb": ("opaco", 1), "global": ("opaco", 1),
    "lote": ("opaco", 1), "servico": ("opaco", 1), "sv": ("opaco", 1),
    "srv": ("opaco", 1), "outras unidades": ("opaco", 1),
    "percentual": ("opaco", 1), "ponto": ("opaco", 1),
}

# "CX C/100", "CAIXA COM 12", "PCT C/ 50 UN", "FD 20" e a unidade de fornecimento
# padronizada do PNCP: "Caixa 100,00 UN", "Pacote 100,00 UN", "Saco 100,00 UN".
# Esta última é frequente e traz a contagem explícita — ignorá-la descartaria
# comparações perfeitamente válidas por "unidade desconhecida".
_EMBALAGEM = re.compile(
    r"^(?:cx|caixa|pct|pacote|fd|fardo|pc|emb|embalagem|sc|saco|cj|conjunto|kit|"
    r"bl|bloco|rl|rolo|env|envelope|tb|tubo|fr|frasco|pt|pote|lta|lata|amp|ampola)\s*"
    r"(?:c|com)?\s*(\d+(?:\.\d+)?)\s*(?:un|und|unid|unidade|unidades|pc|peca|pecas)?$")

# litragem/gramatura embutida: "FRASCO 500ML", "SACO 5KG"
_QTD_EMBUTIDA = re.compile(
    r"^(?:fr|frs|frasco|gl|galao|bd|balde|sc|saco|bombona|tb|tubo|lata|lta|"
    r"bisnaga|emb|embalagem|pote|pt|pct|pacote|amp|ampola|tubete|sache|"
    r"flaconete|seringa|rl|rolo|bobina|cx|caixa|bolsa|copo|garrafa|garrafao|"
    r"par)\s*\(?\s*(?:de\s*|com\s*)?"
    r"(\d+(?:\.\d+)?)\s*"
    r"(ml|l|lt|litro|litros|g|gr|mg|kg|grama|gramas|quilo|m|mt|metro|metros|cm)\)?$")

# "Pacote 100,00 FL", "PACOTE (DE 1.000 FOLHAS)" — contagem de itens, não massa
# nem volume. Sem esta regra o fallback de primeira palavra devolvia ("un", 1) e
# publicava o preço do pacote como preço da folha (erro de até 1000×).
_CONTAGEM_EMBUTIDA = re.compile(
    r"^(?:cx|caixa|pct|pacote|fd|fardo|emb|embalagem|sc|saco|bl|bloco|rl|rolo|"
    r"talao|resma)\s*\(?\s*(?:de\s*|com\s*|c\s*)?"
    r"([\d.]+)\s*"
    r"(?:fl|folha|folhas|un|und|unid|unidade|unidades|pc|peca|pecas|panos?)\)?$")

_SUB_L = {"ml": 0.001, "l": 1, "lt": 1, "litro": 1, "litros": 1}
_SUB_KG = {"g": 0.001, "kg": 1, "grama": 0.001, "quilo": 1, "mg": 0.000001}
_SUB_M = {"m": 1, "mt": 1, "metro": 1, "metros": 1, "cm": 0.01}

# Número ISOLADO na string — uma contagem. Não confundir com o dígito que faz
# parte do nome da unidade ('m2', 'm3'), que precisa continuar passando.
_NUMERO_SOLTO = re.compile(r"(?<!\w)\d[\d.]*(?!\w)")


def _quantidade(s: str):
    """'1.000'→1000 · '100.00'→100.0 · '100'→100 · lixo→None.

    `normalizar` já trocou a vírgula decimal por ponto, então '1,000' e '1.000'
    chegam idênticos: a regra tem de ser POSICIONAL. Três dígitos depois do
    ponto = separador de milhar (`CX COM 5.000 UND` são cinco mil, não cinco);
    uma ou duas casas = decimal (`Pacote 100,00 FL` são cem).
    """
    t = (s or "").strip(".")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        return float(t.replace(".", ""))
    try:
        return float(t)
    except ValueError:
        return None


def normalizar_unidade(bruto):
    """Texto livre → (canônica, fator) ou (None, None) se desconhecida.

    (None, None) é resultado legítimo e frequente: significa "não sei, rejeite".
    """
    t = normalizar(bruto)
    if not t:
        return (None, None)
    t = t.replace(" c ", " com ")           # 'cx c 100' → 'cx com 100'

    if t in _TABELA:
        return _TABELA[t]

    for rx, familia in ((_EMBALAGEM, "un"), (_CONTAGEM_EMBUTIDA, "un")):
        m = rx.match(t)
        if m:
            n = _quantidade(m.group(1))
            return (familia, n) if (n and n > 0) else (None, None)

    m = _QTD_EMBUTIDA.match(t)
    if m:
        n, sub = _quantidade(m.group(1)), m.group(2)
        # 'FRASCO 0ML' existe em edital mal digitado; fator zero viraria divisão
        # por zero no cálculo do preço unitário — rejeitar na fonte
        if n and n > 0:
            if sub in _SUB_L:
                return ("l", n * _SUB_L[sub])
            if sub in _SUB_KG:
                return ("kg", n * _SUB_KG[sub])
            if sub in _SUB_M:
                return ("m", n * _SUB_M[sub])
        return (None, None)

    # Última tentativa: primeira palavra ("m2 instalado", "un fornecida").
    # NUNCA quando há um número solto: aí a contagem existe mas não foi
    # interpretada, e devolver fator 1 publicaria o preço da embalagem como
    # preço da unidade — 'Pacote 100,00 FL' virava ('un', 1), erro de 100×.
    if any((_quantidade(x) or 0) > 1 for x in _NUMERO_SOLTO.findall(t)):
        return (None, None)
    primeira = t.split()[0]
    if primeira in _TABELA:
        return _TABELA[primeira]

    return (None, None)


def converter(bruto, canonica_alvo):
    """Fator para levar 1 unidade `bruto` à `canonica_alvo`, ou None.

    None quando a unidade é desconhecida, quando as famílias diferem, ou quando
    a família é `opaco` — em todos os casos o item deve ser rejeitado com o
    motivo `unidade_desconhecida`, nunca convertido no chute.
    """
    can, fator = normalizar_unidade(bruto)
    if can is None:
        return None
    alvo = normalizar(canonica_alvo)
    if FAMILIA.get(can) == "opaco" or FAMILIA.get(alvo) == "opaco":
        return None
    if can == alvo:
        return fator
    # mesma família, canônicas distintas: só volume tem duas bases (m3 e l)
    if FAMILIA.get(can) == FAMILIA.get(alvo) == "volume":
        if can == "m3" and alvo == "l":
            return fator * 1000
        if can == "l" and alvo == "m3":
            return fator / 1000
    return None
