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
  atualizarResumo();
  el("csv").disabled = filtradas.length === 0;
  Comum.gravarParams({ q: el("q").value.trim(), ano, status });
}

// "dd/mm/aaaa" -> Date (null se inválida)
function dataBR(s) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s || "");
  return m ? new Date(+m[3], +m[2] - 1, +m[1]) : null;
}

// Cards de resumo (respeitam o filtro atual)
function atualizarResumo() {
  const total = filtradas.length;
  const respondidos = filtradas.filter((i) => i.respondido).length;
  const pendentes = total - respondidos;
  const pct = total ? Math.round((respondidos / total) * 100) : 0;

  // tempo médio de resposta (dias entre sessão e resposta), só dos respondidos
  const prazos = filtradas
    .map((i) => {
      const a = dataBR(i.data_sessao), b = dataBR(i.data_resposta);
      return a && b ? (b - a) / 864e5 : null;
    })
    .filter((d) => d != null && d >= 0);
  const media = prazos.length
    ? Math.round(prazos.reduce((s, d) => s + d, 0) / prazos.length)
    : null;

  const cards = [
    { rotulo: "Requerimentos", valor: total.toLocaleString("pt-BR"), sub: "no filtro atual" },
    { rotulo: "Respondidos", valor: `${pct}%`, sub: `${respondidos.toLocaleString("pt-BR")} de ${total.toLocaleString("pt-BR")}` },
    { rotulo: "Pendentes", valor: pendentes.toLocaleString("pt-BR"), sub: "aguardando o Executivo" },
    { rotulo: "Tempo médio de resposta", valor: media == null ? "—" : `${media} dias`, sub: "entre a sessão e a resposta" },
  ];
  el("stats").innerHTML = cards
    .map((c) => `<div class="stat">
        <div class="rotulo">${escapar(c.rotulo)}</div>
        <div class="valor">${escapar(c.valor)}</div>
        <div class="sub">${escapar(c.sub)}</div>
      </div>`)
    .join("");
}

// Exporta o resultado filtrado (mesmas colunas da tabela)
function exportarCSV() {
  if (!filtradas.length) return;
  const campos = ["numero", "ano", "assunto", "data_sessao", "data_resposta", "status", "respondido", "url_resposta"];
  Comum.exportarCsv(
    `requerimentos-filtro-${new Date().toISOString().slice(0, 10)}.csv`,
    campos,
    filtradas.map((i) => campos.map((c) => (c === "respondido" ? (i[c] ? "sim" : "não") : i[c])))
  );
}

function linhaHTML(i) {
  const resposta = i.url_resposta
    ? `<a class="pdf" href="${escapar(i.url_resposta)}" target="_blank" rel="noopener">Resposta ↗</a>`
    : `<span class="pendente">Pendente</span>`;
  return `<tr>
    <td data-label="Número" class="num">${escapar(i.numero)}</td>
    <td data-label="Assunto">${escapar(i.assunto)}</td>
    <td data-label="Sessão" class="data">${escapar(i.data_sessao)}</td>
    <td data-label="Resposta em" class="data">${escapar(i.data_resposta)}</td>
    <td data-label="Situação" class="status">${escapar(i.status)}</td>
    <td data-label="Resposta">${resposta}</td>
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
  el("contagem").classList.remove("pulsa"); void el("contagem").offsetWidth;
  el("contagem").classList.add("pulsa");
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
  // estado vindo da URL (link compartilhável) — antes do primeiro render
  const p = Comum.lerParams();
  for (const id of ["q", "ano", "status"]) {
    const v = p.get(id);
    if (v) el(id).value = v;
  }
  ["q", "ano", "status"].forEach((id) =>
    el(id).addEventListener("input", aplicarFiltros)
  );
  el("mais").addEventListener("click", renderizarMais);
  el("csv").addEventListener("click", exportarCSV);
  aplicarFiltros();
}

init();
