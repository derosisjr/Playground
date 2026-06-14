#!/usr/bin/env python3
"""
Motor de risco fiscal do Diário Oficial de Santos
=================================================

Classifica cada ato em 🔴 / 🟡 / 🟢 aplicando os **gatilhos determinísticos** da skill
`dom-santos` (ver `references/criterios-risco.md`) — **sem IA e sem a Base de Despesas**.
Usa só os dados do próprio ato (enriquecidos no `classificador.py`: termo, valor_num,
favorecido, retroativo) e, para gatilhos cross-edição, o histórico em `diario.sqlite`.

O `motivo` traz o gatilho + a base legal, no formato que alimenta o requerimento da skill.
Quando falta o dado para decidir (ex.: dispensa sem valor), o ato fica 🟢 — nunca 🔴 falso.

Limiares legais ficam em constantes no topo — **verificar anualmente** (decretos atualizam
os valores do art. 75 da Lei 14.133/21).
"""

import re
import unicodedata

# ── Limiares (verificar anualmente) ───────────────────────────────────────────
ADITIVO_PCT = 0.25                       # art. 125, Lei 14.133/21
DISPENSA_COMPRAS_SERVICOS = 59_906.02    # art. 75, II — base 2024 (atualizar p/ ano corrente)
DISPENSA_OBRAS = 119_812.02             # art. 75, I
LOCACAO_INEXIG_MES = 30_000.0            # art. 74, V (heurística da skill)
BRINDES = 50_000.0                       # art. 37, §1º, CF/88
VALOR_ALERTA = 1_000_000.0               # teto genérico p/ monitorar (🟡)

VERMELHO, AMARELO, VERDE = "🔴", "🟡", "🟢"
_ORDEM = {VERDE: 0, AMARELO: 1, VERMELHO: 2}


def _sa(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    return s.lower()


def _br(v: float) -> str:
    """Formata em moeda BR: 7597872.0 -> 'R$ 7.597.872,00'."""
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class _R:
    """Acumula nível e motivos de um ato (o maior nível prevalece)."""
    def __init__(self):
        self.nivel = VERDE
        self.motivos: list[str] = []

    def add(self, nivel: str, motivo: str):
        if _ORDEM[nivel] > _ORDEM[self.nivel]:
            self.nivel = nivel
        self.motivos.append(motivo)


def _contar_osc_historico(conn, favorecido: str, secretaria: str) -> int:
    """Quantos convênios/fomento dessa OSC nessa secretaria já há no histórico."""
    if conn is None or not favorecido:
        return 0
    cur = conn.execute(
        "SELECT COUNT(*) FROM atos WHERE categoria='Convênios e fomento' "
        "AND favorecido = ? AND secretaria = ?", (favorecido, secretaria))
    return cur.fetchone()[0]


def avaliar(atos: list[dict], conn=None) -> list[dict]:
    """Devolve, para cada ato (mesma ordem), {'risco': nível, 'motivo': texto}."""
    # índices intra-edição para gatilhos de padrão
    osc_edicao: dict[tuple, int] = {}        # (favorecido, secretaria) -> contagem (convênios)
    valor_favs: dict[float, set] = {}        # valor_num -> {favorecidos} (convênios)
    for a in atos:
        if a["categoria"] == "Convênios e fomento" and a.get("favorecido"):
            k = (a["favorecido"], a.get("secretaria", ""))
            osc_edicao[k] = osc_edicao.get(k, 0) + 1
            if a.get("valor_num"):
                valor_favs.setdefault(a["valor_num"], set()).add(a["favorecido"])

    saida = []
    for a in atos:
        r = _R()
        tipo = a.get("tipo", "")
        obj = _sa(a.get("objeto", ""))
        v = a.get("valor_num")
        termo = a.get("termo")

        # Aditivos
        if termo and termo >= 3:
            r.add(VERMELHO, f"Aditivo {termo}º termo ao mesmo contrato — art. 125, Lei 14.133/21")
        elif termo == 2:
            r.add(AMARELO, "2º aditivo no exercício — monitorar (art. 125, Lei 14.133/21)")
        if a.get("retroativo"):
            r.add(VERMELHO, "Ato com efeitos retroativos — art. 37, caput, CF/88")

        # Dispensa / inexigibilidade acima do limite legal
        if tipo in ("Dispensa", "Inexigibilidade") and v:
            limite = DISPENSA_OBRAS if ("obra" in obj or "engenharia" in obj) else DISPENSA_COMPRAS_SERVICOS
            if v > limite:
                r.add(VERMELHO, f"{tipo} acima do limite legal ({_br(v)}) — art. 75, Lei 14.133/21")
        if tipo == "Inexigibilidade" and v and "loca" in obj and v > LOCACAO_INEXIG_MES:
            r.add(VERMELHO, "Inexigibilidade de locação de alto valor — art. 74, V, Lei 14.133/21")

        # Crédito extraordinário (decreto)
        if "credito extraordinario" in obj:
            r.add(VERMELHO, "Crédito extraordinário — verificar urgência (art. 167, §3º, CF/88)")

        # Material promocional / brindes
        if v and v > BRINDES and re.search(r"brinde|promocional|material publicit", obj):
            r.add(VERMELHO, "Material promocional/brindes de alto valor — art. 37, §1º, CF/88")

        # OSC: repetição na mesma secretaria (edição + histórico)
        if a["categoria"] == "Convênios e fomento" and a.get("favorecido"):
            k = (a["favorecido"], a.get("secretaria", ""))
            total = osc_edicao.get(k, 0) + _contar_osc_historico(conn, *k)
            if total >= 2:
                r.add(VERMELHO, "Mesma OSC com 2+ termos na mesma secretaria — Lei 13.019/14")
            # valores idênticos para OSCs diferentes
            if v and len(valor_favs.get(v, set())) >= 2:
                r.add(VERMELHO, "Valores idênticos em termos para OSCs diferentes — Lei 13.019/14")

        # Valor elevado (genérico) — só sobe se ainda estiver verde
        if v and v >= VALOR_ALERTA and r.nivel == VERDE:
            r.add(AMARELO, f"Valor elevado ({_br(v)}) — monitorar")

        saida.append({"risco": r.nivel, "motivo": " | ".join(r.motivos)})
    return saida
