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
  renderRecibo();
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
  ligarFichaEmpenho();
  // consulta citável: ?dm=… restaura meses+filtros do Detalhamento e auto-carrega
  const pURL = Comum.lerParams();
  if (pURL.get("dm")) aplicarEstadoURL(pURL);

  const at = DADOS.atualizado_em ? new Date(DADOS.atualizado_em).toLocaleString("pt-BR") : "";
  const ate = DADOS.dados_ate
    ? " O portal publica com defasagem: pagamentos até " +
      new Date(DADOS.dados_ate.slice(0, 10) + "T12:00:00").toLocaleDateString("pt-BR") + "."
    : "";
  document.getElementById("atualizado").textContent = (at ? "Atualizado em " + at + "." : "") + ate;
}

// ── Cards ────────────────────────────────────────────────────────────────────
const POP_SANTOS = (window.Comum && Comum.POP_SANTOS) || 418608; // IBGE, Censo 2022 definitivo

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
  // Série mensal — pontos fora do padrão (>±25% da média móvel) ganham destaque;
  // linha de média móvel 3m dá a tendência sem o serrilhado dos pagamentos.
  const serie = DADOS.series_mensais;
  const desvios = desviosSerie(serie);
  const anomalo = desvios.map(d => d != null && Math.abs(d) > 25);
  const mm3 = serie.map((s, i) => i < 2 ? null :
    (serie[i - 2].valor + serie[i - 1].valor + s.valor) / 3);
  const optsMensal = chartOpts({ y: eixoReais() }, undefined, {
    afterLabel: (c) => c.datasetIndex === 0 && anomalo[c.dataIndex]
      ? `${desvios[c.dataIndex] > 0 ? "+" : ""}${desvios[c.dataIndex]}% vs média 12m — fora do padrão, ver aba Alertas`
      : "",
  });
  optsMensal.plugins.legend = { display: true, labels: { boxWidth: 18, font: { size: 12 } } };
  new Chart(document.getElementById("ch-mensal"), {
    type: "line",
    data: {
      labels: serie.map(s => `${MESES[s.mes]}/${String(s.ano).slice(2)}`),
      datasets: [{
        label: "Pago no mês",
        data: serie.map(s => s.valor), borderColor: NAVY, backgroundColor: FILL_SERIE,
        fill: true, tension: .25, borderWidth: 2,
        pointRadius: anomalo.map(a => a ? 5 : 2),
        pointBackgroundColor: anomalo.map((a, i) =>
          a ? (desvios[i] > 0 ? "#b42318" : "#b54708") : NAVY),
        pointBorderColor: anomalo.map(a => a ? "#fff" : NAVY),
        pointBorderWidth: anomalo.map(a => a ? 1.5 : 0),
      }, {
        label: "Média móvel (3 m)",
        data: mm3, borderColor: GOLD, borderDash: [5, 4], borderWidth: 2,
        pointRadius: 0, tension: .3, fill: false,
      }],
    },
    options: optsMensal,
  });

  // Execução: empenhado × liquidado × pago por mês (tríade coletada pelo crawler)
  renderExecucao();

  // Top funções (barra horizontal, com vista R$ / % / per capita)
  renderFuncao();

  // Ano contra ano por função (mesmo período)
  renderComparativo();

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
    `Total pago por mês, com média móvel de três meses. Último mês (${ult ? MESES[ult.mes] + "/" + ult.ano : "—"}): ${ult ? compacto(ult.valor) : "—"}. Pontos fora do padrão são detalhados na aba Alertas.`,
    ["Mês", "Pago", "Média 3 m", "Desvio vs média 12m"],
    serie.map((s, i) => [`${MESES[s.mes]}/${s.ano}`, compacto(s.valor),
      mm3[i] == null ? "—" : compacto(mm3[i]),
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

// ── Comparativo ano contra ano por função (mesmo período jan–M) ──────────────
// Usa series_mensais_por_funcao do índice; compara o acumulado do ano corrente
// (até o último mês COMPLETO) com o mesmo período do ano anterior.
function renderComparativo() {
  const box = document.getElementById("box-comparativo");
  const serie = DADOS.series_mensais_por_funcao || [];
  const ref = DADOS.resumo?.mes_ref;   // último mês completo, calculado no export
  if (!box || !serie.length || !ref) { if (box) box.hidden = true; return; }
  const atual = ref.ano, anterior = atual - 1, mesLim = ref.mes;
  const temAnterior = serie.some(s => s.ano === anterior && s.mes <= mesLim);
  if (!temAnterior) { box.hidden = true; return; }

  const soma = { [atual]: {}, [anterior]: {} };
  for (const s of serie) {
    if (s.mes > mesLim || !(s.ano in soma)) continue;
    soma[s.ano][s.funcao] = (soma[s.ano][s.funcao] || 0) + s.valor;
  }
  const funcoes = Object.entries(soma[atual]).sort((a, b) => b[1] - a[1]).slice(0, 8);

  const antigo = Chart.getChart("ch-comparativo");
  if (antigo) antigo.destroy();
  new Chart(document.getElementById("ch-comparativo"), {
    type: "bar",
    data: {
      labels: funcoes.map(([f]) => rotulo(f)),
      datasets: [
        { label: String(anterior), data: funcoes.map(([f]) => soma[anterior][f] || 0),
          backgroundColor: ESCURO ? "#3d4c63" : "#c7cdd8" },
        { label: String(atual), data: funcoes.map(([f]) => soma[atual][f] || 0),
          backgroundColor: GOLD },
      ],
    },
    options: (() => {
      const o = chartOpts({ x: eixoReais() }, "y", {
        label: (c) => `${c.dataset.label}: ${brlc(c.raw)}`,
        afterLabel: (c) => {
          if (c.dataset.label !== String(atual)) return "";
          const va = soma[anterior][funcoes[c.dataIndex][0]] || 0;
          if (!va) return "sem base no ano anterior";
          const d = Math.round(100 * (c.raw - va) / va);
          return `${d >= 0 ? "+" : ""}${d}% vs ${anterior}`;
        },
      });
      o.plugins.legend = { display: true, labels: { boxWidth: 18, font: { size: 12 } } };
      return o;
    })(),
  });

  document.getElementById("comparativo-titulo").textContent =
    `${atual} × ${anterior}, por função`;
  document.getElementById("comparativo-sub").textContent =
    `Acumulado jan–${MESES[mesLim].toLowerCase()} de cada ano (meses completos).`;
  box.hidden = false;

  Comum.chartAcessivel("ch-comparativo",
    `Gasto pago por função, ${atual} contra ${anterior}, mesmo período (jan–${MESES[mesLim]}).`,
    ["Função", String(anterior), String(atual), "Variação"],
    funcoes.map(([f, v]) => {
      const va = soma[anterior][f] || 0;
      const d = va ? Math.round(100 * (v - va) / va) : null;
      return [f, compacto(va), compacto(v), d == null ? "—" : (d >= 0 ? "+" : "") + d + "%"];
    }));
}

// ── Recibo do contribuinte (didático, IPTU → funções) ────────────────────────
function renderRecibo() {
  const box = document.getElementById("box-recibo");
  const fns = DADOS.por_funcao || [];
  const total = DADOS.totais?.geral;
  if (!box || !fns.length || !total) return;
  const faixa = document.getElementById("recibo-faixa");
  const campo = document.getElementById("recibo-valor");

  const desenhar = () => {
    const valor = Math.max(0, Number(campo.value) || 0);
    const top = fns.slice(0, 8);
    const outros = total - top.reduce((s, f) => s + f.valor, 0);
    const itens = top.map(f => ({ nome: nomeFuncao(f.funcao), v: valor * f.valor / total }));
    if (outros > 0) itens.push({ nome: "Demais áreas", v: valor * outros / total });
    const max = Math.max(...itens.map(i => i.v)) || 1;
    document.getElementById("recibo-linhas").innerHTML = itens.map(i => `
      <div class="r100-linha">
        <span class="r100-nome" title="${esc(i.nome)}">${esc(i.nome)}</span>
        <span class="r100-barra" aria-hidden="true"><span class="r100-fill" style="width:${(100 * i.v / max).toFixed(1)}%"></span></span>
        <span class="r100-vlr">${i.v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}</span>
      </div>`).join("");
  };

  faixa.addEventListener("input", () => { campo.value = faixa.value; desenhar(); });
  campo.addEventListener("input", () => {
    const v = Number(campo.value) || 0;
    faixa.value = Math.min(Math.max(v, faixa.min), faixa.max);
    desenhar();
  });
  desenhar();
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
        } else if (mapaPath.length === 2 && original.n !== "Demais elementos") {
          // folha (elemento) → Detalhamento filtrado por função+elemento
          irParaDetalhe({ funcao: ARVORE.arvore[mapaPath[0]].n, elemento_despesa: original.n });
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
  pico_favorecido: "Pico de um favorecido", pico_elemento: "Pico de um elemento",
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
      if (!fav) {
        // alertas sem favorecido (ex.: pico de elemento) desembocam no Detalhamento
        const elemento = el.getAttribute("data-elemento");
        if (elemento) irParaDetalhe({ elemento_despesa: elemento });
        return;
      }
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

// ── Abas / interações (padrão ARIA APG: tabpanel + navegação por setas) ──────
function ligarAbas() {
  const abas = [...document.querySelectorAll(".tab")];
  abas.forEach((t, i) => {
    t.id = t.id || "tab-" + t.dataset.tab;
    t.setAttribute("aria-controls", "painel-" + t.dataset.tab);
    t.addEventListener("click", () => selecionarAba(t.dataset.tab));
    t.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const prox = abas[(i + (e.key === "ArrowRight" ? 1 : -1) + abas.length) % abas.length];
      prox.focus();
      selecionarAba(prox.dataset.tab);
    });
  });
  document.querySelectorAll(".painel").forEach(p => {
    p.setAttribute("role", "tabpanel");
    p.setAttribute("aria-labelledby", "tab-" + p.id.replace("painel-", ""));
  });
}
function selecionarAba(nome) {
  document.querySelectorAll(".tab").forEach(t => {
    const ativa = t.dataset.tab === nome;
    t.setAttribute("aria-selected", ativa);
    t.tabIndex = ativa ? 0 : -1;
  });
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
// Padrões adotados da pesquisa (Checkbook NYC / USAspending / CGU / Socrata):
// estado na URL (consulta citável), chips de filtros ativos, facetas com
// contagem, faixa de valor, colunas configuráveis, agrupamento com subtotais,
// métrica ativa (empenhado/liquidado/pago) e ficha do empenho por linha.
const DET_LABELS = {
  data: "Data", unidade_gestora: "Unidade gestora", tipo: "Tipo",
  nome_favorecido: "Favorecido", documento_favorecido: "CPF/CNPJ",
  funcao: "Função / área", subfuncao: "Subfunção", programa: "Programa",
  elemento_despesa: "Elemento de despesa", fonte_recurso: "Fonte de recurso",
  grupo_despesa: "Grupo de despesa", empenho: "Nº empenho",
  empenhado: "Empenhado", liquidado: "Liquidado", pago: "Pago",
};
const DET_NUM = new Set(["empenhado", "liquidado", "pago"]);  // colunas de valor
const DET_FILTROS = ["tipo", "unidade_gestora", "funcao", "subfuncao", "programa",
                     "elemento_despesa", "fonte_recurso", "grupo_despesa"];
// chaves curtas na URL (prefixo d p/ não colidir com o ?q= dos Favorecidos)
const DET_URL = { tipo: "dt", unidade_gestora: "du", funcao: "df", subfuncao: "dsf",
                  programa: "dpr", elemento_despesa: "del", fonte_recurso: "dfr",
                  grupo_despesa: "dg" };
const DET_COLS_PADRAO = ["data", "nome_favorecido", "unidade_gestora", "funcao",
                         "elemento_despesa", "empenho", "empenhado", "liquidado", "pago"];
const DET_GRUPOS = { nome_favorecido: "favorecido", funcao: "função",
                     elemento_despesa: "elemento", fonte_recurso: "fonte",
                     unidade_gestora: "unidade gestora", mes: "mês" };
const DET_PAGINA = 100;       // linhas por página (modo plano)
const DET_PAG_GRUPO = 50;     // grupos por página (modo agrupado)
let detCampos = [];
let detRows = [];        // todas as linhas carregadas (arrays)
let detNorm = [];        // texto normalizado (sem acento, minúsculo) por linha, p/ busca
const detArquivoDaLinha = new WeakMap();  // linha → dados/AAAA-MM.json de origem
let detFiltradas = [];
let detSomas = { empenhado: 0, liquidado: 0, pago: 0 };  // memoizado por filtragem
let detGrupos = [];      // modo agrupado: [{chave, n, empenhado, liquidado, pago, linhas}]
let detExpandidos = new Set();

// remove acentos e baixa caixa — busca tolerante a acentuação (dados em PT-BR)
const semAcento = (s) => String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
let detSort = { col: "pago", dir: "desc" };
let detPagina = 1;
let detMetrica = "pago";      // métrica ativa (padrão SIGA): governa destaque/ordenação/faixa
let detGrupo = "";            // "" = tabela plana; senão, coluna de agrupamento
let detVisiveis = (() => {    // colunas exibidas (gerenciador + localStorage)
  try {
    const s = JSON.parse(localStorage.getItem("despesas_det_cols"));
    if (Array.isArray(s) && s.length) return s;
  } catch (e) { /* primeira visita */ }
  return DET_COLS_PADRAO.slice();
})();

// ── Estado na URL (consulta citável — padrão Checkbook/CGU) ──────────────────
function estadoDetalhe() {
  const est = {
    dm: mesesSelecionados().map(c => c.value).join(","),
    dq: document.getElementById("det-q").value.trim(),
    dmin: document.getElementById("det-vmin").value,
    dmax: document.getElementById("det-vmax").value,
    dord: `${detSort.col}:${detSort.dir}`,
    dpg: detPagina > 1 ? String(detPagina) : "",
    dgrp: detGrupo,
    dmet: detMetrica !== "pago" ? detMetrica : "",
    dcols: detVisiveis.join(",") === DET_COLS_PADRAO.join(",") ? "" : detVisiveis.join(","),
  };
  for (const c of DET_FILTROS) est[DET_URL[c]] = document.getElementById("f-" + c).value;
  return est;
}

function sincronizarURL(extra) {
  const atual = Comum.lerParams();
  const obj = {};
  if (atual.get("q")) obj.q = atual.get("q");            // deep-link dos Favorecidos
  Object.assign(obj, estadoDetalhe(), extra || {});
  if (obj.dord === "pago:desc") obj.dord = "";           // default fica fora da URL
  Comum.gravarParams(obj);
}

// aplica o estado vindo da URL (chamado no init quando há dm=) — auto-carrega
async function aplicarEstadoURL(p) {
  const meses = (p.get("dm") || "").split(",").filter(Boolean);
  const chks = [...document.querySelectorAll("#meses-grid input")];
  chks.forEach(c => c.checked = meses.includes(c.value) ||
    meses.some(m => /^\d{4}$/.test(m) && c.value.startsWith(m + "-")));
  atualizarSelInfo();
  if (!chks.some(c => c.checked)) return;
  selecionarAba("detalhe");
  await carregarDetalhe({
    q: p.get("dq") || "",
    filtros: Object.fromEntries(DET_FILTROS.map(c => [c, p.get(DET_URL[c]) || ""])),
    vmin: p.get("dmin") || "", vmax: p.get("dmax") || "",
    ord: p.get("dord") || "", pg: +(p.get("dpg") || 1),
    grp: p.get("dgrp") || "", met: p.get("dmet") || "pago",
    cols: (p.get("dcols") || "").split(",").filter(Boolean),
    emp: p.get("emp") || "",
  });
}

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

// Ponte agregado→transação (padrão Checkbook): marca todos os meses, aplica os
// filtros pedidos e cai na aba já carregando. Usada pelo treemap e por alertas.
function irParaDetalhe(filtros) {
  document.querySelectorAll("#meses-grid input").forEach(c => c.checked = true);
  atualizarSelInfo();
  selecionarAba("detalhe");
  location.hash = "detalhe";
  carregarDetalhe({
    q: "", filtros: { ...Object.fromEntries(DET_FILTROS.map(c => [c, ""])), ...filtros },
    vmin: "", vmax: "", ord: "", pg: 1, grp: "", met: detMetrica, cols: [], emp: "",
  });
}

let detDebounce = null;
function refiltrar() {              // debounce ~150 ms (busca a cada tecla em 57k linhas)
  clearTimeout(detDebounce);
  detDebounce = setTimeout(() => { detPagina = 1; filtrarDetalhe(); }, 150);
}

function ligarDetalhe() {
  document.getElementById("det-limpar").addEventListener("click", () => {
    document.querySelectorAll("#meses-grid input").forEach(c => c.checked = false);
    atualizarSelInfo();
  });
  document.getElementById("det-carregar").addEventListener("click", () => carregarDetalhe());
  document.getElementById("det-q").addEventListener("input", refiltrar);
  DET_FILTROS.forEach(c => document.getElementById("f-" + c)
    .addEventListener("change", () => { detPagina = 1; filtrarDetalhe(); }));
  ["det-vmin", "det-vmax"].forEach(id =>
    document.getElementById(id).addEventListener("input", refiltrar));
  document.getElementById("det-grupo").addEventListener("change", (e) => {
    detGrupo = e.target.value; detPagina = 1; detExpandidos.clear(); filtrarDetalhe();
  });
  document.querySelectorAll("#det-metrica button").forEach(b =>
    b.addEventListener("click", () => {
      detMetrica = b.dataset.met;
      document.querySelectorAll("#det-metrica button").forEach(x =>
        x.classList.toggle("primario", x.dataset.met === detMetrica));
      detSort = { col: detMetrica, dir: "desc" };
      detPagina = 1;
      montarCabecalho();
      filtrarDetalhe();
    }));
  document.getElementById("det-csv").addEventListener("click", exportarDetCsv);
  document.getElementById("det-link").addEventListener("click", async () => {
    sincronizarURL();
    try {
      await navigator.clipboard.writeText(location.href);
      Comum.toast("Link desta consulta copiado.");
    } catch (e) { Comum.toast("Copie o link na barra de endereço."); }
  });
  document.getElementById("det-anterior").addEventListener("click", () => { detPagina--; renderDetTabela(); sincronizarURL(); });
  document.getElementById("det-proxima").addEventListener("click", () => { detPagina++; renderDetTabela(); sincronizarURL(); });
  // glossário fica na Visão geral: troca de aba e abre o <details> no lugar certo
  document.getElementById("det-glossario-link").addEventListener("click", (e) => {
    e.preventDefault();
    selecionarAba("geral");
    const g = document.querySelector("details.entenda");
    if (g) { g.open = true; g.scrollIntoView({ behavior: "smooth", block: "start" }); }
  });
  ligarColunas();
}

// Gerenciador de colunas ("Colunas ▾"): default enxuto aprovado; CSV exporta tudo.
function ligarColunas() {
  const caixa = document.getElementById("det-cols-lista");
  caixa.innerHTML = Object.keys(DET_LABELS).map(c => `
    <label class="mes-chk"><input type="checkbox" value="${c}"
      ${detVisiveis.includes(c) ? "checked" : ""} />${DET_LABELS[c]}</label>`).join("");
  caixa.querySelectorAll("input").forEach(ch => ch.addEventListener("change", () => {
    const marcadas = [...caixa.querySelectorAll("input:checked")].map(x => x.value);
    if (!marcadas.length) { ch.checked = true; Comum.toast("Mantenha ao menos uma coluna."); return; }
    detVisiveis = Object.keys(DET_LABELS).filter(c => marcadas.includes(c));  // ordem canônica
    try { localStorage.setItem("despesas_det_cols", JSON.stringify(detVisiveis)); } catch (e) {}
    montarCabecalho();
    renderDetTabela();
    sincronizarURL();
  }));
  document.getElementById("det-cols-reset").addEventListener("click", () => {
    detVisiveis = DET_COLS_PADRAO.slice();
    try { localStorage.removeItem("despesas_det_cols"); } catch (e) {}
    ligarColunas(); montarCabecalho(); renderDetTabela(); sincronizarURL();
  });
}

async function carregarDetalhe(estado) {
  const sel = mesesSelecionados();
  if (!sel.length) { Comum.toast("Selecione ao menos um mês."); return; }
  const res = document.getElementById("det-resultado");
  const carregando = document.getElementById("det-carregando");
  res.hidden = true; carregando.hidden = false;
  carregando.textContent = "Carregando…";
  try {
    let feitos = 0;
    const arquivos = sel.map(c => c.dataset.arquivo);
    const partes = await carregarPartes(arquivos, () => {
      feitos += 1;
      carregando.textContent = `Baixando ${feitos}/${sel.length} mês(es)…`;
    });
    detCampos = partes[0].campos;
    detRows = [];
    partes.forEach((p, k) => p.linhas.forEach(r => {
      detRows.push(r);
      detArquivoDaLinha.set(r, arquivos[k]);   // p/ a ficha achar o estagios/ do mês
    }));
    detNorm = detRows.map(r => semAcento(r.join(" ")));
    popularFiltros();
    if (estado) {                       // consulta vinda da URL: restaura tudo
      document.getElementById("det-q").value = estado.q;
      DET_FILTROS.forEach(c => { document.getElementById("f-" + c).value = estado.filtros[c] || ""; });
      document.getElementById("det-vmin").value = estado.vmin;
      document.getElementById("det-vmax").value = estado.vmax;
      detMetrica = ["empenhado", "liquidado", "pago"].includes(estado.met) ? estado.met : "pago";
      detGrupo = estado.grp in DET_GRUPOS ? estado.grp : "";
      if (estado.cols.length) detVisiveis = Object.keys(DET_LABELS).filter(c => estado.cols.includes(c));
      const [col, dir] = (estado.ord || "").split(":");
      detSort = DET_LABELS[col] ? { col, dir: dir === "asc" ? "asc" : "desc" }
                                : { col: detMetrica, dir: "desc" };
      detPagina = Math.max(1, estado.pg || 1);
    } else {                            // carga manual: começa limpa
      detSort = { col: detMetrica, dir: "desc" };
      detPagina = 1;
      document.getElementById("det-q").value = "";
      DET_FILTROS.forEach(c => document.getElementById("f-" + c).value = "");
      document.getElementById("det-vmin").value = "";
      document.getElementById("det-vmax").value = "";
    }
    document.getElementById("det-grupo").value = detGrupo;
    document.querySelectorAll("#det-metrica button").forEach(x =>
      x.classList.toggle("primario", x.dataset.met === detMetrica));
    ligarColunas();
    montarCabecalho();
    filtrarDetalhe();
    // dados abertos: link para o JSON bruto de cada mês carregado
    document.getElementById("det-json-links").innerHTML = arquivos.slice(0, 3)
      .map(a => `<a href="./${a}" target="_blank" rel="noopener">${a.split("/").pop()}</a>`)
      .join(" · ") + (arquivos.length > 3 ? ` e mais ${arquivos.length - 3} em despesas/dados/` : "");
    carregando.hidden = true; res.hidden = false;
    if (estado?.emp) abrirFichaEmpenho(null, estado.emp);   // ficha deep-linkada
  } catch (e) {
    carregando.hidden = false;
    carregando.textContent = "Falha ao carregar os dados do período.";
  }
}

// Facetas com contagem (cross-filter): cada select conta as linhas que restariam
// sob TODOS os demais filtros; opções com 0 ficam desabilitadas (menos a ativa).
function popularFiltros() {
  DET_FILTROS.forEach(campo => {
    const i = detCampos.indexOf(campo);
    const sel = document.getElementById("f-" + campo);
    const rotulo = sel.dataset.rotulo || sel.options[0].text;
    sel.dataset.rotulo = rotulo;
    const vals = [...new Set(detRows.map(r => r[i]).filter(v => v != null && v !== ""))]
      .sort((a, b) => String(a).localeCompare(String(b)));
    const atual = sel.value;
    sel.innerHTML = `<option value="">${esc(rotulo)}</option>` +
      vals.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    sel.value = atual;
  });
}

function atualizarFacetas() {
  DET_FILTROS.forEach(campo => {
    const i = detCampos.indexOf(campo);
    const sel = document.getElementById("f-" + campo);
    const base = linhasFiltradas({ ignorar: campo });
    const contagem = new Map();
    for (const r of base) {
      const v = r[i];
      if (v != null && v !== "") contagem.set(v, (contagem.get(v) || 0) + 1);
    }
    for (const op of sel.options) {
      if (!op.value) continue;
      const n = contagem.get(op.value) || 0;
      op.textContent = `${op.value} (${n.toLocaleString("pt-BR")})`;
      op.disabled = n === 0 && sel.value !== op.value;
    }
  });
}

// Uma passada de filtro; `ignorar` exclui um select (p/ contagem de facetas).
function linhasFiltradas(opts) {
  const ignorar = opts?.ignorar;
  const termos = semAcento(document.getElementById("det-q").value || "").split(/\s+/).filter(Boolean);
  const fixos = DET_FILTROS
    .filter(c => c !== ignorar)
    .map(c => [detCampos.indexOf(c), document.getElementById("f-" + c).value])
    .filter(([, v]) => v !== "");
  const iMet = detCampos.indexOf(detMetrica);
  const vmin = parseFloat(document.getElementById("det-vmin").value);
  const vmax = parseFloat(document.getElementById("det-vmax").value);
  const temMin = !isNaN(vmin), temMax = !isNaN(vmax);
  return detRows.filter((r, i) => {
    if (!fixos.every(([idx, v]) => r[idx] === v)) return false;
    if (temMin && (r[iMet] ?? 0) < vmin) return false;
    if (temMax && (r[iMet] ?? 0) > vmax) return false;
    if (termos.length) { const hay = detNorm[i]; return termos.every(t => hay.includes(t)); }
    return true;
  });
}

function montarCabecalho() {
  const tr = document.getElementById("det-cabecalho");
  tr.innerHTML = detVisiveis.map(c => {
    const ordenada = detSort.col === c;
    const seta = ordenada ? (detSort.dir === "asc" ? " ▲" : " ▼") : "";
    const aria = ordenada ? ` aria-sort="${detSort.dir === "asc" ? "ascending" : "descending"}"` : "";
    const destaque = c === detMetrica ? " met-ativa" : "";
    const cls = ` class="${DET_NUM.has(c) ? "r" : ""}${destaque}"`;
    return `<th data-col="${c}"${cls}${aria} tabindex="0" role="columnheader" ` +
      `aria-label="Ordenar por ${DET_LABELS[c]}">${DET_LABELS[c]}${seta}</th>`;
  }).join("");
  const ordenar = (th) => {
    const c = th.dataset.col;
    detSort.dir = detSort.col === c && detSort.dir === "desc" ? "asc" : "desc";
    detSort.col = c;
    detPagina = 1;
    montarCabecalho();
    filtrarDetalhe();
  };
  tr.querySelectorAll("th").forEach(th => {
    th.addEventListener("click", () => ordenar(th));
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ordenar(th); }
    });
  });
}

function filtrarDetalhe() {
  detFiltradas = linhasFiltradas();
  // somas memoizadas (1× por filtragem, não por render)
  detSomas = { empenhado: 0, liquidado: 0, pago: 0 };
  const idx = { empenhado: detCampos.indexOf("empenhado"),
                liquidado: detCampos.indexOf("liquidado"),
                pago: detCampos.indexOf("pago") };
  for (const r of detFiltradas) {
    detSomas.empenhado += r[idx.empenhado] ?? 0;
    detSomas.liquidado += r[idx.liquidado] ?? 0;
    detSomas.pago += r[idx.pago] ?? 0;
  }
  const i = detCampos.indexOf(detSort.col), dir = detSort.dir === "asc" ? 1 : -1;
  const numerico = DET_NUM.has(detSort.col);
  detFiltradas.sort((a, b) => {
    let va = a[i], vb = b[i];
    if (numerico) return ((va ?? 0) - (vb ?? 0)) * dir;
    return String(va ?? "").localeCompare(String(vb ?? "")) * dir;
  });
  if (detGrupo) montarGrupos(idx);
  atualizarFacetas();
  renderChips();
  renderDetTabela();
  sincronizarURL();
}

// Agrupamento com subtotais (pivô-lite Socrata): 1 dimensão, grupos ordenados
// pela métrica ativa, expansíveis para as linhas.
function montarGrupos(idx) {
  const porChave = new Map();
  const iG = detGrupo === "mes" ? detCampos.indexOf("data") : detCampos.indexOf(detGrupo);
  for (const r of detFiltradas) {
    const bruto = detGrupo === "mes" ? String(r[iG] || "").slice(0, 7) : (r[iG] ?? "");
    const chave = bruto === "" ? "(vazio)" : bruto;
    let g = porChave.get(chave);
    if (!g) { g = { chave, n: 0, empenhado: 0, liquidado: 0, pago: 0, linhas: [] }; porChave.set(chave, g); }
    g.n += 1;
    g.empenhado += r[idx.empenhado] ?? 0;
    g.liquidado += r[idx.liquidado] ?? 0;
    g.pago += r[idx.pago] ?? 0;
    g.linhas.push(r);
  }
  detGrupos = [...porChave.values()].sort((a, b) => b[detMetrica] - a[detMetrica]);
}

// chips dos filtros ativos (padrão USAspending): × individual + limpar tudo
function renderChips() {
  const box = document.getElementById("det-chips");
  const chips = [];
  const q = document.getElementById("det-q").value.trim();
  if (q) chips.push({ id: "q", texto: `busca: "${q}"` });
  DET_FILTROS.forEach(c => {
    const v = document.getElementById("f-" + c).value;
    if (v) chips.push({ id: c, texto: `${DET_LABELS[c]}: ${v.length > 34 ? v.slice(0, 32) + "…" : v}` });
  });
  const vmin = document.getElementById("det-vmin").value;
  const vmax = document.getElementById("det-vmax").value;
  if (vmin || vmax)
    chips.push({ id: "faixa", texto: `${DET_LABELS[detMetrica]} ${vmin ? "≥ " + compacto(+vmin) : ""}${vmin && vmax ? " e " : ""}${vmax ? "≤ " + compacto(+vmax) : ""}` });

  box.innerHTML = chips.map(ch =>
    `<button class="chip" type="button" data-chip="${esc(ch.id)}"
       aria-label="Remover filtro ${esc(ch.texto)}">${esc(ch.texto)} ✕</button>`).join("") +
    (chips.length > 1 ? '<button class="chip chip-limpar" type="button" data-chip="*">Limpar tudo</button>' : "");
  box.hidden = chips.length === 0;
  box.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    const alvo = b.dataset.chip;
    if (alvo === "*" || alvo === "q") document.getElementById("det-q").value = alvo === "q" ? "" : document.getElementById("det-q").value;
    if (alvo === "*") {
      document.getElementById("det-q").value = "";
      DET_FILTROS.forEach(c => document.getElementById("f-" + c).value = "");
      document.getElementById("det-vmin").value = "";
      document.getElementById("det-vmax").value = "";
    } else if (alvo === "faixa") {
      document.getElementById("det-vmin").value = "";
      document.getElementById("det-vmax").value = "";
    } else if (alvo !== "q") {
      document.getElementById("f-" + alvo).value = "";
    }
    detPagina = 1;
    filtrarDetalhe();
  }));
}

function renderDetTabela() {
  if (detGrupo) return renderDetGrupos();
  const totalPag = Math.max(1, Math.ceil(detFiltradas.length / DET_PAGINA));
  detPagina = Math.min(Math.max(1, detPagina), totalPag);
  const ini = (detPagina - 1) * DET_PAGINA;
  const pagina = detFiltradas.slice(ini, ini + DET_PAGINA);

  const corpo = document.getElementById("det-corpo");
  document.getElementById("det-vazio").hidden = detFiltradas.length > 0;
  corpo.innerHTML = pagina.map((r, j) => {
    const tds = detVisiveis.map(c => celulaDet(r, c)).join("");
    return `<tr class="det-linha" data-i="${ini + j}" tabindex="0" ` +
      `aria-label="Abrir ficha do empenho ${esc(r[detCampos.indexOf("empenho")] || "")}">${tds}</tr>`;
  }).join("");
  corpo.querySelectorAll(".det-linha").forEach(tr => {
    tr.addEventListener("click", () => abrirFichaEmpenho(detFiltradas[+tr.dataset.i]));
    tr.addEventListener("keydown", (e) => {
      if (e.key === "Enter") abrirFichaEmpenho(detFiltradas[+tr.dataset.i]);
    });
  });
  renderRodapeTabela(totalPag, `${detFiltradas.length.toLocaleString("pt-BR")} linha(s)`);
}

function celulaDet(r, c) {
  const v = r[detCampos.indexOf(c)];
  const destaque = c === detMetrica ? " met-ativa" : "";
  if (DET_NUM.has(c)) {
    if (v == null) return `<td class="r${destaque}" data-label="${DET_LABELS[c]}" style="color:var(--muted)">—</td>`;
    return `<td class="r num${v < 0 ? " neg" : ""}${destaque}" data-label="${DET_LABELS[c]}">${brlc(v)}</td>`;
  }
  return `<td data-label="${DET_LABELS[c]}" title="${esc(v ?? "")}">${esc(v ?? "")}</td>`;
}

function renderDetGrupos() {
  const totalPag = Math.max(1, Math.ceil(detGrupos.length / DET_PAG_GRUPO));
  detPagina = Math.min(Math.max(1, detPagina), totalPag);
  const ini = (detPagina - 1) * DET_PAG_GRUPO;
  const pagina = detGrupos.slice(ini, ini + DET_PAG_GRUPO);
  const span = detVisiveis.length;

  const corpo = document.getElementById("det-corpo");
  document.getElementById("det-vazio").hidden = detGrupos.length > 0;
  corpo.innerHTML = pagina.map(g => {
    const aberto = detExpandidos.has(g.chave);
    let html = `<tr class="det-grupo" data-chave="${esc(g.chave)}" tabindex="0" role="button"
        aria-expanded="${aberto}">
      <td colspan="${span}" data-label="${esc(DET_GRUPOS[detGrupo] || "grupo")}">
        <span class="grp-seta" aria-hidden="true">${aberto ? "▾" : "▸"}</span>
        <strong>${esc(g.chave)}</strong>
        <span class="grp-meta">${g.n.toLocaleString("pt-BR")} doc(s) ·
          Empenhado ${compacto(g.empenhado)} · Liquidado ${compacto(g.liquidado)} ·
          Pago ${compacto(g.pago)}</span>
      </td></tr>`;
    if (aberto) {
      html += g.linhas.map(r =>
        `<tr class="det-linha det-sub" data-emp="${esc(r[detCampos.indexOf("unidade_gestora")])}|${esc(r[detCampos.indexOf("empenho")])}">` +
        detVisiveis.map(c => celulaDet(r, c)).join("") + "</tr>").join("");
    }
    return html;
  }).join("");
  corpo.querySelectorAll(".det-grupo").forEach(tr => {
    const alternar = () => {
      const ch = tr.dataset.chave;
      detExpandidos.has(ch) ? detExpandidos.delete(ch) : detExpandidos.add(ch);
      renderDetTabela();
    };
    tr.addEventListener("click", alternar);
    tr.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); alternar(); }
    });
  });
  corpo.querySelectorAll(".det-sub").forEach(tr =>
    tr.addEventListener("click", (e) => {
      e.stopPropagation();
      const [ug, emp] = tr.dataset.emp.split("|");
      const iU = detCampos.indexOf("unidade_gestora"), iE = detCampos.indexOf("empenho");
      abrirFichaEmpenho(detFiltradas.find(r => r[iU] === ug && r[iE] === emp));
    }));
  renderRodapeTabela(totalPag,
    `${detGrupos.length.toLocaleString("pt-BR")} grupo(s) · ${detFiltradas.length.toLocaleString("pt-BR")} linha(s)`);
}

function renderRodapeTabela(totalPag, contagem) {
  document.getElementById("det-contagem").textContent = contagem;
  document.getElementById("det-soma").textContent =
    `Empenhado ${brlc(detSomas.empenhado)} · Liquidado ${brlc(detSomas.liquidado)} · Pago ${brlc(detSomas.pago)}`;
  document.getElementById("det-pagina").textContent = `Página ${detPagina} de ${totalPag}`;
  document.getElementById("det-anterior").disabled = detPagina <= 1;
  document.getElementById("det-proxima").disabled = detPagina >= totalPag;
  document.getElementById("det-sr").textContent =
    `${contagem}, ordenado por ${DET_LABELS[detSort.col]}, ` +
    `${detSort.dir === "asc" ? "crescente" : "decrescente"}.`;
}

// Baixa um CSV do detalhe (rótulos amigáveis no cabeçalho; dialeto Excel pt-BR do Comum).
function baixarCsv(campos, rows, nomeArquivo) {
  Comum.exportarCsv(nomeArquivo, campos.map(c => DET_LABELS[c] || c), rows);
}

function exportarDetCsv() {
  if (!detFiltradas.length) { Comum.toast("Nada para exportar."); return; }
  if (detGrupo) {   // modo agrupado: exporta os subtotais
    Comum.exportarCsv("despesas-agrupado.csv",
      [DET_GRUPOS[detGrupo] || "grupo", "Documentos", "Empenhado", "Liquidado", "Pago"],
      detGrupos.map(g => [g.chave, g.n, g.empenhado.toFixed(2), g.liquidado.toFixed(2), g.pago.toFixed(2)]));
    return;
  }
  baixarCsv(detCampos, detFiltradas, "despesas-detalhe.csv");
}

// ── Ficha do empenho (modal, padrão CGU: documento + estágios vinculados) ────
const ESTAGIOS_CACHE = new Map();   // arquivo estagios/AAAA-MM.json → dicionário
const FASE_NOME = { E: "Empenho", L: "Liquidação", P: "Pagamento" };

async function abrirFichaEmpenho(row, chaveURL) {
  if (!row && chaveURL) {           // deep-link ?emp=UG|numero
    const [ug, emp] = chaveURL.split("|");
    const iU = detCampos.indexOf("unidade_gestora"), iE = detCampos.indexOf("empenho");
    row = detRows.find(r => r[iU] === ug && r[iE] === emp);
    if (!row) { Comum.toast("Empenho não encontrado nos meses carregados."); return; }
  }
  if (!row) return;
  const v = (c) => row[detCampos.indexOf(c)];
  const chave = `${v("unidade_gestora")}|${v("empenho")}`;

  const modal = document.getElementById("emp-modal");
  modal.hidden = false;
  document.getElementById("emp-titulo").textContent =
    v("empenho") ? `Empenho ${v("empenho")}` : v("tipo");
  document.getElementById("emp-sub").textContent = v("unidade_gestora");
  document.getElementById("emp-tipo-linha").textContent =
    v("tipo") !== "Empenho" ? v("tipo") : "";

  // favorecido com ponte p/ o raio-X (slug do top-300 ou rota por documento)
  const fav = document.getElementById("emp-fav");
  const top = (DADOS.top_favorecidos || []).find(f =>
    f.nome === v("nome_favorecido") && (f.documento || "") === (v("documento_favorecido") || ""));
  fav.textContent = `${v("nome_favorecido")} ${v("documento_favorecido") ? "· " + v("documento_favorecido") : ""}`;
  fav.href = top?.slug
    ? "./favorecido.html?f=" + encodeURIComponent(top.slug)
    : "./favorecido.html?doc=" + encodeURIComponent(v("documento_favorecido") || "") +
      "&nome=" + encodeURIComponent(v("nome_favorecido") || "");

  document.getElementById("emp-classif").innerHTML =
    ["funcao", "subfuncao", "programa", "elemento_despesa", "fonte_recurso", "grupo_despesa", "data"]
      .filter(c => v(c))
      .map(c => `<div class="emp-li"><dt>${DET_LABELS[c]}</dt><dd>${esc(v(c))}</dd></div>`).join("");

  document.getElementById("emp-triade").textContent =
    `Empenhado ${v("empenhado") == null ? "—" : brlc(v("empenhado"))} · ` +
    `Liquidado ${v("liquidado") == null ? "—" : brlc(v("liquidado"))} · ` +
    `Pago ${brlc(v("pago") ?? 0)}`;

  const corpo = document.getElementById("emp-eventos");
  const carregando = document.getElementById("emp-carregando");
  corpo.innerHTML = "";
  document.getElementById("emp-eventos-box").hidden = true;
  carregando.hidden = false;
  carregando.textContent = "Carregando os documentos de estágio…";

  let eventos = null, tipoEmp = "";
  if (v("tipo") === "Extra-orçamentário" || !v("empenho")) {
    eventos = [["P", "—", v("data") || "", v("pago") ?? 0]];
  } else {
    const arquivo = (detArquivoDaLinha.get(row) || "").replace("despesas/dados/", "despesas/dados/estagios/");
    try {
      if (!ESTAGIOS_CACHE.has(arquivo)) {
        const r = await fetch("./" + arquivo + "?v=" + (DADOS.atualizado_em || ""));
        if (!r.ok) throw new Error(r.status);
        ESTAGIOS_CACHE.set(arquivo, await r.json());
      }
      const o = ESTAGIOS_CACHE.get(arquivo)?.[chave];
      if (o) { eventos = o.e; tipoEmp = o.t || ""; }
    } catch (e) { /* sem estágios publicados ainda → degrada abaixo */ }
  }

  document.getElementById("emp-tipo").textContent = tipoEmp ? `Tipo: ${tipoEmp}` : "";
  if (eventos) {
    corpo.innerHTML = eventos.map(ev => {
      const [fase, doc, data, valor] = ev;
      const especie = ev[4] || "Original";
      const badge = especie !== "Original"
        ? ` <span class="emp-especie${especie === "Anulação" ? " anulacao" : ""}">${esc(especie)}</span>` : "";
      return `<tr>
        <td data-label="Fase">${FASE_NOME[fase] || fase}${badge}</td>
        <td data-label="Nº documento">${esc(doc || "—")}</td>
        <td data-label="Data">${esc(data || "—")}</td>
        <td data-label="Valor" class="r num${valor < 0 ? " neg" : ""}">${brlc(valor)}</td>
      </tr>`;
    }).join("");
    carregando.hidden = true;
    document.getElementById("emp-eventos-box").hidden = false;
    fichaEmpAtual = { chave, eventos };
  } else {
    carregando.textContent =
      "Documentos de estágio ainda não publicados para este empenho — mostrando só o resumo acima.";
    fichaEmpAtual = { chave, eventos: [] };
  }
  sincronizarURL({ emp: chave });
}

let fichaEmpAtual = { chave: "", eventos: [] };

function fecharFichaEmpenho() {
  document.getElementById("emp-modal").hidden = true;
  sincronizarURL({ emp: "" });
}

function ligarFichaEmpenho() {
  document.getElementById("emp-fechar").addEventListener("click", fecharFichaEmpenho);
  document.getElementById("emp-modal").addEventListener("click", (e) => {
    if (e.target.id === "emp-modal") fecharFichaEmpenho();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.getElementById("emp-modal").hidden) fecharFichaEmpenho();
  });
  document.getElementById("emp-link").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      Comum.toast("Link da ficha copiado.");
    } catch (e) { Comum.toast("Copie o link na barra de endereço."); }
  });
  document.getElementById("emp-csv").addEventListener("click", () => {
    if (!fichaEmpAtual.eventos.length) { Comum.toast("Nada para exportar."); return; }
    Comum.exportarCsv("empenho-" + fichaEmpAtual.chave.split("|")[1].replace(/\W/g, "-") + ".csv",
      ["Fase", "Nº documento", "Data", "Valor", "Espécie"],
      fichaEmpAtual.eventos.map(ev =>
        [FASE_NOME[ev[0]] || ev[0], ev[1], ev[2], ev[3].toFixed(2), ev[4] || "Original"]));
  });
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
async function carregarPartes(arquivos, aoBaixar) {
  const faltam = arquivos.filter(a => !DET_PARTES.has(a));
  arquivos.filter(a => DET_PARTES.has(a)).forEach(() => aoBaixar && aoBaixar());
  await Promise.all(faltam.map(a =>
    fetch("./" + a + "?v=" + (DADOS.atualizado_em || "")).then(r => r.json())
      .then(p => { DET_PARTES.set(a, p); if (aoBaixar) aoBaixar(); })));
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
  // ponte p/ o raio-X: top-300 usa o dossiê pré-computado (?f=slug); os demais
  // usam a rota por documento/nome (página reconstruída dos lançamentos)
  const raiox = document.getElementById("fav-raiox");
  const top = (DADOS.top_favorecidos || []).find(f => f.nome === nome && (f.documento || "") === (documento || ""));
  raiox.hidden = false;
  raiox.href = top?.slug
    ? "./favorecido.html?f=" + encodeURIComponent(top.slug)
    : "./favorecido.html?doc=" + encodeURIComponent(documento || "") +
      "&nome=" + encodeURIComponent(nome || "");
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
