// Painel da Base de Proposituras — lê proposituras-index.json e filtra no cliente.
"use strict";

let PROPS = [];
let filtradas = [];
let pag = null;  // Comum.paginador — montado no init
let FOCO = "";   // ?cod= — uma propositura pelo link direto (busca universal, Novidades)

// Índice com tramitação (out/2026, proposituras/export.py): `tram` em todo item e, nos em
// tramitação, `ua` (último andamento, ISO), `uad` (despacho) e `ual` (local, quando difere
// do atual). No índice antigo os atalhos e os KPIs novos somem.
let TEM_TRAM = false;
// O autor 282 da Câmara; "Rui Sergio Gomes de Rosis" (2017–24, sem o Junior) é OUTRO autor.
const AUTOR_MANDATO = "Rui Sergio Gomes de Rosis Junior";
const ATALHOS = { tram: false, mandato: false, seg: false };
// "Acompanhar" fica neste aparelho: cod → `ua` visto por último ("" se sem andamento)
const CHAVE_SEG = "proposituras:acompanhando";
let SEG = {};

const el = (id) => document.getElementById(id);
// utilitários da camada comum (eram cópias locais idênticas em cada painel)
const norm = Comum.norm;
const escapar = Comum.escapar;
const fmt = (n) => n.toLocaleString("pt-BR");

// tram=1 sem local é ambíguo (projeto transformado, anexado…): fora do "em tramitação"
// — ver .claude/rules/proposituras.md
const emTramitacao = (p) => p.tram === 1 && !!p.local_atual;
const doMandato = (p) => p.autor === AUTOR_MANDATO;
const seguindo = (p) => Object.prototype.hasOwnProperty.call(SEG, p.cod);
const andamentoNovo = (p) => seguindo(p) && !!p.ua && (SEG[p.cod] || "") < p.ua;
const isoBR = (s) => (s || "").split("-").reverse().join("/");

function lerSeg() {
  try { return JSON.parse(localStorage.getItem(CHAVE_SEG) || "{}") || {}; } catch { return {}; }
}
function gravarSeg() {
  try { localStorage.setItem(CHAVE_SEG, JSON.stringify(SEG)); } catch { /* modo privado: vale só nesta visita */ }
}

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
  if (!TEM_TRAM) el("ordem").querySelector('option[value="andamento"]').remove();
}

// ── Atalhos: em tramitação · do mandato · acompanhando ──────────────────────
function montarAtalhos() {
  const cont = el("atalhos");
  if (!TEM_TRAM) return;  // índice antigo: fica escondido
  const defs = [["tram", "Em tramitação"], ["mandato", "Do mandato"], ["seg", "Acompanhando"]];
  cont.innerHTML = defs.map(([k, r]) =>
    `<button type="button" class="chip" data-atalho="${k}" aria-pressed="false">${r} <span class="n">0</span></button>`
  ).join("");
  cont.hidden = false;
  cont.addEventListener("click", (e) => {
    const b = e.target.closest("[data-atalho]");
    if (!b) return;
    ATALHOS[b.dataset.atalho] = !ATALHOS[b.dataset.atalho];
    FOCO = "";
    aplicarFiltros();
  });
}

function atualizarAtalhos() {
  if (!TEM_TRAM) return;
  const n = {
    tram: PROPS.filter(emTramitacao).length,
    mandato: PROPS.filter(doMandato).length,
    seg: PROPS.filter(seguindo).length,
  };
  const novos = PROPS.filter(andamentoNovo).length;
  for (const b of el("atalhos").querySelectorAll("[data-atalho]")) {
    const k = b.dataset.atalho;
    b.setAttribute("aria-pressed", String(ATALHOS[k]));
    b.querySelector(".n").textContent = fmt(n[k]) + (k === "seg" && novos ? ` · ${fmt(novos)} com andamento novo` : "");
  }
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
      FOCO = "";
      aplicarFiltros();
    });
    cont.appendChild(b);
  }
}

function atualizarChips(base) {
  const ativo = el("subtipo").value;
  // contagem por subtipo respeita os demais filtros (exceto o próprio subtipo);
  // `base` vem do aplicarFiltros — antes era uma 2ª varredura das 7 mil linhas por tecla
  const cont = {};
  for (const p of base) cont[p.subtipo] = (cont[p.subtipo] || 0) + 1;
  for (const chip of el("chips").querySelectorAll(".chip")) {
    const s = chip.dataset.subtipo;
    chip.setAttribute("aria-pressed", String(ativo === s));
    chip.querySelector(".n").textContent = (cont[s] || 0).toLocaleString("pt-BR");
  }
}

// ── Filtragem e ordem ───────────────────────────────────────────────────────
// tudo menos o subtipo — o subtipo entra depois, para os chips contarem sobre esta base
function filtrarBase() {
  const q = norm(el("q").value).trim();
  const termos = q ? q.split(/\s+/) : [];
  const ano = el("ano").value;
  const autor = el("autor").value;
  const local = el("local").value;

  return PROPS.filter((p) => {
    if (ano && String(p.ano) !== ano) return false;
    if (autor && p.autor !== autor) return false;
    if (local && p.local_atual !== local) return false;
    if (ATALHOS.tram && !emTramitacao(p)) return false;
    if (ATALHOS.mandato && !doMandato(p)) return false;
    if (ATALHOS.seg && !seguindo(p)) return false;
    if (termos.length && !termos.every((t) => p._busca.includes(t))) return false;
    return true;
  });
}

// "dd/mm/aaaa" → "aaaammdd" (ordena como texto); nº "12/2026" → ano×1e5 + nº
const dataOrd = (s) => { const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s || ""); return m ? m[3] + m[2] + m[1] : ""; };
const numOrd = (p) => { const m = /^(\d+)\/(\d{4})$/.exec(p.numero || ""); return m ? +m[2] * 1e5 + +m[1] : 0; };
const cmpTexto = (a, b) => (a < b ? 1 : a > b ? -1 : 0);  // decrescente
const ORDENS = {
  // mais recentes primeiro (o índice novo já vem assim; o antigo vinha em ordem de texto)
  recentes: (a, b) => cmpTexto(a._data, b._data) || b._num - a._num,
  andamento: (a, b) => cmpTexto(a.ua || "", b.ua || "") || cmpTexto(a._data, b._data),
  numero: (a, b) => b._num - a._num,
};

function aplicarFiltros() {
  // link direto: só a propositura do `cod`, ignorando os filtros (antes a paleta
  // mandava "?q=1/2026", que casava também 11/2026, 101/2026…)
  const base = FOCO ? PROPS.filter((p) => String(p.cod) === FOCO) : filtrarBase();
  const subtipo = FOCO ? "" : el("subtipo").value;
  const ordem = el("ordem").value || "recentes";
  filtradas = (subtipo ? base.filter((p) => p.subtipo === subtipo) : base.slice())
    .sort(ORDENS[ordem] || ORDENS.recentes);
  atualizarResumo(filtradas);
  atualizarChips(base);
  atualizarAtalhos();

  pag.reiniciar(filtradas);
  el("vazio").hidden = filtradas.length > 0;
  el("csv").disabled = filtradas.length === 0;
  el("foco").hidden = !FOCO;
  Comum.gravarParams({
    q: el("q").value.trim(),
    subtipo: el("subtipo").value,
    ano: el("ano").value,
    autor: el("autor").value,
    local: el("local").value,
    ordem: ordem === "recentes" ? "" : ordem,
    tram: ATALHOS.tram ? "1" : "",
    mandato: ATALHOS.mandato ? "1" : "",
    seg: ATALHOS.seg ? "1" : "",
    cod: FOCO,
  });
}

// ── Cards de resumo ─────────────────────────────────────────────────────────
function atualizarResumo(lista) {
  const total = lista.length;
  let cards;
  if (TEM_TRAM) {
    const tramit = lista.filter(emTramitacao);
    const pauta = tramit.filter((p) => /aguardando paut/i.test(p.local_atual)).length;
    const mandato = tramit.filter(doMandato).length;
    cards = [
      { rotulo: "Proposituras", valor: fmt(total), sub: "tipo Projeto · no filtro atual" },
      { rotulo: "Em tramitação", valor: fmt(tramit.length), sub: "fora do arquivo, com local na Câmara" },
      { rotulo: "Aguardando pautação", valor: fmt(pauta), sub: "na Diretoria Legislativa" },
      { rotulo: "Do mandato em tramitação", valor: fmt(mandato), sub: "autoria do vereador" },
    ];
  } else {
    const autores = new Set(lista.map((p) => p.autor).filter(Boolean)).size;
    const anos = lista.map((p) => p.ano).filter(Boolean);
    const anoMin = anos.length ? Math.min(...anos) : "—";
    const anoMax = anos.length ? Math.max(...anos) : "—";
    const porLocal = {};
    for (const p of lista) if (p.local_atual) porLocal[p.local_atual] = (porLocal[p.local_atual] || 0) + 1;
    let topLocal = "—", topLocalN = 0;
    for (const [k, v] of Object.entries(porLocal)) if (v > topLocalN) { topLocal = k; topLocalN = v; }
    cards = [
      { rotulo: "Proposituras", valor: fmt(total), sub: "tipo Projeto" },
      { rotulo: "Autores distintos", valor: fmt(autores), sub: "no filtro atual" },
      { rotulo: "Período", valor: anoMin === anoMax ? `${anoMin}` : `${anoMin}–${anoMax}`, sub: "ano da propositura" },
      { rotulo: "Local mais frequente", valor: topLocalN ? fmt(topLocalN) : "—", sub: topLocal },
    ];
  }
  el("stats").innerHTML = cards
    .map((c) => `<div class="stat">
        <div class="rotulo">${escapar(c.rotulo)}</div>
        <div class="valor">${escapar(c.valor)}</div>
        <div class="sub" title="${escapar(c.sub)}">${escapar(c.sub)}</div>
      </div>`)
    .join("");
}

// ── Tabela ────────────────────────────────────────────────────────────────────
function andamentoHTML(p) {
  if (!(p.tram === 1 && p.ua)) return "";
  const onde = p.ual || p.local_atual;
  const novo = andamentoNovo(p)
    ? ` <button type="button" class="lnk novo" data-visto="${escapar(p.cod)}" title="Marcar como visto">andamento novo ✓</button>`
    : "";
  return `<div class="andamento">Último andamento em <b>${escapar(isoBR(p.ua))}</b>` +
    (onde ? ` · ${escapar(onde)}` : "") + (p.uad ? ` — ${escapar(p.uad)}` : "") + novo + "</div>";
}

function linhaHTML(p) {
  const local = p.local_atual
    ? `<span class="sit-badge">${escapar(p.local_atual)}</span>`
    : "";
  // abre no visor embutido (clique simples); Ctrl/⌘/botão do meio seguem para a nova aba
  const pdf = p.url_pdf
    ? `<a class="pdf" href="${escapar(p.url_pdf)}" target="_blank" rel="noopener" data-titulo="${escapar(p.subtipo + " " + p.numero)}">PDF</a>`
    : "";
  const det = p.url_detalhes
    ? `<a class="det" href="${escapar(p.url_detalhes)}" target="_blank" rel="noopener">Detalhes ↗</a>`
    : "";
  const seguir = TEM_TRAM
    ? `<button type="button" class="lnk seguir" data-seguir="${escapar(p.cod)}" aria-pressed="${seguindo(p)}">` +
      `${seguindo(p) ? "★ Acompanhando" : "☆ Acompanhar"}</button>`
    : "";
  return `<tr>
    <td data-label="Subtipo"><span class="tipo-badge">${escapar(p.subtipo)}</span></td>
    <td data-label="Número" class="num">${escapar(p.numero)}</td>
    <td data-label="Data">${escapar(p.data_propositura)}</td>
    <td data-label="Autor">${escapar(p.autor)}</td>
    <td data-label="Ementa"><div class="ementa">${escapar(p.ementa)}</div>${andamentoHTML(p)}</td>
    <td data-label="Local">${local}</td>
    <td data-label="Links">${det}${det && pdf ? "<br />" : ""}${pdf}${seguir}</td>
  </tr>`;
}

// ── Exportar CSV do resultado filtrado (dialeto Excel pt-BR via Comum) ──────
function exportarCSV() {
  if (!filtradas.length) return;
  const cols = ["subtipo", "numero", "ano", "data_propositura", "autor", "ementa", "local_atual", "ua", "uad", "url_detalhes", "url_pdf"];
  Comum.exportarCsv(
    `proposituras-filtro-${new Date().toISOString().slice(0, 10)}.csv`,
    cols.map((c) => (c === "ua" ? "ultimo_andamento" : c === "uad" ? "despacho" : c)),
    filtradas.map((p) => cols.map((c) => (c === "ua" ? isoBR(p.ua) : p[c] ?? "")))
  );
}

function limparFiltros() {
  el("q").value = "";
  for (const id of ["subtipo", "ano", "autor", "local", "ordem"]) el(id).value = "";
  for (const k of Object.keys(ATALHOS)) ATALHOS[k] = false;
  FOCO = "";
  aplicarFiltros();
}

// Clique simples no "PDF" abre o visor embutido; com Ctrl/⌘/Shift ou botão do
// meio o navegador segue o href normalmente (nova aba).
function abrirPdfNoVisor(e) {
  const a = e.target.closest("a.pdf");
  if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  Comum.visorPdf(a.href, a.dataset.titulo);
}

// ☆ Acompanhar / ★ Acompanhando e "andamento novo ✓" (marcar como visto)
function acoesDaLinha(e) {
  const s = e.target.closest("[data-seguir]");
  const v = e.target.closest("[data-visto]");
  if (!s && !v) return;
  const cod = (s || v).dataset.seguir || (s || v).dataset.visto;
  const p = PROPS.find((x) => String(x.cod) === cod);
  if (!p) return;
  if (s && seguindo(p)) delete SEG[p.cod];
  else SEG[p.cod] = p.ua || "";  // começar a acompanhar (ou marcar visto) = andamento atual
  gravarSeg();
  if (s) Comum.toast(seguindo(p) ? "Acompanhando — o selo avisa quando houver andamento novo" : "Deixou de acompanhar");
  // recria só esta linha (preserva a rolagem e o "Mostrar mais")
  const tr = (s || v).closest("tr");
  tr.insertAdjacentHTML("afterend", linhaHTML(p));
  tr.remove();
  atualizarAtalhos();
}

async function init() {
  try {
    const resp = await fetch("./proposituras-index.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    PROPS = await resp.json();
  } catch (e) {
    el("contagem").textContent = "";
    Comum.estadoErro("stats",
      "Não foi possível carregar as proposituras. Verifique a conexão.", init);
    return;
  }
  TEM_TRAM = PROPS.some((p) => "tram" in p);
  SEG = lerSeg();
  // texto de busca normalizado UMA vez (era normalize("NFD") em 7 mil linhas, 2× por tecla)
  for (const p of PROPS) {
    p._busca = norm([p.numero, p.ano, p.subtipo, p.ementa, p.autor, p.local_atual].join(" "));
    p._data = dataOrd(p.data_propositura);
    p._num = numOrd(p);
  }
  preencherSelects();
  montarAtalhos();
  montarChips();
  // estado vindo da URL (link compartilhável) — antes do primeiro render
  const p = Comum.lerParams();
  for (const id of ["q", "subtipo", "ano", "autor", "local", "ordem"]) {
    const v = p.get(id);
    if (v) el(id).value = v;
  }
  if (TEM_TRAM) for (const k of Object.keys(ATALHOS)) ATALHOS[k] = p.get(k) === "1";
  FOCO = p.get("cod") || "";
  // mexer em qualquer filtro sai do link direto
  const sairDoFoco = () => { FOCO = ""; };
  el("q").addEventListener("input", sairDoFoco);
  ["subtipo", "ano", "autor", "local", "ordem"].forEach((id) => el(id).addEventListener("input", sairDoFoco));
  el("foco-todos").addEventListener("click", () => { FOCO = ""; aplicarFiltros(); });
  el("q").addEventListener("input", Comum.debounce(aplicarFiltros));
  ["subtipo", "ano", "autor", "local", "ordem"].forEach((id) => el(id).addEventListener("input", aplicarFiltros));
  pag = Comum.paginador({
    corpo: "corpo", mais: "mais", contagem: "contagem", linha: linhaHTML,
    rotulo: (lista, mostrando) =>
      `${lista.length.toLocaleString("pt-BR")} propositura(s) — exibindo ${mostrando.toLocaleString("pt-BR")}`,
  });
  el("csv").addEventListener("click", exportarCSV);
  el("limpar").addEventListener("click", limparFiltros);
  el("corpo").addEventListener("click", abrirPdfNoVisor);
  el("corpo").addEventListener("click", acoesDaLinha);
  aplicarFiltros();
}

init();
