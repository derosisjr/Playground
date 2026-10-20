#!/usr/bin/env python3
"""Pré-cadastro (R5, out/2026): a linha de cada requerimento e indicação do mandato entra na
planilha assim que o pedido é protocolado na Câmara. Antes ela só entrava quando chegava
resposta, e a assessoria digitava o resto à mão — em 19/10/2026 faltavam 127 requerimentos
e 281 indicações, e o site subcontava os pedidos sem resposta.

Fonte: a listagem pública por autor (`camara.listar_autor`). Requerimentos: só o subtipo
"Requerimento" (a numeração é por subtipo — "Requerimento de Convite Nº 1/2026" é outro
pedido); indicações: todas.

A linha nova recebe só o que vem da Câmara — Número (canônico), Assunto (a ementa; a equipe
pode encurtar), "Ementa (Câmara)" (o texto oficial, que o site publica), Data da Sessão e
"Situação na Câmara" — e entra depois da última linha da aba, relida na hora
(`planilha.aplicar`). Secretaria, Bairro e observações seguem com a equipe. "Situação na
Câmara" é o espelho da listagem ("-" = ainda não votado; "Aprovado"; "Encaminhado") e é a
única coluna que o robô regrava quando muda: o prazo da Lei Orgânica só corre depois que o
pedido sai da Câmara (`prazos.enviado`).

Varredura diária: cada ano/tipo para depois de 2 páginas seguidas sem pedido novo nem
situação mudada; às segundas, ou na primeira vez, é completa (2025 até o ano corrente).

    python respostas-executivo/precadastro.py             # plano + conciliação, só leitura
    python respostas-executivo/precadastro.py --aplicar   # cria as linhas (1ª carga)

No robô diário (`index.py`) ele roda antes da busca de respostas, ligado pela variável do
repositório PRECADASTRO_ATIVO=true; desligado, só conta o que faria.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camara  # noqa: E402
import planilha  # noqa: E402

COL_EMENTA = "Ementa (Câmara)"
COL_SIT_CAMARA = "Situação na Câmara"
COLUNAS_NOVAS = [COL_EMENTA, COL_SIT_CAMARA]
PAGINAS_SEM_NOVIDADE = 2
TIPOS = (("Requerimento", camara.TIPO_REQUERIMENTO), ("Indicação", camara.TIPO_INDICACAO))


def _do_escopo(bloco: dict, tipo: str) -> bool:
    return bool(bloco.get("numero")) and (tipo == "Indicação" or bloco.get("subtipo") == "Requerimento")


def coletar(anos: list[str], conhecidos: dict[str, dict[str, str]], completo: bool,
            abas: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """(pedidos do escopo, pedidos de outro subtipo) do autor na Câmara.

    `conhecidos` = {aba: {número: "Situação na Câmara" gravada}}; `abas` = {tipo: aba}. Sem
    `completo`, cada ano/tipo para depois de PAGINAS_SEM_NOVIDADE páginas seguidas sem
    pedido novo nem situação mudada (a listagem vem do número maior para o menor)."""
    itens, fora = [], []
    for ano in anos:
        for tipo, codigo in TIPOS:
            aba = abas[tipo]
            seguidas = [0]

            def parar(blocos, aba=aba, tipo=tipo, seguidas=seguidas):
                if completo:
                    return False
                novidade = any(_do_escopo(b, tipo) and conhecidos[aba].get(b["numero"]) != b["situacao"]
                               for b in blocos)
                seguidas[0] = 0 if novidade else seguidas[0] + 1
                return seguidas[0] >= PAGINAS_SEM_NOVIDADE

            for b in camara.listar_autor(ano, codigo, parar=parar):
                (itens if _do_escopo(b, tipo) else fora).append({**b, "aba": aba, "tipo": tipo})
    return itens, fora


def planejar(itens: list[dict], conhecidos: dict[str, dict[str, str]]) -> tuple[list, list]:
    """(linhas novas, atualizações do espelho "Situação na Câmara")."""
    novas, espelho, vistos = [], [], set()
    for it in itens:
        aba, num = it["aba"], it["numero"]
        if (aba, num) in vistos:
            continue
        vistos.add((aba, num))
        situacao = (it.get("situacao") or "").strip()
        if num not in conhecidos[aba]:
            ementa = (it.get("ementa") or "").strip()
            novas.append(planilha.NovaLinha(aba, num, {
                "Assunto": ementa, COL_EMENTA: ementa, "Data da Sessão": it.get("data", ""),
                COL_SIT_CAMARA: situacao}))
        elif situacao and conhecidos[aba][num] != situacao:
            espelho.append(planilha.Escrita(aba, num, {COL_SIT_CAMARA: situacao}))
    return novas, espelho


def _palavras(texto: str) -> set[str]:
    vazias = {"INDICA", "AO", "EXECUTIVO", "A", "O", "OS", "AS", "DE", "DA", "DO", "DAS", "DOS",
              "NA", "NO", "E", "EM", "QUE", "PARA", "COM", "OFICIAR", "SOLICITANDO", "SEJA", "SEJAM"}
    return set(re.sub(r"[^A-Z0-9]+", " ", planilha._sem_acento(texto).upper()).split()) - vazias


def conciliar(itens: list[dict], fora: list[dict], na_planilha: dict[str, dict[str, str]]) -> list[dict]:
    """Números da planilha que, na Câmara, são de OUTRO subtipo ou não aparecem entre os
    pedidos do autor, com o provável número certo pela ementa. Só relatório: nada é mudado.
    `na_planilha` = {aba: {número: assunto}} (precisa da varredura completa)."""
    do_autor = {(it["aba"], it["numero"]) for it in itens}
    outro_subtipo = {(it["aba"], it["numero"]): it["subtipo"] for it in fora}
    faltando = {}
    for it in itens:
        if it["numero"] not in na_planilha[it["aba"]]:
            faltando.setdefault(it["aba"], []).append(it)
    achados = []
    for aba, linhas in na_planilha.items():
        for num, assunto in linhas.items():
            if (aba, num) in do_autor:
                continue
            motivo = (f"na Câmara é {outro_subtipo[(aba, num)]}" if (aba, num) in outro_subtipo
                      else "não aparece entre os pedidos do autor")
            p = _palavras(assunto)
            melhor = max(faltando.get(aba, []), default=None,
                         key=lambda it: len(p & _palavras(it.get("ementa", ""))) / max(1, len(p)))
            nota = len(p & _palavras(melhor.get("ementa", ""))) / max(1, len(p)) if melhor else 0
            achados.append({"aba": aba, "numero": num, "motivo": motivo,
                            "provavel": melhor["numero"] if melhor and nota >= 0.5 else ""})
    return achados


def main() -> int:
    import index  # aqui dentro: o index importa este módulo
    p = argparse.ArgumentParser(description="Pré-cadastro dos pedidos do mandato (simula por padrão)")
    p.add_argument("--aplicar", action="store_true", help="Cria as linhas (e as colunas, se faltarem)")
    p.add_argument("--detalhe", action="store_true", help="Lista números (só localmente)")
    args = p.parse_args()
    sheet_id = os.environ.get("SHEET_ID", "")
    if not sheet_id:
        raise EnvironmentError("Defina SHEET_ID.")
    _, sheets = (planilha.com_retentativa(s, index._executar) for s in index._google_services())
    if not args.aplicar:
        sheets = planilha.somente_leitura(sheets)
    else:
        for aba in index.ABAS:
            index.garantir_colunas(sheets, sheet_id, aba, index.COLUNAS_CLASSIFICACAO + COLUNAS_NOVAS)
    indice = index.carregar_planilha(sheets, sheet_id)
    conhecidos = {aba: {n: x.get("sit_camara", "") for n, x in info["mapa"].items()} for aba, info in indice.items()}
    abas = {"Requerimento": index.ABA_REQUERIMENTOS, "Indicação": index.ABA_INDICACOES}
    itens, fora = coletar(index.anos_do_mandato(), conhecidos, True, abas)
    novas, espelho = planejar(itens, conhecidos)
    rel = planilha.aplicar(sheets, sheet_id, novas + espelho, gravar=args.aplicar)
    por_aba = {}
    for aba, _, _ in rel.novas:
        por_aba[aba] = por_aba.get(aba, 0) + 1
    verbo = "criadas" if args.aplicar else "a criar"
    print(f"{len(itens)} pedido(s) do autor na Câmara; linhas {verbo}: {por_aba or 0}; "
          f"\"{COL_SIT_CAMARA}\" {'acertada' if args.aplicar else 'a acertar'} em "
          f"{len(rel.escritas)} linha(s) existente(s).")
    na_planilha = {aba: {n: x.get("assunto", "") for n, x in info["mapa"].items()} for aba, info in indice.items()}
    achados = conciliar(itens, fora, na_planilha)
    print(f"Conciliação: {len(achados)} número(s) da planilha que não batem com a Câmara.")
    for a in achados if args.detalhe else []:
        print(f"  {a['aba']} {a['numero']}: {a['motivo']}"
              f"{' — provável ' + a['provavel'] if a['provavel'] else ''}")
    if args.detalhe:
        for aba, num, linha in rel.novas:
            print(f"  nova: {aba} {num} (linha {linha})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
