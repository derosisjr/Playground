// Painel Preço comparado — lista de comparações curadas e o detalhe de cada uma.
// Índice leve na raiz (precos-index.json); o detalhe de cada comparação vem de
// precos/dados/<slug>.json, baixado só quando a comparação é aberta.
"use strict";

let ESCURO, GOLD, MUTED, LINHA, VERMELHO, VERDE;
let INDICE = null;
let DETALHE = null;
let ORDEM = { col: "preco", dir: 1 };
// Snapshot da URL de entrada. `Comum.gravarParams` substitui a query inteira, e
// a troca de aba acontece ANTES de o catálogo ler seus filtros — sem esta cópia,
// abrir ?aba=itens&iq=cadeira perderia o `iq` no caminho.
const PARAMS_INICIAIS = new URLSearchParams(location.search);

function definirCores() {
  ESCURO = document.documentElement.dataset.tema === "escuro";
  GOLD = ESCURO ? "#e3c977" : "#c9a84c";
  MUTED = ESCURO ? "#93a0b3" : "#5d6675";
  LINHA = ESCURO ? "rgba(255,255,255,.12)" : "#e2dccd";
  VERMELHO = ESCURO ? "#f87171" : "#b42318";
  VERDE = ESCURO ? "#4ade80" : "#067647";
  if (window.Chart) {
    Chart.defaults.color = MUTED;
    Chart.defaults.borderColor = LINHA;
    Chart.defaults.font.family = "Manrope, sans-serif";
  }
}
definirCores();

// Preço unitário de material de consumo vive na casa dos centavos: com 2 casas,
// Santos (R$ 0,0737) e a mediana (R$ 0,0695) viram ambos "R$ 0,07" e a
// comparação some. A precisão é decidida UMA vez por comparação, a partir da
// menor grandeza envolvida, e usada em toda a tela — casas variando de linha
// para linha na mesma tabela seria pior que arredondar.
let CASAS = 2;

function definirCasas(valores) {
  const v = valores.filter((x) => x != null && x !== 0).map(Math.abs);
  if (!v.length) { CASAS = 2; return; }
  const menor = Math.min(...v);
  CASAS = menor >= 1 ? 2 : menor >= 0.01 ? 4 : 6;
}

const brl = (v) =>
  v == null ? "—" : "R$ " + Number(v).toLocaleString("pt-BR",
    { minimumFractionDigits: CASAS, maximumFractionDigits: CASAS });

/** Preço por LINHA, para o catálogo. Ali a faixa vai de centavos a dezenas de
 *  milhares: uma precisão única para a coluna inteira escreveria "R$ 1.549,0000"
 *  ao lado de "R$ 0,0900". Na comparação isso não acontece — os preços são do
 *  mesmo item, e lá a precisão única é o que mantém as linhas comparáveis. */
const brlAuto = (v) => {
  if (v == null) return "—";
  const casas = Math.abs(v) >= 1 ? 2 : 4;
  return "R$ " + Number(v).toLocaleString("pt-BR",
    { minimumFractionDigits: casas, maximumFractionDigits: casas });
};
const num = (v, casas = 0) =>
  v == null ? "—" : Number(v).toLocaleString("pt-BR",
    { minimumFractionDigits: casas, maximumFractionDigits: casas });
const dataBr = (s) => (s ? s.slice(8, 10) + "/" + s.slice(5, 7) + "/" + s.slice(0, 4) : "—");
const mesBr = (s) => (s ? s.slice(5, 7) + "/" + s.slice(0, 4) : "—");

/** Farol textual + ícone — nunca só cor (WCAG 1.4.1).
 *
 * `curto` é a forma para a coluna da tabela: com dezenas de linhas, alternar
 * entre "+13% vs mediana" e "2,1× a mediana" na mesma coluna atrapalha a
 * varredura visual. Na tabela a notação é sempre "×"; a frase por extenso fica
 * para o cartão e o detalhe, onde há espaço e uma comparação de cada vez.
 */
function farol(razao, curto) {
  if (razao == null) return { cls: "neutro", txt: "sem mediana", ico: "•" };
  const mult = razao.toFixed(2).replace(".", ",") + "×";
  if (razao >= 2)
    return { cls: "acima", ico: "▲",
             txt: curto ? mult : razao.toFixed(1).replace(".", ",") + "× a mediana" };
  if (razao > 1.05)
    return { cls: "atencao", ico: "▲",
             txt: curto ? mult : "+" + Math.round((razao - 1) * 100) + "% vs mediana" };
  if (razao < 0.95)
    return { cls: "ok", ico: "▼",
             txt: curto ? mult : "−" + Math.round((1 - razao) * 100) + "% vs mediana" };
  return { cls: "ok", ico: "=", txt: curto ? mult : "na mediana" };
}

function el(tag, attrs, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "cls") n.className = v;
    else if (k === "txt") n.textContent = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos) if (f != null) n.append(f);
  return n;
}

// ── lista ────────────────────────────────────────────────────────────────
// Abaixo deste número a grade de cartões é mais agradável e igualmente
// navegável; acima, "rolar e comparar à vista" para de funcionar e a tabela
// ordenável passa a valer mais que a estética.
const LIMITE_CARTOES = 12;
let ORDEM_LISTA = { col: "razao", dir: -1 };

function filtros() {
  const g = (id) => (document.getElementById(id) || {}).value || "";
  return { q: g("q").trim(), tema: g("f-tema"), cidade: g("f-cidade"), dif: g("f-dif") };
}

function comparacoesFiltradas() {
  const f = filtros();
  const norm = (s) => (s || "").toString().toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "");
  const termo = norm(f.q);
  return (INDICE.comparacoes || []).filter((c) => {
    if (termo && !norm(c.titulo + " " + (c.tema || "") + " " + c.unidade).includes(termo)) return false;
    if (f.tema && c.tema !== f.tema) return false;
    if (f.cidade && !(c.cidades || []).includes(f.cidade)) return false;
    if (f.dif === "acima" && !(c.razao > 1.05)) return false;
    if (f.dif === "muito" && !(c.razao >= 2)) return false;
    if (f.dif === "abaixo" && !(c.razao != null && c.razao <= 1.05)) return false;
    return true;
  });
}

function ordenar(comps) {
  const val = (c) => ({
    titulo: c.titulo, tema: c.tema || "", unidade: c.unidade,
    santos: c.santos.preco, mediana: c.pares.mediana,
    razao: c.razao, n: c.pares.n, data: c.santos.data || "",
  }[ORDEM_LISTA.col]);
  return comps.slice().sort((a, b) => {
    const x = val(a), y = val(b);
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === "number" ? x - y
      : String(x).localeCompare(String(y), "pt-BR")) * ORDEM_LISTA.dir;
  });
}

const COLS_LISTA = [
  ["titulo", "Item", false],
  ["tema", "Tema", false],
  ["santos", "Santos pagou", true],
  ["mediana", "Mediana dos pares", true],
  ["razao", "Diferença", true],
  ["n", "Preços/cidades", true],
  ["data", "Data", false],
];

function cartaoComparacao(c) {
  definirCasas([c.santos.preco, c.pares.mediana, c.pares.min]);
  const f = farol(c.razao);
  const cartao = el("a", { cls: "comp", href: "./precos.html?c=" + encodeURIComponent(c.slug) });
  cartao.append(el("h3", { txt: c.titulo }));
  cartao.append(el("span", { cls: "un",
    txt: (c.tema ? c.tema + " · " : "") + "preço por " + c.unidade + " · base " + c.base }));

  const precos = el("div", { cls: "precos" });
  const bSantos = el("div");
  bSantos.append(el("span", { cls: "p-lbl", txt: "Santos pagou" }));
  bSantos.append(el("span", { cls: "p-val", txt: brl(c.santos.preco) }));
  precos.append(bSantos);
  const bPares = el("div");
  bPares.append(el("span", { cls: "p-lbl", txt: "mediana dos pares" }));
  bPares.append(el("span", { cls: "p-val", txt: c.pares.mediana == null ? "—" : brl(c.pares.mediana) }));
  precos.append(bPares);
  cartao.append(precos);

  cartao.append(el("span", { cls: "farol " + f.cls }, f.ico + " " + f.txt));
  const meta = el("p", { cls: "meta" });
  meta.append(document.createTextNode(
    c.modo === "mediana"
      ? `${c.pares.n} preços em ${c.pares.n_cidades} cidades · `
      : `${c.pares.n} referência(s) pontual(is) · `));
  meta.append(el("span", { cls: "selo-conf", txt: "confiança " + (c.confianca_min || "—") }));
  cartao.append(meta);
  return cartao;
}

function tabelaComparacoes(comps) {
  const tab = el("table", { cls: "comparacoes" });
  const trh = el("tr");
  for (const [id, rot, isNum] of COLS_LISTA) {
    const th = el("th", {
      cls: isNum ? "num" : null, tabindex: "0", scope: "col",
      "aria-sort": ORDEM_LISTA.col === id
        ? (ORDEM_LISTA.dir === 1 ? "ascending" : "descending") : "none",
    }, rot);
    const acao = () => {
      if (ORDEM_LISTA.col === id) ORDEM_LISTA.dir *= -1;
      else { ORDEM_LISTA.col = id; ORDEM_LISTA.dir = id === "titulo" || id === "tema" ? 1 : -1; }
      renderLista();
    };
    th.addEventListener("click", acao);
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); acao(); }
    });
    trh.append(th);
  }
  const thead = el("thead");
  thead.append(trh);
  tab.append(thead);

  const tbody = el("tbody");
  for (const c of ordenar(comps)) {
    definirCasas([c.santos.preco, c.pares.mediana, c.pares.min]);
    const f = farol(c.razao, true);
    const tr = el("tr");

    const tdT = el("td", { cls: "tit", "data-label": "Item" });
    tdT.append(el("a", { href: "./precos.html?c=" + encodeURIComponent(c.slug), txt: c.titulo }));
    tdT.append(document.createElement("br"));
    tdT.append(el("span", { cls: "un", txt: "por " + c.unidade + " · base " + c.base }));
    tr.append(tdT);

    const tdTema = el("td", { "data-label": "Tema" });
    if (c.tema) tdTema.append(el("span", { cls: "tema", txt: c.tema }));
    tr.append(tdTema);

    tr.append(el("td", { cls: "num", "data-label": "Santos pagou", txt: brl(c.santos.preco) }));
    tr.append(el("td", { cls: "num", "data-label": "Mediana dos pares",
                         txt: c.pares.mediana == null ? "—" : brl(c.pares.mediana) }));

    const tdF = el("td", { cls: "num", "data-label": "Diferença" });
    tdF.append(el("span", { cls: "farol " + f.cls }, f.ico + " " + f.txt));
    tr.append(tdF);

    tr.append(el("td", { cls: "num", "data-label": "Preços/cidades",
                         title: `${c.pares.n} preços em ${c.pares.n_cidades} cidades`,
                         txt: `${c.pares.n}/${c.pares.n_cidades}` }));
    tr.append(el("td", { "data-label": "Data", txt: dataBr(c.santos.data) }));
    tbody.append(tr);
  }
  tab.append(tbody);
  return tab;
}

function renderLista() {
  const alvo = document.getElementById("lista");
  alvo.textContent = "";
  const todas = INDICE.comparacoes || [];
  if (!todas.length) {
    alvo.append(el("p", { cls: "vazio", txt: "Nenhuma comparação publicada ainda." }));
    return;
  }
  const comps = comparacoesFiltradas();
  const cont = document.getElementById("contagem");
  cont.textContent = comps.length === todas.length
    ? `${todas.length} comparações`
    : `${comps.length} de ${todas.length} comparações`;

  if (!comps.length) {
    alvo.append(el("p", { cls: "vazio",
      txt: "Nenhuma comparação atende a esses filtros." }));
    return;
  }
  // No mobile a tabela já vira linhas empilhadas pelo CSS (data-label), então
  // não há checagem de viewport aqui — que só criaria bug no redimensionamento.
  if (todas.length <= LIMITE_CARTOES) {
    const grade = el("div", { cls: "lista" });
    for (const c of ordenar(comps)) grade.append(cartaoComparacao(c));
    alvo.append(grade);
  } else {
    const wrap = el("div", { cls: "tabela-wrap" });
    wrap.append(tabelaComparacoes(comps));
    alvo.append(wrap);
  }
}

function montarConsulta() {
  const barra = document.getElementById("consulta");
  const todas = INDICE.comparacoes || [];
  // com 1 ou 2 comparações a barra de filtros é ruído — só aparece quando serve
  if (todas.length < 4) return;
  barra.hidden = false;

  const selTema = document.getElementById("f-tema");
  for (const t of INDICE.temas || []) selTema.append(el("option", { value: t, txt: t }));
  const selCidade = document.getElementById("f-cidade");
  for (const c of [...new Set(todas.flatMap((x) => x.cidades || []))].sort())
    selCidade.append(el("option", { value: c, txt: c }));

  const p = Comum.lerParams();
  for (const [id, chave] of [["q", "q"], ["f-tema", "tema"],
                             ["f-cidade", "cidade"], ["f-dif", "dif"]]) {
    const v = p.get(chave);
    if (v) document.getElementById(id).value = v;
  }

  let t;
  const aplicar = () => {
    const f = filtros();
    Comum.gravarParams({ q: f.q, tema: f.tema, cidade: f.cidade, dif: f.dif });
    renderLista();
  };
  document.getElementById("q").addEventListener("input", () => {
    clearTimeout(t); t = setTimeout(aplicar, 200);
  });
  for (const id of ["f-tema", "f-cidade", "f-dif"])
    document.getElementById(id).addEventListener("change", aplicar);
}

// ── detalhe ──────────────────────────────────────────────────────────────
function linhasTabela() {
  const obs = (DETALHE.observacoes || []).slice();
  const dir = ORDEM.dir;
  obs.sort((a, b) => {
    const x = a[ORDEM.col], y = b[ORDEM.col];
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === "number" ? x - y : String(x).localeCompare(String(y), "pt-BR")) * dir;
  });
  return obs;
}

const COLUNAS = [
  ["cidade", "Cidade", false],
  ["descricao", "Descrição no edital", false],
  ["quantidade", "Qtd.", true],
  ["unidade_original", "Un.", false],
  ["preco", "Preço unitário", true],
  ["preco_corrigido", "Corrigido", true],
  ["data", "Data", false],
  ["fornecedor", "Fornecedor", false],
  ["confianca", "Confiança", false],
];

function renderTabela(caixa) {
  caixa.textContent = "";
  const tab = el("table");
  const thead = el("thead");
  const trh = el("tr");
  for (const [id, rot, isNum] of COLUNAS) {
    const th = el("th", {
      cls: isNum ? "num" : null, tabindex: "0", scope: "col",
      "aria-sort": ORDEM.col === id ? (ORDEM.dir === 1 ? "ascending" : "descending") : "none",
    }, rot);
    const ordenar = () => {
      if (ORDEM.col === id) ORDEM.dir *= -1; else { ORDEM.col = id; ORDEM.dir = 1; }
      renderTabela(caixa);
    };
    th.addEventListener("click", ordenar);
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ordenar(); }
    });
    trh.append(th);
  }
  thead.append(trh);
  tab.append(thead);

  const tbody = el("tbody");
  const s = DETALHE.santos;
  const trs = el("tr", { cls: "santos" });
  const celulasSantos = [
    ["Santos", false], [s.descricao, false], [num(s.quantidade), true],
    [s.unidade_original, false], [brl(s.preco), true],
    [s.preco_corrigido == null ? "—" : brl(s.preco_corrigido), true],
    [dataBr(s.data), false], [s.fornecedor || "—", false], ["âncora", false],
  ];
  celulasSantos.forEach((c, i) => trs.append(
    el("td", { cls: c[1] ? "num" : (i === 1 ? "desc" : null),
               "data-label": COLUNAS[i][1], title: i === 1 ? c[0] : null, txt: c[0] })));
  tbody.append(trs);

  for (const o of linhasTabela()) {
    const tr = el("tr");
    const celulas = [
      [o.cidade, false], [o.descricao, false], [num(o.quantidade), true],
      [o.unidade_original + (o.fator !== 1 ? ` (×${o.fator})` : ""), false],
      [brl(o.preco), true],
      [o.preco_corrigido == null ? "—" : brl(o.preco_corrigido), true],
      [dataBr(o.data), false], [o.fornecedor || "—", false], [o.confianca, false],
    ];
    celulas.forEach((c, i) => {
      const td = el("td", { cls: c[1] ? "num" : (i === 1 ? "desc" : null),
                            "data-label": COLUNAS[i][1] });
      if (i === 1) {
        td.append(el("a", { href: o.url, target: "_blank", rel: "noopener",
                            title: c[0], txt: c[0] }));
      } else td.textContent = c[0];
      tr.append(td);
    });
    tbody.append(tr);
  }
  tab.append(tbody);
  caixa.append(tab);
}

function renderGrafico(canvas) {
  const obs = DETALHE.observacoes || [];
  Chart.getChart(canvas)?.destroy();
  const pontos = obs.filter((o) => o.data).map((o) => ({ x: o.data, y: o.preco, o }));
  const s = DETALHE.santos;
  const dados = {
    datasets: [
      {
        label: "Cidades-par", data: pontos, backgroundColor: GOLD,
        pointRadius: 6, pointHoverRadius: 8, showLine: false,
      },
      {
        label: "Santos",
        data: s.data ? [{ x: s.data, y: s.preco }] : [],
        backgroundColor: VERMELHO, pointStyle: "rectRot",
        pointRadius: 10, pointHoverRadius: 12, showLine: false,
      },
    ],
  };
  const mediana = DETALHE.pares?.mediana;
  new Chart(canvas, {
    type: "scatter",
    data: dados,
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { type: "category",
             labels: [...new Set([...pontos.map((p) => p.x), s.data].filter(Boolean))].sort(),
             // na escala category o callback recebe o ÍNDICE, não o rótulo —
             // getLabelForValue é o único jeito de chegar na data
             ticks: { callback(v) { return mesBr(this.getLabelForValue(v)); } } },
        y: { beginAtZero: true,
             ticks: { callback: (v) => "R$ " + Number(v).toLocaleString("pt-BR") } },
      },
      plugins: {
        legend: { labels: { usePointStyle: true } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const o = ctx.raw.o;
              return o ? `${o.cidade}: ${brl(o.preco)} (${dataBr(o.data)})`
                       : `Santos: ${brl(ctx.raw.y)}`;
            },
          },
        },
        annotation: undefined,
      },
    },
    plugins: mediana ? [{
      id: "linhaMediana",
      afterDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        const y = scales.y.getPixelForValue(mediana);
        ctx.save();
        ctx.setLineDash([6, 5]);
        ctx.strokeStyle = VERDE;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(chartArea.left, y);
        ctx.lineTo(chartArea.right, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = VERDE;
        ctx.font = "600 11px Manrope, sans-serif";
        ctx.fillText("mediana dos pares " + brl(mediana), chartArea.left + 6, y - 6);
        ctx.restore();
      },
    }] : [],
  });

  Comum.chartAcessivel(
    canvas,
    `Dispersão do preço unitário por ${DETALHE.unidade}: Santos e as cidades-par, por data do resultado.`,
    ["Cidade", "Data", "Preço unitário"],
    [[ "Santos", dataBr(s.data), brl(s.preco) ]].concat(
      obs.map((o) => [o.cidade, dataBr(o.data), brl(o.preco)])));
}

function renderDetalhe() {
  const alvo = document.getElementById("visao-detalhe");
  alvo.textContent = "";
  const d = DETALHE;
  definirCasas([d.santos.preco, d.pares.mediana, d.pares.min,
                ...(d.observacoes || []).map((o) => o.preco)]);
  const f = farol(d.razao);

  alvo.append(el("a", { cls: "voltar", href: "./precos.html" }, "← todas as comparações"));

  const cab = el("div", { cls: "painel" });
  cab.style.marginTop = "14px";
  cab.append(el("h2", { txt: d.titulo }));
  cab.append(el("span", { cls: "un", txt: "preço por " + d.unidade + " · base " + d.base }));

  const precos = el("div", { cls: "precos" });
  const b1 = el("div");
  b1.append(el("span", { cls: "p-lbl", txt: "Santos pagou" }));
  b1.append(el("span", { cls: "p-val", txt: brl(d.santos.preco) }));
  precos.append(b1);
  const b2 = el("div");
  b2.append(el("span", { cls: "p-lbl", txt: "mediana dos pares" }));
  b2.append(el("span", { cls: "p-val", txt: d.pares.mediana == null ? "—" : brl(d.pares.mediana) }));
  precos.append(b2);
  const b3 = el("div");
  b3.append(el("span", { cls: "p-lbl", txt: "faixa observada" }));
  b3.append(el("span", { cls: "p-val", txt: d.pares.n ? brl(d.pares.min) + " – " + brl(d.pares.max) : "—" }));
  precos.append(b3);
  cab.append(precos);
  cab.append(el("span", { cls: "farol " + f.cls }, f.ico + " " + f.txt));

  const meta = el("p", { cls: "meta" });
  meta.textContent = d.modo === "mediana"
    ? `${d.pares.n} preços em ${d.pares.n_cidades} cidades, entre ${dataBr(d.pares.data_min)} e ${dataBr(d.pares.data_max)}. `
      + `Avaliados ${d.avaliados} itens · ${d.pares.n} comparáveis · ${d.descartados} descartados.`
    : `Apenas ${d.pares.n} referência(s) pontual(is): insuficiente para uma mediana. `
      + `Avaliados ${d.avaliados} itens · ${d.descartados} descartados.`;
  cab.append(meta);

  if (d.economia_se_mediana) {
    const e = el("p", { cls: "meta" });
    e.textContent = `Se tivesse pago a mediana dos pares, a diferença sobre a quantidade `
      + `contratada seria de ${brl(d.economia_se_mediana)} — projeção aritmética, não economia realizável.`;
    cab.append(e);
  }
  alvo.append(cab);

  // ficha do item de Santos
  const ficha = el("div", { cls: "painel" });
  ficha.append(el("p", { cls: "section-tag", txt: "O item de Santos" }));
  ficha.querySelector(".section-tag").style.margin = "0 0 10px";
  ficha.append(el("p", { txt: d.santos.descricao, style: "font-size:14px;line-height:1.6;margin:0" }));
  const g = el("div", { cls: "ficha" });
  const campos = [
    ["Objeto da contratação", d.santos.objeto],
    ["Modalidade", d.santos.modalidade],
    ["Processo", d.santos.processo],
    ["Quantidade", num(d.santos.quantidade) + " " + d.santos.unidade_original],
    ["Fornecedor", d.santos.fornecedor || "—"],
    ["Data do resultado", dataBr(d.santos.data)],
  ];
  for (const [rot, val] of campos) {
    const c = el("div");
    c.append(el("span", { cls: "f-lbl", txt: rot }));
    c.append(document.createTextNode(val || "—"));
    g.append(c);
  }
  ficha.append(g);
  if (d.santos.url) {
    const p = el("p", { cls: "meta" });
    p.append(el("a", { href: d.santos.url, target: "_blank", rel: "noopener",
                       txt: "ver a contratação de Santos no PNCP ↗" }));
    ficha.append(p);
  }
  alvo.append(ficha);

  // gráfico
  const gr = el("div", { cls: "painel" });
  gr.append(el("p", { cls: "section-tag", txt: "Dispersão dos preços" }));
  gr.querySelector(".section-tag").style.margin = "0 0 6px";
  const caixaG = el("div", { cls: "grafico-caixa" });
  const cv = el("canvas", { id: "g-precos" });
  caixaG.append(cv);
  gr.append(caixaG);
  alvo.append(gr);

  // tabela
  const tb = el("div", { cls: "painel" });
  tb.append(el("p", { cls: "section-tag", txt: "Todas as observações" }));
  tb.querySelector(".section-tag").style.margin = "0 0 6px";
  const wrap = el("div", { cls: "tabela-wrap" });
  tb.append(wrap);
  const acoes = el("div", { cls: "barra-acoes" });
  const btn = el("button", { cls: "acao", type: "button", txt: "Baixar CSV" });
  btn.addEventListener("click", () => {
    const linhas = (DETALHE.observacoes || []).map((o) => [
      o.cidade, o.orgao, o.descricao, o.quantidade, o.unidade_original, o.fator,
      o.preco, o.preco_corrigido, o.data, o.fornecedor, o.srp ? "sim" : "não",
      o.confianca, o.url]);
    linhas.unshift([
      "Santos", DETALHE.santos.orgao, DETALHE.santos.descricao, DETALHE.santos.quantidade,
      DETALHE.santos.unidade_original, 1, DETALHE.santos.preco,
      DETALHE.santos.preco_corrigido, DETALHE.santos.data, DETALHE.santos.fornecedor,
      "", "âncora", DETALHE.santos.url]);
    Comum.exportarCsv("preco-" + DETALHE.slug + ".csv",
      ["Cidade", "Órgão", "Descrição", "Quantidade", "Unidade", "Fator",
       "Preço unitário", "Preço corrigido", "Data", "Fornecedor", "SRP",
       "Confiança", "Fonte PNCP"], linhas);
  });
  acoes.append(btn);
  tb.append(acoes);
  alvo.append(tb);

  // descartes
  const des = el("div", { cls: "painel" });
  const det = el("details");
  det.style.borderTop = "0";
  det.style.paddingTop = "0";
  det.append(el("summary", { txt: `Candidatos não usados (${d.descartados}) e por quê` }));
  const ul = el("ul");
  for (const [motivo, n] of Object.entries(d.motivos_descarte || {})) {
    ul.append(el("li", { txt: `${n} — ${motivo.replace(/_/g, " ")}` }));
  }
  det.append(ul);
  det.append(el("p", { cls: "meta", txt:
    "Cada motivo é um gate objetivo aplicado antes de qualquer comparação. "
    + "Um item só entra na mediana se passar por todos." }));
  des.append(det);
  alvo.append(des);

  // metodologia
  const av = el("div", { cls: "aviso" });
  av.append(el("strong", { txt: "O que estes números não provam" }));
  av.append(document.createTextNode(
    "O preço unitário não é ajustado por especificação técnica exata, prazo de entrega, "
    + "garantia, local de entrega, condição de pagamento nem tamanho do lote. Diferença de "
    + "preço não é, por si, indício de irregularidade — é ponto de partida para perguntar. "
    + "Todas as observações vêm da mesma base ("
    + d.base + "); estimado e homologado nunca são misturados."));
  if (d.nota_metodologica) {
    av.append(el("p", { cls: "meta", txt: d.nota_metodologica }));
  }
  alvo.append(av);

  renderTabela(wrap);
  renderGrafico(cv);
}

// ── aba "O que Santos comprou" ───────────────────────────────────────────
// Reuso do Detalhamento de Despesas: array completo em memória, só a fatia da
// página no DOM, haystack normalizado pré-computado uma vez na carga.
const CAT_PAGINA = 100;
let CAT = null;          // {campos, orgaos, modalidades, linhas}
let CAT_NORM = null;     // haystack por linha, calculado 1× (busca a cada tecla)
let catFiltradas = [];
let catPagina = 1;
let catOrdem = { col: 4, dir: -1 };   // data desc

const CAT_COLS = [
  [0, "Item", false], [8, "Órgão", false], [2, "Qtd.", true], [1, "Un.", false],
  [3, "Preço unitário", true], [4, "Data", false], [5, "Fornecedor", false],
];

/** ncp → URL pública do PNCP. Espelha `fontes.parse_ncp`; a duplicação é
 *  deliberada e barata — carregar a URL pronta no shard custaria ~300 KB. */
function urlDoNcp(ncp) {
  const m = /^(\d{14})-\d+-(\d+)\/(\d{4})$/.exec(ncp || "");
  return m ? `https://pncp.gov.br/app/editais/${m[1]}/${m[3]}/${Number(m[2])}` : null;
}

const normCat = (s) => (s || "").toString().toLowerCase()
  .normalize("NFD").replace(/[̀-ͯ]/g, "");

async function carregarCatalogo() {
  if (CAT) return CAT;
  const ponteiro = (INDICE || {}).catalogo;
  if (!ponteiro || !ponteiro.arquivo) throw new Error("catálogo ausente do índice");
  // cache-buster estável (nunca Date.now(), que derrota o cache do navegador)
  const r = await fetch(ponteiro.arquivo + "?v=" + (INDICE.atualizado_em || ""));
  if (!r.ok) throw new Error(r.status);
  CAT = await r.json();
  CAT_NORM = CAT.linhas.map((l) =>
    normCat(l[0] + " " + l[1] + " " + l[5] + " " + CAT.orgaos[l[8]]));
  return CAT;
}

function catFiltrar() {
  const termos = normCat(document.getElementById("iq").value).split(/\s+/).filter(Boolean);
  const ano = document.getElementById("i-ano").value;
  const orgao = document.getElementById("i-orgao").value;
  catFiltradas = CAT.linhas.filter((l, i) => {
    if (ano && (l[4] || "").slice(0, 4) !== ano) return false;
    if (orgao && CAT.orgaos[l[8]] !== orgao) return false;
    return !termos.length || termos.every((t) => CAT_NORM[i].includes(t));
  });
  const c = catOrdem.col;
  catFiltradas.sort((a, b) => {
    let x = a[c], y = b[c];
    if (c === 8) { x = CAT.orgaos[x]; y = CAT.orgaos[y]; }
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === "number" ? x - y
      : String(x).localeCompare(String(y), "pt-BR")) * catOrdem.dir;
  });
  catRender();
  Comum.gravarParams(Object.assign(estadoLista(), {
    aba: "itens",
    iq: document.getElementById("iq").value.trim(),
    iano: ano, iorg: orgao,
    ipg: catPagina > 1 ? String(catPagina) : "",
    iord: `${catOrdem.col}:${catOrdem.dir}`,
  }));
}

function catRender() {
  const totalPag = Math.max(1, Math.ceil(catFiltradas.length / CAT_PAGINA));
  catPagina = Math.min(Math.max(1, catPagina), totalPag);
  const ini = (catPagina - 1) * CAT_PAGINA;
  const pagina = catFiltradas.slice(ini, ini + CAT_PAGINA);

  const wrap = document.getElementById("i-tabela");
  wrap.textContent = "";
  const tab = el("table", { cls: "comparacoes" });
  const trh = el("tr");
  for (const [col, rot, isNum] of CAT_COLS) {
    const th = el("th", {
      cls: isNum ? "num" : null, tabindex: "0", scope: "col",
      "aria-sort": catOrdem.col === col
        ? (catOrdem.dir === 1 ? "ascending" : "descending") : "none",
    }, rot);
    const acao = () => {
      if (catOrdem.col === col) catOrdem.dir *= -1;
      else { catOrdem.col = col; catOrdem.dir = col === 0 || col === 8 ? 1 : -1; }
      catFiltrar();
    };
    th.addEventListener("click", acao);
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); acao(); }
    });
    trh.append(th);
  }
  const thead = el("thead");
  thead.append(trh);
  tab.append(thead);

  const tbody = el("tbody");
  for (const l of pagina) {
    const tr = el("tr");
    const tdItem = el("td", { cls: "desc", "data-label": "Item" });
    const url = urlDoNcp(l[6]);
    tdItem.append(url
      ? el("a", { href: url, target: "_blank", rel: "noopener", title: l[0], txt: l[0] })
      : document.createTextNode(l[0]));
    tr.append(tdItem);
    tr.append(el("td", { "data-label": "Órgão", txt: CAT.orgaos[l[8]] }));
    tr.append(el("td", { cls: "num", "data-label": "Qtd.", txt: num(l[2]) }));
    tr.append(el("td", { "data-label": "Un.", txt: l[1] }));
    tr.append(el("td", { cls: "num", "data-label": "Preço unitário", txt: brlAuto(l[3]) }));
    tr.append(el("td", { "data-label": "Data", txt: dataBr(l[4]) }));
    tr.append(el("td", { "data-label": "Fornecedor", txt: l[5] || "—" }));
    tbody.append(tr);
  }
  tab.append(tbody);
  wrap.append(tab);

  const n = catFiltradas.length.toLocaleString("pt-BR");
  document.getElementById("i-contagem").textContent =
    `${n} ${catFiltradas.length === 1 ? "item" : "itens"}`;
  document.getElementById("i-pagina").textContent = `Página ${catPagina} de ${totalPag}`;
  document.getElementById("i-anterior").disabled = catPagina <= 1;
  document.getElementById("i-proxima").disabled = catPagina >= totalPag;
  document.getElementById("i-sr").textContent =
    `${n} itens, página ${catPagina} de ${totalPag}.`;
}

async function abrirCatalogo() {
  const carregando = document.getElementById("i-carregando");
  const res = document.getElementById("i-resultado");
  if (CAT) { catFiltrar(); return; }
  carregando.hidden = false;
  res.hidden = true;
  carregando.textContent = "Carregando o catálogo…";
  try {
    await carregarCatalogo();
  } catch (e) {
    Comum.estadoErro(carregando, "Não foi possível carregar o catálogo de itens.",
                     abrirCatalogo);
    return;
  }
  const p = PARAMS_INICIAIS;
  const selAno = document.getElementById("i-ano");
  for (const a of [...new Set(CAT.linhas.map((l) => (l[4] || "").slice(0, 4)))]
       .filter(Boolean).sort().reverse())
    selAno.append(el("option", { value: a, txt: a }));
  const selOrg = document.getElementById("i-orgao");
  for (const o of [...CAT.orgaos].sort())
    selOrg.append(el("option", { value: o, txt: o }));

  document.getElementById("iq").value = p.get("iq") || "";
  selAno.value = p.get("iano") || "";
  selOrg.value = p.get("iorg") || "";
  catPagina = parseInt(p.get("ipg") || "1", 10) || 1;
  const ord = (p.get("iord") || "").split(":");
  if (ord.length === 2) catOrdem = { col: +ord[0], dir: +ord[1] };

  let t;
  document.getElementById("iq").addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => { catPagina = 1; catFiltrar(); }, 150);
  });
  for (const id of ["i-ano", "i-orgao"])
    document.getElementById(id).addEventListener("change", () => {
      catPagina = 1; catFiltrar();
    });
  document.getElementById("i-anterior").addEventListener("click", () => {
    catPagina -= 1; catFiltrar();
  });
  document.getElementById("i-proxima").addEventListener("click", () => {
    catPagina += 1; catFiltrar();
  });
  document.getElementById("i-csv").addEventListener("click", () => {
    Comum.exportarCsv("itens-santos.csv",
      ["Item", "Órgão", "Quantidade", "Unidade", "Preço unitário", "Data",
       "Fornecedor", "Modalidade", "Contratação (PNCP)"],
      catFiltradas.map((l) => [l[0], CAT.orgaos[l[8]], l[2], l[1], l[3], l[4],
                               l[5], CAT.modalidades[l[9]], urlDoNcp(l[6]) || l[6]]));
  });

  carregando.hidden = true;
  res.hidden = false;
  catFiltrar();
}

// ── abas (APG) ───────────────────────────────────────────────────────────
function selecionarAba(nome, comFoco) {
  for (const t of document.querySelectorAll(".tab")) {
    const ativa = t.dataset.aba === nome;
    t.setAttribute("aria-selected", ativa);
    t.tabIndex = ativa ? 0 : -1;
  }
  for (const p of document.querySelectorAll(".aba")) p.classList.remove("ativo");
  const painel = document.getElementById("aba-" + nome);
  painel.classList.add("ativo");
  if (comFoco) painel.focus();
  Comum.gravarParams(Object.assign(estadoLista(), { aba: nome }));
  if (nome === "itens") abrirCatalogo();
}

function ligarAbas() {
  const abas = [...document.querySelectorAll(".tab")];
  abas.forEach((t, i) => {
    t.id = "tab-" + t.dataset.aba;
    t.setAttribute("aria-controls", "aba-" + t.dataset.aba);
    t.tabIndex = t.getAttribute("aria-selected") === "true" ? 0 : -1;
    t.addEventListener("click", () => selecionarAba(t.dataset.aba));
    t.addEventListener("keydown", (e) => {
      const teclas = { ArrowRight: 1, ArrowLeft: -1, Home: "inicio", End: "fim" };
      if (!(e.key in teclas)) return;
      e.preventDefault();
      const alvo = teclas[e.key] === "inicio" ? abas[0]
        : teclas[e.key] === "fim" ? abas[abas.length - 1]
        : abas[(i + teclas[e.key] + abas.length) % abas.length];
      alvo.focus();
      selecionarAba(alvo.dataset.aba);
    });
  });
  for (const p of document.querySelectorAll(".aba")) {
    p.setAttribute("role", "tabpanel");
    p.setAttribute("aria-labelledby", "tab-" + p.id.replace("aba-", ""));
    p.tabIndex = -1;
  }
}

/** Estado dos filtros da lista de comparações, para não perdê-lo ao trocar de aba. */
function estadoLista() {
  const f = filtros();
  return { q: f.q, tema: f.tema, cidade: f.cidade, dif: f.dif };
}

// ── carga ────────────────────────────────────────────────────────────────
function renderHero() {
  const n = document.getElementById("hero-num");
  const ctx = document.getElementById("hero-ctx");
  const comps = (INDICE.comparacoes || []).filter((c) => c.modo === "mediana" && c.razao);
  if (!comps.length) {
    n.textContent = String((INDICE.comparacoes || []).length);
    ctx.textContent = "comparações publicadas. " + (INDICE.resumo || "");
    return;
  }
  // o máximo, não o primeiro do array: depender da ordem do export tornaria o
  // número-âncora refém de uma decisão de ordenação lá do outro lado
  const pior = comps.reduce((a, b) => (b.razao > a.razao ? b : a));
  n.textContent = pior.razao.toFixed(1).replace(".", ",") + "×";
  ctx.textContent = `a mediana das cidades-par no caso mais extremo (${pior.titulo}). `
    + (INDICE.resumo || "");
}

function renderRodape() {
  const c = INDICE.cobertura || {};
  const p = document.getElementById("rodape");
  // cidades COM dado espelhado — não o tamanho da lista de alvos
  const nCidades = Object.keys(c.por_cidade || {}).length;
  p.textContent =
    `Fonte: ${INDICE.fonte}. Espelho local de ${num(c.contratacoes)} contratações e `
    + `${num(c.itens)} itens de ${nCidades} cidades-par `
    + `(${Object.values(c.por_cidade || {}).map((x) => x.nome).join(", ")}), `
    + `modalidades ${(c.modalidades_nome || []).join(" e ")}, de ${mesBr(c.de + "-01")} `
    + `a ${mesBr(c.ate + "-01")}. Correção monetária pelo IPCA `
    + `(${(INDICE.ipca || {}).fonte || "—"}), base ${mesBr((INDICE.ipca || {}).base + "-01")}. `
    + `Índice gerado em ${dataBr((INDICE.atualizado_em || "").slice(0, 10))}.`;
}

async function iniciar() {
  const alvo = document.getElementById("conteudo");
  try {
    const r = await fetch("./precos-index.json", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    INDICE = await r.json();
  } catch (e) {
    Comum.estadoErro(alvo, "Não foi possível carregar o índice de preços.", iniciar);
    return;
  }
  renderHero();
  renderRodape();

  // lerParams devolve URLSearchParams — acessar como propriedade daria undefined
  const slug = Comum.lerParams().get("c");
  const comp = (INDICE.comparacoes || []).find((c) => c.slug === slug);
  if (!comp) {
    document.getElementById("visao-lista").hidden = false;
    document.getElementById("visao-detalhe").hidden = true;
    montarConsulta();
    renderLista();
    ligarAbas();
    // `?c=` vence as abas (abre o detalhe); sem ele, `?aba=` decide
    const aba = Comum.lerParams().get("aba");
    if (aba === "itens") selecionarAba("itens");
    return;
  }
  document.getElementById("visao-lista").hidden = true;
  document.getElementById("visao-detalhe").hidden = false;
  try {
    const r = await fetch(comp.arquivo, { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    DETALHE = await r.json();
  } catch (e) {
    Comum.estadoErro(document.getElementById("visao-detalhe"),
      "Não foi possível carregar esta comparação.", iniciar);
    return;
  }
  document.title = DETALHE.titulo + " — Preço comparado";
  renderDetalhe();
}

window.addEventListener("temamudou", () => {
  definirCores();
  if (DETALHE && !document.getElementById("visao-detalhe").hidden) {
    renderGrafico(document.getElementById("g-precos"));
  }
});

iniciar();
