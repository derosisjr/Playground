# -*- coding: utf-8 -*-
"""precos/espelho/*.jsonl.gz → precos.sqlite.

O SQLite é descartável; o espelho versionado é a fonte da verdade. O cache do
GitHub Actions expira em 7 dias e o backfill custa horas — sem esta reconstrução,
um cache miss quebraria o painel silenciosamente.

Uso:
  python precos/reconstruir.py            # refaz do zero
  python precos/reconstruir.py --se-faltar  # no-op se o banco já existe
"""
import argparse
import glob
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crawler  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COLS_CONTRATACAO = [
    "ncp", "ibge", "cnpj", "razao_social", "ano", "sequencial", "modalidade",
    "modalidade_nome", "objeto", "srp", "valor_estimado", "valor_homologado",
    "situacao", "processo", "unidade_orgao", "data_publicacao", "itens_status"]
COLS_ITEM = [
    "ncp", "numero_item", "descricao", "descricao_norm", "info_complementar",
    "material_ou_servico", "quantidade", "unidade_medida", "unidade_norm",
    "fator_canonico", "valor_unitario_estimado", "valor_total",
    "criterio_julgamento", "situacao_item", "tem_resultado", "catalogo_codigo",
    "ncm", "resultado_status"]
COLS_RESULTADO = [
    "ncp", "numero_item", "sequencial_resultado", "valor_unitario_homologado",
    "valor_total_homologado", "quantidade_homologada", "ni_fornecedor",
    "nome_fornecedor", "porte_fornecedor", "data_resultado", "situacao_resultado",
    "ordem_classificacao_srp"]


def _ins(conn, tabela, cols, registros):
    if not registros:
        return 0
    conn.executemany(
        f"INSERT OR REPLACE INTO {tabela}({','.join(cols)}) "
        f"VALUES ({','.join('?' * len(cols))})",
        [[r.get(c) for c in cols] for r in registros])
    return len(registros)


def reconstruir():
    conn = crawler.conectar()
    nc = ni = nr = 0
    for caminho in sorted(glob.glob(os.path.join(crawler.ESPELHO, "*.jsonl.gz"))):
        contratacoes, itens, resultados = [], [], []
        with gzip.open(caminho, "rt", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                reg = json.loads(linha)
                itens += reg.pop("itens", [])
                resultados += reg.pop("resultados", [])
                contratacoes.append(reg)
        nc += _ins(conn, "contratacao", COLS_CONTRATACAO, contratacoes)
        ni += _ins(conn, "item", COLS_ITEM, itens)
        nr += _ins(conn, "resultado", COLS_RESULTADO, resultados)
        conn.commit()

    # o controle de listagem não vive no espelho (é derivado): remonta a partir
    # do que já foi carregado, para o incremental não re-varrer meses prontos
    conn.execute("""
        INSERT OR IGNORE INTO controle_listagem(ibge, ano, mes, modalidade,
                                                total_registros, carregado_em)
        SELECT ibge, CAST(substr(data_publicacao,1,4) AS INT),
               CAST(substr(data_publicacao,6,2) AS INT), modalidade,
               COUNT(*), 'reconstruido'
        FROM contratacao WHERE data_publicacao <> ''
        GROUP BY 1,2,3,4""")
    conn.commit()
    print(f"reconstruído: {nc} contratações · {ni} itens · {nr} resultados")
    return nc, ni, nr


def main():
    ap = argparse.ArgumentParser(description="Espelho versionado → precos.sqlite")
    ap.add_argument("--se-faltar", action="store_true",
                    help="não faz nada se o sqlite já existe (uso no workflow)")
    args = ap.parse_args()
    if args.se_faltar and os.path.exists(crawler.BASE):
        print("sqlite presente (cache do Actions); reconstrução dispensada")
        return
    reconstruir()


if __name__ == "__main__":
    main()
