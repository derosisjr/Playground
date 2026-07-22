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
  atualizarResumo();
  el("csv").disabled = filtradas.length === 0;
  Comum.gravarParams({
    q: el("q").value.trim(), tipo, ano, tema: el("tema").value,
  });
}

// Cards de resumo (respeitam o filtro atual)
function atualizarResumo() {
  const conta = (t) => filtradas.filter((n) => n.tipo === t).length;
  const anos = filtradas.map((n) => n.ano).filter(Boolean);
  const anoMin = anos.length ? Math.min(...anos) : "—";
  const anoMax = anos.length ? Math.max(...anos) : "—";
  const cards = [
    { rotulo: "Normas", valor: filtradas.length.toLocaleString("pt-BR"), sub: "no filtro atual" },
    { rotulo: "Leis ordinárias", valor: conta("Lei ordinária").toLocaleString("pt-BR"), sub: "no filtro atual" },
    { rotulo: "Leis complementares", valor: conta("Lei complementar").toLocaleString("pt-BR"), sub: "no filtro atual" },
    { rotulo: "Período", valor: anoMin === anoMax ? `${anoMin}` : `${anoMin}–${anoMax}`, sub: "ano da norma" },
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
  const campos = ["tipo", "numero", "ano", "data_norma", "ementa", "tags", "url_pdf"];
  Comum.exportarCsv(
    `legislacao-filtro-${new Date().toISOString().slice(0, 10)}.csv`,
    campos,
    filtradas.map((n) => campos.map((c) => n[c]))
  );
}

function linhaHTML(n) {
  const desc = n.ementa || n.titulo || "";
  const temas = n.tags
    ? `<div class="tags">${escapar(n.tags)}</div>`
    : "";
  return `<tr>
    <td data-label="Tipo"><span class="tipo-badge">${escapar(n.tipo)}</span></td>
    <td data-label="Número" class="num">${escapar(n.numero)}</td>
    <td data-label="Ano">${escapar(n.ano)}</td>
    <td data-label="Data">${escapar(n.data_norma)}</td>
    <td data-label="Ementa">${escapar(desc)}${temas}</td>
    <td data-label="Temas" class="tags">${escapar(n.tags)}</td>
    <td data-label="Documento"><a class="pdf" href="${escapar(n.url_pdf)}" target="_blank" rel="noopener">PDF ↗</a></td>
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
    const resp = await fetch("./legis-index.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    NORMAS = await resp.json();
  } catch (e) {
    el("contagem").textContent = "";
    Comum.estadoErro("stats",
      "Não foi possível carregar a base de legislação. Verifique a conexão.", init);
    return;
  }
  preencherSelects();
  // estado vindo da URL (link compartilhável) — antes do primeiro render
  const p = Comum.lerParams();
  for (const id of ["q", "tipo", "ano", "tema"]) {
    const v = p.get(id);
    if (v) el(id).value = v;
  }
  ["q", "tipo", "ano", "tema"].forEach((id) =>
    el(id).addEventListener("input", aplicarFiltros)
  );
  el("mais").addEventListener("click", renderizarMais);
  el("csv").addEventListener("click", exportarCSV);
  aplicarFiltros();
}

init();
