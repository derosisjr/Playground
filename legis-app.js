// Painel da Base de Legislação — lê legis-index.json e filtra no cliente.
"use strict";

let NORMAS = [];
let filtradas = [];
let pag = null;  // Comum.paginador — montado no init
let POR_ID = new Map();  // id → norma (para achar a revogadora)
let FOCO = "";           // ?id= — uma norma pelo link direto (busca universal, Novidades)

const el = (id) => document.getElementById(id);
// utilitários da camada comum (eram cópias locais idênticas em cada painel)
const norm = Comum.norm;
const escapar = Comum.escapar;

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
  const sit = el("sit").value;

  filtradas = NORMAS.filter((n) => {
    // link direto: só a norma do `id` (antes a paleta abria "?q=&ano=2026" — o ano
    // inteiro — para normas sem número)
    if (FOCO) return String(n.id) === FOCO;
    if (tipo && n.tipo !== tipo) return false;
    if (sit && (n.situacao || "nenhuma") !== sit) return false;
    if (ano && String(n.ano) !== ano) return false;
    if (tema && !n._tags.includes(tema)) return false;
    if (termos.length && !termos.every((t) => n._busca.includes(t))) return false;
    return true;
  });

  pag.reiniciar(filtradas);
  el("vazio").hidden = filtradas.length > 0;
  atualizarResumo();
  el("csv").disabled = filtradas.length === 0;
  el("foco").hidden = !FOCO;
  Comum.gravarParams({
    q: el("q").value.trim(), tipo, ano, tema: el("tema").value, sit, id: FOCO,
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
  const campos = ["tipo", "numero", "ano", "data_norma", "ementa", "tags", "situacao", "url_pdf"];
  Comum.exportarCsv(
    `legislacao-filtro-${new Date().toISOString().slice(0, 10)}.csv`,
    campos,
    filtradas.map((n) => campos.map((c) => n[c]))
  );
}

// "Lei nº 3.386/2017" — rótulo curto da norma revogadora
function rotuloNorma(n) {
  const curto = { "Lei ordinária": "Lei", "Lei complementar": "LC" }[n.tipo] || n.tipo;
  return `${curto} nº ${n.numero}${n.ano ? "/" + n.ano : ""}`;
}

// Selo de situação. Tudo aqui é INFERIDO da ementa da norma posterior — o Legis
// não publica a situação — e o texto diz isso.
const SELOS = {
  "revogada": ["sit-rev", "Revogada"],
  "revogada parcialmente": ["sit-parc", "Revogada em parte"],
  "alterada": ["sit-alt", "Alterada"],
};
function seloHTML(n) {
  const s = SELOS[n.situacao];
  if (!s) return "";
  const r = n.revogada_por && POR_ID.get(n.revogada_por);
  const por = r
    ? ` por <a href="${escapar(r.url_legis)}" target="_blank" rel="noopener">${escapar(rotuloNorma(r))} ↗</a>`
    : "";
  return `<div class="sit-linha"><span class="sit ${s[0]}">${s[1]}</span>` +
    `<span class="sit-por">${por} <span class="sit-inf">(inferido da ementa da norma posterior)</span></span></div>`;
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
    <td data-label="Ementa">${seloHTML(n)}${escapar(desc)}${temas}</td>
    <td data-label="Temas" class="tags">${escapar(n.tags)}</td>
    <td data-label="Documento"><a class="pdf" href="${escapar(n.url_pdf)}" target="_blank" rel="noopener">PDF ↗</a></td>
  </tr>`;
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
  // texto de busca normalizado UMA vez (era normalize("NFD") em 3,8 mil linhas a cada tecla)
  for (const n of NORMAS) {
    n._busca = norm([n.numero, n.ano, n.titulo, n.ementa, n.tags, n.tipo].join(" "));
    n._tags = norm(n.tags);
  }
  POR_ID = new Map(NORMAS.map((n) => [n.id, n]));
  preencherSelects();
  // estado vindo da URL (link compartilhável) — antes do primeiro render
  const p = Comum.lerParams();
  for (const id of ["q", "tipo", "ano", "tema", "sit"]) {
    const v = p.get(id);
    if (v) el(id).value = v;
  }
  FOCO = p.get("id") || "";
  // mexer em qualquer filtro sai do link direto
  for (const id of ["q", "tipo", "ano", "tema", "sit"]) el(id).addEventListener("input", () => { FOCO = ""; });
  el("foco-todos").addEventListener("click", () => { FOCO = ""; aplicarFiltros(); });
  el("q").addEventListener("input", Comum.debounce(aplicarFiltros));
  ["tipo", "ano", "tema", "sit"].forEach((id) => el(id).addEventListener("input", aplicarFiltros));
  pag = Comum.paginador({
    corpo: "corpo", mais: "mais", contagem: "contagem", linha: linhaHTML,
    rotulo: (lista, mostrando) =>
      `${lista.length.toLocaleString("pt-BR")} norma(s) — exibindo ${mostrando.toLocaleString("pt-BR")}`,
  });
  el("csv").addEventListener("click", exportarCSV);
  el("limpar").addEventListener("click", () => {
    for (const id of ["q", "tipo", "ano", "tema", "sit"]) el(id).value = "";
    FOCO = "";
    aplicarFiltros();
  });
  aplicarFiltros();
}

init();
