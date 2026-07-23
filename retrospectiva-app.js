// O ano em gastos — scrollytelling sobre o despesas-index.json (zero backend).
"use strict";

const MESES_N = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const el = (id) => document.getElementById(id);
const esc = Comum.escapar;
const reduzMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const brl = (v) => (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const compacto = (v) => {
  const a = Math.abs(v);
  if (a >= 1e9) return "R$ " + (v / 1e9).toFixed(2).replace(".", ",") + " bi";
  if (a >= 1e6) return "R$ " + (v / 1e6).toFixed(1).replace(".", ",") + " mi";
  return brl(v);
};

let DADOS = null, ANO = null;

// contagem crescente (respeita reduced-motion)
function contarAte(elemento, valor, fmt) {
  if (reduzMotion) { elemento.textContent = fmt(valor); return; }
  const t0 = performance.now(), dur = 1300;
  (function tick(t) {
    const p = Math.min(1, (t - t0) / dur), ease = 1 - Math.pow(1 - p, 3);
    elemento.textContent = fmt(valor * ease);
    if (p < 1) requestAnimationFrame(tick);
  })(t0);
}

// gráfico da série do ano desenhado progressivamente (canvas puro)
function desenharSerie(progresso) {
  const cv = el("ch-serie");
  const hoje = new Date();
  const serie = DADOS.series_mensais.filter((s) =>
    s.ano === ANO && !(s.ano === hoje.getFullYear() && s.mes === hoje.getMonth() + 1));
  if (!serie.length) return;
  const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  const cx = cv.getContext("2d");
  cx.scale(dpr, dpr);
  const max = Math.max(...serie.map((s) => s.valor));
  const px = (i) => 8 + (i / Math.max(1, serie.length - 1)) * (w - 60);
  const py = (v) => h - 30 - (v / max) * (h - 60);

  cx.strokeStyle = "rgba(201,168,76,0.25)"; cx.lineWidth = 1;
  cx.beginPath(); cx.moveTo(0, h - 30); cx.lineTo(w, h - 30); cx.stroke();

  const n = Math.max(2, Math.round(serie.length * progresso));
  cx.beginPath();
  serie.slice(0, n).forEach((s, i) => (i ? cx.lineTo(px(i), py(s.valor)) : cx.moveTo(px(0), py(s.valor))));
  cx.strokeStyle = "#e3c977"; cx.lineWidth = 2.5; cx.stroke();

  cx.fillStyle = "#8794a6"; cx.font = "10px 'IBM Plex Mono', monospace";
  serie.forEach((s, i) => { if (i % 2 === 0) cx.fillText(MESES_N[s.mes].slice(0, 3), px(i) - 8, h - 12); });
  if (n === serie.length) {
    const ult = serie[serie.length - 1], iU = serie.length - 1;
    cx.beginPath(); cx.arc(px(iU), py(ult.valor), 4, 0, 7); cx.fillStyle = "#e3c977"; cx.fill();
    cx.fillText(compacto(ult.valor), Math.min(px(iU) - 30, w - 78), py(ult.valor) - 12);
  }
}

function animarSerie() {
  if (reduzMotion) { desenharSerie(1); return; }
  const t0 = performance.now(), dur = 1600;
  (function tick(t) {
    const p = Math.min(1, (t - t0) / dur);
    desenharSerie(p);
    if (p < 1) requestAnimationFrame(tick);
  })(t0);
}

function render() {
  // exclui o mês corrente (parcial) — um mês pela metade viraria um "tombo" falso no fim do gráfico
  const hoje = new Date();
  const serieAno = DADOS.series_mensais.filter((s) =>
    s.ano === ANO && !(s.ano === hoje.getFullYear() && s.mes === hoje.getMonth() + 1));
  const total = DADOS.totais.por_ano?.[String(ANO)] ??
    serieAno.reduce((t, s) => t + s.valor, 0);
  const parcial = serieAno.length < 12;
  const ultimoMes = serieAno.length ? serieAno[serieAno.length - 1].mes : 0;

  el("t-ano").textContent = ANO;
  el("t-abre").textContent = parcial
    ? `De janeiro a ${MESES_N[ultimoMes]}, o caixa da Prefeitura já desembolsou:`
    : "Ao longo de doze meses, o caixa da Prefeitura desembolsou:";

  // maior e menor mês
  if (serieAno.length >= 2) {
    const maior = serieAno.reduce((a, b) => (b.valor > a.valor ? b : a));
    const menor = serieAno.reduce((a, b) => (b.valor < a.valor ? b : a));
    el("t-serie").textContent =
      `O mês mais pesado foi ${MESES_N[maior.mes]} (${compacto(maior.valor)}); ` +
      `o mais leve, ${MESES_N[menor.mes]} (${compacto(menor.valor)}).`;
  }

  el("t-capita-sub").textContent =
    `É o gasto ${parcial ? "no ano até agora" : "do ano"} dividido por cada um dos ` +
    `${Comum.POP_SANTOS.toLocaleString("pt-BR")} habitantes — ` +
    "do bebê recém-nascido ao morador mais antigo da cidade.";

  // funções e favorecidos do ano (se o index já tiver anos_detalhe)
  const det = DADOS.anos_detalhe?.[String(ANO)];
  if (det?.por_funcao?.length) {
    el("cap-funcoes").hidden = false;
    const top = det.por_funcao.slice(0, 5);
    const max = top[0].valor;
    el("lista-funcoes").innerHTML = top.map((f) => `
      <div class="barra-fn rev">
        <div class="topo"><span class="nome">${esc(f.funcao.replace(/^\d+\s*-\s*/, ""))}</span>
          <span class="vlr">${compacto(f.valor)}</span></div>
        <div class="trilho"><div class="fill" style="--w:${Math.round(f.valor / max * 100)}%"></div></div>
      </div>`).join("");
  }
  if (det?.top_favorecidos?.length) {
    el("cap-favorecidos").hidden = false;
    el("lista-favorecidos").innerHTML = det.top_favorecidos.slice(0, 5).map((f, i) => {
      const top = (DADOS.top_favorecidos || []).find((t) =>
        t.nome === f.nome && (t.documento || "") === (f.documento || ""));
      const nome = top?.slug
        ? `<a href="./favorecido.html?f=${encodeURIComponent(top.slug)}">${esc(f.nome)}</a>`
        : esc(f.nome);
      return `<li><span class="pos">${i + 1}</span><span class="quem">${nome}</span>
        <span class="qto">${compacto(f.valor)}</span></li>`;
    }).join("");
  }

  // alertas (vigentes — só faz sentido no ano corrente da base)
  const ultimoAnoBase = Math.max(...DADOS.series_mensais.map((s) => s.ano));
  const alertas = (DADOS.alertas || []).filter((a) => a.severidade !== "baixa");
  if (ANO === ultimoAnoBase && alertas.length) {
    el("cap-alertas").hidden = false;
    el("t-alertas-n").textContent = alertas.length;
    el("lista-alertas").innerHTML = alertas.filter((a) => a.severidade === "alta").slice(0, 3)
      .map((a) => `<div class="alerta-r"><div class="t">${esc(a.titulo)}</div>
        <div class="d">${esc(a.detalhe)}</div></div>`).join("");
  }

  // observador: revela capítulos e dispara animações
  const obs = new IntersectionObserver((entradas) => {
    for (const e of entradas) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("vista");
      if (e.target.id === "cap-abre") contarAte(el("t-total"), total, compacto);
      if (e.target.id === "cap-capita") contarAte(el("t-capita"), total / Comum.POP_SANTOS, brl);
      if (e.target.id === "cap-serie") animarSerie();
      obs.unobserve(e.target);
    }
  }, { threshold: 0.35 });
  document.querySelectorAll(".cap").forEach((s) => obs.observe(s));
}

async function init() {
  const r = await fetch("./despesas-index.json?v=" + Date.now());
  if (!r.ok) { el("t-abre").textContent = "Não foi possível carregar os dados."; return; }
  DADOS = await r.json();

  const anos = [...new Set(DADOS.series_mensais.map((s) => s.ano))].sort((a, b) => b - a);
  const pedido = parseInt(Comum.lerParams().get("ano"), 10);
  ANO = anos.includes(pedido) ? pedido : anos[0];

  const sel = el("ano");
  anos.forEach((a) => sel.add(new Option(a, a)));
  sel.value = ANO;
  sel.addEventListener("change", () => { location.search = "?ano=" + sel.value; });

  render();
}

init();
