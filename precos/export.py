# -*- coding: utf-8 -*-
"""precos.sqlite + consultas curadas → precos-index.json + precos/dados/<slug>.json.

Estatística deliberadamente modesta: com 5 a 15 observações por item, média e
desvio-padrão são teatro. Aqui só saem mediana, mínimo, máximo, `n` e o número
de cidades distintas — e abaixo de 3 observações a comparação nem manchete tem.

Três regras que o export impõe e que nenhuma consulta pode afrouxar:

  1. **Base única.** O preço de Santos e o de todos os pares vêm da mesma base
     (homologado ou estimado). Cruzar as duas inventaria economia inexistente.
  2. **Toda observação carrega a URL da fonte no PNCP.** Número sem link não
     é publicado.
  3. **O denominador aparece.** "avaliados 214 · 9 comparáveis · 205 descartados"
     com os motivos agregados — sem isso a comparação é indistinguível de
     cherry-picking.

Uso:
  python precos/export.py --dry-run
  python precos/export.py
"""
import argparse
import glob
import json
import os
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casar  # noqa: E402
import crawler  # noqa: E402
import fontes  # noqa: E402
import ipca as ipca_mod  # noqa: E402

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(DIR)
SAIDA = os.path.join(RAIZ, "precos-index.json")
DADOS = os.path.join(DIR, "dados")
IPCA = os.path.join(DIR, "ipca.json")

N_MINIMO_MEDIANA = 3   # abaixo disso: referências pontuais, sem manchete
N_MIN_QUARTIS = 8      # abaixo disso: quartil é ruído com cara de precisão
N_MIN_EXTRAPOLACAO = 5
CIDADES_MIN_EXTRAPOLACAO = 3

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _nome_cidade(ibge):
    return next((c[1] for c in fontes.CIDADES if c[0] == ibge),
                "Santos" if ibge == fontes.IBGE_SANTOS else ibge)


def _carregar_ipca():
    try:
        with open(IPCA, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _corrigir(serie_ipca, valor, data, base_mes):
    """Valor corrigido pelo IPCA, ou None se faltar qualquer ponta da série."""
    if not (serie_ipca and valor and data):
        return None
    f = ipca_mod.fator(serie_ipca, data[:7], base_mes)
    return round(valor * f, 4) if f else None


def _observacao(conn, a, base, serie_ipca, base_mes):
    c = conn.execute("SELECT * FROM contratacao WHERE ncp=?", (a["ncp"],)).fetchone()
    return {
        "cidade": _nome_cidade(a["ibge"]),
        "ibge": a["ibge"],
        "orgao": c["razao_social"],
        "descricao": a["descricao"],          # original, nunca a normalizada
        "quantidade": a["quantidade"],
        "unidade_original": a["unidade_medida"],
        "fator": a["_fator"],
        "preco": round(a["_preco"], 4),
        "preco_corrigido": _corrigir(serie_ipca, a["_preco"], a["_data"], base_mes),
        "data": a["_data"],
        "fornecedor": a["_forn"],
        "documento_fornecedor": a["_ni"],
        "srp": bool(c["srp"]),
        "modalidade": c["modalidade_nome"],
        "confianca": a["_conf"],
        "jaccard": round(a["_j"], 3),
        "ncp": a["ncp"],
        "numero_item": a["numero_item"],
        "url": fontes.url_publica(c["cnpj"], c["ano"], c["sequencial"]),
    }


def _estatistica(obs, base_mes):
    precos = sorted(o["preco"] for o in obs)
    n = len(precos)
    cidades = {o["ibge"] for o in obs}
    corrigidos = [o["preco_corrigido"] for o in obs if o["preco_corrigido"]]
    d = {
        "n": n, "n_cidades": len(cidades),
        "mediana": round(statistics.median(precos), 4) if n else None,
        "min": precos[0] if n else None, "max": precos[-1] if n else None,
        "mediana_corrigida": (round(statistics.median(corrigidos), 4)
                              if len(corrigidos) == n and n else None),
        "base_correcao": base_mes if len(corrigidos) == n and n else None,
        "data_min": min((o["data"] for o in obs if o["data"]), default=None),
        "data_max": max((o["data"] for o in obs if o["data"]), default=None),
        "q1": None, "q3": None,
    }
    if n >= N_MIN_QUARTIS:
        q = statistics.quantiles(precos, n=4)
        d["q1"], d["q3"] = round(q[0], 4), round(q[2], 4)
    return d


def _preco_santos(conn, ref, base, fator_ref):
    """Preço da âncora já na unidade canônica.

    `fator_ref` nunca pode ser None aqui — `casar.casar()` aborta a comparação
    antes. Se chegasse, dividir por 1 publicaria o preço da caixa como preço da
    unidade (erro de 100×), então falha alto em vez de degradar em silêncio.
    """
    if not fator_ref or fator_ref <= 0:
        raise SystemExit("ABORTANDO: fator da âncora ausente — bug de casar.casar()")
    if base == "homologado":
        ph = casar.preco_homologado(conn, ref["ncp"], ref["numero_item"])
        if not ph:
            return None, None, None
        return ph[0] / fator_ref, ph[1], ph[2]
    c = conn.execute("SELECT data_publicacao FROM contratacao WHERE ncp=?",
                     (ref["ncp"],)).fetchone()
    v = ref["valor_unitario_estimado"]
    return ((v / fator_ref) if v else None,
            (c["data_publicacao"] if c else None), None)


def montar_comparacao(conn, q, serie_ipca, base_mes):
    r = casar.casar(conn, q)
    if r.get("erro"):
        return None, r["erro"]

    base, ref = r["base"], r["ref"]
    p_santos, d_santos, f_santos = _preco_santos(conn, ref, base, r["fator_ref"])
    if not p_santos or p_santos <= 0:
        return None, "preço de Santos ausente (rode --santos e o Tier 3)"

    obs = [_observacao(conn, a, base, serie_ipca, base_mes)
           for a in r["aceitos_detalhe"] if a["_preco"]]
    obs.sort(key=lambda o: (o["preco"], o["cidade"]))
    est = _estatistica(obs, base_mes)

    modo = "mediana" if est["n"] >= N_MINIMO_MEDIANA else "referencias_pontuais"
    mediana = est["mediana"]
    delta = razao = None
    if modo == "mediana" and mediana:
        razao = round(p_santos / mediana, 3)
        delta = round(100 * (p_santos / mediana - 1), 1)

    economia = None
    if (modo == "mediana" and mediana and p_santos > mediana
            and est["n"] >= N_MIN_EXTRAPOLACAO
            and est["n_cidades"] >= CIDADES_MIN_EXTRAPOLACAO):
        economia = round((p_santos - mediana) * (ref["quantidade"] or 0), 2)

    contr = conn.execute("SELECT * FROM contratacao WHERE ncp=?",
                         (ref["ncp"],)).fetchone()
    santos = {
        "preco": round(p_santos, 4), "base": base, "data": d_santos,
        "fornecedor": f_santos, "quantidade": ref["quantidade"],
        "unidade_original": ref["unidade_medida"], "descricao": ref["descricao"],
        "numero_item": ref["numero_item"], "ncp": ref["ncp"],
        "orgao": contr["razao_social"] if contr else "MUNICIPIO DE SANTOS",
        "objeto": contr["objeto"] if contr else None,
        "modalidade": contr["modalidade_nome"] if contr else None,
        "processo": contr["processo"] if contr else None,
        "preco_corrigido": _corrigir(serie_ipca, p_santos, d_santos, base_mes),
        "url": (fontes.url_publica(contr["cnpj"], contr["ano"], contr["sequencial"])
                if contr else None),
    }

    confs = [o["confianca"] for o in obs]
    # A entrada do índice fica ENXUTA: descrição e objeto do item somam ~450 B
    # por comparação e só aparecem no detalhe. O índice é baixado pelo cartão do
    # hub e pela paleta ⌘K em toda visita — peso ali é peso pago por todo mundo.
    santos_leve = {k: v for k, v in santos.items()
                   if k not in ("descricao", "objeto", "processo", "modalidade",
                                "orgao", "numero_item", "ncp")}
    resumo = {
        "slug": q["slug"], "titulo": q.get("titulo"), "tema": q.get("tema"),
        "unidade": q.get("unidade_canonica"), "base": base,
        "santos": santos_leve, "pares": est, "delta_pct": delta, "razao": razao,
        "economia_se_mediana": economia,
        "confianca_min": ("media" if "media" in confs else "alta") if confs else None,
        "modo": modo, "avaliados": r["avaliados"], "descartados": r["descartados"],
        "cidades": sorted({o["cidade"] for o in obs}),
        "publicada_em": q.get("publicada_em"),
        "arquivo": f"./precos/dados/{q['slug']}.json",
    }

    detalhe = {
        "slug": q["slug"], "titulo": q.get("titulo"), "tema": q.get("tema"),
        "base": base, "unidade": q.get("unidade_canonica"),
        "santos": santos, "pares": est, "delta_pct": delta, "razao": razao,
        "economia_se_mediana": economia, "modo": modo,
        "observacoes": obs,
        "avaliados": r["avaliados"], "descartados": r["descartados"],
        "motivos_descarte": dict(sorted(r["motivos"].items(), key=lambda kv: -kv[1])),
        "regras": {
            "termos": q.get("termos"), "unidade_canonica": q.get("unidade_canonica"),
            "material_ou_servico": q.get("material_ou_servico"), "srp": q.get("srp"),
            "faixa_quantidade": q.get("faixa_quantidade"),
            "janela_meses": q.get("janela_meses"), "modalidades": q.get("modalidades"),
            "correcao": q.get("correcao"),
        },
        "revisao": q.get("revisao"),
        "nota_metodologica": q.get("nota_metodologica"),
    }
    return (resumo, detalhe), None


def cobertura(conn):
    d = {"modalidades": sorted(fontes.MODALIDADES),
         "modalidades_nome": [fontes.MODALIDADES[m] for m in sorted(fontes.MODALIDADES)]}
    linha = conn.execute(
        "SELECT MIN(data_publicacao), MAX(data_publicacao) FROM contratacao "
        "WHERE data_publicacao <> '' AND ibge <> ?", (fontes.IBGE_SANTOS,)).fetchone()
    d["de"], d["ate"] = (linha[0] or "")[:7], (linha[1] or "")[:7]
    d["contratacoes"] = conn.execute(
        "SELECT COUNT(*) FROM contratacao WHERE ibge <> ?",
        (fontes.IBGE_SANTOS,)).fetchone()[0]
    # itens e resultados contam só as cidades-par: o rodapé do painel anuncia a
    # cobertura DO ESPELHO, e Santos entra por consulta curada, não por varredura
    d["itens"] = conn.execute(
        "SELECT COUNT(*) FROM item i JOIN contratacao c ON c.ncp=i.ncp "
        "WHERE c.ibge <> ?", (fontes.IBGE_SANTOS,)).fetchone()[0]
    d["resultados"] = conn.execute(
        "SELECT COUNT(*) FROM resultado r JOIN contratacao c ON c.ncp=r.ncp "
        "WHERE c.ibge <> ?", (fontes.IBGE_SANTOS,)).fetchone()[0]
    d["itens_pendentes"] = conn.execute(
        "SELECT COUNT(*) FROM contratacao WHERE itens_status='pendente'").fetchone()[0]
    d["por_cidade"] = {}
    for r in conn.execute(
            "SELECT c.ibge, COUNT(DISTINCT c.ncp) nc, COUNT(i.ncp) ni "
            "FROM contratacao c LEFT JOIN item i ON i.ncp=c.ncp "
            "WHERE c.ibge <> ? GROUP BY 1 ORDER BY 1", (fontes.IBGE_SANTOS,)):
        d["por_cidade"][r[0]] = {"nome": _nome_cidade(r[0]),
                                 "contratacoes": r[1], "itens": r[2]}
    return d


def _resumo(comparacoes):
    """Narrativa determinística, sem IA — mesmo padrão dos demais painéis."""
    pub = [c for c in comparacoes if c["modo"] == "mediana"]
    if not pub:
        return ("Nenhuma comparação reuniu observações suficientes para uma mediana "
                "até agora.")
    acima = [c for c in pub if (c["delta_pct"] or 0) > 0]
    if not acima:
        return (f"Nas {len(pub)} comparações com mediana, Santos pagou igual ou abaixo "
                "da mediana das cidades-par em todas.")
    pior = max(acima, key=lambda c: c["razao"] or 0)
    return (f"Em {len(acima)} de {len(pub)} comparações com mediana, Santos pagou acima "
            f"da mediana das cidades-par. A maior diferença é "
            f"\"{pior['titulo']}\": {pior['razao']:.1f}× a mediana de "
            f"{pior['pares']['n']} preços em {pior['pares']['n_cidades']} cidades.")


def main():
    ap = argparse.ArgumentParser(description="Export do painel Preço comparado")
    ap.add_argument("--dry-run", action="store_true", help="imprime sem gravar")
    args = ap.parse_args()

    conn = crawler.conectar()
    ipca_d = _carregar_ipca()
    serie = (ipca_d or {}).get("serie")
    base_mes = (ipca_d or {}).get("base")
    if not serie:
        print("AVISO — ipca.json ausente; coluna corrigida sai vazia", file=sys.stderr)

    comparacoes, detalhes, avisos = [], [], []
    for q in casar.carregar_consultas():
        if not q.get("publicada"):
            print(f"  {q['slug']}: rascunho (publicada=false), fora do índice")
            continue
        par, erro = montar_comparacao(conn, q, serie, base_mes)
        if erro:
            avisos.append(f"{q['slug']}: {erro}")
            continue
        resumo, detalhe = par
        comparacoes.append(resumo)
        detalhes.append(detalhe)
        print(f"  {resumo['slug']}: Santos R$ {resumo['santos']['preco']:,.2f}/"
              f"{resumo['unidade']} · n={resumo['pares']['n']} "
              f"({resumo['pares']['n_cidades']} cidades) · modo {resumo['modo']}"
              + (f" · {resumo['razao']:.2f}× a mediana" if resumo["razao"] else ""))

    comparacoes.sort(key=lambda c: (-(c["razao"] or 0), c["slug"]))
    indice = {
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": "Portal Nacional de Contratações Públicas (PNCP) — API de consulta",
        "ipca": {"fonte": (ipca_d or {}).get("fonte"), "base": base_mes},
        "cidades": [{"ibge": i, "nome": n, "pop": p} for i, n, p in fontes.CIDADES],
        "cobertura": cobertura(conn),
        "temas": sorted({c["tema"] for c in comparacoes if c.get("tema")}),
        "comparacoes": comparacoes,
        "resumo": _resumo(comparacoes),
    }

    # ── guardas: preferir não publicar a publicar número frágil ──────────────
    for c in comparacoes:
        if not c["santos"]["preco"] or c["pares"]["n"] < 1:
            raise SystemExit(f"ABORTANDO: {c['slug']} sem preço de Santos ou sem par")
    for d in detalhes:
        if any(not o.get("url") for o in d["observacoes"]):
            raise SystemExit(f"ABORTANDO: {d['slug']} tem observação sem URL de fonte")

    for a in avisos:
        print(f"AVISO — {a}", file=sys.stderr)

    if args.dry_run:
        print(f"[dry-run] {len(comparacoes)} comparações · "
              f"{indice['cobertura']['contratacoes']} contratações espelhadas · "
              f"{indice['cobertura']['itens']} itens")
        print(f"[dry-run] resumo: {indice['resumo']}")
        return

    os.makedirs(DADOS, exist_ok=True)
    for d in detalhes:
        with open(os.path.join(DADOS, f"{d['slug']}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    for orfao in glob.glob(os.path.join(DADOS, "*.json")):
        if os.path.splitext(os.path.basename(orfao))[0] not in {d["slug"] for d in detalhes}:
            os.remove(orfao)
            print(f"  removido shard órfão: {os.path.basename(orfao)}")
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    kb = os.path.getsize(SAIDA) / 1024
    print(f"gravado: precos-index.json ({kb:.1f} KB) · {len(detalhes)} shards")
    if kb > 100:
        print(f"AVISO — índice passou de 100 KB ({kb:.0f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
