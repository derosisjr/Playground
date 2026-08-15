#!/usr/bin/env python3
"""Backfill: classifica as respostas já arquivadas no Drive e preenche a coluna
`Situação da resposta` da planilha.

O crawler (`index.py`) classifica o que chega a partir de agora; este script
resolve o passivo — as centenas de itens arquivados antes da classificação
existir, que hoje constam como "respondido" só porque algum PDF apareceu.

Não depende do site da Câmara: varre as subpastas de DRIVE_FOLDER_ID.

Economia de banda: PDFs grandes não precisam ser lidos. Os ofícios de trâmite
observados têm 112–200 KB; qualquer anexo acima de LIMITE_DOWNLOAD é mérito.

Uso:
    python respostas-executivo/reclassificar.py --dry-run   # só relatório
    python respostas-executivo/reclassificar.py             # grava na planilha
    python respostas-executivo/reclassificar.py --dry-run --conferir 4164/2025,3912/2025
"""

import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classificar as cls  # noqa: E402
from index import (  # noqa: E402
    ABA_INDICACOES, ABA_REQUERIMENTOS, COL_SITUACAO,
    _col_letra, _google_services, _idx_coluna_numero, _idx_header, _norm_num,
    garantir_colunas, listar_arquivos_pasta, listar_subpastas,
)

# Acima disto, não baixa: ofício de trâmite é sempre pequeno.
LIMITE_DOWNLOAD = 1_000_000

RE_PASTA = re.compile(r"^(REQUERIMENTO|INDICACAO)_(.+)$")
RE_RESPOSTA = re.compile(r"^RESPOSTA_(\d+)_", re.I)
RE_PEDIDO = re.compile(r"^PEDIDO_", re.I)

CACHE = os.path.join(
    os.environ.get("TEMP", "."), "respostas-executivo-classes.json"
)
# Incrementar sempre que uma regra de classificar.py mudar: senão a rodada
# seguinte reaproveita veredictos obsoletos e "confirma" o resultado antigo.
CACHE_VERSAO = 1


def carregar_cache() -> dict:
    try:
        with open(CACHE, encoding="utf-8") as f:
            dados = json.load(f)
        if dados.get("versao") == CACHE_VERSAO:
            return dados.get("classes", {})
        print("  Cache de classificação obsoleto — reclassificando do zero.",
              file=sys.stderr)
    except Exception:
        pass
    return {}


def salvar_cache(cache: dict) -> None:
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump({"versao": CACHE_VERSAO, "classes": cache}, f)
    except Exception as e:
        print(f"  Aviso: não consegui gravar o cache: {e}", file=sys.stderr)


def baixar(drive, file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload

    buf = io.BytesIO()
    req = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    baixador = MediaIoBaseDownload(buf, req)
    concluido = False
    while not concluido:
        _, concluido = baixador.next_chunk()
    return buf.getvalue()


def classificar_pasta(drive, pasta_id: str, cache: dict) -> list[tuple[str, str]]:
    """Devolve [(nome do arquivo, classe)] das respostas de uma pasta, em ordem."""
    arquivos = listar_arquivos_pasta(drive, pasta_id)
    resultado: list[tuple[str, str]] = []
    for arq in sorted(arquivos, key=lambda a: a.get("createdTime", "")):
        nome = arq["name"]
        if RE_PEDIDO.match(nome):
            continue  # é o requerimento do vereador, não resposta
        if not RE_RESPOSTA.match(nome):
            # Anexo colocado à mão pela assessoria (ex.: "023491-2026-42 - OK.pdf"):
            # a presença dele já é evidência de conteúdo recebido.
            resultado.append((nome, cls.MERITO))
            continue
        if arq["id"] in cache:
            resultado.append((nome, cache[arq["id"]]))
            continue
        try:
            tamanho = int(arq.get("size") or 0)
        except (TypeError, ValueError):
            tamanho = 0
        if tamanho >= LIMITE_DOWNLOAD:
            classe = cls.MERITO
        else:
            classe = cls.classificar(cls.texto_pdf(baixar(drive, arq["id"])))
        cache[arq["id"]] = classe
        resultado.append((nome, classe))
    return resultado


def gravar_lote(sheets, sheet_id: str, pendentes: list[dict]) -> None:
    """Escreve as células acumuladas de uma vez e esvazia a lista.

    Uma chamada por linha estouraria a cota de escrita do Sheets (60/min/usuário)
    logo nas primeiras centenas de pastas."""
    if not pendentes:
        return
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=sheet_id,
        body={"valueInputOption": "RAW", "data": list(pendentes)},
    ).execute()
    pendentes.clear()


def _numero_da_pasta(nome_pasta: str) -> tuple[str, str] | None:
    """'REQUERIMENTO_4164-2025' → ('requerimentos', '4164/2025')."""
    m = RE_PASTA.match(nome_pasta)
    if not m:
        return None
    aba = ABA_REQUERIMENTOS if m.group(1) == "REQUERIMENTO" else ABA_INDICACOES
    return aba, m.group(2).replace("-", "/")


def carregar_linhas(sheets, sheet_id: str) -> dict[str, dict]:
    """Por aba: índice da coluna de situação e mapa número→linha.

    `Data da resposta de mérito` não é preenchida aqui: a data de recebimento vem
    da página da Câmara, não do Drive (o `createdTime` do arquivo é a data de
    arquivamento). Quem preenche é o crawler."""
    indice: dict[str, dict] = {}
    for aba in (ABA_REQUERIMENTOS, ABA_INDICACOES):
        cab = garantir_colunas(sheets, sheet_id, aba)
        valores = sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{aba}'!A1:Z",
        ).execute().get("values", [])
        idx_num = _idx_coluna_numero(cab)
        mapa = {}
        for n, linha in enumerate(valores[1:], start=2):
            if idx_num >= 0 and len(linha) > idx_num and linha[idx_num].strip():
                mapa[_norm_num(linha[idx_num])] = n
        indice[aba] = {"col_situacao": _idx_header(cab, COL_SITUACAO), "mapa": mapa}
    return indice


def main() -> None:
    p = argparse.ArgumentParser(description="Reclassifica as respostas já arquivadas")
    p.add_argument("--dry-run", action="store_true", help="Só relatório; não grava")
    p.add_argument("--limite", type=int, default=0, help="Processa só N pastas")
    p.add_argument("--conferir", default="",
                   help="Números separados por vírgula, detalhados arquivo a arquivo")
    args = p.parse_args()

    pasta_raiz = os.environ.get("DRIVE_FOLDER_ID", "")
    sheet_id = os.environ.get("SHEET_ID", "")
    if not pasta_raiz:
        raise EnvironmentError("Defina DRIVE_FOLDER_ID.")
    if not args.dry_run and not sheet_id:
        raise EnvironmentError("Defina SHEET_ID (ou use --dry-run).")

    conferir = {c.strip() for c in args.conferir.split(",") if c.strip()}
    drive, sheets = _google_services()
    cache = carregar_cache()

    pastas = listar_subpastas(drive, pasta_raiz)
    print(f"{len(pastas)} pasta(s) no Drive.", file=sys.stderr)

    indice = {}
    if not args.dry_run:
        indice = carregar_linhas(sheets, sheet_id)

    contagem: dict[str, dict[str, int]] = {}
    sem_linha: list[str] = []
    pendentes: list[dict] = []  # células a gravar, esvaziadas por gravar_lote
    atualizadas = 0
    for i, pasta in enumerate(sorted(pastas, key=lambda x: x["name"]), 1):
        alvo = _numero_da_pasta(pasta["name"])
        if not alvo:
            print(f"  Ignorando pasta fora do padrão: {pasta['name']}", file=sys.stderr)
            continue
        aba, numero = alvo
        if args.limite and i > args.limite:
            break
        try:
            classes = classificar_pasta(drive, pasta["id"], cache)
        except Exception as e:
            print(f"  ERRO em {pasta['name']}: {e} — pulando.", file=sys.stderr)
            continue
        sit = cls.situacao([c for _, c in classes])
        contagem.setdefault(aba, {}).setdefault(sit, 0)
        contagem[aba][sit] += 1

        if numero in conferir or sit != cls.RESPONDIDO:
            detalhe = ", ".join(f"{n}={c}" for n, c in classes) or "(sem resposta)"
            print(f"  {numero:>12}  {cls.ROTULOS[sit]:<18} {detalhe}")

        if not args.dry_run:
            info = indice.get(aba, {})
            linha = info.get("mapa", {}).get(_norm_num(numero))
            if not linha:
                sem_linha.append(f"{aba}:{numero}")
                continue
            cs = info["col_situacao"]
            if cs >= 0:
                pendentes.append({
                    "range": f"'{aba}'!{_col_letra(cs)}{linha}",
                    "values": [[sit]],
                })
                atualizadas += 1
        if i % 25 == 0:
            salvar_cache(cache)
            gravar_lote(sheets, sheet_id, pendentes)
            print(f"  ... {i}/{len(pastas)}", file=sys.stderr)

    salvar_cache(cache)
    gravar_lote(sheets, sheet_id, pendentes)

    print("\n=== Situação por aba ===")
    for aba, cs in contagem.items():
        total = sum(cs.values())
        print(f"\n{aba} — {total} item(ns) com pasta no Drive")
        for chave in (cls.RESPONDIDO, cls.SO_ENCAMINHAMENTO, cls.SO_PRORROGACAO,
                      cls.PENDENTE):
            n = cs.get(chave, 0)
            if n:
                print(f"  {cls.ROTULOS[chave]:<18} {n:>4}  ({n / total:.1%})")
    if sem_linha:
        print(f"\n{len(sem_linha)} pasta(s) sem linha correspondente na planilha: "
              f"{', '.join(sem_linha[:10])}{'...' if len(sem_linha) > 10 else ''}")
    if not args.dry_run:
        print(f"\n{atualizadas} linha(s) atualizada(s) na planilha.")


if __name__ == "__main__":
    main()
