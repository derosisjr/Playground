#!/usr/bin/env python3
"""Exporta a aba `requerimentos` da planilha de controle para um JSON enxuto
(`requerimentos-index.json` na raiz do repo), consumido pelo painel estático
do hub (requerimentos.html). Com `--indicacoes`, exporta a aba `indicações` para
`indicacoes-index.json` (painel indicacoes.html) — ver a seção "Indicações" abaixo.

Fonte de verdade é o Google Sheets (não há SQLite aqui). Reutiliza a
autenticação e os helpers de cabeçalho de `index.py`. Só LÊ a planilha.

ATENÇÃO: a coluna `Resposta` guarda uma fórmula `=HYPERLINK("<url>";"Resposta")`.
Uma leitura comum devolveria só o texto "Resposta"; por isso lemos com
`valueRenderOption=FORMULA` e extraímos a URL do Drive por regex.

Uso:
    python respostas-executivo/export.py            # grava requerimentos-index.json
    python respostas-executivo/export.py --dry-run  # só imprime contagens
    python respostas-executivo/export.py --salvar caminho.json
    python respostas-executivo/export.py --indicacoes [--dry-run]  # indicacoes-index.json
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

# Permite `import index` quando rodado como `python respostas-executivo/export.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classificar as cls  # noqa: E402
import prazos  # noqa: E402
from index import (  # noqa: E402
    ABA_INDICACOES, COL_DATA_MERITO, COL_SITUACAO, _google_services, _idx_header, _sem_acento,
)

ABA = "requerimentos"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.append(RAIZ)  # camada comum do repo (comum/)
from comum.escrita import gravar_json  # noqa: E402
from secretarias import canonica as secretaria_canonica  # noqa: E402  (usa comum/)
from bairros import canonico as bairro_canonico  # noqa: E402  (usa comum/ e geo/)
JSON_PADRAO = os.path.join(RAIZ, "requerimentos-index.json")
JSON_INDICACOES = os.path.join(RAIZ, "indicacoes-index.json")

# Captura a 1ª string entre aspas de =HYPERLINK("url"; "texto") (separador , ou ;)
RE_HYPERLINK = re.compile(r'HYPERLINK\(\s*"([^"]+)"', re.IGNORECASE)

# O índice é PÚBLICO (GitHub Pages). Só sai o que está nesta lista: a planilha é de
# trabalho do gabinete e tem colunas internas — a "Status atual" chegou a publicar
# anotações como "ok (Falar com o Rui)" e links de entrega de documentos (out/2026).
# Coluna nova só entra no site se for acrescentada aqui de propósito.
CAMPOS_PUBLICOS = (
    "numero", "ano", "assunto", "data_sessao", "data_resposta",
    "data_resposta_merito", "situacao", "respondido", "url_resposta",
    # cobrança do Executivo (out/2026): sigla da secretaria indicada pelo gabinete
    # (secretarias.py), prazo da LOM (prazos.py) e pedidos anteriores citados no assunto
    "secretaria", "vence_em", "cita",
)

# Número de requerimento válido ("1729/2026"). Linha com outra coisa na coluna
# (ex.: uma data, como as linhas-fantasma de set/2026) não é requerimento.
RE_NUMERO = re.compile(r"^\d{1,5}/\d{4}$")


def _ano_do_numero(numero: str) -> int | str:
    """Extrai o ano de um número tipo '1729/2026'. Devolve int ou '' se não achar."""
    m = re.search(r"/\s*(\d{4})", numero or "")
    if m:
        return int(m.group(1))
    m = re.search(r"\b(20\d{2})\b", numero or "")
    return int(m.group(1)) if m else ""


_EPOCH_SHEETS = datetime(1899, 12, 30)  # serial 0 do Sheets/Excel
_SERIAL_MAX = 73051  # 01/01/2100: acima disso não é data real da planilha


def _data(valor) -> str:
    """Datas do Sheets vêm em formatos mistos por coluna (M/D/Y vs D/M/Y). Lendo o
    valor bruto (UNFORMATTED_VALUE), datas reais vêm como nº de série — inequívoco.
    Converte para 'dd/mm/aaaa'; se vier texto, devolve como está."""
    if isinstance(valor, bool):
        return ""
    if isinstance(valor, (int, float)):
        if 0 < valor < _SERIAL_MAX:
            return (_EPOCH_SHEETS + timedelta(days=int(valor))).strftime("%d/%m/%Y")
        # Data digitada sem barras (ex.: 13082026) vira número gigante na planilha;
        # recupera ddmmaaaa se for válida, senão avisa e segue sem a data.
        txt = str(int(valor)) if valor == int(valor) else ""
        if len(txt) in (7, 8):
            try:
                return datetime.strptime(txt.zfill(8), "%d%m%Y").strftime("%d/%m/%Y")
            except ValueError:
                pass
        print(f"Aviso: data inválida na planilha: {valor!r}", file=sys.stderr)
        return ""
    return str(valor).strip()


def _url_resposta(celula: str) -> str:
    """Extrai a URL do Drive de uma célula `Resposta` (fórmula HYPERLINK)."""
    if not celula:
        return ""
    m = RE_HYPERLINK.search(celula)
    if m:
        return m.group(1)
    # Caso a célula já seja uma URL nua (sem fórmula).
    if str(celula).startswith("http"):
        return str(celula).strip()
    return ""


def ler_aba(aba: str) -> tuple[list, list, list]:
    """As três leituras da aba (só leitura), alinhadas por linha."""
    _, sheets = _google_services()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise EnvironmentError("Defina SHEET_ID (env) ou o secret correspondente.")

    # Três leituras alinhadas por linha:
    #  - FORMATTED_VALUE: textos e datas como exibidos (datas viriam como nº de série
    #    se lidas como FORMULA);
    #  - FORMULA: preserva a fórmula =HYPERLINK(...) da coluna Resposta p/ extrair a URL;
    #  - UNFORMATTED_VALUE: datas como nº de série (formato inequívoco).
    def ler(render: str) -> list:
        return (
            sheets.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"'{aba}'", valueRenderOption=render)
            .execute()
            .get("values", [])
        )

    return ler("FORMATTED_VALUE"), ler("FORMULA"), ler("UNFORMATTED_VALUE")


def coletar() -> list[dict]:
    return montar_itens(*ler_aba(ABA))


def montar_itens(valores: list, formulas: list, brutos: list) -> list[dict]:
    """Monta os itens públicos a partir das três leituras da aba (alinhadas por
    linha). Separado de `coletar()` para ser testável sem o Google."""
    if not valores:
        return []

    cab = valores[0]
    c_num = _idx_header(cab, "Número")
    c_assunto = _idx_header(cab, "Assunto")
    c_sessao = _idx_header(cab, "Data da Sessão")
    c_resp = _idx_header(cab, "Resposta")
    c_dataresp = _idx_header(cab, "Data da resposta")
    c_situacao = _idx_header(cab, COL_SITUACAO)
    c_merito = _idx_header(cab, COL_DATA_MERITO)
    c_secretaria = _idx_header(cab, "Secretaria")

    def campo(linha: list, idx: int) -> str:
        if idx < 0 or idx >= len(linha):
            return ""
        return str(linha[idx]).strip()

    def bruto(linha: list, idx: int):
        if idx < 0 or idx >= len(linha):
            return ""
        return linha[idx]

    itens: list[dict] = []
    for n, linha in enumerate(valores[1:], start=1):
        numero = campo(linha, c_num)
        assunto = campo(linha, c_assunto)
        if not numero and not assunto:
            continue  # linha vazia
        if not RE_NUMERO.match(numero):
            print(f"Aviso: linha {n + 1} ignorada — número inválido {numero!r}",
                  file=sys.stderr)
            continue
        # A URL sai da fórmula HYPERLINK (leitura FORMULA), mesma posição de linha;
        # as datas saem do valor bruto (UNFORMATTED), também alinhado por linha.
        linha_formula = formulas[n] if n < len(formulas) else []
        linha_bruta = brutos[n] if n < len(brutos) else []
        url = _url_resposta(campo(linha_formula, c_resp))
        # `situacao` distingue resposta de mérito de mero trâmite (pedido de prazo,
        # ofício de encaminhamento). Pasta no Drive sem veredito é "a classificar", não
        # "respondido": pasta criada sem PDF de resposta (ou com PDF que ainda não deu
        # para ler) não prova resposta de mérito — como nas indicações.
        situacao = campo(linha, c_situacao) or (
            A_CLASSIFICAR if url else cls.PENDENTE
        )
        data_sessao = _data(bruto(linha_bruta, c_sessao))
        itens.append(
            {
                "numero": numero,
                "ano": _ano_do_numero(numero),
                "assunto": assunto,
                "data_sessao": data_sessao,
                "data_resposta": _data(bruto(linha_bruta, c_dataresp)),
                "data_resposta_merito": _data(bruto(linha_bruta, c_merito)),
                "situacao": situacao,
                "respondido": situacao == cls.RESPONDIDO,
                "url_resposta": url,
                "secretaria": secretaria_canonica(campo(linha, c_secretaria)),
                "vence_em": prazos.vence_em(data_sessao, situacao),
            }
        )
    # Desdobramentos: "Resposta ao requerimento 210/2025 - …" cita um pedido anterior.
    # Só vale número que está na base (e não o próprio); a volta ("citado por") o
    # painel monta sozinho.
    existentes = {i["numero"] for i in itens}
    for i in itens:
        cita = [n for n in prazos.citados(i["assunto"]) if n in existentes and n != i["numero"]]
        if cita:
            i["cita"] = cita
    return itens


def resumo_prazos(itens: list[dict], hoje=None) -> dict:
    """Números da cobrança (dry-run e conferência): mediana até o mérito, quantos
    chegaram em até 15 e 30 dias, quantos estão sem mérito e fora do prazo."""
    from datetime import date
    from statistics import median
    hoje = hoje or date.today()
    dias = []
    for i in itens:
        a, b = prazos.data_br(i["data_sessao"]), prazos.data_br(i["data_resposta_merito"])
        if i["respondido"] and a and b and b >= a:
            dias.append((b - a).days)
    return {
        "com_merito": len(dias),
        "mediana": median(dias) if dias else None,
        "ate_15": sum(d <= prazos.PRAZO_DIAS for d in dias),
        "ate_30": sum(d <= prazos.PRAZO_DIAS + prazos.PRORROGACAO_DIAS for d in dias),
        "sem_merito": sum(1 for i in itens if not i["respondido"]),
        "fora_do_prazo": sum(1 for i in itens if prazos.fora_do_prazo(i, hoje)),
    }


def campos_fora_da_lista(itens: list[dict]) -> set[str]:
    """Chaves que não estão em CAMPOS_PUBLICOS (deve ser vazio)."""
    return {k for i in itens for k in i} - set(CAMPOS_PUBLICOS)


# ── Indicações (aba "indicações") ─────────────────────────────────────────────
# Mesma planilha, outra aba, outras armadilhas (out/2026):
#  1. LINHAS REPETIDAS: 887 linhas para 562 indicações. A linha que a assessoria
#     digitou (resumo curto + bairro) e a que o robô das Respostas do Executivo anexou
#     depois (ementa da Câmara, data de mérito) são a MESMA indicação — juntadas pelo
#     número (`juntar_indicacao`): texto e datas da linha do robô, bairro da linha da
#     assessoria (só ela tem bairro).
#  2. COLUNAS INTERNAS: "sta", "A contento" (anotações como "pediu número"), "Prazo" e
#     "Data do Protocolo na PMS" nunca são lidas (só as de COLUNAS_INDICACOES); a
#     "Bairro" é texto livre — às vezes anotação interna ("RESPOSTA EM 07 MESES") — e
#     só sai normalizada para o nome oficial ou a região (bairros.py).
#  3. DATAS: a assessoria exibe M/D e o robô dd/mm, mas o valor bruto (nº de série) é o
#     mesmo — vale o bruto; texto só se for dd/mm/aaaa válido (ano com um dígito a mais,
#     "18/03/82025", é consertado quando bate com o ano do número).
# Indicação NÃO tem prazo legal (o do requerimento é da LOM, art. 58, XVIII): nada de
# vencimento aqui.
CAMPOS_PUBLICOS_INDICACOES = (
    "numero", "ano", "assunto", "data_sessao", "data_resposta",
    "data_resposta_merito", "situacao", "respondido", "url_resposta",
    # só o nome OFICIAL do bairro (geo/santos-bairros.geojson) ou a região maior que
    # um bairro — nunca o texto da coluna "Bairro" da planilha (bairros.py)
    "bairro", "regiao",
)
# as únicas colunas da aba que o export lê
COLUNAS_INDICACOES = ("Número", "Assunto", "Data da Sessão", "Resposta", "Data da resposta",
                      "Bairro", COL_SITUACAO, COL_DATA_MERITO)
# documento da Prefeitura registrado (pasta no Drive, "SIM" na coluna Resposta ou data
# de resposta), mas sem a classificação de mérito × trâmite: não é "respondido" nem
# "pendente" — o painel mostra "Resposta a classificar"
A_CLASSIFICAR = "a_classificar"
# situações da planilha (classificar.py), da mais forte para a mais fraca; outro texto
# na coluna é ignorado — a situação publicada sai sempre deste vocabulário
PRIORIDADE_SITUACAO = {cls.RESPONDIDO: 4, cls.SO_ENCAMINHAMENTO: 3, cls.SO_PRORROGACAO: 2,
                       cls.PENDENTE: 1}
RE_DATA_BR = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
RE_ANO_A_MAIS = re.compile(r"^(\d{2})/(\d{2})/\d(\d{4})$")  # "18/03/82025"
# dado pessoal no assunto: CPF ou e-mail abortam a publicação; telefone só avisa
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RE_CPF = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)|\bCPF\b\W{0,3}(?:n[º°o]?\.?\s*)?\d",
                    re.IGNORECASE)
RE_ONZE_DIGITOS = re.compile(r"(?<![\d.,/-])\d{11}(?![\d.,/-])")
RE_TELEFONE = re.compile(r"(?<![\d/])(?:\(?\d{2}\)?[\s.]?)?9?\d{4}[-.\s]\d{4}(?![\d/])")


def _cpf_valido(d: str) -> bool:
    """11 dígitos com os dígitos verificadores do CPF (sequência repetida não vale)."""
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def dados_pessoais(texto: str) -> tuple[list[str], bool]:
    """(motivos que BLOQUEIAM a publicação — CPF, e-mail —, tem cara de telefone)."""
    texto = texto or ""
    motivos = []
    if RE_EMAIL.search(texto):
        motivos.append("e-mail")
    if RE_CPF.search(texto) or any(_cpf_valido(m) for m in RE_ONZE_DIGITOS.findall(texto)):
        motivos.append("CPF")
    return motivos, bool(RE_TELEFONE.search(texto))


def _vazio(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _data_indicacao(valor, ano) -> tuple[str, str]:
    """(dd/mm/aaaa ou '', ocorrência): '' = ok, 'consertada', 'invalida'."""
    if _vazio(valor):
        return "", ""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        d = _data(valor)  # nº de série do Sheets (ou ddmmaaaa digitado sem barras)
        return d, "" if d else "invalida"
    s = str(valor).strip()

    def valida(txt):
        try:
            datetime.strptime(txt, "%d/%m/%Y")
            return True
        except ValueError:
            return False
    if RE_DATA_BR.match(s) and valida(s):
        return s, ""
    m = RE_ANO_A_MAIS.match(s)
    if m and ano and int(m[3]) == ano and valida(f"{m[1]}/{m[2]}/{m[3]}"):
        return f"{m[1]}/{m[2]}/{m[3]}", "consertada"
    return "", "invalida"


def _formato_robo(bruto, exibido: str) -> bool:
    """A data da sessão está no formato que o robô grava? Ele escreve "dd/mm/aaaa" e a
    planilha (pt_BR) a exibe assim; a assessoria usa um formato M/D ("2/4/2025")."""
    if not isinstance(bruto, (int, float)) or isinstance(bruto, bool) or not 0 < bruto < _SERIAL_MAX:
        return False
    d = _EPOCH_SHEETS + timedelta(days=int(bruto))
    return exibido == d.strftime("%d/%m/%Y") and exibido != f"{d.month}/{d.day}/{d.year}"


def _numero_canonico(numero: str) -> str:
    n, ano = numero.split("/")
    return f"{int(n)}/{ano}"


def linhas_indicacoes(valores: list, formulas: list, brutos: list) -> tuple[list[dict], list[int]]:
    """Cada linha da aba reduzida às colunas de COLUNAS_INDICACOES (o resto da linha
    nunca sai daqui) + os nºs das linhas descartadas por número inválido."""
    if not valores:
        return [], []
    cab = valores[0]
    col = {c: _idx_header(cab, c) for c in COLUNAS_INDICACOES}

    def pega(linha: list, c: str):
        i = col[c]
        return linha[i] if 0 <= i < len(linha) else ""

    linhas, descartadas = [], []
    for n, linha in enumerate(valores[1:], start=1):
        f = formulas[n] if n < len(formulas) else []
        b = brutos[n] if n < len(brutos) else []
        numero = str(pega(linha, "Número")).strip()
        assunto = str(pega(linha, "Assunto")).strip()
        if not numero and not assunto:
            continue  # linha vazia
        if not RE_NUMERO.match(numero):
            descartadas.append(n + 1)
            continue
        linhas.append({
            "linha": n + 1,
            "numero": _numero_canonico(numero),
            "assunto": assunto,
            "sessao": pega(b, "Data da Sessão"),
            "sessao_exibida": str(pega(linha, "Data da Sessão")).strip(),
            "url": _url_resposta(str(pega(f, "Resposta")).strip()),
            "tem_resposta": not _vazio(pega(linha, "Resposta")),
            "data_resposta": pega(b, "Data da resposta"),
            "merito": pega(b, COL_DATA_MERITO),
            "situacao": str(pega(linha, COL_SITUACAO)).strip(),
            "bairro": str(pega(linha, "Bairro")).strip(),
        })
    return linhas, descartadas


def linha_oficial(linhas: list[dict]) -> dict:
    """A linha que o robô anexou (ementa e datas da Câmara): a última com data de
    mérito (só o robô grava essa coluna); senão a última com a data da sessão no
    formato do robô; senão a última da planilha (o robô anexa no fim)."""
    for x in reversed(linhas):
        if not _vazio(x["merito"]):
            return x
    for x in reversed(linhas):
        if _formato_robo(x["sessao"], x["sessao_exibida"]):
            return x
    return linhas[-1]


def juntar_indicacao(linhas: list[dict], rel: dict) -> dict:
    """Um item público a partir das linhas (na ordem da planilha) do mesmo número."""
    of = linha_oficial(linhas)
    ordem = [of] + [x for x in linhas if x is not of]
    numero = of["numero"]
    ano = _ano_do_numero(numero)

    def data(campo: str) -> str:
        achadas = []
        for x in ordem:
            d, ocorrencia = _data_indicacao(x[campo], ano)
            if ocorrencia:
                rel["datas"][f"{campo}:{ocorrencia}"] += 1
            if d:
                achadas.append(d)
        if len(set(achadas)) > 1:
            rel["datas"][f"{campo}:divergente"] += 1
            rel["divergencias"].append(f"{numero} {campo}: {achadas} — vale {achadas[0]}")
        return achadas[0] if achadas else ""

    assunto = next((x["assunto"] for x in ordem if x["assunto"]), "")
    for x in ordem[1:]:
        if x["assunto"] and _sem_acento(x["assunto"]) != _sem_acento(assunto) and not (
                _parecidos(x["assunto"], assunto)):
            rel["assuntos_diferentes"].append(f"{numero}: vale «{assunto[:70]}»; "
                                              f"descartado «{x['assunto'][:70]}»")
    url = next((x["url"] for x in ordem if x["url"]), "")
    situacoes = [x["situacao"] for x in linhas if x["situacao"] in PRIORIDADE_SITUACAO]
    situacao = max(situacoes, key=PRIORIDADE_SITUACAO.get) if situacoes else ""
    if not situacao:
        documento = url or any(x["tem_resposta"] or not _vazio(x["data_resposta"])
                               or not _vazio(x["merito"]) for x in linhas)
        situacao = A_CLASSIFICAR if documento else cls.PENDENTE
    # bairro: o 1º texto (na ordem da planilha) que vira bairro oficial ou região
    bairro = regiao = None
    textos = [x["bairro"] for x in linhas if x["bairro"]]
    for t in textos:
        bairro, regiao = bairro_canonico(t)
        if bairro or regiao:
            break
        rel["nao_reconhecidos"][t] += 1
    if len(set(textos)) > 1:
        rel["bairros_diferentes"].append(numero)
    return {
        "numero": numero,
        "ano": ano,
        "assunto": assunto,
        "data_sessao": data("sessao"),
        "data_resposta": data("data_resposta"),
        "data_resposta_merito": data("merito"),
        "situacao": situacao,
        "respondido": situacao == cls.RESPONDIDO,
        "url_resposta": url,
        "bairro": bairro or "",
        "regiao": regiao or "",
    }


def _parecidos(a: str, b: str) -> bool:
    """Assuntos que falam da mesma coisa (palavras em comum, sem as de ligação)."""
    vazias = {"INDICA", "AO", "EXECUTIVO", "A", "O", "DE", "DA", "DO", "NA", "NO", "E", "EM"}
    ta = set(re.sub(r"[^A-Z0-9]+", " ", _sem_acento(a).upper()).split()) - vazias
    tb = set(re.sub(r"[^A-Z0-9]+", " ", _sem_acento(b).upper()).split()) - vazias
    return len(ta & tb) / max(1, min(len(ta), len(tb))) >= 0.2


def montar_indicacoes(valores: list, formulas: list, brutos: list) -> tuple[list[dict], dict]:
    """(itens públicos, relatório) a partir das três leituras da aba de indicações.
    Separado de `coletar_indicacoes()` para ser testável sem o Google."""
    linhas, descartadas = linhas_indicacoes(valores, formulas, brutos)
    grupos: dict[str, list[dict]] = {}
    for x in linhas:
        grupos.setdefault(x["numero"], []).append(x)
    rel = {"linhas": len(linhas), "descartadas": descartadas, "datas": Counter(),
           "divergencias": [], "assuntos_diferentes": [], "nao_reconhecidos": Counter(),
           "bairros_diferentes": [],
           "grupos": Counter(len(g) for g in grupos.values())}
    itens = [juntar_indicacao(g, rel) for g in grupos.values()]
    itens.sort(key=lambda i: (i["ano"], int(i["numero"].split("/")[0])), reverse=True)
    return itens, rel


def coletar_indicacoes() -> tuple[list[dict], dict]:
    return montar_indicacoes(*ler_aba(ABA_INDICACOES))


def campos_fora_da_lista_indicacoes(itens: list[dict]) -> set[str]:
    """Chaves que não estão em CAMPOS_PUBLICOS_INDICACOES (deve ser vazio)."""
    return {k for i in itens for k in i} - set(CAMPOS_PUBLICOS_INDICACOES)


def main_indicacoes(args) -> int:
    itens, rel = coletar_indicacoes()
    extras = campos_fora_da_lista_indicacoes(itens)
    if extras:
        print(f"ABORTANDO: campos fora de CAMPOS_PUBLICOS_INDICACOES: {sorted(extras)}",
              file=sys.stderr)
        return 1
    bloqueios, telefones = [], []
    for i in itens:
        motivos, telefone = dados_pessoais(i["assunto"])
        if motivos:
            bloqueios.append(f"{i['numero']} ({', '.join(motivos)})")
        if telefone:
            telefones.append(i["numero"])
    if bloqueios:
        # só o número: o log do Actions é público, o texto suspeito não pode ir para ele
        print("ABORTANDO: possível dado pessoal no assunto de indicação(ões): "
              + "; ".join(bloqueios), file=sys.stderr)
        return 1
    if telefones:
        print(f"Aviso: possível telefone no assunto de {len(telefones)} indicação(ões): "
              + ", ".join(telefones), file=sys.stderr)

    grupos = rel["grupos"]
    juntadas = sum(n for tam, n in grupos.items() if tam > 1)
    com_bairro = sum(1 for i in itens if i["bairro"])
    regioes = Counter(i["regiao"] for i in itens if i["regiao"])
    nao_rec = sum(rel["nao_reconhecidos"].values())
    print(f"{rel['linhas']} linha(s) com número válido → {len(itens)} indicação(ões) "
          f"({juntadas} juntadas de linhas repetidas; grupos por tamanho "
          f"{dict(sorted(grupos.items()))}); {len(rel['descartadas'])} linha(s) descartada(s) "
          f"por número inválido {rel['descartadas']}.")
    print(f"  Bairro oficial em {com_bairro} ({com_bairro / max(1, len(itens)):.0%}); região em "
          f"{sum(regioes.values())} {dict(regioes)}; {nao_rec} com texto de bairro não reconhecido "
          f"({len(rel['nao_reconhecidos'])} grafia(s)).")
    print(f"  Situação: {dict(Counter(i['situacao'] for i in itens))}.")
    if rel["datas"]:
        print(f"  Datas: {dict(rel['datas'])}.")

    if args.dry_run:
        # o detalhe traz texto da planilha (grafias, resumos da assessoria): só no
        # --dry-run local — o log do workflow é público
        for t, n in rel["nao_reconhecidos"].most_common():
            print(f"    não reconhecido: {t!r} × {n}")
        for linha in rel["divergencias"] + rel["assuntos_diferentes"]:
            print(f"    {linha}")
        if rel["bairros_diferentes"]:
            print(f"    bairros diferentes entre linhas: {rel['bairros_diferentes']}")
        for i in itens[:5]:
            print(f"  {i['numero']:>10}  {i['situacao']:<16}  {i['bairro'] or i['regiao']:<16}  "
                  f"{i['assunto'][:50]}")
        return 0

    destino = args.salvar or JSON_INDICACOES
    gravar_json(destino, itens, separators=(",", ":"))
    print(f"Gravado: {destino}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exporta requerimentos (ou, com --indicacoes, as indicações) da planilha "
                    "para o JSON do painel"
    )
    parser.add_argument("--dry-run", action="store_true", help="Só imprime contagens")
    parser.add_argument("--salvar", default=None,
                        help="Caminho do JSON de saída (padrão: requerimentos-index.json ou "
                             "indicacoes-index.json na raiz)")
    parser.add_argument("--indicacoes", action="store_true",
                        help="Exporta a aba de indicações (indicacoes-index.json)")
    args = parser.parse_args()
    if args.indicacoes:
        return main_indicacoes(args)
    args.salvar = args.salvar or JSON_PADRAO

    itens = coletar()
    extras = campos_fora_da_lista(itens)
    if extras:
        # nunca publicar coluna que ninguém decidiu tornar pública
        print(f"ABORTANDO: campos fora de CAMPOS_PUBLICOS: {sorted(extras)}", file=sys.stderr)
        return 1
    respondidos = sum(1 for i in itens if i["respondido"])
    print(f"{len(itens)} requerimento(s) — {respondidos} com resposta de mérito.")
    for chave in (cls.RESPONDIDO, cls.SO_ENCAMINHAMENTO, cls.SO_PRORROGACAO,
                  cls.PENDENTE):
        n = sum(1 for i in itens if i["situacao"] == chave)
        if n:
            print(f"  {cls.ROTULOS[chave]:<18} {n:>4}  ({n / len(itens):.1%})")

    r = resumo_prazos(itens)
    print(f"  Prazo da LOM (15 dias, +15 se prorrogado): {r['ate_15']} de {r['com_merito']} "
          f"respondidos em até 15 dias, {r['ate_30']} em até 30; mediana {r['mediana']} dias; "
          f"{r['fora_do_prazo']} de {r['sem_merito']} sem mérito estão fora do prazo.")
    com_sec = sum(1 for i in itens if i["secretaria"])
    print(f"  Secretaria indicada em {com_sec} de {len(itens)}; "
          f"{sum(1 for i in itens if i.get('cita'))} citam requerimento anterior.")

    if args.dry_run:
        for i in itens[:5]:
            print(f"  {i['numero']:>12}  {i['situacao']:<16}  {i['assunto'][:50]}")
        return 0

    gravar_json(args.salvar, itens, separators=(",", ":"))
    print(f"Gravado: {args.salvar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
