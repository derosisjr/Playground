// Camada comum do site — topbar, estado na URL, export CSV e busca universal (⌘K).
// Sem build: script clássico, expõe window.Comum.
"use strict";

window.Comum = (() => {
  const POP_SANTOS = 433656; // IBGE, Censo 2022 (per capita nos painéis)

  const PAGINAS = [
    ["index.html", "Início", "inicio"],
    ["despesas.html", "Despesas", ""],
    ["proposituras.html", "Proposituras", ""],
    ["legis.html", "Legislação", ""],
    ["requerimentos.html", "Requerimentos", ""],
    ["regimento.html", "Regimento", ""],
  ];
  let paginaAtual = null;

  const escapar = (s) =>
    (s == null ? "" : String(s)).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const norm = (s) =>
    (s || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

  const brlCurto = (v) => {
    const a = Math.abs(v);
    if (a >= 1e9) return "R$ " + (v / 1e9).toFixed(1).replace(".", ",") + " bi";
    if (a >= 1e6) return "R$ " + (v / 1e6).toFixed(1).replace(".", ",") + " mi";
    return "R$ " + Math.round(v).toLocaleString("pt-BR");
  };

  // ── Topbar ──────────────────────────────────────────────────────────────────
  // Injeta a barra de navegação no topo. `atual` = nome do arquivo da página.
  function topbar(atual) {
    paginaAtual = atual;
    const nav = document.createElement("nav");
    nav.className = "topnav";
    nav.setAttribute("aria-label", "Painéis do site");
    nav.innerHTML = '<div class="topnav-in">' + PAGINAS.map(([arq, nome, extra]) => {
      const cls = [extra, arq === atual ? "atual" : ""].filter(Boolean).join(" ");
      const attrs = (cls ? ` class="${cls}"` : "") + (arq === atual ? ' aria-current="page"' : "");
      return `<a href="./${arq}"${attrs}>${escapar(nome)}</a>`;
    }).join("") +
      '<button type="button" class="topnav-busca" aria-label="Buscar em todas as bases">' +
      'Buscar <kbd>Ctrl K</kbd></button></div>';
    document.body.prepend(nav);
    nav.querySelector(".topnav-busca").addEventListener("click", abrirPaleta);
  }

  // ── Estado na URL (links compartilháveis) ───────────────────────────────────
  function lerParams() {
    return new URLSearchParams(location.search);
  }
  function gravarParams(obj) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(obj)) if (v) p.set(k, v);
    const qs = p.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
  }

  // ── CSV no dialeto Excel pt-BR (`;`, BOM, CRLF) ─────────────────────────────
  function exportarCsv(nomeArquivo, cabecalhos, linhas) {
    const sep = ";";
    const esc = (v) => {
      const s = String(v ?? "");
      return /[";\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const out = [cabecalhos.map(esc).join(sep)];
    for (const r of linhas) out.push(r.map(esc).join(sep));
    const blob = new Blob(["﻿" + out.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = nomeArquivo;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ── Busca universal (⌘K / Ctrl+K / "/") ─────────────────────────────────────
  // Fontes carregadas SOB DEMANDA no 1º uso e cacheadas em memória.
  // Cada item vira {t: título, s: subtítulo, url, h: haystack normalizado}.
  const FONTES = [
    { id: "regimento", rotulo: "Regimento Interno", url: "./regimento-index.json",
      mapear: (d) => d.map((a) => ({
        t: "Art. " + a.numero,
        s: ((a.blocos && a.blocos[0] && a.blocos[0].texto) || "").slice(0, 110),
        url: "./regimento.html#" + a.id,
        h: norm("art artigo " + a.numero + " " + (a.texto_busca || "")),
        numArt: String(a.numero).toLowerCase(),
      })) },
    { id: "proposituras", rotulo: "Proposituras", url: "./proposituras-index.json",
      mapear: (d) => d.map((p) => ({
        t: (p.subtipo || "Projeto") + " " + p.numero,
        s: (p.ementa || "").slice(0, 110),
        url: "./proposituras.html?q=" + encodeURIComponent(p.numero || ""),
        h: norm([p.subtipo, p.numero, p.ementa, p.autor].join(" ")),
      })) },
    { id: "legis", rotulo: "Legislação", url: "./legis-index.json",
      mapear: (d) => d.map((n) => ({
        t: (n.tipo || "Norma") + " " + n.numero + "/" + n.ano,
        s: (n.ementa || n.titulo || "").slice(0, 110),
        url: "./legis.html?q=" + encodeURIComponent(n.numero || "") + "&ano=" + (n.ano || ""),
        h: norm([n.tipo, n.numero, n.ano, n.ementa, n.tags].join(" ")),
      })) },
    { id: "requerimentos", rotulo: "Requerimentos", url: "./requerimentos-index.json",
      mapear: (d) => d.map((i) => ({
        t: "Requerimento " + i.numero,
        s: (i.assunto || "").slice(0, 110),
        url: "./requerimentos.html?q=" + encodeURIComponent(i.numero || ""),
        h: norm([i.numero, i.assunto, i.ano].join(" ")),
      })) },
    { id: "favorecidos", rotulo: "Despesas · favorecidos", url: "./despesas-index.json",
      mapear: (d) => (d.top_favorecidos || []).map((f) => ({
        t: f.nome,
        s: brlCurto(f.valor) + " no mandato",
        // com dossiê pré-computado abre o raio-X; sem, cai na busca do painel
        url: f.slug ? "./favorecido.html?f=" + encodeURIComponent(f.slug)
                    : "./despesas.html?q=" + encodeURIComponent(f.nome) + "#favorecidos",
        h: norm(f.nome),
      })) },
  ];
  const cacheFontes = {};     // id -> array de itens (ou "erro")
  let carregouFontes = false;
  let paletaFundo = null, paletaInput = null, paletaRes = null;
  let planos = [];            // resultados achatados p/ navegação por teclado
  let sel = 0;

  function carregarFontes() {
    if (carregouFontes) return;
    carregouFontes = true;
    for (const f of FONTES) {
      fetch(f.url, { cache: "no-cache" })
        .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then((d) => { cacheFontes[f.id] = f.mapear(d); })
        .catch((e) => { cacheFontes[f.id] = "erro"; console.warn("paleta:", f.id, e.message); })
        .finally(() => { if (paletaFundo && !paletaFundo.hidden) renderPaleta(); });
    }
  }

  // "art 79" / "artigo 23-a" / "79" → busca direta por número de artigo
  function alvoArtigo(q) {
    const m = q.trim().match(/^(?:art(?:igo)?\.?\s*)?(\d+(?:-[a-z])?)$/i);
    return m ? m[1].toLowerCase() : null;
  }

  function buscarPaleta(q) {
    const nq = norm(q).trim();
    if (!nq) return [];
    const termos = nq.split(/\s+/);
    const art = alvoArtigo(q);
    const grupos = [];
    for (const f of FONTES) {
      const itens = cacheFontes[f.id];
      if (itens === "erro") continue;
      if (!itens) { grupos.push({ f, carregando: true, hits: [] }); continue; }
      let hits;
      if (art && f.id === "regimento") {
        hits = itens.filter((i) => i.numArt === art);
        if (!hits.length) hits = itens.filter((i) => termos.every((t) => i.h.includes(t)));
      } else {
        hits = itens.filter((i) => termos.every((t) => i.h.includes(t)));
      }
      if (hits.length) grupos.push({ f, hits: hits.slice(0, 5) });
    }
    if (art) grupos.sort((a, b) => (b.f.id === "regimento") - (a.f.id === "regimento"));
    return grupos;
  }

  function renderPaleta() {
    const q = paletaInput.value;
    const grupos = buscarPaleta(q);
    planos = [];
    if (!norm(q).trim()) {
      paletaRes.innerHTML = '<div class="paleta-vazio">Digite para buscar em Despesas, ' +
        "Proposituras, Legislação, Requerimentos e Regimento.<br>" +
        'Dica: <b>art 79</b> abre o artigo direto.</div>';
      return;
    }
    if (!grupos.length) {
      paletaRes.innerHTML = '<div class="paleta-vazio">Nada encontrado nas 5 bases.</div>';
      return;
    }
    let html = "";
    for (const g of grupos) {
      html += `<div class="paleta-grupo">${escapar(g.f.rotulo)}` +
        (g.carregando ? ' <span class="paleta-carregando">carregando…</span>' : "") + "</div>";
      for (const h of g.hits) {
        const i = planos.length;
        planos.push(h);
        html += `<a class="paleta-item${i === sel ? " sel" : ""}" href="${escapar(h.url)}" ` +
          `data-i="${i}" role="option" aria-selected="${i === sel}">` +
          `<span class="pi-t">${escapar(h.t)}</span>` +
          (h.s ? `<span class="pi-s">${escapar(h.s)}</span>` : "") + "</a>";
      }
    }
    paletaRes.innerHTML = html;
  }

  function montarPaleta() {
    if (paletaFundo) return;
    paletaFundo = document.createElement("div");
    paletaFundo.className = "paleta-fundo";
    paletaFundo.hidden = true;
    paletaFundo.innerHTML =
      '<div class="paleta" role="dialog" aria-modal="true" aria-label="Busca em todas as bases">' +
      '<input class="paleta-q" type="search" autocomplete="off" spellcheck="false" ' +
      'placeholder="Buscar em tudo: favorecido, lei, projeto, art. 79…" />' +
      '<div class="paleta-res" role="listbox"></div>' +
      '<div class="paleta-dicas"><span>↑↓ navegar</span><span>↵ abrir</span><span>esc fechar</span></div>' +
      "</div>";
    document.body.appendChild(paletaFundo);
    paletaInput = paletaFundo.querySelector(".paleta-q");
    paletaRes = paletaFundo.querySelector(".paleta-res");

    paletaInput.addEventListener("input", () => { sel = 0; renderPaleta(); });
    paletaFundo.addEventListener("mousedown", (e) => {
      if (e.target === paletaFundo) fecharPaleta();
    });
    paletaRes.addEventListener("mousemove", (e) => {
      const a = e.target.closest(".paleta-item");
      if (a && +a.dataset.i !== sel) { sel = +a.dataset.i; marcarSel(); }
    });
    paletaInput.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, planos.length - 1); marcarSel(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); marcarSel(); }
      else if (e.key === "Enter" && planos[sel]) { e.preventDefault(); location.href = planos[sel].url; }
      else if (e.key === "Escape") { e.preventDefault(); fecharPaleta(); }
    });
  }

  function marcarSel() {
    paletaRes.querySelectorAll(".paleta-item").forEach((a) => {
      const ativo = +a.dataset.i === sel;
      a.classList.toggle("sel", ativo);
      a.setAttribute("aria-selected", String(ativo));
      if (ativo) a.scrollIntoView({ block: "nearest" });
    });
  }

  function abrirPaleta() {
    montarPaleta();
    carregarFontes();
    paletaFundo.hidden = false;
    document.body.style.overflow = "hidden";
    sel = 0;
    paletaInput.value = "";
    renderPaleta();
    paletaInput.focus();
  }

  function fecharPaleta() {
    if (!paletaFundo) return;
    paletaFundo.hidden = true;
    document.body.style.overflow = "";
  }

  // Atalhos globais: Ctrl+K / ⌘K sempre; "/" onde não conflita com atalho local
  document.addEventListener("keydown", (e) => {
    const digitando = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      (paletaFundo && !paletaFundo.hidden) ? fecharPaleta() : abrirPaleta();
    } else if (e.key === "/" && !digitando && paginaAtual !== "regimento.html") {
      // no Regimento, "/" foca a busca local (atalho de plenário) — não interceptar
      e.preventDefault();
      abrirPaleta();
    }
  });

  return { topbar, lerParams, gravarParams, exportarCsv, escapar, abrirPaleta, POP_SANTOS };
})();
