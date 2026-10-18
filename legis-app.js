// Painel da Base de Legislação — lê legis-index.json e filtra no cliente.
"use strict";

let NORMAS = [];
let filtradas = [];
let pag = null;  // Comum.paginador — montado no init
let POR_ID = new Map();  // id → norma (para achar a revogadora)
let FOCO = "";           // ?id= — uma norma pelo link direto (busca universal, Novidades)
// Ementa oficial (legis/ementas.json, {id: descricao}): o índice traz em `ementa` só as
// palavras-chave do Legis, vazias em 3,3 mil das 3,9 mil normas. Vem junto com o índice
// (é pequena); se faltar (404 até o 1º workflow depois do merge), a página segue sem ela.
let EMENTAS = {};
const N_CHIPS = 20;  // temas mais frequentes em chips; o resto pelo campo com sugestões

const el = (id) => document.getElementById(id);
// utilitários da camada comum (eram cópias locais idênticas em cada painel)
const norm = Comum.norm;
const escapar = Comum.escapar;
// tema normalizado: caixa, acento e espaços ("Termo de Fomento" = "TERMO DE FOMENTO")
const normTema = (t) => norm(t).replace(/\s+/g, " ").trim();
const temasDe = (n) => (n.tags || "").split(";").map((t) => t.trim()).filter(Boolean);

function preencherSelects() {
  const tipos = [...new Set(NORMAS.map((n) => n.tipo).filter(Boolean))].sort();
  const anos = [...new Set(NORMAS.map((n) => n.ano).filter(Boolean))].sort((a, b) => b - a);
  for (const t of tipos) el("tipo").add(new Option(t, t));
  for (const a of anos) el("ano").add(new Option(a, a));

  // Temas: o select tinha 4.659 opções (3,4 mil usadas uma vez, a mesma palavra em várias
  // grafias). Agrupa pelo tema normalizado e mostra a grafia mais frequente.
  const grupos = new Map();
  for (const n of NORMAS) {
    for (const t of temasDe(n)) {
      const k = normTema(t);
      const g = grupos.get(k) || { n: 0, grafias: new Map() };
      g.n++;
      g.grafias.set(t, (g.grafias.get(t) || 0) + 1);
      grupos.set(k, g);
    }
  }
  const lista = [...grupos.values()].map((g) => ({
    n: g.n, rotulo: [...g.grafias.entries()].sort((a, b) => b[1] - a[1])[0][0],
  })).sort((a, b) => b.n - a.n || a.rotulo.localeCompare(b.rotulo, "pt"));
  el("temas-lista").innerHTML = lista.map((t) => `<option value="${escapar(t.rotulo)}"></option>`).join("");
  el("temas-chips").innerHTML = lista.slice(0, N_CHIPS).map((t) =>
    `<button type="button" class="chip" data-tema="${escapar(t.rotulo)}" aria-pressed="false">` +
    `${escapar(t.rotulo)} <span class="n">${t.n.toLocaleString("pt-BR")}</span></button>`).join("");
}

function aplicarFiltros() {
  const q = norm(el("q").value).trim();
  const termos = q ? q.split(/\s+/) : [];
  const tipo = el("tipo").value;
  const ano = el("ano").value;
  const tema = normTema(el("tema").value);
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
  for (const c of el("temas-chips").querySelectorAll(".chip")) {
    c.setAttribute("aria-pressed", String(!!tema && normTema(c.dataset.tema) === tema));
  }
  el("csv").disabled = filtradas.length === 0;
  el("foco").hidden = !FOCO;
  Comum.gravarParams({
    q: el("q").value.trim(), tipo, ano, tema: el("tema").value.trim(), sit, id: FOCO,
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

// Exporta o resultado filtrado (mesmas colunas da tabela, com a ementa oficial)
function exportarCSV() {
  if (!filtradas.length) return;
  const campos = ["tipo", "numero", "ano", "data_norma", "ementa_oficial", "ementa", "tags", "situacao", "url_legis", "url_pdf"];
  Comum.exportarCsv(
    `legislacao-filtro-${new Date().toISOString().slice(0, 10)}.csv`,
    campos.map((c) => (c === "ementa" ? "palavras_chave" : c)),
    filtradas.map((n) => campos.map((c) => (c === "ementa_oficial" ? EMENTAS[String(n.id)] || "" : n[c] ?? "")))
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
  const oficial = EMENTAS[String(n.id)];
  const desc = oficial || n.ementa || n.titulo || "";
  // com a ementa oficial, as palavras-chave do Legis viram uma linha à parte; os temas
  // ficam só na coluna Temas (antes saíam duas vezes na mesma linha)
  const chave = oficial && n.ementa ? `<span class="chave">${escapar(n.ementa)}</span>` : "";
  // a página da norma abre no navegador; o PDF do Legis vem como download (sem CORS)
  const docs = (n.url_legis
    ? `<a class="legis" href="${escapar(n.url_legis)}" target="_blank" rel="noopener">Ver no Legis ↗</a>` : "") +
    (n.url_pdf
      ? `${n.url_legis ? "<br />" : ""}<a class="pdf secundario" href="${escapar(n.url_pdf)}" target="_blank" rel="noopener">PDF (baixa) ↗</a>`
      : "");
  return `<tr>
    <td data-label="Tipo"><span class="tipo-badge">${escapar(n.tipo)}</span></td>
    <td data-label="Número" class="num">${escapar(n.numero)}</td>
    <td data-label="Ano">${escapar(n.ano)}</td>
    <td data-label="Data">${escapar(n.data_norma)}</td>
    <td data-label="Ementa">${seloHTML(n)}${escapar(desc)}${chave}</td>
    <td data-label="Temas" class="tags">${escapar(n.tags)}</td>
    <td data-label="Documento">${docs}</td>
  </tr>`;
}

async function init() {
  try {
    const [resp, ementas] = await Promise.all([
      fetch("./legis-index.json", { cache: "no-cache" }),
      fetch("./legis/ementas.json", { cache: "no-cache" })
        .then((r) => (r.ok ? r.json() : {}))
        .catch(() => ({})),
    ]);
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    NORMAS = await resp.json();
    EMENTAS = ementas || {};
  } catch (e) {
    el("contagem").textContent = "";
    Comum.estadoErro("stats",
      "Não foi possível carregar a base de legislação. Verifique a conexão.", init);
    return;
  }
  // texto de busca normalizado UMA vez (era normalize("NFD") em 3,8 mil linhas a cada tecla);
  // a ementa oficial entra na busca
  for (const n of NORMAS) {
    n._busca = norm([n.numero, n.ano, n.titulo, n.ementa, EMENTAS[String(n.id)], n.tags, n.tipo].join(" "));
    n._tags = normTema(n.tags);
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
  el("tema").addEventListener("input", Comum.debounce(aplicarFiltros));
  ["tipo", "ano", "sit"].forEach((id) => el(id).addEventListener("input", aplicarFiltros));
  el("temas-chips").addEventListener("click", (e) => {
    const c = e.target.closest("[data-tema]");
    if (!c) return;
    // alterna: o mesmo chip de novo limpa o tema
    el("tema").value = normTema(el("tema").value) === normTema(c.dataset.tema) ? "" : c.dataset.tema;
    FOCO = "";
    aplicarFiltros();
  });
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
