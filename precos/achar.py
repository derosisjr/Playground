# -*- coding: utf-8 -*-
"""Achar o ITEM de Santos que vira âncora de uma comparação — 100% offline.

Antes desta ferramenta, criar uma comparação começava por DESCOBRIR o
`numeroControlePNCP` de um pregão de Santos, e não havia como fazer isso senão
varrendo a API por objeto (lento e sujeito a estrangulamento). Aqui a porta de
entrada é o item: digite "papel a4" e veja o que Santos comprou, com preço,
unidade e uma estimativa de quantos pares existem — tudo do espelho local, sem
uma requisição sequer.

Duas coisas que esta ferramenta deliberadamente NÃO faz:

  - **não sugere termos de busca.** A tentação é óbvia e o resultado é ruim:
    ordenar os tokens da descrição por raridade sugere `chico`, `gema`,
    `rabello` para "perito técnico para apuração de imóveis na Travessa Gema
    Rabello, bairro Chico de Paula" — nome de rua e de bairro são sempre os
    tokens mais raros. O rascunho nasce com `termos` VAZIOS, para o curador
    escrever.
  - **não publica.** O rascunho sai com `publicada: false`, e `--gravar` recusa
    sobrescrever arquivo existente.

O que ela FAZ de heurístico é ranquear a busca por posição na descrição, e isso
é indispensável: procurar `agulha` sem ranquear devolve cinco máquinas de
costura entre os oito primeiros de 119 resultados (a palavra aparece no fundo do
spec), e até um fogão industrial. O nome do produto está no começo da descrição.

Uso:
  python precos/achar.py papel a4
  python precos/achar.py agulha --limite 15 --ano 2026 --tudo
  python precos/achar.py papel a4 --item 3
  python precos/achar.py papel a4 --rascunho 3 --gravar --tema Administrativo
"""
import argparse
import collections
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casar  # noqa: E402
import crawler  # noqa: E402
import export  # noqa: E402
import fontes  # noqa: E402
import texto  # noqa: E402
import unidades  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Faixas do ranqueamento, em caracteres da descrição normalizada. O PNCP escreve
# "TÍTULO - Especificação: <spec longo>"; o produto está no título.
REL_TITULO_TOKENS = 4     # rel 3: todos os termos nos N primeiros tokens
REL_CABECALHO = 90        # rel 2: dentro do cabeçalho
REL_CORPO = 240           # rel 1: ainda perto do começo

# "caixa com 100 unidades", "cx c/100 un", "resma com 500 folhas"
_CONTAGEM = re.compile(
    r"(?:caixa|cx|pacote|pct|saco|sc|fardo|fd|embalagem|emb|frasco|fr|resma|"
    r"envelope|env|bloco|bl|rolo|rl)\s*(?:com|c)?\s*"
    r"([\d.,]+)\s*"
    r"(?:un|und|unid|unidade|unidades|pc|pecas?|folhas?|fl|comprimidos?|panos?)")


def _numero(bruto: str):
    """'1.000'→1000 · '100'→100 · '2.5'→None (contagem fracionária não existe).

    `texto.normalizar` já trocou a vírgula decimal por ponto, então '5,000' e
    '5.000' chegam idênticos aqui — daí a regra ser posicional (3 dígitos após o
    ponto = milhar) e não pelo separador.
    """
    t = bruto.strip(".,")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        return int(t.replace(".", ""))
    if re.fullmatch(r"\d+", t):
        return int(t)
    return None


# Famílias em que a unidade JÁ é a grandeza final. Se o item é vendido por
# 'UNI' e a descrição menciona "caixa com 100 unidades", os 100 são só a
# embalagem de entrega — propor conversão ali dividiria o preço por 100 sem
# motivo. A contagem só vale quando a unidade cobrada É a embalagem.
_FAMILIAS_FINAIS = {"contagem", "massa", "volume", "comprimento", "area"}


def contagem_declarada(descricao_norm: str, unidade=None):
    """Quantidade por embalagem declarada na descrição, ou None.

    `unidade` é obrigatória na prática: sem ela não há como saber se a contagem
    encontrada descreve a unidade cobrada ou apenas como o produto vem embalado.
    """
    if unidade is not None:
        can, _ = unidades.normalizar_unidade(unidade)
        if can is None or unidades.FAMILIA.get(can) in _FAMILIAS_FINAIS:
            return None
    m = _CONTAGEM.search(descricao_norm or "")
    if not m:
        return None
    n = _numero(m.group(1))
    return n if (n and n > 1) else None


def relevancia(descricao_norm: str, termos: list[str]) -> int:
    """3 = título · 2 = cabeçalho · 1 = perto do começo · 0 = fundo do spec."""
    if not all(texto.contem(descricao_norm, t) for t in termos):
        return -1
    inicio = " ".join((descricao_norm or "").split()[:REL_TITULO_TOKENS])
    if all(texto.contem(inicio, t) for t in termos):
        return 3
    if all(texto.contem(descricao_norm[:REL_CABECALHO], t) for t in termos):
        return 2
    if all(texto.contem(descricao_norm[:REL_CORPO], t) for t in termos):
        return 1
    return 0


def buscar(conn, termos, ano=None, desde=None):
    """Itens de Santos que contêm todos os termos, com relevância calculada."""
    sql = ("SELECT i.*, c.data_publicacao, c.modalidade_nome, c.cnpj, c.ano, "
           "c.sequencial, c.objeto FROM item i JOIN contratacao c ON c.ncp=i.ncp "
           "WHERE c.ibge=?")
    args = [fontes.IBGE_SANTOS]
    if ano:
        sql += " AND substr(c.data_publicacao,1,4)=?"
        args.append(str(ano))
    if desde:
        sql += " AND c.data_publicacao >= ?"
        args.append(desde)
    achados = []
    for r in conn.execute(sql, args):
        rel = relevancia(r["descricao_norm"] or "", termos)
        if rel >= 0:
            achados.append(dict(r, _rel=rel))
    return achados


def preco_de(conn, item):
    """(valor, base, data, fornecedor) do item, preferindo o homologado."""
    ph = casar.preco_homologado(conn, item["ncp"], item["numero_item"])
    if ph:
        return ph[0], "homologado", ph[1], ph[2]
    v = item.get("valor_unitario_estimado")
    return (v, "estimado", (item.get("data_publicacao") or "")[:10], None) if v \
        else (None, None, None, None)


# ─────────────────────────── funil de pares potenciais ──────────────────────

def _consulta_provisoria(canonica, extra=None):
    """Consulta mínima só para reusar `casar.fator_para_canonica`."""
    return {"unidade_canonica": canonica, "conversoes_extra": extra or {}}


def funil(conn, pares, termos, canonica, base, extra=None):
    """Teto de pares comparáveis: A texto → B unidade → C preço → D cidades.

    É TETO, não previsão: não aplica `termos.excluir` (que o curador ainda não
    escreveu), nem confiança/contenção, nem o corte de outlier. Calibrado contra
    a única comparação publicada — com os termos curados da agulha dá
    7 → 7 → 4 · 3 cidades, exatamente os 4 aceitos do `casar.py`.
    """
    q = _consulta_provisoria(canonica, extra)
    cache = {}

    a = [x for x in pares
         if all(texto.contem(x["descricao_norm"] or "", t) for t in termos)]

    b, perdidos = [], collections.Counter()
    for x in a:
        u = x["unidade_medida"]
        if u not in cache:
            cache[u] = casar.fator_para_canonica(q, u)
        if cache[u]:
            b.append(x)
        else:
            perdidos[(u or "—").strip()] += 1

    c = []
    for x in b:
        sit = texto.sem_acento(x["situacao_item"] or "")
        if any(s in sit for s in
               (texto.sem_acento(y) for y in fontes.SITUACOES_ITEM_INVALIDAS)):
            continue
        if base == "homologado":
            if x["tem_resultado"]:
                c.append(x)
        elif (x["valor_unitario_estimado"] or 0) > 0:
            c.append(x)

    return len(a), len(b), len(c), len({x["ibge"] for x in c}), perdidos


# Acima disso o teto não é boa notícia: significa que os termos pegam meio
# catálogo. Ler "109 comparáveis" como "comparação pronta" seria o contrário do
# que o número diz — a curadoria ainda vai derrubar quase tudo.
TETO_SUSPEITO = 40


def veredicto(n, n_cidades) -> str:
    if n < export.N_MINIMO_MEDIANA:
        return (f"insuficiente para mediana (precisa {export.N_MINIMO_MEDIANA}; "
                f"sairia como referências pontuais)")
    if n > TETO_SUSPEITO:
        return (f"teto alto ({n}) — termos genéricos demais para concluir algo; "
                f"refine a busca antes de curar")
    if n >= export.N_MIN_EXTRAPOLACAO and n_cidades >= export.CIDADES_MIN_EXTRAPOLACAO:
        return "dá mediana e extrapolação"
    return (f"dá mediana; não dá extrapolação (precisa n≥{export.N_MIN_EXTRAPOLACAO} "
            f"e {export.CIDADES_MIN_EXTRAPOLACAO} cidades)")


def _brl(v, casas=4) -> str:
    return ("R$ " + f"{v:,.{casas}f}").replace(",", "X").replace(".", ",").replace("X", ".")


# ──────────────────────────────── apresentação ──────────────────────────────

def avisos_do_item(item, canonica, fator, contagem):
    av = []
    u = (item["unidade_medida"] or "").strip()
    if not item["unidade_norm"]:
        av.append(f"unidade {u!r} fora da tabela — sem conversoes_extra a consulta não roda")
    elif unidades.FAMILIA.get(item["unidade_norm"]) not in (
            "contagem", "massa", "volume", "comprimento", "area", None):
        if contagem:
            av.append(f"unidade {u!r} é embalagem sem contagem; a descrição declara "
                      f"{contagem} → conversoes_extra {{{u!r}: {contagem}}} sugerida "
                      f"(CONFERIR no edital)")
        else:
            av.append(f"unidade {u!r} é embalagem sem contagem e a descrição não "
                      f"declara — só casa com outra {item['unidade_norm']!r}")
    # bug conhecido de escala (ver .claude/rules/precos.md): unidade com contagem
    # embutida que normaliza para fator 1 publicaria o preço da embalagem
    nums = [_numero(x) for x in re.findall(r"[\d.,]+", texto.normalizar(u))]
    if any(n and n > 1 for n in nums) and fator == 1:
        av.append(f"suspeita de escala: {u!r} tem contagem > 1 mas normaliza para fator 1")
    if (item["material_ou_servico"] or "") == "S":
        av.append("item de serviço (S) — descrição costuma ser genérica; espere poucos pares")
    return av


def imprimir(conn, achados, pares, termos, limite, tudo):
    mostrados = [a for a in achados if tudo or a["_rel"] >= 2]
    mostrados = mostrados[:limite]
    print(f"\n=== achar: \"{' '.join(termos)}\" · {len(achados)} itens de Santos · "
          f"{len(mostrados)} exibidos ===\n")
    if not achados:
        print("  nada encontrado. Tente menos termos, ou --tudo para ver a cauda.\n")
        return
    for i, it in enumerate(mostrados, start=1):
        valor, base, data, forn = preco_de(conn, it)
        u = (it["unidade_medida"] or "—").strip()
        canonica = it["unidade_norm"] or "un"
        contagem = contagem_declarada(it["descricao_norm"] or "", u)
        extra = {u: contagem} if contagem else None
        fator = casar.fator_para_canonica(_consulta_provisoria(canonica, extra), u)

        preco = _brl(valor) if valor else "sem preço"
        qtd = f"{it['quantidade']:,.0f}".replace(",", ".")
        print(f"[{i:2d}] rel {it['_rel']} · {data or '—'} · {preco}/{u} "
              f"({base or '—'}) · {qtd} {u}")
        print(f"     {(it['descricao'] or '')[:96]}")
        print(f"     {it['ncp']}#{it['numero_item']} · {it['modalidade_nome']}")
        for a in avisos_do_item(it, canonica, fator, contagem):
            print(f"     ! {a}")

        na, nb, nc, ncid, perdidos = funil(
            conn, pares, termos, canonica, base or "homologado", extra)
        print(f"     pares (teto): {na} texto → {nb} unidade → {nc} com preço · "
              f"{ncid} cidades  [canônica {canonica!r}]")
        if perdidos:
            top = " · ".join(f"{u2} {n}" for u2, n in perdidos.most_common(6))
            print(f"       perdidos na unidade: {top}")
        print(f"     veredicto: {veredicto(nc, ncid)}")
        print()
    print("  teto — excluir/confiança/outlier ainda derrubam parte.")
    print("  aprofundar: --item N · gerar rascunho: --rascunho N [--gravar]\n")


def aprofundar(conn, item, pares, termos):
    print(f"\n=== item {item['ncp']}#{item['numero_item']} ===")
    print(item["descricao"] or "")
    print(f"\nobjeto da contratação: {(item['objeto'] or '')[:140]}")
    print(f"unidade: {item['unidade_medida']!r} → {item['unidade_norm']!r} "
          f"(fator {item['fator_canonico']}) · quantidade {item['quantidade']}")
    c = contagem_declarada(item["descricao_norm"] or "", item["unidade_medida"])
    print(f"contagem declarada na descrição: {c if c else '—'}")
    print(f"fonte: {fontes.url_publica(item['cnpj'], item['ano'], item['sequencial'])}")

    print("\n-- tokens da descrição (frequência no espelho) " + "-" * 30)
    df = collections.Counter()
    for r in conn.execute("SELECT descricao_norm FROM item"):
        for t in set((r[0] or "").split()):
            df[t] += 1
    toks = sorted(texto.tokens(item["descricao"]), key=lambda t: df.get(t, 0))
    print("   " + " · ".join(f"{t}({df.get(t,0)})" for t in toks[:24]))

    print("\n-- vizinhos textuais nas cidades-par " + "-" * 40)
    print("   (é daqui que saem os termos de EXCLUSÃO)")
    viz = collections.Counter()
    for x in pares:
        if all(texto.contem(x["descricao_norm"] or "", t) for t in termos):
            viz[" ".join((x["descricao"] or "").split()[:9])[:78]] += 1
    for d, n in viz.most_common(25):
        print(f"   {n:4d}x  {d}")
    print()


# ───────────────────────────────── rascunho ─────────────────────────────────

def montar_rascunho(item, termos, tema, slug):
    u = (item["unidade_medida"] or "").strip()
    contagem = contagem_declarada(item["descricao_norm"] or "", u)
    canonica = item["unidade_norm"] or "un"
    revisar = [
        "termos estão VAZIOS — escreva obrigatorios/algum_de e rode "
        "`casar.py --slug X --revisar`",
        "termos.excluir também vazio — use `achar.py ... --item N` para ver os "
        "vizinhos textuais e escolher as exclusões",
        f"unidade_canonica {canonica!r} derivada de {u!r} — confirmar",
    ]
    extra = {}
    if contagem:
        extra[u] = contagem
        revisar.append(
            f"conversoes_extra {{{u!r}: {contagem}}} foi LIDA da descrição — conferir "
            f"em CADA edital das cidades-par, a embalagem pode diferir")
    elif not item["unidade_norm"]:
        # unidade fora da tabela: não dá para saber a família, então NÃO se
        # propõe fator. Mas se a descrição declara uma contagem, o curador
        # precisa ver esse número — é o que costuma destravar a comparação.
        bruta = contagem_declarada(item["descricao_norm"] or "")
        revisar.append(
            f"unidade {u!r} não está na tabela de unidades — escreva conversoes_extra "
            + (f"à mão; a descrição menciona {bruta} (CONFERIR se é a contagem da "
               f"unidade cobrada ou só da embalagem de entrega)" if bruta
               else "à mão, ou a consulta não roda"))
    elif canonica not in ("un", "kg", "l", "m", "m2", "m3"):
        revisar.append(
            f"unidade {u!r} é embalagem sem contagem declarada — sem conversoes_extra "
            f"a comparação só casa com a mesma embalagem")
    digitos = [t for t in texto.tokens(item["descricao"]) if any(c.isdigit() for c in t)]
    if digitos:
        revisar.append(
            "tokens com dígito na descrição: " + ", ".join(sorted(digitos)[:8])
            + " — para virar gate, cole em numeros[]")
    if (item["material_ou_servico"] or "") == "S":
        revisar.append("item de SERVIÇO — descrições de serviço são genéricas; "
                       "espere poucos pares e termos difíceis")

    titulo = " ".join((item["descricao"] or "").split()[:9])[:80]
    return {
        "slug": slug,
        "titulo": titulo,
        "tema": tema,
        "publicada": False,
        "publicada_em": None,
        "santos": {
            "numero_controle_pncp": item["ncp"],
            "itens": [item["numero_item"]],
            "cnpj": None, "ano": None, "sequencial": None,
        },
        "unidade_canonica": canonica,
        "conversoes_extra": extra,
        "termos": {"obrigatorios": [], "algum_de": [], "excluir": []},
        "material_ou_servico": item["material_ou_servico"],
        "srp": None,
        "numeros": [],
        "faixa_quantidade": None,
        "janela_meses": 36,
        "modalidades": sorted(fontes.MODALIDADES),
        "cidades": None,
        "correcao": "ipca",
        "revisao": {"por": None, "em": None, "confirmados": [], "rejeitados": []},
        "rascunho": {
            "gerado_por": "precos/achar.py",
            "gerado_em": date.today().isoformat(),
            "termo_buscado": " ".join(termos),
            "revisar": revisar,
        },
        "nota_metodologica": "RASCUNHO — não publicada. Gerado por achar.py a partir "
                             "do item de Santos; termos e exclusões ainda não escritos.",
    }


def _slug_de(item, termos):
    base = "-".join(t for t in termos if t)[:34].strip("-")
    return f"{base or 'item'}-{item['ano']}"


# ─────────────────────────────────── CLI ────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Acha o item de Santos que vira âncora de uma comparação (offline)")
    ap.add_argument("termo", nargs="+", help="palavras do item, sem aspas")
    ap.add_argument("--limite", type=int, default=10)
    ap.add_argument("--ano", type=int)
    ap.add_argument("--desde", help="AAAA-MM-DD")
    ap.add_argument("--tudo", action="store_true", help="inclui rel<2 (menção no spec)")
    ap.add_argument("--item", type=int, metavar="N", help="aprofunda o candidato N")
    ap.add_argument("--rascunho", type=int, metavar="N", help="gera consulta do candidato N")
    ap.add_argument("--gravar", action="store_true", help="grava o rascunho em consultas/")
    ap.add_argument("--slug")
    ap.add_argument("--tema", default=None)
    args = ap.parse_args()

    termos = [texto.normalizar(t) for t in args.termo if texto.normalizar(t)]
    if not termos:
        raise SystemExit("informe ao menos um termo")

    conn = crawler.conectar()
    achados = buscar(conn, termos, args.ano, args.desde)
    pares = [dict(r) for r in conn.execute(
        "SELECT i.*, c.ibge FROM item i JOIN contratacao c ON c.ncp=i.ncp "
        "WHERE c.ibge<>?", (fontes.IBGE_SANTOS,))]

    # ordenação: relevância → teto de pares → data (o recente vale mais)
    achados.sort(key=lambda a: (-a["_rel"], (a["data_publicacao"] or "")), reverse=False)
    achados.sort(key=lambda a: -a["_rel"])

    visiveis = [a for a in achados if args.tudo or a["_rel"] >= 2]

    if args.item or args.rascunho:
        n = args.item or args.rascunho
        if not 1 <= n <= len(visiveis):
            raise SystemExit(f"candidato {n} fora da lista (1..{len(visiveis)})")
        item = visiveis[n - 1]
        if args.item:
            aprofundar(conn, item, pares, termos)
            return
        slug = args.slug or _slug_de(item, termos)
        d = montar_rascunho(item, termos, args.tema, slug)
        if not args.gravar:
            print(json.dumps(d, ensure_ascii=False, indent=2))
            print(f"\n[não gravado] use --gravar para escrever em "
                  f"precos/consultas/{slug}.json", file=sys.stderr)
            return
        alvo = os.path.join(crawler.CONSULTAS, f"{slug}.json")
        if os.path.exists(alvo):
            raise SystemExit(f"ABORTANDO: {alvo} já existe — escolha outro --slug")
        with open(alvo, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"gravado: {alvo}")
        print("  próximos passos: escreva os termos, depois")
        print(f"  python precos/casar.py --slug {slug} --revisar")
        return

    imprimir(conn, achados, pares, termos, args.limite, args.tudo)


if __name__ == "__main__":
    main()
