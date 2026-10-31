#!/usr/bin/env python3
"""
Conciliação mensal com o TCE-SP (AUDESP) — mês incompleto na origem
====================================================================

A base de despesas tem uma fonte só, a API da Prefeitura (Portal TP), e ela pode
publicar um mês pela metade sem aviso: jan/2025 tem R$ 69 mi empenhados no portal e
R$ 2,93 bi no TCE-SP (os empenhos globais do ano). Este script baixa, mês a mês, os
totais que o município enviou ao Tribunal (AUDESP) e grava
`despesas/conciliacao-tce.json` (versionado). O export compara com a base e marca o
mês como "incompleto na origem": fica fora das comparações e vira alerta de dados.
O dado do TCE NÃO preenche a base (decisão do usuário, 2026-10-30).

Fonte: transparencia.tce.sp.gov.br/api/json/despesas/santos/{ano}/{mes} — sem token,
um array por mês (evento, nº do empenho, fornecedor, data, valor em texto pt-BR).
Conferido em 2026-10-30: o empenhado líquido (Empenhado + Reforço − Anulação, sem a
Câmara, que não está no portal da Prefeitura) bate ao centavo com a base em jun/2025
e mar/2026; o liquidado, a ≤ 2%. O "Valor Pago" difere 5–10% do pago da base (outra
semântica) e fica registrado, mas não entra na conciliação. O TCE recebe o mês com
~1–2 meses de atraso: mês sem dado lá = "sem referência", não "incompleto".

O arquivo só muda quando um número do TCE muda (sem carimbo diário): cada mês leva
`obtido_em`, a data em que AQUELES valores chegaram.

Uso:
    python despesas/tce.py              # meses sem referência + os 3 mais recentes
    python despesas/tce.py --todos      # rebaixa todos os meses da base
    python despesas/tce.py --dry-run    # mostra sem gravar
"""

import argparse
import json
import os
import sys
import time
from datetime import date

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz do repo: comum/
from comum import http  # noqa: E402
from comum.escrita import gravar_json  # noqa: E402
from comum.formato import sem_acento  # noqa: E402
from comum.saida import configurar_stdio  # noqa: E402

configurar_stdio()

URL = "https://transparencia.tce.sp.gov.br/api/json/despesas/{municipio}/{ano}/{mes}"
MUNICIPIO = "santos"
HEADERS = {"User-Agent": "GabineteSantos/1.0 (+https://github.com/derosisjr/Playground)"}
ANO_INICIAL = 2025        # mesmo da base (crawler/export)
RECENTES = 3              # meses com referência que são rebaixados a cada execução
PAUSA = 1.0               # cortesia entre requisições (s)
AQUI = os.path.dirname(os.path.abspath(__file__))
ESTADO_PATH = os.path.join(AQUI, "conciliacao-tce.json")
FONTE = ("TCE-SP — transparencia.tce.sp.gov.br/api/json/despesas (dados enviados pelo município "
         "ao AUDESP), sem a Câmara Municipal")


def valor_br(v) -> float:
    """'7.974,63' → 7974.63; número já numérico passa direto."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def totais_mes(itens: list[dict]) -> dict:
    """Totais do mês sem a Câmara: empenhado líquido (Empenhado + Reforço − Anulação),
    liquidado e pago. Evento desconhecido fica contado em `outros` (diagnóstico)."""
    t = {"empenhado": 0.0, "liquidado": 0.0, "pago": 0.0, "registros": 0, "outros": 0}
    for r in itens:
        if "CAMARA MUNICIPAL" in sem_acento(r.get("orgao") or "").upper():
            continue
        ev = sem_acento(r.get("evento") or "").upper()
        v = valor_br(r.get("vl_despesa"))
        t["registros"] += 1
        if ev == "EMPENHADO" or ev.startswith("REFORCO"):
            t["empenhado"] += v
        elif ev.startswith("ANULACAO"):
            t["empenhado"] -= v
        elif ev == "VALOR LIQUIDADO":
            t["liquidado"] += v
        elif ev == "VALOR PAGO":
            t["pago"] += v
        else:
            t["outros"] += 1
    for c in ("empenhado", "liquidado", "pago"):
        t[c] = round(t[c], 2)
    if not t["outros"]:
        del t["outros"]
    return t


def baixar(ano: int, mes: int) -> list[dict]:
    r = http.get(URL.format(municipio=MUNICIPIO, ano=ano, mes=mes), tentativas=3, passo=10,
                 timeout=180, headers=HEADERS)
    bruto = r.content
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    dados = json.loads(texto) if texto.strip() else []
    return dados if isinstance(dados, list) else []


def ler_estado(caminho: str = ESTADO_PATH) -> dict:
    try:
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("meses"), dict) else {"meses": {}}
    except (OSError, ValueError):
        return {"meses": {}}


def meses_alvo(estado: dict, todos: bool, hoje: date) -> list[tuple[int, int]]:
    """Do 1º mês da base ao mês anterior ao corrente (o corrente nunca está no TCE).
    Sem --todos: os que ainda não têm referência + os RECENTES mais novos que têm."""
    meses = [(a, m) for a in range(ANO_INICIAL, hoje.year + 1) for m in range(1, 13)
             if (a, m) < (hoje.year, hoje.month)]
    if todos:
        return meses
    com = [k for k in meses if f"{k[0]}-{k[1]:02d}" in estado["meses"]]
    sem = [k for k in meses if k not in com]
    return sorted(set(sem) | set(com[-RECENTES:]))


def atualizar(estado: dict, alvo: list, hoje: date) -> tuple[dict, list[str]]:
    """Devolve (estado novo, mensagens). Falha de rede num mês mantém o valor anterior."""
    novo = {"versao": 1, "fonte": FONTE, "municipio": MUNICIPIO, "meses": dict(estado["meses"])}
    msgs = []
    for i, (ano, mes) in enumerate(alvo):
        chave = f"{ano}-{mes:02d}"
        try:
            itens = baixar(ano, mes)
        except Exception as e:  # noqa: BLE001 — TCE fora do ar não derruba o pipeline
            msgs.append(f"{chave}: falha ({type(e).__name__}: {str(e)[:120]}) — mantido o anterior")
            continue
        finally:
            if i < len(alvo) - 1:
                time.sleep(PAUSA)
        if not itens:
            msgs.append(f"{chave}: sem dados no TCE (ainda não enviado?)")
            continue
        t = totais_mes(itens)
        ant = novo["meses"].get(chave)
        if ant and {k: v for k, v in ant.items() if k != "obtido_em"} == t:
            continue
        novo["meses"][chave] = {**t, "obtido_em": hoje.isoformat()}
        msgs.append(f"{chave}: empenhado {t['empenhado']:,.2f} · liquidado {t['liquidado']:,.2f} "
                    f"({'novo' if not ant else 'mudou'})")
    novo["meses"] = dict(sorted(novo["meses"].items()))
    return novo, msgs


def main():
    p = argparse.ArgumentParser(description="Conciliação mensal da base de despesas com o TCE-SP (AUDESP)")
    p.add_argument("--todos", action="store_true", help="Rebaixa todos os meses (padrão: faltantes + recentes).")
    p.add_argument("--dry-run", action="store_true", help="Mostra o que mudaria; não grava.")
    p.add_argument("--estado", default=ESTADO_PATH, help="Arquivo de estado (padrão: despesas/conciliacao-tce.json).")
    args = p.parse_args()
    hoje = date.today()
    estado = ler_estado(args.estado)
    alvo = meses_alvo(estado, args.todos, hoje)
    print(f"TCE-SP: {len(alvo)} mês(es) a consultar ({', '.join(f'{a}-{m:02d}' for a, m in alvo)})",
          file=sys.stderr)
    novo, msgs = atualizar(estado, alvo, hoje)
    for m in msgs:
        print("  " + m, file=sys.stderr)
    if novo["meses"] == estado["meses"] and estado.get("versao") == novo["versao"]:
        print("Sem mudança no TCE — nada gravado.", file=sys.stderr)
        return
    if args.dry_run:
        print("[dry-run] nada gravado.", file=sys.stderr)
        return
    gravar_json(args.estado, novo, indent=1, sort_keys=True)
    print(f"Gravado {os.path.basename(args.estado)}: {len(novo['meses'])} meses com referência.", file=sys.stderr)


if __name__ == "__main__":
    main()
