// Raio-X do favorecido — lê favorecidos/<slug>.json (pré-computado pelo export).
"use strict";

const MESES = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
               "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
// cores conscientes do tema; recalculadas no "temamudou" (repinta sem reload)
let ESCURO, NAVY;
const GOLD = "#c9a84c";
function definirCores() {
  ESCURO = document.documentElement.dataset.tema === "escuro";
  NAVY = ESCURO ? "#9fb6d9" : "#07111f";
  if (window.Chart) {
    Chart.defaults.color = ESCURO ? "#93a0b3" : "#5d6675";
    Chart.defaults.borderColor = ESCURO ? "rgba(147,160,179,.16)" : "rgba(0,0,0,.08)";
  }
}
definirCores();
let DOSSIE = null;
window.addEventListener("temamudou", () => {
  definirCores();
  if (DOSSIE) renderGraficosFav(DOSSIE);
});
const el = (id) => document.getElementById(id);
const esc = (s) => (s == null ? "" : String(s)).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const brl = (v) => (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const brlc = (v) => (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2 });
const compacto = (v) => {
  const a = Math.abs(v);
  if (a >= 1e9) return "R$ " + (v / 1e9).toFixed(1) + " bi";
  if (a >= 1e6) return "R$ " + (v / 1e6).toFixed(1) + " mi";
  if (a >= 1e3) return "R$ " + (v / 1e3).toFixed(0) + " mil";
  return brl(v);
};
const eixoReais = { ticks: { callback: (v) => compacto(v) } };

function falha(msg) {
  el("fav-nome").textContent = "Favorecido não encontrado";
  el("carregando").innerHTML = esc(msg) +
    ' <br><br><a href="./despesas.html#favorecidos">← Voltar ao painel de despesas</a>';
}

// gráficos separados do resto do render: o "temamudou" repinta só esta parte
function renderGraficosFav(d) {
  ["ch-mensal", "ch-funcao"].forEach((id) => {
    const c = Chart.getChart(id);
    if (c) c.destroy();
  });

  // gráfico mensal
  const serie = d.serie_mensal || [];
  new Chart(el("ch-mensal"), {
    type: "bar",
    data: {
      labels: serie.map((s) => `${MESES[s.mes]}/${String(s.ano).slice(2)}`),
      datasets: [{ data: serie.map((s) => s.valor), backgroundColor: GOLD }],
    },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (c) => brlc(c.parsed.y) } } },
      scales: { y: eixoReais } },
  });

  // por função
  const fn = d.por_funcao || [];
  new Chart(el("ch-funcao"), {
    type: "bar",
    data: { labels: fn.map((f) => f.funcao), datasets: [{ data: fn.map((f) => f.valor), backgroundColor: NAVY }] },
    options: { responsive: true, maintainAspectRatio: false, indexAxis: "y",
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (c) => brlc(c.raw) } } },
      scales: { x: eixoReais } },
  });

  // equivalentes acessíveis (tabela oculta + descrição por gráfico)
  Comum.chartAcessivel("ch-mensal",
    `Pagamentos recebidos por mês. Total no mandato: ${compacto(d.total)}.`,
    ["Mês", "Recebido"], serie.map((s) => [`${MESES[s.mes]}/${s.ano}`, compacto(s.valor)]));
  Comum.chartAcessivel("ch-funcao",
    "Distribuição do valor recebido por função de governo.",
    ["Função", "Recebido"], fn.map((f) => [f.funcao, compacto(f.valor)]));
}

function render(d) {
  DOSSIE = d;
  document.title = `${d.nome} — Raio-X do favorecido`;
  el("fav-nome").textContent = d.nome;
  el("fav-doc").textContent = d.documento || "documento não informado";
  el("fav-rank").textContent = d.rank ? `#${d.rank} entre os favorecidos do mandato` : "";
  if (d.atualizado_em)
    el("fav-atualizado").textContent = "atualizado " + new Date(d.atualizado_em).toLocaleDateString("pt-BR");

  // cards
  const anos = Object.keys(d.por_ano || {}).sort();
  const ultimoAno = anos[anos.length - 1];
  const cards = [
    { rotulo: "Total no mandato", valor: compacto(d.total), sub: `${(d.qtd || 0).toLocaleString("pt-BR")} pagamentos` },
    { rotulo: `Em ${ultimoAno || "—"}`, valor: compacto(d.por_ano?.[ultimoAno] || 0), sub: "exercício corrente" },
    { rotulo: "Presença", valor: `${d.meses || 0} meses`, sub: "com pagamento recebido" },
    { rotulo: "Alertas fiscais", valor: String((d.alertas || []).length), sub: "envolvendo este favorecido" },
  ];
  el("stats").innerHTML = cards.map((c) =>
    `<div class="stat"><div class="rotulo">${esc(c.rotulo)}</div>
     <div class="valor">${esc(c.valor)}</div><div class="sub">${esc(c.sub)}</div></div>`).join("");

  renderGraficosFav(d);

  // alertas
  const alertas = d.alertas || [];
  if (alertas.length) {
    el("box-alertas").hidden = false;
    el("lista-alertas").innerHTML = alertas.map((a) => `
      <div class="alerta ${esc(a.severidade)}">
        <span class="sev">${esc(a.severidade)}</span><span class="tit">${esc(a.titulo)}</span>
        <div class="det">${esc(a.detalhe)}</div>
      </div>`).join("");
  }

  // últimos pagamentos (dossiê pré-computado; a rota por documento usa só os lançamentos)
  el("box-pagamentos").hidden = !(d.ultimos_pagamentos || []).length;
  el("corpo-pagamentos").innerHTML = (d.ultimos_pagamentos || []).map((p) => `
    <tr>
      <td data-label="Data">${esc(p.data)}</td>
      <td data-label="Função">${esc(p.funcao)}</td>
      <td data-label="Elemento">${esc(p.elemento)}</td>
      <td data-label="Unidade">${esc(p.unidade)}</td>
      <td data-label="Valor" class="num">${brlc(p.valor)}</td>
    </tr>`).join("");

  el("link-painel").href = "./despesas.html?q=" + encodeURIComponent(d.nome) + "#favorecidos";
  el("carregando").hidden = true;
  el("conteudo").hidden = false;
}

// ── Lançamentos de execução (empenhado/liquidado/pago, todos os meses) ────────
// Mesmo mecanismo do painel: indice-favorecidos.json aponta os meses onde o
// favorecido aparece e só esses dados/AAAA-MM.json são baixados (fallback: todos).
const LANC_COLS = ["data", "unidade_gestora", "tipo", "funcao", "elemento_despesa",
                   "empenho", "empenhado", "liquidado", "pago"];
const LANC_LABELS = {
  data: "Data", unidade_gestora: "Unidade gestora", tipo: "Tipo",
  funcao: "Função", elemento_despesa: "Elemento de despesa", empenho: "Nº empenho",
  empenhado: "Empenhado", liquidado: "Liquidado", pago: "Pago",
};
const LANC_NUM = new Set(["empenhado", "liquidado", "pago"]);
const LANC_PAGINA = 50;
let lanc = { campos: [], rows: [], sort: { idx: 0, dir: "desc" }, pag: 1 };
let IDX_PAINEL = null;

const semAcentoMin = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

async function indicePainel() {
  if (!IDX_PAINEL) {
    const r = await fetch("./despesas-index.json?v=" + Date.now());
    if (!r.ok) throw new Error("HTTP " + r.status);
    IDX_PAINEL = await r.json();
  }
  return IDX_PAINEL;
}

async function buscarLancamentos(nome, doc) {
  const idx = await indicePainel();
  const meses = idx.meses || [];
  let arquivos = meses.map((m) => m.arquivo);
  try {
    const r = await fetch("./despesas/dados/indice-favorecidos.json?v=" + (idx.atualizado_em || ""));
    if (r.ok) {
      const ind = await r.json();
      const chave = (doc || "").replace(/\D/g, "") || semAcentoMin(nome);
      const ms = ind.fav?.[chave];
      if (ms) {
        const quer = new Set(ms);
        arquivos = meses.filter((m) => quer.has(m.ano * 100 + m.mes)).map((m) => m.arquivo);
      }
    }
  } catch (e) { /* sem índice → baixa todos os meses */ }
  const partes = await Promise.all(arquivos.map((a) =>
    fetch("./" + a + "?v=" + (idx.atualizado_em || "")).then((r) => r.json())));
  const campos = partes[0]?.campos || [];
  const iN = campos.indexOf("nome_favorecido"), iD = campos.indexOf("documento_favorecido");
  const digs = (doc || "").replace(/\D/g, "");
  const rows = partes.flatMap((p) => p.linhas).filter((r) =>
    nome ? (r[iN] === nome && (!doc || (r[iD] || "") === doc))
         : ((r[iD] || "").replace(/\D/g, "") === digs && digs));
  return { campos, rows };
}

function renderLancCabecalho() {
  el("lanc-cabecalho").innerHTML = LANC_COLS.map((c) => {
    const i = lanc.campos.indexOf(c);
    const seta = lanc.sort.idx === i ? (lanc.sort.dir === "asc" ? " ▲" : " ▼") : "";
    return `<th data-idx="${i}"${LANC_NUM.has(c) ? ' style="text-align:right"' : ""}>${LANC_LABELS[c]}${seta}</th>`;
  }).join("");
  el("lanc-cabecalho").querySelectorAll("th").forEach((th) =>
    th.addEventListener("click", () => {
      const i = +th.dataset.idx;
      lanc.sort.dir = lanc.sort.idx === i && lanc.sort.dir === "desc" ? "asc" : "desc";
      lanc.sort.idx = i; lanc.pag = 1;
      renderLancCabecalho(); renderLancTabela();
    }));
}

function renderLancTabela() {
  const { campos, rows, sort } = lanc;
  const numerico = LANC_NUM.has(campos[sort.idx]);
  const dir = sort.dir === "asc" ? 1 : -1;
  rows.sort((a, b) => numerico
    ? ((a[sort.idx] ?? 0) - (b[sort.idx] ?? 0)) * dir
    : String(a[sort.idx] ?? "").localeCompare(String(b[sort.idx] ?? "")) * dir);

  const soma = (c) => rows.reduce((s, r) => s + (r[campos.indexOf(c)] ?? 0), 0);
  el("lanc-resumo").textContent =
    `${rows.length.toLocaleString("pt-BR")} lançamento(s) · Empenhado ${compacto(soma("empenhado"))} · ` +
    `Liquidado ${compacto(soma("liquidado"))} · Pago ${compacto(soma("pago"))}`;

  const totalPag = Math.max(1, Math.ceil(rows.length / LANC_PAGINA));
  lanc.pag = Math.min(Math.max(1, lanc.pag), totalPag);
  const pagina = rows.slice((lanc.pag - 1) * LANC_PAGINA, lanc.pag * LANC_PAGINA);
  el("lanc-corpo").innerHTML = pagina.map((r) => "<tr>" + LANC_COLS.map((c) => {
    const v = r[campos.indexOf(c)];
    if (LANC_NUM.has(c)) {
      if (v == null) return '<td class="num" style="color:var(--muted)">—</td>';
      return `<td class="num${v < 0 ? " neg" : ""}">${brlc(v)}</td>`;
    }
    return `<td title="${esc(v ?? "")}">${esc(v ?? "")}</td>`;
  }).join("") + "</tr>").join("");

  el("lanc-pagina").textContent = `Página ${lanc.pag} de ${totalPag}`;
  el("lanc-anterior").disabled = lanc.pag <= 1;
  el("lanc-proxima").disabled = lanc.pag >= totalPag;
}

function iniciarLancamentos(campos, rows) {
  lanc = { campos, rows, sort: { idx: campos.indexOf("pago"), dir: "desc" }, pag: 1 };
  el("lanc-carregando").hidden = true;
  if (!rows.length) { el("lanc-carregando").hidden = false;
    el("lanc-carregando").textContent = "Sem lançamentos de execução para este favorecido."; return; }
  renderLancCabecalho();
  renderLancTabela();
  el("lanc-conteudo").hidden = false;
  el("lanc-anterior").onclick = () => { lanc.pag--; renderLancTabela(); };
  el("lanc-proxima").onclick = () => { lanc.pag++; renderLancTabela(); };
  el("lanc-csv").onclick = () => {
    const idxs = LANC_COLS.map((c) => lanc.campos.indexOf(c));
    Comum.exportarCsv("lancamentos-favorecido.csv",
      LANC_COLS.map((c) => LANC_LABELS[c]),
      lanc.rows.map((r) => idxs.map((i) => r[i])));
  };
}

// Dossiê reconstruído dos lançamentos — p/ favorecidos fora do top-300 (?doc=/&nome=)
function dossieSintetico(nome, doc, campos, rows, atualizadoEm) {
  const i = (c) => campos.indexOf(c);
  const iData = i("data"), iP = i("pago"), iF = i("funcao"),
        iN = i("nome_favorecido"), iD = i("documento_favorecido");
  const porMes = new Map(), porFn = new Map(), porAno = {};
  let total = 0, qtd = 0;
  for (const r of rows) {
    const p = r[iP] || 0;
    if (!p) continue;
    qtd += 1; total += p;
    const m = String(r[iData] || "").slice(0, 7);
    if (m) {
      porMes.set(m, (porMes.get(m) || 0) + p);
      porAno[m.slice(0, 4)] = (porAno[m.slice(0, 4)] || 0) + p;
    }
    const f = r[iF] || "(sem função)";
    porFn.set(f, (porFn.get(f) || 0) + p);
  }
  return {
    nome: nome || rows[0]?.[iN] || "(sem nome)",
    documento: doc || rows[0]?.[iD] || "",
    rank: null, total, qtd, meses: porMes.size, por_ano: porAno,
    serie_mensal: [...porMes.keys()].sort().map((k) =>
      ({ ano: +k.slice(0, 4), mes: +k.slice(5, 7), valor: porMes.get(k) })),
    por_funcao: [...porFn.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6)
      .map(([funcao, valor]) => ({ funcao, valor })),
    ultimos_pagamentos: [], alertas: [], atualizado_em: atualizadoEm,
  };
}

async function init() {
  const params = Comum.lerParams();
  const slug = (params.get("f") || "").trim();

  // rota 1: dossiê pré-computado do top-300 (?f=<slug>) + lançamentos sob demanda
  if (/^[0-9a-f]{6,20}$/i.test(slug)) {
    let d;
    try {
      const r = await fetch(`./favorecidos/${slug}.json`, { cache: "no-cache" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      d = await r.json();
      render(d);
    } catch (e) {
      console.warn("favorecido:", e.message);
      return falha("Dossiê não encontrado — ele cobre os 300 maiores favorecidos e é regerado diariamente.");
    }
    try {
      const { campos, rows } = await buscarLancamentos(d.nome, d.documento || "");
      iniciarLancamentos(campos, rows);
    } catch (e) {
      el("lanc-carregando").textContent = "Falha ao carregar os lançamentos de execução.";
    }
    return;
  }

  // rota 2: qualquer favorecido por documento e/ou nome (?doc=&nome=) — dossiê
  // reconstruído dos próprios lançamentos (sem rank/alertas pré-computados)
  const doc = (params.get("doc") || "").trim();
  const nome = (params.get("nome") || "").trim();
  if (!doc && !nome) return falha("Endereço inválido ou sem favorecido indicado.");
  try {
    const { campos, rows } = await buscarLancamentos(nome, doc);
    if (!rows.length) return falha("Nenhum lançamento encontrado para este favorecido na base do mandato.");
    render(dossieSintetico(nome, doc, campos, rows, (IDX_PAINEL || {}).atualizado_em));
    iniciarLancamentos(campos, rows);
  } catch (e) {
    console.warn("favorecido:", e.message);
    falha("Não foi possível montar a página deste favorecido agora.");
  }
}

init();
