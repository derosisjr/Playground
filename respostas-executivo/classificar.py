#!/usr/bin/env python3
"""Classifica os PDFs que a Prefeitura anexa como "resposta" a um requerimento.

Motivação: nem todo PDF anexado é resposta. A Prefeitura manda três coisas
diferentes pelo mesmo canal, e o painel contava as três como "respondido":

1. **Pedido de prorrogação de prazo** — ofício do Gabinete pedindo mais 15 dias
   (art. 58, XVIII da Lei Orgânica). Costuma vir em lote: um único ofício
   citando dezenas de requerimentos, arquivado dentro da pasta de cada um.
   Não é resposta; é o contrário disso.
2. **Ofício de encaminhamento** — o Gabinete diz "cumpre-nos encaminhar os
   esclarecimentos prestados pela Secretaria X". É o envelope. Quase sempre vem
   junto do PDF de mérito, mas às vezes chega sozinho.
3. **Resposta de mérito** — o documento da Secretaria que de fato responde.

Módulo puro (sem rede, sem Google) para poder ser testado direto:
    python -m unittest respostas-executivo/testes_classificar.py
"""

import re
import unicodedata

# Classes de um PDF de resposta
PRORROGACAO = "prorrogacao"
ENCAMINHAMENTO = "encaminhamento"
MERITO = "merito"
INDETERMINADO = "indeterminado"

# Situação agregada de um item (requerimento/indicação)
RESPONDIDO = "respondido"
SO_PRORROGACAO = "so_prorrogacao"
SO_ENCAMINHAMENTO = "so_encaminhamento"
PENDENTE = "pendente"

ROTULOS = {
    RESPONDIDO: "Respondido",
    SO_PRORROGACAO: "Prazo prorrogado",
    SO_ENCAMINHAMENTO: "Só encaminhamento",
    PENDENTE: "Sem resposta",
}

# Ofícios de trâmite são de 1 página. Respostas de mérito sobre aditivos de obra
# citam "prorrogação do prazo" no corpo — este teto impede o falso positivo.
LIMITE_TRAMITE = 4000

# A Prefeitura às vezes junta o ofício de encaminhamento e a resposta da
# Secretaria NO MESMO PDF (ofício na 1ª página, conteúdo na 2ª). Nesse caso o
# arquivo É resposta de mérito. Para separar os dois, cortamos o texto na fórmula
# de fecho do ofício, removemos o rodapé (assinatura, endereço, carimbo digital) e
# medimos o que sobra: ofício puro deixa algumas dezenas de caracteres, ofício com
# anexo deixa centenas. Medido em 14 amostras reais: 28–42 contra 330+.
LIMITE_CAUDA = 200

_RE_PRORROGACAO = re.compile(r"prorrogac|dilacao")
_RE_PEDE_PRAZO = re.compile(r"solicitamos|artigo 58, inciso xviii|art\.? 58, inciso xviii")
_RE_ENCAMINHA = re.compile(r"cumpre-?nos encaminhar")
_RE_FECHO = re.compile(r"distinta consideracao|elevada estima")

# Rodapé padrão dos ofícios — nada disso conta como conteúdo.
_RODAPE = [
    re.compile(r"se impresso, para conferencia acesse o site.*", re.S),
    re.compile(r"este documento foi assinado digitalmente.*", re.S),
    re.compile(r"digitally signed by.*", re.S),
    re.compile(r"palacio jose bon\w+.*?cep ?[\d.\-]+", re.S),
    re.compile(r"tel\.?:?\s*\(13\)[\d\s.\-]*"),
    re.compile(r"\batenciosamente\b"),
    re.compile(r"assinado digitalmente"),
    re.compile(r"assessoria de assuntos legislativos"),
    re.compile(r"prefeit[oa] de santos( em exercicio)?"),
    re.compile(r"presidente da camara municipal"),
]


def _norm(texto: str) -> str:
    """Minúsculas, sem acento e com espaços colapsados — o texto extraído de PDF
    vem com quebras de linha em lugares arbitrários."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto or "")
        if not unicodedata.combining(c)
    ).lower()
    return re.sub(r"\s+", " ", sem_acento).strip()


def texto_pdf(dados: bytes) -> str:
    """Extrai o texto de um PDF. Devolve '' se não houver camada de texto
    (documento escaneado) ou se o arquivo não puder ser lido."""
    import io

    try:
        from pypdf import PdfReader

        leitor = PdfReader(io.BytesIO(dados))
        return "\n".join((p.extract_text() or "") for p in leitor.pages)
    except Exception:
        return ""


def sobra_apos_fecho(texto_norm: str) -> str:
    """Texto que resta depois da fórmula de fecho do ofício, sem o rodapé.

    É o que decide se o PDF é só o envelope ou se traz a resposta anexada
    dentro do mesmo arquivo."""
    m = _RE_FECHO.search(texto_norm)
    cauda = texto_norm[m.end():] if m else texto_norm
    for padrao in _RODAPE:
        cauda = padrao.sub(" ", cauda)
    return re.sub(r"[^a-z0-9]+", " ", cauda).strip()


def classificar(texto: str) -> str:
    """Classifica um PDF de resposta pelo seu texto."""
    t = _norm(texto)
    if not t:
        return INDETERMINADO
    if len(t) <= LIMITE_TRAMITE:
        if _RE_PRORROGACAO.search(t) and _RE_PEDE_PRAZO.search(t) and "prazo" in t:
            return PRORROGACAO
        if (_RE_ENCAMINHA.search(t) and "casa legislativa" in t
                and len(sobra_apos_fecho(t)) <= LIMITE_CAUDA):
            return ENCAMINHAMENTO
    return MERITO


def situacao(classes: list[str]) -> str:
    """Agrega as classes dos PDFs de um item na situação do item.

    `indeterminado` conta como mérito: não conseguir ler o PDF nunca pode
    rebaixar um item para "não respondido".

    Quando só há trâmite, o encaminhamento tem prioridade sobre a prorrogação:
    ele indica que o anexo de mérito existe mas não foi publicado — vale
    conferir à mão, enquanto a prorrogação sozinha é apenas atraso."""
    if not classes:
        return PENDENTE
    if any(c in (MERITO, INDETERMINADO) for c in classes):
        return RESPONDIDO
    if ENCAMINHAMENTO in classes:
        return SO_ENCAMINHAMENTO
    return SO_PRORROGACAO
