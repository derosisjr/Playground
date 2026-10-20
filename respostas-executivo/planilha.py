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
