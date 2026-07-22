// Painel do Regimento Interno — leitura corrida da lei + interpretacao conforme.
// Le regimento-index.json (artigos) e regimento-notas.json (notas curadas),
// mescla por id e filtra no cliente. O texto do artigo aparece INTEIRO; so as
// notas (jurisprudencia/doutrina) ficam recolhidas atras de um botao.
"use strict";

const PAGINA = 50;        // artigos por pagina
let ARTIGOS = [];
let NOTAS = {};
let filtrados = [];
let mostrando = 0;
let ultimoCrumb = { t: null, c: null, s: null };  // cabecalhos ja emitidos

const el = (id) => document.getElementById(id);
const norm = (s) =>
  (s || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

function escapar(s) {
  return (s == null ? "" : String(s)).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// Detecta consulta por numero de artigo: "79", "art 79", "artigo 23-A".
function numeroAlvo(q) {
  const m = q.match(/(?:^|\b)(?:art(?:igo)?\.?\s*)?(\d+(?:-[a-z])?)\b/i);
  return m ? m[1].toLowerCase() : null;
}

function aplicarFiltros() {
  const bruto = el("q").value.trim();
  const q = norm(bruto);
  const termos = q ? q.split(/\s+/) : [];
  const alvo = numeroAlvo(bruto);

  filtrados = ARTIGOS.filter((a) => {
    if (!termos.length) return true;
    if (alvo && a.numero.toLowerCase() === alvo) return true;
    return termos.every((t) => a.texto_busca.includes(t));
  });
  if (alvo) {
    filtrados.sort((a, b) => (b.numero.toLowerCase() === alvo) - (a.numero.toLowerCase() === alvo));
  }

  mostrando = 0;
  ultimoCrumb = { t: null, c: null, s: null };
  el("lista").innerHTML = "";
  renderizarMais();
  el("vazio").hidden = filtrados.length > 0;
  Comum.gravarParams({ q: bruto });
}

function notasDoArtigo(id) {
  const ns = NOTAS[id];
  return Array.isArray(ns) ? ns : [];
}

function badgesHTML(notas) {
  const j = notas.filter((n) => n.tipo === "jurisprudencia").length;
  const d = notas.filter((n) => n.tipo === "doutrina").length;
  let h = "";
  if (j) h += `<span class="badge j">${j} jurisprud${j > 1 ? "ências" : "ência"}</span>`;
  if (d) h += `<span class="badge d">${d} doutrina${d > 1 ? "s" : ""}</span>`;
  return h;
}

function blocoHTML(b) {
  const rot = b.rotulo ? `<span class="rot">${escapar(b.rotulo)}</span> ` : "";
  return `<p class="bloco ${escapar(b.tipo)}">${rot}${escapar(b.texto)}</p>`;
}

function notaHTML(n) {
  const cls = n.tipo === "jurisprudencia" ? "j" : "d";
  const rotulo = n.tipo === "jurisprudencia" ? "Jurisprudência" : "Doutrina";
  const link = n.url
    ? `<div><a href="${escapar(n.url)}" target="_blank" rel="noopener">Abrir fonte ↗</a></div>`
    : "";
  return `<div class="nota ${cls}">
    <div class="nota-tag">${rotulo}</div>
    <div class="nota-fonte">${escapar(n.fonte)}</div>
    <div class="nota-texto">${escapar(n.texto)}</div>
    ${link}
  </div>`;
}

// Cabecalhos estruturais (Titulo/Capitulo/Secao) emitidos quando mudam.
function cabecalhosHTML(a) {
  let h = "";
  if (a.titulo_sup && a.titulo_sup !== ultimoCrumb.t) {
    h += `<h2 class="h-titulo">${escapar(a.titulo_sup)}</h2>`;
    ultimoCrumb = { t: a.titulo_sup, c: null, s: null };
  }
  if (a.capitulo && a.capitulo !== ultimoCrumb.c) {
    h += `<h3 class="h-capitulo">${escapar(a.capitulo)}</h3>`;
    ultimoCrumb.c = a.capitulo; ultimoCrumb.s = null;
  }
  if (a.secao && a.secao !== ultimoCrumb.s) {
    h += `<h4 class="h-secao">${escapar(a.secao)}</h4>`;
    ultimoCrumb.s = a.secao;
  }
  return h;
}

function artigoHTML(a) {
  const notas = notasDoArtigo(a.id);
  const [caput, ...resto] = a.blocos;
  const rotuloArt = caput && caput.rotulo ? caput.rotulo : `Art. ${a.numero}`;
  const caputHTML = `<p class="bloco caput"><span class="art-num">${escapar(rotuloArt)}</span> ${escapar(caput ? caput.texto : "")}</p>`;
  const corpo = caputHTML + resto.map(blocoHTML).join("");
  let caixaNotas = "";
  if (notas.length) {
    caixaNotas = `<div class="notas-box">
      <button class="notas-toggle" aria-expanded="false">
        <span class="nt-ico">⚖</span>
        <span class="nt-label">Interpretação conforme</span>
        <span class="badges">${badgesHTML(notas)}</span>
        <span class="chev">▶</span>
      </button>
      <div class="notas" hidden>${notas.map(notaHTML).join("")}</div>
    </div>`;
  }
  return `${cabecalhosHTML(a)}
    <article class="artigo${notas.length ? " com-nota" : ""}" id="${escapar(a.id)}">
      ${corpo}
      ${caixaNotas}
    </article>`;
}

function renderizarMais() {
  const fim = Math.min(mostrando + PAGINA, filtrados.length);
  const html = filtrados.slice(mostrando, fim).map(artigoHTML).join("");
  el("lista").insertAdjacentHTML("beforeend", html);
  mostrando = fim;
  el("mais").hidden = mostrando >= filtrados.length;
  el("contagem").textContent = `${filtrados.length.toLocaleString("pt-BR")} artigo(s)`;
}

function alternarNotas(botao) {
  const caixa = botao.nextElementSibling;
  const aberto = botao.getAttribute("aria-expanded") === "true";
  botao.setAttribute("aria-expanded", String(!aberto));
  caixa.hidden = aberto;
  botao.classList.toggle("aberto", !aberto);
}

function ligarEventos() {
  el("q").addEventListener("input", aplicarFiltros);
  el("mais").addEventListener("click", renderizarMais);

  el("lista").addEventListener("click", (e) => {
    const btn = e.target.closest(".notas-toggle");
    if (!btn) return;
    alternarNotas(btn);
    // URL compartilhável do artigo aberto
    const art = btn.closest(".artigo");
    if (art && btn.getAttribute("aria-expanded") === "true") {
      history.replaceState(null, "", location.pathname + location.search + "#" + art.id);
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== el("q")) {
      e.preventDefault(); el("q").focus(); el("q").select();
    } else if (e.key === "Escape" && document.activeElement === el("q")) {
      el("q").value = ""; aplicarFiltros();
    } else if (e.key === "Enter" && document.activeElement === el("q")) {
      const primeiro = el("lista").querySelector(".artigo");
      if (primeiro) {
        primeiro.scrollIntoView({ behavior: "smooth", block: "start" });
        const btn = primeiro.querySelector(".notas-toggle");
        if (btn && btn.getAttribute("aria-expanded") !== "true") alternarNotas(btn);
      }
    }
  });
}

async function init() {
  try {
    const r = await fetch("./regimento-index.json", { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    ARTIGOS = await r.json();
  } catch (e) {
    el("contagem").textContent =
      "Não foi possível carregar regimento-index.json. Rode regimento/parser.py para gerá-lo.";
    return;
  }
  try {
    const r = await fetch("./regimento-notas.json", { cache: "no-cache" });
    if (r.ok) NOTAS = await r.json();
  } catch (e) {
    NOTAS = {};
  }
  ligarEventos();

  // estado vindo da URL: #art-79 abre direto no artigo; ?q= restaura a busca
  const hash = decodeURIComponent(location.hash.replace("#", ""));
  const alvoHash = hash && ARTIGOS.find((a) => a.id === hash);
  const q = Comum.lerParams().get("q");
  if (alvoHash) {
    el("q").value = "art " + alvoHash.numero;
  } else if (q) {
    el("q").value = q;
  }
  aplicarFiltros();
  if (alvoHash) {
    const artigo = document.getElementById(alvoHash.id);
    if (artigo) {
      artigo.scrollIntoView({ block: "start" });
      const btn = artigo.querySelector(".notas-toggle");
      if (btn && btn.getAttribute("aria-expanded") !== "true") alternarNotas(btn);
    }
  } else if (matchMedia("(hover: hover) and (pointer: fine)").matches) {
    // foco automático só com mouse/teclado — em touch abriria o teclado e pularia a página
    el("q").focus();
  }
}

init();
