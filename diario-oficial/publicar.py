#!/usr/bin/env python3
"""
Publicador — grava na planilha os atos classificados pela IA e avisa os assessores
==================================================================================

Passo 3 do pipeline da rotina /schedule:
    dom_md.py (PDF→MD) → skill dom-santos (MD→JSON) → publicar.py (JSON→Sheets+e-mail)

Determinístico de ponta a ponta:
  - **Dedup pela planilha** (fonte da verdade — a rotina em nuvem não persiste nada
    entre execuções): lê as linhas existentes e insere só o que falta. Chave estável:
    Data DO | Categoria | Tipo de Ato | Nº | Órgão/Secretaria (campos estáveis; nunca
    texto livre como Objeto, que a IA redige diferente entre execuções).
  - **Inserção no TOPO** (linha 2), com a leva ordenada por risco (🔴 > 🟡 > 🟢) —
    o mais crítico fica na linha mais alta.
  - **Status = "Novo"**: coluna de trabalho da equipe; linhas existentes nunca são
    tocadas (a dedup impede regravação).
  - **E-mail por último**, e só se houver ato novo (mesmo briefing do monitor.py).

Uso:
    python diario-oficial/publicar.py atos.json                   # grava + e-mail
    python diario-oficial/publicar.py atos.json --dry-run         # só imprime
    python diario-oficial/publicar.py atos.json --sem-email       # grava sem e-mail

Ambiente: DOM_SHEET_ID, GOOGLE_OAUTH_TOKEN (e GMAIL_* p/ o e-mail).
JSON de entrada: lista de atos no contrato da skill (.claude/skills/dom-santos):
    numero, data_do, categoria, tipo_ato, orgao, objeto, valor, partes,
    base_legal, nivel_atencao, observacoes, acao_sugerida, pagina
"""

import argparse
import json
import os
import sys

import extrator
import sheets as gsheets

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ORDEM_RISCO = {"🔴": 0, "🟡": 1, "🟢": 2}


def _norm(s) -> str:
    return " ".join(str(s or "").split()).upper()


def chave(data_do: str, categoria: str, tipo: str, numero: str, orgao: str) -> str:
    """Chave estável da dedup (independe de texto livre e da ordem das linhas)."""
    return "|".join(_norm(x) for x in (data_do, categoria, tipo, numero, orgao))


def chaves_existentes(linhas: list[dict]) -> set[str]:
    """Chaves das linhas já na planilha (dicts de sheets.ler_existentes)."""
    return {
        chave(l.get("Data DO", ""), l.get("Categoria", ""), l.get("Tipo de Ato", ""),
              l.get("Nº", ""), l.get("Órgão/Secretaria", ""))
        for l in linhas
    }


def linha_planilha(ato: dict, sep: str) -> list:
    """Ato (contrato da skill) → linha na ordem de sheets.COLUNAS."""
    data_do = ato.get("data_do", "")
    data_cell = gsheets.hyperlink(extrator.url_edicao(data_do), data_do, sep)
    return [
        ato.get("numero", ""), data_cell, ato.get("categoria", ""),
        ato.get("tipo_ato", ""), ato.get("orgao", ""), ato.get("objeto", ""),
        ato.get("valor", ""), ato.get("partes", ""), ato.get("base_legal", ""),
        ato.get("nivel_atencao", ""), ato.get("observacoes", ""),
        ato.get("acao_sugerida", ""), "Novo", ato.get("pagina", ""),
    ]


def _para_email(ato: dict) -> dict:
    """Adapta o ato ao formato esperado por monitor.montar_email_html/enviar_email."""
    return {
        "risco": ato.get("nivel_atencao", ""), "categoria": ato.get("categoria", ""),
        "tipo": ato.get("tipo_ato", ""), "secretaria": ato.get("orgao", ""),
        "objeto": ato.get("objeto", ""), "valor": ato.get("valor", ""),
        "numero": ato.get("numero", ""), "data_edicao": ato.get("data_do", ""),
        "motivo": ato.get("observacoes", ""),
    }


def main():
    p = argparse.ArgumentParser(description="Publica atos classificados pela IA na planilha do DOM")
    p.add_argument("json_path", nargs="?", help="Arquivo JSON com os atos (contrato da skill dom-santos).")
    p.add_argument("--dry-run", action="store_true", help="Não grava; imprime o que faria.")
    p.add_argument("--sem-email", action="store_true", help="Grava sem enviar e-mail.")
    p.add_argument("--listar-edicoes", action="store_true",
                   help="Só imprime as datas de edição já presentes na planilha (pré-check "
                        "da rotina: edição já processada não precisa ser analisada de novo).")
    args = p.parse_args()

    if args.listar_edicoes:
        sheet_id = os.environ.get("DOM_SHEET_ID", "")
        if not sheet_id:
            sys.exit("Defina DOM_SHEET_ID.")
        sheets = gsheets.conectar_sheets()
        gsheets.garantir_aba(sheets, sheet_id)
        datas = sorted({l.get("Data DO", "") for l in gsheets.ler_existentes(sheets, sheet_id)} - {""})
        print("\n".join(datas))
        return
    if not args.json_path:
        p.error("informe o JSON de atos (ou use --listar-edicoes)")

    with open(args.json_path, encoding="utf-8") as f:
        atos = json.load(f)
    if not isinstance(atos, list):
        sys.exit("JSON inválido: esperado uma lista de atos.")

    # validação mínima do contrato (campos essenciais presentes)
    obrigatorios = ("data_do", "categoria", "tipo_ato", "nivel_atencao")
    invalidos = [a for a in atos if not all(a.get(c) for c in obrigatorios)]
    if invalidos:
        sys.exit(f"{len(invalidos)} ato(s) sem campos obrigatórios {obrigatorios}; abortando. "
                 f"Exemplo: {json.dumps(invalidos[0], ensure_ascii=False)[:200]}")

    sheet_id = os.environ.get("DOM_SHEET_ID", "")
    if not sheet_id and not args.dry_run:
        sys.exit("Defina DOM_SHEET_ID (planilha de destino).")

    if args.dry_run:
        print(f"{len(atos)} ato(s) no JSON:")
        for a in sorted(atos, key=lambda a: _ORDEM_RISCO.get(a.get("nivel_atencao", "🟢"), 3)):
            print(f"  {a.get('nivel_atencao','')} [{a.get('categoria','')}/{a.get('tipo_ato','')}] "
                  f"nº {a.get('numero','')} | {a.get('orgao','')[:24]} | {a.get('objeto','')[:60]}")
        return

    sheets = gsheets.conectar_sheets()
    gsheets.garantir_aba(sheets, sheet_id)
    sep = gsheets.separador_formula(sheets, sheet_id)

    existentes = chaves_existentes(gsheets.ler_existentes(sheets, sheet_id))
    novos = []
    for a in atos:
        k = chave(a.get("data_do", ""), a.get("categoria", ""), a.get("tipo_ato", ""),
                  a.get("numero", ""), a.get("orgao", ""))
        if k not in existentes:
            existentes.add(k)  # dedup também dentro do próprio JSON
            novos.append(a)

    if not novos:
        print("Nenhum ato novo — planilha já em dia; e-mail não enviado.", file=sys.stderr)
        return

    # mais crítico na linha mais alta (mesma ordem do e-mail)
    novos.sort(key=lambda a: _ORDEM_RISCO.get(a.get("nivel_atencao", "🟢"), 3))
    gsheets.inserir_no_topo(sheets, sheet_id, [linha_planilha(a, sep) for a in novos])
    print(f"{len(novos)} ato(s) novo(s) inserido(s) no topo "
          f"({len(atos) - len(novos)} já existiam).", file=sys.stderr)

    if not args.sem_email:
        import monitor
        monitor.enviar_email([_para_email(a) for a in novos], sheet_id)


if __name__ == "__main__":
    main()
