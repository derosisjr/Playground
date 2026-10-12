#!/usr/bin/env python3
"""
Crawler do Legis (Prefeitura de Santos) — índice enxuto (só metadados)
======================================================================

Varre o sistema Legis (`egov.santos.sp.gov.br/legis`) e indexa os METADADOS de
cada norma (tipo, número, ano, data, ementa, tags) + link para o PDF oficial,
gravando num SQLite. NÃO baixa o PDF nem extrai texto integral (ver plano).

Navegação:
  tipo:  /legis/topics/{T}/documents        (lista os anos como sub-tópicos)
  ano:   /legis/topics/{Y}/documents?page=N  (lista /legis/documents/{ID})
  norma: /legis/documents/{ID}               (h1 + badges = ementa/tags)
  PDF:   /legis/documents/{ID}/download

Encoding: páginas em latin-1, MAS alguns campos (ementa/tags) contêm UTF-8
"dentro" do latin-1 (double-encoding). Resolve-se decodificando a página como
latin-1 (1:1, sem sniffing) e reparando cada campo com `_fix`.

Uso:
    python legis/crawler.py --tipo 6 --ano 2024 --limite 5   # amostra
    python legis/crawler.py --tipo 6                          # um tipo inteiro
    python legis/crawler.py                                   # tudo (carga completa)
    python legis/crawler.py --forcar                          # reprocessa existentes
    python legis/crawler.py --ano 2026 --revisitar 1000       # + revisita 1000 já gravadas
    python legis/crawler.py --so-situacao                     # só recalcula situação (sem rede)

Situação (revogada / revogada parcialmente / alterada): o Legis não a publica;
é INFERIDA da ementa oficial (`descricao`) das normas posteriores — ver
`legis/revogacoes.py`. Recalculada no fim de toda execução, sobre o banco todo.
"""

import argparse
import os
import re
import sqlite3
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raiz do repo: comum/
from comum.saida import configurar_stdio  # noqa: E402
from comum import http  # noqa: E402
from revogacoes import calcular_situacoes  # noqa: E402  (legis/ está no path: é o dir do script)
import time
from collections import Counter
from datetime import datetime

import requests
from bs4 import BeautifulSoup

configurar_stdio()

BASE_URL = "https://egov.santos.sp.gov.br"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LegisIndexBot/1.0)"}
AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(AQUI, "legis.sqlite")
SCHEMA_PATH = os.path.join(AQUI, "schema.sql")
FONTE = "Legis Prefeitura de Santos"
PAUSA = 0.2  # cortesia entre requisições (s)

# Tópico de cada tipo de norma (confirmado por inspeção).
TIPOS = {
    6: "Lei ordinária",
    5: "Lei complementar",
    7: "Decreto",
    4: "Consolidação",
    8: "Índice de leis e decretos",
    150: "Ordem de Serviço",
    1: "Código",
    2: "Lei Orgânica",
}

MESES = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}


# ── HTTP / parsing ────────────────────────────────────────────────────────────
def _http_get(url: str, params: dict | None = None, tentativas: int = 4) -> requests.Response:
    return http.get(url, params, tentativas=tentativas, passo=4, timeout=30, headers=HEADERS)


def _fix(t: str) -> str:
    """Repara campos UTF-8 que vieram embutidos numa página latin-1."""
    try:
        return t.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return t


def _soup(url: str, params: dict | None = None) -> BeautifulSoup:
    raw = _http_get(url, params=params).content
    # decodifica 1:1 como latin-1 e passa str (evita o sniffing UTF-8 do BS)
    return BeautifulSoup(raw.decode("latin-1"), "html.parser")


def _txt(tag) -> str:
    return _fix(tag.get_text(" ", strip=True)) if tag else ""


# ── Navegação ─────────────────────────────────────────────────────────────────
def mapear_anos(topico: int) -> dict[int, str]:
    """Retorna {ano: url_do_subtopico}. Vazio se o tipo não tem nível de ano."""
    soup = _soup(f"{BASE_URL}/legis/topics/{topico}/documents")
    anos: dict[int, str] = {}
    for a in soup.select("a[href]"):
        rotulo = a.get_text(strip=True)
        href = a.get("href", "")
        if re.fullmatch(r"\d{4}", rotulo) and re.search(r"/topics/\d+/documents", href):
            anos[int(rotulo)] = href if href.startswith("http") else BASE_URL + href
    return anos


def coletar_ids(listagem_url: str) -> list[int]:
    """Pagina a listagem (?page=N) e devolve os IDs de documentos, em ordem."""
    ids: list[int] = []
    vistos: set[int] = set()
    page = 1
    while True:
        soup = _soup(listagem_url, params={"page": page} if page > 1 else None)
        novos = 0
        for a in soup.select("a[href]"):
            m = re.search(r"/legis/documents/(\d+)(?:$|[/?#])", a.get("href", ""))
            if m:
                did = int(m.group(1))
                if did not in vistos:
                    vistos.add(did)
                    ids.append(did)
                    novos += 1
        if novos == 0:
            break
        page += 1
        time.sleep(PAUSA)
    return ids


def detalhar(docid: int, tipo: str, ano: int | None) -> dict:
    """Faz scraping da página da norma e devolve metadados + temas."""
    url = f"{BASE_URL}/legis/documents/{docid}"
    soup = _soup(url)
    h1 = _txt(soup.select_one("h1"))

    # "2024 » Lei n.º 4.450, de 01 de março"  /  "Consolidações » Estatuto ..."
    prefixo, _, resto = h1.partition("»")
    prefixo, resto = prefixo.strip(), resto.strip()
    titulo = resto or prefixo

    numero = ""
    m = re.search(r"n\.?º\s*([\d][\d.\-/]*)", resto)
    if m:
        numero = m.group(1)

    if ano is None:
        ma = re.fullmatch(r"\d{4}", prefixo)
        if ma:
            ano = int(prefixo)

    # data "..., de 01 de março" + ano
    data_norma = ""
    md = re.search(r",\s*de\s+(\d{1,2})\s+de\s+([A-Za-zçãéê]+)", resto, re.I)
    if md and ano:
        dia = int(md.group(1))
        mes = MESES.get(md.group(2).lower())
        if mes:
            data_norma = f"{dia:02d}/{mes:02d}/{ano}"

    # badges: frases longas = ementa; curtas = temas
    ementa_partes, temas = [], []
    for b in soup.select(".badge-primary"):
        texto = _txt(b)
        if not texto:
            continue
        if len(texto) > 40 or len(texto.split()) > 4:
            ementa_partes.append(texto)
        else:
            temas.append(texto)
    ementa = " ".join(ementa_partes)
    # ementa oficial (o que a norma faz: "REVOGA A LEI Nº ..."); base da situação inferida
    descricao = " ".join(_txt(soup.select_one("p.descricao")).split())

    return {
        "id": docid,
        "tipo": tipo,
        "numero": numero,
        "ano": ano,
        "data_norma": data_norma,
        "titulo": titulo,
        "ementa": ementa,
        "tags": "; ".join(temas),
        "descricao": descricao,
        "url_legis": url,
        "url_pdf": f"{url}/download",
        "fonte": FONTE,
        "data_coleta": datetime.now().isoformat(timespec="seconds"),
        "_temas": temas,
    }


# ── Banco ─────────────────────────────────────────────────────────────────────
def abrir_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    # migração de bancos anteriores à situação (2026-10): só acrescenta colunas
    existentes = {r[1] for r in conn.execute("PRAGMA table_info(normas)")}
    for col, tipo in (("descricao", "TEXT"), ("revogada_por", "INTEGER")):
        if col not in existentes:
            conn.execute(f"ALTER TABLE normas ADD COLUMN {col} {tipo}")
    conn.commit()
    return conn


def ids_existentes(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT id FROM normas")}


def upsert(conn: sqlite3.Connection, n: dict) -> None:
    # situacao/revogada_por ficam de fora: são do recálculo (recalcular_situacao),
    # e o ON CONFLICT preserva o que já estava gravado (INSERT OR REPLACE apagava)
    cols = ["id", "tipo", "numero", "ano", "data_norma", "titulo", "ementa",
            "tags", "descricao", "url_legis", "url_pdf", "fonte", "data_coleta"]
    placeholders = ",".join("?" for _ in cols)
    atualiza = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO normas ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {atualiza}",
        [n[c] for c in cols],
    )
    conn.execute("DELETE FROM temas WHERE norma_id = ?", (n["id"],))
    conn.executemany(
        "INSERT OR IGNORE INTO temas (norma_id, tema) VALUES (?, ?)",
        [(n["id"], t) for t in n["_temas"]],
    )


def recalcular_situacao(conn: sqlite3.Connection) -> dict[int, dict]:
    """Recalcula situacao/revogada_por do banco todo a partir das ementas gravadas
    (sem rede, ~1 s). Zera antes: uma inferência que deixou de valer some."""
    conn.row_factory = sqlite3.Row
    normas = [dict(r) for r in conn.execute(
        "SELECT id, tipo, numero, ano, descricao FROM normas")]
    conn.row_factory = None
    sit = calcular_situacoes(normas)
    conn.execute("UPDATE normas SET situacao = '', revogada_por = NULL")
    conn.executemany(
        "UPDATE normas SET situacao = ?, revogada_por = ? WHERE id = ?",
        [(s["situacao"], s["revogada_por"], alvo) for alvo, s in sit.items()],
    )
    conn.commit()
    return sit


def revisitar_ids(conn: sqlite3.Connection, teto: int, pular: set[int]) -> list[tuple]:
    """As `teto` normas verificadas há mais tempo (data_coleta mais antiga) —
    revisita incremental: preenche a ementa oficial das antigas e pega mudanças
    no Legis sem reprocessar a base inteira a cada execução."""
    linhas = conn.execute(
        "SELECT id, tipo, ano FROM normas ORDER BY data_coleta, id").fetchall()
    return [l for l in linhas if l[0] not in pular][:teto]


# ── Orquestração ──────────────────────────────────────────────────────────────
def _resumo_situacao(sit: dict[int, dict]) -> None:
    c = Counter(s["situacao"] for s in sit.values())
    print("Situação inferida das ementas: "
          + (", ".join(f"{k}: {v}" for k, v in sorted(c.items())) or "nenhuma"), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Crawler do Legis — índice de metadados")
    parser.add_argument("--tipo", type=int, help="ID do tópico de tipo (ver TIPOS). Padrão: todos.")
    parser.add_argument("--ano", type=int, help="Ano específico. Padrão: todos os anos do tipo.")
    parser.add_argument("--limite", type=int, default=0, help="Máx. de normas a processar (0=todas).")
    parser.add_argument("--forcar", action="store_true", help="Reprocessa normas já no banco.")
    parser.add_argument("--dry-run", action="store_true", help="Não grava no banco (só imprime).")
    parser.add_argument("--revisitar", type=int, default=0,
                        help="Além das novas, reprocessa até N normas já gravadas "
                             "(as verificadas há mais tempo primeiro). 0 = nenhuma.")
    parser.add_argument("--so-situacao", action="store_true",
                        help="Só recalcula a situação a partir das ementas gravadas (sem rede).")
    args = parser.parse_args()

    if args.so_situacao:
        conn = abrir_db()
        sit = recalcular_situacao(conn)
        conn.close()
        _resumo_situacao(sit)
        return

    tipos = {args.tipo: TIPOS.get(args.tipo, f"Tópico {args.tipo}")} if args.tipo else dict(TIPOS)

    conn = None if args.dry_run else abrir_db()
    existentes = ids_existentes(conn) if conn else set()
    processados_agora: set[int] = set()  # a revisita não repete o que já veio nesta execução
    processados = 0
    sucessos = erros = 0  # chamadas de rede ok / com erro — decidem o exit code no fim

    for tid, nome_tipo in tipos.items():
        print(f"== Tipo {tid} — {nome_tipo} ==", file=sys.stderr)
        try:
            anos = mapear_anos(tid)
            sucessos += 1
        except Exception as e:
            erros += 1
            print(f"  ERRO ao mapear anos do tipo {tid}: {e} — pulando tipo.", file=sys.stderr)
            continue
        if anos:
            if args.ano:
                anos = {args.ano: anos[args.ano]} if args.ano in anos else {}
            alvos = sorted(anos.items(), reverse=True)
        else:
            # tipo sem nível de ano (ex.: Lei Orgânica, Códigos) — lista direto
            alvos = [(None, f"{BASE_URL}/legis/topics/{tid}/documents")]

        for ano, url in alvos:
            try:
                ids = coletar_ids(url)
                sucessos += 1
            except Exception as e:
                erros += 1
                print(f"  ERRO ao listar {nome_tipo} {ano or ''}: {e} — pulando.", file=sys.stderr)
                continue
            print(f"  {nome_tipo} {ano or ''}: {len(ids)} documentos.", file=sys.stderr)
            for did in ids:
                if args.limite and processados >= args.limite:
                    break
                if did in existentes and not args.forcar:
                    continue
                try:
                    n = detalhar(did, nome_tipo, ano)
                    sucessos += 1
                except Exception as e:
                    erros += 1
                    print(f"  ERRO doc {did}: {e} — pulando.", file=sys.stderr)
                    continue
                if args.dry_run:
                    print(f"  [{n['tipo']}] nº {n['numero']} ({n['ano']}) — "
                          f"{(n['ementa'] or n['titulo'])[:80]} | tags={n['tags']}")
                else:
                    upsert(conn, n)
                    conn.commit()
                    existentes.add(did)
                    processados_agora.add(did)
                processados += 1
                time.sleep(PAUSA)
            if args.limite and processados >= args.limite:
                break
        if args.limite and processados >= args.limite:
            break

    revisitadas = 0
    if conn and args.revisitar > 0:
        alvos_rev = revisitar_ids(conn, args.revisitar, pular=processados_agora)
        print(f"== Revisita: {len(alvos_rev)} normas já gravadas (mais antigas primeiro) ==",
              file=sys.stderr)
        for did, tipo, ano in alvos_rev:
            try:
                n = detalhar(did, tipo, ano)
                sucessos += 1
            except Exception as e:
                erros += 1
                print(f"  ERRO revisita doc {did}: {e} — pulando.", file=sys.stderr)
                continue
            upsert(conn, n)
            conn.commit()
            revisitadas += 1
            time.sleep(PAUSA)

    if conn:
        _resumo_situacao(recalcular_situacao(conn))
        conn.close()
    print(f"Concluído: {processados} normas processadas, {revisitadas} revisitadas "
          f"({sucessos} chamadas ok, {erros} com erro).", file=sys.stderr)

    # Falha visível (mesmo padrão de despesas/crawler.py): se TUDO que se tentou
    # deu erro, a fonte nos barrou. Sem isto o crawler saía 0, o export
    # reexportava o sqlite versionado inalterado e o workflow ficava verde com
    # a base congelada — só o alarme de frescor (45 dias) perceberia.
    if erros and not sucessos:
        print(f"ERRO FATAL: nenhuma chamada ao Legis funcionou ({erros} falhas). "
              f"Site fora do ar, bloqueio por User-Agent ou HTML mudou.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
