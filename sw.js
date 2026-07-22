// Service worker do site — PWA leve para uso em campo (plenário, rua, sinal ruim).
// Estratégias:
//   • páginas/CSS/JS/imagens (mesma origem): network-first com fallback ao cache
//     — o site continua sempre fresco (o CI commita código e dados todo dia) e
//     ainda abre offline com a última versão vista;
//   • *.json de dados: stale-while-revalidate IGNORANDO a query string — os
//     painéis fazem cache-busting com ?v=..., que sem normalização nunca teria
//     acerto de cache e incharia o storage.
"use strict";

const CACHE = "gabinete-v1";

// Núcleo pré-cacheado na instalação (melhor esforço: um 404 não derruba o resto).
const NUCLEO = [
  "./",
  "./index.html",
  "./despesas.html",
  "./endividamento.html",
  "./proposituras.html",
  "./legis.html",
  "./requerimentos.html",
  "./regimento.html",
  "./indicadores.html",
  "./consulta.html",
  "./favorecido.html",
  "./retrospectiva.html",
  "./comum.css",
  "./comum.js",
  "./favicon.svg",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) =>
      Promise.allSettled(NUCLEO.map((url) => c.add(url)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

// URL normalizada para os JSON de dados (derruba ?v=... do cache-busting)
function chaveJson(req) {
  const u = new URL(req.url);
  u.search = "";
  return u.href;
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // CDN/fontes: deixa a rede cuidar

  if (url.pathname.endsWith(".json")) {
    // dados: responde do cache na hora (se houver) e revalida por trás
    e.respondWith(
      caches.open(CACHE).then(async (c) => {
        const chave = chaveJson(req);
        const cacheado = await c.match(chave);
        const daRede = fetch(req)
          .then((r) => { if (r.ok) c.put(chave, r.clone()); return r; })
          .catch(() => null);
        return cacheado || daRede.then((r) => r || Response.error());
      })
    );
    return;
  }

  // estáticos: rede primeiro (site sempre fresco), cache como rede de segurança
  e.respondWith(
    fetch(req)
      .then((r) => {
        if (r.ok) caches.open(CACHE).then((c) => c.put(req, r.clone()));
        return r;
      })
      .catch(() =>
        caches.match(req).then((cacheado) =>
          cacheado || (req.mode === "navigate" ? caches.match("./index.html") : Response.error())
        )
      )
  );
});
