// Camada comum do site — topbar, estado na URL, export CSV e busca universal (⌘K).
// Sem build: script clássico, expõe window.Comum.
"use strict";

window.Comum = (() => {
  const POP_SANTOS = 433656; // IBGE, Censo 2022 (per capita nos painéis)

  const PAGINAS = [
    ["index.html", "Início", "inicio"],
    ["despesas.html", "Despesas", ""],
    ["endividamento.html", "Endividamento", ""],
    ["proposituras.html", "Proposituras", ""],
    ["legis.html", "Legislação", ""],
    ["requerimentos.html", "Requerimentos", ""],
    ["regimento.html", "Regimento", ""],
    ["indicadores.html", "Indicadores", ""],
    ["consulta.html", "Escuta Pública", ""],
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
      'Buscar <kbd>Ctrl K</kbd></button>' +
      '<button type="button" class="topnav-tema" aria-label="Alternar tema claro/escuro">' +
      (temaAtual() === "escuro" ? "☀" : "🌙") + "</button></div>";
    document.body.prepend(nav);
    nav.querySelector(".topnav-busca").addEventListener("click", abrirPaleta);
    nav.querySelector(".topnav-tema").addEventListener("click", alternarTema);
  }

  // ── Tema claro/escuro ───────────────────────────────────────────────────────
  // O atributo inicial é aplicado por um snippet inline no <head> (anti-flash);
  // aqui fica só a troca. Páginas com Chart.js escutam "temamudou" e repintam
  // os gráficos em memória — sem reload, preservando rolagem e aba ativa.
  function temaAtual() {
    return document.documentElement.dataset.tema === "escuro" ? "escuro" : "claro";
  }
  function alternarTema() {
    const novo = temaAtual() === "escuro" ? "claro" : "escuro";
    try { localStorage.setItem("tema", novo); } catch (e) { /* modo privado */ }
    if (novo === "escuro") document.documentElement.dataset.tema = "escuro";
    else delete document.documentElement.dataset.tema;
    document.querySelectorAll(".topnav-tema, .hub-tema").forEach((b) =>
      b.textContent = novo === "escuro" ? "☀" : "🌙");
    window.dispatchEvent(new CustomEvent("temamudou", { detail: { escuro: novo === "escuro" } }));
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

  // ── Toast (aviso passageiro, no lugar de alert()) ───────────────────────────
  let toastEl = null, toastTimer = null;
  function toast(msg) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "toast-comum";
      toastEl.setAttribute("role", "status");
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.add("ver");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("ver"), 2600);
  }

  // ── Estado de erro padrão com "Tentar de novo" ──────────────────────────────
  // alvo: elemento ou id; aoTentar: callback que refaz a carga (ex.: init).
  function estadoErro(alvo, mensagem, aoTentar) {
    const el = typeof alvo === "string" ? document.getElementById(alvo) : alvo;
    if (!el) return;
    el.hidden = false;
    el.innerHTML = `<div class="estado-erro" role="alert"><p>${escapar(mensagem)}</p>` +
      '<button type="button" class="btn">Tentar de novo</button></div>';
    el.querySelector("button").addEventListener("click", aoTentar);
  }

  // ── Acessibilidade de gráficos ──────────────────────────────────────────────
  // Canvas é invisível para leitor de tela (padrão USWDS): dá role="img" +
  // descrição conclusiva e anexa uma tabela equivalente visualmente oculta,
  // gerada do MESMO array que alimenta o gráfico.
  function chartAcessivel(canvas, descricao, cabecalhos, linhas) {
    const c = typeof canvas === "string" ? document.getElementById(canvas) : canvas;
    if (!c || !c.parentNode) return;
    c.setAttribute("role", "img");
    c.setAttribute("aria-label", descricao);
    const marca = c.id || c.getAttribute("aria-label") || "";
    const ant = c.parentNode.querySelector(`table.sr-only[data-de="${marca}"]`);
    if (ant) ant.remove(); // rerender (troca de filtro/ano) não duplica a tabela
    const t = document.createElement("table");
    t.className = "sr-only";
    t.dataset.de = marca;
    t.innerHTML = "<caption>" + escapar(descricao) + "</caption><thead><tr>" +
      cabecalhos.map((h) => '<th scope="col">' + escapar(h) + "</th>").join("") +
      "</tr></thead><tbody>" +
      linhas.map((r) => "<tr>" + r.map((v) => "<td>" + escapar(v) + "</td>").join("") + "</tr>").join("") +
      "</tbody></table>";
    c.insertAdjacentElement("afterend", t);
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
    { id: "endividamento", rotulo: "Endividamento", url: "./endividamento-index.json",
      mapear: (d) => (d.semaforo || []).map((m) => ({
        t: m.nome,
        s: (m.pct != null ? m.pct.toLocaleString("pt-BR") + "% da RCL · " : "") +
           (m.cor === "verde" ? "dentro do limite" : m.cor === "amarelo" ? "zona de alerta" : "acima do limite"),
        url: "./endividamento.html#semaforo",
        h: norm([m.nome, "divida endividamento lrf semaforo fiscal rcl limite", m.base_legal].join(" ")),
      })).concat([{
        t: "Dívida consolidada de Santos",
        s: d.totais && d.totais.divida ? brlCurto(d.totais.divida) + " · " + (d.ultimo ? d.ultimo.rotulo : "") : "evolução e limites da LRF",
        url: "./endividamento.html",
        h: norm("divida consolidada endividamento precatorios rcl santos"),
      }]) },
    { id: "indicadores", rotulo: "Custo por Resultado", url: "./indicadores-index.json",
      mapear: (d) => Object.entries(d.temas || {}).flatMap(([slug, t]) =>
        (t.indicadores || []).map((i) => ({
          t: i.nome,
          s: (t.nome + " — Santos vs comparáveis · " + (i.fonte || "")).slice(0, 110),
          url: "./indicadores.html?tema=" + slug,
          h: norm([i.nome, t.nome, "indicador custo resultado gasto"].join(" ")),
        })).concat([{
          t: "Gasto por habitante em " + t.nome.toLowerCase(),
          s: "série anual vs cidades de porte similar",
          url: "./indicadores.html?tema=" + slug,
          h: norm("gasto per capita habitante " + t.nome),
        }])) },
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
    // aviso honesto quando alguma base falhou (antes era omitida em silêncio)
    const falhas = FONTES.filter((f) => cacheFontes[f.id] === "erro").map((f) => f.rotulo);
    const avisoFalhas = falhas.length
      ? `<div class="paleta-vazio paleta-falhas">⚠ Fora do ar agora: ${escapar(falhas.join(", "))}.</div>`
      : "";
    if (!norm(q).trim()) {
      paletaRes.innerHTML = '<div class="paleta-vazio">Digite para buscar em Despesas, ' +
        "Proposituras, Legislação, Requerimentos, Regimento, Endividamento e Indicadores.<br>" +
        'Dica: <b>art 79</b> abre o artigo direto.</div>' + avisoFalhas;
      atualizarAtivo();
      return;
    }
    if (!grupos.length) {
      paletaRes.innerHTML = '<div class="paleta-vazio">Nada encontrado nas bases do site.</div>' + avisoFalhas;
      atualizarAtivo();
      return;
    }
    let html = "";
    for (const g of grupos) {
      html += `<div class="paleta-grupo">${escapar(g.f.rotulo)}` +
        (g.carregando ? ' <span class="paleta-carregando">carregando…</span>' : "") + "</div>";
      for (const h of g.hits) {
        const i = planos.length;
        planos.push(h);
        html += `<a class="paleta-item${i === sel ? " sel" : ""}" id="paleta-op-${i}" href="${escapar(h.url)}" ` +
          `data-i="${i}" role="option" aria-selected="${i === sel}">` +
          `<span class="pi-t">${escapar(h.t)}</span>` +
          (h.s ? `<span class="pi-s">${escapar(h.s)}</span>` : "") + "</a>";
      }
    }
    paletaRes.innerHTML = html + avisoFalhas;
    atualizarAtivo();
  }

  // combobox: aponta o leitor de tela para a opção ativa sem mover o foco
  function atualizarAtivo() {
    if (!paletaInput) return;
    if (planos.length) paletaInput.setAttribute("aria-activedescendant", "paleta-op-" + sel);
    else paletaInput.removeAttribute("aria-activedescendant");
  }

  function montarPaleta() {
    if (paletaFundo) return;
    paletaFundo = document.createElement("div");
    paletaFundo.className = "paleta-fundo";
    paletaFundo.hidden = true;
    paletaFundo.innerHTML =
      '<div class="paleta" role="dialog" aria-modal="true" aria-label="Busca em todas as bases">' +
      '<input class="paleta-q" type="search" autocomplete="off" spellcheck="false" ' +
      'role="combobox" aria-expanded="true" aria-haspopup="listbox" ' +
      'aria-controls="paleta-listbox" aria-autocomplete="list" ' +
      'placeholder="Buscar em tudo: favorecido, lei, projeto, art. 79…" />' +
      '<div class="paleta-res" id="paleta-listbox" role="listbox" aria-label="Resultados"></div>' +
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
      // paleta de comandos: o foco fica preso no input (setas navegam, Tab não escapa
      // do diálogo — sem isso o Tab vazava p/ a página atrás do modal).
      else if (e.key === "Tab") { e.preventDefault(); }
    });
  }

  function marcarSel() {
    paletaRes.querySelectorAll(".paleta-item").forEach((a) => {
      const ativo = +a.dataset.i === sel;
      a.classList.toggle("sel", ativo);
      a.setAttribute("aria-selected", String(ativo));
      if (ativo) a.scrollIntoView({ block: "nearest" });
    });
    atualizarAtivo();
  }

  let focoAnterior = null;  // p/ devolver o foco a quem abriu a paleta

  function abrirPaleta() {
    montarPaleta();
    carregarFontes();
    focoAnterior = document.activeElement;
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
    // restaura o foco ao elemento que abriu (a11y de teclado/leitor de tela)
    if (focoAnterior && typeof focoAnterior.focus === "function") focoAnterior.focus();
    focoAnterior = null;
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

  // ── PWA: service worker (offline com a última versão vista) ─────────────────
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js")
        .catch(() => { /* contexto sem suporte: o site segue normal, só sem offline */ });
    });
  }

  return { topbar, lerParams, gravarParams, exportarCsv, escapar, abrirPaleta,
           alternarTema, temaAtual, chartAcessivel, toast, estadoErro, POP_SANTOS };
})();
