"""GET com retry/backoff — camada comum dos crawlers.

Eram 8 cópias do mesmo laço (despesas, legis, proposituras, respostas-executivo,
diario-oficial, endividamento, indicadores, precos), duas delas byte a byte
idênticas. O User-Agent continua sendo de cada módulo (passado em `headers`):
foi um bloqueio por UA que parou Despesas por 40 dias em 2026-07, e cada fonte
externa aceita o UA que usa hoje — unificar seria mudança de comportamento
diante de WAFs que ninguém testou. [Verificar] antes de unificar.

Uma `Session` compartilhada reaproveita conexões (antes cada GET abria uma).
"""
import sys
import time

import requests

_sessao = None


def sessao() -> requests.Session:
    global _sessao
    if _sessao is None:
        _sessao = requests.Session()
    return _sessao


def get(url, params=None, *, tentativas=4, passo=4, timeout=30, headers=None,
        ok_vazio=(), silencioso=False, json=False):
    """GET com `tentativas` e backoff linear (`passo` × nº da tentativa, em s).

    ok_vazio: códigos tratados como "sem conteúdo" → devolve None (PNCP: 204/404
    são respostas normais). json=True devolve `r.json()` (o parse fica DENTRO do
    retry, como nos módulos que já faziam assim). Levanta a última exceção
    depois da última tentativa — sem dormir depois dela.
    """
    ultimo = None
    for i in range(tentativas):
        try:
            r = sessao().get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code in ok_vazio:
                return None
            r.raise_for_status()
            return r.json() if json else r
        except (requests.exceptions.RequestException, ValueError) as e:
            ultimo = e
            if i < tentativas - 1:
                espera = passo * (i + 1)
                if not silencioso:
                    print(f"  Aviso: falha HTTP ({e}); tentativa {i + 1}/{tentativas}, "
                          f"aguardando {espera}s...", file=sys.stderr)
                time.sleep(espera)
    raise ultimo


def get_json(url, params=None, **kw):
    return get(url, params, json=True, **kw)
