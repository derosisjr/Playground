// Raio-X do favorecido — lê favorecidos/<slug>.json (pré-computado pelo export).
"use strict";

const MESES = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
               "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
const NAVY = "#07111f", GOLD = "#c9a84c";
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

function render(d) {
  document.title = `${d.nome} — Raio-X do favorecido`;
  el("fav-nome").textContent = d.nome;
  el("fav-doc").textContent = d.documento || "documento não informado";
  el("fav-rank").textContent = `#${d.rank} entre os favorecidos do mandato`;
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

  // últimos pagamentos
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

async function init() {
  const slug = (Comum.lerParams().get("f") || "").trim();
  if (!/^[0-9a-f]{6,20}$/i.test(slug)) return falha("Endereço inválido ou sem favorecido indicado.");
  try {
    const r = await fetch(`./favorecidos/${slug}.json`, { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    render(await r.json());
  } catch (e) {
    console.warn("favorecido:", e.message);
    falha("Dossiê não encontrado — ele cobre os 300 maiores favorecidos e é regerado diariamente.");
  }
}

init();
