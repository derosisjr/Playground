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
// camada comum (eram cópias locais)
const esc = Comum.escapar;
const brl = Comum.brl;
const brlc = (v) => Comum.brl(v, 2);
const compacto = Comum.compacto;
const eixoReais = { ticks: { callback: (v) => compacto(v) } };
const dataBR = (s) => s ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : "—";
const soDigitos = (s) => String(s || "").replace(/\D/g, "");

function falha(msg) {
  el("stats-skel").hidden = true;
  el("fav-nome").textContent = "Favorecido não encontrado";
  el("carregando").innerHTML = esc(msg) +
    ' <br><br><a href="./despesas.html#favorecidos">← Voltar ao painel de despesas</a>';
}

// ── Índice do painel (meses, meses parciais, alertas) — carregado uma vez ─────
let IDX_PAINEL = null;
async function indicePainel() {
  if (!IDX_PAINEL) {
    const r = await fetch("./despesas-index.json", { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    IDX_PAINEL = await r.json();
  }
  return IDX_PAINEL;
}
const parciais = () => new Set(IDX_PAINEL?.resumo?.meses_parciais || []);

// série mensal com TODOS os meses do período (os sem pagamento viram 0 — antes o eixo
// "fechava" a lacuna e dois meses sem nada sumiam do gráfico)
function serieCompleta(d) {
  const s = d.serie_mensal || [];
  if (!s.length) return [];
  const mapa = new Map(s.map((x) => [x.ano * 100 + x.mes, x.valor]));
  let ini = s[0].ano * 100 + s[0].mes, fim = s[s.length - 1].ano * 100 + s[s.length - 1].mes;
  const p = IDX_PAINEL?.periodo;
  if (p?.de) ini = Math.min(ini, +p.de.replace("-", ""));
  if (p?.ate) fim = Math.max(fim, +p.ate.replace("-", ""));
  const out = [];
  for (let k = ini; k <= fim; k = k % 100 === 12 ? k + 89 : k + 1)
    out.push({ ano: Math.floor(k / 100), mes: k % 100, valor: mapa.get(k) || 0 });
  return out;
}

// gráficos separados do resto do render: o "temamudou" repinta só esta parte
function renderGraficosFav(d) {
  if (!window.Chart) {   // CDN fora do ar: o resto da página segue
    document.querySelectorAll("#conteudo canvas").forEach((cv) => {
      cv.hidden = true;
      if (!cv.nextElementSibling?.classList.contains("nota"))
        cv.insertAdjacentHTML("afterend", '<p class="nota">Gráfico indisponível — a biblioteca de gráficos não carregou.</p>');
    });
    return;
  }
  ["ch-mensal", "ch-funcao"].forEach((id) => {
    const c = Chart.getChart(id);
    if (c) c.destroy();
  });

  // gráfico mensal — meses ainda parciais na origem ficam claros e com *
  const serie = serieCompleta(d);
  const parc = parciais();
  const ehParcial = (s) => parc.has(`${s.ano}-${String(s.mes).padStart(2, "0")}`);
  new Chart(el("ch-mensal"), {
    type: "bar",
    data: {
      labels: serie.map((s) => `${MESES[s.mes]}/${String(s.ano).slice(2)}${ehParcial(s) ? "*" : ""}`),
      datasets: [{ data: serie.map((s) => s.valor),
                   backgroundColor: serie.map((s) => ehParcial(s) ? "rgba(201,168,76,.35)" : GOLD) }],
    },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (c) => brlc(c.parsed.y),
          footer: (it) => it.length && ehParcial(serie[it[0].dataIndex]) ? "mês parcial — a origem ainda está publicando" : "" } } },
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
    `Pagamentos recebidos por mês, pela data do pagamento. Total no mandato: ${compacto(d.total)}.`,
    ["Mês", "Recebido"], serie.map((s) => [`${MESES[s.mes]}/${s.ano}${ehParcial(s) ? " (parcial)" : ""}`, compacto(s.valor)]));
  Comum.chartAcessivel("ch-funcao",
    "Distribuição do valor recebido por função de governo.",
    ["Função", "Recebido"], fn.map((f) => [f.funcao, compacto(f.valor)]));
}

// card de alertas: "a conferir" (anomalia + inconsistência) separado de contexto,
// a mesma divisão do painel e do hub
function alertasCard(alertas) {
  const conferir = alertas.filter((a) => a.classe ? a.classe !== "contexto" : a.severidade !== "baixa").length;
  const contexto = alertas.length - conferir;
  return { rotulo: "Alertas a conferir", valor: String(conferir),
           sub: contexto ? `+ ${contexto} de contexto (escala, não achado)` : "envolvendo este favorecido" };
}

// grafia × outro nome: sem acento/caixa/pontuação e sem sufixos societários, os nomes
// que não compartilham nem metade das palavras não são "grafia" — é outra razão social
const SUFIXOS = new Set(["LTDA", "EIRELI", "EPP", "ME", "SA", "CIA", "COMPANHIA", "DE", "DA", "DO", "DOS", "DAS", "E",
                         "SPE", "S", "A", "NOME", "EMPRESARIAL"]);
const palavras = (n) => new Set(Comum.nomeNormalizado(n).replace(/[^A-Z0-9 ]/g, " ").split(/\s+/)
  .filter((t) => t.length > 1 && !SUFIXOS.has(t)));
function outroNome(a, b) {
  const A = palavras(a), B = palavras(b);
  if (!A.size || !B.size) return false;
  let comum = 0;
  A.forEach((t) => { if (B.has(t)) comum += 1; });
  return comum / Math.min(A.size, B.size) < 0.5;
}

function renderComposicao(d) {
  const tot = d.total || 1;
  const pct = (v) => `${(100 * v / tot).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% do recebido`;
  const li = (rot, v, extra) => `<li>${esc(rot || "(não informado)")}<br><span class="v">${compacto(v)}</span>
    <span class="p"> · ${pct(v)}${extra ? " · " + extra : ""}</span></li>`;
  const elem = d.por_elemento || [], ug = d.por_unidade || [], tp = d.por_tipo || [];
  if (!elem.length && !ug.length && !tp.length) return;
  el("comp-elemento").innerHTML = elem.map((e) => li(e.elemento, e.valor,
    e.participacao_pct != null ? `${e.participacao_pct.toLocaleString("pt-BR")}% de todo o elemento` : "")).join("");
  el("comp-unidade").innerHTML = ug.map((u) => li(u.unidade, u.valor)).join("");
  el("comp-tipo").innerHTML = tp.map((t) => li(t.tipo, t.valor, `${t.qtd.toLocaleString("pt-BR")} pagamento(s)`)).join("");
  el("box-composicao").hidden = false;
}

function renderGrafias(d) {
  const g = d.grafias_detalhe || [];
  if (g.length < 2) return;
  el("corpo-grafias").innerHTML = g.map((x) => `
    <tr>
      <td data-label="Nome na origem">${esc(x.nome)}${outroNome(x.nome, d.nome) ? '<span class="outro-nome">outro nome</span>' : ""}</td>
      <td data-label="Recebido" class="num">${brlc(x.valor)}</td>
      <td data-label="Pagamentos" class="num">${x.qtd.toLocaleString("pt-BR")}</td>
      <td data-label="Período">${dataBR(x.primeiro)} a ${dataBR(x.ultimo)}</td>
    </tr>`).join("");
  el("box-grafias").hidden = false;
}

// ── Consultas externas (só CNPJ de fornecedor — CPF e entes públicos não) ─────
function renderExterno(d) {
  const dig = (d.chave || "").startsWith("cnpj:") ? d.chave.slice(5) : (soDigitos(d.documento).length === 14 ? soDigitos(d.documento) : "");
  if (!dig || d.ente_publico) return;
  el("ext-links").innerHTML =
    `<a href="https://portaldatransparencia.gov.br/pessoa-juridica/${dig}" target="_blank" rel="noopener">` +
    "Portal da Transparência federal ↗</a> — sanções (CEIS/CNEP), contratos e repasses federais deste CNPJ.";
  el("ext-cnpj").onclick = () => consultarCnpj(dig, d);
  el("box-externo").hidden = false;
}

async function consultarCnpj(dig, d) {
  const alvo = el("ext-resultado");
  el("ext-cnpj").disabled = true;
  alvo.textContent = "Consultando…";
  try {
    const r = await fetch(`https://brasilapi.com.br/api/cnpj/v1/${dig}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const c = await r.json();
    const sinais = [];
    // empresa aberta perto do 1º pagamento: sinal clássico de triagem (pode ser normal:
    // SPE de concessão, filial nova) — a base começa em jan/2025, então "1º" é o 1º NA BASE
    if (c.data_inicio_atividade && d.primeiro_pagamento) {
      const meses = (new Date(d.primeiro_pagamento) - new Date(c.data_inicio_atividade)) / (30.44 * 864e5);
      if (meses < 12)
        sinais.push(`Aberta em ${dataBR(c.data_inicio_atividade)}, ${meses < 0 ? "depois do" : `${Math.max(0, Math.round(meses))} mês(es) antes do`} ` +
                    `1º pagamento na base (${dataBR(d.primeiro_pagamento)}; a base começa em jan/2025). Pode ser normal ` +
                    "(SPE de concessão, filial nova) — vale conferir o contrato e o processo.");
    }
    if (c.descricao_situacao_cadastral && c.descricao_situacao_cadastral !== "ATIVA")
      sinais.push(`Situação cadastral: ${c.descricao_situacao_cadastral}` +
                  (c.data_situacao_cadastral ? ` desde ${dataBR(c.data_situacao_cadastral)}` : "") + ".");
    const socios = (c.qsa || []).map((q) => `${q.nome_socio}${q.qualificacao_socio ? " (" + q.qualificacao_socio + ")" : ""}`);
    const linha = (k, v) => v ? `<dt>${esc(k)}</dt><dd>${esc(String(v))}</dd>` : "";
    alvo.innerHTML = sinais.map((s) => `<div class="sinal">⚠ ${esc(s)}</div>`).join("") + "<dl>" +
      linha("Razão social", c.razao_social) + linha("Nome fantasia", c.nome_fantasia) +
      linha("Abertura", dataBR(c.data_inicio_atividade)) +
      linha("Situação", c.descricao_situacao_cadastral) +
      linha("Atividade principal", c.cnae_fiscal_descricao) + linha("Porte", c.porte) +
      linha("Capital social", c.capital_social != null ? brl(c.capital_social) : "") +
      linha("Sede", [c.municipio, c.uf].filter(Boolean).join("/")) +
      linha("Sócios", socios.join("; ")) + "</dl>" +
      '<p class="nota" style="margin-top:8px">Fonte: cadastro da Receita Federal via BrasilAPI (consulta feita agora, ' +
      "pelo seu navegador). Confira no comprovante oficial antes de citar.</p>";
  } catch (e) {
    console.warn("cnpj:", e.message);
    Comum.estadoErro(alvo, "Não foi possível consultar o cadastro agora (serviço externo).", () => consultarCnpj(dig, d));
  } finally {
    el("ext-cnpj").disabled = false;
  }
}

function render(d) {
  DOSSIE = d;
  document.title = `${d.nome} — Raio-X do favorecido`;
  el("fav-nome").textContent = d.nome;
  el("fav-doc").textContent = d.documento || "documento não informado";
  el("fav-rank").textContent = d.rank ? `#${d.rank} entre os favorecidos do mandato` : "";
  // grafias originais consolidadas na mesma identidade (CNPJ) — o total soma todas;
  // comparação normalizada (um espaço no fim não é outra grafia)
  const nn = Comum.nomeNormalizado;
  const outras = [...new Set((d.grafias || []).filter((g) => nn(g) !== nn(d.nome)))];
  const gEl = el("fav-grafias");
  if (gEl) gEl.textContent = outras.length ? `também grafado na origem como: ${outras.join(" · ")}` : "";
  if (d.atualizado_em)
    el("fav-atualizado").textContent = "atualizado " + new Date(d.atualizado_em).toLocaleDateString("pt-BR");

  // cards — "Em <ano>" é o ano corrente DA BASE (antes era o último ano do favorecido,
  // e quem só recebeu em 2025 aparecia como "Em 2025 — exercício corrente")
  const anoBase = +String(IDX_PAINEL?.dados_ate || d.atualizado_em || "").slice(0, 4) || null;
  const noAno = anoBase ? (d.por_ano?.[anoBase] || 0) : 0;
  const cards = [
    { rotulo: "Total no mandato", valor: compacto(d.total), sub: `${(d.qtd || 0).toLocaleString("pt-BR")} pagamentos` },
    { rotulo: `Em ${anoBase || "—"}`, valor: noAno ? compacto(noAno) : "—",
      sub: noAno ? "exercício corrente da base"
        : `sem pagamentos em ${anoBase}${d.ultimo_pagamento ? " · último em " + dataBR(d.ultimo_pagamento) : ""}` },
    { rotulo: "Presença", valor: `${d.meses || 0} meses`,
      sub: d.primeiro_pagamento ? `de ${dataBR(d.primeiro_pagamento)} a ${dataBR(d.ultimo_pagamento)}` : "com pagamento recebido" },
    alertasCard(d.alertas || []),
  ];
  el("stats").innerHTML = cards.map((c) =>
    `<div class="stat"><div class="rotulo">${esc(c.rotulo)}</div>
     <div class="valor">${esc(c.valor)}</div><div class="sub">${esc(c.sub)}</div></div>`).join("");

  renderGraficosFav(d);
  renderComposicao(d);
  renderGrafias(d);
  renderExterno(d);

  // alertas
  const alertas = d.alertas || [];
  if (alertas.length) {
    el("box-alertas").hidden = false;
    const classe = { contexto: "contexto", anomalia: "anomalia a conferir", inconsistencia: "inconsistência de dados" };
    const sev = { alta: "alta", media: "média", baixa: "baixa" };
    // o alerta de um favorecido costuma linkar para o próprio raio-X — não repetir a página atual
    const ehEstaPagina = (link) => d.slug && /[?&]f=([^&#]+)/.exec(link || "")?.[1] === d.slug;
    el("lista-alertas").innerHTML = alertas.map((a) => `
      <div class="alerta ${esc(a.severidade)} classe-${esc(a.classe || "anomalia")}">
        <span class="sev">${esc(sev[a.severidade] || a.severidade)}</span>${a.classe ? `<span class="sev classe">${esc(classe[a.classe] || a.classe)}</span>` : ""}<span class="tit">${esc(a.titulo)}</span>
        <div class="det">${esc(a.detalhe)}${a.link && !ehEstaPagina(a.link) ? ` <a href="${esc(a.link)}">Abrir o recorte ↗</a>` : ""}</div>
      </div>`).join("");
  }

  // últimos pagamentos: o título diz que é um recorte ("50 mais recentes de N")
  const ult = d.ultimos_pagamentos || [];
  el("box-pagamentos").hidden = !ult.length;
  el("tit-pagamentos").textContent = ult.length < (d.qtd || 0)
    ? `Últimos pagamentos — os ${ult.length} mais recentes de ${(d.qtd || 0).toLocaleString("pt-BR")}` : "Pagamentos";
  el("corpo-pagamentos").innerHTML = ult.map((p) => `
    <tr>
      <td data-label="Data">${esc(dataBR(p.data))}</td>
      <td data-label="Função">${esc(p.funcao || "")}</td>
      <td data-label="Elemento">${esc(p.elemento || "")}</td>
      <td data-label="Unidade">${esc(p.unidade || "")}</td>
      <td data-label="Tipo">${esc(p.tipo || "")}</td>
      <td data-label="Nº pagamento · empenho">${esc([p.pagamento, p.empenho].filter(Boolean).join(" · "))}</td>
      <td data-label="Valor" class="num${p.valor < 0 ? " neg" : ""}">${brlc(p.valor)}${p.valor < 0 ? " (estorno)" : ""}</td>
    </tr>`).join("");

  // navegação: voltar para quem trouxe (se veio do site) e ponte para o Detalhamento
  // filtrado pela IDENTIDADE (todas as grafias) nos meses em que recebeu
  if (document.referrer && new URL(document.referrer).origin === location.origin) {
    el("link-voltar").addEventListener("click", (e) => { e.preventDefault(); history.back(); });
  }
  if (d.chave && (d.serie_mensal || []).length) {
    const meses = d.serie_mensal.map((s) => `${s.ano}-${String(s.mes).padStart(2, "0")}`).join(",");
    el("link-detalhe").href = `./despesas.html?dv=mov&dm=${encodeURIComponent(meses)}&dfav=${encodeURIComponent(d.chave)}#detalhe`;
    el("link-detalhe").hidden = false;
  }
  el("link-painel").href = "./despesas.html?q=" + encodeURIComponent(d.nome) + "#favorecidos";
  el("carregando").hidden = true;
  el("stats-skel").hidden = true;
  el("conteudo").hidden = false;
}

// ── Arquivos mensais (execução e movimentação) ────────────────────────────────
// decodifica os arquivos de movimentação (colunas por dicionário → valores)
function decodificarParte(p) {
  if (!p || !p.dicionario) return p;
  const idx = Object.keys(p.dicionario).map((c) => [p.campos.indexOf(c), p.dicionario[c]]);
  return { campos: p.campos, linhas: p.linhas.map((r) => {
    const o = r.slice();
    for (const [i, dic] of idx) o[i] = dic[o[i]];
    return o;
  }) };
}

// baixa os arquivos com progresso; um mês fora do ar não descarta os outros, mas a
// falha é declarada (e.falhas) para a pessoa tentar de novo
async function baixarMeses(manifesto, versao, aoBaixar) {
  let feitos = 0;
  const res = await Promise.allSettled(manifesto.map((m) =>
    fetch("./" + m.arquivo + "?v=" + (versao || ""))
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((p) => { feitos += 1; if (aoBaixar) aoBaixar(feitos, manifesto.length); return decodificarParte(p); })));
  const falhas = manifesto.filter((m, i) => res[i].status === "rejected");
  if (falhas.length) {
    const e = new Error("falha");
    e.falhas = falhas.map((m) => `${m.ano}-${String(m.mes).padStart(2, "0")}`);
    throw e;
  }
  return res.map((x) => x.value);
}

let IND_FAV = null;   // dados/indice-favorecidos.json (identidade → meses)
async function mesesDoFavorecido(chave, visao) {
  const idx = await indicePainel();
  const manifesto = (visao === "mov" ? idx.meses_movimento : idx.meses) || [];
  if (IND_FAV === null) {
    try {
      const r = await fetch("./despesas/dados/indice-favorecidos.json?v=" + (idx.atualizado_em || ""));
      IND_FAV = r.ok ? await r.json() : false;
    } catch (e) { IND_FAV = false; }
  }
  // índice v2 é por identidade; ausente = presente em quase todos os meses → todos
  const ms = IND_FAV && IND_FAV.versao === 2 ? IND_FAV[visao === "mov" ? "mov" : "fav"]?.[chave] : null;
  if (!ms) return manifesto;
  const quer = new Set(ms);
  return manifesto.filter((m) => quer.has(m.ano * 100 + m.mes));
}
const mb = (bytes) => (bytes / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " MB";
const LIMITE_AUTO = 3e6;   // até ~3 MB baixa sozinho; acima, a pessoa decide

// ── Lançamentos de execução (empenhado/liquidado/pago, todos os meses) ────────
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

// Identidade canônica (Comum.identidadeFavorecido = espelho de formato.identidade_favorecido):
// CNPJ completo reúne todas as grafias; CPF mascarado só com o mesmo nome.
function casaFavorecido(nome, doc, chave) {
  const ident = Comum.identidadeFavorecido;
  const nn = Comum.nomeNormalizado;
  if (chave) return (n, d) => ident(n, d) === chave;
  if (doc) return (n, d) => (d || "") === doc;
  const alvo = nn(nome);
  return (n, d) => nn(n) === alvo;
}

async function prepararLancamentos(nome, doc, chave) {
  const idx = await indicePainel();
  const manifesto = await mesesDoFavorecido(chave, "exe");
  const bytes = manifesto.reduce((s, m) => s + (m.bytes || 0), 0);
  const carregar = () => carregarLancamentos(manifesto, idx, nome, doc, chave);
  if (bytes <= LIMITE_AUTO || !bytes) return carregar();
  // presente em quase todos os meses (Município, IPS, grandes contratos): baixar tudo
  // passa de 10 MB — a pessoa decide, sabendo o tamanho
  el("lanc-carregando").textContent =
    `Os lançamentos deste favorecido estão em ${manifesto.length} meses (≈ ${mb(bytes)}).`;
  const b = el("lanc-carregar");
  b.textContent = `Carregar lançamentos (${manifesto.length} meses, ≈ ${mb(bytes)})`;
  b.hidden = false;
  b.onclick = () => { b.hidden = true; carregar(); };
}

async function carregarLancamentos(manifesto, idx, nome, doc, chave) {
  const aviso = el("lanc-carregando");
  aviso.hidden = false;
  aviso.textContent = `Baixando 0/${manifesto.length} meses…`;
  try {
    const partes = await baixarMeses(manifesto, idx.atualizado_em,
      (k, n) => { aviso.textContent = `Baixando ${k}/${n} meses…`; });
    const campos = partes[0]?.campos || [];
    const iN = campos.indexOf("nome_favorecido"), iD = campos.indexOf("documento_favorecido");
    const casa = casaFavorecido(nome, doc, chave);
    iniciarLancamentos(campos, partes.flatMap((p) => p.linhas).filter((r) => casa(r[iN], r[iD])));
  } catch (e) {
    console.warn("lançamentos:", e);
    Comum.estadoErro(aviso, e.falhas?.length
      ? `Não foi possível baixar ${e.falhas.join(", ")}. Tente de novo.`
      : "Falha ao carregar os lançamentos de execução. Verifique a conexão.",
      () => carregarLancamentos(manifesto, idx, nome, doc, chave));
  }
}

function renderLancCabecalho() {
  const tr = el("lanc-cabecalho");
  tr.innerHTML = LANC_COLS.map((c) => {
    const i = lanc.campos.indexOf(c);
    const ordenada = lanc.sort.idx === i;
    const seta = ordenada ? (lanc.sort.dir === "asc" ? " ▲" : " ▼") : "";
    const aria = ordenada ? ` aria-sort="${lanc.sort.dir === "asc" ? "ascending" : "descending"}"` : "";
    // dica de ordenação no title: aria-label no <th> substituía o nome da coluna ao ler as células
    return `<th data-idx="${i}"${LANC_NUM.has(c) ? ' style="text-align:right"' : ""}${aria} ` +
      `tabindex="0" role="columnheader" title="Ordenar por ${LANC_LABELS[c]}">${LANC_LABELS[c]}${seta}</th>`;
  }).join("");
  // ordenável por teclado; o foco volta ao <th> depois de o cabeçalho ser reconstruído
  const ordenar = (th) => {
    const i = +th.dataset.idx;
    lanc.sort.dir = lanc.sort.idx === i && lanc.sort.dir === "desc" ? "asc" : "desc";
    lanc.sort.idx = i; lanc.pag = 1;
    renderLancCabecalho(); renderLancTabela();
    tr.querySelector(`th[data-idx="${i}"]`)?.focus();
  };
  tr.querySelectorAll("th").forEach((th) => {
    th.addEventListener("click", () => ordenar(th));
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ordenar(th); }
    });
  });
}

// Faixa de conciliação: recebido (pagamentos em nome do favorecido) × pago sob os
// empenhos DELE (execução). A diferença tem causas conhecidas — dizer quais.
function renderConciliacao(somaPagoExe) {
  const d = DOSSIE;
  if (!d || !d.total) return;
  const dif = d.total - somaPagoExe;
  const box = el("lanc-conc");
  el("lanc-conc-nota")?.remove();
  box.innerHTML =
    `<div><small>Recebido (pagamentos em nome dele)</small><b>${compacto(d.total)}</b></div>` +
    `<div><small>Pago sob empenhos dele (abaixo)</small><b>${compacto(somaPagoExe)}</b></div>` +
    `<div><small>Diferença</small><b>${compacto(dif)}</b></div>`;
  box.hidden = false;
  if (Math.abs(dif) > 0.01 * Math.abs(d.total))
    box.insertAdjacentHTML("afterend", `<p class="nota" id="lanc-conc-nota">A diferença ${dif > 0 ? "a mais no recebido" : "a mais na execução"} ` +
      "vem, em geral, de retenções e consignações pagas a ele sob empenhos de terceiros (IRRF e contribuições da " +
      "folha, p. ex.), de pagamentos extra-orçamentários sem empenho e de restos a pagar de empenhos anteriores a " +
      "2025 — que não geram linha de execução na base.</p>");
}

function renderLancTabela() {
  const { campos, rows, sort } = lanc;
  const numerico = LANC_NUM.has(campos[sort.idx]);
  const dir = sort.dir === "asc" ? 1 : -1;
  rows.sort((a, b) => numerico
    ? ((a[sort.idx] ?? 0) - (b[sort.idx] ?? 0)) * dir
    : String(a[sort.idx] ?? "").localeCompare(String(b[sort.idx] ?? "")) * dir);

  const soma = (c) => rows.reduce((s, r) => s + (r[campos.indexOf(c)] ?? 0), 0);
  // "linhas", não "empenhos": pagamentos sem empenho na base viram pseudo-empenhos
  el("lanc-resumo").textContent =
    `${rows.length.toLocaleString("pt-BR")} linha(s) de execução · Empenhado ${compacto(soma("empenhado"))} · ` +
    `Liquidado ${compacto(soma("liquidado"))} · Pago ${compacto(soma("pago"))}`;

  const totalPag = Math.max(1, Math.ceil(rows.length / LANC_PAGINA));
  lanc.pag = Math.min(Math.max(1, lanc.pag), totalPag);
  const pagina = rows.slice((lanc.pag - 1) * LANC_PAGINA, lanc.pag * LANC_PAGINA);
  el("lanc-corpo").innerHTML = pagina.map((r) => "<tr>" + LANC_COLS.map((c) => {
    const v = r[campos.indexOf(c)];
    const lbl = ` data-label="${LANC_LABELS[c]}"`;
    if (LANC_NUM.has(c)) {
      if (v == null) return `<td class="num"${lbl} style="color:var(--muted)">—</td>`;
      return `<td class="num${v < 0 ? " neg" : ""}"${lbl}>${brlc(v)}</td>`;
    }
    return `<td${lbl} title="${esc(v ?? "")}">${esc(v ?? "")}</td>`;
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
  renderConciliacao(rows.reduce((s, r) => s + (r[campos.indexOf("pago")] ?? 0), 0));
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

// ── Rota 2: qualquer favorecido (?doc=&nome=) ─────────────────────────────────
// Resolve a IDENTIDADE (a mesma chave do export) e monta o dossiê com os PAGAMENTOS
// reais (movimentação, pela data do pagamento) — antes a série vinha da execução,
// pela data do empenho, e "N pagamentos" contava empenhos.
let NOMES = null;   // dados/nomes-favorecidos.json: chave → [nome, documento]
async function nomesFavorecidos(idx) {
  if (!NOMES) {
    const r = await fetch("./despesas/dados/nomes-favorecidos.json?v=" + (idx.atualizado_em || ""));
    if (!r.ok) throw new Error("HTTP " + r.status);
    NOMES = await r.json();
  }
  return NOMES;
}

// → { chave } | { candidatos: [[chave, nome, doc]…] } | { erro }
async function resolverIdentidade(nome, doc, idx) {
  const dig = soDigitos(doc);
  if (dig.length === 14 && !doc.includes("*")) return { chave: "cnpj:" + dig };
  if (doc.includes("*") && !nome)   // CPF mascarado sozinho não identifica uma pessoa
    return { erro: "CPF mascarado (***.123.456-**) não identifica uma pessoa sozinho — informe também o nome." };
  if (doc && nome) return { chave: Comum.identidadeFavorecido(nome, doc) };
  const nomes = await nomesFavorecidos(idx);
  const alvo = Comum.nomeNormalizado(nome || "");
  const lista = Object.entries(nomes);
  let achados = lista.filter(([, [n, d]]) => Comum.nomeNormalizado(n) === alvo && (!doc || d === doc));
  if (!achados.length && alvo.length >= 4)   // sem nome exato: quem CONTÉM o termo
    achados = lista.filter(([, [n]]) => Comum.nomeNormalizado(n).includes(alvo)).slice(0, 30);
  if (achados.length === 1) return { chave: achados[0][0] };
  if (!achados.length) return { erro: "Nenhum favorecido com esse nome na base do mandato." };
  return { candidatos: achados.map(([k, [n, d]]) => [k, n, d]) };
}

function dossieDosPagamentos(chave, campos, rows, idx) {
  const i = (c) => campos.indexOf(c);
  const iData = i("data"), iP = i("pago"), iF = i("funcao"), iE = i("elemento_despesa"), iU = i("unidade_gestora"),
        iT = i("tipo"), iN = i("nome_favorecido"), iD = i("documento_favorecido"), iDoc = i("documento"), iEmp = i("empenho");
  const porMes = new Map(), porFn = new Map(), porEl = new Map(), porUg = new Map(), porTipo = new Map(), porNome = new Map();
  const soma = (m, k, v) => m.set(k, (m.get(k) || 0) + v);
  const porAno = {};
  let total = 0;
  for (const r of rows) {
    const v = r[iP] || 0, dt = String(r[iData] || "");
    total += v;
    soma(porMes, dt.slice(0, 7), v);
    porAno[dt.slice(0, 4)] = (porAno[dt.slice(0, 4)] || 0) + v;
    soma(porFn, r[iF] || "(sem função)", v);
    soma(porEl, r[iE] || "(não informado)", v);
    soma(porUg, r[iU] || "(não informado)", v);
    const t = porTipo.get(r[iT]) || { valor: 0, qtd: 0 };
    t.valor += v; t.qtd += 1; porTipo.set(r[iT], t);
    const g = porNome.get(r[iN]) || { valor: 0, qtd: 0, primeiro: dt, ultimo: dt };
    g.valor += v; g.qtd += 1; if (dt < g.primeiro) g.primeiro = dt; if (dt > g.ultimo) g.ultimo = dt;
    porNome.set(r[iN], g);
  }
  const ord = (m) => [...m.entries()].sort((a, b) => b[1] - a[1]);
  const datas = rows.map((r) => String(r[iData] || "")).filter(Boolean).sort();
  const nomeExib = [...porNome.entries()].sort((a, b) => b[1].qtd - a[1].qtd)[0]?.[0] || "(sem nome)";
  const recentes = [...rows].sort((a, b) => String(b[iData]).localeCompare(String(a[iData])) || (b[iP] - a[iP])).slice(0, 50);
  return {
    nome: nomeExib, documento: rows[0]?.[iD] || "", chave,
    grafias: [...porNome.keys()], rank: null, total, qtd: rows.length, meses: porMes.size, por_ano: porAno,
    serie_mensal: [...porMes.keys()].sort().map((k) => ({ ano: +k.slice(0, 4), mes: +k.slice(5, 7), valor: porMes.get(k) })),
    por_funcao: ord(porFn).slice(0, 6).map(([funcao, valor]) => ({ funcao, valor })),
    por_elemento: ord(porEl).slice(0, 8).map(([elemento, valor]) => ({ elemento, valor, participacao_pct: null })),
    por_unidade: ord(porUg).map(([unidade, valor]) => ({ unidade, valor })),
    por_tipo: [...porTipo.entries()].sort((a, b) => b[1].valor - a[1].valor)
      .map(([tipo, t]) => ({ tipo: tipo || "(não informado)", valor: t.valor, qtd: t.qtd })),
    grafias_detalhe: porNome.size > 1 ? [...porNome.entries()].map(([nome, g]) => ({ nome, ...g })) : undefined,
    primeiro_pagamento: datas[0] || null, ultimo_pagamento: datas[datas.length - 1] || null,
    ultimos_pagamentos: recentes.map((r) => ({ data: r[iData], valor: r[iP], funcao: r[iF], elemento: r[iE],
      unidade: r[iU], tipo: r[iT], pagamento: r[iDoc], empenho: r[iEmp] })),
    alertas: (idx.alertas || []).filter((a) => (a.filtro || {}).chave === chave),
    ente_publico: (idx.entes_publicos || []).includes(chave),
    atualizado_em: idx.atualizado_em,
  };
}

async function rotaPorDocumento(nome, doc) {
  const idx = await indicePainel();
  const id = await resolverIdentidade(nome, doc, idx);
  if (id.erro) return falha(id.erro);
  if (id.candidatos) {   // nome ambíguo: a pessoa escolhe
    el("stats-skel").hidden = true;
    el("fav-nome").textContent = `${id.candidatos.length} favorecidos com “${nome}”`;
    el("carregando").innerHTML = "<p>Escolha um:</p><ul style='text-align:left;display:inline-block'>" +
      id.candidatos.map(([k, n, d]) => `<li><a href="./favorecido.html?doc=${encodeURIComponent(d)}&nome=${encodeURIComponent(n)}">` +
        `${esc(n)}</a> <span style="color:var(--muted)">${esc(d)}</span></li>`).join("") + "</ul>";
    return;
  }
  const chave = id.chave;
  // CNPJ com dossiê pré-computado (top-300): a rota 1 é mais completa
  if (chave.startsWith("cnpj:")) {
    const slug = chave.slice(5);
    const r = await fetch(`./favorecidos/${slug}.json`, { method: "HEAD", cache: "no-cache" }).catch(() => null);
    if (r?.ok) { location.replace(`./favorecido.html?f=${slug}`); return; }
  }
  const manifesto = await mesesDoFavorecido(chave, "mov");
  const bytes = manifesto.reduce((s, m) => s + (m.bytes || 0), 0);
  const montar = async () => {
    el("carregando").textContent = `Baixando 0/${manifesto.length} meses de pagamentos…`;
    const partes = await baixarMeses(manifesto, idx.atualizado_em,
      (k, n) => { el("carregando").textContent = `Baixando ${k}/${n} meses de pagamentos…`; });
    const campos = partes[0]?.campos || [];
    const iN = campos.indexOf("nome_favorecido"), iD = campos.indexOf("documento_favorecido"), iF = campos.indexOf("fase");
    const casa = casaFavorecido(nome, doc, chave);
    const pags = partes.flatMap((p) => p.linhas).filter((r) => r[iF] === "P" && casa(r[iN], r[iD]));
    if (!pags.length) return falha("Nenhum pagamento encontrado para este favorecido na base do mandato.");
    render(dossieDosPagamentos(chave, campos, pags, idx));
    prepararLancamentos(nome, doc, chave);
  };
  if (bytes > 15e6) {   // identidade fora do índice leve: seriam todos os meses
    el("stats-skel").hidden = true;
    el("carregando").innerHTML = `Este favorecido aparece em quase todos os meses — montar a página baixa ` +
      `≈ ${esc(mb(bytes))}. <br><br><button class="btn" type="button" id="rota2-carregar">Carregar mesmo assim</button>`;
    el("rota2-carregar").onclick = () => montar().catch(erroRota2);
    return;
  }
  await montar();
}

function erroRota2(e) {
  console.warn("favorecido:", e);
  el("stats-skel").hidden = true;
  Comum.estadoErro("carregando", e.falhas?.length
    ? `Não foi possível baixar ${e.falhas.join(", ")}. Tente de novo.`
    : "Não foi possível montar a página deste favorecido agora.", init);
}

async function init() {
  const params = Comum.lerParams();
  const slug = (params.get("f") || "").trim();

  // rota 1: dossiê pré-computado do top-300 (?f=<slug>) + lançamentos sob demanda
  if (/^[0-9a-f]{6,20}$/i.test(slug)) {
    let d;
    try {
      // o índice dá meses parciais, período e ano da base; se falhar, a página sai sem eles
      const [r] = await Promise.all([fetch(`./favorecidos/${slug}.json`, { cache: "no-cache" }),
                                     indicePainel().catch(() => null)]);
      if (!r.ok) throw new Error("HTTP " + r.status);
      d = await r.json();
      render(d);
    } catch (e) {
      console.warn("favorecido:", e.message);
      // 404 é "não existe" (fora do top-300); o resto é rede — merece "Tentar de novo"
      if (/HTTP 404/.test(e.message)) {
        return falha("Dossiê não encontrado — ele cobre os 300 maiores favorecidos e é regerado diariamente.");
      }
      el("stats-skel").hidden = true;
      return Comum.estadoErro("carregando", "Não foi possível carregar o dossiê agora. Verifique a conexão.", init);
    }
    prepararLancamentos(d.nome, d.documento || "", d.chave).catch((e) => {
      console.warn("lançamentos:", e);
      Comum.estadoErro("lanc-carregando", "Falha ao carregar os lançamentos de execução.",
        () => prepararLancamentos(d.nome, d.documento || "", d.chave));
    });
    return;
  }

  // rota 2: qualquer favorecido por documento e/ou nome (?doc=&nome=)
  const doc = (params.get("doc") || "").trim();
  const nome = (params.get("nome") || "").trim();
  if (!doc && !nome) return falha("Endereço inválido ou sem favorecido indicado.");
  try {
    await rotaPorDocumento(nome, doc);
  } catch (e) {
    erroRota2(e);
  }
}

init();
