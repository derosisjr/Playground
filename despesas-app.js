// Radar de Despesas — painel (vanilla + Chart.js)
// Consome despesas-index.json (agregado, gerado por despesas/export.py).

const MESES = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
               "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
// cores dos gráficos conscientes do tema (navy puro sumiria no fundo escuro);
// recalculadas no evento "temamudou" do Comum — os charts repintam sem reload
let ESCURO, NAVY, FILL_SERIE, PALETA;
const GOLD = "#c9a84c";
function definirCores() {
  ESCURO = document.documentElement.dataset.tema === "escuro";
  NAVY = ESCURO ? "#9fb6d9" : "#07111f";
  FILL_SERIE = ESCURO ? "rgba(159,182,217,.10)" : "rgba(10,22,40,.08)";
  PALETA = [ESCURO ? "#9fb6d9" : "#0a1628", "#c9a84c", "#8d9aad", "#5b8def", "#e08a3c",
            "#2fa79a", "#a78bfa", "#e0564a", "#38bdf8", "#84cc16"];
  if (window.Chart) {
    Chart.defaults.color = ESCURO ? "#93a0b3" : "#5d6675";
    Chart.defaults.borderColor = ESCURO ? "rgba(147,160,179,.16)" : "rgba(0,0,0,.08)";
  }
}
definirCores();
window.addEventListener("temamudou", () => {
  definirCores();
  if (DADOS) renderGraficos();
});

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
    Comum.estadoErro("stats",
      "Não foi possível carregar os dados de despesas. Verifique a conexão.", init);
    return;
  }
  renderStats();
  renderResumo();
  renderGraficos();
  renderR100();
  ligarVistaFuncao();
  initMapa();   // treemap (assíncrono; degrada se arvore.json/plugin faltarem)
  initPares();  // benchmark SICONFI (assíncrono; degrada se benchmark.json faltar)
  popularFiltrosAlertas();
  renderAlertas();
  ligarAlertas();
  // deep-link de busca (paleta ⌘K / links externos): ?q= pré-preenche favorecidos
  const qIni = new URLSearchParams(location.search).get("q");
  if (qIni) document.getElementById("q").value = qIni;
  renderFavoridosTabela();
  renderSeletorMeses();
  ligarAbas();
  // deep-link de aba: despesas.html#alertas / #favorecidos / #detalhe
  const aba = location.hash.replace("#", "");
  if (["geral", "alertas", "favorecidos", "detalhe"].includes(aba)) selecionarAba(aba);
  ligarBusca();
  ligarOrdenacao();
  ligarModosFav();
  ligarDetalhe();
  ligarFicha();

  const at = DADOS.atualizado_em ? new Date(DADOS.atualizado_em).toLocaleString("pt-BR") : "";
  const ate = DADOS.dados_ate
    ? " O portal publica com defasagem: pagamentos até " +
      new Date(DADOS.dados_ate.slice(0, 10) + "T12:00:00").toLocaleDateString("pt-BR") + "."
    : "";
  document.getElementById("atualizado").textContent = (at ? "Atualizado em " + at + "." : "") + ate;
}

// ── Cards ────────────────────────────────────────────────────────────────────
const POP_SANTOS = (window.Comum && Comum.POP_SANTOS) || 433656; // IBGE, Censo 2022

function deltaHTML(pct, rotulo) {
  if (pct == null) return "";
  const pos = pct >= 0;
  return ` <span class="delta ${pos ? "pos" : "neg"}" title="${esc(rotulo)}">` +
    `${pos ? "▲" : "▼"} ${Math.abs(pct)}%</span>`;
}

function renderStats() {
  const t = DADOS.totais, p = DADOS.periodo, r = DADOS.resumo;
  const anos = Object.keys(t.por_ano || {}).sort();
  const ultimoAno = anos[anos.length - 1];
  const perCapita = t.geral / POP_SANTOS;
  const yoy = r?.yoy; // acumulado do ano vs mesmo período do ano anterior
  const cards = [
    { rotulo: "Total no período", valor: compacto(t.geral),
      sub: `${p.de} a ${p.ate} · ≈ ${brl(perCapita)} por santista` },
    { rotulo: `Total em ${ultimoAno || "—"}`,
      valor: compacto(t.por_ano?.[ultimoAno] || 0) + deltaHTML(yoy?.pct, "vs mesmo período do ano anterior"),
      sub: yoy ? `vs ${compacto(yoy.anterior)} no mesmo período de ${ultimoAno - 1}` : "exercício corrente" },
    { rotulo: "Pagamentos", valor: t.pagamentos.toLocaleString("pt-BR"), sub: "registros" },
    { rotulo: "Favorecidos", valor: t.favorecidos.toLocaleString("pt-BR"), sub: "distintos" },
  ];
  document.getElementById("stats").innerHTML = cards.map(c =>
    `<div class="stat"><div class="rotulo">${c.rotulo}</div>
     <div class="valor">${c.valor}</div><div class="sub">${c.sub}</div></div>`).join("");
}

// "Em resumo" — narrativa determinística gerada pelo export (DADOS.resumo)
function renderResumo() {
  const box = document.getElementById("em-resumo");
  if (!box || !DADOS.resumo?.texto) return;
  box.querySelector(".resumo-texto").textContent = DADOS.resumo.texto;
  box.hidden = false;
}

// ── Gráficos ─────────────────────────────────────────────────────────────────
function eixoReais() {
  return { ticks: { callback: (v) => compacto(v) } };
}

// Desvio de cada mês vs a média dos até 12 meses anteriores (null = sem base p/ comparar)
function desviosSerie(serie) {
  return serie.map((s, i) => {
    const ant = serie.slice(Math.max(0, i - 12), i);
    if (ant.length < 3) return null;
    const media = ant.reduce((t, x) => t + x.valor, 0) / ant.length;
    return Math.round((s.valor - media) / media * 100);
  });
}

function renderGraficos() {
  // rerender (troca de tema): solta os charts anteriores antes de recriar
  ["ch-mensal", "ch-execucao", "ch-funcao", "ch-fonte", "ch-unidade"].forEach(id => {
    const c = Chart.getChart(id);
    if (c) c.destroy();
  });
  // Série mensal — pontos fora do padrão (>±25% da média móvel) ganham destaque
  const serie = DADOS.series_mensais;
  const desvios = desviosSerie(serie);
  const anomalo = desvios.map(d => d != null && Math.abs(d) > 25);
  new Chart(document.getElementById("ch-mensal"), {
    type: "line",
    data: {
      labels: serie.map(s => `${MESES[s.mes]}/${String(s.ano).slice(2)}`),
      datasets: [{
        data: serie.map(s => s.valor), borderColor: NAVY, backgroundColor: FILL_SERIE,
        fill: true, tension: .25, borderWidth: 2,
        pointRadius: anomalo.map(a => a ? 5 : 2),
        pointBackgroundColor: anomalo.map((a, i) =>
          a ? (desvios[i] > 0 ? "#b42318" : "#b54708") : NAVY),
        pointBorderColor: anomalo.map(a => a ? "#fff" : NAVY),
        pointBorderWidth: anomalo.map(a => a ? 1.5 : 0),
      }],
    },
    options: chartOpts({ y: eixoReais() }, undefined, {
      afterLabel: (c) => anomalo[c.dataIndex]
        ? `${desvios[c.dataIndex] > 0 ? "+" : ""}${desvios[c.dataIndex]}% vs média 12m — fora do padrão, ver aba Alertas`
        : "",
    }),
  });

  // Execução: empenhado × liquidado × pago por mês (tríade coletada pelo crawler)
  renderExecucao();

  // Top funções (barra horizontal, com vista R$ / % / per capita)
  renderFuncao();

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

  // Equivalentes acessíveis: descrição conclusiva + tabela oculta por gráfico
  const ult = serie[serie.length - 1];
  Comum.chartAcessivel("ch-mensal",
    `Total pago por mês. Último mês (${ult ? MESES[ult.mes] + "/" + ult.ano : "—"}): ${ult ? compacto(ult.valor) : "—"}. Pontos fora do padrão são detalhados na aba Alertas.`,
    ["Mês", "Pago", "Desvio vs média 12m"],
    serie.map((s, i) => [`${MESES[s.mes]}/${s.ano}`, compacto(s.valor),
      desvios[i] == null ? "—" : (desvios[i] > 0 ? "+" : "") + desvios[i] + "%"]));
  Comum.chartAcessivel("ch-fonte",
    "Distribuição do gasto pago por fonte de recurso (oito maiores).",
    ["Fonte", "Pago"], ft.map(f => [f.fonte, compacto(f.valor)]));
  Comum.chartAcessivel("ch-unidade",
    `Gasto pago por unidade gestora. Primeira: ${un[0] ? un[0].unidade + ", " + compacto(un[0].valor) : "—"}.`,
    ["Unidade gestora", "Pago"], un.map(u => [u.unidade, compacto(u.valor)]));

  if (ARVORE) renderMapa();   // repinta na troca de tema
  if (PARES) renderPares();
}

// Tríade empenhado/liquidado/pago por mês + taxas de execução do exercício.
// Some quando o índice ainda não traz o bloco "execucao" (JSON antigo).
function renderExecucao() {
  const exe = DADOS.execucao;
  const box = document.getElementById("box-execucao");
  if (!exe?.serie?.length) { if (box) box.hidden = true; return; }
  box.hidden = false;

  const anos = Object.keys(exe.por_ano || {}).sort();
  const ultimo = anos[anos.length - 1];
  const taxas = exe.por_ano?.[ultimo] || {};
  const partes = [];
  if (taxas.taxa_pagamento != null)
    partes.push(`Dos empenhos de ${ultimo}: ${Math.round(taxas.taxa_liquidacao)}% liquidado · ` +
                `${Math.round(taxas.taxa_pagamento)}% pago`);
  if (taxas.restos)
    partes.push(`restos a pagar quitados em ${ultimo}: ${compacto(taxas.restos)}`);
  document.getElementById("exe-taxas").textContent = partes.join(" · ");

  const s = exe.serie;
  const labels = s.map(x => `${MESES[x.mes]}/${String(x.ano).slice(2)}`);
  new Chart(document.getElementById("ch-execucao"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Empenhado", data: s.map(x => x.empenhado), borderColor: PALETA[2],
          borderDash: [6, 4], borderWidth: 2, pointRadius: 0, tension: .25 },
        { label: "Liquidado", data: s.map(x => x.liquidado), borderColor: GOLD,
          borderWidth: 2, pointRadius: 0, tension: .25 },
        { label: "Pago", data: s.map(x => x.pago), borderColor: NAVY,
          backgroundColor: FILL_SERIE, fill: true, borderWidth: 2.5, pointRadius: 0, tension: .25 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, labels: { boxWidth: 18, font: { size: 12 } } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${brlc(c.parsed.y)}` } },
      },
      scales: { y: eixoReais() },
    },
  });

  Comum.chartAcessivel("ch-execucao",
    "Empenhado (compromisso assumido), liquidado (entrega atestada) e pago (dinheiro que saiu) " +
    "em cada mês. " + (partes.length ? partes.join("; ") + "." : ""),
    ["Mês", "Empenhado", "Liquidado", "Pago"],
    s.map((x, i) => [labels[i], compacto(x.empenhado), compacto(x.liquidado), compacto(x.pago)]));
}

// Top funções com três vistas: R$ absoluto, % do total e por habitante (padrão
// dos melhores portais — todo número em três escalas). Rerenderizado pelo toggle.
let fnVista = "reais";

function renderFuncao() {
  const antigo = Chart.getChart("ch-funcao");
  if (antigo) antigo.destroy();
  const fn = DADOS.por_funcao.slice(0, 10);
  const total = DADOS.totais?.geral || 1;
  const conv = fnVista === "pct" ? (v) => 100 * v / total
    : fnVista === "capita" ? (v) => v / POP_SANTOS : (v) => v;
  const fmt = fnVista === "pct" ? (v) => v.toFixed(1).replace(".", ",") + "% do total"
    : (v) => brlc(v);
  const tick = fnVista === "pct" ? (v) => v + "%"
    : fnVista === "capita" ? (v) => brl(v) : (v) => compacto(v);

  new Chart(document.getElementById("ch-funcao"), {
    type: "bar",
    data: {
      labels: fn.map(f => rotulo(f.funcao)),
      datasets: [{ data: fn.map(f => conv(f.valor)), backgroundColor: GOLD }],
    },
    options: chartOpts({ x: { ticks: { callback: tick } } }, "y", {
      label: (c) => fmt(c.raw),
      afterLabel: (c) => fnVista === "reais" ? "" : compacto(fn[c.dataIndex].valor) + " no total",
    }),
  });

  const rotuloVista = fnVista === "pct" ? "% do total pago"
    : fnVista === "capita" ? "valor por habitante (IBGE 2022)" : "total pago";
  Comum.chartAcessivel("ch-funcao",
    `Dez funções com maior gasto no período, em ${rotuloVista}. ` +
    `Primeira: ${fn[0] ? fn[0].funcao + ", " + fmt(conv(fn[0].valor)) : "—"}.`,
    ["Função", rotuloVista], fn.map(f => [f.funcao, fmt(conv(f.valor))]));
}

function ligarVistaFuncao() {
  document.querySelectorAll("#fn-vista button").forEach(b =>
    b.addEventListener("click", () => {
      fnVista = b.dataset.vista;
      document.querySelectorAll("#fn-vista button").forEach(x =>
        x.classList.toggle("primario", x.dataset.vista === fnVista));
      renderFuncao();
    }));
}

// "De cada R$ 100 pagos" — tradução do total em escala humana (barras proporcionais)
function renderR100() {
  const box = document.getElementById("box-r100");
  const fns = DADOS.por_funcao || [];
  const total = DADOS.totais?.geral;
  if (!box || !fns.length || !total) return;
  const top = fns.slice(0, 8);
  const outros = total - top.reduce((s, f) => s + f.valor, 0);
  const itens = top.map(f => ({ nome: nomeFuncao(f.funcao), v: 100 * f.valor / total }));
  if (outros > 0) itens.push({ nome: "Demais áreas", v: 100 * outros / total });
  const max = Math.max(...itens.map(i => i.v));
  document.getElementById("r100-linhas").innerHTML = itens.map(i => `
    <div class="r100-linha">
      <span class="r100-nome" title="${esc(i.nome)}">${esc(i.nome)}</span>
      <span class="r100-barra" aria-hidden="true"><span class="r100-fill" style="width:${(100 * i.v / max).toFixed(1)}%"></span></span>
      <span class="r100-vlr">R$ ${i.v.toFixed(2).replace(".", ",")}</span>
    </div>`).join("");
  document.getElementById("r100-nota").textContent =
    `Distribuição do total pago no período (${compacto(total)}) por função de governo.`;
  box.hidden = false;
}

// ── Mapa do gasto (treemap com drill-down função → subfunção → elemento) ─────
// Consome despesas/arvore.json (gerado pelo export). Degrada em silêncio se o
// arquivo ou o plugin de treemap (CDN) faltarem — a barra de funções cobre o caso.
let ARVORE = null;
let mapaPath = [];   // [] = funções · [i] = subfunções da função i · [i,j] = elementos

async function initMapa() {
  try {
    Chart.registry.getController("treemap");   // lança se o plugin não carregou
    const r = await fetch("./despesas/arvore.json?v=" + (DADOS.atualizado_em || ""));
    if (!r.ok) throw new Error(r.status);
    ARVORE = await r.json();
  } catch (e) { return; }
  document.getElementById("box-mapa").hidden = false;
  renderMapa();
}

function nivelMapa() {
  if (mapaPath.length === 0)
    return { nos: ARVORE.arvore, rotulo: "Todas as áreas", nivel: "função" };
  const fn = ARVORE.arvore[mapaPath[0]];
  if (mapaPath.length === 1)
    return { nos: fn.f, rotulo: nomeFuncao(fn.n), nivel: "subfunção" };
  const sf = fn.f[mapaPath[1]];
  return { nos: sf.f, rotulo: nomeFuncao(sf.n), nivel: "elemento" };
}

function renderMapa() {
  const antigo = Chart.getChart("ch-mapa");
  if (antigo) antigo.destroy();
  const { nos, rotulo: nomeNivel, nivel } = nivelMapa();
  const itens = nos.map((x, i) => ({ n: x.n, v: x.v, i })).filter(x => x.v > 0);
  const total = itens.reduce((s, x) => s + x.v, 0) || 1;
  const max = Math.max(...itens.map(x => x.v));
  const corTexto = ESCURO ? "#eef2f8" : "#07111f";

  new Chart(document.getElementById("ch-mapa"), {
    type: "treemap",
    data: {
      datasets: [{
        tree: itens, key: "v",
        spacing: 2, borderWidth: 0, borderRadius: 3,
        backgroundColor: (c) => {
          if (!c.raw?._data) return "transparent";
          const a = 0.35 + 0.6 * Math.sqrt(c.raw._data.v / max);
          return `rgba(201, 168, 76, ${Math.min(a, 0.95).toFixed(2)})`;
        },
        labels: {
          display: true, color: corTexto, overflow: "hidden",
          font: [{ size: 12, weight: 600 }, { size: 11 }],
          formatter: (c) => c.raw?._data
            ? [nomeFuncao(c.raw._data.n).slice(0, 26), compacto(c.raw._data.v)] : "",
        },
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      onClick: (e, elems, chart) => {
        if (!elems.length) return;
        const dado = chart.data.datasets[0].data[elems[0].index]?._data;
        if (!dado) return;
        const original = nos[dado.i];
        if (mapaPath.length < 2 && original?.f?.length) {
          mapaPath.push(dado.i);
          renderMapa();
        } else {
          Comum.toast(`${original.n} — ${brlc(original.v)}`);
        }
      },
      onHover: (e, elems) => { e.native.target.style.cursor = elems.length ? "pointer" : "default"; },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (its) => its[0]?.raw?._data?.n || "",
            label: (c) => `${brlc(c.raw._data.v)} · ${(100 * c.raw._data.v / total).toFixed(1)}% deste nível`,
          },
        },
      },
    },
  });

  // trilha (breadcrumb) clicável
  const trilha = [{ nome: "Todas as áreas", path: [] }];
  if (mapaPath.length >= 1)
    trilha.push({ nome: nomeFuncao(ARVORE.arvore[mapaPath[0]].n), path: [mapaPath[0]] });
  if (mapaPath.length === 2)
    trilha.push({ nome: nomeFuncao(ARVORE.arvore[mapaPath[0]].f[mapaPath[1]].n),
                  path: mapaPath.slice() });
  document.getElementById("mapa-trilha").innerHTML = trilha.map((t, i) => {
    const atual = i === trilha.length - 1;
    return `<button class="btn${atual ? " primario" : ""}" type="button" data-path="${t.path.join(",")}"
      ${atual ? 'aria-current="true"' : ""}>${esc(t.nome)}</button>`;
  }).join("");
  document.getElementById("mapa-trilha").querySelectorAll("button").forEach(b =>
    b.addEventListener("click", () => {
      mapaPath = b.dataset.path ? b.dataset.path.split(",").map(Number) : [];
      renderMapa();
    }));

  Comum.chartAcessivel("ch-mapa",
    `Mapa do gasto por ${nivel} — nível atual: ${nomeNivel}. ` +
    `Maior item: ${itens[0] ? nomeFuncao(itens[0].n) + ", " + compacto(itens[0].v) : "—"}.`,
    [nivel === "elemento" ? "Elemento de despesa" : nivel === "subfunção" ? "Subfunção" : "Função", "Pago"],
    itens.map(x => [x.n, compacto(x.v)]));
}

// ── Santos × cidades pares (benchmark SICONFI/DCA, per capita) ───────────────
// Consome despesas/benchmark.json (gerado por benchmark.py). Some se faltar.
let PARES = null;
let paresFuncao = "";   // função selecionada (chave completa "10 - Saúde")

async function initPares() {
  try {
    const r = await fetch("./despesas/benchmark.json?v=" + (DADOS.atualizado_em || ""));
    if (!r.ok) throw new Error(r.status);
    PARES = await r.json();
  } catch (e) { return; }
  const santos = PARES.cidades.find(c => c.ibge === 3548500);
  if (!santos) return;
  // opções: funções de Santos por valor desc + "Todas as funções"
  const funcoes = Object.entries(santos.por_funcao)
    .sort((a, b) => b[1].pago - a[1].pago).map(([k]) => k);
  const sel = document.getElementById("pares-funcao");
  sel.innerHTML = '<option value="">Todas as funções (total)</option>' +
    funcoes.map(f => `<option value="${esc(f)}">${esc(nomeFuncao(f))}</option>`).join("");
  sel.addEventListener("change", () => { paresFuncao = sel.value; renderPares(); });
  document.getElementById("box-pares").hidden = false;
  renderPares();
}

function valorPares(cidade) {
  if (paresFuncao) return (cidade.por_funcao[paresFuncao]?.pago || 0) / cidade.pop;
  return Object.values(cidade.por_funcao).reduce((s, f) => s + (f.pago || 0), 0) / cidade.pop;
}

function renderPares() {
  const antigo = Chart.getChart("ch-pares");
  if (antigo) antigo.destroy();
  const cidades = PARES.cidades.map(c => ({ nome: c.nome, ibge: c.ibge, v: valorPares(c) }))
    .sort((a, b) => b.v - a.v);
  const rotuloF = paresFuncao ? nomeFuncao(paresFuncao) : "todas as funções";

  new Chart(document.getElementById("ch-pares"), {
    type: "bar",
    data: {
      labels: cidades.map(c => c.nome),
      datasets: [{
        data: cidades.map(c => c.v),
        backgroundColor: cidades.map(c => c.ibge === 3548500 ? GOLD : (ESCURO ? "#3d4c63" : "#c7cdd8")),
      }],
    },
    options: chartOpts({ x: { ticks: { callback: (v) => brl(v) } } }, "y", {
      label: (c) => `${brlc(c.raw)} por habitante/ano`,
    }),
  });

  // frase determinística: Santos vs mediana dos pares
  const santos = cidades.find(c => c.ibge === 3548500);
  const pares = cidades.filter(c => c.ibge !== 3548500).map(c => c.v).sort((a, b) => a - b);
  const frase = document.getElementById("pares-frase");
  if (santos && pares.length >= 3) {
    const m = pares.length % 2 ? pares[(pares.length - 1) / 2]
      : (pares[pares.length / 2 - 1] + pares[pares.length / 2]) / 2;
    const dif = Math.round(100 * (santos.v - m) / m);
    frase.textContent = `Em ${rotuloF} (${PARES.exercicio}), Santos gastou ${brl(santos.v)} ` +
      `por habitante — ${Math.abs(dif)}% ${dif >= 0 ? "acima" : "abaixo"} da mediana das cidades pares (${brl(m)}).`;
  } else frase.textContent = "";

  document.getElementById("pares-nota").textContent =
    `Fonte: ${PARES.fonte}, exercício ${PARES.exercicio} · população: ${PARES.populacao_fonte}. ` +
    "Competência anual consolidada (inclui administração indireta) — os valores não coincidem " +
    "com a visão de caixa do painel, que usa o portal municipal.";

  Comum.chartAcessivel("ch-pares",
    `Gasto por habitante em ${rotuloF}, exercício ${PARES.exercicio}: Santos comparada a cinco cidades ` +
    `paulistas. ${frase.textContent}`,
    ["Cidade", "R$ por habitante"], cidades.map(c => [c.nome, brl(c.v)]));
}

// "04 - ADMINISTRAÇÃO" → "Administração" (rótulo amigável p/ blocos didáticos)
function nomeFuncao(s) {
  const nice = String(s || "").replace(/^\d+\s*-\s*/, "").trim();
  return nice ? nice.charAt(0) + nice.slice(1).toLowerCase() : "—";
}

function rotulo(s) {
  s = s || "—";
  return s.length > 38 ? s.slice(0, 36) + "…" : s;
}

function chartOpts(scales, indexAxis, tooltipExtra) {
  const o = {
    responsive: true, maintainAspectRatio: false, indexAxis: indexAxis || "x",
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (c) => brlc(indexAxis === "y" ? c.raw : c.parsed.y), ...(tooltipExtra || {}) } },
    },
    scales: {},
  };
  if (scales.x) o.scales.x = scales.x;
  if (scales.y) o.scales.y = scales.y;
  return o;
}

// ── Alertas ──────────────────────────────────────────────────────────────────
const ALERTA_LABELS = {
  favorecido_recorrente: "Favorecido recorrente", concentracao: "Concentração em função",
  pico_mensal: "Pico mensal", extra_orcamentario: "Extra-orçamentário",
  fracionamento: "Possível fracionamento", favorecido_novo: "Favorecido novo",
  crescimento_yoy: "Crescimento anômalo", pf_sensivel: "Pessoa física sensível",
};

function popularFiltrosAlertas() {
  const lista = DADOS.alertas || [];
  const tipos = [...new Set(lista.map(a => a.tipo))];
  const selT = document.getElementById("alerta-tipo");
  selT.innerHTML = '<option value="">Tipo (todos)</option>' +
    tipos.map(t => `<option value="${esc(t)}">${esc(ALERTA_LABELS[t] || t)}</option>`).join("");
}

function ligarAlertas() {
  document.getElementById("alerta-tipo").addEventListener("change", renderAlertas);
  document.getElementById("alerta-sev").addEventListener("change", renderAlertas);
}

function renderAlertas() {
  const lista = DADOS.alertas || [];
  document.getElementById("badge-alertas").textContent = lista.length ? `(${lista.length})` : "";
  const fTipo = document.getElementById("alerta-tipo").value;
  const fSev = document.getElementById("alerta-sev").value;
  const vis = lista.filter(a => (!fTipo || a.tipo === fTipo) && (!fSev || a.severidade === fSev));

  const cont = document.getElementById("lista-alertas");
  document.getElementById("alertas-vazio").hidden = vis.length > 0;
  cont.innerHTML = vis.map(a => `
    <div class="alerta ${a.severidade}" data-fav="${esc(a.filtro?.favorecido || "")}"
         data-elemento="${esc(a.filtro?.elemento || "")}" data-modo="${esc(a.filtro?.tipo_doc || "")}">
      <div class="top">
        <div class="titulo"><span class="sev ${a.severidade}">${a.severidade}</span>${esc(a.titulo)}</div>
        <div class="vlr">${brlc(a.valor)}</div>
      </div>
      <div class="det">${esc(a.detalhe)}</div>
    </div>`).join("");

  cont.querySelectorAll(".alerta").forEach(el => {
    el.addEventListener("click", async () => {
      const fav = el.getAttribute("data-fav");
      if (!fav) return;
      const modo = el.getAttribute("data-modo");
      const elemento = el.getAttribute("data-elemento");
      selecionarAba("favorecidos");
      if (modo) {
        favModo = modo;
        document.querySelectorAll("#fav-modos button").forEach(x =>
          x.classList.toggle("primario", x.dataset.modo === favModo));
      }
      favElemento = elemento || "";
      document.getElementById("q").value = fav;
      await atualizarFav();
      document.getElementById("f-elemento-fav").value = favElemento;
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
let PF_RESUMO = null;         // dados/pf-resumo.json (agregado leve do modo PF)
let PF_FALHOU = false;        // fetch do pf-resumo falhou → usar detalhe completo
let ELEMENTOS = null;         // dados/elementos.json (opções do filtro por tipo)
const FAV_LOTE = 60;          // linhas por lote na lista (o "Mostrar mais")
let favVisiveis = FAV_LOTE;

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
  // PF sem elemento: agregado leve pré-computado (dados/pf-resumo.json).
  if (favModo === "pf" && !favElemento && PF_RESUMO) return PF_RESUMO;
  // Qualquer modo com elemento (ou PF sem o índice leve): agrega do detalhe.
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
  const visiveis = linhas.slice(0, favVisiveis);
  corpo.innerHTML = visiveis.map(f => `
    <tr class="fav-row" style="cursor:pointer" data-nome="${esc(f.nome)}" data-doc="${esc(f.documento)}">
      <td data-label="Favorecido">${esc(f.nome)}${f.documento ? `<div class="sub" style="color:var(--muted);font-size:12px">${esc(f.documento)}</div>` : ""}</td>
      <td data-label="Valor total" class="r num">${brlc(f.valor)}</td>
      <td data-label="Pagamentos" class="r num">${f.qtd}</td>
      <td data-label="Meses" class="r num">${f.meses}</td>
    </tr>`).join("");
  corpo.querySelectorAll(".fav-row").forEach(tr =>
    tr.addEventListener("click", () => abrirFichaFavorecido(tr.dataset.nome, tr.dataset.doc)));
  document.getElementById("fav-mais").hidden = linhas.length <= favVisiveis;
  const rotuloModo = favModo === "pf" ? "pessoa(s) física(s)"
    : favModo === "pj" ? "empresa(s)" : "favorecido(s)";
  document.getElementById("contagem").textContent =
    `${linhas.length} ${rotuloModo} — top ${fonte.length} por valor` +
    (linhas.length > visiveis.length ? ` · exibindo ${visiveis.length}` : "");
}

// Popula o select de elemento de despesa para o tipo selecionado. Fonte leve:
// dados/elementos.json (pré-computado). Fallback: deriva do detalhe completo.
function popularElementosFav() {
  let vals = null;
  if (ELEMENTOS) {
    vals = ELEMENTOS[favModo === "pf" ? "pf" : favModo === "pj" ? "pj" : "todos"] || [];
  } else if (FAV_DETALHE) {
    const pred = predTipoFav();
    const iE = FAV_DETALHE.campos.indexOf("elemento_despesa");
    const iD = FAV_DETALHE.campos.indexOf("documento_favorecido");
    vals = [...new Set(FAV_DETALHE.rows
      .filter(r => r[iE] && pred(r[iD]))
      .map(r => r[iE]))].sort((a, b) => a.localeCompare(b));
  }
  if (!vals) return;
  const sel = document.getElementById("f-elemento-fav");
  // se o elemento escolhido não existe para este tipo, volta para "todos"
  if (favElemento && !vals.includes(favElemento)) favElemento = "";
  sel.innerHTML = '<option value="">Elemento de despesa (todos)</option>' +
    vals.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
  sel.value = favElemento;
}

// Recalcula a lista ativa. Caminhos leves primeiro (pf-resumo/elementos.json);
// o detalhe completo (~20 MB) só quando um ELEMENTO é filtrado.
async function atualizarFav() {
  if (favModo === "pf" && !favElemento && !PF_RESUMO && !PF_FALHOU) {
    document.getElementById("contagem").textContent = "Carregando…";
    try {
      const r = await fetch("./despesas/dados/pf-resumo.json?v=" + (DADOS.atualizado_em || ""));
      if (!r.ok) throw new Error(r.status);
      PF_RESUMO = (await r.json()).itens || [];
    } catch (e) { PF_FALHOU = true; }   // sem o índice leve → cai no detalhe completo
  }
  const precisaDetalhe = favElemento || (favModo === "pf" && !PF_RESUMO);
  if (precisaDetalhe && !FAV_DETALHE) {
    document.getElementById("contagem").textContent = "Carregando…";
    try { await carregarTodoDetalhe(); }
    catch (e) { document.getElementById("contagem").textContent = "Falha ao carregar o detalhe."; return; }
  }
  popularElementosFav();
  renderFavoridosTabela();
}

async function carregarElementosLeve() {
  if (ELEMENTOS) return;
  try {
    const r = await fetch("./despesas/dados/elementos.json?v=" + (DADOS.atualizado_em || ""));
    if (!r.ok) throw new Error(r.status);
    ELEMENTOS = await r.json();
  } catch (e) {
    await carregarTodoDetalhe();   // fallback: detalhe completo
  }
}

function ligarModosFav() {
  document.querySelectorAll("#fav-modos button").forEach(b =>
    b.addEventListener("click", () => {
      favModo = b.dataset.modo;
      document.querySelectorAll("#fav-modos button").forEach(x =>
        x.classList.toggle("primario", x.dataset.modo === favModo));
      favVisiveis = FAV_LOTE;
      atualizarFav();
    }));
  const sel = document.getElementById("f-elemento-fav");
  // Popula as opções ao abrir o select pela 1ª vez (arquivo leve, não os ~20 MB).
  sel.addEventListener("mousedown", () => {
    if (!ELEMENTOS && !FAV_DETALHE) carregarElementosLeve().then(popularElementosFav);
  });
  sel.addEventListener("change", () => { favElemento = sel.value; favVisiveis = FAV_LOTE; atualizarFav(); });
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
  document.getElementById("q").addEventListener("input", () => {
    favVisiveis = FAV_LOTE;
    renderFavoridosTabela();
  });
  document.getElementById("fav-mais").addEventListener("click", () => {
    favVisiveis += FAV_LOTE;
    renderFavoridosTabela();
  });
}
function ligarOrdenacao() {
  document.querySelectorAll("th[data-sort]").forEach(th =>
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      favSort.dir = favSort.col === col && favSort.dir === "desc" ? "asc" : "desc";
      favSort.col = col;
      favVisiveis = FAV_LOTE;
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
  if (!sel.length) { Comum.toast("Selecione ao menos um mês."); return; }
  const res = document.getElementById("det-resultado");
  const carregando = document.getElementById("det-carregando");
  res.hidden = true; carregando.hidden = false;
  try {
    const partes = await carregarPartes(sel.map(c => c.dataset.arquivo));
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

// Baixa um CSV do detalhe (rótulos amigáveis no cabeçalho; dialeto Excel pt-BR do Comum).
function baixarCsv(campos, rows, nomeArquivo) {
  Comum.exportarCsv(nomeArquivo, campos.map(c => DET_LABELS[c] || c), rows);
}

function exportarDetCsv() {
  if (!detFiltradas.length) { Comum.toast("Nada para exportar."); return; }
  baixarCsv(detCampos, detFiltradas, "despesas-detalhe.csv");
}

// ── Ficha do favorecido (modal) ──────────────────────────────────────────────
// Colunas exibidas na ficha (subconjunto de CAMPOS_DETALHE; o CSV exporta o mesmo)
const FAV_COLS = ["data", "unidade_gestora", "tipo", "funcao", "elemento_despesa",
                  "empenho", "empenhado", "liquidado", "pago"];
const FAV_PAGINA = 50;
let FAV_DETALHE = null;   // { campos, rows } — todos os meses concatenados (cacheado)
let FAV_INDICE = null;    // dados/indice-favorecidos.json (favorecido → meses); "erro" = sem índice
let favFicha = { nome: "", doc: "", campos: [], rows: [], sort: { idx: 0, dir: "desc" }, pag: 1 };

// Cache por arquivo mensal: a ficha baixa só os meses do favorecido e o
// Detalhamento/`carregarTodoDetalhe` reaproveitam o que já veio.
const DET_PARTES = new Map();
async function carregarPartes(arquivos) {
  const faltam = arquivos.filter(a => !DET_PARTES.has(a));
  await Promise.all(faltam.map(a =>
    fetch("./" + a + "?v=" + (DADOS.atualizado_em || "")).then(r => r.json())
      .then(p => DET_PARTES.set(a, p))));
  return arquivos.map(a => DET_PARTES.get(a));
}

async function carregarTodoDetalhe() {
  if (FAV_DETALHE) return FAV_DETALHE;
  const partes = await carregarPartes((DADOS.meses || []).map(m => m.arquivo));
  FAV_DETALHE = { campos: partes[0]?.campos || [], rows: partes.flatMap(p => p.linhas) };
  popularElementosFav();
  return FAV_DETALHE;
}

// mesma chave do export (_chave_fav): dígitos do documento; sem doc → nome sem acento
const chaveFavorecido = (nome, doc) => soDigitos(doc || "") || semAcento(nome || "");

// Meses (arquivos) onde o favorecido aparece, via índice leve. null = não sei → todos.
async function arquivosDoFavorecido(nome, documento) {
  if (!FAV_INDICE) {
    try {
      const r = await fetch("./despesas/dados/indice-favorecidos.json?v=" + (DADOS.atualizado_em || ""));
      if (!r.ok) throw new Error(r.status);
      FAV_INDICE = await r.json();
    } catch (e) { FAV_INDICE = "erro"; }
  }
  if (FAV_INDICE === "erro" || !FAV_INDICE.fav) return null;
  const meses = FAV_INDICE.fav[chaveFavorecido(nome, documento)];
  if (!meses) return null;   // fora do índice (ex.: presente em quase todos os meses)
  const quer = new Set(meses);
  return (DADOS.meses || []).filter(m => quer.has(m.ano * 100 + m.mes)).map(m => m.arquivo);
}

async function abrirFichaFavorecido(nome, documento) {
  const modal = document.getElementById("fav-modal");
  modal.hidden = false;
  document.getElementById("fav-titulo").textContent = nome;
  document.getElementById("fav-doc").textContent = documento || "";
  // ponte p/ o raio-X (só p/ o top-300, que tem dossiê pré-computado)
  const raiox = document.getElementById("fav-raiox");
  const top = (DADOS.top_favorecidos || []).find(f => f.nome === nome && (f.documento || "") === (documento || ""));
  raiox.hidden = !top?.slug;
  if (top?.slug) raiox.href = "./favorecido.html?f=" + encodeURIComponent(top.slug);
  document.getElementById("fav-carregando").hidden = false;
  document.getElementById("fav-conteudo").hidden = true;
  try {
    let campos, rows;
    if (FAV_DETALHE) {
      ({ campos, rows } = FAV_DETALHE);        // já está tudo em memória
    } else {
      const arquivos = await arquivosDoFavorecido(nome, documento);
      if (arquivos) {
        const partes = await carregarPartes(arquivos);   // só os meses do favorecido
        campos = partes[0]?.campos || [];
        rows = partes.flatMap(p => p.linhas);
      } else {
        ({ campos, rows } = await carregarTodoDetalhe()); // fallback: tudo
      }
    }
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
    if (!favFicha.rows.length) { Comum.toast("Nada para exportar."); return; }
    const nomeArq = "favorecido-" + soDigitos(favFicha.doc || favFicha.nome).slice(0, 20) + ".csv";
    baixarCsv(favFicha.campos, favFicha.rows, nomeArq);
  });
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

init();
