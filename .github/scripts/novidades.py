#!/usr/bin/env python3
"""Gera `novidades.json`: o que mudou nas bases desde a passada anterior (feed do site).

Por que existe: o hub mostra contagens e "atualizado há N dias", mas nada diz O QUE
mudou — qual requerimento foi respondido, que projeto entrou, que norma foi revogada.

Como funciona: compara cada índice com um RETRATO compacto da passada anterior,
guardado no próprio `novidades.json` (chave `retrato`), e acrescenta EVENTOS com
`visto_em` = data (UTC) em que este script viu a mudança pela 1ª vez — não é a data
do fato na origem (proposituras roda 2×/semana, legislação 1×).

Robustez:
- Sem retrato (1ª execução, ou base nova no retrato): só grava o retrato, sem
  eventos — senão o acervo inteiro viraria "novo". Idem quando um campo aparece pela
  1ª vez no índice (`vence_em` em requerimentos, `ua` em proposituras).
- Índice ausente/ilegível: pula a base com aviso em stderr, mantém o retrato e os
  eventos dela. Não derruba o workflow — quem reclama de índice é a guarda de frescor.
- Surto (mais de LIMITE_SURTO eventos de uma base numa passada) é troca de formato ou
  carga em massa, não novidade: o retrato é refeito e os eventos, descartados.
- Janela de JANELA_DIAS dias e teto de TETO_EVENTOS eventos (os mais novos).

Contrato do JSON: `.claude/rules/site-frontend.md`, seção "Novidades (feed)".

Uso:
    python .github/scripts/novidades.py            # grava novidades.json na raiz
    python .github/scripts/novidades.py --dry-run  # mostra os eventos novos, não grava
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from itertools import accumulate
from pathlib import Path
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.append(str(RAIZ))  # camada comum do repo (comum/)
from comum.escrita import gravar_texto  # noqa: E402
from comum.formato import compacto  # noqa: E402
from comum.saida import configurar_stdio  # noqa: E402

SAIDA = "novidades.json"
VERSAO_RETRATO = 1        # mudou o formato do retrato? suba: o antigo vira "sem retrato"
JANELA_DIAS = 60
TETO_EVENTOS = 400
LIMITE_SURTO = 200        # eventos de UMA base numa passada
TITULO_MAX = 140
AUTOR_MANDATO = "Rui Sergio Gomes de Rosis Junior"
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

# o que um índice (ou retrato) quebrado pode levantar: arquivo, JSON, formato inesperado
ERROS_DE_INDICE = (OSError, ValueError, TypeError, LookupError, AttributeError)


# ── utilitários ──────────────────────────────────────────────────────────────
def _evento(base, tipo, titulo, chave, link, mandato=False):
    """Evento na ordem do contrato (`visto_em` entra ao mesclar); `mandato` só se verdadeiro."""
    ev = {"base": base, "tipo": tipo, "titulo": titulo, "chave": chave, "link": link}
    if mandato:
        ev["mandato"] = True
    return ev


def _resumir(texto, limite=TITULO_MAX):
    """Espaços colapsados; acima do limite, corta na última palavra inteira + "…"."""
    t = " ".join(str(texto or "").split())
    if len(t) <= limite:
        return t
    corte = t[:limite - 1]  # reserva 1 caractere para o "…"
    if t[limite - 1] != " " and " " in corte:  # parou no meio de uma palavra
        corte = corte.rsplit(" ", 1)[0]
    return corte.rstrip(" ,;:.-–—") + "…"


def _titulo(cabeca, descricao=""):
    """'cabeça — descrição' em até TITULO_MAX caracteres (o fim é que encolhe)."""
    descricao = " ".join(str(descricao or "").split())
    return _resumir(f"{cabeca} — {descricao}" if descricao else cabeca)


def _data_br(texto):
    """'14/08/2026' → date; None no que não casar (vazio, lixo)."""
    try:
        d, m, a = str(texto).strip().split("/")
        return date(int(a), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _data_iso(texto):
    """'2026-08-14' → date; None no que não casar."""
    try:
        return date.fromisoformat(str(texto)[:10])
    except ValueError:
        return None


def _inteiro(valor):
    """cod/id do índice → int (None se não for número)."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _deltas(numeros):
    """Conjunto de inteiros → lista ORDENADA em diferenças (a 1ª é absoluta): ids
    vizinhos diferem por 1–3 dígitos em vez de 6."""
    saida, anterior = [], 0
    for n in sorted(numeros):
        saida.append(n - anterior)
        anterior = n
    return saida


def _de_deltas(deltas):
    return list(accumulate(int(d) for d in deltas))


def _novos_com_piso(itens, anterior, hoje):
    """Ids que estreiam no índice + o retrato {"piso", "ids"} que os detecta amanhã.

    `itens` = [(id, ano)]. Só os ids a partir do PISO — o menor id do ano corrente e do
    anterior — ficam guardados (proposituras: 1.074 de 7.097 cods; legislação: 489 de
    3.915). Id novo abaixo do piso da véspera é carga retroativa de acervo, não
    novidade, e não vira evento. Id que some do índice continua guardado: um índice
    parcial não faz ninguém "estrear" de novo no dia seguinte."""
    ant = anterior or {}
    piso_ant = int(ant.get("piso") or 0)
    conhecidos = set(_de_deltas(ant.get("ids") or []))
    ids = {i for i, _ in itens}
    recentes = [i for i, ano in itens if ano and ano >= hoje.year - 1]
    piso = min(recentes) if recentes else 0
    novos = set() if anterior is None else {i for i in ids if i >= piso_ant and i not in conhecidos}
    return novos, {"piso": piso, "ids": _deltas(i for i in ids | conhecidos if i >= piso)}


_EPOCA = date(2000, 1, 1)


def _ua_dias(ua):
    """'2026-10-15' → dias desde 2000-01-01 (ordena como a data, 4–5 dígitos); 0 se vazio."""
    d = _data_iso(ua) if ua else None
    return (d - _EPOCA).days if d else 0


# ── requerimentos ─────────────────────────────────────────────────────────────
# 419 de 623 assuntos começam por "Oficiar ao Executivo solicitando, nos termos do
# artigo 58, …" — fórmula que, cortada em 140 caracteres, não deixa ver o pedido.
_RE_ART58 = re.compile(r",?\s*nos termos do art(?:igo|\.)?\s*58\s*,?", re.I)
_RE_OFICIAR = re.compile(r"^oficiar ao (?:poder )?executivo\s*(?:solicitando|para que)?\s*", re.I)
_RE_MEIO = re.compile(r"^,?\s*em meio digital(?: ou f[íi]sico)?\s*,?\s*", re.I)


def _assunto_curto(assunto):
    t = " ".join(str(assunto or "").split())
    curto = " ".join(_RE_ART58.sub(" ", t).split())
    curto = _RE_MEIO.sub("", _RE_OFICIAR.sub("", curto)).lstrip(" ,;:-")
    return curto[:1].upper() + curto[1:] if curto else t


def comparar_requerimentos(doc, anterior, hoje):
    """resposta / prorrogacao / vencido.

    Retrato: `pendentes` = {numero: [situacao, vencido 0|1]} só de quem está SEM
    resposta de mérito (respondido sai — não há evento depois dele; número fora do
    retrato é tratado como novo e só entra no retrato, sem evento) e `prazo` = o
    índice trazia `vence_em` (sem isso, o dia em que o campo chega transformaria
    todo pedido atrasado em "vencido"). O `vencido` do retrato é "já anunciado":
    uma prorrogação que empurra o prazo não faz o pedido vencer de novo no feed."""
    if not isinstance(doc, list):
        raise ValueError("requerimentos-index.json não é uma lista")
    prazo = any(isinstance(r, dict) and "vence_em" in r for r in doc)
    ant = anterior or {}
    ant_pend, ant_prazo = ant.get("pendentes") or {}, bool(ant.get("prazo"))
    eventos, pendentes = [], {}
    for r in doc:
        if not isinstance(r, dict):
            continue
        numero = str(r.get("numero") or "").strip()
        if not numero:
            continue
        situacao = str(r.get("situacao") or "")
        respondido = situacao == "respondido" or bool(r.get("data_resposta_merito"))
        vence = _data_br(r.get("vence_em")) if prazo else None
        vencido = not respondido and vence is not None and vence < hoje
        visto = ant_pend.get(numero) if anterior is not None else None
        sit_ant, venc_ant = (str(visto[0]), bool(visto[1])) if visto else ("", False)

        if visto:
            sec = str(r.get("secretaria") or "").strip()
            ident = f"Requerimento {numero}" + (f" ({sec})" if sec else "")
            assunto = _assunto_curto(r.get("assunto"))
            link = f"requerimentos.html?n={quote(numero, safe='')}"
            fatos = []
            if respondido:
                fatos.append(("resposta", f"{ident} respondido"))
            elif situacao == "so_prorrogacao" and sit_ant != "so_prorrogacao":
                fatos.append(("prorrogacao", f"{ident}: Prefeitura pediu mais prazo"))
            if vencido and not venc_ant and ant_prazo:
                fatos.append(("vencido", f"{ident} sem resposta no prazo"))
            for tipo, cabeca in fatos:
                eventos.append(_evento("requerimentos", tipo, _titulo(cabeca, assunto),
                                       f"requerimentos:{tipo}:{numero}", link))
        if not respondido:
            pendentes[numero] = [situacao, int(vencido or venc_ant)]
    return eventos, {"prazo": prazo, "pendentes": pendentes}


# ── proposituras ──────────────────────────────────────────────────────────────
def _com_id(doc, campo):
    """[(id inteiro, item)] dos itens válidos de um índice em lista."""
    saida = []
    for item in doc:
        if isinstance(item, dict) and _inteiro(item.get(campo)) is not None:
            saida.append((_inteiro(item[campo]), item))
    return saida


def comparar_proposituras(doc, anterior, hoje):
    """nova / andamento.

    Retrato: `piso` + `ids` (cods, ver _novos_com_piso) e, só quando o índice traz
    `ua`, `tram` = {"ids": cods com tram=1 em deltas, "ua": o `ua` de cada um em dias
    desde 2000-01-01, alinhado} — todos os em tramitação, de qualquer ano. Andamento =
    `ua` mais recente num item que JÁ estava em tramitação na véspera; quem entra ou
    sai de tramitação não gera evento (com tram=0 o índice não traz `ua`)."""
    if not isinstance(doc, list):
        raise ValueError("proposituras-index.json não é uma lista")
    itens = _com_id(doc, "cod")
    novos, retrato = _novos_com_piso([(c, _inteiro(p.get("ano"))) for c, p in itens], anterior, hoje)
    ant_tram = (anterior or {}).get("tram")
    ua_ant = (dict(zip(_de_deltas(ant_tram.get("ids") or []), ant_tram.get("ua") or []))
              if isinstance(ant_tram, dict) else {})
    com_ua = any("ua" in p for _, p in itens)
    eventos, tram = [], {}
    for cod, p in itens:
        ua = str(p.get("ua") or "")
        andou = False
        if com_ua and p.get("tram") == 1 and "ua" in p:
            tram[cod] = _ua_dias(ua)
            andou = cod in ua_ant and tram[cod] > int(ua_ant[cod] or 0)
        if cod not in novos and not andou:
            continue
        especie = p.get("subtipo") or p.get("tipo") or "Propositura"
        ident = f"{especie} {p.get('numero') or '(cód. %d)' % cod}"
        if cod in novos:
            autor = str(p.get("autor") or "").strip()
            tipo, chave = "nova", f"proposituras:nova:{cod}"
            cabeca = f"Nova propositura: {ident}" + (f" ({autor})" if autor else "")
        else:
            local = " ".join(str(p.get("ual") or p.get("local_atual") or "").split())
            tipo, chave = "andamento", f"proposituras:andamento:{cod}:{ua}"
            cabeca = f"{ident}: novo andamento" + (f" ({local})" if local else "")
        eventos.append(_evento("proposituras", tipo, _titulo(cabeca, p.get("ementa")), chave,
                               f"proposituras.html?cod={cod}", mandato=p.get("autor") == AUTOR_MANDATO))
    if com_ua:
        ordem = sorted(tram)
        retrato["tram"] = {"ids": _deltas(ordem), "ua": [tram[c] for c in ordem]}
    return eventos, retrato


# ── legislação ────────────────────────────────────────────────────────────────
def _nome_norma(n):
    """'Lei n.º 4.804, de 05 de outubro' + ano (o título do Legis não traz o ano)."""
    nome = " ".join(str(n.get("titulo") or "").split()) or \
        f"{n.get('tipo') or 'Norma'} {n.get('numero') or ''}".strip()
    ano = n.get("ano")
    return f"{nome} de {ano}" if ano and str(ano) not in nome else nome


def comparar_legis(doc, anterior, hoje):
    """nova / revogada.

    Retrato: `piso` + `ids` (ver _novos_com_piso) e `revog` = TODOS os ids com "revog"
    na situação, de qualquer ano (revogação costuma cair em norma antiga). Norma que
    some do índice leva o estado anterior: índice parcial não "desrevoga" ninguém."""
    if not isinstance(doc, list):
        raise ValueError("legis-index.json não é uma lista")
    itens = _com_id(doc, "id")
    novos, retrato = _novos_com_piso([(i, _inteiro(n.get("ano"))) for i, n in itens], anterior, hoje)
    revog_ant = {int(i) for i in (anterior or {}).get("revog") or []}
    eventos, revog = [], set()
    for id_, n in itens:
        situacao = " ".join(str(n.get("situacao") or "").split()).lower()
        if "revog" in situacao:
            revog.add(id_)
        if anterior is None:
            continue
        link = f"legis.html?id={id_}"
        if id_ in novos:
            eventos.append(_evento("legis", "nova", _titulo(f"Nova norma: {_nome_norma(n)}", n.get("ementa")),
                                   f"legis:nova:{id_}", link))
        elif id_ in revog and id_ not in revog_ant:
            eventos.append(_evento("legis", "revogada", _titulo(f"Norma {situacao}: {_nome_norma(n)}"),
                                   f"legis:revogada:{id_}", link))
    revog |= revog_ant - {i for i, _ in itens}
    retrato["revog"] = sorted(revog)
    return eventos, retrato


# ── despesas ──────────────────────────────────────────────────────────────────
def _mes_ref(doc):
    """('aaaa-mm', valor pago) do último mês completo (`resumo.mes_ref`) ou (None, None)."""
    mr = (doc.get("resumo") or {}).get("mes_ref")
    if not isinstance(mr, dict):
        return None, None
    ano, mes = _inteiro(mr.get("ano")), _inteiro(mr.get("mes"))
    if not ano or not mes or not 1 <= mes <= 12:
        return None, None
    return f"{ano:04d}-{mes:02d}", mr.get("valor")


def comparar_despesas(doc, anterior, hoje):
    """alerta / alerta_resolvido / mes_fechado.

    Retrato: `alertas` = {id: título} dos alertas a conferir (classe ≠ contexto) — o
    título fica guardado porque o alerta resolvido já não está no índice para
    descrevê-lo — e `mes_ref` = 'aaaa-mm' do último mês completo."""
    if not isinstance(doc, dict) or not isinstance(doc.get("alertas"), list):
        raise ValueError("despesas-index.json sem a lista `alertas`")
    ant = anterior or {}
    ant_alertas = ant.get("alertas") if isinstance(ant.get("alertas"), dict) else {}
    atuais = {}
    for a in doc["alertas"]:
        if isinstance(a, dict) and a.get("id") and a.get("classe") != "contexto":
            atuais[str(a["id"])] = _resumir(a.get("titulo"), 110)
    mes, valor = _mes_ref(doc)
    mes_ant = ant.get("mes_ref")
    eventos = []
    if anterior is not None:
        for aid, titulo in atuais.items():
            if aid not in ant_alertas:
                eventos.append(_evento("despesas", "alerta", _titulo("Novo alerta de despesas", titulo),
                                       f"despesas:alerta:{aid}", "despesas.html#alertas"))
        for aid, titulo in ant_alertas.items():
            if aid not in atuais:
                eventos.append(_evento("despesas", "alerta_resolvido",
                                       _titulo("Alerta de despesas encerrado", titulo),
                                       f"despesas:alerta_resolvido:{aid}", "despesas.html#alertas"))
        if mes and mes_ant and mes > str(mes_ant):
            nome = f"{MESES[int(mes[5:]) - 1]} de {mes[:4]}"
            titulo = (f"Mês fechado: a Prefeitura pagou {compacto(valor)} em {nome}"
                      if isinstance(valor, (int, float)) else f"Mês fechado nas despesas: {nome}")
            eventos.append(_evento("despesas", "mes_fechado", _titulo(titulo),
                                   f"despesas:mes_fechado:{mes}", "despesas.html"))
    return eventos, {"alertas": atuais, "mes_ref": mes or mes_ant}


# ── montagem ──────────────────────────────────────────────────────────────────
BASES = [  # (nome no feed, índice, comparador) — a ordem é a dos eventos do mesmo dia
    ("requerimentos", "requerimentos-index.json", comparar_requerimentos),
    ("proposituras", "proposituras-index.json", comparar_proposituras),
    ("legis", "legis-index.json", comparar_legis),
    ("despesas", "despesas-index.json", comparar_despesas),
]


def ler_anterior(caminho):
    """(eventos, retrato) do novidades.json anterior; ([], None) se não houver.
    Retrato de outra VERSAO_RETRATO vale como ausente (os eventos ficam)."""
    if not caminho.exists():
        return [], None
    try:
        doc = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"  aviso: {caminho.name} ilegível ({e}) — recomeçando sem eventos", file=sys.stderr)
        return [], None
    if not isinstance(doc, dict):
        return [], None
    eventos = [e for e in doc.get("eventos") or [] if isinstance(e, dict)]
    retrato = doc.get("retrato")
    if not isinstance(retrato, dict) or retrato.get("versao") != VERSAO_RETRATO:
        retrato = None
    return eventos, retrato


def mesclar(antigos, novos, hoje):
    """Eventos antigos dentro da janela + novos com `visto_em` = hoje, sem repetir
    `chave` (vale o PRIMEIRO registro), do mais novo para o mais antigo, no teto.
    Devolve (feed, eventos novos que entraram nele)."""
    corte = hoje - timedelta(days=JANELA_DIAS)
    vistos, guardados = set(), []
    for ev in antigos:
        quando, chave = _data_iso(ev.get("visto_em")), ev.get("chave")
        if quando is None or quando <= corte or not isinstance(chave, str) or chave in vistos:
            continue
        vistos.add(chave)
        guardados.append(ev)
    frescos = []
    for ev in novos:
        if ev["chave"] not in vistos:
            vistos.add(ev["chave"])
            frescos.append({"visto_em": hoje.isoformat(), **ev})
    todos = frescos + guardados
    todos.sort(key=lambda e: e["visto_em"], reverse=True)  # estável: o dia mantém a ordem
    feed = todos[:TETO_EVENTOS]
    ids_frescos = {id(e) for e in frescos}
    return feed, [e for e in feed if id(e) in ids_frescos]


def _processar_base(raiz, nome, arquivo, comparar, anterior, hoje):
    """(eventos, retrato da base, retrato anterior usado). Levanta ERROS_DE_INDICE se
    o índice não serve. Retrato anterior que o comparador não entende (formato velho,
    arquivo editado à mão) é descartado: a base recomeça do zero, sem eventos."""
    doc = json.loads((raiz / arquivo).read_text(encoding="utf-8"))
    falha = None
    if anterior is not None:
        try:
            eventos, retrato = comparar(doc, anterior, hoje)
            return eventos, retrato, anterior
        except ERROS_DE_INDICE as e:
            falha = e
    eventos, retrato = comparar(doc, None, hoje)  # índice ruim levanta de novo aqui
    if falha is not None:
        print(f"  aviso: retrato de {nome} incompatível ({falha}) — refeito do zero", file=sys.stderr)
    return eventos, retrato, None


def gerar(agora=None):
    """Monta o novo documento a partir de RAIZ. Devolve (doc, situação por base, eventos novos)."""
    raiz = RAIZ
    agora = (agora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    hoje = agora.date()
    eventos_ant, retrato_ant = ler_anterior(raiz / SAIDA)
    retrato, situacao, novos = {"versao": VERSAO_RETRATO}, {}, []
    for nome, arquivo, comparar in BASES:
        anterior = (retrato_ant or {}).get(nome)
        try:
            evs, sec, anterior = _processar_base(raiz, nome, arquivo, comparar, anterior, hoje)
        except ERROS_DE_INDICE as e:
            # pula a base: eventos e retrato dela ficam como estavam
            print(f"  aviso: {nome} pulada ({arquivo}: {type(e).__name__}: {e})", file=sys.stderr)
            if anterior is not None:
                retrato[nome] = anterior
            situacao[nome] = "pulada (índice ausente ou ilegível)"
            continue
        retrato[nome] = sec
        if anterior is None:
            situacao[nome] = "retrato inicial (sem eventos)"
        elif len(evs) > LIMITE_SURTO:
            print(f"  aviso: {nome} gerou {len(evs)} eventos (> {LIMITE_SURTO}): troca de formato "
                  f"ou carga em massa — retrato refeito, eventos descartados", file=sys.stderr)
            situacao[nome] = f"surto: {len(evs)} eventos descartados"
        else:
            novos.extend(evs)
            situacao[nome] = None  # contado depois de mesclar (repetidos não entram)
    eventos, entraram = mesclar(eventos_ant, novos, hoje)
    for nome, sit in situacao.items():
        if sit is None:
            situacao[nome] = f"{sum(e['base'] == nome for e in entraram)} evento(s)"
    doc = {
        "gerado_em": agora.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "eventos": eventos,
        "retrato": retrato,
    }
    return doc, situacao, entraram


def serializar(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"


def executar(agora=None, gravar=True):
    """Gera, relata no stdout e (se `gravar`) grava RAIZ/novidades.json de forma atômica."""
    doc, situacao, novos = gerar(agora)
    texto = serializar(doc)
    for nome, sit in situacao.items():
        print(f"  {nome:14} {sit}")
    for ev in novos:
        print(f"  + [{ev['base']}/{ev['tipo']}] {ev['titulo']}")
    tamanho = f"{len(texto.encode('utf-8')):,}".replace(",", ".")
    resumo = f"{tamanho} bytes; {len(doc['eventos'])} eventos no feed, {len(novos)} visto(s) agora"
    if gravar:
        gravar_texto(RAIZ / SAIDA, texto)
        print(f"\ngravado {SAIDA} ({resumo})")
    else:
        print(f"\n--dry-run: {SAIDA} NÃO gravado ({resumo})")
    return doc, situacao, novos


def main():
    configurar_stdio()
    ap = argparse.ArgumentParser(description="Gera novidades.json (feed de mudanças nas bases).")
    ap.add_argument("--dry-run", action="store_true", help="mostra os eventos novos sem gravar")
    args = ap.parse_args()
    executar(gravar=not args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
