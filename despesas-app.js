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
  ligarDetalhe();

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
function renderFavoridosTabela() {
  const termo = (document.getElementById("q").value || "").toLowerCase().trim();
  let linhas = (DADOS.top_favorecidos || []).map(f => ({
    nome: f.nome || "—", valor: f.valor, qtd: f.qtd, meses: f.meses, documento: f.documento || "",
  }));
  if (termo) linhas = linhas.filter(f => f.nome.toLowerCase().includes(termo));
  const dir = favSort.dir === "asc" ? 1 : -1;
  linhas.sort((a, b) => {
    const va = a[favSort.col], vb = b[favSort.col];
    if (typeof va === "string") return va.localeCompare(vb) * dir;
    return (va - vb) * dir;
  });

  const corpo = document.getElementById("corpo-fav");
  document.getElementById("fav-vazio").hidden = linhas.length > 0;
  corpo.innerHTML = linhas.map(f => `
    <tr>
      <td>${esc(f.nome)}${f.documento ? `<div class="sub" style="color:var(--muted);font-size:12px">${esc(f.documento)}</div>` : ""}</td>
      <td class="r num">${brlc(f.valor)}</td>
      <td class="r num">${f.qtd}</td>
      <td class="r num">${f.meses}</td>
    </tr>`).join("");
  document.getElementById("contagem").textContent =
    `${linhas.length} favorecido(s) — top ${DADOS.top_favorecidos.length} por valor`;
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

function exportarDetCsv() {
  if (!detFiltradas.length) { alert("Nada para exportar."); return; }
  const sep = ";";
  const escaparCsv = (v) => {
    const s = String(v ?? "");
    return /[";\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const linhas = [detCampos.map(c => DET_LABELS[c] || c).join(sep)];
  for (const r of detFiltradas) linhas.push(r.map(escaparCsv).join(sep));
  const blob = new Blob(["﻿" + linhas.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "despesas-detalhe.csv"; a.click();
  URL.revokeObjectURL(url);
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

init();
