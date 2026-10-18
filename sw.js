// Service worker do site — PWA leve para uso em campo (plenário, rua, sinal ruim).
// Estratégias (por tipo de recurso — inalteradas desde a v3):
//   • páginas/CSS/JS/imagens (mesma origem): network-first com fallback ao cache
//     — o site continua sempre fresco (o CI commita código e dados todo dia) e
//     ainda abre offline com a última versão vista;
//   • dados de despesas (índice, meses, estágios, dossiês): network-first — ver
//     DADOS_COERENTES;
//   • demais *.json de dados: stale-while-revalidate ignorando a query string (os
//     painéis pedem com `cache: "no-cache"` desde 2026-09; a normalização fica
//     como rede de segurança para qualquer ?v= que sobreviva). Desde 2026-10, se a
//     versão revalidada difere da servida do cache, a página recebe um postMessage
//     {tipo: "dados-novos"} e o comum.js oferece "Atualizar" — antes quem voltava
//     ao site via a base de ontem sem saber;
//   • bases-atualizacao.json: network-first — é a fonte da verdade do "atualizado
//     há N dias" do hub; servido do cache, o hub anunciava as datas da visita
//     anterior e o `cache: "no-cache"` da página não valia de nada.
//
// Arrumação do armazenamento (v4, 2026-10) — até a v3 era um cache único que só crescia:
//   • ESTÁTICOS (CACHE_ESTATICOS): a chave inclui a query (`comum.js?v=11`, páginas
//     com filtros na URL). Ao gravar um recurso, as entradas do MESMO caminho com
//     outra query são apagadas — fica só a última versão vista de cada arquivo
//     (antes, cada `?v=` novo e cada combinação de filtros virava uma entrada eterna);
//   • DADOS (CACHE_DADOS, todo *.json): teto de TETO_DADOS entradas, descartando as
//     gravadas há mais tempo (LRU simples: `Cache.keys()` devolve na ordem de inserção
//     e um `put` na mesma chave move a entrada para o fim). Os dossiês e meses de
//     despesas acumulavam sem limite;
//   • `activate` apaga qualquer cache cujo nome não seja um dos dois atuais (inclui o
//     antigo `gabinete-v3`). Mudou a estratégia ou o layout? Suba o sufixo `-vN`.
"use strict";

const CACHE_ESTATICOS = "gabinete-estaticos-v4";
const CACHE_DADOS = "gabinete-dados-v4";
const CACHES_ATUAIS = [CACHE_ESTATICOS, CACHE_DADOS];
const TETO_DADOS = 60;

// Dados de despesas que precisam ser do MESMO export: o índice aponta para meses,
// estágios e dossiês; com stale-while-revalidate a página podia montar o índice de
// hoje com o mês de ontem (ou o contrário). Rede primeiro; o cache só vale offline.
const DADOS_COERENTES = /\/(despesas-index\.json|despesas\/.+\.json|favorecidos\/.+\.json)$/;

// Núcleo pré-cacheado na instalação (melhor esforço: um 404 não derruba o resto).
const NUCLEO = [
  "./",
  "./index.html",
  "./despesas.html",
  "./endividamento.html",
  "./proposituras.html",
  "./legis.html",
  "./precos.html",
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
    caches.open(CACHE_ESTATICOS).then((c) =>
      Promise.allSettled(NUCLEO.map((url) => c.add(url)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(nomes.filter((n) => !CACHES_ATUAIS.includes(n)).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

// URL normalizada para os JSON de dados (derruba ?v=... do cache-busting)
function chaveJson(req) {
  const u = new URL(req.url);
  u.search = "";
  return u.href;
}

// Grava um dado e apara o cache de dados ao teto (as entradas mais antigas saem).
async function gravarDado(chave, resp) {
  const c = await caches.open(CACHE_DADOS);
  await c.put(chave, resp);
  const chaves = await c.keys();
  const excesso = chaves.length - TETO_DADOS;
  if (excesso > 0) await Promise.all(chaves.slice(0, excesso).map((k) => c.delete(k)));
}

// A versão da rede difere da que a página recebeu do cache? (tamanho e, se igual,
// SHA-256 do conteúdo — ETag/Last-Modified do Pages mudam a cada deploy, sem mudança real)
async function mudou(doCache, daRede) {
  const [a, b] = await Promise.all([doCache.arrayBuffer(), daRede.arrayBuffer()]);
  if (a.byteLength !== b.byteLength) return true;
  const [ha, hb] = await Promise.all([crypto.subtle.digest("SHA-256", a), crypto.subtle.digest("SHA-256", b)]);
  const va = new Uint8Array(ha), vb = new Uint8Array(hb);
  return va.some((v, i) => v !== vb[i]);
}

// Avisa a página que pediu o dado (comum.js mostra "Há dados mais novos · Atualizar").
async function avisarDadosNovos(clientId, caminho) {
  if (!clientId) return;
  const cliente = await self.clients.get(clientId);
  if (cliente) cliente.postMessage({ tipo: "dados-novos", caminho });
}

// Grava um estático e apaga as outras versões (outra query) do mesmo caminho.
async function gravarEstatico(req, resp) {
  const c = await caches.open(CACHE_ESTATICOS);
  const irmas = await c.keys(req, { ignoreSearch: true });
  await Promise.all(irmas.filter((k) => k.url !== req.url).map((k) => c.delete(k)));
  await c.put(req, resp);
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // CDN/fontes: deixa a rede cuidar

  if (DADOS_COERENTES.test(url.pathname)) {
    const chave = chaveJson(req);
    e.respondWith(
      fetch(req)
        .then((r) => { if (r.ok) e.waitUntil(gravarDado(chave, r.clone()).catch(() => {})); return r; })
        .catch(() => caches.open(CACHE_DADOS)
          .then((c) => c.match(chave))
          .then((cacheado) => cacheado || Response.error()))
    );
    return;
  }

  if (url.pathname.endsWith(".json") && !url.pathname.endsWith("/bases-atualizacao.json")) {
    // dados: responde do cache na hora (se houver) e revalida por trás
    e.respondWith(
      caches.open(CACHE_DADOS).then(async (c) => {
        const chave = chaveJson(req);
        const cacheado = await c.match(chave);
        // cópia para comparar: o corpo da original vai para a página
        const copia = cacheado ? cacheado.clone() : null;
        const daRede = fetch(req)
          .then((r) => {
            if (r.ok) {
              e.waitUntil(gravarDado(chave, r.clone()).catch(() => {}));
              // a página recebeu a versão do cache: se a da rede for outra, ela está
              // mostrando a base anterior — antes ninguém sabia disso
              if (copia) {
                e.waitUntil(mudou(copia, r.clone())
                  .then((m) => m && avisarDadosNovos(e.clientId, url.pathname))
                  .catch(() => {}));
              }
            }
            return r;
          })
          .catch(() => null);
        // sem o waitUntil o navegador pode encerrar o worker assim que o cache
        // responde — antes de o put acontecer — e o JSON ficaria congelado
        e.waitUntil(daRede);
        return cacheado || daRede.then((r) => r || Response.error());
      })
    );
    return;
  }

  // estáticos: rede primeiro (site sempre fresco), cache como rede de segurança
  e.respondWith(
    fetch(req)
      .then((r) => {
        if (r.ok) e.waitUntil(gravarEstatico(req, r.clone()).catch(() => {}));
        return r;
      })
      .catch(() =>
        // ignoreSearch: o núcleo é pré-cacheado sem ?v=, e as páginas pedem com
        // ?v=N — sem isto, offline na primeira visita abria sem CSS nem JS
        caches.match(req, { ignoreSearch: true }).then((cacheado) =>
          cacheado || (req.mode === "navigate" ? caches.match("./index.html") : Response.error())
        )
      )
  );
});
