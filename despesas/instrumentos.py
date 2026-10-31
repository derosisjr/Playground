#!/usr/bin/env python3
"""
Contratos, convênios, emendas e ordem cronológica — outras operações da API do Portal TP
=========================================================================================

A API da Prefeitura tem 88 operações; a base de despesas usa 3 (empenhos, liquidações e
pagamentos). Esta coleta acrescenta, sem passar pelo SQLite (cada resposta é a fotografia
do ano/mês na origem):

  - contratos (json_contratos, por ano de assinatura, 2019→corrente) e contratos
    emergenciais (json_contratos_emergenciais) → despesas/contratos/NN.json, por
    CNPJ (NN = 2 primeiros dígitos: o raio-X baixa só a fatia do favorecido). Usos: raio-X,
    etiqueta do fracionamento, coluna "Contratos" do ranking;
  - convênios firmados (json_convenios_firmados, mensal; só existem desde 2025) → o mesmo
    arquivo, por CNPJ do participante (OSCs);
  - emendas parlamentares (json_emendas_parlamentares, por ano) → despesas/emendas.json
    (a API de pagamentos não traz a ação orçamentária: dá para LISTAR as emendas, não para
    acompanhar a execução de cada uma);
  - ordem cronológica (json_ordem_cronologica): só o monitor. Vazia na API e na página do
    portal (ordemCronologicaGpi.aspx) para 2024–2026, conferido em 2026-10-30.

Só contratos com CNPJ: os de pessoa física (CPF mascarado na origem; em geral locação de
imóvel, objeto com endereço) ficam fora por cautela, contados no resumo.
Conferido em 2026-10-30 e deixado de fora: json_convenios traz o documento como o texto
"CNPJ" (sem número nem nome); json_orcamento_despesas soma R$ 11,2 bi para 2026 contra
R$ 6,3 bi de dotação no RREO (o orçamento vem do SICONFI — orcamento.py);
json_programa_acao só tem as 7 entidades (não há secretaria); json_obras é uma lista
genérica de pagamentos.

Falha de coleta em qualquer ano/mês de um bloco mantém os arquivos anteriores daquele
bloco (nunca publica pela metade). Mesmo dado = mesmos bytes (tudo ordenado).

Uso:
    python despesas/instrumentos.py              # coleta e grava
    python despesas/instrumentos.py --dry-run    # mostra o resumo sem gravar
"""

import argparse
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz do repo: comum/
from comum import http  # noqa: E402
from comum.escrita import gravar_json  # noqa: E402
from comum.saida import configurar_stdio  # noqa: E402

configurar_stdio()

API = "https://santos-sp.portaltp.com.br/api/transparencia.asmx"
HEADERS = {"User-Agent": "GabineteSantos/1.0 (+https://github.com/derosisjr/Playground)"}   # = crawler
UG_EXCLUIR = "DEMONSTRA"     # entidade-demonstração da plataforma (ver crawler.py)
ANO_CONTRATOS = 2019         # contratos assinados desde então (os vigentes no mandato)
ANO_INICIAL = 2025           # emendas, convênios firmados e ordem cronológica: o mandato
PAUSA = 0.4
OBJETO_MAX = 300
AQUI = os.path.dirname(os.path.abspath(__file__))
# FORA de despesas/dados/: lá o export apaga todo .json que não é dele (exportar_detalhe_mensal)
CONTRATOS_DIR = os.path.join(AQUI, "contratos")
EMENDAS_PATH = os.path.join(AQUI, "emendas.json")
RESUMO_PATH = os.path.join(AQUI, "instrumentos.json")
# página "Ordem Cronológica dos Pagamentos" (ordemCronologicaGpi.aspx, renderiza no navegador):
# conferida à mão — vazia para a Prefeitura em 2024, 2025 e 2026 (todos os meses)
PAGINA_OC_CONFERIDA = "2026-10-30"
CAMPOS_CONTRATO = ["contrato", "processo", "assinatura", "valor", "situacao", "categoria", "objeto", "tipo"]
CAMPOS_CONVENIO = ["convenio", "data", "valor", "tipo", "objeto"]
CAMPOS_EMENDA = ["numero", "origem", "autor", "funcao", "subfuncao", "descricao", "valor"]


class Falha(Exception):
    """Uma operação não respondeu: o bloco inteiro mantém a versão anterior."""


def operacao(op: str, **params) -> list[dict]:
    try:
        r = http.get(f"{API}/{op}", params, tentativas=3, passo=5, timeout=180, headers=HEADERS)
        bruto = html.unescape(ET.fromstring(r.content).text or "").strip()
        dados = json.loads(bruto) if bruto else []
    except Exception as e:  # noqa: BLE001 — rede, XML ou JSON: o chamador decide
        raise Falha(f"{op} {params}: {type(e).__name__}: {str(e)[:120]}") from e
    finally:
        time.sleep(PAUSA)
    dados = dados if isinstance(dados, list) else []
    return [d for d in dados if isinstance(d, dict)
            and UG_EXCLUIR not in json.dumps(d, ensure_ascii=False).upper()]


def cnpj(doc) -> str | None:
    d = re.sub(r"\D", "", str(doc or ""))
    return d if len(d) == 14 else None


def txt(s, limite: int | None = None) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if not limite or len(s) <= limite else s[:limite - 1].rstrip() + "…"


def valor(v) -> float:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


def coletar_contratos(hoje: date) -> tuple[dict, dict]:
    """{cnpj: [linha]} e o resumo (por ano, PF omitidos, sem documento)."""
    por_cnpj, por_ano, pf, sem_doc = defaultdict(list), {}, 0, 0
    for ano in range(ANO_CONTRATOS, hoje.year + 1):
        regs = operacao("json_contratos", ano=ano)
        por_ano[str(ano)] = len(regs)
        for c in regs:
            k = cnpj(c.get("documento_favorecido"))
            if not k:
                pf += "*" in str(c.get("documento_favorecido") or "")
                sem_doc += "*" not in str(c.get("documento_favorecido") or "")
                continue
            por_cnpj[k].append([txt(c.get("contrato")), txt(c.get("processo")), str(c.get("assinatura") or "")[:10],
                                valor(c.get("valor")), txt(c.get("situacao")), txt(c.get("categoria")),
                                txt(c.get("objeto"), OBJETO_MAX), "contrato"])
        for c in operacao("json_contratos_emergenciais", ano=ano):
            k = cnpj(c.get("documento"))
            if k:
                vig = f"vigência {str(c.get('inicio') or '')[:10]} a {str(c.get('termino') or '')[:10]}"
                por_cnpj[k].append([txt(c.get("contrato")), txt(c.get("processo")), str(c.get("assinatura") or "")[:10],
                                    valor(c.get("valor")), vig, txt(c.get("modalidade")),
                                    txt(c.get("objeto"), OBJETO_MAX), "emergencial"])
    return por_cnpj, {"desde": ANO_CONTRATOS, "por_ano": por_ano, "pf_omitidos": pf, "sem_documento": sem_doc}


def coletar_convenios(hoje: date) -> tuple[dict, dict]:
    por_cnpj, por_ano = defaultdict(list), Counter()
    for ano in range(ANO_INICIAL, hoje.year + 1):
        for mes in range(1, 13 if ano < hoje.year else hoje.month + 1):
            for c in operacao("json_convenios_firmados", ano=ano, mes=mes):
                por_ano[str(ano)] += 1
                k = cnpj(c.get("documento_participante"))
                if k:
                    por_cnpj[k].append([txt(c.get("nome_convenio")), str(c.get("data") or "")[:10],
                                        valor(c.get("valor")), txt(c.get("tipo_convenio")),
                                        txt(c.get("historico"), OBJETO_MAX)])
    return por_cnpj, {"desde": ANO_INICIAL, "por_ano": dict(sorted(por_ano.items()))}


def coletar_emendas(hoje: date) -> tuple[dict, dict]:
    por_ano, resumo = {}, {}
    for ano in range(ANO_INICIAL, hoje.year + 1):
        linhas = [[txt(e.get("numero")), txt(e.get("origem")), txt(e.get("autor")) or None, txt(e.get("funcao")),
                   txt(e.get("subfuncao")), txt(e.get("descricao"), OBJETO_MAX), valor(e.get("valor"))]
                  for e in operacao("json_emendas_parlamentares", ano=ano)]
        linhas.sort(key=lambda l: (l[2] is None, l[2] or "", l[0], l[5], l[6]))
        por_ano[str(ano)] = linhas
        origem = Counter(l[1] for l in linhas)
        resumo[str(ano)] = {"emendas": len(linhas), "valor": round(sum(l[6] for l in linhas), 2),
                            "por_origem": dict(sorted(origem.items())),
                            "sem_autor": sum(1 for l in linhas if not l[2])}
    return por_ano, resumo


def ordem_cronologica(hoje: date) -> dict:
    return {str(a): len(operacao("json_ordem_cronologica", ano=a)) for a in range(ANO_INICIAL - 1, hoje.year + 1)}


def estado_ordem(registros: dict, anterior: dict | None, hoje: date) -> dict:
    """`desde` = quando o estado atual (registros por ano) foi visto pela 1ª vez — sem
    carimbo diário: o arquivo só muda quando a origem muda."""
    anterior = anterior or {}
    return {"registros": registros,
            "desde": anterior.get("desde") if anterior.get("registros") == registros else hoje.isoformat(),
            "pagina": "https://santos-sp.portaltp.com.br/consultas/despesas/ordemCronologicaGpi.aspx",
            "pagina_conferida_em": PAGINA_OC_CONFERIDA}


def _ordenar(por_cnpj_c: dict, por_cnpj_v: dict) -> dict:
    """{prefixo: {cnpj: {"c": [...], "v": [...]}}} — tudo ordenado (mesmo dado, mesmos bytes)."""
    fatias = defaultdict(dict)
    for k in sorted(set(por_cnpj_c) | set(por_cnpj_v)):
        item = {}
        if por_cnpj_c.get(k):
            item["c"] = sorted({json.dumps(l, ensure_ascii=False): l for l in por_cnpj_c[k]}.values(),
                               key=lambda l: (l[2] or "", l[0], l[1], l[7]), reverse=True)
        if por_cnpj_v.get(k):
            item["v"] = sorted({json.dumps(l, ensure_ascii=False): l for l in por_cnpj_v[k]}.values(),
                               key=lambda l: (l[1] or "", l[0]), reverse=True)
        fatias[k[:2]][k] = item
    return fatias


def gravar_fatias(fatias: dict, diretorio: str = CONTRATOS_DIR) -> int:
    os.makedirs(diretorio, exist_ok=True)
    validos = {f"{p}.json" for p in fatias}
    for nome in os.listdir(diretorio):
        if nome.endswith(".json") and nome not in validos:
            os.remove(os.path.join(diretorio, nome))
    for p, mapa in sorted(fatias.items()):
        gravar_json(os.path.join(diretorio, f"{p}.json"),
                    {"versao": 1, "campos_contrato": CAMPOS_CONTRATO, "campos_convenio": CAMPOS_CONVENIO,
                     "cnpj": mapa}, separators=(",", ":"))
    return len(fatias)


def ler_resumo(caminho: str = RESUMO_PATH) -> dict:
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    p = argparse.ArgumentParser(description="Contratos, convênios, emendas e ordem cronológica (Portal TP)")
    p.add_argument("--dry-run", action="store_true", help="Mostra o resumo; não grava.")
    args = p.parse_args()
    hoje = date.today()
    resumo = {**ler_resumo(), "versao": 1}
    gravar = {}

    try:
        contratos, r_contr = coletar_contratos(hoje)
        convenios, r_conv = coletar_convenios(hoje)
        fatias = _ordenar(contratos, convenios)
        resumo["contratos"] = {**r_contr, "cnpjs": len(contratos), "total": sum(len(v) for v in contratos.values())}
        resumo["convenios_firmados"] = {**r_conv, "cnpjs": len(convenios)}
        gravar["contratos"] = fatias
    except Falha as e:
        print(f"Contratos/convênios: {e} — mantidos os arquivos anteriores.", file=sys.stderr)
    try:
        emendas, r_em = coletar_emendas(hoje)
        resumo["emendas"] = r_em
        gravar["emendas"] = emendas
    except Falha as e:
        print(f"Emendas: {e} — mantido o arquivo anterior.", file=sys.stderr)
    try:
        resumo["ordem_cronologica"] = estado_ordem(ordem_cronologica(hoje), resumo.get("ordem_cronologica"), hoje)
    except Falha as e:
        print(f"Ordem cronológica: {e} — mantido o estado anterior.", file=sys.stderr)

    print(json.dumps({k: v for k, v in resumo.items() if k != "versao"}, ensure_ascii=False, indent=1), file=sys.stderr)
    if args.dry_run:
        print("[dry-run] nada gravado.", file=sys.stderr)
        return
    if "contratos" in gravar:
        n = gravar_fatias(gravar["contratos"])
        print(f"contratos: {n} fatias em {os.path.relpath(CONTRATOS_DIR, AQUI)}/", file=sys.stderr)
    if "emendas" in gravar:
        gravar_json(EMENDAS_PATH, {"versao": 1, "campos": CAMPOS_EMENDA, "anos": gravar["emendas"]},
                    separators=(",", ":"))
    gravar_json(RESUMO_PATH, resumo, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
