// Painel da Base de Legislação — lê legis-index.json e filtra no cliente.
"use strict";

const PAGINA = 200; // quantas linhas renderizar por vez
let NORMAS = [];
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
  const tipos = [...new Set(NORMAS.map((n) => n.tipo).filter(Boolean))].sort();
  const anos = [...new Set(NORMAS.map((n) => n.ano).filter(Boolean))].sort((a, b) => b - a);
  const temas = [
    ...new Set(
      NORMAS.flatMap((n) => (n.tags || "").split(";").map((t) => t.trim()).filter(Boolean))
    ),
  ].sort((a, b) => a.localeCompare(b, "pt"));

  for (const t of tipos) el("tipo").add(new Option(t, t));
  for (const a of anos) el("ano").add(new Option(a, a));
  for (const t of temas) el("tema").add(new Option(t, t));
}

function aplicarFiltros() {
  const q = norm(el("q").value).trim();
  const termos = q ? q.split(/\s+/) : [];
  const tipo = el("tipo").value;
  const ano = el("ano").value;
  const tema = norm(el("tema").value);

  filtradas = NORMAS.filter((n) => {
    if (tipo && n.tipo !== tipo) return false;
    if (ano && String(n.ano) !== ano) return false;
    if (tema && !norm(n.tags).includes(tema)) return false;
    if (termos.length) {
      const alvo = norm(
        [n.numero, n.ano, n.titulo, n.ementa, n.tags, n.tipo].join(" ")
      );
      if (!termos.every((t) => alvo.includes(t))) return false;
    }
    return true;
  });

  mostrando = 0;
  el("corpo").innerHTML = "";
  renderizarMais();
  el("vazio").hidden = filtradas.length > 0;
}

function linhaHTML(n) {
  const desc = n.ementa || n.titulo || "";
  const temas = n.tags
    ? `<div class="tags">${escapar(n.tags)}</div>`
    : "";
  return `<tr>
    <td><span class="tipo-badge">${escapar(n.tipo)}</span></td>
    <td class="num">${escapar(n.numero)}</td>
    <td>${escapar(n.ano)}</td>
    <td>${escapar(n.data_norma)}</td>
    <td>${escapar(desc)}${temas}</td>
    <td class="tags">${escapar(n.tags)}</td>
    <td><a class="pdf" href="${escapar(n.url_pdf)}" target="_blank" rel="noopener">PDF ↗</a></td>
  </tr>`;
}

function renderizarMais() {
  const fim = Math.min(mostrando + PAGINA, filtradas.length);
  const html = filtradas.slice(mostrando, fim).map(linhaHTML).join("");
  el("corpo").insertAdjacentHTML("beforeend", html);
  mostrando = fim;
  el("mais").hidden = mostrando >= filtradas.length;
  el("contagem").textContent =
    `${filtradas.length.toLocaleString("pt-BR")} norma(s) — exibindo ${mostrando.toLocaleString("pt-BR")}`;
}

function escapar(s) {
  return (s == null ? "" : String(s)).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function init() {
  try {
    const resp = await fetch("./legis-index.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    NORMAS = await resp.json();
  } catch (e) {
    el("contagem").textContent =
      "Não foi possível carregar legis-index.json. Rode legis/export.py para gerá-lo.";
    return;
  }
  preencherSelects();
  ["q", "tipo", "ano", "tema"].forEach((id) =>
    el(id).addEventListener("input", aplicarFiltros)
  );
  el("mais").addEventListener("click", renderizarMais);
  aplicarFiltros();
}

init();
