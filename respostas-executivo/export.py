#!/usr/bin/env python3
"""Exporta a aba `requerimentos` da planilha de controle para um JSON enxuto
(`requerimentos-index.json` na raiz do repo), consumido pelo painel estático
do hub (requerimentos.html).

Fonte de verdade é o Google Sheets (não há SQLite aqui). Reutiliza a
autenticação e os helpers de cabeçalho de `index.py`.

ATENÇÃO: a coluna `Resposta` guarda uma fórmula `=HYPERLINK("<url>";"Resposta")`.
Uma leitura comum devolveria só o texto "Resposta"; por isso lemos com
`valueRenderOption=FORMULA` e extraímos a URL do Drive por regex.

Uso:
    python respostas-executivo/export.py            # grava requerimentos-index.json
    python respostas-executivo/export.py --dry-run  # só imprime contagens
    python respostas-executivo/export.py --salvar caminho.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

# Permite `import index` quando rodado como `python respostas-executivo/export.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classificar as cls  # noqa: E402
from index import (  # noqa: E402
    COL_DATA_MERITO, COL_SITUACAO, _google_services, _idx_header, _sem_acento,
)

ABA = "requerimentos"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PADRAO = os.path.join(RAIZ, "requerimentos-index.json")

# Captura a 1ª string entre aspas de =HYPERLINK("url"; "texto") (separador , ou ;)
RE_HYPERLINK = re.compile(r'HYPERLINK\(\s*"([^"]+)"', re.IGNORECASE)


def _ano_do_numero(numero: str) -> int | str:
    """Extrai o ano de um número tipo '1729/2026'. Devolve int ou '' se não achar."""
    m = re.search(r"/\s*(\d{4})", numero or "")
    if m:
        return int(m.group(1))
    m = re.search(r"\b(20\d{2})\b", numero or "")
    return int(m.group(1)) if m else ""


_EPOCH_SHEETS = datetime(1899, 12, 30)  # serial 0 do Sheets/Excel


def _data(valor) -> str:
    """Datas do Sheets vêm em formatos mistos por coluna (M/D/Y vs D/M/Y). Lendo o
    valor bruto (UNFORMATTED_VALUE), datas reais vêm como nº de série — inequívoco.
    Converte para 'dd/mm/aaaa'; se vier texto, devolve como está."""
    if isinstance(valor, bool):
        return ""
    if isinstance(valor, (int, float)):
        return (_EPOCH_SHEETS + timedelta(days=int(valor))).strftime("%d/%m/%Y")
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


def coletar() -> list[dict]:
    _, sheets = _google_services()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise EnvironmentError("Defina SHEET_ID (env) ou o secret correspondente.")

    # Duas leituras alinhadas por linha:
    #  - FORMATTED_VALUE: textos e datas como exibidos (datas viriam como nº de série
    #    se lidas como FORMULA);
    #  - FORMULA: preserva a fórmula =HYPERLINK(...) da coluna Resposta p/ extrair a URL.
    def ler(render: str) -> list:
        return (
            sheets.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"'{ABA}'!A1:Z", valueRenderOption=render)
            .execute()
            .get("values", [])
        )

    valores = ler("FORMATTED_VALUE")
    formulas = ler("FORMULA")
    brutos = ler("UNFORMATTED_VALUE")  # datas como nº de série (formato inequívoco)
    if not valores:
        return []

    cab = valores[0]
    c_num = _idx_header(cab, "Número")
    c_assunto = _idx_header(cab, "Assunto")
    c_sessao = _idx_header(cab, "Data da Sessão")
    c_resp = _idx_header(cab, "Resposta")
    c_dataresp = _idx_header(cab, "Data da resposta")
    c_status = _idx_header(cab, "Status atual")
    c_situacao = _idx_header(cab, COL_SITUACAO)
    c_merito = _idx_header(cab, COL_DATA_MERITO)

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
        # A URL sai da fórmula HYPERLINK (leitura FORMULA), mesma posição de linha;
        # as datas saem do valor bruto (UNFORMATTED), também alinhado por linha.
        linha_formula = formulas[n] if n < len(formulas) else []
        linha_bruta = brutos[n] if n < len(brutos) else []
        url = _url_resposta(campo(linha_formula, c_resp))
        # `situacao` distingue resposta de mérito de mero trâmite (pedido de prazo,
        # ofício de encaminhamento). Antes do backfill a coluna está vazia — aí vale
        # o critério antigo, "tem pasta no Drive".
        situacao = campo(linha, c_situacao) or (
            cls.RESPONDIDO if url else cls.PENDENTE
        )
        itens.append(
            {
                "numero": numero,
                "ano": _ano_do_numero(numero),
                "assunto": assunto,
                "data_sessao": _data(bruto(linha_bruta, c_sessao)),
                "data_resposta": _data(bruto(linha_bruta, c_dataresp)),
                "data_resposta_merito": _data(bruto(linha_bruta, c_merito)),
                "status": campo(linha, c_status),
                "situacao": situacao,
                "respondido": situacao == cls.RESPONDIDO,
                "url_resposta": url,
            }
        )
    return itens


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exporta requerimentos da planilha para requerimentos-index.json"
    )
    parser.add_argument("--dry-run", action="store_true", help="Só imprime contagens")
    parser.add_argument("--salvar", default=JSON_PADRAO, help="Caminho do JSON de saída")
    args = parser.parse_args()

    itens = coletar()
    respondidos = sum(1 for i in itens if i["respondido"])
    print(f"{len(itens)} requerimento(s) — {respondidos} com resposta de mérito.")
    for chave in (cls.RESPONDIDO, cls.SO_ENCAMINHAMENTO, cls.SO_PRORROGACAO,
                  cls.PENDENTE):
        n = sum(1 for i in itens if i["situacao"] == chave)
        if n:
            print(f"  {cls.ROTULOS[chave]:<18} {n:>4}  ({n / len(itens):.1%})")

    if args.dry_run:
        for i in itens[:5]:
            print(f"  {i['numero']:>12}  {i['situacao']:<16}  {i['assunto'][:50]}")
        return

    with open(args.salvar, "w", encoding="utf-8") as f:
        json.dump(itens, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Gravado: {args.salvar}")


if __name__ == "__main__":
    main()
