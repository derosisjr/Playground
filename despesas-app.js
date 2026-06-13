// Radar de Despesas — painel (vanilla + Chart.js)
// Consome despesas-index.json (agregado, gerado por despesas/export.py).

const MESES = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
               "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
const NAVY = "#07111f", GOLD = "#c9a84c";
const PALETA = ["#0a1628", "#c9a84c", "#475467", "#1d4ed8", "#b54708",
                "#0f766e", "#7c3aed", "#b42318", "#0891b2", "#65a30d"];

let DADOS = null;
let favSort = { col: "valor", dir: "desc" };

// ── Formatação ───────────────────────────────────────────────────────────────
const brl = (v) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const brlc = (v) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2 });
const compacto = (v) => {
  const a = Math.abs(v);
  if (a >= 1e9) return "R$ " + (v / 1e9).toFixed(1) + " bi";
  if (a >= 1e6) return "R$ " + (v / 1e6).toFixed(1) + " mi";
  if (a >= 1e3) return "R$ " + (v / 1e3).toFixed(0) + " mil";
  return brl(v);
};

// ── Inicialização ────────────────────────────────────────────────────────────
async function init() {
  try {
    const r = await fetch("./despesas-index.json?v=" + Date.now());
    DADOS = await r.json();
  } catch (e) {
    document.getElementById("stats").innerHTML =
      '<div class="stat"><div class="rotulo">Erro</div><div class="sub">Não foi possível carregar despesas-index.json. Rode o export.</div></div>';
    return;
  }
  renderStats();
  renderGraficos();
  renderAlertas();
  renderFavoridosTabela();
  renderSeletorMeses();
  ligarAbas();
  ligarBusca();
  ligarOrdenacao();
  ligarModosFav();
  ligarDetalhe();
  ligarFicha();

  const at = DADOS.atualizado_em ? new Date(DADOS.atualizado_em).toLocaleString("pt-BR") : "";
  document.getElementById("atualizado").textContent = at ? "Atualizado em " + at + "." : "";
}

// ── Cards ────────────────────────────────────────────────────────────────────
function renderStats() {
  const t = DADOS.totais, p = DADOS.periodo;
  const anos = Object.keys(t.por_ano || {}).sort();
  const ultimoAno = anos[anos.length - 1];
  const cards = [
    { rotulo: "Total no período", valor: compacto(t.geral), sub: `${p.de} a ${p.ate}` },
    { rotulo: `Total em ${ultimoAno || "—"}`, valor: compacto(t.por_ano?.[ultimoAno] || 0), sub: "exercício corrente" },
    { rotulo: "Pagamentos", valor: t.pagamentos.toLocaleString("pt-BR"), sub: "registros" },
    { rotulo: "Favorecidos", valor: t.favorecidos.toLocaleString("pt-BR"), sub: "distintos" },
  ];
  document.getElementById("stats").innerHTML = cards.map(c =>
    `<div class="stat"><div class="rotulo">${c.rotulo}</div>
     <div class="valor">${c.valor}</div><div class="sub">${c.sub}</div></div>`).join("");
}

// ── Gráficos ─────────────────────────────────────────────────────────────────
function eixoReais() {
  return { ticks: { callback: (v) => compacto(v) } };
}

function renderGraficos() {
  // Série mensal
  const serie = DADOS.series_mensais;
  new Chart(document.getElementById("ch-mensal"), {
    type: "line",
    data: {
      labels: serie.map(s => `${MESES[s.mes]}/${String(s.ano).slice(2)}`),
      datasets: [{
        data: serie.map(s => s.valor), borderColor: NAVY, backgroundColor: "rgba(10,22,40,.08)",
        fill: true, tension: .25, pointRadius: 2, borderWidth: 2,
      }],
    },
    options: chartOpts({ y: eixoReais() }),
  });

  // Top funções (barra horizontal)
  const fn = DADOS.por_funcao.slice(0, 10);
  new Chart(document.getElementById("ch-funcao"), {
    type: "bar",
    data: {
      labels: fn.map(f => rotulo(f.funcao)),
      datasets: [{ data: fn.map(f => f.valor), backgroundColor: GOLD }],
    },
    options: chartOpts({ x: eixoReais() }, "y"),
  });

  // Por fonte (donut top 8)
  const ft = DADOS.por_fonte.slice(0, 8);
  new Chart(document.getElementById("ch-fonte"), {
    type: "doughnut",
    data: { labels: ft.map(f => rotulo(f.fonte)), datasets: [{ data: ft.map(f => f.valor), backgroundColor: PALETA }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "right", labels: { font: { size: 11 } } },
      tooltip: { callbacks: { label: (c) => `${c.label}: ${brlc(c.raw)}` } } } },
  });

  // Por unidade gestora (barra)
  const un = DADOS.por_unidade.slice(0, 8);
  new Chart(document.getElementById("ch-unidade"), {
    type: "bar",
    data: { labels: un.map(u => rotulo(u.unidade)), datasets: [{ data: un.map(u => u.valor), backgroundColor: NAVY }] },
    options: chartOpts({ x: eixoReais() }, "y"),
  });
}

function rotulo(s) {
  s = s || "—";
  return s.length > 38 ? s.slice(0, 36) + "…" : s;
}

function chartOpts(scales, indexAxis) {
  const o = {
    responsive: true, maintainAspectRatio: false, indexAxis: indexAxis || "x",
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (c) => brlc(indexAxis === "y" ? c.raw : c.parsed.y) } },
    },
    scales: {},
  };
  if (scales.x) o.scales.x = scales.x;
  if (scales.y) o.scales.y = scales.y;
  return o;
}

// ── Alertas ──────────────────────────────────────────────────────────────────
function renderAlertas() {
  const lista = DADOS.alertas || [];
  document.getElementById("badge-alertas").textContent = lista.length ? `(${lista.length})` : "";
  const cont = document.getElementById("lista-alertas");
  document.getElementById("alertas-vazio").hidden = lista.length > 0;
  cont.innerHTML = lista.map((a, i) => `
    <div class="alerta ${a.severidade}" data-fav="${esc(a.filtro?.favorecido || "")}">
      <div class="top">
        <div class="titulo"><span class="sev ${a.severidade}">${a.severidade}</span>${esc(a.titulo)}</div>
        <div class="vlr">${brlc(a.valor)}</div>
      </div>
      <div class="det">${esc(a.detalhe)}</div>
    </div>`).join("");

  cont.querySelectorAll(".alerta").forEach(el => {
    el.addEventListener("click", () => {
      const fav = el.getAttribute("data-fav");
      if (!fav) return;
      selecionarAba("favorecidos");
      const q = document.getElementById("q");
      q.value = fav;
      renderFavoridosTabela();
    });
  });
}

// ── Favorecidos ──────────────────────────────────────────────────────────────
const soDigitos = (s) => String(s).replace(/\D/g, "");
// CPF mascarado vem como "***.158.308-**" (sem barra); CNPJ tem "/".
const ehCpf = (doc) => !!doc && !doc.includes("/") && doc.includes("*");

let favModo = "todos";        // "todos" | "pj" (CNPJ) | "pf" (CPF)
let favElemento = "";         // filtro de elemento de despesa ("" = todos)
let favMemo = { chave: null, lista: [] };  // cache do agregado do detalhe

// predicado de tipo de documento conforme o modo
function predTipoFav() {
  if (favModo === "pf") return (d) => ehCpf(d);
  if (favModo === "pj") return (d) => (d || "").includes("/");
  return () => true;
}

// Agrega favorecidos a partir do detalhe (execução), filtrando por tipo e elemento.
function agregarFavDetalhe(predTipo, elemento) {
  const { campos, rows } = FAV_DETALHE;
  const iN = campos.indexOf("nome_favorecido"), iD = campos.indexOf("documento_favorecido"),
        iP = campos.indexOf("pago"), iData = campos.indexOf("data"), iE = campos.indexOf("elemento_despesa");
  const map = new Map();
  for (const r of rows) {
    const doc = r[iD];
    if (!predTipo(doc)) continue;
    if (elemento && r[iE] !== elemento) continue;
    const chave = r[iN] + "|" + doc;
    let o = map.get(chave);
    if (!o) { o = { nome: r[iN], documento: doc, valor: 0, qtd: 0, meses: new Set() }; map.set(chave, o); }
    o.valor += (r[iP] || 0);
    o.qtd += 1;
    if (r[iData]) o.meses.add(String(r[iData]).slice(0, 7));
  }
  return [...map.values()]
    .map(o => ({ nome: o.nome, documento: o.documento, valor: o.valor, qtd: o.qtd, meses: o.meses.size }))
    .sort((a, b) => b.valor - a.valor)
    .slice(0, 300);
}

// Fonte da tabela conforme modo + elemento (com memo p/ não reagregar a cada render).
function fonteFav() {
  // Sem elemento e em modo CNPJ/Todos: usa o agregado pronto do index (visão caixa/pago).
  if (!favElemento && favModo !== "pf") {
    const all = DADOS.top_favorecidos || [];
    if (favModo === "pj") return all.filter(f => (f.documento || "").includes("/"));
    return all;
  }
  // PF (sem elemento) ou qualquer modo com elemento: agrega do detalhe.
  if (!FAV_DETALHE) return [];
  const chave = favModo + "|" + favElemento;
  if (favMemo.chave !== chave) favMemo = { chave, lista: agregarFavDetalhe(predTipoFav(), favElemento || null) };
  return favMemo.lista;
}

function renderFavoridosTabela() {
  const bruto = (document.getElementById("q").value || "").trim();
  const termo = semAcento(bruto);
  const termoDig = soDigitos(bruto);
  const fonte = fonteFav();
  let linhas = fonte.map(f => ({
    nome: f.nome || "—", valor: f.valor, qtd: f.qtd, meses: f.meses, documento: f.documento || "",
  }));
  if (termo) linhas = linhas.filter(f =>
    semAcento(f.nome).includes(termo) ||
    (f.documento && (semAcento(f.documento).includes(termo) ||
      (termoDig && soDigitos(f.documento).includes(termoDig)))));
  const dir = favSort.dir === "asc" ? 1 : -1;
  linhas.sort((a, b) => {
    const va = a[favSort.col], vb = b[favSort.col];
    if (typeof va === "string") return va.localeCompare(vb) * dir;
    return (va - vb) * dir;
  });

  const corpo = document.getElementById("corpo-fav");
  document.getElementById("fav-vazio").hidden = linhas.length > 0;
  corpo.innerHTML = linhas.map(f => `
    <tr class="fav-row" style="cursor:pointer" data-nome="${esc(f.nome)}" data-doc="${esc(f.documento)}">
      <td>${esc(f.nome)}${f.documento ? `<div class="sub" style="color:var(--muted);font-size:12px">${esc(f.documento)}</div>` : ""}</td>
      <td class="r num">${brlc(f.valor)}</td>
      <td class="r num">${f.qtd}</td>
      <td class="r num">${f.meses}</td>
    </tr>`).join("");
  corpo.querySelectorAll(".fav-row").forEach(tr =>
    tr.addEventListener("click", () => abrirFichaFavorecido(tr.dataset.nome, tr.dataset.doc)));
  const rotuloModo = favModo === "pf" ? "pessoa(s) física(s)"
    : favModo === "pj" ? "empresa(s)" : "favorecido(s)";
  document.getElementById("contagem").textContent =
    `${linhas.length} ${rotuloModo} — top ${fonte.length} por valor`;
}

// Popula o select de elemento de despesa com APENAS os elementos que aparecem
// para o tipo de documento selecionado (CPF/CNPJ/Todos), do detalhe de execução.
function popularElementosFav() {
  if (!FAV_DETALHE) return;
  const pred = predTipoFav();
  const iE = FAV_DETALHE.campos.indexOf("elemento_despesa");
  const iD = FAV_DETALHE.campos.indexOf("documento_favorecido");
  const vals = [...new Set(FAV_DETALHE.rows
    .filter(r => r[iE] && pred(r[iD]))
    .map(r => r[iE]))].sort((a, b) => a.localeCompare(b));
  const sel = document.getElementById("f-elemento-fav");
  // se o elemento escolhido não existe para este tipo, volta para "todos"
  if (favElemento && !vals.includes(favElemento)) favElemento = "";
  sel.innerHTML = '<option value="">Elemento de despesa (todos)</option>' +
    vals.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
  sel.value = favElemento;
}

// Recalcula a lista ativa, carregando o detalhe quando o modo/elemento exigem.
async function atualizarFav() {
  const precisaDetalhe = favElemento || favModo === "pf";
  if (precisaDetalhe && !FAV_DETALHE) {
    document.getElementById("contagem").textContent = "Carregando…";
    try { await carregarTodoDetalhe(); }
    catch (e) { document.getElementById("contagem").textContent = "Falha ao carregar o detalhe."; return; }
  }
  if (FAV_DETALHE) popularElementosFav();
  renderFavoridosTabela();
}

function ligarModosFav() {
  document.querySelectorAll("#fav-modos button").forEach(b =>
    b.addEventListener("click", () => {
      favModo = b.dataset.modo;
      document.querySelectorAll("#fav-modos button").forEach(x =>
        x.classList.toggle("primario", x.dataset.modo === favModo));
      atualizarFav();
    }));
  const sel = document.getElementById("f-elemento-fav");
  // Carrega o detalhe ao abrir o select pela 1ª vez, para listar os elementos.
  sel.addEventListener("mousedown", () => {
    if (!FAV_DETALHE) carregarTodoDetalhe().then(popularElementosFav);
  });
  sel.addEventListener("change", () => { favElemento = sel.value; atualizarFav(); });
}

// ── Abas / interações ────────────────────────────────────────────────────────
function ligarAbas() {
  document.querySelectorAll(".tab").forEach(t =>
    t.addEventListener("click", () => selecionarAba(t.dataset.tab)));
}
function selecionarAba(nome) {
  document.querySelectorAll(".tab").forEach(t =>
    t.setAttribute("aria-selected", t.dataset.tab === nome));
  document.querySelectorAll(".painel").forEach(p => p.classList.remove("ativo"));
  document.getElementById("painel-" + nome).classList.add("ativo");
}
function ligarBusca() {
  document.getElementById("q").addEventListener("input", renderFavoridosTabela);
}
function ligarOrdenacao() {
  document.querySelectorAll("th[data-sort]").forEach(th =>
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      favSort.dir = favSort.col === col && favSort.dir === "desc" ? "asc" : "desc";
      favSort.col = col;
      renderFavoridosTabela();
    }));
}

// ── Detalhamento (íntegra pesquisável, carga por mês sob demanda) ─────────────
const DET_LABELS = {
  data: "Data", unidade_gestora: "Unidade gestora", tipo: "Tipo",
  nome_favorecido: "Favorecido", documento_favorecido: "CPF/CNPJ",
  funcao: "Função / área", subfuncao: "Subfunção", programa: "Programa",
  elemento_despesa: "Elemento de despesa", fonte_recurso: "Fonte de recurso",
  grupo_despesa: "Grupo de despesa", empenho: "Nº empenho",
  empenhado: "Empenhado", liquidado: "Liquidado", pago: "Pago",
};
const DET_NUM = new Set(["empenhado", "liquidado", "pago"]);  // colunas de valor
const DET_FILTROS = ["tipo", "unidade_gestora", "funcao", "fonte_recurso", "grupo_despesa"];
const DET_PAGINA = 100;
let detCampos = [];
let detRows = [];        // todas as linhas carregadas (arrays)
let detNorm = [];        // texto normalizado (sem acento, minúsculo) por linha, p/ busca
let detFiltradas = [];

// remove acentos e baixa caixa — busca tolerante a acentuação (dados em PT-BR)
const semAcento = (s) => String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
let detSort = { idx: 0, dir: "asc" };
let detPagina = 1;

function renderSeletorMeses() {
  const meses = DADOS.meses || [];
  // botões rápidos por ano + último mês
  const anos = [...new Set(meses.map(m => m.ano))].sort();
  const rapido = document.getElementById("periodo-rapido");
  rapido.innerHTML =
    anos.map(a => `<button class="btn" data-ano="${a}" type="button">${a} inteiro</button>`).join("") +
    `<button class="btn" data-ultimo="1" type="button">Último mês</button>`;

  const grid = document.getElementById("meses-grid");
  grid.innerHTML = meses.map(m => `
    <label class="mes-chk">
      <input type="checkbox" value="${m.ano}-${String(m.mes).padStart(2, "0")}"
        data-arquivo="${esc(m.arquivo)}" />
      ${MESES[m.mes]}/${m.ano}<span class="mn">${m.n}</span>
    </label>`).join("");

  rapido.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    const chks = grid.querySelectorAll("input[type=checkbox]");
    if (b.dataset.ultimo) {
      chks.forEach((c, i) => c.checked = i === chks.length - 1);
    } else {
      const ano = b.dataset.ano;
      chks.forEach(c => c.checked = c.value.startsWith(ano + "-"));
    }
    atualizarSelInfo();
  }));
  grid.querySelectorAll("input").forEach(c => c.addEventListener("change", atualizarSelInfo));
}

function mesesSelecionados() {
  return [...document.querySelectorAll("#meses-grid input:checked")];
}
function atualizarSelInfo() {
  const sel = mesesSelecionados();
  const total = sel.reduce((s, c) => {
    const m = (DADOS.meses || []).find(x => x.arquivo === c.dataset.arquivo);
    return s + (m ? m.n : 0);
  }, 0);
  document.getElementById("sel-info").textContent = sel.length
    ? `${sel.length} mês(es) selecionado(s) — ~${total.toLocaleString("pt-BR")} linhas de execução`
    : "Nenhum mês selecionado.";
}

function ligarDetalhe() {
  document.getElementById("det-limpar").addEventListener("click", () => {
    document.querySelectorAll("#meses-grid input").forEach(c => c.checked = false);
    atualizarSelInfo();
  });
  document.getElementById("det-carregar").addEventListener("click", carregarDetalhe);
  document.getElementById("det-q").addEventListener("input", () => { detPagina = 1; filtrarDetalhe(); });
  DET_FILTROS.forEach(c => document.getElementById("f-" + c)
    .addEventListener("change", () => { detPagina = 1; filtrarDetalhe(); }));
  document.getElementById("det-csv").addEventListener("click", exportarDetCsv);
  document.getElementById("det-anterior").addEventListener("click", () => { detPagina--; renderDetTabela(); });
  document.getElementById("det-proxima").addEventListener("click", () => { detPagina++; renderDetTabela(); });
}

async function carregarDetalhe() {
  const sel = mesesSelecionados();
  if (!sel.length) { alert("Selecione ao menos um mês."); return; }
  const res = document.getElementById("det-resultado");
  const carregando = document.getElementById("det-carregando");
  res.hidden = true; carregando.hidden = false;
  try {
    const partes = await Promise.all(sel.map(c =>
      fetch("./" + c.dataset.arquivo + "?v=" + (DADOS.atualizado_em || "")).then(r => r.json())));
    detCampos = partes[0].campos;
    detRows = partes.flatMap(p => p.linhas);
    detNorm = detRows.map(r => semAcento(r.join(" ")));
    // ordena por pago desc por padrão
    detSort = { idx: detCampos.indexOf("pago"), dir: "desc" };
    montarCabecalho();
    popularFiltros();
    detPagina = 1;
    document.getElementById("det-q").value = "";
    DET_FILTROS.forEach(c => document.getElementById("f-" + c).value = "");
    filtrarDetalhe();
    carregando.hidden = true; res.hidden = false;
  } catch (e) {
    carregando.hidden = false;
    carregando.textContent = "Falha ao carregar os dados do período.";
  }
}

function popularFiltros() {
  DET_FILTROS.forEach(campo => {
    const i = detCampos.indexOf(campo);
    const sel = document.getElementById("f-" + campo);
    const rotulo = sel.options[0].text;  // preserva o "(todos)"
    const vals = [...new Set(detRows.map(r => r[i]).filter(v => v != null && v !== ""))]
      .sort((a, b) => String(a).localeCompare(String(b)));
    sel.innerHTML = `<option value="">${esc(rotulo)}</option>` +
      vals.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
  });
}

function montarCabecalho() {
  const tr = document.getElementById("det-cabecalho");
  tr.innerHTML = detCampos.map((c, i) => {
    const seta = detSort.idx === i ? (detSort.dir === "asc" ? " ▲" : " ▼") : "";
    const cls = DET_NUM.has(c) ? ' class="r"' : "";
    return `<th data-idx="${i}"${cls}>${DET_LABELS[c] || c}${seta}</th>`;
  }).join("");
  tr.querySelectorAll("th").forEach(th => th.addEventListener("click", () => {
    const i = +th.dataset.idx;
    detSort.dir = detSort.idx === i && detSort.dir === "asc" ? "desc" : "asc";
    detSort.idx = i;
    filtrarDetalhe();
  }));
}

function filtrarDetalhe() {
  const termos = semAcento(document.getElementById("det-q").value || "").split(/\s+/).filter(Boolean);
  // filtros estruturados ativos: [idxColuna, valor]
  const fixos = DET_FILTROS
    .map(c => [detCampos.indexOf(c), document.getElementById("f-" + c).value])
    .filter(([, v]) => v !== "");
  detFiltradas = detRows.filter((r, i) => {
    if (!fixos.every(([idx, v]) => r[idx] === v)) return false;
    if (termos.length) { const hay = detNorm[i]; return termos.every(t => hay.includes(t)); }
    return true;
  });
  const i = detSort.idx, dir = detSort.dir === "asc" ? 1 : -1;
  const numerico = DET_NUM.has(detCampos[i]);
  detFiltradas.sort((a, b) => {
    let va = a[i], vb = b[i];
    if (numerico) return ((va ?? 0) - (vb ?? 0)) * dir;
    return String(va ?? "").localeCompare(String(vb ?? "")) * dir;
  });
  renderDetTabela();
}

function renderDetTabela() {
  const totalPag = Math.max(1, Math.ceil(detFiltradas.length / DET_PAGINA));
  detPagina = Math.min(Math.max(1, detPagina), totalPag);
  const ini = (detPagina - 1) * DET_PAGINA;
  const pagina = detFiltradas.slice(ini, ini + DET_PAGINA);
  const numIdx = new Set([...DET_NUM].map(c => detCampos.indexOf(c)));

  const corpo = document.getElementById("det-corpo");
  document.getElementById("det-vazio").hidden = detFiltradas.length > 0;
  corpo.innerHTML = pagina.map(r => "<tr>" + r.map((v, i) => {
    if (numIdx.has(i)) {
      if (v == null) return `<td class="r" style="color:var(--muted)">—</td>`;
      return `<td class="r num${v < 0 ? " neg" : ""}">${brlc(v)}</td>`;
    }
    return `<td title="${esc(v ?? "")}">${esc(v ?? "")}</td>`;
  }).join("") + "</tr>").join("");

  const soma = (campo) => detFiltradas.reduce((s, r) => s + (r[detCampos.indexOf(campo)] ?? 0), 0);
  document.getElementById("det-contagem").textContent =
    `${detFiltradas.length.toLocaleString("pt-BR")} linha(s)`;
  document.getElementById("det-soma").textContent =
    `Empenhado ${brlc(soma("empenhado"))} · Liquidado ${brlc(soma("liquidado"))} · Pago ${brlc(soma("pago"))}`;
  document.getElementById("det-pagina").textContent = `Página ${detPagina} de ${totalPag}`;
  document.getElementById("det-anterior").disabled = detPagina <= 1;
  document.getElementById("det-proxima").disabled = detPagina >= totalPag;
}

// Monta e baixa um CSV (`;`, BOM, CRLF) a partir de campos (chaves) + linhas (arrays).
function baixarCsv(campos, rows, nomeArquivo) {
  const sep = ";";
  const escaparCsv = (v) => {
    const s = String(v ?? "");
    return /[";\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const linhas = [campos.map(c => DET_LABELS[c] || c).join(sep)];
  for (const r of rows) linhas.push(r.map(escaparCsv).join(sep));
  const blob = new Blob(["﻿" + linhas.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = nomeArquivo; a.click();
  URL.revokeObjectURL(url);
}

function exportarDetCsv() {
  if (!detFiltradas.length) { alert("Nada para exportar."); return; }
  baixarCsv(detCampos, detFiltradas, "despesas-detalhe.csv");
}

// ── Ficha do favorecido (modal) ──────────────────────────────────────────────
// Colunas exibidas na ficha (subconjunto de CAMPOS_DETALHE; o CSV exporta o mesmo)
const FAV_COLS = ["data", "unidade_gestora", "tipo", "funcao", "elemento_despesa",
                  "empenho", "empenhado", "liquidado", "pago"];
const FAV_PAGINA = 50;
let FAV_DETALHE = null;   // { campos, rows } — todos os meses concatenados (cacheado)
let favFicha = { nome: "", doc: "", campos: [], rows: [], sort: { idx: 0, dir: "desc" }, pag: 1 };

async function carregarTodoDetalhe() {
  if (FAV_DETALHE) return FAV_DETALHE;
  const meses = DADOS.meses || [];
  const partes = await Promise.all(meses.map(m =>
    fetch("./" + m.arquivo + "?v=" + (DADOS.atualizado_em || "")).then(r => r.json())));
  FAV_DETALHE = { campos: partes[0]?.campos || [], rows: partes.flatMap(p => p.linhas) };
  popularElementosFav();
  return FAV_DETALHE;
}

async function abrirFichaFavorecido(nome, documento) {
  const modal = document.getElementById("fav-modal");
  modal.hidden = false;
  document.getElementById("fav-titulo").textContent = nome;
  document.getElementById("fav-doc").textContent = documento || "";
  document.getElementById("fav-carregando").hidden = false;
  document.getElementById("fav-conteudo").hidden = true;
  try {
    const { campos, rows } = await carregarTodoDetalhe();
    const iN = campos.indexOf("nome_favorecido"), iD = campos.indexOf("documento_favorecido");
    const linhas = rows.filter(r => r[iN] === nome && r[iD] === documento);
    favFicha = { nome, doc: documento, campos, rows: linhas,
                 sort: { idx: campos.indexOf("pago"), dir: "desc" }, pag: 1 };
    renderFichaCabecalho();
    renderFicha();
    document.getElementById("fav-carregando").hidden = true;
    document.getElementById("fav-conteudo").hidden = false;
  } catch (e) {
    document.getElementById("fav-carregando").textContent = "Falha ao carregar os lançamentos.";
  }
}

function fecharFichaFavorecido() {
  document.getElementById("fav-modal").hidden = true;
}

function renderFichaCabecalho() {
  const tr = document.getElementById("fav-cabecalho");
  tr.innerHTML = FAV_COLS.map(c => {
    const i = favFicha.campos.indexOf(c);
    const seta = favFicha.sort.idx === i ? (favFicha.sort.dir === "asc" ? " ▲" : " ▼") : "";
    const cls = DET_NUM.has(c) ? ' class="r"' : "";
    return `<th data-idx="${i}"${cls}>${DET_LABELS[c] || c}${seta}</th>`;
  }).join("");
  tr.querySelectorAll("th").forEach(th => th.addEventListener("click", () => {
    const i = +th.dataset.idx;
    favFicha.sort.dir = favFicha.sort.idx === i && favFicha.sort.dir === "asc" ? "desc" : "asc";
    favFicha.sort.idx = i; favFicha.pag = 1;
    renderFichaCabecalho(); renderFicha();
  }));
}

function renderFicha() {
  const { campos, rows, sort } = favFicha;
  const numerico = DET_NUM.has(campos[sort.idx]);
  const dir = sort.dir === "asc" ? 1 : -1;
  rows.sort((a, b) => {
    let va = a[sort.idx], vb = b[sort.idx];
    if (numerico) return ((va ?? 0) - (vb ?? 0)) * dir;
    return String(va ?? "").localeCompare(String(vb ?? "")) * dir;
  });

  const soma = (campo) => rows.reduce((s, r) => s + (r[campos.indexOf(campo)] ?? 0), 0);
  document.getElementById("fav-resumo").innerHTML =
    `<strong>${rows.length.toLocaleString("pt-BR")}</strong> lançamento(s) de execução · ` +
    `Empenhado ${brlc(soma("empenhado"))} · Liquidado ${brlc(soma("liquidado"))} · ` +
    `Pago ${brlc(soma("pago"))}` +
    `<div class="sub" style="color:var(--muted);font-size:12px;margin-top:4px">` +
    `Execução por empenho — o total pago aproxima o valor agregado da lista de favorecidos.</div>`;

  const totalPag = Math.max(1, Math.ceil(rows.length / FAV_PAGINA));
  favFicha.pag = Math.min(Math.max(1, favFicha.pag), totalPag);
  const ini = (favFicha.pag - 1) * FAV_PAGINA;
  const pagina = rows.slice(ini, ini + FAV_PAGINA);

  const corpo = document.getElementById("fav-corpo");
  document.getElementById("fav-vazio").hidden = rows.length > 0;
  corpo.innerHTML = pagina.map(r => "<tr>" + FAV_COLS.map(c => {
    const i = campos.indexOf(c), v = r[i];
    if (DET_NUM.has(c)) {
      if (v == null) return `<td class="r" style="color:var(--muted)">—</td>`;
      return `<td class="r num${v < 0 ? " neg" : ""}">${brlc(v)}</td>`;
    }
    return `<td title="${esc(v ?? "")}">${esc(v ?? "")}</td>`;
  }).join("") + "</tr>").join("");

  document.getElementById("fav-pagina").textContent = `Página ${favFicha.pag} de ${totalPag}`;
  document.getElementById("fav-anterior").disabled = favFicha.pag <= 1;
  document.getElementById("fav-proxima").disabled = favFicha.pag >= totalPag;
}

function ligarFicha() {
  document.getElementById("fav-fechar").addEventListener("click", fecharFichaFavorecido);
  document.getElementById("fav-modal").addEventListener("click", (e) => {
    if (e.target.id === "fav-modal") fecharFichaFavorecido();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.getElementById("fav-modal").hidden) fecharFichaFavorecido();
  });
  document.getElementById("fav-anterior").addEventListener("click", () => { favFicha.pag--; renderFicha(); });
  document.getElementById("fav-proxima").addEventListener("click", () => { favFicha.pag++; renderFicha(); });
  document.getElementById("fav-csv").addEventListener("click", () => {
    if (!favFicha.rows.length) { alert("Nada para exportar."); return; }
    const nomeArq = "favorecido-" + soDigitos(favFicha.doc || favFicha.nome).slice(0, 20) + ".csv";
    baixarCsv(favFicha.campos, favFicha.rows, nomeArq);
  });
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

init();
