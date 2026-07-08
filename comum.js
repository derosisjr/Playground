// Camada comum do site — topbar, estado na URL e export CSV.
// Sem build: script clássico, expõe window.Comum.
"use strict";

window.Comum = (() => {
  const PAGINAS = [
    ["index.html", "Início", "inicio"],
    ["despesas.html", "Despesas", ""],
    ["proposituras.html", "Proposituras", ""],
    ["legis.html", "Legislação", ""],
    ["requerimentos.html", "Requerimentos", ""],
    ["regimento.html", "Regimento", ""],
  ];

  const escapar = (s) =>
    (s == null ? "" : String(s)).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Injeta a barra de navegação no topo. `atual` = nome do arquivo da página.
  function topbar(atual) {
    const nav = document.createElement("nav");
    nav.className = "topnav";
    nav.setAttribute("aria-label", "Painéis do site");
    nav.innerHTML = '<div class="topnav-in">' + PAGINAS.map(([arq, nome, extra]) => {
      const cls = [extra, arq === atual ? "atual" : ""].filter(Boolean).join(" ");
      const attrs = (cls ? ` class="${cls}"` : "") + (arq === atual ? ' aria-current="page"' : "");
      return `<a href="./${arq}"${attrs}>${escapar(nome)}</a>`;
    }).join("") + "</div>";
    document.body.prepend(nav);
  }

  // Estado na URL (links compartilháveis): lê/grava querystring sem recarregar.
  function lerParams() {
    return new URLSearchParams(location.search);
  }
  function gravarParams(obj) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(obj)) if (v) p.set(k, v);
    const qs = p.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
  }

  // CSV no dialeto Excel pt-BR (`;`, BOM, CRLF) — mesmo do painel de Despesas.
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

  return { topbar, lerParams, gravarParams, exportarCsv, escapar };
})();
