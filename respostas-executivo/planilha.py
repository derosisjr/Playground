#!/usr/bin/env python3
"""Acesso à planilha de controle — normalização do número e trava de somente leitura.

`numero_canonico` é a chave única de um pedido ("845/2026"): a mesma que o export de
indicações já usava (`int(n)/ano`). O crawler casava só os dígitos ("0845/2026" ≠
"845/2026"), e número escrito de outro jeito virava linha nova.

`somente_leitura` embrulha o cliente do Sheets/Drive e levanta `EscritaBloqueada` em
qualquer chamada que grave (update, append, batchUpdate, clear, create, delete…). É
obrigatório em diagnóstico, simulação e `--dry-run`: a garantia de que nada é gravado
fica no código, não na disciplina de quem roda.
"""

import re

# Métodos da API do Google que gravam (Sheets: values/spreadsheets; Drive: files,
# comments, permissions). Lista fechada: método novo de escrita precisa entrar aqui.
METODOS_ESCRITA = frozenset({
    "update", "append", "batchUpdate", "clear", "batchClear",
    "batchUpdateByDataFilter", "batchClearByDataFilter", "copyTo",
    "create", "delete", "copy", "patch", "emptyTrash", "modifyLabels",
    "new_batch_http_request",
})


def numero_canonico(s) -> str | None:
    """'0845/2026' → '845/2026'; '7.562/2025' → '7562/2025'; ' 12 / 2026 ' → '12/2026'.

    None para o que não é nº/aaaa (ano com 2 dígitos, data, texto, zero)."""
    t = re.sub(r"[\s.]", "", str(s or ""))
    m = re.fullmatch(r"(\d{1,6})/(\d{4})", t)
    if not m or int(m.group(1)) == 0:
        return None
    return f"{int(m.group(1))}/{m.group(2)}"


class EscritaBloqueada(PermissionError):
    """Tentativa de gravar num cliente em modo somente leitura."""


_SIMPLES = (dict, list, tuple, str, bytes, int, float, bool, type(None))


class _SomenteLeitura:
    def __init__(self, alvo):
        object.__setattr__(self, "_alvo", alvo)

    def __getattr__(self, nome):
        if nome in METODOS_ESCRITA:
            raise EscritaBloqueada(f"modo somente leitura: '{nome}' bloqueado")
        atributo = getattr(self._alvo, nome)
        if not callable(atributo):
            return atributo

        def chamada(*args, **kwargs):
            resultado = atributo(*args, **kwargs)
            # recursos (spreadsheets(), values(), files()) e requisições seguem embrulhados;
            # o resultado do execute() (dict/list) volta como é
            return resultado if isinstance(resultado, _SIMPLES) else _SomenteLeitura(resultado)
        return chamada

    def __setattr__(self, nome, valor):
        raise EscritaBloqueada("modo somente leitura: o cliente não pode ser alterado")


def somente_leitura(cliente):
    """Embrulha um cliente da API do Google (ou um falso, nos testes) e bloqueia escrita."""
    return _SomenteLeitura(cliente)


class _ComRetentativa:
    def __init__(self, alvo, executar):
        object.__setattr__(self, "_alvo", alvo)
        object.__setattr__(self, "_executar", executar)

    def __getattr__(self, nome):
        atributo = getattr(self._alvo, nome)
        if nome == "execute":
            def execute(*args, **kwargs):
                return self._executar(self._alvo) if not args and not kwargs else atributo(*args, **kwargs)
            return execute
        if not callable(atributo):
            return atributo

        def chamada(*args, **kwargs):
            resultado = atributo(*args, **kwargs)
            return resultado if isinstance(resultado, _SIMPLES) else _ComRetentativa(resultado, self._executar)
        return chamada


def com_retentativa(cliente, executar):
    """Todo `.execute()` do cliente passa por `executar(req)` (retentativa em erro
    transitório) — sem tocar em cada chamada espalhada pelo código."""
    return _ComRetentativa(cliente, executar)


def desembrulhar(obj):
    """O objeto real por baixo dos embrulhos (ex.: requisição para MediaIoBaseDownload)."""
    while isinstance(obj, (_SomenteLeitura, _ComRetentativa)):
        obj = object.__getattribute__(obj, "_alvo")
    return obj


# ── Escrita planejada ─────────────────────────────────────────────────────────
# O robô não grava mais célula a célula durante a varredura (que dura até 35 min, com a
# equipe mexendo na planilha): acumula um plano e o aplica RELENDO a aba na hora — cada
# escrita é resolvida pelo número do pedido, nunca pela linha lida no início.
#
# Garantias por construção (testes em testes_plano.py):
#   - só grava nas colunas do robô (listas fechadas abaixo); outra coluna → EscritaProibida;
#   - em linha existente só preenche célula VAZIA; sobrescrever exige `resposta_nova`
#     (chegou documento de resposta novo) e vale só para as colunas de resposta — a exceção
#     é a coluna-espelho "Situação na Câmara", que acompanha a listagem pública;
#   - não há operação de apagar linha; valor vazio nunca é gravado. Limpar célula só com
#     `Escrita.limpar`: coluna de resposta e correção autorizada (`resposta_nova`) — é o caso
#     da data de mérito de um "respondido" falso (reclassificar.py --aplicar-divergentes);
#   - linha nova entra depois da última linha com conteúdo, relida na hora, e recebe só as
#     células do robô — as colunas da equipe da linha nova ficam como estão;
#   - grava só valores (values.batchUpdate), nunca formato.
from dataclasses import dataclass, field  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

COLUNAS_RESPOSTA = ("Resposta", "Data da resposta", "Situação da resposta",
                    "Data da resposta de mérito")
# "Ementa (Câmara)": o texto oficial (o site o publica; o "Assunto" a equipe pode encurtar)
COLUNAS_CRIACAO = ("Número", "Nùmero", "Assunto", "Data da Sessão", "Ementa (Câmara)",
                   "Situação na Câmara")
# espelho da Câmara, só do robô: acompanha a listagem pública (o pedido foi votado,
# encaminhado…) e por isso é regravada quando muda — a única coluna assim (R5, out/2026)
COLUNAS_ESPELHO = ("Situação na Câmara",)


class EscritaProibida(PermissionError):
    """Escrita fora das colunas do robô."""


@dataclass
class Escrita:
    """Valores para a linha EXISTENTE de um pedido (só colunas de resposta).

    `resposta_nova` autoriza sobrescrever as colunas de resposta: chegou documento novo, ou
    é a lista aprovada de correções do reclassificar.py. `limpar` esvazia colunas de
    resposta e exige essa autorização."""
    aba: str
    numero: str
    valores: dict
    resposta_nova: bool = False
    limpar: tuple = ()


@dataclass
class NovaLinha:
    """Linha nova para um pedido que não está na aba."""
    aba: str
    numero: str
    valores: dict


@dataclass
class Relatorio:
    celulas: int = 0
    escritas: list = field(default_factory=list)       # (aba, numero) com célula gravada
    novas: list = field(default_factory=list)          # (aba, numero, linha)
    divergencias: list = field(default_factory=list)   # (aba, numero, coluna): mantida a da planilha
    sem_linha: list = field(default_factory=list)      # (aba, numero): a linha sumiu da aba
    ja_existia: list = field(default_factory=list)     # NovaLinha de número que já está na aba

    def somar(self, outro: "Relatorio") -> None:
        self.celulas += outro.celulas
        for campo in ("escritas", "novas", "divergencias", "sem_linha", "ja_existia"):
            getattr(self, campo).extend(getattr(outro, campo))


def _sem_acento(s) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).strip().lower()


def _letra(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _chave_data(s) -> tuple | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(s or ""))
    return (m.group(3), m.group(2).zfill(2), m.group(1).zfill(2)) if m else None


_EPOCA = datetime(1899, 12, 30)  # número de série 0 do Sheets
_SERIAL_MAX = 73051              # 01/01/2100 (o mesmo limite do export)


def _chave_data_celula(bruto, exibido) -> tuple | None:
    """Data de uma célula pelo VALOR (UNFORMATTED_VALUE), não pelo texto exibido: parte das
    células da planilha real está formatada como m/d/aaaa ("5/20/2026" é 20 de maio), e
    comparar o texto dava 96 divergências falsas. Número de série → data; ddmmaaaa digitado
    sem barras → data (como o `_data` do export); texto → d/m/aaaa."""
    if isinstance(bruto, (int, float)) and not isinstance(bruto, bool):
        try:
            d = (_EPOCA + timedelta(days=int(bruto)) if 0 < bruto < _SERIAL_MAX
                 else datetime.strptime(str(int(bruto)).zfill(8), "%d%m%Y"))
        except ValueError:
            return None
        return (str(d.year), f"{d.month:02d}", f"{d.day:02d}")
    return _chave_data(exibido)


def _pasta(s) -> str | None:
    m = re.search(r"/folders/([\w-]{10,})", str(s or ""))
    return m.group(1) if m else None


def _mesmo_valor(coluna: str, exibido: str, formula: str, novo, bruto=None) -> bool:
    """Compara o que está na célula com o que o robô gravaria, pelo sentido: a pasta do
    hyperlink, a data (pelo valor da célula; o robô grava dd/mm/aaaa) ou o texto sem caixa."""
    novo = str(novo or "").strip()
    if coluna == "Resposta" and _pasta(formula) and _pasta(novo):
        return _pasta(formula) == _pasta(novo)
    if coluna.startswith("Data") and _chave_data(novo):
        atual = _chave_data_celula(bruto, exibido)
        if atual:
            return atual == _chave_data(novo)
    return exibido.strip().lower() == novo.lower()


def aplicar(sheets, sheet_id: str, plano: list, executar=None, gravar: bool = True) -> Relatorio:
    """Aplica `plano` (Escrita/NovaLinha) relendo cada aba agora; uma só gravação
    (values.batchUpdate, USER_ENTERED). `executar(req)` permite retentativa.
    `gravar=False` faz a simulação completa contra a planilha de agora e só não grava
    (o `--planejar` do robô)."""
    executar = executar or (lambda req: req.execute())
    rel = Relatorio()
    dados = []
    for aba in dict.fromkeys(p.aba for p in plano):
        def ler(render):
            return executar(sheets.spreadsheets().values().get(
                spreadsheetId=sheet_id, range=f"'{aba}'", valueRenderOption=render)).get("values", [])
        exibidos, formulas, brutos = ler("FORMATTED_VALUE"), ler("FORMULA"), ler("UNFORMATTED_VALUE")
        if not exibidos:
            raise RuntimeError(f"aba '{aba}' vazia na hora de gravar — nada gravado")
        cab = exibidos[0]
        colunas = {_sem_acento(h): i for i, h in enumerate(cab) if str(h).strip()}
        i_num = colunas.get("numero", -1)
        if i_num < 0:
            raise RuntimeError(f"aba '{aba}' sem a coluna do número na hora de gravar — nada gravado")
        linhas = {}
        for n, linha in enumerate(exibidos[1:], start=2):
            num = numero_canonico(linha[i_num] if i_num < len(linha) else "")
            if num:
                linhas[num] = n  # número repetido: vale a última, como na leitura
        proxima = len(exibidos) + 1  # a leitura vem até a última linha com conteúdo

        def celula(tabela, n, c):
            linha = tabela[n - 1] if n - 1 < len(tabela) else []
            return str(linha[c]).strip() if c < len(linha) else ""

        def bruta(n, c):  # valor sem formatação (data = número de série)
            linha = brutos[n - 1] if n - 1 < len(brutos) else []
            return linha[c] if c < len(linha) else None

        for p in (x for x in plano if x.aba == aba):
            if numero_canonico(p.numero) != p.numero:
                raise ValueError(f"número fora da forma canônica no plano: {p.numero!r} — nada gravado")
            permitidas = (COLUNAS_RESPOSTA + COLUNAS_ESPELHO if isinstance(p, Escrita)
                          else COLUNAS_RESPOSTA + COLUNAS_CRIACAO)
            for nome in p.valores:
                if nome not in permitidas:
                    raise EscritaProibida(f"coluna '{nome}' não é do robô — nada gravado")
            for nome in getattr(p, "limpar", ()):
                if nome not in COLUNAS_RESPOSTA or not p.resposta_nova or nome in p.valores:
                    raise EscritaProibida(f"limpar '{nome}' exige coluna de resposta e correção "
                                          "autorizada — nada gravado")
            if isinstance(p, NovaLinha):
                if p.numero in linhas:
                    rel.ja_existia.append((aba, p.numero))
                    continue
                # célula a célula: a linha nova recebe só o que é do robô (uma fórmula que a
                # equipe puxou para baixo fica); o número vai sempre na forma canônica
                novas = {i_num: p.numero}
                for nome, val in p.valores.items():
                    c = colunas.get(_sem_acento(nome))
                    if c is not None and c != i_num and str(val or "").strip():
                        novas[c] = val
                for c, val in sorted(novas.items()):
                    dados.append({"range": f"'{aba}'!{_letra(c)}{proxima}", "values": [[val]]})
                linhas[p.numero] = proxima
                rel.novas.append((aba, p.numero, proxima))
                rel.celulas += len(novas)
                proxima += 1
                continue
            n = linhas.get(p.numero)
            if n is None:
                rel.sem_linha.append((aba, p.numero))
                continue
            gravou = False
            for nome, val in p.valores.items():
                c = colunas.get(_sem_acento(nome))
                if c is None or not str(val or "").strip():
                    continue  # valor vazio nunca é gravado: seria limpar a célula
                exibido, formula = celula(exibidos, n, c), celula(formulas, n, c)
                if _mesmo_valor(nome, exibido, formula, val, bruta(n, c)):
                    continue
                if (exibido or formula) and not p.resposta_nova and nome not in COLUNAS_ESPELHO:
                    rel.divergencias.append((aba, p.numero, nome))
                    continue
                dados.append({"range": f"'{aba}'!{_letra(c)}{n}", "values": [[val]]})
                rel.celulas += 1
                gravou = True
            for nome in p.limpar:
                c = colunas.get(_sem_acento(nome))
                if c is None or not (celula(exibidos, n, c) or celula(formulas, n, c)):
                    continue
                dados.append({"range": f"'{aba}'!{_letra(c)}{n}", "values": [[""]]})
                rel.celulas += 1
                gravou = True
            if gravou:
                rel.escritas.append((aba, p.numero))
    if dados and gravar:
        executar(sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id, body={"valueInputOption": "USER_ENTERED", "data": dados}))
    return rel
