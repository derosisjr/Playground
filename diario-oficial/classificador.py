#!/usr/bin/env python3
"""
Classificador determinístico de atos do Diário Oficial de Santos
================================================================

Recebe as páginas já extraídas (de `extrator.py`) e devolve a lista de **atos**
das quatro categorias-alvo, com os campos disponíveis. **Sem IA** — só regras.

Como funciona:

  1. As linhas de todas as páginas viram um fluxo único, cada linha carregando a
     `página` e a `secretaria` de onde veio (do índice).
  2. Uma linha que casa uma **âncora** (ex.: "EXTRATO DE CONTRATO", "AVISO DE
     DISPENSA", "TERMO DE FOMENTO", "DECRETO Nº") abre um **bloco** que vai até a
     próxima âncora (ou um teto de linhas). A categoria e o tipo vêm da âncora;
     a página/secretaria, da linha onde a âncora começa.
  3. Do bloco — desfeita a hifenização de fim de linha e juntando tudo numa
     string — extraem-se por rótulo os campos `número`, `objeto`, `valor`,
     `favorecido/partes`, `processo`, `modalidade`, `vigência`, `fundamentação`.
     Campos ausentes ficam vazios.

A precisão é refinável ajustando ANCORAS/ROTULOS (ver etapa de verificação).
"""

import re

# ── Âncoras: (categoria, tipo, regex). Ordem importa — a 1ª que casa vence. ────
# Regex aplicadas por linha, sem acento e em maiúsculas (ver _norm_busca).
ANCORAS: list[tuple[str, str, re.Pattern]] = [
    # contratos e aditivos
    ("Contratos e aditivos", "Extrato de contrato",   re.compile(r"\bEXTRATO DE CONTRATO\b")),
    ("Contratos e aditivos", "Termo aditivo",         re.compile(r"\b(?:EXTRATO DE )?(?:TERMO )?ADITIVO\b")),
    ("Contratos e aditivos", "Apostilamento",         re.compile(r"\bAPOSTILAMENTO\b")),
    ("Contratos e aditivos", "Ata de registro de preços", re.compile(r"\bATA DE REGISTRO DE PRECOS\b")),
    ("Contratos e aditivos", "Extrato de contrato",   re.compile(r"\bEXTRATO DE TERMO DE CONTRATO\b")),
    # licitações e dispensas
    ("Licitações e dispensas", "Dispensa",            re.compile(r"\b(?:AVISO DE )?DISPENSA(?: ELETRONICA| DE LICITACAO)?\b")),
    ("Licitações e dispensas", "Inexigibilidade",     re.compile(r"\bINEXIGIBILIDADE\b")),
    ("Licitações e dispensas", "Pregão",              re.compile(r"\b(?:AVISO DE )?PREGAO\b")),
    ("Licitações e dispensas", "Concorrência",        re.compile(r"\bCONCORRENCIA\b")),
    ("Licitações e dispensas", "Aviso de licitação",  re.compile(r"\bAVISO DE LICITACAO\b")),
    ("Licitações e dispensas", "Edital",              re.compile(r"\bEDITAL DE (?:LICITACAO|PREGAO|CONCORRENCIA|CREDENCIAMENTO)\b")),
    ("Licitações e dispensas", "Credenciamento",      re.compile(r"\bCREDENCIAMENTO\b")),
    ("Licitações e dispensas", "Homologação",         re.compile(r"\bHOMOLOGAC")),
    ("Licitações e dispensas", "Ratificação",         re.compile(r"\bRATIFICAC")),
    # convênios e fomento
    ("Convênios e fomento", "Convênio",               re.compile(r"\b(?:EXTRATO DE )?CONVENIO\b")),
    ("Convênios e fomento", "Termo de fomento",       re.compile(r"\bTERMO DE FOMENTO\b")),
    ("Convênios e fomento", "Termo de colaboração",   re.compile(r"\bTERMO DE COLABORACAO\b")),
    ("Convênios e fomento", "Termo de parceria",      re.compile(r"\bTERMO DE PARCERIA\b")),
    ("Convênios e fomento", "Acordo de cooperação",   re.compile(r"\bACORDO DE COOPERACAO\b")),
    ("Convênios e fomento", "Chamamento público",     re.compile(r"\bEDITAL DE CHAMAMENTO\b")),
    ("Convênios e fomento", "Chamamento público",     re.compile(r"\bCHAMAMENTO PUBLICO\b")),
    # leis e decretos (baixo volume, alto valor). A precisão vem do filtro de ANO
    # no cabeçalho (ver _TIPOS_NORMA): a norma publicada hoje é do ano corrente
    # ("Nº 11.242 / 2026"); "Lei Complementar nº 752, de ... 2009" citada como
    # base legal numa tabela de pessoal é descartada. (Nomeações/exonerações
    # ficaram fora desta fase.)
    ("Leis e decretos", "Lei complementar",           re.compile(r"\bLEI COMPLEMENTAR N")),
    ("Leis e decretos", "Lei",                        re.compile(r"\bLEI N[O\d]")),
    ("Leis e decretos", "Decreto",                    re.compile(r"\bDECRETO N")),
]

# Rótulos de campo (label → regex de captura no bloco normalizado, 1 grupo).
# O valor vai até o próximo RÓTULO em maiúsculas seguido de ':' (ou fim).
_ATE_PROX = r"(?=\s+[A-ZÀ-Ý][A-ZÀ-Ý /]{3,}:|$)"


def _rotulo(*nomes: str) -> re.Pattern:
    alt = "|".join(nomes)
    return re.compile(rf"(?:{alt})\s*:?\s*(.+?)" + _ATE_PROX, re.S)


ROTULOS = {
    "processo":   re.compile(r"PROCESSO\s*N?[ºO°]?\s*([\d./\-]+)", re.I),
    "objeto":     _rotulo("OBJETO"),
    "modalidade": _rotulo("MODALIDADE"),
    "vigencia":   _rotulo("VIG[ÊE]NCIA", "PRAZO"),
    "favorecido": _rotulo("PARTES", "CONTRATAD[AO]", "FORNECEDOR[A]?", "PERMISSION[ÁA]RI[AO]",
                          "CONCESSION[ÁA]RI[AO]", "PROPONENTE", "ORGANIZA[ÇC][ÃA]O",
                          "ENTIDADE", "OSC", "PARCEIR[AO]", "BENEFICI[ÁA]RI[AO]"),
}
# Valor: preferir rótulos "global/total/contrato/mensal"; senão, 1ª moeda do bloco.
_RE_VALOR_ROTULADO = re.compile(
    r"VALOR(?:\s+(?:GLOBAL|TOTAL|DO CONTRATO|MENSAL|ESTIMADO|ANUAL))?\s*:?\s*"
    r"(R\$\s?[\d.]+,\d{2})", re.I)
_RE_VALOR_QUALQUER = re.compile(r"R\$\s?[\d.]+,\d{2}")
# Número do ato — extraído SÓ da linha-gatilho (evita pegar um "Nº" solto fundo
# no bloco, que gerava números errados). Duas formas:
#   "Nº 019/2026", "N° 15023/2026", "Nº 11.242"  → _RE_NUM_ROT
#   "EDITAL 017/2026", "LICITAÇÃO 009/2026" (sem Nº) → _RE_NUM_TIPO
_RE_NUM_ROT = re.compile(r"\bN[ºO°]\s*([\d.]+/?\d{0,4})", re.I)
_RE_NUM_TIPO = re.compile(
    r"\b(?:EDITAL|LICITA[ÇC][ÃA]O|LEIL[ÃA]O|CONCORR[ÊE]NCIA|PREG[ÃA]O|DISPENSA|"
    r"CHAMAMENTO|CREDENCIAMENTO)\b[^/\d]{0,30}?(\d{1,5}/20\d\d)", re.I)
_RE_ANO_NUM = re.compile(r"/\s*(20\d\d)\b")  # ano embutido no número (".../2024")


def _numero(linha0: str, janela: str) -> str:
    """Número do ato. Prioridade:
      1. 'Nº N' na PRÓPRIA linha-gatilho — o protocolo do ato (ata/contrato/decreto),
         evitando pegar o nº do pregão citado na linha 'MODALIDADE:' logo abaixo.
      2. padrão 'TIPO NNN/AAAA' na janela — p/ avisos sem 'Nº' ('EDITAL 017/2026',
         'LICITAÇÃO 009/2026'), inclusive quando o nº está na linha seguinte.
      3. 'Nº N' em qualquer parte da janela (último recurso)."""
    m = _RE_NUM_ROT.search(linha0)
    if not m:
        m = _RE_NUM_TIPO.search(janela) or _RE_NUM_ROT.search(janela)
    return m.group(1).strip(".") if m else ""
# Objeto "inline": avisos de licitação não usam o rótulo "OBJETO:" no início, mas
# costumam dizer "...cujo objeto é...", "tem por objeto...", "Objeto: ...".
_RE_OBJETO_INLINE = re.compile(
    r"\bobjeto\b[^A-Za-zÀ-Ý0-9]{0,6}(?:é\s+|e\s+|a\s+|o\s+|de\s+|da\s+|do\s+)?"
    r"(.{18,}?)(?=\s+(?:PROCESSO|VALOR|VIG[ÊE]NCIA|MODALIDADE|ASSINATURA|DATA DA|R\$)|$)",
    re.I | re.S)
# Objeto "PARA ...": pregões/dispensas costumam dizer "PARA REGISTRO DE PREÇOS/AQUISIÇÃO DE X".
_RE_OBJETO_PARA = re.compile(
    r"\bPARA\s+(?:A\s+|O\s+|AO\s+)?(REGISTRO DE PRE[ÇC]OS|AQUISI[ÇC][ÃA]O|CONTRATA[ÇC][ÃA]O|"
    r"FORNECIMENTO|LOCA[ÇC][ÃA]O|PRESTA[ÇC][ÃA]O)\b(.{0,220}?)"
    r"(?=\s+(?:PROCESSO|A\s+SE[ÇC][ÃA]O|A\s+COMISS|O\s+MUNIC[IÍ]PIO|ABERTURA|DATA|EDITAL)|$)",
    re.I | re.S)
# Limpeza de objeto: tira prefixo de processo/código de órgão e boilerplate final.
_RE_OBJ_PREFIXO = re.compile(
    r"^(?:PROCESSO[^A-Za-zÀ-Ý]{0,4}N?[ºO°]?[\s:]*[\d./-]+\s*[-–:]?\s*|[A-ZÀ-Ý]{2,}[-/][A-ZÀ-Ý]{2,}\s+)", re.I)
_RE_OBJ_BOILER = re.compile(
    r"\s+(?:A\s+Se[çc][ãa]o\b|A\s+Comiss[ãa]o\b|comunica\s+que\b|O\s+MUNIC[IÍ]PIO DE SANTOS,\s+por\b|"
    r"Torna[\- ]se\s+p[úu]blico\b).*$", re.I | re.S)
# trecho de processo no meio/fim do objeto: "... PROCESSO N° 43557/2025-21 ..."
_RE_OBJ_PROC_TRAIL = re.compile(r"\s+PROCESSO[^A-Za-zÀ-Ý]{0,4}N?[ºO°]?[\s:]*[\d./-]+.*$", re.I | re.S)


def _limpa_objeto(obj: str) -> str:
    for _ in range(2):  # remove prefixo de processo/código (pode haver os dois)
        novo = _RE_OBJ_PREFIXO.sub("", obj).strip(" .:-")
        if novo == obj:
            break
        obj = novo
    obj = _RE_OBJ_BOILER.sub("", obj).strip(" .:-")
    obj = _RE_OBJ_PROC_TRAIL.sub("", obj).strip(" .:-")
    return obj
# Cabeçalho de norma a remover p/ sobrar a ementa: "DECRETO Nº 11.242, DE 10 DE JUNHO DE 2026."
_RE_EMENTA = re.compile(
    r"^.*?\bDE\s+\d{4}\b\s*\.?\s*", re.I | re.S)
# Fundamentação legal
_RE_FUNDAMENTO = re.compile(
    r"(art(?:igo)?\.?\s*\d+[^.;]{0,60}?Lei\s*n[ºo°]?\s*[\d./]+|Lei\s*n[ºo°]?\s*[\d./]+"
    r"|Lei\s*Federal\s*n[ºo°]?\s*[\d./]+)", re.I)

LIMITE_LINHAS_BLOCO = 45  # teto de segurança p/ um bloco de ato

# Leis/decretos: o ano no cabeçalho deve ser o da edição. Uma "Lei Complementar
# nº 752, DE ... 2009" citada como base legal numa tabela de pessoal é descartada;
# a norma realmente publicada hoje é do ano corrente.
_TIPOS_NORMA = {"Lei", "Lei complementar", "Decreto"}
# Ano do ato no cabeçalho: "Nº 11.242 / 2026" ou "..., DE 11 DE JUNHO DE 2026".
_RE_ANO_HEADING = re.compile(r"(?:/\s*|DE\s+)(20\d\d)\b", re.I)


def _ano_norma(linha0: str, prox: str) -> int | None:
    """Maior ano citado no cabeçalho da norma (linha0; cai p/ a próxima linha)."""
    anos = [int(a) for a in _RE_ANO_HEADING.findall(linha0)]
    if not anos:
        anos = [int(a) for a in _RE_ANO_HEADING.findall(prox)]
    return max(anos) if anos else None


def _norm_busca(s: str) -> str:
    """Maiúsculas sem acento — só para casar âncoras (não muda o texto extraído)."""
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.upper()


def _desfaz_hifen(linhas: list[str]) -> str:
    """Junta o bloco numa string, colando palavras quebradas por '-' no fim da linha."""
    txt = []
    for ln in linhas:
        ln = ln.rstrip()
        if txt and re.search(r"[a-zà-ÿ]-$", txt[-1]):
            txt[-1] = txt[-1][:-1] + ln.lstrip()
        else:
            txt.append(ln)
    return re.sub(r"\s+", " ", " ".join(txt)).strip()


def _campo(rx: re.Pattern, bloco: str) -> str:
    m = rx.search(bloco)
    if not m:
        return ""
    val = (m.group(1) if m.groups() else m.group(0)).strip(" .:-")
    return re.sub(r"\s+", " ", val)[:600]


# ── Enriquecimento (Fase 2): campos que alimentam os gatilhos de risco ─────────
# Ordinal do termo aditivo: "(Terceiro Termo de Aditamento)", "3º Termo Aditivo".
_ORDINAIS = {
    "PRIMEIRO": 1, "SEGUNDO": 2, "TERCEIRO": 3, "QUARTO": 4, "QUINTO": 5,
    "SEXTO": 6, "SETIMO": 7, "OITAVO": 8, "NONO": 9, "DECIMO": 10,
}


def _termo(bloco: str) -> int | None:
    """Ordinal do termo aditivo (1, 2, 3...) ou None se não for aditivo numerado."""
    b = _norm_busca(bloco)
    m = re.search(r"\b(\d{1,2})\s*[ºO°]?\s+TERMO\s+(?:DE\s+)?(?:ADITAMENTO|ADITIVO)", b)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([A-Z]+)\s+TERMO\s+(?:DE\s+)?(?:ADITAMENTO|ADITIVO)", b)
    if m and m.group(1) in _ORDINAIS:
        return _ORDINAIS[m.group(1)]
    m = re.search(r"TERMO\s+ADITIVO\s+N[ºO°]?\s*(\d{1,2})", b)
    return int(m.group(1)) if m else None


def _valor_num(valor: str) -> float | None:
    """Converte 'R$ 1.234.567,89' em float (None se não houver valor)."""
    m = re.search(r"R\$\s?([\d.]+,\d{2})", valor or "")
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


_RE_RETRO = re.compile(r"retroativ|efeitos?\s+retroativos?", re.I)

# "UNIDADE: SEDUC." — a secretaria/sigla real do ato (extratos de contrato/convênio/
# fomento/ata sempre trazem). Estrito (dois-pontos + SIGLA maiúscula) p/ não pegar a
# palavra "unidade" em prosa ("unidade de Ensino", "Unidade I, Seção de…").
_RE_UNIDADE = re.compile(r"\bUNIDADE\s*(?:GESTORA|OR[ÇC]AMENT\w+)?\s*:\s*([A-ZÀ-Ý]{2,12})\b")


def _unidade(bloco: str) -> str:
    m = _RE_UNIDADE.search(bloco)
    return m.group(1).strip() if m else ""


# Padronização da secretaria: unifica siglas (UNIDADE) e nomes do índice num único
# rótulo canônico, p/ a mesma secretaria não aparecer com 2 nomes (ex.: SMS/SAÚDE).
# Chaves NORMALIZADAS (maiúsculas, sem acento — ver _norm_busca). Fonte: "Unidades e
# Siglas da Prefeitura" (santos.sp.gov.br). Órgãos/autarquias sem secretaria ficam
# como estão (CAPEP, IPREV, COHAB, FUNDAÇÃO, CONSELHOS, PRODESAN, CET).
_CANON_SECRETARIAS = {
    "SEDUC": "Secretaria de Educação", "EDUCACAO": "Secretaria de Educação",
    "SMS": "Secretaria de Saúde", "SAUDE": "Secretaria de Saúde",
    "SECULT": "Secretaria de Cultura", "CULTURA": "Secretaria de Cultura",
    "SEMES": "Secretaria de Esportes", "ESPORTES": "Secretaria de Esportes",
    "SETUR": "Secretaria de Turismo, Comércio e Empreendedorismo",
    "SEGOV": "Secretaria de Governo",
    "SEINFRA": "Secretaria de Infraestrutura e Serviços Públicos",
    "SECOM": "Secretaria de Comunicação e Economia Criativa",
    "COMUNICACAO E ECONOMIA CRIATIVA": "Secretaria de Comunicação e Economia Criativa",
    "SEDS": "Secretaria de Desenvolvimento Social",
    "DESENVOLVIMENTO SOCIAL": "Secretaria de Desenvolvimento Social",
    "SEPREF": "Secretaria das Prefeituras Regionais",
    "PREFEITURAS REGIONAIS": "Secretaria das Prefeituras Regionais",
    "SEOBE": "Secretaria de Obras e Edificações",
    "OBRAS E EDIFICACOES": "Secretaria de Obras e Edificações",
    "SEFIN": "Secretaria de Finanças e Gestão", "SEGES": "Secretaria de Finanças e Gestão",
    "FINANCAS E GESTAO": "Secretaria de Finanças e Gestão",
    "SESEG": "Secretaria de Segurança", "SEGURANCA": "Secretaria de Segurança",
    "SEMAM": "Secretaria de Meio Ambiente, Desenvolvimento Urbano e Sustentabilidade",
    "MEIO AMBIENTE, DESENVOLVIMENTO URBANO E SUSTENTABILIDADE":
        "Secretaria de Meio Ambiente, Desenvolvimento Urbano e Sustentabilidade",
    "SECC": "Secretaria da Casa Civil",
    "SEPORTE": "Secretaria de Assuntos Portuários e Emprego",
    "SEMULHER": "Secretaria da Mulher, Cidadania, Diversidade e Direitos Humanos",
    "PGM": "Procuradoria Geral do Município",
    "PROCURADORIA GERAL": "Procuradoria Geral do Município",
    "GPM": "Gabinete do Prefeito Municipal",
    "PODER EXECUTIVO": "Poder Executivo",
    "CAMARA": "Câmara Municipal",
}


def _padroniza_secretaria(sec: str) -> str:
    if not sec:
        return sec
    return _CANON_SECRETARIAS.get(_norm_busca(sec).strip(), sec)


def _limpa_favorecido(fav: str) -> str:
    """Remove o prefixo 'Município de Santos e [a/o]' para sobrar a contraparte.
    Se a contraparte não foi capturada (sobra só 'Município de Santos [e]'), devolve ''."""
    out = re.sub(r"^MUN[IÍ]C[IÍ]PIO DE SANTOS\s+e\s+(?:a\s+|o\s+)?", "", fav, flags=re.I).strip(" .:-")
    if re.match(r"(?i)^MUN[IÍ]C[IÍ]PIO DE SANTOS\b", out) or out.lower() in ("", "e"):
        return ""
    return out


# Marcadores de lista/pontuação que podem preceder o cabeçalho de um ato.
_LIXO_INICIO = " .\t0123456789)-–—•º°ºª:"


def _achar_ancora(linha_norm: str) -> tuple[str, str] | None:
    """Casa âncora SÓ no início da linha (cabeçalho de ato) — assim 'LEI Nº' como
    cabeçalho conta, mas 'nos termos da Lei nº 14.133' (citação) é ignorada."""
    inicio = linha_norm.lstrip(_LIXO_INICIO)
    for categoria, tipo, rx in ANCORAS:
        if rx.match(inicio):
            return categoria, tipo
    return None


def classificar(paginas: list[dict], ano_edicao: int | None = None) -> list[dict]:
    """Recebe páginas {pagina, secretaria, texto} e devolve a lista de atos.
    `ano_edicao` (opcional) filtra normas citadas de anos anteriores."""
    # fluxo plano de linhas com proveniência
    fluxo: list[tuple[int, str, str]] = []
    for pg in paginas:
        for ln in pg["texto"].splitlines():
            if ln.strip():
                fluxo.append((pg["pagina"], pg["secretaria"], ln))

    # posições das âncoras
    marcos: list[tuple[int, str, str]] = []  # (idx, categoria, tipo)
    for i, (_, _, ln) in enumerate(fluxo):
        achou = _achar_ancora(_norm_busca(ln))
        if achou:
            marcos.append((i, achou[0], achou[1]))

    atos: list[dict] = []
    vistos: set[tuple] = set()  # dedup intra-edição por (categoria, número, secretaria)
    for k, (i, categoria, tipo) in enumerate(marcos):
        fim = marcos[k + 1][0] if k + 1 < len(marcos) else len(fluxo)
        fim = min(fim, i + LIMITE_LINHAS_BLOCO)
        pagina, secretaria, linha0 = fluxo[i]
        linhas_bloco = [fluxo[j][2] for j in range(i, fim)]
        bloco = _desfaz_hifen(linhas_bloco)

        # número a partir do cabeçalho (linha-gatilho + até 2 linhas seguintes —
        # alguns avisos põem o "Processo nº ..." na linha de baixo).
        numero = _numero(linha0, " ".join(linhas_bloco[:3]))
        # Todo ato real tem número no cabeçalho. Sem número = fragmento de cláusula
        # (ex.: "homologação do certame. 8.13. ...") → descarta.
        if not numero:
            continue

        # Lei/decreto: manter só a norma do ano corrente (descarta citação de lei antiga).
        if tipo in _TIPOS_NORMA:
            prox = fluxo[i + 1][2] if i + 1 < len(fluxo) else ""
            ano_ato = _ano_norma(linha0, prox)
            if ano_ato is None or (ano_edicao and ano_ato < ano_edicao):
                continue
        # Licitações/convênios: número de ano anterior é republicação/citação → descarta.
        if categoria in ("Licitações e dispensas", "Convênios e fomento") and ano_edicao:
            man = _RE_ANO_NUM.search(numero)
            if man and int(man.group(1)) < ano_edicao:
                continue

        # Secretaria: preferir a "UNIDADE: XXX" do próprio ato (precisa) ao índice
        # (que às vezes só dá "PODER EXECUTIVO"); padronizar sigla/nome num rótulo único.
        secretaria = _padroniza_secretaria(_unidade(bloco) or secretaria)

        # dedup intra-edição (mesmo ato citado em 2 páginas/seções)
        chave = (categoria, numero, secretaria)
        if chave in vistos:
            continue
        vistos.add(chave)

        # valor: rótulo sempre; "qualquer moeda" só p/ contratos/convênios (onde um
        # único valor é significativo) — evita pegar item solto de um edital.
        mval = _RE_VALOR_ROTULADO.search(bloco)
        if not mval and categoria in ("Contratos e aditivos", "Convênios e fomento"):
            mval = _RE_VALOR_QUALQUER.search(bloco)
        mfun = _RE_FUNDAMENTO.search(bloco)

        objeto = _campo(ROTULOS["objeto"], bloco)
        # Leis/decretos não têm rótulo "OBJETO:" — a ementa vem logo após o
        # cabeçalho "TIPO Nº X, DE DD DE MÊS DE AAAA.". Usa-a como objeto.
        if not objeto and categoria == "Leis e decretos":
            ementa = _RE_EMENTA.sub("", bloco, count=1).strip(" .")
            objeto = re.sub(r"\s+", " ", ementa)[:300]
        # Avisos de licitação: tenta "...cujo objeto é...", "tem por objeto...".
        if not objeto:
            mo = _RE_OBJETO_INLINE.search(bloco)
            if mo:
                objeto = re.sub(r"\s+", " ", mo.group(1)).strip(" .:-")[:300]
        # Pregões/dispensas: "PARA REGISTRO DE PREÇOS/AQUISIÇÃO DE X".
        if not objeto:
            mp = _RE_OBJETO_PARA.search(bloco)
            if mp:
                objeto = re.sub(r"\s+", " ", mp.group(1) + mp.group(2)).strip(" .:-")[:300]
        # Fallback genérico: usa o texto do ato (sem o cabeçalho) para a linha
        # trazer ao menos o contexto.
        if not objeto:
            corpo = " ".join(linhas_bloco[1:]) if len(linhas_bloco) > 1 else bloco
            objeto = re.sub(r"\s+", " ", _desfaz_hifen([corpo])).strip(" .:-")[:300]
        # remove prefixo de cláusula ("1.1.", "3)", "Item 2.") no início do objeto
        objeto = re.sub(r"^(?:\d+(?:\.\d+)*\.?|\d+\)|Item\s+\d+\.?)\s*", "", objeto).strip(" .:-")
        # remove prefixo de processo/código de órgão e boilerplate final
        objeto = _limpa_objeto(objeto)

        valor = (mval.group(0) if mval else "").replace(" ", " ")
        atos.append({
            "categoria": categoria,
            "tipo": tipo,
            "numero": numero,
            "secretaria": secretaria,
            "pagina": pagina,
            "objeto": objeto,
            "valor": valor,
            "valor_num": _valor_num(valor),
            "favorecido": _limpa_favorecido(_campo(ROTULOS["favorecido"], bloco)),
            "processo": _campo(ROTULOS["processo"], bloco),
            "modalidade": _campo(ROTULOS["modalidade"], bloco),
            "vigencia": _campo(ROTULOS["vigencia"], bloco),
            "fundamentacao": (mfun.group(1).strip() if mfun else ""),
            "termo": _termo(bloco),
            "retroativo": bool(_RE_RETRO.search(bloco)),
            "trecho": bloco[:300],
        })
    return atos
