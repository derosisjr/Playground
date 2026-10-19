// Leitor de lei — Regimento Interno (regimento.html) e Lei Orgânica (lei-organica.html).
// Lê o índice da lei (artigos) e, no Regimento, regimento-notas.json (notas curadas),
// mescla por id e filtra no cliente. O texto do artigo aparece INTEIRO; só as
// notas (jurisprudência/doutrina) ficam recolhidas atrás de um botão.
// A página escolhe a lei pelo data-doc do <main> (sem atributo = Regimento, como sempre).
"use strict";

const DOCS = {
  regimento: {
    indice: "./regimento-index.json",
    notas: "./regimento-notas.json",
    nome: "o Regimento",
    citacao: "Regimento Interno da Câmara Municipal de Santos (Resolução nº 16/2019)",
    dispositivos: false,
  },
  // Lei Orgânica: rótulos com a pontuação oficial ("Art. 10.", "XVIII –"), notas de
  // emenda em `notas` de cada artigo e citação por dispositivo ("58 XVIII" na busca)
  lom: {
    indice: "./lei-organica-index.json",
    notas: null,
    nome: "a Lei Orgânica",
    citacao: "Lei Orgânica do Município de Santos",
    dispositivos: true,
  },
};
const DOC = DOCS[document.querySelector("main")?.dataset.doc] || DOCS.regimento;

const PAGINA = 50;        // artigos por pagina
let ARTIGOS = [];
let NOTAS = {};
let TEM_ADT = false;      // a lei tem Disposições Transitórias (numeração própria)?
let filtrados = [];
let mostrando = 0;
let ultimoCrumb = { t: null, c: null, s: null };  // cabecalhos ja emitidos
let dispAlvo = null;      // dispositivo pedido na busca: { num, par, inc, ali }

const el = (id) => document.getElementById(id);
// utilitários da camada comum (eram cópias locais idênticas em cada painel)
const norm = Comum.norm;
const escapar = Comum.escapar;

// Detecta consulta por numero de artigo: "79", "art 79", "artigo 23-A".
function numeroAlvo(q) {
  const m = q.match(/(?:^|\b)(?:art(?:igo)?\.?\s*)?(\d+(?:-[a-z])?)\b/i);
  return m ? m[1].toLowerCase() : null;
}

// ── Dispositivo (Lei Orgânica): "58 XVIII", "art. 58, inciso XVIII", "73 § 4º-A",
// "4 parágrafo único", "58 XII a". O que vem depois do nº do artigo diz o parágrafo,
// o inciso e a alínea; o bloco achado fica marcado e ganha citação própria.
const NIVEL = { caput: 0, paragrafo: 1, inciso: 2, alinea: 3 };
const ROMANO = /^(?=[ivxlc])(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})$/;
// rótulo sem a pontuação de exibição: "Art. 10." → "Art. 10"; "XVIII –" → "XVIII"; "a)" → "a"
const semPontuacao = (r) => (r || "").replace(/\s*[.–)]\s*$/, "");
// "§ 4º-A." → "4-a"; "§ 10." → "10"; "Parágrafo único." → "unico"
function chaveParagrafo(rotulo) {
  const r = norm(rotulo);
  const m = r.match(/§\s*(\d+)\s*[ºo°]?(?:\s*-\s*([a-z]))?/);
  return m ? m[1] + (m[2] ? "-" + m[2] : "") : (/unico/.test(r) ? "unico" : "");
}

function dispositivoAlvo(bruto) {
  const m = bruto.match(/(?:^|\b)(?:art(?:igo)?\.?\s*)?(\d+(?:-[a-z])?)\b(.*)$/i);
  if (!m) return null;
  let r = " " + norm(m[2]).replace(/[,;“”"'()]/g, " ") + " ";
  const alvo = { num: m[1].toLowerCase() };
  let mm = r.match(/(?:§|\bpar(?:agrafo)?\.?)\s*(\d+)\s*[ºo°]?(?:\s*-\s*([a-z])\b)?/);
  if (mm) alvo.par = mm[1] + (mm[2] ? "-" + mm[2] : "");
  else if ((mm = r.match(/(?:§|\bpar(?:agrafo)?\.?|\bp\.)\s*unico\b/))) alvo.par = "unico";
  if (mm) r = r.slice(mm.index + mm[0].length);
  mm = r.match(/(?:^|\s)(?:inc(?:iso)?\.?\s*)?([ivxlc]+)(?=\s)/);
  if (mm && ROMANO.test(mm[1])) {
    alvo.inc = mm[1].toUpperCase();
    r = r.slice(mm.index + mm[0].length);
    const ma = r.match(/^\s*(?:al(?:inea)?\.?\s*)?([a-z])\)?(?=\s)/);
    if (ma) alvo.ali = ma[1];
  }
  return alvo.par || alvo.inc ? alvo : null;
}

// fim do trecho de um bloco: ele e tudo que está abaixo dele (incisos de um §, alíneas)
function fimDoTrecho(blocos, i) {
  let j = i + 1;
  while (j < blocos.length && NIVEL[blocos[j].tipo] > NIVEL[blocos[i].tipo]) j++;
  return j;
}

// índice do bloco pedido em `alvo` (-1 se o artigo não o tem)
function acharDispositivo(a, alvo) {
  const bs = a.blocos;
  let ini = 1, fim = bs.length, idx = -1;
  if (alvo.par) {
    idx = bs.findIndex((b) => b.tipo === "paragrafo" && chaveParagrafo(b.rotulo) === alvo.par);
    if (idx < 0) return -1;
    ini = idx + 1; fim = fimDoTrecho(bs, idx);
  }
  if (alvo.inc) {
    const j = bs.findIndex((b, k) => k >= ini && k < fim && b.tipo === "inciso" &&
      semPontuacao(b.rotulo) === alvo.inc);
    if (j < 0) return -1;
    idx = j;
    if (alvo.ali) {
      const f = fimDoTrecho(bs, j);
      const k = bs.findIndex((b, n) => n > j && n < f && b.tipo === "alinea" && b.rotulo === alvo.ali + ")");
      if (k >= 0) idx = k;  // alínea que não existe: fica o inciso
    }
  }
  return idx;
}

// "art. 58, XVIII" · "art. 73, § 4º-A" · "art. 4º, parágrafo único" · "art. 58, XII, “a”"
// · "Disposições Transitórias, art. 17, I" (i = índice do bloco; 0 = o artigo)
function referencia(a, i = 0) {
  const art = (a.adt ? "Disposições Transitórias, " : "") +
    semPontuacao(a.blocos[0].rotulo).replace(/^Art\./, "art.");
  if (!i) return art;
  const b = a.blocos[i];
  let par = b.tipo === "paragrafo" ? b : null, inc = null;
  for (let k = i - 1; k > 0 && !par; k--) {
    const x = a.blocos[k];
    if (x.tipo === "paragrafo") par = x;
    else if (x.tipo === "inciso" && b.tipo === "alinea" && !inc) inc = x;
  }
  if (b.tipo === "inciso") inc = b;
  const partes = [art];
  if (par) partes.push(/único/.test(par.rotulo) ? "parágrafo único" : semPontuacao(par.rotulo));
  if (inc) partes.push(semPontuacao(inc.rotulo));
  if (b.tipo === "alinea") partes.push(`“${semPontuacao(b.rotulo)}”`);
  return partes.join(", ");
}

function aplicarFiltros() {
  const bruto = el("q").value.trim();
  const q = norm(bruto);
  const termos = q ? q.split(/\s+/) : [];
  const alvo = numeroAlvo(bruto);
  // "adt 5" / "transitórias 5": o número vale só nas Disposições Transitórias
  const soAdt = TEM_ADT && /\b(?:adt|transitori)/.test(q);
  const casaNumero = (a) => !!alvo && a.numero.toLowerCase() === alvo && (!soAdt || !!a.adt);

  filtrados = ARTIGOS.filter((a) => {
    if (!termos.length) return true;
    if (casaNumero(a)) return true;
    return termos.every((t) => a.texto_busca.includes(t));
  });
  if (alvo) {
    filtrados.sort((a, b) => casaNumero(b) - casaNumero(a));
  }
  dispAlvo = DOC.dispositivos && alvo ? dispositivoAlvo(bruto) : null;
  if (dispAlvo) dispAlvo.casa = casaNumero;

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

function blocoHTML(b, extra = "", marcas = "") {
  const rot = b.rotulo ? `<span class="rot">${escapar(b.rotulo)}</span> ` : "";
  return `<p class="bloco ${escapar(b.tipo)}${extra}">${rot}${escapar(b.texto)}${marcas}</p>`;
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

// ── Notas de emenda (Lei Orgânica): número no ponto do PDF + lista no pé do artigo ──
// mapa índice do bloco → números das notas que vêm depois dele (-1 = antes do caput:
// nota de um cabeçalho, como "Título com denominação alterada…")
function marcasDeNotas(a) {
  const m = new Map();
  (a.notas || []).forEach((n, k) => {
    const chave = n.bloco == null ? -1 : n.bloco;
    if (!m.has(chave)) m.set(chave, []);
    m.get(chave).push(k + 1);
  });
  return m;
}
const supNotas = (nums) => (nums && nums.length
  ? `<sup class="nota-ref"><span class="sr-only">${nums.length > 1 ? "notas" : "nota"} de alteração </span>${nums.join(", ")}</sup>`
  : "");

function alteracoesHTML(a) {
  if (!a.notas || !a.notas.length) return "";
  return `<div class="alteracoes"><p class="alt-tit">Notas de alteração</p><ol>` +
    a.notas.map((n) => `<li>${escapar(n.texto)}</li>`).join("") + "</ol></div>";
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
  const marcas = marcasDeNotas(a);
  // dispositivo pedido na busca: o bloco e o que está abaixo dele ficam marcados
  const iAlvo = dispAlvo && dispAlvo.casa(a) ? acharDispositivo(a, dispAlvo) : -1;
  const fimAlvo = iAlvo > 0 ? fimDoTrecho(a.blocos, iAlvo) : -1;
  const classe = (k) => (iAlvo > 0 && k >= iAlvo && k < fimAlvo ? " alvo" : "");
  const caputHTML = `<p class="bloco caput"><span class="art-num">${escapar(rotuloArt)}</span>${supNotas(marcas.get(-1))} ${escapar(caput ? caput.texto : "")}${supNotas(marcas.get(0))}</p>`;
  const corpo = caputHTML + resto.map((b, k) => blocoHTML(b, classe(k + 1), supNotas(marcas.get(k + 1)))).join("");
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
  // levar o artigo para a sessão: link direto (#art-N) e citação pronta
  const citarAlvo = iAlvo > 0
    ? `\n      <button type="button" class="lnk" data-copiar="citacao" data-art="${escapar(a.id)}" data-bloco="${iAlvo}">Copiar citação: ${escapar(referencia(a, iAlvo))}</button>`
    : "";
  const acoes = `<div class="art-acoes">
      <button type="button" class="lnk" data-copiar="link" data-art="${escapar(a.id)}">Copiar link</button>
      <button type="button" class="lnk" data-copiar="citacao" data-art="${escapar(a.id)}">Copiar citação</button>${citarAlvo}
    </div>`;
  return `${cabecalhosHTML(a)}
    <article class="artigo${notas.length ? " com-nota" : ""}" id="${escapar(a.id)}">
      ${corpo}
      ${caixaNotas}${alteracoesHTML(a)}
      ${acoes}
    </article>`;
}

// "Regimento Interno da Câmara Municipal de Santos (Resolução nº 16/2019), Art. 79: «…»"
// "Lei Orgânica do Município de Santos, art. 58, XVIII: «…»" (i = bloco citado; 0 = artigo)
function citacao(a, i = 0) {
  const [caput, ...resto] = a.blocos;
  if (!DOC.dispositivos) {
    const rotulo = (caput && caput.rotulo) || `Art. ${a.numero}`;
    const texto = [caput ? caput.texto : "", ...resto.map((b) => [b.rotulo, b.texto].filter(Boolean).join(" "))]
      .filter(Boolean).join(" ");
    return `${DOC.citacao}, ${rotulo.replace(/\.$/, "")}: «${texto}»`;
  }
  const bs = a.blocos;
  const texto = [bs[i].texto, ...bs.slice(i + 1, fimDoTrecho(bs, i)).map((b) => `${b.rotulo} ${b.texto}`)]
    .filter(Boolean).join(" ");
  return `${DOC.citacao}, ${referencia(a, i)}: «${texto}»`;
}

function copiarDoArtigo(botao) {
  const a = ARTIGOS.find((x) => x.id === botao.dataset.art);
  if (!a) return;
  if (botao.dataset.copiar === "link") {
    Comum.copiar(location.origin + location.pathname + "#" + a.id, "Link do artigo copiado");
  } else {
    Comum.copiar(citacao(a, Number(botao.dataset.bloco || 0)), "Citação copiada — confira com o texto oficial antes de usar");
  }
}

// Rola até o artigo descontando a barra de busca fixa (topnav + busca + dicas, 140–230 px
// conforme a largura): com scrollIntoView o rótulo "Art. N" e o começo do caput ficavam
// escondidos atrás dela (o scroll-margin-top de 80 px é de antes da barra crescer).
function rolarAte(alvo, suave = false) {
  const barra = document.querySelector(".barra-busca");
  const encosto = barra ? (parseFloat(getComputedStyle(barra).top) || 0) + barra.offsetHeight + 8 : 0;
  const y = alvo.getBoundingClientRect().top + window.scrollY - encosto;
  window.scrollTo({ top: Math.max(0, y), behavior: suave ? "smooth" : "auto" });
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
    const copiar = e.target.closest("[data-copiar]");
    if (copiar) { copiarDoArtigo(copiar); return; }
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
        // "58 XVIII": vai direto ao inciso marcado
        const alvo = primeiro.querySelector(".bloco.alvo");
        if (alvo) alvo.scrollIntoView({ behavior: "smooth", block: "center" });
        else rolarAte(primeiro, true);
        const btn = primeiro.querySelector(".notas-toggle");
        if (btn && btn.getAttribute("aria-expanded") !== "true") alternarNotas(btn);
      }
    }
  });
}

async function init() {
  try {
    const r = await fetch(DOC.indice, { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    ARTIGOS = await r.json();
  } catch (e) {
    el("contagem").textContent = "";
    // #lista é seguro para o retry: o render a reconstrói no sucesso
    Comum.estadoErro("lista",
      `Não foi possível carregar ${DOC.nome}. Verifique a conexão.`, init);
    return;
  }
  TEM_ADT = ARTIGOS.some((a) => a.adt);
  if (DOC.notas) {
    try {
      const r = await fetch(DOC.notas, { cache: "no-cache" });
      if (r.ok) NOTAS = await r.json();
    } catch (e) {
      NOTAS = {};
    }
  }
  // o texto do topo só fala de "interpretação conforme" quando há alguma nota publicada
  const temNotas = Object.entries(NOTAS).some(([k, v]) => !k.startsWith("_") && Array.isArray(v) && v.length);
  if (el("intro-notas")) el("intro-notas").hidden = !temNotas;
  ligarEventos();

  // estado vindo da URL: #art-79 abre direto no artigo (#adt-art-1: Disposições
  // Transitórias); ?q= restaura a busca ("58 XVIII" marca o inciso)
  if (!irParaHash()) {
    const q = Comum.lerParams().get("q");
    if (q) el("q").value = q;
    aplicarFiltros();
    const marcado = document.querySelector(".bloco.alvo");
    if (marcado) {
      marcado.scrollIntoView({ block: "center" });
    } else if (matchMedia("(hover: hover) and (pointer: fine)").matches) {
      // foco automático só com mouse/teclado — em touch abriria o teclado e pularia a página
      el("q").focus();
    }
  }
  // a busca Ctrl+K abre "./lei-organica.html#art-58" (ou "./regimento.html#art-79"): na
  // própria página isso só troca o hash, e o artigo podia nem estar na lista
  window.addEventListener("hashchange", irParaHash);
}

// #art-N (ou #adt-art-N): busca o artigo, rola até ele e abre as notas, se houver.
// Devolve false quando o hash não é de artigo.
function irParaHash() {
  const hash = decodeURIComponent(location.hash.replace("#", ""));
  const alvoHash = hash && ARTIGOS.find((a) => a.id === hash);
  if (!alvoHash) return false;
  el("q").value = (alvoHash.adt ? "adt " : "art ") + alvoHash.numero;
  aplicarFiltros();
  const artigo = document.getElementById(alvoHash.id);
  if (artigo) {
    rolarAte(artigo);
    // a fonte web chega depois e muda a altura do topo e da barra (a 320 px as dicas
    // passam a 3 linhas): o artigo ficava sob a barra. Realinha quando as fontes chegam,
    // se quem lê ainda não mexeu na página (não leva um pulo no meio da leitura)
    let quieto = true;
    const mexeu = () => { quieto = false; };
    const gestos = ["wheel", "touchstart", "keydown", "mousedown"];
    gestos.forEach((g) => window.addEventListener(g, mexeu, { once: true, passive: true }));
    if (document.fonts) document.fonts.ready.then(() => {
      gestos.forEach((g) => window.removeEventListener(g, mexeu));
      if (quieto) rolarAte(artigo);
    });
    const btn = artigo.querySelector(".notas-toggle");
    if (btn && btn.getAttribute("aria-expanded") !== "true") alternarNotas(btn);
  }
  return true;
}

init();
