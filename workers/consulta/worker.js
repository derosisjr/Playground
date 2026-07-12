/* Worker da Consulta Pública — contadores de voto e fila de sugestões.
   Endpoints:
     POST /voto      {consulta, proposta, voto: "sim"|"nao"|"pular", bairro}
     POST /sugestao  {consulta, texto, bairro}
     GET  /resultados?consulta=X   (Authorization: Bearer CONSULTA_ADMIN_TOKEN)
   Armazenamento: KV (binding CONSULTA_KV). Sem dados pessoais — anonimato de
   projeto (LGPD): não se grava telefone, nome, cookie nem IP (o IP só passa
   pelo rate-limit, com janela de 1 minuto, e não é persistido com o voto). */

const VOTOS = new Set(["sim", "nao", "pular"]);
const MAX_SUGESTAO = 500;
const RATE_LIMIT = 10; // requisições por IP por minuto

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function json(corpo, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status, headers: { "Content-Type": "application/json", ...CORS },
  });
}

// slug simples: evita chave de KV com caracteres estranhos vindos do cliente
function limpo(s, max = 80) {
  return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, max).toLowerCase();
}

async function rateLimit(env, ip) {
  const chave = `rl:${ip}:${Math.floor(Date.now() / 60000)}`;
  const n = parseInt(await env.CONSULTA_KV.get(chave) || "0") + 1;
  await env.CONSULTA_KV.put(chave, String(n), { expirationTtl: 120 });
  return n > RATE_LIMIT;
}

async function incrementar(env, chave) {
  const n = parseInt(await env.CONSULTA_KV.get(chave) || "0") + 1;
  await env.CONSULTA_KV.put(chave, String(n));
}

export default {
  async fetch(req, env) {
    if (req.method === "OPTIONS") return new Response(null, { headers: CORS });
    const url = new URL(req.url);
    const ip = req.headers.get("CF-Connecting-IP") || "0.0.0.0";

    if (req.method === "POST" && (url.pathname === "/voto" || url.pathname === "/sugestao")) {
      if (await rateLimit(env, ip)) return json({ erro: "muitas requisições" }, 429);
      let corpo;
      try { corpo = await req.json(); } catch { return json({ erro: "JSON inválido" }, 400); }
      const consulta = limpo(corpo.consulta);
      const bairro = limpo(corpo.bairro || "nao-informado");
      if (!consulta) return json({ erro: "consulta obrigatória" }, 400);

      if (url.pathname === "/voto") {
        const proposta = limpo(corpo.proposta);
        const voto = String(corpo.voto || "");
        if (!proposta || !VOTOS.has(voto)) return json({ erro: "voto inválido" }, 400);
        await incrementar(env, `voto:${consulta}:${proposta}:${voto}:${bairro}`);
        return json({ ok: true });
      }

      // sugestão
      const texto = String(corpo.texto || "").trim().slice(0, MAX_SUGESTAO);
      if (texto.length < 10) return json({ erro: "sugestão muito curta" }, 400);
      await env.CONSULTA_KV.put(
        `sugestao:${consulta}:${Date.now()}:${crypto.randomUUID().slice(0, 8)}`,
        JSON.stringify({ texto, bairro, quando: new Date().toISOString() }),
      );
      return json({ ok: true });
    }

    if (req.method === "GET" && url.pathname === "/resultados") {
      const auth = req.headers.get("Authorization") || "";
      if (auth !== `Bearer ${env.CONSULTA_ADMIN_TOKEN}`) {
        return json({ erro: "não autorizado" }, 401);
      }
      const consulta = limpo(url.searchParams.get("consulta"));
      if (!consulta) return json({ erro: "consulta obrigatória" }, 400);

      const votos = {};
      let cursor;
      do {
        const pagina = await env.CONSULTA_KV.list({ prefix: `voto:${consulta}:`, cursor });
        for (const k of pagina.keys) {
          votos[k.name] = parseInt(await env.CONSULTA_KV.get(k.name) || "0");
        }
        cursor = pagina.list_complete ? null : pagina.cursor;
      } while (cursor);

      const sugestoes = [];
      cursor = undefined;
      do {
        const pagina = await env.CONSULTA_KV.list({ prefix: `sugestao:${consulta}:`, cursor });
        for (const k of pagina.keys) {
          const v = await env.CONSULTA_KV.get(k.name);
          if (v) sugestoes.push(JSON.parse(v));
        }
        cursor = pagina.list_complete ? null : pagina.cursor;
      } while (cursor);

      return json({ consulta, votos, sugestoes });
    }

    return json({ erro: "rota desconhecida" }, 404);
  },
};
