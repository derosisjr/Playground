# Limites dos bairros de Santos (`santos-bairros.geojson`)

Usado pelo mapa do painel de Indicações (`indicacoes.html`) e pelo normalizador de
bairros do export (`respostas-executivo/bairros.py`), que só publica nomes que existem
aqui.

- **Fonte:** Prefeitura de Santos, GeoServer público
  (`https://egov.santos.sp.gov.br/geoserver/ows`, WFS 2.0, EPSG:4326), camada
  `santos:bairros` ("abairramento oficial do município"); a camada
  `santos:subprefeituras` (Prefeituras Regionais) só marca a área continental.
- **Baixado em:** 18/10/2026 (72 feições, 71 nomes — Barnabé vem duas vezes, com a
  mesma geometria).
- **Licença:** não declarada — o serviço informa `Fees: NONE` e
  `AccessConstraints: NONE`, mas não cita licença de uso. [Verificar]
- **Tratamento** (`preparar_bairros.py`, só biblioteca padrão): Douglas–Peucker com
  tolerância de 4 m, coordenadas com 5 casas (~1 m), feições de mesmo nome juntadas
  num MultiPolygon, conectivos do nome em minúscula ("Chico de Paula"). De 19.200 para
  4.829 vértices (~113 KB).
- **Propriedades:** `nome`, `cdbairro` (código da Prefeitura) e `area_continental`
  (11 bairros: a Prefeitura Regional da Área Continental inclui as ilhas de Barnabé e
  Bagres).

Regerar (só quando a Prefeitura mudar o abairramento — e conferir no diff se algum
nome mudou, porque o normalizador depende deles):

```bash
python geo/preparar_bairros.py --dry-run   # baixa e relata
python geo/preparar_bairros.py             # baixa e grava
python -m unittest discover -s respostas-executivo -p "testes_*.py"
```
