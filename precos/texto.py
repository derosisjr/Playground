# -*- coding: utf-8 -*-
"""Normalização de texto para o casamento de itens entre municípios.

O PNCP não traz código de catálogo (CATMAT/CATSER) nas compras municipais de
Santos e das cidades-par — `catalogoCodigoItem` e `ncmNbsCodigo` vêm nulos. Logo
o único elo entre "placa de metalon" de Santos e a de Praia Grande é o texto da
descrição, digitado à mão por servidores diferentes, em sistemas diferentes.

Duas decisões deliberadas, ambas na direção de errar para menos:

  - **Sem stemming.** Radicalizador de pt-BR aproxima palavras que não são a
    mesma coisa ("cadeira"/"cadeirante", "papel"/"papelaria") e o falso positivo
    entra silencioso na mediana. Abreviação só é expandida por dicionário fixo.
  - **Tokens curtos fora, exceto com dígito.** "de", "kg" e "un" viram ruído no
    jaccard; já "a4", "2x1" e "75g" são justamente o que distingue um item.
"""
import re
import unicodedata

# Abreviações de fato observadas em descrições do PNCP. Dicionário FECHADO —
# crescer só com caso real conferido, nunca por suposição.
_ABREV = {
    "p/": " para ", "c/": " com ", "s/": " sem ", "n/": " nao ",
    "qtd": " quantidade ", "qtde": " quantidade ", "und": " unidade ",
    "unid": " unidade ", "pç": " peca ", "pc": " peca ", "pcs": " peca ",
    "mat": " material ", "instal": " instalacao ", "aprox": " aproximadamente ",
    "ref": " referencia ", "esp": " especificacao ", "med": " medindo ",
}

# Palavras sem poder discriminante em descrição de item de licitação.
_STOPWORDS = {
    "de", "da", "do", "dos", "das", "para", "com", "sem", "em", "no", "na",
    "nos", "nas", "por", "ao", "aos", "que", "seu", "sua", "ou", "the",
    "tipo", "modelo", "referencia", "marca", "cor", "conforme", "edital",
    "anexo", "termo", "especificacao", "especificacoes", "medindo",
    "aproximadamente", "unidade", "item", "itens", "lote", "fornecimento",
    "aquisicao", "contratacao", "prestacao", "servico", "servicos",
    "empresa", "especializada", "demais", "conforme", "descrito", "detalhes",
    "constante", "constantes", "minimo", "minima", "maximo", "maxima",
    "qualidade", "primeira", "nova", "novo", "novos", "novas",
}

_SUPERSCRIPT = str.maketrans({"²": "2", "³": "3", "º": "", "ª": "", "°": ""})


def sem_acento(s) -> str:
    """Minúsculas sem acento (NFD, descarta combinantes)."""
    s = "" if s is None else str(s)
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").casefold()


def normalizar(s) -> str:
    """Descrição pronta para busca de substring e tokenização.

    Ordem importa: as abreviações com barra ('p/', 'c/') precisam ser expandidas
    ANTES de a pontuação virar espaço, senão 'p/' já chegou como 'p' isolado.
    """
    t = sem_acento(s).translate(_SUPERSCRIPT)
    for k, v in _ABREV.items():
        if "/" in k:
            # fronteira de palavra obrigatória: sem ela, `t.replace("s/", ...)`
            # parte QUALQUER palavra terminada em s antes de barra —
            # "criticos/graves" virava "critico sem graves" e "MS/ANVISA" virava
            # "m sem anvisa". Media 2% das descrições do espelho.
            t = re.sub(r"(?<!\w)" + re.escape(sem_acento(k)), v, t)
    # vírgula decimal → ponto, só entre dígitos (1,5mm → 1.5mm)
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    t = re.sub(r"[^\w.]+", " ", t, flags=re.UNICODE)
    # ponto só sobrevive entre dígitos; o resto é pontuação
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    palavras = []
    for p in t.split():
        palavras.append(_ABREV.get(p, p).strip() if p in _ABREV else p)
    return re.sub(r"\s+", " ", " ".join(palavras)).strip()


def tokens(s) -> set:
    """Conjunto de tokens discriminantes de uma descrição já normalizada ou não."""
    return {p for p in normalizar(s).split()
            if p not in _STOPWORDS and (len(p) >= 3 or any(c.isdigit() for c in p))}


def jaccard(a: set, b: set) -> float:
    """Interseção sobre união; 0.0 se qualquer lado for vazio."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def contencao(a: set, b: set) -> float:
    """Interseção sobre o MENOR conjunto (coeficiente de sobreposição).

    Métrica correta para descrições de tamanhos muito diferentes, que é a regra
    no PNCP: Santos escreve 200 caracteres de especificação técnica ("atóxica,
    haste em aço inox, bisel trifacetado, siliconizado...") enquanto São Vicente
    escreve "AGULHA DESCARTAVEL 40 X 12 - CAIXA C/ 100 UNIDADES". O jaccard
    puniria o item curto por tudo que ele NÃO diz, rejeitando o mesmo produto;
    a contenção pergunta a coisa certa — "o que o item curto afirma está
    corroborado pelo outro?".

    Quem garante que é o mesmo PRODUTO são os gates de termo obrigatório e de
    exclusão, aplicados antes. Isto aqui só gradua a confiança.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def contem(texto_norm: str, termo: str) -> bool:
    """Termo (possivelmente multi-palavra) presente na descrição normalizada.

    Casa por palavra inteira: 'lona' não pode casar dentro de 'lonardo', e
    'placa' não casa em 'placas'... por isso o teste é feito sobre a forma
    normalizada com fronteira de palavra tolerante a plural simples.
    """
    t = normalizar(termo)
    if not t:
        return False
    return re.search(r"(?<!\w)" + re.escape(t) + r"s?(?!\w)", texto_norm) is not None
