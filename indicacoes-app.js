// Painel de Indicações & Respostas — lê indicacoes-index.json (export de
// respostas-executivo/export.py --indicacoes) e os limites dos bairros
// (geo/santos-bairros.geojson) e filtra no cliente. O mapa é desenhado pela camada
// comum de gráficos (Comum.grafico, ECharts 6, série "map").
// Indicação não tem prazo legal de resposta: nada de "fora do prazo" aqui.
"use strict";

// Graus de longitude encolhem com a latitude: cos(23,95°) ≈ 0,914.
const ASPECTO = 0.914;
// Canto sudoeste do quadro da ilha: ali é São Vicente (fora do mapa) e cabe o recorte continental.
const LAT_CORTE = -23.9615;

// Lugares que não são um bairro (campo `regiao` do índice: rótulos de
// respostas-executivo/bairros.py, REGIOES) + o que ficou sem bairro reconhecível.
const REGIOES = [
  ["Orla", "orla", "Indicações que citam a orla, sem um bairro só"],
  ["Zona Noroeste", "zona-noroeste", "Indicações que citam a Zona Noroeste, sem um bairro só"],
  ["Morros", "morros", "Indicações que citam os morros, sem um bairro só"],
  ["Área Continental", "area-continental", "Indicações que citam a área continental, sem um bairro só"],
  ["Centro Histórico", "centro-historico", "Indicações que citam o Centro Histórico, sem um bairro só"],
  ["Cidade toda", "cidade-toda", "Indicações para a cidade toda (“Geral” na planilha)"],
];
const SOBRAS = [
  ["Sem bairro reconhecível", "sem-bairro",
    "Indicações sem bairro na planilha do gabinete, ou com um texto que não é bairro de Santos"],
];
const LUGARES = new Map([...REGIOES, ...SOBRAS].map(([nome, slug, desc]) => [slug, { nome, slug, desc }]));
const SLUG_DA_REGIAO = new Map(REGIOES.map(([nome, slug]) => [nome, slug]));

// Situação do export → [chave do painel, rótulo, classe]. "Pedido de prorrogação" e não
// "prazo prorrogado": indicação não tem prazo legal (o ofício só pede mais tempo).
const SITUACOES = {
  respondido: ["respondida", "Respondida", "ok"],
  so_encaminhamento: ["encaminhamento", "Só encaminhamento", "tramite"],
  so_prorrogacao: ["prorrogacao", "Pedido de prorrogação", "tramite"],
  a_classificar: ["classificar", "Resposta a classificar", "classificar"],
  pendente: ["sem", "Sem resposta", "sem"],
};

const el = (id) => document.getElementById(id);
const norm = Comum.norm;
const esc = Comum.escapar;
const fmt = (n) => n.toLocaleString("pt-BR");
const plural = (n, um, varios) => `${fmt(n)} ${n === 1 ? um : varios}`;
const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
  "setembro", "outubro", "novembro", "dezembro"];
const TOQUE = matchMedia("(pointer: coarse)").matches;

let ITENS = [], BASE = [], FILTRADAS = [], STATS = new Map(), CLASSES = [];
let pag = null;
let LUGAR = null;            // {tipo:"bairro", nome} | {tipo:"lugar", slug}
let FOCO = "";               // ?n= — uma indicação só
let ZOOM = 1, CENTRO = null; // centro (lon, lat) do mapa aproximado; arrastar atualiza
let ORDEM_TAB = { col: "n", dir: "desc" };
let ACESSIVEL = null;        // descrição + tabela oculta do mapa (Comum.chartAcessivel)
const GEO = { ilha: [], cont: [], bbox: new Map(), feicao: new Map(), caixa: {}, lonCorte: null };

function dataBR(s) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s || "");
  return m ? new Date(+m[3], +m[2] - 1, +m[1]) : null;
}
const diasEntre = (a, b) => Math.round((b - a) / 864e5);
const chaveNumero = (n) => {
  const m = /^(\d+)\/(\d{4})$/.exec(n || "");
  return m ? +m[2] * 1e5 + +m[1] : 0;
};
function mediana(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
}

function derivar(i) {
  i._ini = dataBR(i.data_sessao);
  i._resp = dataBR(i.data_resposta_merito) || dataBR(i.data_resposta);
  [i._sit, i._sitRotulo, i._sitClasse] = SITUACOES[i.situacao] || SITUACOES.pendente;
  i._dias = i._sit === "respondida" && i._ini && i._resp && i._resp >= i._ini ? diasEntre(i._ini, i._resp) : null;
  if (i.bairro && GEO.feicao.has(i.bairro)) i._lugar = { tipo: "bairro", nome: i.bairro };
  else if (i.regiao && SLUG_DA_REGIAO.has(i.regiao)) i._lugar = { tipo: "lugar", slug: SLUG_DA_REGIAO.get(i.regiao) };
  else i._lugar = { tipo: "lugar", slug: "sem-bairro" };
  i._chave = i._lugar.tipo === "bairro" ? i._lugar.nome : "#" + i._lugar.slug;
  i._busca = norm([i.numero, i.assunto, i.bairro, i.regiao].join(" "));
}

// ── Geometria ────────────────────────────────────────────────────────────────
function caixaDe(coords, bb) {
  for (const poli of coords) for (const [x, y] of poli[0]) {
    if (x < bb[0]) bb[0] = x; if (y < bb[1]) bb[1] = y;
    if (x > bb[2]) bb[2] = x; if (y > bb[3]) bb[3] = y;
  }
  return bb;
}
function dentroAnel(x, y, anel) {
  let d = false;
  for (let i = 0, j = anel.length - 1; i < anel.length; j = i++) {
    const [xi, yi] = anel[i], [xj, yj] = anel[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) d = !d;
  }
  return d;
}
const dentroPoli = (x, y, poli) => dentroAnel(x, y, poli[0]) && !poli.slice(1).some((h) => dentroAnel(x, y, h));
const dentroFeicao = (x, y, f) => f.geometry.coordinates.some((poli) => dentroPoli(x, y, poli));
function distSeg(px, py, [ax, ay], [bx, by]) {
  const dx = bx - ax, dy = by - ay, l = dx * dx + dy * dy;
  const t = l ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l)) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}
// Ponto para o rótulo: o "polo de inacessibilidade" do maior polígono (o ponto interno
// mais longe das bordas), por grade + refino. O centro que o ECharts usa por padrão cai
// perto da borda em formas de trapézio (Boqueirão, Ponta da Praia) e o nome vazava.
function polo(f) {
  const polis = f.geometry.coordinates.map((poli) => poli.map((anel) => anel.map(([x, y]) => [x * ASPECTO, y])));
  const area = (anel) => Math.abs(anel.reduce((s, [x, y], i) => { const [u, v] = anel[(i + 1) % anel.length]; return s + x * v - u * y; }, 0)) / 2;
  const P = polis.reduce((a, b) => (area(b[0]) > area(a[0]) ? b : a));
  const xs = P[0].map((p) => p[0]), ys = P[0].map((p) => p[1]);
  let x0 = Math.min(...xs), y0 = Math.min(...ys), lx = Math.max(...xs) - x0, ly = Math.max(...ys) - y0;
  let passo = Math.max(lx, ly) / 24, melhor = null, dMelhor = -1;
  for (let rodada = 0; rodada < 3; rodada++) {
    for (let x = x0; x <= x0 + lx + 1e-12; x += passo) {
      for (let y = y0; y <= y0 + ly + 1e-12; y += passo) {
        if (!dentroPoli(x, y, P)) continue;
        let d = Infinity;
        for (const anel of P) for (let i = 0; i < anel.length - 1; i++) d = Math.min(d, distSeg(x, y, anel[i], anel[i + 1]));
        if (d > dMelhor) { dMelhor = d; melhor = [x, y]; }
      }
    }
    if (!melhor) break;
    x0 = melhor[0] - passo; y0 = melhor[1] - passo; lx = ly = 2 * passo; passo /= 6;
  }
  if (!melhor) { const bb = GEO.bbox.get(f.properties.nome); return [(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2]; }
  return [melhor[0] / ASPECTO, melhor[1]];
}

// Ilha × área continental vêm da propriedade `area_continental` do GeoJSON
// (geo/preparar_bairros.py, pela camada de Prefeituras Regionais).
function prepararGeo(geo) {
  for (const f of geo.features) {
    const nome = f.properties.nome;
    GEO.bbox.set(nome, caixaDe(f.geometry.coordinates, [Infinity, Infinity, -Infinity, -Infinity]));
    f.properties.cp = polo(f);  // o ECharts ancora o rótulo da região em properties.cp
    GEO.feicao.set(nome, f);
    (f.properties.area_continental ? GEO.cont : GEO.ilha).push(f);
  }
  for (const parte of ["ilha", "cont"]) {
    const bb = [Infinity, Infinity, -Infinity, -Infinity];
    for (const f of GEO[parte]) caixaDe(f.geometry.coordinates, bb);
    GEO.caixa[parte] = { bb, ar: ((bb[2] - bb[0]) / (bb[3] - bb[1])) * ASPECTO };
  }
  // largura livre do canto sudoeste: o vértice mais a oeste abaixo do corte de latitude
  let lon = Infinity;
  for (const f of GEO.ilha) for (const poli of f.geometry.coordinates) for (const [x, y] of poli[0]) {
    if (y < LAT_CORTE + 0.0015 && x < lon) lon = x;
  }
  GEO.lonCorte = lon - 0.0015;
}
const CONTINENTAL = (nome) => { const f = GEO.feicao.get(nome); return !!(f && f.properties.area_continental); };

// O GeoJSON entra no ECharts uma vez só, já com o ponto do rótulo (cp) de cada bairro
// (dentro do `opcao`: a biblioteca só existe quando o mapa vai ser desenhado).
let MAPAS_REGISTRADOS = false;
function registrarMapas() {
  if (MAPAS_REGISTRADOS || !window.echarts) return;
  echarts.registerMap("santos-ilha", { type: "FeatureCollection", features: GEO.ilha });
  echarts.registerMap("santos-continente", { type: "FeatureCollection", features: GEO.cont });
  MAPAS_REGISTRADOS = true;
}

// ── Classes: quebras naturais (soma mínima de quadrados) sobre a RAIZ da contagem ──
// A raiz estabiliza a variância de contagens; na escala crua José Menino (55) ficava
// sozinho na classe de cima e 1–6 viravam uma classe só. Cortes só entre valores
// diferentes (um empate nunca fica dividido entre duas classes).
function quebras(valores, kMax = 5) {
  const v = valores.filter((x) => x > 0).sort((a, b) => a - b);
  const k = Math.min(kMax, new Set(v).size);
  if (!k) return [];
  const n = v.length, s1 = [0], s2 = [0];
  for (const x of v.map(Math.sqrt)) { s1.push(s1[s1.length - 1] + x); s2.push(s2[s2.length - 1] + x * x); }
  const custo = (i, j) => { const s = s1[j + 1] - s1[i], m = j - i + 1; return s2[j + 1] - s2[i] - (s * s) / m; };
  const D = Array.from({ length: k }, () => new Array(n).fill(Infinity));
  const B = Array.from({ length: k }, () => new Array(n).fill(0));
  for (let j = 0; j < n; j++) D[0][j] = custo(0, j);
  for (let c = 1; c < k; c++) {
    for (let j = c; j < n; j++) {
      for (let i = c; i <= j; i++) {
        if (v[i] === v[i - 1]) continue;  // não parte um empate entre duas classes
        const t = D[c - 1][i - 1] + custo(i, j);
        if (t < D[c][j]) { D[c][j] = t; B[c][j] = i; }
      }
    }
  }
  const lim = [];
  let j = n - 1;
  for (let c = k - 1; c >= 0; c--) { const i = c ? B[c][j] : 0; lim.unshift(v[j]); j = i - 1; }
  // classes contíguas em inteiros: [1–3], [4–6], …
  return lim.map((max, c) => ({ min: c ? lim[c - 1] + 1 : 1, max }));
}
// Rampa dourada de 5 passos da camada comum (Comum.paleta().rampa); zero = neutro.
// Com menos de 5 classes, as cores se espalham pela rampa inteira.
function corDaClasse(c, k, p) {
  const idx = k === 1 ? 2 : Math.round((c * 4) / (k - 1));
  return p.rampa[idx];
}
function corDe(n, p) {
  if (!n) return p.neutro;
  const c = CLASSES.findIndex((q) => n <= q.max);
  return corDaClasse(c < 0 ? CLASSES.length - 1 : c, CLASSES.length, p);
}
// texto sobre a cor: tinta escura ou clara, a que contrastar mais (card e tinta trocam
// de papel entre os temas: um é sempre claro, o outro escuro)
function luminancia(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contraste = (a, b) => { const [x, y] = [luminancia(a), luminancia(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
const textoSobre = (fundo, p) => (contraste(fundo, p.tinta) >= contraste(fundo, p.card) ? p.tinta : p.card);

// ── Enquadramento e projeção ─────────────────────────────────────────────────
// Sem zoom, a ilha ocupa o quadro (alinhada ao topo) e o recorte continental vai para o
// canto sudoeste, que é território de São Vicente e fica vazio; no celular o recorte vira
// uma faixa sob a ilha. Aproximado, a ilha usa o quadro inteiro (o recorte some).
function enquadrar(W, H) {
  const pad = 4, ilha = GEO.caixa.ilha, cont = GEO.caixa.cont;
  const faixa = W < 560, folga = 8, rotTopo = 34, rotLado = 116;
  let w = W - 2 * pad, h = w / ilha.ar;
  const reserva = faixa ? 64 : 0;
  if (h > H - 2 * pad - reserva) { h = H - 2 * pad - reserva; w = h * ilha.ar; }
  const x = (W - w) / 2, y = pad;
  const [x0, , x1, y1] = ilha.bb, y0 = ilha.bb[1];
  const px = (lon) => x + ((lon - x0) / (x1 - x0)) * w;
  const py = (lat) => y + ((y1 - lat) / (y1 - y0)) * h;
  let moldura, iw, ih, cx, cy;
  if (faixa) {
    // a faixa encosta no pé do quadro: entre a praia e ela fica o mar, onde vão os
    // rótulos que não cabem nos bairros pequenos
    const livre = { y: y + h + 6, h: H - pad - (y + h + 6) };
    iw = W - 2 * pad - rotLado - 2 * folga;
    ih = Math.min(iw / cont.ar, 58);
    if (ih > livre.h - 2 * folga) ih = livre.h - 2 * folga;
    iw = ih * cont.ar;
    moldura = { x: pad, w: W - 2 * pad, h: ih + 2 * folga };
    moldura.y = H - pad - moldura.h;
    cx = moldura.x + rotLado + (moldura.w - rotLado - iw) / 2;
    cy = moldura.y + folga;
  } else {
    const canto = { x: Math.max(pad, x), y: py(LAT_CORTE), w: px(GEO.lonCorte) - Math.max(pad, x) };
    canto.h = H - pad - canto.y;
    iw = canto.w - 2 * folga;
    ih = iw / cont.ar;
    if (ih > canto.h - rotTopo - folga) { ih = canto.h - rotTopo - folga; iw = ih * cont.ar; }
    moldura = { x: canto.x, y: H - pad - (ih + rotTopo + folga), w: iw + 2 * folga, h: ih + rotTopo + folga };
    cx = moldura.x + folga;
    cy = moldura.y + rotTopo;
  }
  // aproximado: a mesma proporção, centrada no quadro inteiro
  let zw = W, zh = W / ilha.ar;
  if (zh > H) { zh = H; zw = H * ilha.ar; }
  return {
    ilha: { left: x, top: y, width: w, height: h },
    zoom: { left: (W - zw) / 2, top: (H - zh) / 2, width: zw, height: zh },
    cont: { left: cx, top: cy, width: iw, height: ih },
    moldura, faixa, usaInset: iw >= 80 && ih >= 24,
  };
}
const centroIlha = () => { const bb = GEO.caixa.ilha.bb; return [(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2]; };

// geo ↔ pixel na série da ilha. A caixa recebe a ilha esticada nas duas direções (a
// proporção já vem certa do enquadrar); com zoom, o ECharts põe o `center` no meio da
// caixa e escala em torno dele — a mesma conta aqui, sem depender do estado do gráfico.
function projecao(caixa, zoom, centro) {
  const [x0, y0, x1, y1] = GEO.caixa.ilha.bb;
  const crua = ([lon, lat]) => [caixa.left + ((lon - x0) / (x1 - x0)) * caixa.width,
    caixa.top + ((y1 - lat) / (y1 - y0)) * caixa.height];
  const inversa = ([X, Y]) => [x0 + ((X - caixa.left) / caixa.width) * (x1 - x0),
    y1 - ((Y - caixa.top) / caixa.height) * (y1 - y0)];
  const C = crua(centro), D = [caixa.left + caixa.width / 2, caixa.top + caixa.height / 2];
  return {
    paraPx: (g) => { const p = crua(g); return [(p[0] - C[0]) * zoom + D[0], (p[1] - C[1]) * zoom + D[1]]; },
    deGeo: (P) => inversa([(P[0] - D[0]) / zoom + C[0], (P[1] - D[1]) / zoom + C[1]]),
  };
}

let medidor = null;
function larguraTexto(txt, fonte) {
  medidor = medidor || document.createElement("canvas").getContext("2d");
  medidor.font = fonte;
  return medidor.measureText(txt).width;
}

// Rótulos seletivos: os bairros com mais indicações (ou só o escolhido, quando há escolha).
// 1) dentro da forma, no ponto mais perto do polo onde o retângulo inteiro do rótulo cabe;
// 2) se não couber, o nome em duas linhas; 3) se ainda não couber, fora, com linha-guia,
// numa direção livre (mar ou São Vicente), sem bater em outro rótulo, no recorte
// continental nem nos botões de zoom.
function partirNome(nome) {
  const p = nome.split(" ");
  if (p.length < 2) return null;
  let melhor = null;
  for (let i = 1; i < p.length; i++) {
    const a = p.slice(0, i).join(" "), b = p.slice(i).join(" ");
    const pior = Math.max(a.length, b.length);
    if (!melhor || pior < melhor.pior) melhor = { linhas: [a, b], pior };
  }
  return melhor.linhas;
}
const amostrasRet = (cx, cy, w, h) => {
  const out = [];
  for (const fx of [-0.5, -0.25, 0, 0.25, 0.5]) for (const fy of [-0.5, 0, 0.5]) out.push([cx + fx * w, cy + fy * h]);
  return out;
};
const cruza = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

function aRotular(L, proj, W, H, pequeno) {
  const fonte = `600 ${pequeno ? 10 : 11}px Manrope`;
  let nomes;
  if (LUGAR) nomes = LUGAR.tipo === "bairro" && !CONTINENTAL(LUGAR.nome) ? [LUGAR.nome] : [];
  else {
    nomes = [...STATS.entries()].filter(([k, s]) => !k.startsWith("#") && s.n > 0 && !CONTINENTAL(k))
      .sort((a, b) => b[1].n - a[1].n || a[0].localeCompare(b[0])).slice(0, pequeno ? 3 : 5).map(([k]) => k);
  }
  const { paraPx, deGeo } = proj;
  const altLinha = pequeno ? 12 : 14;
  // áreas já ocupadas (px): botões de zoom e moldura do recorte continental
  const ocupados = [{ x: W - 40, y: 0, w: 40, h: 76 }];
  if (L.usaInset && ZOOM === 1) ocupados.push({ x: L.moldura.x, y: L.moldura.y, w: L.moldura.w, h: L.moldura.h });
  const naIlha = (g) => GEO.ilha.some((f) => {
    const bb = GEO.bbox.get(f.properties.nome);
    return g[0] >= bb[0] && g[0] <= bb[2] && g[1] >= bb[1] && g[1] <= bb[3] && dentroFeicao(g[0], g[1], f);
  });
  const rotulos = new Map();  // nome → { linhas, dx, dy, fora, linha }
  for (const nome of nomes) {
    const f = GEO.feicao.get(nome);
    if (!f) continue;
    const s = STATS.get(nome) || { n: 0 };
    const [cx, cy] = paraPx(f.properties.cp);
    let posto = null;
    for (const linhas of [[nome], partirNome(nome)].filter(Boolean)) {
      const w = Math.max(...linhas.map((l) => larguraTexto(l, fonte)), larguraTexto(fmt(s.n), fonte)) + 8;
      const h = (linhas.length + 1) * altLinha + 4;
      const cabe = (x, y) => amostrasRet(x, y, w, h).every((pt) => { const g = deGeo(pt); return dentroFeicao(g[0], g[1], f); });
      let ponto = cabe(cx, cy) ? [cx, cy] : null;
      if (!ponto) {
        // varre a forma (passo de 3 px) e fica com o ponto que cabe mais perto do polo
        const bb = GEO.bbox.get(nome);
        const [ax, ay] = paraPx([bb[0], bb[3]]), [bx, by] = paraPx([bb[2], bb[1]]);
        let dMin = Infinity;
        for (let x = ax; x <= bx; x += 3) for (let y = ay; y <= by; y += 3) {
          const d = Math.hypot(x - cx, y - cy);
          if (d < dMin && cabe(x, y)) { dMin = d; ponto = [x, y]; }
        }
      }
      if (ponto) {
        const r = { x: ponto[0] - w / 2, y: ponto[1] - h / 2, w, h };
        if (!ocupados.some((o) => cruza(o, r))) {
          posto = { linhas, dx: ponto[0] - cx, dy: ponto[1] - cy, fora: false };
          ocupados.push(r);
          break;
        }
      }
    }
    if (!posto && ZOOM === 1) {
      // fora: direções em ordem de preferência (y cresce para baixo) e distâncias crescentes
      const dirs = [[0, 1], [-0.5, 0.87], [0.5, 0.87], [-0.87, 0.5], [0.87, 0.5], [-1, 0], [1, 0],
        [-0.87, -0.5], [0.87, -0.5], [-0.5, -0.87], [0.5, -0.87], [0, -1]];
      const vizinho = (pt) => { const g = deGeo(pt); return GEO.ilha.some((o) => o !== f && dentroFeicao(g[0], g[1], o)); };
      busca: for (const linhas of [[nome], partirNome(nome)].filter(Boolean)) {
        const w = Math.max(...linhas.map((l) => larguraTexto(l, fonte)), larguraTexto(fmt(s.n), fonte)) + 8;
        const h = (linhas.length + 1) * altLinha + 4;
        for (const dist of [24, 30, 38, 48, 60, 74, 90]) {
          for (const [ux, uy] of dirs) {
            const x = cx + ux * (dist + (w / 2) * Math.abs(ux)), y = cy + uy * (dist + (h / 2) * Math.abs(uy));
            const r = { x: x - w / 2, y: y - h / 2, w, h };
            if (r.x < 2 || r.y < 2 || r.x + w > W - 2 || r.y + h > H - 2) continue;
            if (ocupados.some((o) => cruza(o, r))) continue;
            // o rótulo (com 3 px de folga) fica todo fora da ilha: no mar ou em São Vicente
            if (amostrasRet(x, y, w + 6, h + 6).some((pt) => naIlha(deGeo(pt)))) continue;
            // linha-guia: da borda do bairro (onde o segmento polo→rótulo sai da forma) até a
            // beirada do rótulo. Sem isso o ECharts liga à caixa envolvente da região.
            let a = 0, b = 1;
            for (let k = 0; k < 18; k++) {
              const m = (a + b) / 2, g = deGeo([cx + (x - cx) * m, cy + (y - cy) * m]);
              if (dentroFeicao(g[0], g[1], f)) a = m; else b = m;
            }
            const borda = [cx + (x - cx) * a, cy + (y - cy) * a];
            const vx = cx - x, vy = cy - y;
            const fator = Math.min(1, (w / 2 + 3) / (Math.abs(vx) || 1e-9), (h / 2 + 3) / (Math.abs(vy) || 1e-9));
            const ponta = [x + vx * fator, y + vy * fator];
            // linha curta demais vira um tracinho colado ao texto: afasta mais o rótulo
            if (Math.hypot(ponta[0] - borda[0], ponta[1] - borda[1]) < 10) continue;
            // a linha não pode nascer numa quina com outro bairro nem atravessar outro bairro
            if ([0, 1, 2, 3, 4, 5].some((k) => vizinho([borda[0] + 6 * Math.cos((k * Math.PI) / 3), borda[1] + 6 * Math.sin((k * Math.PI) / 3)]))) continue;
            if ([0.3, 0.55, 0.8].some((tt) => naIlha(deGeo([borda[0] + (ponta[0] - borda[0]) * tt, borda[1] + (ponta[1] - borda[1]) * tt])))) continue;
            posto = { linhas, dx: x - cx, dy: y - cy, fora: true, linha: [borda, ponta] };
            ocupados.push(r);
            break busca;
          }
        }
      }
    }
    if (posto) rotulos.set(nome, posto);  // sem lugar (raro): o nome fica na dica e na tabela
  }
  return rotulos;
}

function dadosDaSerie(feicoes, p, rotulos, pequeno) {
  const escolhido = LUGAR && LUGAR.tipo === "bairro" ? LUGAR.nome : null;
  const apagado = !!LUGAR;  // com um lugar escolhido, o resto do mapa recua
  // divisa entre bairros: no claro, o fundo do cartão (frestas claras); no escuro o neutro
  // (zero indicação) quase some no fundo — a divisa vira a linha do tema e desenha a ilha
  const divisa = luminancia(p.card) < 0.2 ? p.linha : p.card;
  return feicoes.map((f) => {
    const nome = f.properties.nome;
    const s = STATS.get(nome) || { n: 0 };
    const cor = corDe(s.n, p);
    const sel = nome === escolhido;
    const r = rotulos.get(nome), fora = !!(r && r.fora);
    // dentro da forma: tinta pela luminância da cor; fora: tinta do texto sobre o fundo
    const txt = fora ? p.tinta : textoSobre(cor, p);
    const label = {
      show: !!r, formatter: r ? [...r.linhas.map((l) => `{a|${l}}`), `{b|${fmt(s.n)}}`].join("\n") : "",
      rich: {
        a: { fontFamily: "Manrope", fontWeight: 600, fontSize: pequeno ? 10 : 11, color: txt, lineHeight: pequeno ? 12 : 14 },
        b: { fontFamily: "IBM Plex Mono", fontWeight: 600, fontSize: pequeno ? 10.5 : 11.5, color: txt, lineHeight: pequeno ? 12 : 14 },
      },
      textBorderColor: fora ? p.card : cor, textBorderWidth: fora ? 3 : 2,
    };
    return {
      name: nome, value: s.n,
      itemStyle: {
        areaColor: cor, borderColor: sel ? p.tinta : divisa, borderWidth: sel ? 2.4 : 0.8,
        opacity: apagado && !sel ? 0.4 : 1,
      },
      label,
      emphasis: {
        itemStyle: { areaColor: cor, borderColor: p.tinta, borderWidth: sel ? 2.4 : 1.4, opacity: 1 },
        label,
      },
    };
  });
}

function dicaMapa(nome, p) {
  const s = STATS.get(nome) || { n: 0, resp: 0 };
  const sel = LUGAR && LUGAR.tipo === "bairro" && LUGAR.nome === nome;
  const verbo = TOQUE ? "toque" : "clique";
  const nota = sel ? `${verbo} de novo para limpar` : (s.n ? `${verbo} para ver a lista` : "");
  if (!s.n) return Comum.dicaGrafico(nome, [[corDe(0, p), "nenhuma indicação", "", "p"]], nota);
  return Comum.dicaGrafico(nome, [
    [corDe(s.n, p), "Indicações", fmt(s.n), "p"],
    [null, "Respondidas", fmt(s.resp)],
  ], nota);
}

// option do ECharts (Comum.grafico chama de novo a cada filtro, tema e largura)
function opcaoMapa(p, largura) {
  registrarMapas();
  const W = largura, H = el("mapa").clientHeight;
  const L = enquadrar(W, H);
  const pequeno = L.ilha.width < 520;
  const centro = ZOOM > 1 ? (CENTRO || centroIlha()) : centroIlha();
  const caixa = ZOOM > 1 ? L.zoom : L.ilha;
  const rotulos = aRotular(L, projecao(caixa, ZOOM, centro), W, H, pequeno);
  const mostraInset = L.usaInset && ZOOM === 1;
  const comum = {
    type: "map", nameProperty: "nome", aspectScale: ASPECTO, selectedMode: false,
    itemStyle: { borderJoin: "round" }, label: { show: false }, select: { disabled: true },
  };
  // moldura e rótulo do recorte (HTML por cima do canvas, sem capturar o ponteiro)
  const ins = el("inset");
  ins.classList.toggle("ver", mostraInset);
  ins.classList.toggle("faixa", L.faixa);
  Object.assign(ins.style, { left: L.moldura.x + "px", top: L.moldura.y + "px", width: L.moldura.w + "px", height: L.moldura.h + "px" });
  const nCont = GEO.cont.reduce((a, f) => a + ((STATS.get(f.properties.nome) || { n: 0 }).n), 0);
  el("inset-sub").textContent = nCont ? plural(nCont, "indicação", "indicações") : "nenhuma indicação";
  return {
    // linhas-guia dos rótulos postos fora: desenhadas à mão, em pixels do quadro (a linha
    // automática do ECharts liga à caixa envolvente da região e errava o bairro)
    graphic: [...rotulos.entries()].filter(([, r]) => r.fora && r.linha).map(([nome, r]) => ({
      id: "guia-" + nome, type: "polyline", silent: true, z: 100,
      shape: { points: r.linha }, style: { stroke: p.muted, lineWidth: 1, fill: null },
    })),
    animationDurationUpdate: 250,
    tooltip: { trigger: "item", confine: true, transitionDuration: 0, formatter: (ps) => dicaMapa(ps.name, p) },
    series: [
      { ...comum, id: "ilha", map: "santos-ilha", ...caixa, zoom: ZOOM, center: centro,
        roam: ZOOM > 1 ? "move" : false,
        data: dadosDaSerie(GEO.ilha, p, rotulos, pequeno),
        // posição escolhida em aRotular (deslocamento a partir do polo; fora = com linha-guia)
        labelLayout: (q) => {
          const r = rotulos.get(GEO.ilha[q.dataIndex] && GEO.ilha[q.dataIndex].properties.nome);
          return r ? { dx: r.dx, dy: r.dy } : {};
        } },
      { ...comum, id: "continente", map: "santos-continente", ...L.cont, silent: !mostraInset,
        data: dadosDaSerie(GEO.cont, p, new Map(), true)
          .map((d) => (mostraInset ? d : { ...d, itemStyle: { ...d.itemStyle, opacity: 0 } })) },
    ],
  };
}

const DEF_MAPA = {
  opcao: opcaoMapa,
  acessivel: () => ACESSIVEL,
  dependeDaLargura: true,
  eventos: (chart) => {
    chart.on("click", (ev) => {
      if (ev.componentType === "series" && ev.name) escolher({ tipo: "bairro", nome: ev.name });
    });
    // arrastar o mapa aproximado muda o centro no ECharts: guardado para o próximo desenho
    chart.on("georoam", () => {
      const s = (chart.getOption().series || [])[0];
      if (ZOOM > 1 && s && Array.isArray(s.center)) CENTRO = [+s.center[0], +s.center[1]];
    });
  },
};
const desenharMapa = () => Comum.grafico("mapa", DEF_MAPA);

function atualizarLegenda() {
  const p = Comum.paleta();
  const itens = ['<li class="tit">Indicações por bairro</li>',
    `<li><span class="sw" style="background:${p.neutro}"></span>nenhuma</li>`];
  CLASSES.forEach((c, i) => {
    const txt = c.min === c.max ? fmt(c.min) : `${fmt(c.min)}–${fmt(c.max)}`;
    itens.push(`<li><span class="sw" style="background:${corDaClasse(i, CLASSES.length, p)}"></span>${txt}</li>`);
  });
  el("legenda").innerHTML = itens.join("");
}

// ── Filtros ──────────────────────────────────────────────────────────────────
function passaSit(i, sit) {
  if (sit === "respondida") return i._sit === "respondida";
  if (sit === "sem_merito") return i._sit !== "respondida";
  if (sit === "sem_retorno") return i._sit === "sem";
  return true;
}
const noLugar = (i) => !LUGAR || (LUGAR.tipo === "bairro" ? i._chave === LUGAR.nome : i._chave === "#" + LUGAR.slug);
const ORDEM = (a, b) => (b._ini || 0) - (a._ini || 0) || chaveNumero(b.numero) - chaveNumero(a.numero);

function estatisticas(lista) {
  const m = new Map();
  for (const i of lista) {
    let s = m.get(i._chave);
    if (!s) m.set(i._chave, (s = { n: 0, resp: 0, dias: [] }));
    s.n++;
    if (i._sit === "respondida") { s.resp++; if (i._dias != null) s.dias.push(i._dias); }
  }
  for (const s of m.values()) s.med = mediana(s.dias);
  return m;
}

function aplicar() {
  const q = norm(el("q").value).trim();
  const termos = q ? q.split(/\s+/) : [];
  const ano = el("ano").value, sit = el("sit").value;
  BASE = ITENS.filter((i) => (!ano || String(i.ano) === ano) && passaSit(i, sit)
    && (!termos.length || termos.every((tt) => i._busca.includes(tt))));
  STATS = estatisticas(BASE);
  CLASSES = quebras([...STATS.entries()].filter(([k]) => !k.startsWith("#")).map(([, s]) => s.n));
  // link direto (?n=): só a indicação, ignorando os outros filtros
  FILTRADAS = FOCO ? ITENS.filter((i) => i.numero === FOCO) : BASE.filter(noLugar).sort(ORDEM);
  el("foco").hidden = !FOCO;
  if (FOCO) el("foco-num").textContent = FOCO;
  pag.reiniciar(FILTRADAS);
  el("lista-rolagem").scrollTop = 0;  // lista nova começa do topo (no desktop ela rola por dentro)
  el("vazio").hidden = FILTRADAS.length > 0;
  el("csv").disabled = FILTRADAS.length === 0;
  atualizarResumo();
  atualizarNota();
  atualizarSelecao();
  atualizarChips();
  atualizarCabLista();
  atualizarLegenda();
  atualizarTabela();
  desenharMapa();
  Comum.gravarParams({
    q: el("q").value.trim(), ano, sit,
    bairro: LUGAR && LUGAR.tipo === "bairro" ? LUGAR.nome : "",
    regiao: LUGAR && LUGAR.tipo === "lugar" ? LUGAR.slug : "",
    n: FOCO,
  });
}

// mexer em filtro (ou escolher lugar) sai do link direto
function aoFiltrar() { FOCO = ""; aplicar(); }

function escolher(novo) {
  const igual = LUGAR && novo && LUGAR.tipo === novo.tipo && (LUGAR.nome || LUGAR.slug) === (novo.nome || novo.slug);
  LUGAR = igual ? null : novo;
  aoFiltrar();
}

// ── Textos e cartões ─────────────────────────────────────────────────────────
function nomeDoLugar() {
  if (!LUGAR) return "";
  return LUGAR.tipo === "bairro" ? LUGAR.nome : LUGARES.get(LUGAR.slug).nome;
}

// Número-manchete: a base inteira (os cartões abaixo seguem o filtro). Escrito com as
// fontes já carregadas (Comum.quandoFonte): antes a frase trocava de linha — CLS.
function renderHero() {
  const sem = ITENS.filter((i) => i._sit !== "respondida").length;
  const nada = ITENS.filter((i) => i._sit === "sem").length;
  const ini = ITENS.map((i) => i._ini).filter(Boolean).sort((a, b) => a - b)[0];
  Comum.quandoFonte(Comum.FACES_MANCHETE, () => {
    el("hero-grande").textContent = fmt(sem);
    const ctx = el("hero-contexto");
    ctx.textContent = `${sem === 1 ? "indicação do mandato" : "indicações do mandato"} sem resposta de mérito da Prefeitura — `;
    const b = document.createElement("b");
    b.textContent = nada === sem ? (sem === 1 ? "sem nenhum retorno" : "todas sem nenhum retorno") : `${fmt(nada)} sem nenhum retorno`;
    // "de N desde …" (e não "apresentadas desde"): a frase cabe nas 2 linhas reservadas no desktop
    ctx.append(b, `, de ${fmt(ITENS.length)} desde ${ini ? `${MESES[ini.getMonth()]} de ${ini.getFullYear()}` : "2025"}.`);
  });
}

// Cartões de resumo (respeitam o filtro e o lugar escolhido)
function atualizarResumo() {
  const total = FILTRADAS.length;
  const resp = FILTRADAS.filter((i) => i._sit === "respondida").length;
  const sem = total - resp;
  const nada = FILTRADAS.filter((i) => i._sit === "sem").length;
  const tram = sem - nada;
  const dias = FILTRADAS.map((i) => i._dias).filter((d) => d != null);
  const med = mediana(dias);
  const pct = total ? Math.round((resp / total) * 100) : 0;
  const subSem = !sem ? "nenhuma pendente no filtro"
    : (tram ? `${fmt(nada)} sem nenhum retorno · ${fmt(tram)} com ofício ou a classificar` : "nenhum retorno da Prefeitura");
  const tituloSem = tram
    ? `${fmt(nada)} sem nenhum documento da Prefeitura; ${fmt(tram)} com ofício de encaminhamento ou com resposta ainda não classificada`
    : subSem;
  const cards = [
    { rotulo: "Indicações", valor: fmt(total), sub: FOCO ? "link direto" : (LUGAR ? "no lugar escolhido" : "no filtro atual") },
    { rotulo: "Respondidas", valor: total ? `${pct}%` : "—", sub: `${fmt(resp)} de ${fmt(total)} com resposta de mérito` },
    { rotulo: "Sem resposta de mérito", valor: fmt(sem), sub: subSem, titulo: tituloSem },
    { rotulo: "Mediana até a resposta", valor: med == null ? "—" : `${fmt(med)} dias`,
      sub: dias.length ? `entre a sessão e a resposta (${plural(dias.length, "resposta", "respostas")})` : "sem respostas no filtro atual" },
  ];
  el("stats").innerHTML = cards.map((c) => `<div class="stat">
      <div class="rotulo">${esc(c.rotulo)}</div>
      <div class="valor">${esc(c.valor)}</div>
      <div class="sub" title="${esc(c.titulo || c.sub)}">${esc(c.sub)}</div>
    </div>`).join("");
}

// Cobertura do mapa em palavras (sobre os filtros de busca, ano e situação)
function atualizarNota() {
  const total = BASE.length;
  const noMapa = BASE.filter((i) => i._lugar.tipo === "bairro").length;
  const regiao = BASE.filter((i) => i._lugar.tipo === "lugar" && i._lugar.slug !== "sem-bairro").length;
  const sem = total - noMapa - regiao;
  const pct = total ? Math.round((noMapa / total) * 100) : 0;
  el("mapa-nota").innerHTML = total
    ? `<b>${fmt(noMapa)} de ${fmt(total)}</b> indicações estão num bairro do mapa (${pct}%)` +
      (regiao ? `; ${fmt(regiao)} ${regiao === 1 ? "cita" : "citam"} uma região maior que um bairro` : "") +
      (sem ? ` e ${fmt(sem)} ${sem === 1 ? "não tem" : "não têm"} bairro reconhecível na planilha` : "") +
      ". A contagem mostra onde o mandato pediu, não a necessidade de cada bairro."
    : "Nenhuma indicação com esses filtros.";
}

// Linha de estado sobre o mapa: a dica, ou o lugar escolhido com o "Limpar"
function atualizarSelecao() {
  const box = el("selecao");
  if (!LUGAR) {
    box.innerHTML = `<span class="dica">${TOQUE ? "Toque" : "Clique"} num bairro para ver as indicações dele.</span>`;
    return;
  }
  const nome = nomeDoLugar();
  const n = BASE.filter(noLugar).length;
  box.innerHTML = `<span><b>${esc(nome)}</b> · ${plural(n, "indicação", "indicações")}</span>` +
    `<button type="button" class="chip limpar" data-limpar aria-label="Limpar a escolha (${esc(nome)}) e ver todas as indicações">✕ Limpar</button>` +
    `<a class="ir-lista" href="#lista">ver a lista ↓</a>`;
}

function atualizarChips() {
  const partes = [];
  const totais = estatisticas(ITENS);  // quais lugares existem na base inteira (os botões não somem com o filtro)
  for (const [nome, slug, desc] of [...REGIOES, ...SOBRAS]) {
    if (!totais.has("#" + slug)) continue;
    const n = (STATS.get("#" + slug) || { n: 0 }).n;
    const on = !!(LUGAR && LUGAR.tipo === "lugar" && LUGAR.slug === slug);
    partes.push(`<button type="button" class="chip" data-lugar="${slug}" aria-pressed="${on}" title="${esc(desc)}">${esc(nome)} <span class="n">${fmt(n)}</span></button>`);
  }
  el("chips").innerHTML = partes.join("");
}

function atualizarCabLista() {
  const tit = el("lista-tit"), sub = el("lista-sub");
  if (FOCO) { tit.textContent = "Indicação " + FOCO; sub.textContent = "Link direto para uma indicação."; return; }
  if (!LUGAR) { tit.textContent = "Indicações"; sub.textContent = "Mais recentes primeiro."; return; }
  if (LUGAR.tipo === "bairro") {
    tit.textContent = LUGAR.nome;
    sub.textContent = `${plural(FILTRADAS.length, "indicação", "indicações")} neste bairro · mais recentes primeiro.`;
  } else {
    const l = LUGARES.get(LUGAR.slug);
    tit.textContent = l.nome;
    sub.textContent = `${l.desc} · ${plural(FILTRADAS.length, "indicação", "indicações")}.`;
  }
}

function rotuloLugar(i) {
  if (i._lugar.tipo === "bairro") return i._lugar.nome;
  return i._lugar.slug === "sem-bairro" ? "" : LUGARES.get(i._lugar.slug).nome;
}

function linhaHTML(i) {
  const quando = i._resp
    ? (i._sit === "respondida"
      ? `respondida em ${esc(i.data_resposta_merito || i.data_resposta)}${i._dias != null ? ` · ${plural(i._dias, "dia", "dias")}` : ""}`
      : `documento recebido em ${esc(i.data_resposta_merito || i.data_resposta)}`)
    : "";
  const lugar = LUGAR && !FOCO ? "" : rotuloLugar(i);
  const pasta = i.url_resposta
    ? `<a class="pdf" href="${esc(i.url_resposta)}" target="_blank" rel="noopener" title="Pasta do gabinete no Drive com os PDFs (pode exigir login)">Resposta ↗</a>`
    : "";
  const pe = [lugar ? `<span class="lugar">${esc(lugar)}</span>` : "", quando ? `<span>${quando}</span>` : "", pasta]
    .filter(Boolean).join("");
  return `<li class="ind">
    <div class="ind-topo"><span class="num">${esc(i.numero)}</span><span class="data">sessão ${esc(i.data_sessao || "sem data")}</span><span class="sit ${i._sitClasse}">${esc(i._sitRotulo)}</span></div>
    <p class="ind-assunto">${esc(i.assunto)}</p>${pe ? `<div class="ind-pe">${pe}</div>` : ""}
  </li>`;
}

// ── Tabela por bairro (equivalente do mapa: clicável e ordenável) ─────────────
function atualizarTabela() {
  const linhas = [...STATS.entries()].filter(([k]) => !k.startsWith("#")).map(([nome, s]) => ({ nome, ...s }));
  const { col, dir } = ORDEM_TAB, sinal = dir === "asc" ? 1 : -1;
  linhas.sort((a, b) => {
    if (col === "nome") return sinal * a.nome.localeCompare(b.nome, "pt-BR");
    const va = a[col] ?? -1, vb = b[col] ?? -1;
    return sinal * (va - vb) || b.n - a.n || a.nome.localeCompare(b.nome, "pt-BR");
  });
  const escolhido = LUGAR && LUGAR.tipo === "bairro" ? LUGAR.nome : null;
  el("pb-corpo").innerHTML = linhas.map((l) => `<tr${l.nome === escolhido ? ' class="atual"' : ""}>
      <th scope="row"><button type="button" class="lnk" data-bairro="${esc(l.nome)}" aria-pressed="${l.nome === escolhido}">${esc(l.nome)}</button></th>
      <td>${fmt(l.n)}</td><td>${fmt(l.resp)}</td><td>${l.med == null ? "—" : fmt(l.med)}</td>
    </tr>`).join("");
  const pe = [];
  for (const [nome, slug] of [...REGIOES, ...SOBRAS]) {
    const s = STATS.get("#" + slug);
    if (!s) continue;
    pe.push(`<tr><th scope="row">${esc(nome)} <span class="sr-only">(fora do mapa)</span></th><td>${fmt(s.n)}</td><td>${fmt(s.resp)}</td><td>${s.med == null ? "—" : fmt(s.med)}</td></tr>`);
  }
  const zeros = GEO.ilha.length + GEO.cont.length - linhas.length;
  if (zeros > 0) pe.push(`<tr><th scope="row">Outros ${fmt(zeros)} bairros</th><td>0</td><td>—</td><td>—</td></tr>`);
  el("pb-pe").innerHTML = pe.join("");
  document.querySelectorAll("#por-bairro thead th").forEach((th) => {
    if (th.dataset.col === col) th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
    else th.removeAttribute("aria-sort");
  });
  el("pb-sub").textContent = `${plural(linhas.length, "bairro", "bairros")} com indicação · a mesma informação do mapa, em tabela`;
  // descrição + tabela oculta do mapa (Comum.chartAcessivel), do mesmo array que pinta o mapa
  const top = [...linhas].sort((a, b) => b.n - a.n).slice(0, 3).map((l) => `${l.nome} (${fmt(l.n)})`);
  const nCont = GEO.cont.reduce((a, f) => a + ((STATS.get(f.properties.nome) || { n: 0 }).n), 0);
  const tabela = [...linhas].sort((a, b) => b.n - a.n || a.nome.localeCompare(b.nome, "pt-BR"))
    .map((l) => [l.nome, fmt(l.n), fmt(l.resp), l.med == null ? "—" : fmt(l.med)]);
  if (zeros > 0) tabela.push([`Outros ${fmt(zeros)} bairros`, "0", "0", "—"]);
  ACESSIVEL = {
    descricao: linhas.length
      ? `Mapa dos bairros de Santos colorido pelo número de indicações do mandato. ${plural(linhas.length, "bairro tem", "bairros têm")} ao menos uma; ` +
        `mais indicações em ${top.join(", ")}. ` +
        (nCont ? `${plural(nCont, "indicação", "indicações")} na área continental.` : `Nenhuma indicação nos ${fmt(GEO.cont.length)} bairros da área continental.`)
      : "Mapa dos bairros de Santos: nenhuma indicação com bairro nos filtros atuais.",
    cabecalhos: ["Bairro", "Indicações", "Respondidas", "Mediana de dias até a resposta"],
    linhas: tabela,
  };
}

// Exporta o resultado filtrado: só campos públicos do índice (+ os dias, calculados deles)
function exportarCSV() {
  if (!FILTRADAS.length) return;
  const campos = ["numero", "ano", "assunto", "data_sessao", "data_resposta", "data_resposta_merito",
    "situacao", "respondido", "bairro", "regiao", "dias_ate_resposta", "url_resposta"];
  Comum.exportarCsv(`indicacoes-filtro-${new Date().toISOString().slice(0, 10)}.csv`, campos,
    FILTRADAS.map((i) => campos.map((c) => (
      c === "situacao" ? i._sitRotulo
        : c === "respondido" ? (i.respondido ? "sim" : "não")
          : c === "dias_ate_resposta" ? (i._dias ?? "") : (i[c] ?? "")))));
}

// ── Zoom (botões; arrastar só vale com o mapa aproximado) ─────────────────────
function aplicarZoom(novo) {
  const antes = ZOOM;
  ZOOM = Math.min(8, Math.max(1, novo));
  el("zoom-volta").hidden = ZOOM === 1;
  el("zoom-menos").disabled = ZOOM === 1;
  if (ZOOM === 1) CENTRO = null;
  else if (antes === 1) {
    // aproxima no bairro escolhido (se for da ilha); senão no centro da ilha
    const bb = LUGAR && LUGAR.tipo === "bairro" && !CONTINENTAL(LUGAR.nome) && GEO.bbox.get(LUGAR.nome);
    CENTRO = bb ? [(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2] : centroIlha();
  }
  desenharMapa();
}

// ── Início ───────────────────────────────────────────────────────────────────
async function init() {
  let geo;
  try {
    const [rg, ri] = await Promise.all([
      fetch("./geo/santos-bairros.geojson", { cache: "no-cache" }),
      fetch("./indicacoes-index.json", { cache: "no-cache" }),
    ]);
    if (!rg.ok || !ri.ok) throw new Error("HTTP " + (rg.ok ? ri.status : rg.status));
    [geo, ITENS] = await Promise.all([rg.json(), ri.json()]);
  } catch (e) {
    el("contagem").textContent = "";
    el("hero-num").hidden = true;  // sem dado, sem esqueleto eterno
    Comum.estadoErro("stats", "Não foi possível carregar as indicações. Verifique a conexão.", init);
    return;
  }
  prepararGeo(geo);
  for (const i of ITENS) derivar(i);
  renderHero();

  const anos = [...new Set(ITENS.map((i) => i.ano).filter(Boolean))].sort((a, b) => b - a);
  for (const a of anos) el("ano").add(new Option(a, a));
  // estado vindo da URL (link compartilhável) — antes do primeiro render
  const p = Comum.lerParams();
  for (const id of ["q", "ano", "sit"]) { const v = p.get(id); if (v) el(id).value = v; }
  const b = p.get("bairro"), r = p.get("regiao");
  if (b && GEO.bbox.has(b)) LUGAR = { tipo: "bairro", nome: b };
  else if (r && LUGARES.has(r)) LUGAR = { tipo: "lugar", slug: r };
  FOCO = p.get("n") || "";

  pag = Comum.paginador({
    // no desktop a lista rola dentro do cartão; no celular ela segue a página: lotes menores
    corpo: "corpo", mais: "mais", contagem: "contagem", linha: linhaHTML,
    tamanho: matchMedia("(max-width: 900px)").matches ? 20 : 60,
    rotulo: (lista, mostrando) => {
      const resp = lista.filter((i) => i._sit === "respondida").length;
      return `${plural(lista.length, "indicação", "indicações")} — ${fmt(resp)} com resposta de mérito — exibindo ${fmt(mostrando)}`;
    },
  });

  el("q").addEventListener("input", Comum.debounce(aoFiltrar));
  ["ano", "sit"].forEach((id) => el(id).addEventListener("input", aoFiltrar));
  el("limpar").addEventListener("click", () => {
    for (const id of ["q", "ano", "sit"]) el(id).value = "";
    LUGAR = null;
    ZOOM = 1; CENTRO = null;
    el("zoom-volta").hidden = true;
    el("zoom-menos").disabled = true;
    aoFiltrar();
  });
  el("foco-todos").addEventListener("click", aoFiltrar);
  el("csv").addEventListener("click", exportarCSV);
  el("chips").addEventListener("click", (e) => {
    const c = e.target.closest("button[data-lugar]");
    if (c) escolher({ tipo: "lugar", slug: c.dataset.lugar });
  });
  el("selecao").addEventListener("click", (e) => {
    if (!e.target.closest("[data-limpar]")) return;
    LUGAR = null;
    aoFiltrar();
  });
  el("por-bairro").addEventListener("click", (e) => {
    const bt = e.target.closest("button");
    if (!bt) return;
    if (bt.dataset.bairro) { escolher({ tipo: "bairro", nome: bt.dataset.bairro }); return; }
    const th = bt.closest("th[data-col]");
    if (th) {
      const col = th.dataset.col;
      ORDEM_TAB = { col, dir: ORDEM_TAB.col === col ? (ORDEM_TAB.dir === "asc" ? "desc" : "asc") : (col === "nome" ? "asc" : "desc") };
      atualizarTabela();
    }
  });
  el("zoom-mais").addEventListener("click", () => aplicarZoom(ZOOM * 1.6));
  el("zoom-menos").addEventListener("click", () => aplicarZoom(ZOOM / 1.6));
  el("zoom-volta").addEventListener("click", () => aplicarZoom(1));
  // a legenda é HTML: repinta com o tema (o mapa a camada comum repinta sozinha)
  window.addEventListener("temamudou", atualizarLegenda);

  aplicar();
  // rótulos do canvas (medidos e pintados) na fonte certa: com Manrope e Plex Mono 600
  // carregadas (no máximo 2,5 s), o mapa é refeito — a lista e os números não esperam
  Comum.quandoFonte(['600 11px Manrope', '600 11px "IBM Plex Mono"'], desenharMapa);
}

init();
