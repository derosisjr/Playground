// Semáforo Fiscal — painel de endividamento (vanilla + Chart.js)
// Consome endividamento-index.json (gerado por endividamento/export.py).

// cores conscientes do tema; recalculadas no "temamudou" (repinta sem reload)
let ESCURO, NAVY, GOLD, FILL_SERIE, COR_LIMITE, COR_ALERTA, COR_VERDE;
function definirCores() {
  ESCURO = document.documentElement.dataset.tema === "escuro";
  // dourado mais escuro no tema claro: a linha fina precisa de contraste ≥3:1
  NAVY = ESCURO ? "#9fb6d9" : "#07111f";
  GOLD = ESCURO ? "#c9a84c" : "#967c2f";
  FILL_SERIE = ESCURO ? "rgba(159,182,217,.10)" : "rgba(10,22,40,.08)";
  // status nos gráficos (linhas de limite/alerta) — mesmos tokens do CSS
  COR_LIMITE = ESCURO ? "#f87171" : "#b42318";
  COR_ALERTA = ESCURO ? "#fbbf24" : "#b54708";
  COR_VERDE = ESCURO ? "#4ade80" : "#067647";
  if (window.Chart) {
    Chart.defaults.color = ESCURO ? "#93a0b3" : "#5d6675";
    Chart.defaults.borderColor = ESCURO ? "rgba(147,160,179,.16)" : "rgba(0,0,0,.08)";
  }
}
definirCores();
window.addEventListener("temamudou", () => {
  definirCores();
  if (DADOS) renderGraficos();
  if (SD) desenharServicoDivida();
});

let DADOS = null;
let SD = null;   // bloco servico_divida do despesas-index.json (cacheado p/ repintar)

// ── Formatação ───────────────────────────────────────────────────────────────
const brl = (v) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const compacto = (v) => {
  const a = Math.abs(v);
  if (a >= 1e9) return "R$ " + (v / 1e9).toFixed(2).replace(".", ",") + " bi";
  if (a >= 1e6) return "R$ " + (v / 1e6).toFixed(0) + " mi";
  return brl(v);
};
const pct = (v, casas = 1) =>
  v == null ? "—" : v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }) + "%";
const esc = (s) => String(s).replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ── Inicialização ────────────────────────────────────────────────────────────
async function init() {
  try {
    const r = await fetch("./endividamento-index.json?v=" + Date.now());
    if (!r.ok) throw new Error("HTTP " + r.status);
    DADOS = await r.json();
  } catch (e) {
    Comum.estadoErro("semaforo-cards",
      "Não foi possível carregar os dados do painel. Se persistir, a fonte pode estar fora do ar.", init);
    document.getElementById("dados-vivos").hidden = true;
    return;
  }
  renderHero();
  renderSemaforo();
  renderResumo();
  renderGraficos();
  renderEstatais();
  renderServicoDivida();   // fonte secundária (Radar de Despesas); some se falhar
  renderTabela();
  document.getElementById("btn-csv").addEventListener("click", exportarCsv);

  const at = DADOS.atualizado_em ? new Date(DADOS.atualizado_em).toLocaleDateString("pt-BR") : "";
  document.getElementById("atualizado").textContent = at ? "Painel atualizado em " + at + "." : "";
}

// ── Hero: número-âncora ──────────────────────────────────────────────────────
const POP_SANTOS = (window.Comum && Comum.POP_SANTOS) || 418608;

function rotuloLongo(u) {
  return `${u.q}º quadrimestre de ${u.ano}`;
}

function renderHero() {
  const t = DADOS.totais, u = DADOS.ultimo;
  if (!t.divida) return;
  document.getElementById("hero-divida").textContent = compacto(t.divida);
  document.getElementById("hero-contexto").innerHTML =
    `é a <b>dívida consolidada</b> da Prefeitura no ${esc(rotuloLongo(u))} — ` +
    `${esc(pct(t.dc_pct))} da receita corrente líquida, ` +
    `ou <b>${esc(brl(t.divida / POP_SANTOS))} por santista</b>.`;
  document.getElementById("hero-num").hidden = false;
}

// ── Semáforo ─────────────────────────────────────────────────────────────────
const SELOS = {
  verde: "✓ Dentro do limite",
  amarelo: "⚠ Zona de alerta",
  vermelho: "✕ Acima do limite",
};

function renderSemaforo() {
  const u = DADOS.ultimo;
  document.getElementById("semaforo-quando").textContent = "· " + rotuloLongo(u);
  document.getElementById("semaforo-cards").innerHTML = (DADOS.semaforo || []).map(m => {
    const escala = m.limite;                       // medidor vai de 0 ao limite legal
    const uso = Math.max(0, Math.min(1, (m.pct || 0) / escala));
    const marcaAlerta = (m.alerta / escala) * 100;
    const negativo = m.pct != null && m.pct < 0;
    return `
    <div class="mostrador ${m.cor}" role="group" aria-label="${esc(m.nome)}: ${esc(SELOS[m.cor] || "")}">
      <div class="farol" aria-hidden="true">
        <span class="lamp l-verm"></span><span class="lamp l-amar"></span><span class="lamp l-verd"></span>
      </div>
      <div class="m-corpo">
        <span class="selo">${esc(SELOS[m.cor] || m.cor)}</span>
        <p class="m-nome">${esc(m.nome)}</p>
        <p class="m-pergunta">${esc(m.pergunta || "")}</p>
        <div class="m-pct">${esc(pct(m.pct))}<small> da RCL${negativo ? " · caixa maior que a dívida" : ""}</small></div>
        <div class="medidor" aria-hidden="true" style="--alerta-pos:${marcaAlerta.toFixed(1)}%">
          <span class="preench" style="width:${(uso * 100).toFixed(1)}%"></span>
          <span class="marca" style="left:${marcaAlerta.toFixed(1)}%" title="Nível de alerta: ${esc(pct(m.alerta))}"></span>
          <span class="marca lim" style="left:100%" title="Limite legal: ${esc(pct(m.limite))}"></span>
        </div>
        <div class="m-escala"><span>0%</span><span>alerta ${esc(pct(m.alerta))}</span><span>limite ${esc(pct(m.limite))}</span></div>
        <p class="m-rodape">${m.valor != null ? `<b>${esc(compacto(m.valor))}</b> · ` : ""}${esc(m.base_legal || "")}</p>
      </div>
    </div>`;
  }).join("");
}

function renderResumo() {
  const box = document.getElementById("em-resumo");
  if (!DADOS.resumo) return;
  box.querySelector(".resumo-texto").textContent = DADOS.resumo;
  box.hidden = false;
}

// ── Gráficos ─────────────────────────────────────────────────────────────────
const rotuloQ = (p) => `${p.q}º/${String(p.ano).slice(2)}`;

function linhaLimite(rotulo, valor, cor, n) {
  return { label: rotulo, data: Array(n).fill(valor), borderColor: cor,
           borderDash: [6, 5], borderWidth: 1.5, pointRadius: 0, fill: false };
}

function opts(fmtY, comLegenda) {
  return {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: !!comLegenda, labels: { boxWidth: 14, boxHeight: 3, font: { size: 11 } } },
      tooltip: { callbacks: { label: (c) => `${c.dataset.label || ""}: ${fmtY(c.parsed.y)}` } },
    },
    scales: { y: { ticks: { callback: (v) => fmtY(v) } } },
  };
}

function renderGraficos() {
  if (!window.Chart) return;
  // rerender (troca de tema): solta os charts anteriores antes de recriar
  ["ch-divida", "ch-dcl-pct", "ch-pessoal", "ch-precatorios", "ch-caixa"].forEach(id => {
    const c = Chart.getChart(id);
    if (c) c.destroy();
  });
  const S = DADOS.serie || [];
  const labels = S.map(rotuloQ);
  const n = S.length;

  // Dívida bruta × líquida
  new Chart(document.getElementById("ch-divida"), {
    type: "line",
    data: { labels, datasets: [
      { label: "Dívida bruta (DC)", data: S.map(p => p.dc), borderColor: NAVY,
        backgroundColor: FILL_SERIE, fill: true, tension: .25, borderWidth: 2, pointRadius: 2 },
      { label: "Dívida líquida (DCL)", data: S.map(p => p.dcl), borderColor: GOLD,
        tension: .25, borderWidth: 2, pointRadius: 2, fill: false },
    ] },
    options: opts(compacto, true),
  });

  // DCL % da RCL vs limites
  new Chart(document.getElementById("ch-dcl-pct"), {
    type: "line",
    data: { labels, datasets: [
      { label: "DCL / RCL", data: S.map(p => p.dcl_pct), borderColor: NAVY,
        backgroundColor: FILL_SERIE, fill: true, tension: .25, borderWidth: 2, pointRadius: 2 },
      linhaLimite("Limite legal (120%)", 120, COR_LIMITE, n),
      linhaLimite("Alerta (108%)", 108, COR_ALERTA, n),
    ] },
    options: opts((v) => pct(v, 0), true),
  });

  // Pessoal % da RCL vs limites
  new Chart(document.getElementById("ch-pessoal"), {
    type: "line",
    data: { labels, datasets: [
      { label: "Pessoal / RCL", data: S.map(p => p.pessoal_pct), borderColor: NAVY,
        backgroundColor: FILL_SERIE, fill: true, tension: .25, borderWidth: 2, pointRadius: 2 },
      linhaLimite("Limite legal (54%)", 54, COR_LIMITE, n),
      linhaLimite("Alerta (48,6%)", 48.6, COR_ALERTA, n),
    ] },
    options: opts((v) => pct(v, 0), true),
  });

  // Precatórios vencidos
  new Chart(document.getElementById("ch-precatorios"), {
    type: "bar",
    data: { labels, datasets: [
      { label: "Precatórios vencidos e não pagos", data: S.map(p => p.precatorios),
        backgroundColor: GOLD, borderRadius: 4, maxBarThickness: 26 },
    ] },
    options: opts(compacto, false),
  });

  // Restos a pagar × caixa
  new Chart(document.getElementById("ch-caixa"), {
    type: "line",
    data: { labels, datasets: [
      { label: "Caixa bruto", data: S.map(p => p.caixa_bruta), borderColor: COR_VERDE,
        tension: .25, borderWidth: 2, pointRadius: 2, fill: false },
      { label: "Restos a pagar", data: S.map(p => p.rp), borderColor: COR_LIMITE,
        tension: .25, borderWidth: 2, pointRadius: 2, fill: false },
    ] },
    options: opts(compacto, true),
  });

  // Equivalentes acessíveis: descrição conclusiva + tabela oculta por gráfico
  const u = S[S.length - 1] || {};
  const vc = (v) => (v != null ? compacto(v) : "—");
  Comum.chartAcessivel("ch-divida",
    `Dívida bruta e líquida por quadrimestre. Em ${u.rotulo || "—"}: bruta ${vc(u.dc)}, líquida ${vc(u.dcl)}.`,
    ["Quadrimestre", "Dívida bruta", "Dívida líquida"],
    S.map(p => [p.rotulo, vc(p.dc), vc(p.dcl)]));
  Comum.chartAcessivel("ch-dcl-pct",
    `Dívida consolidada líquida em percentual da RCL, contra o limite legal de 120% e o alerta de 108%. Em ${u.rotulo || "—"}: ${pct(u.dcl_pct)}.`,
    ["Quadrimestre", "DCL/RCL"],
    S.map(p => [p.rotulo, pct(p.dcl_pct)]));
  Comum.chartAcessivel("ch-pessoal",
    `Despesa com pessoal em percentual da RCL, contra o limite legal de 54% e o alerta de 48,6%. Em ${u.rotulo || "—"}: ${pct(u.pessoal_pct)}.`,
    ["Quadrimestre", "Pessoal/RCL"],
    S.map(p => [p.rotulo, pct(p.pessoal_pct)]));
  Comum.chartAcessivel("ch-precatorios",
    `Precatórios vencidos e não pagos por quadrimestre. Em ${u.rotulo || "—"}: ${vc(u.precatorios)}.`,
    ["Quadrimestre", "Precatórios vencidos"],
    S.map(p => [p.rotulo, vc(p.precatorios)]));
  Comum.chartAcessivel("ch-caixa",
    `Caixa bruto contra restos a pagar por quadrimestre. Em ${u.rotulo || "—"}: caixa ${vc(u.caixa_bruta)}, restos a pagar ${vc(u.rp)}.`,
    ["Quadrimestre", "Caixa bruto", "Restos a pagar"],
    S.map(p => [p.rotulo, vc(p.caixa_bruta), vc(p.rp)]));
}

// ── Dívida das estatais (curadoria anual — endividamento/estatais.json) ─────
function renderEstatais() {
  const e = DADOS.estatais;
  if (!e || !e.empresas || !e.empresas.length) return;
  document.getElementById("sec-estatais").hidden = false;
  document.getElementById("estatais-cards").innerHTML = e.empresas.map(emp => {
    const varPassivo = emp.passivo_exercicio_anterior
      ? (emp.passivo_total / emp.passivo_exercicio_anterior - 1) * 100 : null;
    return `
    <div class="box estatal">
      <div class="cabeca">
        <span class="sigla">${esc(emp.sigla)}</span>
        <span class="exercicio">${esc(emp.nome)} · balanço 31/12/${emp.exercicio}</span>
      </div>
      <div class="numeros">
        <div class="n-item"><span class="v">${esc(compacto(emp.passivo_total))}</span>
          <span class="l">passivo total${varPassivo != null
            ? ` · ${varPassivo >= 0 ? "+" : "−"}${Math.abs(varPassivo).toFixed(0)}% vs ${emp.exercicio - 1}` : ""}</span></div>
        ${emp.patrimonio_liquido != null ? `
        <div class="n-item"><span class="v${emp.patrimonio_liquido < 0 ? " neg" : ""}">${esc(compacto(emp.patrimonio_liquido))}</span>
          <span class="l">patrimônio líquido</span></div>` : ""}
      </div>
      <ul class="comp">
        ${(emp.componentes || []).map(c =>
          `<li><span>${esc(c.nome)}</span><span class="cv">${esc(compacto(c.valor))}</span></li>`).join("")}
      </ul>
      ${emp.nota ? `<p class="nota-estatal">${esc(emp.nota)}</p>` : ""}
      <p class="nota-estatal fonte-estatal">Fonte: <a href="${esc(emp.url)}" rel="noopener">${esc(emp.fonte)}</a></p>
    </div>`;
  }).join("");
  const pend = e.pendentes || [];
  if (pend.length) {
    document.getElementById("estatais-pendentes").innerHTML =
      `<b>${pend.map(p => esc(p.sigla)).join(" e ")}:</b> balanços ainda não localizados em ` +
      `formato aberto — o portal de transparência municipal publica só a execução ` +
      `(licitações, contratos, folha). Assim que publicados, entram aqui.`;
  }
}

// ── Serviço da dívida (credores) — dados do Radar de Despesas ────────────────
// Nome do credor sem o CNPJ embutido e encurtado p/ o eixo do gráfico.
function nomeCredor(s) {
  s = String(s).replace(/\s*\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2}\s*/g, " ").trim();
  return s.length > 34 ? s.slice(0, 32) + "…" : s;
}

async function renderServicoDivida() {
  try {
    const r = await fetch("./despesas-index.json?v=" + Date.now());
    if (!r.ok) throw new Error("HTTP " + r.status);
    const sd = (await r.json()).servico_divida;
    if (!sd || !sd.credores || !sd.credores.length) return;
    SD = sd;
  } catch (e) { return; }  // sem a base de despesas, a seção simplesmente não aparece
  document.getElementById("sec-servico").hidden = false;
  desenharServicoDivida();
}

// desenho separado da carga: o "temamudou" repinta usando o SD cacheado
function desenharServicoDivida() {
  if (!window.Chart || !SD) return;
  ["ch-credores", "ch-servico-ano"].forEach(id => {
    const c = Chart.getChart(id);
    if (c) c.destroy();
  });
  const sd = SD;

  // Credores (barra horizontal)
  const cred = sd.credores.filter(c => c.valor >= 1e5).slice(0, 8);
  new Chart(document.getElementById("ch-credores"), {
    type: "bar",
    data: { labels: cred.map(c => nomeCredor(c.nome)), datasets: [
      { label: "Pago no mandato", data: cred.map(c => c.valor),
        backgroundColor: GOLD, borderRadius: 4, maxBarThickness: 22 },
    ] },
    options: {
      responsive: true, maintainAspectRatio: false, indexAxis: "y",
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (c) => compacto(c.parsed.x) } } },
      scales: { x: { ticks: { callback: (v) => compacto(v) } } },
    },
  });

  // Juros × amortização por ano (barras agrupadas)
  const anos = [...new Set(sd.por_ano.map(p => p.ano))].sort();
  const serie = (tipo) => anos.map(a =>
    (sd.por_ano.find(p => p.ano === a && p.tipo === tipo) || {}).valor || 0);
  new Chart(document.getElementById("ch-servico-ano"), {
    type: "bar",
    data: { labels: anos, datasets: [
      { label: "Juros e encargos", data: serie("juros"),
        backgroundColor: NAVY, borderRadius: 4, maxBarThickness: 40 },
      { label: "Amortização", data: serie("amortizacao"),
        backgroundColor: GOLD, borderRadius: 4, maxBarThickness: 40 },
    ] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 14, boxHeight: 3, font: { size: 11 } } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${compacto(c.parsed.y)}` } } },
      scales: { y: { ticks: { callback: (v) => compacto(v) } } },
    },
  });

  Comum.chartAcessivel("ch-credores",
    "Maiores credores do serviço da dívida no mandato (juros e amortização pagos).",
    ["Credor", "Pago no mandato"],
    cred.map(c => [nomeCredor(c.nome), compacto(c.valor)]));
  const vJuros = serie("juros"), vAmort = serie("amortizacao");
  Comum.chartAcessivel("ch-servico-ano",
    "Juros e encargos contra amortização pagos por ano.",
    ["Ano", "Juros e encargos", "Amortização"],
    anos.map((a, i) => [a, compacto(vJuros[i]), compacto(vAmort[i])]));
}

// ── Tabela + CSV ─────────────────────────────────────────────────────────────
function renderTabela() {
  const S = [...(DADOS.serie || [])].reverse();   // mais recente primeiro
  document.getElementById("tab-corpo").innerHTML = S.map(p => `
    <tr>
      <td>${esc(p.rotulo)}</td>
      <td class="num">${p.dc != null ? esc(compacto(p.dc)) : "—"}</td>
      <td class="num">${p.dcl != null ? esc(compacto(p.dcl)) : "—"}</td>
      <td class="num">${p.rcl != null ? esc(compacto(p.rcl)) : "—"}</td>
      <td class="num">${esc(pct(p.dcl_pct))}</td>
      <td class="num">${esc(pct(p.pessoal_pct))}</td>
      <td class="num">${esc(pct(p.opcred_pct))}</td>
      <td class="num">${p.precatorios != null ? esc(compacto(p.precatorios)) : "—"}</td>
    </tr>`).join("");
  document.getElementById("tab-contagem").textContent =
    `${S.length} quadrimestres · ${S.length ? S[S.length - 1].ano + "–" + S[0].ano : ""}`;
}

function exportarCsv() {
  const S = DADOS.serie || [];
  Comum.exportarCsv("endividamento-santos.csv",
    ["Período", "Dívida bruta (R$)", "Dívida líquida (R$)", "RCL (R$)",
     "DCL/RCL (%)", "Pessoal/RCL (%)", "Op. crédito/RCL (%)", "Precatórios vencidos (R$)"],
    S.map(p => [p.rotulo, p.dc, p.dcl, p.rcl, p.dcl_pct, p.pessoal_pct, p.opcred_pct, p.precatorios]));
}

init();
