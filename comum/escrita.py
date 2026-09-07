"""Gravação ATÔMICA de arquivos — todo índice publicado pelo CI passa por aqui.

Motivo: os workflows têm `timeout-minutes`, e o de Preços corta o passo de
coleta DE PROPÓSITO (rules/precos.md); um `open(caminho, "w")` interrompido no
meio deixa o arquivo truncado no disco, e o passo de commit (`if: always()`)
o publicaria — o GitHub Pages serve direto do branch. Escrever num temporário
na MESMA pasta e trocar com `os.replace` garante que o caminho final nunca
contém um estado intermediário: a troca é atômica no mesmo sistema de arquivos.

O temporário chama-se `.tmp-*` (ignorado no .gitignore): se o processo morrer
entre a escrita e a troca, sobra um arquivo oculto que o `git add <pasta>` dos
workflows NÃO leva junto.
"""
import json
import os
import tempfile


def gravar_bytes(caminho, dados: bytes) -> None:
    """Escreve `dados` em `caminho` de forma atômica (tmp ao lado + os.replace)."""
    caminho = os.fspath(caminho)
    pasta = os.path.dirname(os.path.abspath(caminho))
    os.makedirs(pasta, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix="-" + os.path.basename(caminho), dir=pasta)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, caminho)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def gravar_texto(caminho, texto: str, encoding: str = "utf-8") -> None:
    gravar_bytes(caminho, texto.encode(encoding))


def gravar_json(caminho, obj, **kw) -> None:
    """`json.dump` atômico. `ensure_ascii=False` por padrão (site em pt-BR);
    os demais argumentos (`separators`, `sort_keys`, `indent`) passam direto."""
    kw.setdefault("ensure_ascii", False)
    gravar_texto(caminho, json.dumps(obj, **kw))


def gravar_json_se_mudou(caminho, obj: dict, ignorar=("atualizado_em",), **kw) -> bool:
    """Grava só se o conteúdo mudou fora dos campos `ignorar`. Devolve True se gravou.

    Para arquivos que carregam um carimbo de hora: sem isto, `atualizado_em`
    novo a cada execução fazia 290 dossiês de favorecidos virarem diff diário
    (2,8 MB/dia no histórico, cache do Pages invalidado) sem nenhum dado novo.
    """
    caminho = os.fspath(caminho)
    if os.path.exists(caminho):
        try:
            with open(caminho, encoding="utf-8") as f:
                atual = json.load(f)
        except (OSError, ValueError):
            atual = None
        if isinstance(atual, dict):
            # compara o que IRIA ao disco (tupla vira lista, etc.), senão um campo
            # em tupla nunca bate com o JSON relido e o arquivo é regravado sempre
            novo = json.loads(json.dumps(obj, **kw))
            sem = lambda d: {k: v for k, v in d.items() if k not in ignorar}  # noqa: E731
            if sem(atual) == sem(novo):
                return False
    gravar_json(caminho, obj, **kw)
    return True
