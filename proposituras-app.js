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
  const situacoes = [...new Set(PROPS.map((p) => p.situacao).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "pt")
  );

  for (const s of subtipos) el("subtipo").add(new Option(s, s));
  for (const a of anos) el("ano").add(new Option(a, a));
  for (const a of autores) el("autor").add(new Option(a, a));
  for (const s of situacoes) el("situacao").add(new Option(s, s));
}

function aplicarFiltros() {
  const q = norm(el("q").value).trim();
  const termos = q ? q.split(/\s+/) : [];
  const subtipo = el("subtipo").value;
  const ano = el("ano").value;
  const autor = el("autor").value;
  const situacao = el("situacao").value;

  filtradas = PROPS.filter((p) => {
    if (subtipo && p.subtipo !== subtipo) return false;
    if (ano && String(p.ano) !== ano) return false;
    if (autor && p.autor !== autor) return false;
    if (situacao && p.situacao !== situacao) return false;
    if (termos.length) {
      const alvo = norm(
        [p.numero, p.ano, p.subtipo, p.ementa, p.autor, p.situacao, p.local_atual].join(" ")
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

function linhaHTML(p) {
  const local = p.local_atual
    ? `<div class="tags">${escapar(p.local_atual)}</div>`
    : "";
  const sit = p.situacao
    ? `<span class="sit-badge">${escapar(p.situacao)}</span>${local}`
    : local;
  const pdf = p.url_pdf
    ? `<a class="pdf" href="${escapar(p.url_pdf)}" target="_blank" rel="noopener">PDF ↗</a>`
    : "";
  const det = p.url_detalhes
    ? `<a class="det" href="${escapar(p.url_detalhes)}" target="_blank" rel="noopener">Detalhes ↗</a>`
    : "";
  return `<tr>
    <td><span class="tipo-badge">${escapar(p.subtipo)}</span></td>
    <td class="num">${escapar(p.numero)}</td>
    <td>${escapar(p.data_propositura)}</td>
    <td>${escapar(p.autor)}</td>
    <td>${escapar(p.ementa)}</td>
    <td>${sit}</td>
    <td>${det}${det && pdf ? "<br />" : ""}${pdf}</td>
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
  ["q", "subtipo", "ano", "autor", "situacao"].forEach((id) =>
    el(id).addEventListener("input", aplicarFiltros)
  );
  el("mais").addEventListener("click", renderizarMais);
  aplicarFiltros();
}

init();
