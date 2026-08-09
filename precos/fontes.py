# -*- coding: utf-8 -*-
"""Fonte do painel Preço comparado: PNCP (Portal Nacional de Contratações Públicas).

Três endpoints, verificados no ar em 2026-08-08 com dados reais de Santos:

  1. `/api/consulta/v1/contratacoes/publicacao` — listagem por período. Exige
     `codigoModalidadeContratacao` (um por chamada) e aceita `codigoMunicipioIbge`
     OU `cnpj`. Envelope paginado: totalRegistros/totalPaginas/numeroPagina.
  2. `/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens` — os itens, com
     descrição, quantidade, unidade e **valor unitário estimado**.
  3. `.../itens/{n}/resultados` — o **valor unitário homologado** e o fornecedor.

Duas armadilhas descobertas na verificação e tratadas aqui:

  - `codigoMunicipioIbge` filtra pela LOCALIZAÇÃO DA UNIDADE, não pela esfera:
    consultar Guarujá devolve a Secretaria da Segurança Pública do estado
    (Bombeiros/GBMAR). Por isso `municipal()` filtra por `esferaId == "M"` — o
    que também abraça autarquias e fundações municipais sem curar CNPJ a mão.
  - Paginar é obrigatório: uma consulta com 16 registros veio em 2 páginas com o
    tamanho default. Usamos `tamanhoPagina=50` e sempre lemos `totalPaginas`.

Os campos de catálogo (`catalogoCodigoItem`, `ncmNbsCodigo`) vêm nulos nas
compras municipais — daí todo o aparato de casamento textual em `casar.py`.
"""
import re
import time

import requests

CONSULTA = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
ITENS = "https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens"
RESULTADOS = ITENS + "/{item}/resultados"
# página pública, para citar a fonte de cada número no painel
URL_PUBLICA = "https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}"

CNPJ_SANTOS = "58200015000183"
IBGE_SANTOS = "3548500"

# Modalidades varridas no espelho. Pregão eletrônico e dispensa concentram a
# compra de material padronizado — que é onde comparar preço unitário faz
# sentido. Ampliar aqui é seguro (o controle_carga refaz só o que falta), mas
# multiplica o backfill: cada modalidade é uma chamada de listagem separada.
MODALIDADES = {6: "Pregão - Eletrônico", 8: "Dispensa de Licitação"}

# Cidades-par. Códigos IBGE conferidos em 2026-08-08 contra
# servicodados.ibge.gov.br/api/v1/localidades/estados/35/municipios.
# População do Censo 2022 (mesma base de Comum.POP_SANTOS = 418.608).
CIDADES = [
    ("3518701", "Guarujá", 322_750),
    ("3551009", "São Vicente", 331_756),
    ("3541000", "Praia Grande", 348_222),
    ("3513504", "Cubatão", 127_303),
    ("3525904", "Jundiaí", 370_126),
    ("3538709", "Piracicaba", 407_252),
    ("3530607", "Mogi das Cruzes", 440_769),
    ("3506003", "Bauru", 379_297),
    ("3549904", "São José dos Campos", 697_428),
]

SITUACOES_ITEM_INVALIDAS = {"cancelado", "deserto", "fracassado", "anulado"}

_UA = {"User-Agent": "painel-precos-camara-santos (github.com/derosisjr/Playground)"}
PAUSA = 0.5  # s entre requisições (educação com a API do PNCP)


def _get(url, params=None, tentativas=5, timeout=90):
    """GET com retry; devolve JSON, ou None quando o PNCP responde 204/404.

    204 (sem conteúdo) e 404 são respostas NORMAIS aqui: mês sem contratação
    naquela modalidade, ou compra sem itens publicados. Tratar como erro faria
    o crawler abortar cidade inteira por um mês vazio.

    Retry longo e paciente por experiência direta (2026-08-08): uma rajada de
    consultas fez `/api/consulta/` devolver 500 e depois estourar o timeout por
    alguns minutos, voltando sozinho em seguida. Backoff de 15/30/45/60 s cobre
    esse tipo de estrangulamento; desistir em ~30 s perderia a cidade inteira.
    """
    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=timeout)
            if r.status_code in (204, 404):
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 — retry genérico de rede
            ultimo = e
            if i < tentativas - 1:
                time.sleep(15 * (i + 1))
    raise ultimo


def municipal(contratacao: dict) -> bool:
    """Só esfera municipal — ver armadilha do `codigoMunicipioIbge` no topo."""
    return (contratacao.get("orgaoEntidade") or {}).get("esferaId") == "M"


def listar(ini: str, fim: str, modalidade: int, ibge=None, cnpj=None) -> list[dict]:
    """Contratações publicadas no período (AAAAMMDD), paginando até o fim."""
    saida, pagina = [], 1
    while True:
        p = {"dataInicial": ini, "dataFinal": fim,
             "codigoModalidadeContratacao": modalidade,
             "pagina": pagina, "tamanhoPagina": 50}
        if ibge:
            p["codigoMunicipioIbge"] = ibge
        if cnpj:
            p["cnpj"] = cnpj
        d = _get(CONSULTA, p)
        if not d:
            break
        saida.extend(d.get("data") or [])
        if pagina >= (d.get("totalPaginas") or 1):
            break
        pagina += 1
        time.sleep(PAUSA)
    return saida


def itens(cnpj: str, ano: int, seq: int) -> list[dict]:
    d = _get(ITENS.format(cnpj=cnpj, ano=ano, seq=seq))
    return d or []


def resultados(cnpj: str, ano: int, seq: int, numero_item: int) -> list[dict]:
    d = _get(RESULTADOS.format(cnpj=cnpj, ano=ano, seq=seq, item=numero_item))
    return d or []


_NCP = re.compile(r"^\s*(\d{14})-(\d+)-(\d+)\s*/\s*(\d{4})\s*$")


def parse_ncp(ncp: str):
    """`58200015000183-1-000002/2026` → ('58200015000183', 2026, 2).

    O segundo grupo é o tipo do documento (1 = edital/contratação), descartado.
    Levanta ValueError em vez de adivinhar — o arquivo de consulta permite
    informar cnpj/ano/sequencial explicitamente quando o formato surpreender.
    """
    m = _NCP.match(str(ncp or ""))
    if not m:
        raise ValueError(f"numeroControlePNCP fora do formato esperado: {ncp!r}")
    return m.group(1), int(m.group(4)), int(m.group(3))


def montar_ncp(cnpj: str, ano: int, seq: int) -> str:
    return f"{cnpj}-1-{seq:06d}/{ano}"


def url_publica(cnpj: str, ano: int, seq: int) -> str:
    return URL_PUBLICA.format(cnpj=cnpj, ano=ano, seq=seq)
