// Painel da Base de Proposituras — lê proposituras-index.json e filtra no cliente.
"use strict";

const PAGINA = 200; // quantas linhas renderizar por vez
let PROPS = [];
let filtradas = [];
let mostrando = 0;

const el = (id) => document.getElementById(id);
const norm = (s) =>
  (s || "")
    .toString()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");

function preencherSelects() {
  const subtipos = [...new Set(PROPS.map((p) => p.subtipo).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "pt")
  );
  const anos = [...new Set(PROPS.map((p) => p.ano).filter(Boolean))].sort((a, b) => b - a);
  const autores = [...new Set(PROPS.map((p) => p.autor).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "pt")
  );
  const locais = [...new Set(PROPS.map((p) => p.local_atual).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "pt")
  );

  for (const s of subtipos) el("subtipo").add(new Option(s, s));
  for (const a of anos) el("ano").add(new Option(a, a));
  for (const a of autores) el("autor").add(new Option(a, a));
  for (const l of locais) el("local").add(new Option(l, l));
}

// ── Chips de subtipo ──────────────────────────────────────────────────────────
function montarChips() {
  const cont = el("chips");
  const subtipos = [...new Set(PROPS.map((p) => p.subtipo).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "pt")
  );
  cont.innerHTML = "";
  for (const s of subtipos) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.dataset.subtipo = s;
    b.setAttribute("aria-pressed", "false");
    b.innerHTML = `${escapar(s)} <span class="n" data-chip="${escapar(s)}">0</span>`;
    b.addEventListener("click", () => {
      // alterna: se já estava selecionado, limpa
      el("subtipo").value = el("subtipo").value === s ? "" : s;
      aplicarFiltros();
    });
    cont.appendChild(b);
  }
}

function atualizarChips() {
  const ativo = el("subtipo").value;
  // contagem por subtipo respeita os demais filtros (exceto o próprio subtipo)
  const base = filtrarBase({ ignorarSubtipo: true });
  const cont = {};
  for (const p of base) cont[p.subtipo] = (cont[p.subtipo] || 0) + 1;
  for (const chip of el("chips").querySelectorAll(".chip")) {
    const s = chip.dataset.subtipo;
    chip.setAttribute("aria-pressed", String(ativo === s));
    chip.querySelector(".n").textContent = (cont[s] || 0).toLocaleString("pt-BR");
  }
}

// ── Filtragem ───────────────────────────────────────────────────────────────
function filtrarBase({ ignorarSubtipo = false } = {}) {
  const q = norm(el("q").value).trim();
  const termos = q ? q.split(/\s+/) : [];
  const subtipo = el("subtipo").value;
  const ano = el("ano").value;
  const autor = el("autor").value;
  const local = el("local").value;

  return PROPS.filter((p) => {
    if (!ignorarSubtipo && subtipo && p.subtipo !== subtipo) return false;
    if (ano && String(p.ano) !== ano) return false;
    if (autor && p.autor !== autor) return false;
    if (local && p.local_atual !== local) return false;
    if (termos.length) {
      const alvo = norm(
        [p.numero, p.ano, p.subtipo, p.ementa, p.autor, p.local_atual].join(" ")
      );
      if (!termos.every((t) => alvo.includes(t))) return false;
    }
    return true;
  });
}

function aplicarFiltros() {
  filtradas = filtrarBase();
  atualizarResumo(filtradas);
  atualizarChips();

  mostrando = 0;
  el("corpo").innerHTML = "";
  renderizarMais();
  el("vazio").hidden = filtradas.length > 0;
  el("csv").disabled = filtradas.length === 0;
  Comum.gravarParams({
    q: el("q").value.trim(),
    subtipo: el("subtipo").value,
    ano: el("ano").value,
    autor: el("autor").value,
    local: el("local").value,
  });
}

// ── Cards de resumo ─────────────────────────────────────────────────────────
function atualizarResumo(lista) {
  const total = lista.length;
  const autores = new Set(lista.map((p) => p.autor).filter(Boolean)).size;
  const anos = lista.map((p) => p.ano).filter(Boolean);
  const anoMin = anos.length ? Math.min(...anos) : "—";
  const anoMax = anos.length ? Math.max(...anos) : "—";

  const porLocal = {};
  for (const p of lista) if (p.local_atual) porLocal[p.local_atual] = (porLocal[p.local_atual] || 0) + 1;
  let topLocal = "—", topLocalN = 0;
  for (const [k, v] of Object.entries(porLocal)) if (v > topLocalN) { topLocal = k; topLocalN = v; }

  const cards = [
    { rotulo: "Proposituras", valor: total.toLocaleString("pt-BR"), sub: "tipo Projeto" },
    { rotulo: "Autores distintos", valor: autores.toLocaleString("pt-BR"), sub: "no filtro atual" },
    { rotulo: "Período", valor: anoMin === anoMax ? `${anoMin}` : `${anoMin}–${anoMax}`, sub: "ano da propositura" },
    { rotulo: "Local mais frequente", valor: topLocalN ? topLocalN.toLocaleString("pt-BR") : "—", sub: topLocal },
  ];
  el("stats").innerHTML = cards
    .map((c) => `<div class="stat">
        <div class="rotulo">${escapar(c.rotulo)}</div>
        <div class="valor">${escapar(c.valor)}</div>
        <div class="sub" title="${escapar(c.sub)}">${escapar(c.sub)}</div>
      </div>`)
    .join("");
}

// ── Tabela ────────────────────────────────────────────────────────────────────
function linhaHTML(p) {
  const local = p.local_atual
    ? `<span class="sit-badge">${escapar(p.local_atual)}</span>`
    : "";
  const pdf = p.url_pdf
    ? `<a class="pdf" href="${escapar(p.url_pdf)}" target="_blank" rel="noopener">PDF ↗</a>`
    : "";
  const det = p.url_detalhes
    ? `<a class="det" href="${escapar(p.url_detalhes)}" target="_blank" rel="noopener">Detalhes ↗</a>`
    : "";
  return `<tr>
    <td data-label="Subtipo"><span class="tipo-badge">${escapar(p.subtipo)}</span></td>
    <td data-label="Número" class="num">${escapar(p.numero)}</td>
    <td data-label="Data">${escapar(p.data_propositura)}</td>
    <td data-label="Autor">${escapar(p.autor)}</td>
    <td data-label="Ementa"><div class="ementa">${escapar(p.ementa)}</div></td>
    <td data-label="Local">${local}</td>
    <td data-label="Links">${det}${det && pdf ? "<br />" : ""}${pdf}</td>
  </tr>`;
}

function renderizarMais() {
  const fim = Math.min(mostrando + PAGINA, filtradas.length);
  const html = filtradas.slice(mostrando, fim).map(linhaHTML).join("");
  el("corpo").insertAdjacentHTML("beforeend", html);
  mostrando = fim;
  el("mais").hidden = mostrando >= filtradas.length;
  el("contagem").textContent =
    `${filtradas.length.toLocaleString("pt-BR")} propositura(s) — exibindo ${mostrando.toLocaleString("pt-BR")}`;
  el("contagem").classList.remove("pulsa"); void el("contagem").offsetWidth;
  el("contagem").classList.add("pulsa");
}

// ── Exportar CSV do resultado filtrado ──────────────────────────────────────
function exportarCSV() {
  if (!filtradas.length) return;
  const cols = ["subtipo", "numero", "ano", "data_propositura", "autor", "ementa", "local_atual", "url_detalhes", "url_pdf"];
  const esc = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
  const linhas = [cols.join(",")];
  for (const p of filtradas) linhas.push(cols.map((c) => esc(p[c])).join(","));
  const blob = new Blob(["﻿" + linhas.join("\r\n")], { type: "text/csv;charset=utf-8;" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `proposituras-filtro-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function limparFiltros() {
  el("q").value = "";
  for (const id of ["subtipo", "ano", "autor", "local"]) el(id).value = "";
  aplicarFiltros();
}

function escapar(s) {
  return (s == null ? "" : String(s)).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function init() {
  try {
    const resp = await fetch("./proposituras-index.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    PROPS = await resp.json();
  } catch (e) {
    el("contagem").textContent =
      "Não foi possível carregar proposituras-index.json. Rode proposituras/export.py para gerá-lo.";
    return;
  }
  preencherSelects();
  montarChips();
  // estado vindo da URL (link compartilhável) — antes do primeiro render
  const p = Comum.lerParams();
  for (const id of ["q", "subtipo", "ano", "autor", "local"]) {
    const v = p.get(id);
    if (v) el(id).value = v;
  }
  ["q", "subtipo", "ano", "autor", "local"].forEach((id) =>
    el(id).addEventListener("input", aplicarFiltros)
  );
  el("mais").addEventListener("click", renderizarMais);
  el("csv").addEventListener("click", exportarCSV);
  el("limpar").addEventListener("click", limparFiltros);
  aplicarFiltros();
}

init();
