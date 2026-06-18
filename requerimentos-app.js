// Painel de Requerimentos & Respostas — lê requerimentos-index.json e filtra no cliente.
"use strict";

const PAGINA = 200; // quantas linhas renderizar por vez
let ITENS = [];
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
  const anos = [...new Set(ITENS.map((i) => i.ano).filter(Boolean))].sort((a, b) => b - a);
  for (const a of anos) el("ano").add(new Option(a, a));
}

function aplicarFiltros() {
  const q = norm(el("q").value).trim();
  const termos = q ? q.split(/\s+/) : [];
  const ano = el("ano").value;
  const status = el("status").value; // "" | "sim" | "nao"

  filtradas = ITENS.filter((i) => {
    if (ano && String(i.ano) !== ano) return false;
    if (status === "sim" && !i.respondido) return false;
    if (status === "nao" && i.respondido) return false;
    if (termos.length) {
      const alvo = norm([i.numero, i.assunto, i.status, i.ano].join(" "));
      if (!termos.every((t) => alvo.includes(t))) return false;
    }
    return true;
  });

  mostrando = 0;
  el("corpo").innerHTML = "";
  renderizarMais();
  el("vazio").hidden = filtradas.length > 0;
}

function linhaHTML(i) {
  const resposta = i.url_resposta
    ? `<a class="pdf" href="${escapar(i.url_resposta)}" target="_blank" rel="noopener">Resposta ↗</a>`
    : `<span class="pendente">Pendente</span>`;
  return `<tr>
    <td class="num">${escapar(i.numero)}</td>
    <td>${escapar(i.assunto)}</td>
    <td class="data">${escapar(i.data_sessao)}</td>
    <td class="data">${escapar(i.data_resposta)}</td>
    <td class="status">${escapar(i.status)}</td>
    <td>${resposta}</td>
  </tr>`;
}

function renderizarMais() {
  const fim = Math.min(mostrando + PAGINA, filtradas.length);
  const html = filtradas.slice(mostrando, fim).map(linhaHTML).join("");
  el("corpo").insertAdjacentHTML("beforeend", html);
  mostrando = fim;
  el("mais").hidden = mostrando >= filtradas.length;
  const respondidos = filtradas.filter((i) => i.respondido).length;
  el("contagem").textContent =
    `${filtradas.length.toLocaleString("pt-BR")} requerimento(s) — ${respondidos.toLocaleString("pt-BR")} respondido(s) — exibindo ${mostrando.toLocaleString("pt-BR")}`;
}

function escapar(s) {
  return (s == null ? "" : String(s)).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function init() {
  try {
    const resp = await fetch("./requerimentos-index.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    ITENS = await resp.json();
  } catch (e) {
    el("contagem").textContent =
      "Não foi possível carregar requerimentos-index.json. Rode respostas-executivo/export.py para gerá-lo.";
    return;
  }
  preencherSelects();
  ["q", "ano", "status"].forEach((id) =>
    el(id).addEventListener("input", aplicarFiltros)
  );
  el("mais").addEventListener("click", renderizarMais);
  aplicarFiltros();
}

init();
