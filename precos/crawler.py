# -*- coding: utf-8 -*-
"""Crawler do painel Preço comparado (PNCP → precos.sqlite → precos/espelho/).

Coleta em três tiers, deliberadamente desacoplados porque o custo de cada um é
de ordem de grandeza diferente:

  Tier 1  listagem por (cidade, mês, modalidade)  — ~360 chamadas no escopo atual
  Tier 2  itens, 1 chamada por contratação        — ~11 mil, amortizado por orçamento
  Tier 3  resultados, 1 chamada por item          — só o que CASOU com uma consulta

O Tier 3 nunca é varrido: `casar.py` roda de graça sobre o texto já espelhado e
só então marca quais itens merecem a chamada de `resultados`. Sem isso seriam
~260 mil requisições para responder a uma pergunta sobre 6 itens.

O SQLite é DERIVADO e gitignored. A fonte da verdade é `precos/espelho/*.jsonl.gz`,
versionado: o cache do GitHub Actions expira em 7 dias e um cache miss custaria o
backfill inteiro. `reconstruir.py` refaz o banco a partir do espelho.

Uso:
  python precos/crawler.py --listagem --dry-run            # amostra, não grava
  python precos/crawler.py --listagem --ano 2025           # Tier 1
  python precos/crawler.py --itens --orcamento 500         # Tier 2, para ao esgotar
  python precos/crawler.py --santos                        # âncoras das consultas
  python precos/crawler.py --resultados                    # Tier 3 (após casar.py)
  python precos/crawler.py --incremental                   # o que o workflow roda
"""
import argparse
import calendar
import glob
import gzip
import json
import os
import sqlite3
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fontes  # noqa: E402
import texto  # noqa: E402
import unidades  # noqa: E402

DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(DIR, "precos.sqlite")
ESPELHO = os.path.join(DIR, "espelho")
CONSULTAS = os.path.join(DIR, "consultas")

ANO_INICIAL = 2025  # escopo enxuto: pregão eletrônico + dispensa, 2025→corrente

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cidade(
    ibge TEXT PRIMARY KEY, nome TEXT, pop INTEGER, par INTEGER);

CREATE TABLE IF NOT EXISTS contratacao(
    ncp TEXT PRIMARY KEY, ibge TEXT, cnpj TEXT, razao_social TEXT,
    ano INTEGER, sequencial INTEGER, modalidade INTEGER, modalidade_nome TEXT,
    objeto TEXT, srp INTEGER, valor_estimado REAL, valor_homologado REAL,
    situacao TEXT, processo TEXT, unidade_orgao TEXT, data_publicacao TEXT,
    itens_status TEXT DEFAULT 'pendente');
CREATE INDEX IF NOT EXISTS ix_contratacao_fila
    ON contratacao(itens_status, data_publicacao DESC);

CREATE TABLE IF NOT EXISTS item(
    ncp TEXT, numero_item INTEGER,
    descricao TEXT, descricao_norm TEXT, info_complementar TEXT,
    material_ou_servico TEXT, quantidade REAL,
    unidade_medida TEXT, unidade_norm TEXT, fator_canonico REAL,
    valor_unitario_estimado REAL, valor_total REAL,
    criterio_julgamento TEXT, situacao_item TEXT, tem_resultado INTEGER,
    catalogo_codigo TEXT, ncm TEXT,
    resultado_status TEXT DEFAULT 'nao_pedido',
    PRIMARY KEY(ncp, numero_item));
CREATE INDEX IF NOT EXISTS ix_item_res ON item(resultado_status);

CREATE TABLE IF NOT EXISTS resultado(
    ncp TEXT, numero_item INTEGER, sequencial_resultado INTEGER,
    valor_unitario_homologado REAL, valor_total_homologado REAL,
    quantidade_homologada REAL, ni_fornecedor TEXT, nome_fornecedor TEXT,
    porte_fornecedor TEXT, data_resultado TEXT, situacao_resultado TEXT,
    ordem_classificacao_srp INTEGER,
    PRIMARY KEY(ncp, numero_item, sequencial_resultado));

CREATE TABLE IF NOT EXISTS controle_listagem(
    ibge TEXT, ano INTEGER, mes INTEGER, modalidade INTEGER,
    total_registros INTEGER, carregado_em TEXT,
    PRIMARY KEY(ibge, ano, mes, modalidade));

CREATE TABLE IF NOT EXISTS casamento(
    slug TEXT, ncp TEXT, numero_item INTEGER, aceito INTEGER, confianca TEXT,
    jaccard REAL, motivo_rejeicao TEXT, curadoria TEXT,
    PRIMARY KEY(slug, ncp, numero_item));
"""


def conectar():
    conn = sqlite3.connect(BASE)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT OR REPLACE INTO cidade VALUES (?,?,?,1)", fontes.CIDADES)
    conn.execute("INSERT OR REPLACE INTO cidade VALUES (?,?,?,0)",
                 (fontes.IBGE_SANTOS, "Santos", 418_608))
    conn.commit()
    return conn


# ─────────────────────────────── Tier 1: listagem ───────────────────────────

def _linha_contratacao(c: dict, ibge: str):
    org = c.get("orgaoEntidade") or {}
    uni = c.get("unidadeOrgao") or {}
    return (
        c.get("numeroControlePNCP"), ibge, org.get("cnpj"), org.get("razaoSocial"),
        c.get("anoCompra"), c.get("sequencialCompra"),
        c.get("modalidadeId"), c.get("modalidadeNome"),
        c.get("objetoCompra"), 1 if c.get("srp") else 0,
        c.get("valorTotalEstimado"), c.get("valorTotalHomologado"),
        c.get("situacaoCompraNome"), c.get("processo"), uni.get("nomeUnidade"),
        (c.get("dataPublicacaoPncp") or "")[:10],
    )


def carregar_listagem(conn, ibge, ano, mes, modalidade, dry_run=False):
    """Uma célula (cidade, mês, modalidade). Devolve nº de contratações municipais."""
    ini = f"{ano}{mes:02d}01"
    fim = f"{ano}{mes:02d}{calendar.monthrange(ano, mes)[1]:02d}"
    brutos = fontes.listar(ini, fim, modalidade, ibge=ibge)
    linhas = [_linha_contratacao(c, ibge) for c in brutos if fontes.municipal(c)]

    if dry_run:
        for ln in linhas[:10]:
            print(f"    {ln[0]}  {(ln[8] or '')[:70]}")
        print(f"    ({len(brutos)} no PNCP, {len(linhas)} de esfera municipal)")
        return len(linhas)

    # INSERT OR IGNORE preserva itens_status de contratações já processadas;
    # os metadados são estáveis e não valem uma releitura de itens.
    conn.executemany(
        "INSERT OR IGNORE INTO contratacao(ncp,ibge,cnpj,razao_social,ano,sequencial,"
        "modalidade,modalidade_nome,objeto,srp,valor_estimado,valor_homologado,"
        "situacao,processo,unidade_orgao,data_publicacao) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", linhas)
    conn.execute("INSERT OR REPLACE INTO controle_listagem VALUES (?,?,?,?,?,?)",
                 (ibge, ano, mes, modalidade, len(linhas),
                  date.today().isoformat()))
    conn.commit()
    return len(linhas)


def tier1(conn, anos, meses=None, cidades=None, modalidades=None,
          forcar=False, dry_run=False):
    hoje = date.today()
    ja = {(r["ibge"], r["ano"], r["mes"], r["modalidade"])
          for r in conn.execute("SELECT * FROM controle_listagem")}
    alvo = cidades or [c[0] for c in fontes.CIDADES]
    mods = modalidades or sorted(fontes.MODALIDADES)
    total, chamadas, falhas = 0, 0, []

    for ibge in alvo:
        nome = next((c[1] for c in fontes.CIDADES if c[0] == ibge), ibge)
        for ano in anos:
            for mes in (meses or range(1, 13)):
                if (ano, mes) > (hoje.year, hoje.month):
                    continue
                for mod in mods:
                    # mês encerrado não muda; só o corrente e o anterior são
                    # rebaixados (publicação no PNCP tem defasagem e retificação)
                    recente = (ano, mes) >= _mes_anterior(hoje)
                    if (ibge, ano, mes, mod) in ja and not (forcar or dry_run or recente):
                        continue
                    try:
                        n = carregar_listagem(conn, ibge, ano, mes, mod, dry_run)
                        chamadas += 1
                        total += n
                        if n or dry_run:
                            print(f"  {nome} {ano}-{mes:02d} mod {mod}: {n}")
                        time.sleep(fontes.PAUSA)
                    except Exception as e:  # noqa: BLE001 — segue p/ as demais células
                        falhas.append(f"{nome} {ano}-{mes:02d} mod {mod}: {e}")
        # flush por cidade: um timeout do Actions no meio do backfill não pode
        # apagar o que já foi coletado (o sqlite não é versionado)
        if not dry_run:
            gravar_espelho(conn, silencioso=True)
    return total, chamadas, falhas


def _mes_anterior(d: date):
    return (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)


# ──────────────────────────────── Tier 2: itens ─────────────────────────────

def _linha_item(ncp: str, it: dict):
    desc = it.get("descricao") or ""
    un = it.get("unidadeMedida")
    can, fator = unidades.normalizar_unidade(un)
    return (
        ncp, it.get("numeroItem"), desc, texto.normalizar(desc),
        it.get("informacaoComplementar"), it.get("materialOuServico"),
        it.get("quantidade"), un, can, fator,
        it.get("valorUnitarioEstimado"), it.get("valorTotal"),
        it.get("criterioJulgamentoNome"), it.get("situacaoCompraItemNome"),
        1 if it.get("temResultado") else 0,
        it.get("catalogoCodigoItem"), it.get("ncmNbsCodigo"),
    )


def carregar_itens(conn, ncp, cnpj, ano, seq):
    brutos = fontes.itens(cnpj, ano, seq)
    if not brutos:
        conn.execute("UPDATE contratacao SET itens_status='vazio' WHERE ncp=?", (ncp,))
        conn.commit()
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO item(ncp,numero_item,descricao,descricao_norm,"
        "info_complementar,material_ou_servico,quantidade,unidade_medida,unidade_norm,"
        "fator_canonico,valor_unitario_estimado,valor_total,criterio_julgamento,"
        "situacao_item,tem_resultado,catalogo_codigo,ncm) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [_linha_item(ncp, it) for it in brutos])
    conn.execute("UPDATE contratacao SET itens_status='ok' WHERE ncp=?", (ncp,))
    conn.commit()
    return len(brutos)


def tier2(conn, orcamento: int, dry_run=False, prioridade=None):
    """Consome a fila de contratações pendentes até esgotar o orçamento.

    Ordem por data de publicação decrescente: o recente vale mais para comparar
    preço, e um backfill interrompido deixa para trás justamente o mais antigo.

    `prioridade` é um termo do objeto que sobe na fila as contratações que o
    contêm. É ORDEM, não filtro: nada é excluído, o backfill continua até cobrir
    tudo. Serve ao fluxo real do gabinete — "tenho um contrato de papel A4, puxe
    primeiro quem comprou papel" — sem enviesar a base final.
    """
    ordem = "data_publicacao DESC"
    args = []
    if prioridade:
        ordem = ("(CASE WHEN lower(objeto) LIKE ? THEN 0 ELSE 1 END), "
                 "data_publicacao DESC")
        args.append(f"%{prioridade.lower()}%")
    fila = conn.execute(
        "SELECT ncp, cnpj, ano, sequencial FROM contratacao "
        f"WHERE itens_status='pendente' ORDER BY {ordem} LIMIT ?",
        args + [orcamento]).fetchall()
    if dry_run:
        print(f"  fila pendente: {_pendentes(conn)} · pegaria {len(fila)}")
        return 0, 0, []
    n_itens, chamadas, falhas = 0, 0, []
    sujos = set()
    for r in fila:
        try:
            n_itens += carregar_itens(conn, r["ncp"], r["cnpj"], r["ano"], r["sequencial"])
            chamadas += 1
            g = _grupo_de(conn, r["ncp"])
            if g:
                sujos.add(g)
            # flush periódico: o job do Actions pode ser morto pelo timeout a
            # qualquer momento, e só o espelho sobrevive entre execuções
            if chamadas % 250 == 0:
                gravar_espelho(conn, sujos, silencioso=True)
                sujos.clear()
                print(f"    ... {chamadas} contratações · espelho gravado", flush=True)
            time.sleep(fontes.PAUSA)
        except Exception as e:  # noqa: BLE001
            falhas.append(f"itens {r['ncp']}: {e}")
            conn.execute("UPDATE contratacao SET itens_status='erro' WHERE ncp=?",
                         (r["ncp"],))
            conn.commit()
    if sujos:
        gravar_espelho(conn, sujos, silencioso=True)
    return n_itens, chamadas, falhas


def _pendentes(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM contratacao WHERE itens_status='pendente'").fetchone()[0]


# ────────────────────────── Tier 3: resultados (puxado) ─────────────────────

def _buscar_resultados(conn, fila):
    """Loop de busca compartilhado pelos dois modos do Tier 3.

    Grava o espelho a cada 250 chamadas: a fila completa de Santos passa de 3,8
    mil itens e o job do Actions morre no timeout sem aviso — só o espelho
    sobrevive entre execuções.
    """
    n, chamadas, falhas = 0, 0, []
    sujos = set()
    for r in fila:
        try:
            brutos = fontes.resultados(r["cnpj"], r["ano"], r["sequencial"],
                                       r["numero_item"])
            chamadas += 1
            if brutos:
                conn.executemany(
                    "INSERT OR REPLACE INTO resultado VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(r["ncp"], r["numero_item"], b.get("sequencialResultado"),
                      b.get("valorUnitarioHomologado"), b.get("valorTotalHomologado"),
                      b.get("quantidadeHomologada"), b.get("niFornecedor"),
                      b.get("nomeRazaoSocialFornecedor"), b.get("porteFornecedorNome"),
                      (b.get("dataResultado") or "")[:10],
                      b.get("situacaoCompraItemResultadoNome"),
                      b.get("ordemClassificacaoSrp")) for b in brutos])
                n += len(brutos)
            conn.execute(
                "UPDATE item SET resultado_status=? WHERE ncp=? AND numero_item=?",
                ("ok" if brutos else "vazio", r["ncp"], r["numero_item"]))
            conn.commit()
            g = _grupo_de(conn, r["ncp"])
            if g:
                sujos.add(g)
            if chamadas % 250 == 0:
                gravar_espelho(conn, sujos, silencioso=True)
                sujos.clear()
                print(f"    ... {chamadas} resultados · espelho gravado", flush=True)
            time.sleep(fontes.PAUSA)
        except Exception as e:  # noqa: BLE001
            falhas.append(f"resultados {r['ncp']}#{r['numero_item']}: {e}")
    if sujos:
        gravar_espelho(conn, sujos, silencioso=True)
    return n, chamadas, falhas


def tier3(conn, slug=None, dry_run=False):
    """Busca `resultados` SÓ de itens que casaram com alguma consulta.

    Três filtros em cascata, todos obrigatórios: casou com consulta aceita,
    `tem_resultado=1`, e ainda não foi pedido. Um item já resolvido nunca é
    repedido, então republicar uma comparação custa zero chamadas.

    Este é o modo das CIDADES-PAR, onde varrer seria especulativo: 6,9 mil itens
    com resultado publicado para responder a perguntas sobre meia dúzia. Santos
    tem modo próprio — ver `tier3_santos`.
    """
    sql = ("SELECT i.ncp, i.numero_item, c.cnpj, c.ano, c.sequencial "
           "FROM item i "
           "JOIN casamento k ON k.ncp=i.ncp AND k.numero_item=i.numero_item "
           "JOIN contratacao c ON c.ncp=i.ncp "
           "WHERE k.aceito=1 AND i.tem_resultado=1 AND i.resultado_status='nao_pedido'")
    args = []
    if slug:
        sql += " AND k.slug=?"
        args.append(slug)
    fila = conn.execute(sql + " GROUP BY i.ncp, i.numero_item", args).fetchall()

    casados = conn.execute(
        "SELECT COUNT(DISTINCT i.ncp||'#'||i.numero_item) FROM item i "
        "JOIN casamento k ON k.ncp=i.ncp AND k.numero_item=i.numero_item "
        "WHERE k.aceito=1 AND i.tem_resultado=1").fetchone()[0]
    print(f"  resultados pedidos: {len(fila)} "
          f"(itens casados com tem_resultado=1: {casados})")
    if dry_run:
        return 0, 0, []
    return _buscar_resultados(conn, fila)


def tier3_santos(conn, orcamento: int, dry_run=False):
    """Busca o resultado de TODOS os itens de Santos — a âncora fica sempre pronta.

    Aqui a varredura não é especulativa: o espelho de Santos já está 100%
    mapeado, e completar os ~3,8 mil preços é fechar uma conta conhecida. É o
    que permite escolher um item e ter a comparação na hora, sem esperar rede.
    Resumível pelo mesmo padrão do Tier 2: consome o orçamento e para limpo.
    """
    fila = conn.execute(
        "SELECT i.ncp, i.numero_item, c.cnpj, c.ano, c.sequencial "
        "FROM item i JOIN contratacao c ON c.ncp=i.ncp "
        "WHERE c.ibge=? AND i.tem_resultado=1 AND i.resultado_status='nao_pedido' "
        "ORDER BY c.data_publicacao DESC LIMIT ?",
        (fontes.IBGE_SANTOS, orcamento)).fetchall()
    restam = conn.execute(
        "SELECT COUNT(*) FROM item i JOIN contratacao c ON c.ncp=i.ncp "
        "WHERE c.ibge=? AND i.tem_resultado=1 AND i.resultado_status='nao_pedido'",
        (fontes.IBGE_SANTOS,)).fetchone()[0]
    print(f"  resultados de Santos pendentes: {restam} · "
          f"pegando {len(fila)} nesta execução")
    if dry_run:
        return 0, 0, []
    return _buscar_resultados(conn, fila)


# ───────────────────── Âncoras de Santos (dirigido por consulta) ────────────

def carregar_santos(conn, dry_run=False):
    """Puxa a contratação e os itens de cada consulta curada. 2-3 chamadas cada."""
    n, falhas = 0, []
    for caminho in sorted(glob.glob(os.path.join(CONSULTAS, "*.json"))):
        with open(caminho, encoding="utf-8") as f:
            q = json.load(f)
        s = q.get("santos") or {}
        try:
            if s.get("cnpj") and s.get("ano") and s.get("sequencial"):
                cnpj, ano, seq = s["cnpj"], int(s["ano"]), int(s["sequencial"])
            else:
                cnpj, ano, seq = fontes.parse_ncp(s.get("numero_controle_pncp"))
        except ValueError as e:
            falhas.append(f"{os.path.basename(caminho)}: {e}")
            continue
        ncp = fontes.montar_ncp(cnpj, ano, seq)
        if dry_run:
            print(f"  {q.get('slug')}: {ncp}")
            continue
        try:
            achou = fontes.listar(f"{ano}0101", f"{ano}1231", 6, cnpj=cnpj) or []
            achou += fontes.listar(f"{ano}0101", f"{ano}1231", 8, cnpj=cnpj) or []
            meta = next((c for c in achou if c.get("sequencialCompra") == seq), None)
            if meta:
                conn.execute(
                    "INSERT OR REPLACE INTO contratacao(ncp,ibge,cnpj,razao_social,ano,"
                    "sequencial,modalidade,modalidade_nome,objeto,srp,valor_estimado,"
                    "valor_homologado,situacao,processo,unidade_orgao,data_publicacao,"
                    "itens_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pendente')",
                    _linha_contratacao(meta, fontes.IBGE_SANTOS))
                conn.commit()
            n += carregar_itens(conn, ncp, cnpj, ano, seq)
            # o preço de Santos é a âncora: seus resultados são sempre buscados
            for it in conn.execute(
                    "SELECT numero_item FROM item WHERE ncp=? AND tem_resultado=1 "
                    "AND resultado_status='nao_pedido'", (ncp,)).fetchall():
                brutos = fontes.resultados(cnpj, ano, seq, it["numero_item"])
                if brutos:
                    conn.executemany(
                        "INSERT OR REPLACE INTO resultado VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(ncp, it["numero_item"], b.get("sequencialResultado"),
                          b.get("valorUnitarioHomologado"), b.get("valorTotalHomologado"),
                          b.get("quantidadeHomologada"), b.get("niFornecedor"),
                          b.get("nomeRazaoSocialFornecedor"), b.get("porteFornecedorNome"),
                          (b.get("dataResultado") or "")[:10],
                          b.get("situacaoCompraItemResultadoNome"),
                          b.get("ordemClassificacaoSrp")) for b in brutos])
                conn.execute(
                    "UPDATE item SET resultado_status=? WHERE ncp=? AND numero_item=?",
                    ("ok" if brutos else "vazio", ncp, it["numero_item"]))
                conn.commit()
                time.sleep(fontes.PAUSA)
            print(f"  {q.get('slug')}: {ncp} carregado")
        except Exception as e:  # noqa: BLE001
            falhas.append(f"{q.get('slug')}: {e}")
    return n, falhas


# ──────────────────────────── Espelho versionado ────────────────────────────

def gravar_espelho(conn, grupos=None, silencioso=False):
    """SQLite → precos/espelho/<ibge>-<ano>.jsonl.gz (uma linha por contratação).

    Projeção reduzida e ordenada: o payload cru do PNCP tem dezenas de campos que
    não usamos, e ordem instável produziria diff a cada execução.

    `grupos` restringe a (ibge, ano) específicos — usado nas gravações parciais
    durante o crawl. Gravar só no fim seria perder o backfill inteiro quando o
    job do Actions estoura o timeout (o sqlite não é versionado).
    """
    os.makedirs(ESPELHO, exist_ok=True)
    if grupos is None:
        grupos = conn.execute(
            "SELECT DISTINCT ibge, ano FROM contratacao ORDER BY ibge, ano").fetchall()
    grupos = sorted({(g["ibge"], g["ano"]) if not isinstance(g, tuple) else g
                     for g in grupos})
    escritos = 0
    for ibge, ano in grupos:
        alvo = os.path.join(ESPELHO, f"{ibge}-{ano}.jsonl.gz")
        linhas = []
        for c in conn.execute(
                "SELECT * FROM contratacao WHERE ibge=? AND ano=? ORDER BY ncp",
                (ibge, ano)).fetchall():
            reg = dict(c)
            reg["itens"] = [dict(i) for i in conn.execute(
                "SELECT * FROM item WHERE ncp=? ORDER BY numero_item", (c["ncp"],))]
            reg["resultados"] = [dict(r) for r in conn.execute(
                "SELECT * FROM resultado WHERE ncp=? "
                "ORDER BY numero_item, sequencial_resultado", (c["ncp"],))]
            linhas.append(json.dumps(reg, ensure_ascii=False, sort_keys=True))
        # mtime=0: sem timestamp no cabeçalho gzip, senão todo run vira diff
        with gzip.GzipFile(alvo, "wb", mtime=0) as f:
            f.write(("\n".join(linhas) + "\n").encode("utf-8"))
        escritos += len(linhas)
    mb = sum(os.path.getsize(p) for p in glob.glob(os.path.join(ESPELHO, "*.gz"))) / 2**20
    if not silencioso:
        print(f"  espelho: {escritos} contratações em {len(grupos)} arquivos · {mb:.1f} MB")
    if mb > 20:
        print(f"AVISO — espelho passou de 20 MB ({mb:.1f} MB); revise o escopo.",
              file=sys.stderr)
    return escritos


def renormalizar(conn):
    """Recalcula unidade_norm/fator_canonico e descricao_norm de todos os itens.

    Necessário depois de mexer em `unidades.py` ou `texto.py`: os itens já
    espelhados guardam o resultado da tabela ANTIGA. O casamento recalcula o
    fator na hora e não depende dessas colunas, mas elas alimentam as consultas
    de auditoria — e ficar com duas verdades no banco é como se perde a confiança
    na base.
    """
    linhas = []
    for r in conn.execute("SELECT ncp, numero_item, descricao, unidade_medida FROM item"):
        can, fator = unidades.normalizar_unidade(r["unidade_medida"])
        linhas.append((texto.normalizar(r["descricao"] or ""), can, fator,
                       r["ncp"], r["numero_item"]))
    conn.executemany(
        "UPDATE item SET descricao_norm=?, unidade_norm=?, fator_canonico=? "
        "WHERE ncp=? AND numero_item=?", linhas)
    conn.commit()
    reconhecidas = conn.execute(
        "SELECT COUNT(*) FROM item WHERE unidade_norm IS NOT NULL").fetchone()[0]
    print(f"  renormalizados {len(linhas)} itens · "
          f"{reconhecidas} com unidade reconhecida "
          f"({100 * reconhecidas / max(len(linhas), 1):.0f}%)")
    return len(linhas)


def _grupo_de(conn, ncp):
    r = conn.execute("SELECT ibge, ano FROM contratacao WHERE ncp=?", (ncp,)).fetchone()
    return (r["ibge"], r["ano"]) if r else None


# ─────────────────────────────────── CLI ────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Crawler do painel Preço comparado (PNCP)")
    ap.add_argument("--listagem", action="store_true", help="Tier 1")
    ap.add_argument("--itens", action="store_true", help="Tier 2")
    ap.add_argument("--resultados", action="store_true", help="Tier 3 (após casar.py)")
    ap.add_argument("--santos", action="store_true",
                    help="âncoras das consultas curadas; com --resultados, baixa "
                         "os preços de TODOS os itens de Santos")
    ap.add_argument("--renormalizar", action="store_true",
                    help="recalcula unidade/descrição normalizadas (após mexer "
                         "em unidades.py ou texto.py); não faz requisição")
    ap.add_argument("--incremental", action="store_true",
                    help="mês corrente+anterior, lacunas, e fila de itens")
    ap.add_argument("--ano", type=int)
    ap.add_argument("--mes", type=int)
    ap.add_argument("--cidade", help="código IBGE")
    ap.add_argument("--modalidade", type=int, choices=sorted(fontes.MODALIDADES))
    ap.add_argument("--slug", help="restringe o Tier 3 a uma consulta")
    ap.add_argument("--orcamento", type=int, default=1000,
                    help="teto de chamadas de itens nesta execução")
    ap.add_argument("--prioridade",
                    help="sobe na fila do Tier 2 as contratações cujo objeto contém "
                         "o termo (é ordem, não filtro — nada fica de fora)")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="imprime sem gravar")
    args = ap.parse_args()

    conn = conectar()
    hoje = date.today()
    falhas, chamadas = [], 0
    nada_pedido = not any([args.listagem, args.itens, args.resultados,
                           args.santos, args.incremental, args.renormalizar])

    if args.renormalizar:
        print("Renormalização (sem rede)")
        renormalizar(conn)
        if not args.dry_run:
            gravar_espelho(conn)
        return

    if args.listagem or args.incremental or nada_pedido:
        if args.incremental:
            ap_ano, ap_mes = _mes_anterior(hoje)
            anos = sorted({hoje.year, ap_ano})
            meses = None  # tier1 pula o que já está no controle e não é recente
        else:
            anos = [args.ano] if args.ano else list(range(ANO_INICIAL, hoje.year + 1))
            meses = [args.mes] if args.mes else None
        print("Tier 1 — listagem")
        n, ch, f = tier1(conn, anos, meses,
                         [args.cidade] if args.cidade else None,
                         [args.modalidade] if args.modalidade else None,
                         args.forcar, args.dry_run)
        chamadas += ch
        falhas += f
        print(f"  contratações municipais: {n} · pendentes de itens: {_pendentes(conn)}")

    # `--santos` sozinho carrega as âncoras das consultas; combinado com
    # `--resultados` significa "os preços de Santos", tratado no Tier 3 abaixo
    if (args.santos and not args.resultados) or args.incremental or nada_pedido:
        print("Âncoras de Santos")
        n, f = carregar_santos(conn, args.dry_run)
        falhas += f

    if args.itens or args.incremental or nada_pedido:
        print(f"Tier 2 — itens (orçamento {args.orcamento})"
              + (f" · prioridade: {args.prioridade}" if args.prioridade else ""))
        n, ch, f = tier2(conn, args.orcamento, args.dry_run, args.prioridade)
        chamadas += ch
        falhas += f
        if not args.dry_run:
            print(f"  {n} itens em {ch} contratações · restam {_pendentes(conn)}")

    if args.resultados:
        if args.santos:
            print("Tier 3 — resultados de Santos (base completa)")
            n, ch, f = tier3_santos(conn, args.orcamento, args.dry_run)
        else:
            print("Tier 3 — resultados")
            n, ch, f = tier3(conn, args.slug, args.dry_run)
        chamadas += ch
        falhas += f

    if not args.dry_run:
        gravar_espelho(conn)

    for f in falhas:
        print(f"AVISO — {f}", file=sys.stderr)
    print(("[dry-run] " if args.dry_run else "")
          + f"chamadas: {chamadas} · falhas: {len(falhas)}")


if __name__ == "__main__":
    main()
