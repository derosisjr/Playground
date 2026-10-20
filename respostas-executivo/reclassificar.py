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
    python respostas-executivo/reclassificar.py             # preenche só célula VAZIA
    python respostas-executivo/reclassificar.py --dry-run --conferir 4164/2025,3912/2025

Auditoria dos "respondido" já gravados (R1c, out/2026) — o crawler antigo transformava PDF que
não baixava em "indeterminado", que conta como mérito, e a Moção 19/2026 caiu na pasta e na
linha do Requerimento 19/2026:
    python respostas-executivo/reclassificar.py --comparar           # só leitura; salva o plano
    python respostas-executivo/reclassificar.py --aplicar-divergentes <hash>

`--comparar` revê pelas cópias do Drive cada linha marcada "respondido" e lista as que são só
trâmite ou pendente; pasta com documentos de dois pedidos é recalculada pela página da Câmara
do pedido certo. `--aplicar-divergentes` grava só essa lista (colunas do robô, via
`planilha.aplicar`), só se o hash bater e só nos itens que ainda estão como na simulação.
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classificar as cls  # noqa: E402
import index  # noqa: E402
import planilha  # noqa: E402
from index import (  # noqa: E402
    ABA_INDICACOES, ABA_REQUERIMENTOS, COL_DATA_MERITO, COL_SITUACAO,
    _google_services, _idx_coluna_numero, _idx_header,
    garantir_colunas, listar_arquivos_pasta, listar_subpastas,
)
from planilha import numero_canonico  # noqa: E402

# Acima disto, não baixa: ofício de trâmite é sempre pequeno.
LIMITE_DOWNLOAD = 1_000_000

RE_PASTA = re.compile(r"^(REQUERIMENTO|INDICACAO)_(.+)$")
RE_RESPOSTA = re.compile(r"^RESPOSTA_(\d+)_", re.I)
RE_PEDIDO = re.compile(r"^PEDIDO_", re.I)

CACHE = os.path.join(
    os.environ.get("TEMP", "."), "respostas-executivo-classes.json"
)
PLANO = os.path.join(os.environ.get("TEMP", "."), "reclassificar-plano.json")
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
    req = planilha.desembrulhar(drive.files().get_media(fileId=file_id, supportsAllDrives=True))
    baixador = MediaIoBaseDownload(buf, req)
    concluido = False
    while not concluido:
        _, concluido = baixador.next_chunk()
    return buf.getvalue()


def classificar_pasta(drive, pasta_id: str, cache: dict,
                      arquivos: list[dict] | None = None) -> list[tuple[str, str]]:
    """Devolve [(nome do arquivo, classe)] das respostas de uma pasta, em ordem."""
    if arquivos is None:
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


def _numero_da_pasta(nome_pasta: str) -> tuple[str, str] | None:
    """'REQUERIMENTO_4164-2025' → ('requerimentos', '4164/2025')."""
    m = RE_PASTA.match(nome_pasta)
    if not m:
        return None
    aba = ABA_REQUERIMENTOS if m.group(1) == "REQUERIMENTO" else ABA_INDICACOES
    return aba, m.group(2).replace("-", "/")


def _hash(correcoes: list[dict]) -> str:
    """Impressão digital da lista: o --aplicar-divergentes só grava a lista simulada."""
    texto = json.dumps(correcoes, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def _ler_aba(sheets, sheet_id: str, aba: str) -> tuple[list, list, list]:
    def ler(render):
        return sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{aba}'", valueRenderOption=render,
        ).execute().get("values", [])
    return ler("FORMATTED_VALUE"), ler("FORMULA"), ler("UNFORMATTED_VALUE")


def _cel(tabela: list, n: int, c: int):
    linha = tabela[n] if n < len(tabela) else []
    return linha[c] if 0 <= c < len(linha) else ""


def _texto(tabela: list, n: int, c: int) -> str:
    return str(_cel(tabela, n, c)).strip()


def _ultima_por_numero(exibidos: list, i_num: int) -> dict[str, int]:
    """Número canônico → índice da ÚLTIMA linha (a que o robô mantém, como no index.py)."""
    mapa = {}
    for n in range(1, len(exibidos)):
        num = numero_canonico(_texto(exibidos, n, i_num))
        if num:
            mapa[num] = n
    return mapa


COLUNAS_GUARDA = (COL_SITUACAO, COL_DATA_MERITO, "Data da resposta")


def _pela_camara(aba: str, numero: str, drive, pasta_raiz: str, listagens: dict) -> dict | None:
    """Valores do pedido pela página DELE na Câmara — o mesmo cálculo do robô, em simulação
    (só leitura). Para pasta que recebeu documentos de outro pedido. None sem um par único."""
    import camara
    ano = numero.split("/")[1]
    tipo = camara.TIPO_REQUERIMENTO if aba == ABA_REQUERIMENTOS else camara.TIPO_INDICACAO
    if (ano, tipo) not in listagens:
        listagens[(ano, tipo)] = camara.listar_autor(ano, tipo)
    alvo = [x for x in listagens[(ano, tipo)] if x["numero"] == numero
            and (aba == ABA_INDICACOES or x["subtipo"] == "Requerimento")]
    if len(alvo) != 1:
        return None
    r = index.processar_item(index.detalhar_item(alvo[0]["cod"]), drive, pasta_raiz, False, ";",
                             classificar_tudo=True, simular=True)
    return {k: v for k, v in r.valores.items() if k in COLUNAS_GUARDA}


def comparar(drive, sheets, sheet_id: str, pasta_raiz: str, cache: dict,
             conferir: frozenset = frozenset()) -> tuple[list[dict], dict]:
    """Revê cada linha "respondido" (a última de cada número) e devolve as correções:
    {aba, numero, motivo, antes, depois, limpar, arquivos}. Só leitura."""
    correcoes, cont, listagens = [], {}, {}

    def contar(chave):
        cont[chave] = cont.get(chave, 0) + 1

    for aba in (ABA_REQUERIMENTOS, ABA_INDICACOES):
        exibidos, formulas, brutos = _ler_aba(sheets, sheet_id, aba)
        cab = exibidos[0]
        cn, cr = _idx_coluna_numero(cab), _idx_header(cab, "Resposta")
        col = {k: _idx_header(cab, k) for k in COLUNAS_GUARDA}
        for numero, n in sorted(_ultima_por_numero(exibidos, cn).items()):
            if _texto(exibidos, n, col[COL_SITUACAO]) != cls.RESPONDIDO:
                continue
            contar(f"{aba}: respondidos revistos")
            antes = {k: _texto(exibidos, n, i) for k, i in col.items()}
            pasta = planilha._pasta(_texto(formulas, n, cr))
            if not pasta:
                contar(f"{aba}: sem pasta no link (não revisto)")
                continue
            try:
                arquivos = listar_arquivos_pasta(drive, pasta)
                pedidos = sorted({a["name"] for a in arquivos if RE_PEDIDO.match(a["name"])})
                if len(pedidos) > 1:
                    # documentos de dois pedidos na mesma pasta (ex.: Moção 19/2026 na do
                    # Requerimento 19/2026): o Drive mistura os dois, vale a página da Câmara
                    contar(f"{aba}: pasta com documentos de dois pedidos")
                    depois = _pela_camara(aba, numero, drive, pasta_raiz, listagens)
                    if depois is None:
                        contar(f"{aba}: sem par único na Câmara (conferir à mão)")
                        continue
                    motivo, detalhe = "pasta com documentos de outro pedido — pela Câmara", pedidos
                else:
                    classes = classificar_pasta(drive, pasta, cache, arquivos)
                    depois = {COL_SITUACAO: cls.situacao([c for _, c in classes])}
                    motivo = "reclassificado pelas cópias do Drive"
                    detalhe = [f"{nome}={c}" for nome, c in classes]
            except Exception as e:
                contar(f"{aba}: erro")
                print(f"  ERRO em {aba} {numero}: {e} — não revisto.", file=sys.stderr)
                continue
            mudou = {k: v for k, v in depois.items() if v and not planilha._mesmo_valor(
                k, antes[k], _texto(formulas, n, col[k]), v, _cel(brutos, n, col[k]))}
            # quem deixa de ser "respondido" perde a data de mérito (o painel a mostraria)
            rebaixado = depois.get(COL_SITUACAO, cls.RESPONDIDO) != cls.RESPONDIDO
            limpar = ([COL_DATA_MERITO] if rebaixado and antes[COL_DATA_MERITO]
                      and not depois.get(COL_DATA_MERITO) else [])
            if numero in conferir:
                print(f"  {aba} {numero}: {motivo}; {detalhe}; muda {mudou or '—'}")
            if mudou or limpar:
                correcoes.append({"aba": aba, "numero": numero, "motivo": motivo, "antes": antes,
                                  "depois": mudou, "limpar": limpar, "arquivos": detalhe})
    return correcoes, cont


def aplicar_divergentes(sheets, sheet_id: str, caminho: str, hash_pedido: str) -> int:
    """Grava a lista salva pelo --comparar: só se o hash bater, só nos itens que estão
    exatamente como na simulação, só nas colunas do robô (planilha.aplicar)."""
    with open(caminho, encoding="utf-8") as f:
        plano = json.load(f)
    if plano.get("sheet_id") != sheet_id:
        print("ERRO: o plano é de outra planilha — nada gravado.", file=sys.stderr)
        return 1
    correcoes = plano.get("correcoes", [])
    if not (hash_pedido == plano.get("hash") == _hash(correcoes)):
        print("ERRO: o hash não confere com o plano salvo — nada gravado.", file=sys.stderr)
        return 1
    atuais = {}
    for aba in dict.fromkeys(c["aba"] for c in correcoes):
        exibidos, _, _ = _ler_aba(sheets, sheet_id, aba)
        cab = exibidos[0]
        col = {k: _idx_header(cab, k) for k in COLUNAS_GUARDA}
        for numero, n in _ultima_por_numero(exibidos, _idx_coluna_numero(cab)).items():
            atuais[(aba, numero)] = {k: _texto(exibidos, n, i) for k, i in col.items()}
    escritas, mudaram = [], []
    for c in correcoes:
        if atuais.get((c["aba"], c["numero"])) != c["antes"]:
            mudaram.append(f"{c['aba']} {c['numero']}")
            continue
        escritas.append(planilha.Escrita(c["aba"], c["numero"], c["depois"],
                                         resposta_nova=True, limpar=tuple(c["limpar"])))
    rel = planilha.aplicar(sheets, sheet_id, escritas)
    lista = (": " + ", ".join(mudaram)) if mudaram else ""
    print(f"{len(rel.escritas)} linha(s) corrigida(s), {rel.celulas} célula(s); "
          f"{len(mudaram)} item(ns) mudaram desde a simulação e ficaram como estão{lista}.")
    if rel.sem_linha:
        print(f"Sem linha na hora de gravar: {rel.sem_linha}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Reclassifica as respostas já arquivadas")
    p.add_argument("--dry-run", action="store_true", help="Só relatório; não grava")
    p.add_argument("--limite", type=int, default=0, help="Processa só N pastas")
    p.add_argument("--conferir", default="",
                   help="Números separados por vírgula, detalhados arquivo a arquivo")
    p.add_argument("--comparar", action="store_true",
                   help="Revê os 'respondido' da planilha (só leitura) e salva o plano de correções")
    p.add_argument("--aplicar-divergentes", default="", metavar="HASH",
                   help="Grava o plano salvo pelo --comparar, se o hash bater")
    p.add_argument("--plano", default=PLANO, help=f"Arquivo do plano (padrão: {PLANO})")
    args = p.parse_args()

    pasta_raiz = os.environ.get("DRIVE_FOLDER_ID", "")
    sheet_id = os.environ.get("SHEET_ID", "")
    if not pasta_raiz:
        raise EnvironmentError("Defina DRIVE_FOLDER_ID.")
    if (not args.dry_run or args.comparar or args.aplicar_divergentes) and not sheet_id:
        raise EnvironmentError("Defina SHEET_ID (ou use --dry-run).")

    conferir = frozenset(numero_canonico(c) or c.strip() for c in args.conferir.split(",") if c.strip())
    drive, sheets = (planilha.com_retentativa(s, index._executar) for s in _google_services())
    if args.dry_run or args.comparar:
        drive, sheets = planilha.somente_leitura(drive), planilha.somente_leitura(sheets)

    if args.aplicar_divergentes:
        return aplicar_divergentes(sheets, sheet_id, args.plano, args.aplicar_divergentes)

    cache = carregar_cache()
    if args.comparar:
        try:
            correcoes, cont = comparar(drive, sheets, sheet_id, pasta_raiz, cache, conferir)
        finally:
            salvar_cache(cache)
        h = _hash(correcoes)
        with open(args.plano, "w", encoding="utf-8") as f:
            json.dump({"sheet_id": sheet_id, "gerado_em": datetime.now().isoformat(timespec="seconds"),
                       "hash": h, "correcoes": correcoes}, f, ensure_ascii=False, indent=1)
        for chave, n in sorted(cont.items()):
            print(f"  {chave}: {n}")
        trocas = {}
        for c in correcoes:
            chave = (c["aba"], c["motivo"], c["depois"].get(COL_SITUACAO, "(situação igual)"))
            trocas[chave] = trocas.get(chave, 0) + 1
        print(f"\n{len(correcoes)} correção(ões):")
        for (aba, motivo, para), n in sorted(trocas.items()):
            print(f"  {aba}: {n} → {para} ({motivo})")
        for c in correcoes:
            extra = (" e limpa " + ", ".join(c["limpar"])) if c["limpar"] else ""
            print(f"    {c['aba']} {c['numero']}: {c['antes']} → {c['depois']}{extra}")
        print(f"\nPlano salvo em {args.plano} — hash {h}.\n"
              f"Para gravar: reclassificar.py --aplicar-divergentes {h}")
        return 0

    pastas = listar_subpastas(drive, pasta_raiz)
    print(f"{len(pastas)} pasta(s) no Drive.", file=sys.stderr)
    if not args.dry_run:
        for aba in (ABA_REQUERIMENTOS, ABA_INDICACOES):
            garantir_colunas(sheets, sheet_id, aba)

    contagem: dict[str, dict[str, int]] = {}
    plano: list = []  # preenche só célula vazia: o que diverge fica para o --comparar
    rel = planilha.Relatorio()
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

        num = numero_canonico(numero)
        if num in conferir or sit != cls.RESPONDIDO:
            detalhe = ", ".join(f"{n}={c}" for n, c in classes) or "(sem resposta)"
            print(f"  {numero:>12}  {cls.ROTULOS[sit]:<18} {detalhe}")

        if not args.dry_run and num:
            plano.append(planilha.Escrita(aba, num, {COL_SITUACAO: sit}))
        if i % 100 == 0:
            salvar_cache(cache)
            if plano:
                rel.somar(planilha.aplicar(sheets, sheet_id, plano))
                plano = []
            print(f"  ... {i}/{len(pastas)}", file=sys.stderr)

    salvar_cache(cache)
    if plano:
        rel.somar(planilha.aplicar(sheets, sheet_id, plano))

    print("\n=== Situação por aba ===")
    for aba, cs in contagem.items():
        total = sum(cs.values())
        print(f"\n{aba} — {total} item(ns) com pasta no Drive")
        for chave in (cls.RESPONDIDO, cls.SO_ENCAMINHAMENTO, cls.SO_PRORROGACAO,
                      cls.PENDENTE):
            n = cs.get(chave, 0)
            if n:
                print(f"  {cls.ROTULOS[chave]:<18} {n:>4}  ({n / total:.1%})")
    if rel.sem_linha:
        amostra = ", ".join(f"{a}:{n}" for a, n in rel.sem_linha[:10])
        print(f"\n{len(rel.sem_linha)} pasta(s) sem linha correspondente na planilha: "
              f"{amostra}{'...' if len(rel.sem_linha) > 10 else ''}")
    if not args.dry_run:
        print(f"\n{len(rel.escritas)} linha(s) preenchida(s) na planilha; "
              f"{len(rel.divergencias)} com outra situação mantida (ver --comparar).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
