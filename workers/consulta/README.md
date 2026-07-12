# Worker da Consulta Pública

Backend mínimo (Cloudflare Workers + KV, plano gratuito) que conta os votos e
recebe sugestões da página `consulta.html`. O site continua 100% estático — só
a contagem vive aqui.

## Setup (uma única vez, ~10 min)

1. Criar conta gratuita em https://dash.cloudflare.com (se ainda não houver).
2. Instalar o wrangler (não precisa de npm no repo — use `npx`):
   ```bash
   npx wrangler login
   ```
3. Criar o namespace KV e colar o `id` gerado no `wrangler.toml`:
   ```bash
   cd workers/consulta
   npx wrangler kv namespace create CONSULTA_KV
   ```
4. Definir o token de administração (usado pelo `consulta/apurar.py`) —
   invente uma senha longa e guarde-a também no ambiente local como
   `CONSULTA_ADMIN_TOKEN`:
   ```bash
   npx wrangler secret put CONSULTA_ADMIN_TOKEN
   ```
5. Publicar:
   ```bash
   npx wrangler deploy
   ```
   A URL final (ex.: `https://consulta-gabinete.<subdominio>.workers.dev`) vai
   na constante `WORKER_URL` de `consulta-app.js` e de `consulta/apurar.py`.

## Endpoints

| Método | Rota | Corpo/Query | Auth |
|---|---|---|---|
| POST | `/voto` | `{consulta, proposta, voto: sim\|nao\|pular, bairro}` | — |
| POST | `/sugestao` | `{consulta, texto (10–500 chars), bairro}` | — |
| GET | `/resultados?consulta=X` | — | `Authorization: Bearer <token>` |

Rate-limit: 10 requisições/IP/minuto. LGPD: nenhum dado pessoal é gravado —
sem nome, telefone, cookie; o IP só participa do rate-limit (chave expira em
2 min) e não é persistido junto ao voto.

## Teste rápido após o deploy

```bash
curl -X POST https://SUA-URL/voto -H "Content-Type: application/json" \
  -d '{"consulta":"piloto","proposta":"p1","voto":"sim","bairro":"gonzaga"}'
curl "https://SUA-URL/resultados?consulta=piloto" \
  -H "Authorization: Bearer SEU_TOKEN"
```
