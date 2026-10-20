#!/usr/bin/env python3
"""Diagnóstico SOMENTE LEITURA da planilha de controle — a base de comparação antes de
qualquer mudança no robô (lote R0).

O que mede, por aba (`requerimentos`, `indicações`):
  - mapa das colunas: toda coluna com conteúdo (com ou sem título), quem é o dono
    (robô ou equipe) e quantas células estão preenchidas;
  - números fora do padrão e grupos de linhas com o mesmo número; nas linhas repetidas,
    quantas têm conteúdo da equipe, nota ou comentário (o que a mescla não pode perder);
  - linhas com pasta no Drive e sem situação, ou cuja pasta não tem PDF de resposta;
  - picos no `Log diário` (origem das linhas repetidas);
  - conciliação com a listagem pública da Câmara (pedidos do mandato que faltam na
    planilha, números da planilha que não são do autor ou são de outro subtipo).

Tudo passa por `planilha.somente_leitura`: uma tentativa de gravar levanta erro.
Saída padrão: só contagens (o log do Actions de repo público é público). `--detalhe` (uso
local) acrescenta números de pedido e linhas da planilha — nunca o texto das células.

    python respostas-executivo/diagnostico.py
    python respostas-executivo/diagnostico.py --sem-camara --sem-drive
    python respostas-executivo/diagnostico.py --detalhe --json /tmp/diagnostico.json
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from planilha import numero_canonico, somente_leitura  # noqa: E402

ABA_REQUERIMENTOS = "requerimentos"
ABA_INDICACOES = "indicações"
LOG_ABA = "Log diário"
# Colunas que o robô ATUALIZA em linha existente; e as que ele só preenche ao criar linha.
ROBO_ATUALIZA = ("Resposta", "Data da resposta", "Situação da resposta", "Data da resposta de mérito")
ROBO_CRIA = ("Número", "Assunto", "Data da Sessão")


def _sem_acento(s: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).strip().lower()


def dono_da_coluna(titulo: str) -> str:
    """'robô' (atualiza linha existente), 'robô na criação' (só ao criar linha) ou 'equipe'."""
    t = _sem_acento(titulo)
    if t in {_sem_acento(c) for c in ROBO_ATUALIZA}:
        return "robô"
    if t in {_sem_acento(c) for c in ROBO_CRIA}:
        return "robô na criação"
    return "equipe"


def _letra(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def mapa_colunas(valores: list[list]) -> list[dict]:
    """Toda coluna com título OU com conteúdo: letra, título, dono e células preenchidas."""
    if not valores:
        return []
    cab = valores[0]
    largura = max(len(l) for l in valores)
    colunas = []
    for c in range(largura):
        titulo = str(cab[c]).strip() if c < len(cab) else ""
        cheias = sum(1 for l in valores[1:] if c < len(l) and str(l[c]).strip())
        if not titulo and not cheias:
            continue
        colunas.append({
            "coluna": _letra(c), "titulo": titulo or "(sem título)",
            "dono": dono_da_coluna(titulo) if titulo else "equipe (sem título)",
            "preenchidas": cheias,
        })
    return colunas


def _idx(cab: list, nome: str) -> int:
    alvo = _sem_acento(nome)
    for i, h in enumerate(cab):
        if _sem_acento(h) == alvo:
            return i
    return -1


def idx_numero(cab: list) -> int:
    for i, h in enumerate(cab):
        if _sem_acento(h) == "numero":
            return i
    return -1


def pasta_id(formula: str) -> str | None:
    """ID da pasta do Drive numa célula `=HYPERLINK("https://drive.google.com/drive/folders/ID"…)`."""
    m = re.search(r"/folders/([\w-]{10,})", str(formula or ""))
    return m.group(1) if m else None


def analisar_aba(valores: list[list], notas: set[tuple[int, int]] | None = None,
                 comentarios_linhas: set[int] | None = None) -> dict:
    """Contagens de uma aba. `notas` = {(linha 1-based, coluna 0-based)} com nota;
    `comentarios_linhas` = linhas com comentário ancorado."""
    notas = notas or set()
    comentarios_linhas = comentarios_linhas or set()
    if not valores:
        return {"linhas": 0}
    cab = valores[0]
    i_num = idx_numero(cab)
    equipe = [c for c, h in enumerate(cab) if str(h).strip() and dono_da_coluna(h) == "equipe"]
    # colunas sem título com conteúdo também são da equipe
    largura = max(len(l) for l in valores)
    equipe += [c for c in range(len(cab), largura)]
    equipe += [c for c in range(len(cab)) if not str(cab[c]).strip()]
    equipe = sorted(set(equipe))

    def cel(linha, c):
        return str(linha[c]).strip() if 0 <= c < len(linha) else ""

    por_numero: dict[str, list[int]] = defaultdict(list)
    fora_do_padrao, sem_numero_com_conteudo = [], 0
    for n, linha in enumerate(valores[1:], start=2):
        bruto = cel(linha, i_num)
        canon = numero_canonico(bruto)
        if canon:
            por_numero[canon].append(n)
        elif bruto:
            fora_do_padrao.append((n, bruto))
        elif any(str(v).strip() for v in linha):
            sem_numero_com_conteudo += 1

    grupos = {k: v for k, v in por_numero.items() if len(v) > 1}
    repetidas = {"total": 0, "com_conteudo_da_equipe_diferente": 0,
                 "com_conteudo_da_equipe_so_nela": 0, "com_nota": 0, "com_comentario": 0,
                 "limpas": 0}
    detalhe_repetidas = []
    for numero, linhas in sorted(grupos.items()):
        mantida = valores[linhas[0] - 1]
        for n in linhas[1:]:
            linha = valores[n - 1]
            difere = [c for c in equipe if cel(linha, c) and cel(mantida, c) and cel(linha, c) != cel(mantida, c)]
            so_nela = [c for c in equipe if cel(linha, c) and not cel(mantida, c)]
            com_nota = any((n, c) in notas for c in range(largura))
            com_coment = n in comentarios_linhas
            repetidas["total"] += 1
            repetidas["com_conteudo_da_equipe_diferente"] += bool(difere)
            repetidas["com_conteudo_da_equipe_so_nela"] += bool(so_nela)
            repetidas["com_nota"] += com_nota
            repetidas["com_comentario"] += com_coment
            limpa = not difere and not com_nota and not com_coment
            repetidas["limpas"] += limpa
            detalhe_repetidas.append({"numero": numero, "mantida": linhas[0], "repetida": n,
                                      "colunas_diferentes": [_letra(c) for c in difere],
                                      "colunas_so_nela": [_letra(c) for c in so_nela],
                                      "nota": com_nota, "comentario": com_coment, "limpa": limpa})

    return {
        "linhas": len(valores) - 1,
        "colunas_alem_de_Z": max(0, largura - 26),
        "numeros_validos": sum(len(v) for v in por_numero.values()),
        "numeros_distintos": len(por_numero),
        "fora_do_padrao": len(fora_do_padrao),
        "sem_numero_com_conteudo": sem_numero_com_conteudo,
        "grupos_repetidos": dict(sorted(Counter(len(v) for v in grupos.values()).items())),
        "repetidas": repetidas,
        "notas": len(notas),
        "_detalhe": {"fora_do_padrao": fora_do_padrao, "repetidas": detalhe_repetidas,
                     "numeros": sorted(por_numero)},
    }


def analisar_pastas(valores_formula: list[list], pastas_com_resposta: set[str] | None) -> dict:
    """Linhas com pasta e sem situação; pastas sem PDF de resposta (se o Drive foi lido)."""
    if not valores_formula:
        return {}
    cab = valores_formula[0]
    i_resp, i_sit = _idx(cab, "Resposta"), _idx(cab, "Situação da resposta")
    i_num = idx_numero(cab)
    com_pasta = sem_situacao = sem_pdf = 0
    detalhe = []
    for n, linha in enumerate(valores_formula[1:], start=2):
        pid = pasta_id(linha[i_resp] if 0 <= i_resp < len(linha) else "")
        if not pid:
            continue
        com_pasta += 1
        sit = str(linha[i_sit]).strip() if 0 <= i_sit < len(linha) else ""
        sem_situacao += not sit
        vazia = pastas_com_resposta is not None and pid not in pastas_com_resposta
        sem_pdf += vazia
        if not sit or vazia:
            num = str(linha[i_num]).strip() if 0 <= i_num < len(linha) else ""
            detalhe.append({"linha": n, "numero": num, "sem_situacao": not sit, "sem_pdf": vazia})
    r = {"com_pasta": com_pasta, "com_pasta_sem_situacao": sem_situacao, "_detalhe": detalhe}
    if pastas_com_resposta is not None:
        r["pasta_sem_pdf_de_resposta"] = sem_pdf
    return r


def picos_log(valores: list[list], top: int = 5) -> dict:
    """Dias com mais linhas no Log diário, separados por tipo (a origem das repetidas de
    indicações some no meio dos ~570 requerimentos/dia reprocessados no começo de out/2026)."""
    if not valores:
        return {}
    cab = valores[0]
    i_data, i_tipo = _idx(cab, "Data processamento"), _idx(cab, "Tipo")
    por_tipo: dict[str, Counter] = defaultdict(Counter)
    for linha in valores[1:]:
        d = str(linha[i_data]).strip() if 0 <= i_data < len(linha) else ""
        m = re.search(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}", d)
        tipo = str(linha[i_tipo]).strip() if 0 <= i_tipo < len(linha) else ""
        por_tipo[tipo][m.group(0) if m else "?"] += 1
    return {"linhas": len(valores) - 1,
            "maiores_por_tipo": {t: [{"dia": d, "linhas": n} for d, n in c.most_common(top)]
                                 for t, c in sorted(por_tipo.items())}}


def conciliar(numeros_planilha: set[str], camara: list[dict], subtipo: str | None) -> dict:
    """Planilha × listagem da Câmara. `subtipo` = o que conta (ex.: 'Requerimento'); os demais
    subtipos do autor viram 'outro subtipo'. None = qualquer subtipo (indicações)."""
    alvo = {i["numero"] for i in camara if i["numero"] and (subtipo is None or i["subtipo"] == subtipo)}
    outros = defaultdict(set)
    for i in camara:
        if i["numero"] and subtipo is not None and i["subtipo"] != subtipo:
            outros[i["numero"]].add(i["subtipo"])
    faltam = alvo - numeros_planilha
    sobram = numeros_planilha - alvo
    situacao_das_que_faltam = Counter(i["situacao"] or "?" for i in camara
                                      if i["numero"] in faltam and (subtipo is None or i["subtipo"] == subtipo))
    return {
        "na_camara": len(alvo), "na_planilha": len(numeros_planilha),
        "faltam_na_planilha": len(faltam),
        "situacao_na_camara_das_que_faltam": dict(situacao_das_que_faltam.most_common()),
        "na_planilha_de_outro_subtipo": len([n for n in sobram if n in outros]),
        "na_planilha_nao_encontradas_no_autor": len([n for n in sobram if n not in outros]),
        "_detalhe": {"faltam": sorted(faltam, key=_chave_num),
                     "outro_subtipo": {n: sorted(outros[n]) for n in sorted(sobram, key=_chave_num) if n in outros},
                     "nao_encontradas": sorted([n for n in sobram if n not in outros], key=_chave_num)},
    }


def _chave_num(n: str) -> tuple:
    num, ano = n.split("/")
    return (int(ano), int(num))


# ── leitura (Google) ─────────────────────────────────────────────────────────
def ler_aba(sheets, sheet_id: str, aba: str, render: str = "FORMATTED_VALUE") -> list[list]:
    res = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{aba}'", valueRenderOption=render).execute()
    return res.get("values", [])


def ler_notas(sheets, sheet_id: str, aba: str) -> set[tuple[int, int]]:
    res = sheets.spreadsheets().get(
        spreadsheetId=sheet_id, ranges=[f"'{aba}'"], includeGridData=True,
        fields="sheets(data(rowData(values(note))))").execute()
    notas = set()
    for sh in res.get("sheets", []):
        for bloco in sh.get("data", []):
            for r, row in enumerate(bloco.get("rowData", []) or [], start=1):
                for c, v in enumerate(row.get("values", []) or []):
                    if v.get("note"):
                        notas.add((r, c))
    return notas


def ler_comentarios(drive, sheet_id: str) -> list[dict]:
    """Comentários (balões) da planilha via Drive. A âncora de comentário do Sheets não é
    documentada: o diagnóstico só conta e mostra se dá para localizar a linha."""
    coment, token = [], None
    while True:
        res = drive.comments().list(
            fileId=sheet_id, pageSize=100, pageToken=token, includeDeleted=False,
            fields="nextPageToken,comments(id,anchor,resolved)").execute()
        coment.extend(res.get("comments", []))
        token = res.get("nextPageToken")
        if not token:
            return coment


def pastas_com_pdf_de_resposta(drive) -> set[str]:
    """Pastas (ids) que contêm algum RESPOSTA_*.pdf — uma consulta paginada no Drive todo."""
    pastas, token = set(), None
    while True:
        res = drive.files().list(
            q="name contains 'RESPOSTA_' and trashed = false and mimeType != 'application/vnd.google-apps.folder'",
            fields="nextPageToken, files(parents)", pageSize=1000, pageToken=token,
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        for f in res.get("files", []):
            pastas.update(f.get("parents", []))
        token = res.get("nextPageToken")
        if not token:
            return pastas


def _sem_detalhe(d):
    if isinstance(d, dict):
        return {k: _sem_detalhe(v) for k, v in d.items() if not k.startswith("_")}
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detalhe", action="store_true", help="números de pedido e linhas (uso local)")
    ap.add_argument("--sem-camara", action="store_true", help="não consulta a listagem da Câmara")
    ap.add_argument("--sem-drive", action="store_true", help="não lê o Drive (pastas e comentários)")
    ap.add_argument("--json", help="grava o resultado (com --detalhe, inclui as listas)")
    args = ap.parse_args()

    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        sys.exit("Defina SHEET_ID (e o token: GOOGLE_OAUTH_TOKEN ou token.json).")
    from index import _google_services
    drive, sheets = _google_services()
    drive, sheets = somente_leitura(drive), somente_leitura(sheets)

    comentarios = [] if args.sem_drive else ler_comentarios(drive, sheet_id)
    pastas = None if args.sem_drive else pastas_com_pdf_de_resposta(drive)
    resultado = {"gerado_em": date.today().isoformat(),
                 "comentarios_na_planilha": {"total": len(comentarios),
                                             "com_ancora": sum(1 for c in comentarios if c.get("anchor")),
                                             "abertos": sum(1 for c in comentarios if not c.get("resolved"))},
                 "abas": {}}
    numeros = {}
    for aba in (ABA_REQUERIMENTOS, ABA_INDICACOES):
        valores = ler_aba(sheets, sheet_id, aba)
        formulas = ler_aba(sheets, sheet_id, aba, "FORMULA")
        notas = ler_notas(sheets, sheet_id, aba)
        r = analisar_aba(valores, notas)
        r["colunas"] = mapa_colunas(valores)
        r["pastas"] = analisar_pastas(formulas, pastas)
        resultado["abas"][aba] = r
        numeros[aba] = set(r["_detalhe"]["numeros"])

    resultado["log_diario"] = picos_log(ler_aba(sheets, sheet_id, LOG_ABA))

    if not args.sem_camara:
        import camara
        anos = range(2025, date.today().year + 1)
        req = [i for a in anos for i in camara.listar_autor(a, camara.TIPO_REQUERIMENTO)]
        ind = [i for a in anos for i in camara.listar_autor(a, camara.TIPO_INDICACAO)]
        resultado["camara"] = {
            "requerimentos_por_subtipo": dict(Counter(i["subtipo"] for i in req).most_common()),
            "requerimentos": conciliar(numeros[ABA_REQUERIMENTOS], req, "Requerimento"),
            "indicacoes": conciliar(numeros[ABA_INDICACOES], ind, None),
        }

    saida = resultado if args.detalhe else _sem_detalhe(resultado)
    print(json.dumps(saida, ensure_ascii=False, indent=1, default=list))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(saida, f, ensure_ascii=False, indent=1, default=list)


if __name__ == "__main__":
    main()
