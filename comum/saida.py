"""Saída do terminal em UTF-8 — o mesmo bloco de 5 linhas vivia em 19 scripts.

No Windows o console padrão é cp1252 e um `print("ção")` estoura; no runner
do Actions é inofensivo. `reconfigure` não existe em streams substituídos
(pytest captura, por exemplo) — por isso o try.
"""
import sys


def configurar_stdio() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
