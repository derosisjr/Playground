import os
import sys

import pytest
import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
from comum import http  # noqa: E402


class _Resp:
    def __init__(self, status=200, corpo=None):
        self.status_code = status
        self._corpo = corpo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._corpo, Exception):
            raise self._corpo
        return self._corpo


def _sessao_falsa(monkeypatch, respostas):
    """Cada chamada devolve o próximo item: _Resp ou exceção a levantar."""
    fila = list(respostas); chamadas = []

    class S:
        def get(self, url, params=None, headers=None, timeout=None):
            chamadas.append((url, params, headers, timeout))
            r = fila.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
    monkeypatch.setattr(http, "_sessao", S())
    dormidas = []
    monkeypatch.setattr(http.time, "sleep", lambda s: dormidas.append(s))
    return chamadas, dormidas


def test_retry_com_backoff_linear_e_sem_dormir_depois_da_ultima(monkeypatch):
    chamadas, dormidas = _sessao_falsa(monkeypatch, [
        requests.exceptions.ConnectionError("x"), requests.exceptions.ConnectionError("y"),
        requests.exceptions.ConnectionError("z"), requests.exceptions.ConnectionError("w")])
    with pytest.raises(requests.exceptions.ConnectionError):
        http.get("u", tentativas=4, passo=8, silencioso=True)
    assert len(chamadas) == 4
    assert dormidas == [8, 16, 24]      # 3 esperas, nenhuma após a 4ª tentativa


def test_sucesso_na_segunda_tentativa_devolve_resposta(monkeypatch):
    chamadas, dormidas = _sessao_falsa(monkeypatch, [requests.exceptions.Timeout("t"), _Resp(200)])
    r = http.get("u", {"a": 1}, passo=5, timeout=120, headers={"User-Agent": "X"}, silencioso=True)
    assert r.status_code == 200 and dormidas == [5]
    assert chamadas[-1] == ("u", {"a": 1}, {"User-Agent": "X"}, 120)


def test_ok_vazio_devolve_none_sem_retry(monkeypatch):
    chamadas, _ = _sessao_falsa(monkeypatch, [_Resp(204)])
    assert http.get_json("u", ok_vazio=(204, 404), silencioso=True) is None
    assert len(chamadas) == 1


def test_json_invalido_entra_no_retry(monkeypatch):
    _, dormidas = _sessao_falsa(monkeypatch, [_Resp(200, ValueError("json ruim")), _Resp(200, {"ok": 1})])
    assert http.get_json("u", passo=1, silencioso=True) == {"ok": 1}
    assert dormidas == [1]
