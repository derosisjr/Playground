# Escuta Pública (`consulta/` + `consulta.html` + `workers/consulta/`)

Votação leve estilo Pol.is enxuto: uma proposta por vez (Concordo / Discordo /
Pular), recorte por bairro, sugestões abertas. **É escuta, não plebiscito** —
a metodologia e os limites estão publicados na própria página.

Peças:
- `consulta/consultas/<slug>.json` — definição da consulta (propostas, bairros,
  período). Publicar/editar = commitar. Piloto: `prioridades-2026`.
- `consulta.html` + `consulta-app.js` — a "cédula" (mobile-first; 1 voto por
  proposta por navegador via localStorage; sem nome/telefone/cookie).
- `workers/consulta/` — Worker Cloudflare + KV que conta votos e guarda
  sugestões (setup em `workers/consulta/README.md`).
- `consulta/apurar.py` — baixa os contadores (autenticado), publica a fita de
  consenso em `consulta-resultados.json` (raiz, versionado), gera relatório
  `.md` (sugestões entram SÓ no relatório, para moderação humana) e, com
  `--email`, envia aos assessores. Recorte por bairro só com **N ≥ 30**.

## Ativação (pendências manuais)
1. Deploy do worker (ver `workers/consulta/README.md`) — conta Cloudflare grátis.
2. Colar a URL do worker em `WORKER_URL` no `consulta-app.js` (e exportar
   `CONSULTA_WORKER_URL`/`CONSULTA_ADMIN_TOKEN` p/ o apurar.py).
3. Conferir `ativa`/`periodo` no JSON da consulta.

Enquanto `WORKER_URL` estiver vazio a página funciona em modo demonstração
(vota localmente e avisa "consulta ainda não está no ar").

## Apuração
```bash
CONSULTA_WORKER_URL=https://... CONSULTA_ADMIN_TOKEN=... \
  python consulta/apurar.py prioridades-2026 --dry-run
python consulta/apurar.py prioridades-2026 --email   # fecha e avisa assessores
```

Limitações conhecidas (documentadas de propósito): votação anônima na web é
manipulável por quem insistir (rate-limit 10 req/min/IP + 1 voto/navegador são
mitigação, não prova); o contador do KV é eventualmente consistente — sob
concorrência alta pode subcontar de leve. Para o volume esperado de uma escuta
de bairro, irrelevante; se um dia virar problema, migrar p/ Durable Objects.
