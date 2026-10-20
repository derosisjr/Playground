#!/usr/bin/env python3
"""Mescla das indicações repetidas (R4, out/2026).

Em 20/08/2026 a leitura da aba falhou e o robô anexou de novo as indicações que a equipe já
tinha cadastrado: 318 números ficaram com 2 linhas e 3 com 3. A linha da equipe (resumo
curto, bairro, protocolo, prazo) e a do robô (ementa da Câmara, datas, resposta) são a
mesma indicação — o export já as juntava para o site.

Por número repetido:
  - FICA a primeira linha (a da equipe, na posição em que a equipe a pôs). Nela, as colunas
    do robô (Resposta, Data da resposta, Situação da resposta, Data da resposta de mérito)
    recebem os valores da linha oficial — a mesma escolha do export (`linha_oficial`) —, a
    ementa da Câmara vai para a coluna nova do robô "Ementa (Câmara)" (o "Assunto" da equipe
    fica) e valor da equipe que só exista na outra linha é copiado para a célula VAZIA
    correspondente;
  - SAI a outra linha, só se estiver "limpa": sem nota, e cada coluna da equipe vazia ou
    igual à da linha que fica.
Grupo com qualquer conflito NÃO é mexido e vai para a lista da equipe: coluna da equipe
diferente entre as linhas, coluna do robô preenchida com outro valor na linha que fica,
data da sessão diferente, nota na linha que sairia, ou item publicado que mudaria (o export
é refeito com o grupo já mesclado e tem de sair igual, item a item).

    python respostas-executivo/mesclar_indicacoes.py               # simulação, só leitura
    python respostas-executivo/mesclar_indicacoes.py --detalhe     # + números e motivos (local)
    python respostas-executivo/mesclar_indicacoes.py --aplicar <hash>

`--aplicar` refaz a simulação na planilha de agora e só segue se o hash bater (o hash cobre o
conteúdo das linhas que ficam e saem e o que será gravado — nunca a posição). Antes de tudo
duplica a aba ("indicações (backup AAAA-MM-DD)") e confere a cópia; grava os valores na
linha que fica (values.batchUpdate, como o robô) e depois apaga, num único
spreadsheets.batchUpdate e de baixo para cima, só as linhas que continuam idênticas às da
simulação. Planilha com comentário (balão) não é mexida: a âncora não diz a linha.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export  # noqa: E402
import index  # noqa: E402
import planilha  # noqa: E402
from index import ABA_INDICACOES as ABA, _idx_coluna_numero, _idx_header  # noqa: E402
from planilha import numero_canonico  # noqa: E402

COL_EMENTA = export.COL_EMENTA
ROBO = planilha.COLUNAS_RESPOSTA
DATAS = ("Data da Sessão", "Data da resposta", "Data da resposta de mérito")
_EPOCA = datetime(1899, 12, 30)


def ler(sheets, sheet_id: str) -> dict:
    """As três leituras da aba, as notas (linha, coluna — base 0) e o id da aba."""
    def get(render):
        return sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{ABA}'", valueRenderOption=render,
        ).execute().get("values", [])
    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, ranges=[f"'{ABA}'"], includeGridData=True,
        fields="sheets(properties(sheetId),data(rowData(values(note))))").execute()
    folha = meta["sheets"][0]
    notas = set()
    for bloco in folha.get("data", []):
        for r, row in enumerate(bloco.get("rowData", []) or []):
            for c, cel in enumerate(row.get("values", []) or []):
                if cel.get("note"):
                    notas.add((r, c))
    return {"v": get("FORMATTED_VALUE"), "f": get("FORMULA"), "b": get("UNFORMATTED_VALUE"),
            "notas": notas, "sheetId": folha["properties"]["sheetId"]}


def _cel(tabela: list, r: int, c: int):
    linha = tabela[r] if r < len(tabela) else []
    return linha[c] if 0 <= c < len(linha) else ""


def _t(tabela: list, r: int, c: int) -> str:
    return str(_cel(tabela, r, c)).strip()


def _foto(tab: dict, r: int, largura: int) -> list:
    """O conteúdo de uma linha (exibido e fórmula) — base do hash e da conferência final."""
    return [[_t(tab["v"], r, c) for c in range(largura)], [_t(tab["f"], r, c) for c in range(largura)]]


def _data_br(bruto) -> str:
    if isinstance(bruto, (int, float)) and not isinstance(bruto, bool) and 0 < bruto < 73051:
        return (_EPOCA + timedelta(days=int(bruto))).strftime("%d/%m/%Y")
    return ""


def _a_gravar(tab: dict, r: int, c: int, nome: str) -> tuple[str, tuple]:
    """(texto para values.batchUpdate USER_ENTERED, como a célula ficaria nas 3 leituras)."""
    exibido, formula, bruto = _t(tab["v"], r, c), _t(tab["f"], r, c), _cel(tab["b"], r, c)
    if formula.startswith("="):
        return formula, (exibido, formula, bruto)
    d = _data_br(bruto) if nome in DATAS else ""
    if d:  # data vai como dd/mm/aaaa: a planilha (pt_BR) guarda o mesmo nº de série
        return d, (d, d, bruto)
    return exibido, (exibido, exibido, bruto)


def _iguais(tab: dict, r1: int, r2: int, c: int, nome: str) -> bool:
    f1, f2 = _t(tab["f"], r1, c), _t(tab["f"], r2, c)
    if f1 == f2:
        return True
    if nome == "Resposta" and planilha._pasta(f1) and planilha._pasta(f2):
        return planilha._pasta(f1) == planilha._pasta(f2)
    k1 = planilha._chave_data_celula(_cel(tab["b"], r1, c), _t(tab["v"], r1, c))
    k2 = planilha._chave_data_celula(_cel(tab["b"], r2, c), _t(tab["v"], r2, c))
    return bool(k1) and k1 == k2


def _item_publico(cab: list, linhas: list[tuple]) -> dict:
    """O item que o export publicaria para estas linhas [(exibidos, fórmulas, brutos)]."""
    itens, _ = export.montar_indicacoes([cab] + [x[0] for x in linhas], [cab] + [x[1] for x in linhas],
                                        [cab] + [x[2] for x in linhas])
    return itens[0] if len(itens) == 1 else {"_itens": itens}


def simular(tab: dict) -> dict:
    """Plano da mescla: {"mesclar": [...], "conflitos": [...], "criar_ementa", "i_ementa", "largura"}."""
    v, f, b = tab["v"], tab["f"], tab["b"]
    cab = list(v[0])
    largura = max(len(linha) for linha in v + f)
    i_num, i_assunto, i_sessao = _idx_coluna_numero(cab), _idx_header(cab, "Assunto"), _idx_header(cab, "Data da Sessão")
    robo = {_idx_header(cab, c): c for c in ROBO if _idx_header(cab, c) >= 0}
    i_ementa = _idx_header(cab, COL_EMENTA)
    criar = i_ementa < 0
    if criar:
        i_ementa = largura  # 1ª coluna vazia em todas as linhas (coluna sem título com conteúdo é da equipe)
    # tudo que não é do robô nem de criação é da equipe — inclusive coluna sem título
    equipe = [c for c in range(largura) if c not in robo and c not in (i_num, i_assunto, i_sessao, i_ementa)]

    def nome(c):
        return cab[c] if c < len(cab) and str(cab[c]).strip() else f"(coluna {index._col_letra(c)} sem título)"

    cab_depois = cab + [""] * (i_ementa + 1 - len(cab))
    cab_depois[i_ementa] = COL_EMENTA
    grupos: dict[str, list[int]] = {}
    for r in range(1, len(v)):
        num = numero_canonico(_t(v, r, i_num))
        if num:
            grupos.setdefault(num, []).append(r)
    plano = {"mesclar": [], "conflitos": [], "criar_ementa": criar, "i_ementa": i_ementa, "largura": largura}
    for num, linhas in sorted(grupos.items(), key=lambda g: g[1][0]):
        if len(linhas) < 2:
            continue
        fica, sai = linhas[0], linhas[1:]
        motivos, escritas = [], {}  # escritas: coluna → (texto, (v, f, b))
        if any((r, c) in tab["notas"] for r in sai for c in range(largura)):
            motivos.append("nota na linha que sairia")
        for c in equipe:
            for r in sai:
                if not _t(f, r, c):
                    continue
                if not _t(f, fica, c) and c not in escritas:
                    escritas[c] = _a_gravar(tab, r, c, nome(c))
                elif not (_t(f, fica, c) and _iguais(tab, fica, r, c, nome(c))) and not (
                        c in escritas and escritas[c] == _a_gravar(tab, r, c, nome(c))):
                    motivos.append(f"coluna da equipe '{nome(c)}' diferente entre as linhas")
        for r in sai:
            if _t(v, r, i_sessao) and _t(v, fica, i_sessao) and not _iguais(tab, fica, r, i_sessao, "Data da Sessão"):
                motivos.append("data da sessão diferente")
            elif _t(v, r, i_sessao) and not _t(v, fica, i_sessao) and i_sessao not in escritas:
                escritas[i_sessao] = _a_gravar(tab, r, i_sessao, "Data da Sessão")
        # a linha oficial, pela mesma regra do export
        mini = [cab] + [v[r] for r in linhas], [cab] + [_cel_linha(f, r) for r in linhas], [cab] + [_cel_linha(b, r) for r in linhas]
        dados_export, _ = export.linhas_indicacoes(*mini)
        if len(dados_export) != len(linhas):
            motivos.append("linha sem número válido para o export")
            plano["conflitos"].append({"numero": num, "linhas": [r + 1 for r in linhas], "motivos": motivos})
            continue
        of = linhas[dados_export.index(export.linha_oficial(dados_export))]
        if of != fica:
            for c, col_nome in robo.items():
                if not _t(f, of, c):
                    continue
                if not _t(f, fica, c):
                    escritas[c] = _a_gravar(tab, of, c, col_nome)
                elif not _iguais(tab, fica, of, c, col_nome):
                    motivos.append(f"coluna do robô '{col_nome}' com outro valor na linha que fica")
            ementa = _t(v, of, i_assunto)
            if ementa and planilha._sem_acento(ementa) != planilha._sem_acento(_t(v, fica, i_assunto)):
                atual = "" if criar else _t(v, fica, i_ementa)
                if not atual:
                    escritas[i_ementa] = (ementa, (ementa, ementa, ementa))
                elif atual != ementa:
                    motivos.append("ementa diferente na linha que fica")
        # o item publicado não pode mudar (conferido só no grupo sem outro conflito)
        if not motivos:
            antes = _item_publico(cab, [(v[r], _cel_linha(f, r), _cel_linha(b, r)) for r in linhas])
            depois_v, depois_f, depois_b = (_completa(t, fica, len(cab_depois)) for t in (v, f, b))
            for c, (_, (ev, ef, eb)) in escritas.items():
                depois_v[c], depois_f[c], depois_b[c] = ev, ef, eb
            if antes != _item_publico(cab_depois, [(depois_v, depois_f, depois_b)]):
                motivos.append("o item publicado mudaria")
        registro = {"numero": num, "linhas": [r + 1 for r in linhas], "motivos": sorted(set(motivos))}
        if motivos:
            plano["conflitos"].append(registro)
            continue
        registro.update({
            "fica": _foto(tab, fica, largura), "sai": [_foto(tab, r, largura) for r in sai],
            "escritas": {(COL_EMENTA if c == i_ementa else nome(c)): t for c, (t, _) in sorted(escritas.items())},
            "_fica": fica, "_sai": sai, "_colunas": {c: t for c, (t, _) in escritas.items()},
        })
        plano["mesclar"].append(registro)
    return plano


def _cel_linha(tabela: list, r: int) -> list:
    return list(tabela[r]) if r < len(tabela) else []


def _completa(tabela: list, r: int, largura: int) -> list:
    linha = _cel_linha(tabela, r)
    return linha + [""] * (largura - len(linha))


def hash_plano(plano: dict) -> str:
    """Conteúdo (nunca posição) do que será mexido: o --aplicar só segue se bater."""
    base = {"criar_ementa": plano["criar_ementa"],
            "mesclar": [{k: g[k] for k in ("numero", "fica", "sai", "escritas")} for g in plano["mesclar"]]}
    texto = json.dumps(base, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def _resumo(plano: dict, detalhe: bool) -> None:
    apagar = sum(len(g["_sai"]) for g in plano["mesclar"])
    print(f"{len(plano['mesclar'])} número(s) a mesclar ({apagar} linha(s) a apagar); "
          f"{len(plano['conflitos'])} com conflito, que ficam como estão.")
    motivos = {}
    for g in plano["conflitos"]:
        for m in g["motivos"]:
            motivos[m] = motivos.get(m, 0) + 1
    for m, n in sorted(motivos.items(), key=lambda x: -x[1]):
        print(f"  conflito — {m}: {n}")
    if plano["criar_ementa"]:
        print(f"  coluna nova do robô: \"{COL_EMENTA}\" em {index._col_letra(plano['i_ementa'])}")
    if detalhe:  # texto e números da planilha: só localmente (o log do Actions é público)
        for g in plano["conflitos"]:
            print(f"    conflito {g['numero']} (linhas {g['linhas']}): {'; '.join(g['motivos'])}")
        for g in plano["mesclar"]:
            print(f"    mescla {g['numero']}: fica a linha {g['linhas'][0]}, saem {g['linhas'][1:]}; "
                  f"grava {sorted(g['escritas'])}")


def aplicar(drive, sheets, sheet_id: str, hash_pedido: str) -> int:
    tab = ler(sheets, sheet_id)
    plano = simular(tab)
    h = hash_plano(plano)
    if h != hash_pedido:
        print(f"ERRO: o hash da planilha de agora ({h}) não é o da simulação ({hash_pedido}) — "
              "simule de novo. Nada foi feito.", file=sys.stderr)
        return 1
    if not plano["mesclar"]:
        print("Nada a mesclar.")
        return 0
    comentarios = drive.comments().list(fileId=sheet_id, includeDeleted=False,
                                        fields="comments(id,resolved)").execute().get("comments", [])
    if any(not c.get("resolved") for c in comentarios):
        print("ERRO: a planilha tem comentário aberto (a âncora não diz a linha) — nada foi feito.",
              file=sys.stderr)
        return 1
    # 1) cópia da aba inteira, conferida antes de mexer em qualquer coisa
    titulos = {s["properties"]["title"] for s in sheets.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets.properties.title").execute()["sheets"]}
    copia = f"{ABA} (backup {date.today():%Y-%m-%d})"
    n = 2
    while copia in titulos:
        copia, n = f"{ABA} (backup {date.today():%Y-%m-%d} {n})", n + 1
    sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
        {"duplicateSheet": {"sourceSheetId": tab["sheetId"], "newSheetName": copia}}]}).execute()
    for render, chave in (("FORMATTED_VALUE", "v"), ("FORMULA", "f")):
        lida = sheets.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"'{copia}'",
                                                  valueRenderOption=render).execute().get("values", [])
        if lida != tab[chave]:
            print(f"ERRO: a cópia '{copia}' não confere com a aba — nada mais foi feito.", file=sys.stderr)
            return 1
    print(f"Cópia de segurança: aba '{copia}' (conferida).")
    # 2) coluna nova do robô, se faltar
    i_ementa = plano["i_ementa"]
    if plano["criar_ementa"]:
        index._garantir_largura(sheets, sheet_id, ABA, i_ementa + 1)
        sheets.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=f"'{ABA}'!{index._col_letra(i_ementa)}1",
            valueInputOption="RAW", body={"values": [[COL_EMENTA]]}).execute()
    # 3) valores na linha que fica (como o robô grava: USER_ENTERED, só valores)
    dados = [{"range": f"'{ABA}'!{index._col_letra(c)}{g['_fica'] + 1}", "values": [[t]]}
             for g in plano["mesclar"] for c, t in sorted(g["_colunas"].items())]
    if dados:
        sheets.spreadsheets().values().batchUpdate(spreadsheetId=sheet_id, body={
            "valueInputOption": "USER_ENTERED", "data": dados}).execute()
    # 4) apaga só as linhas que continuam idênticas às da simulação, de baixo para cima
    agora = ler(sheets, sheet_id)
    largura = plano["largura"]
    i_num = _idx_coluna_numero(agora["v"][0])
    por_numero: dict[str, list[int]] = {}
    for r in range(1, len(agora["v"])):
        num = numero_canonico(_t(agora["v"], r, i_num))
        if num:
            por_numero.setdefault(num, []).append(r)
    apagar, pulados = [], []
    for g in plano["mesclar"]:
        linhas = por_numero.get(g["numero"], [])
        if len(linhas) == 1 + len(g["sai"]) and all(
                _foto(agora, r, largura) == foto for r, foto in zip(linhas[1:], g["sai"])):
            apagar.extend(linhas[1:])
        else:
            pulados.append(g["numero"])
    if apagar:
        sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
            {"deleteDimension": {"range": {"sheetId": tab["sheetId"], "dimension": "ROWS",
                                           "startIndex": r, "endIndex": r + 1}}}
            for r in sorted(apagar, reverse=True)]}).execute()
    print(f"{len(plano['mesclar']) - len(pulados)} número(s) mesclado(s), {len(apagar)} linha(s) apagada(s); "
          f"{len(pulados)} pulado(s) por terem mudado no meio{': ' + ', '.join(pulados) if pulados else ''}.")
    return 2 if pulados else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Mescla as indicações repetidas (simula por padrão)")
    p.add_argument("--aplicar", default="", metavar="HASH", help="Faz a mescla simulada com este hash")
    p.add_argument("--detalhe", action="store_true", help="Lista números e motivos (só localmente)")
    args = p.parse_args()
    sheet_id = os.environ.get("SHEET_ID", "")
    if not sheet_id:
        raise EnvironmentError("Defina SHEET_ID.")
    drive, sheets = (planilha.com_retentativa(s, index._executar) for s in index._google_services())
    if args.aplicar:
        return aplicar(drive, sheets, sheet_id, args.aplicar)
    sheets = planilha.somente_leitura(sheets)
    plano = simular(ler(sheets, sheet_id))
    _resumo(plano, args.detalhe)
    print(f"\nHash da simulação: {hash_plano(plano)}\n"
          f"Para aplicar: mesclar_indicacoes.py --aplicar {hash_plano(plano)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
