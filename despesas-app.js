// Radar de Despesas — painel (vanilla + ECharts via Comum.grafico)
// Consome despesas-index.json (agregado, gerado por despesas/export.py).

const MESES = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
               "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
// gráficos pela camada comum (Comum.grafico, ECharts): tema, troca de tema, celular e
// biblioteca fora do ar (aviso com "Tentar de novo" no lugar do gráfico) são tratados
// lá; aqui só as séries e as regras de leitura do painel.

// Um gráfico com dado inesperado não pode derrubar o resto do painel — abas,
// alertas, favorecidos, Detalhamento têm de continuar funcionando
function renderGraficosSeguro() {
  try { renderGraficos(); } catch (e) { console.warn("gráficos:", e); }
}

let DADOS = null;
let favSort = { col: "valor", dir: "desc" };

// botões de alternância: .primario (visual) + aria-pressed (leitor de tela anuncia qual está ativo)
function marcarAlternancia(seletor, ativo) {
  document.querySelectorAll(seletor).forEach(x => {
    const on = !!ativo(x);
    x.classList.toggle("primario", on);
    x.setAttribute("aria-pressed", on);
  });
}

// ── Formatação ───────────────────────────────────────────────────────────────
// camada comum: uma escala de moeda para o site inteiro (R$ 8,61 bi · R$ 157,0 mi)
const brl = Comum.brl;
const brlc = (v) => Comum.brl(v, 2);
const compacto = Comum.compacto;
const esc = Comum.escapar;   // era função local no fim do arquivo (e "null" virava texto)

// ── Inicialização ────────────────────────────────────────────────────────────
async function init() {
  try {
    const r = await fetch("./despesas-index.json", { cache: "no-cache" });
    DADOS = await r.json();
  } catch (e) {
    // sem dado, sem esqueleto eterno
    document.getElementById("hero-num").hidden = document.getElementById("em-resumo").hidden = true;
    Comum.estadoErro("stats",
      "Não foi possível carregar os dados de despesas. Verifique a conexão.", init);
    return;
  }
  renderHero();
  renderStats();
  renderResumo();
  renderGraficosSeguro();
  renderR100();
  renderRecibo();
  renderAnalises();   // prazos, anulações, fim de exercício (tabelas; os gráficos vêm com os demais)
  ligarVistaFuncao();
  initMapa();   // treemap (assíncrono; degrada se arvore.json/plugin faltarem)
  initPares();  // benchmark SICONFI (assíncrono; degrada se benchmark.json faltar)
  initGraficosMovimento();   // M8: Mensal | Diário, calendário e caminho do dinheiro
  popularFiltrosAlertas();
  ligarAlertas();   // restaura filtros da URL e renderiza
  // deep-link de busca (paleta ⌘K / links externos): ?q= pré-preenche favorecidos
  const qIni = new URLSearchParams(location.search).get("q");
  if (qIni) document.getElementById("q").value = qIni;
  renderFavoridosTabela();
  renderSeletorMeses();
  ligarAbas();
  // deep-link de aba: despesas.html#alertas / #favorecidos / #detalhe
  const aba = location.hash.replace("#", "");
  selecionarAba(ABAS.includes(aba) ? aba : "geral");   // também tira as abas inativas do Tab
  // links para a própria página (paleta Ctrl+K "#detalhe", rodapé) trocam de aba sem recarregar
  addEventListener("hashchange", () => {
    const h = location.hash.replace("#", "");
    if (!ABAS.includes(h)) return;
    selecionarAba(h);
    document.querySelector(".tabs")?.scrollIntoView({ block: "start", behavior: "smooth" });
  });
  ligarBusca();
  ligarOrdenacao();
  ligarModosFav();
  // estado inicial dos grupos de alternância (o HTML só marca a classe .primario)
  ["#fn-vista button", "#fav-modos button", "#det-metrica button"].forEach(s =>
    marcarAlternancia(s, x => x.classList.contains("primario")));
  ligarDetalhe();
  ligarFichaEmpenho();
  // consulta citável: ?dm=… restaura meses+filtros do Detalhamento e auto-carrega
  const pURL = Comum.lerParams();
  definirVisao(pURL.get("dv") || "exe");   // redesenha o seletor de meses se a visão for "mov"
  if (pURL.get("dm")) aplicarEstadoURL(pURL);
  renderCobertura();

  const at = DADOS.atualizado_em ? new Date(DADOS.atualizado_em).toLocaleString("pt-BR") : "";
  const ate = DADOS.dados_ate
    ? " O portal publica com defasagem: pagamentos até " +
      new Date(DADOS.dados_ate.slice(0, 10) + "T12:00:00").toLocaleDateString("pt-BR") + "."
    : "";
  document.getElementById("atualizado").textContent = (at ? "Atualizado em " + at + "." : "") + ate;
}

// Cobertura da base por partição (fonte × mês): o que falta, o que falhou e o que
// veio em duplicidade sistemática na origem — substitui a confiança cega no total.
function renderCobertura() {
  const cob = DADOS.cobertura, el = document.getElementById("cobertura");
  if (!cob || !el) return;
  const n = (cob.particoes || []).length;
  const partes = [`Cobertura: ${n} partições (estágio × mês) carregadas`];
  if (cob.faltantes?.length) partes.push(`${cob.faltantes.length} sem carga: ${cob.faltantes.slice(0, 4).join(", ")}${cob.faltantes.length > 4 ? "…" : ""}`);
  if (cob.com_erro?.length) partes.push(`${cob.com_erro.length} com falha na última coleta (versão anterior mantida)`);
  if (cob.duplicidade_sistematica?.length)
    partes.push(`${cob.duplicidade_sistematica.length} devolvidas pela origem em duplicidade sistemática (linhas idênticas contadas uma vez — ver Alertas › Inconsistência de dados)`);
  if (DADOS.conservacao && !DADOS.conservacao.ok) partes.push("ATENÇÃO: soma da execução ≠ soma da movimentação (conservação falhou)");
  el.textContent = partes.join(" · ") + ".";
}

// ── Cards ────────────────────────────────────────────────────────────────────
const POP_SANTOS = (window.Comum && Comum.POP_SANTOS) || 418608; // IBGE, Censo 2022 definitivo

function deltaHTML(pct, rotulo) {
  if (pct == null) return "";
  const pos = pct >= 0;
  return ` <span class="delta ${pos ? "pos" : "neg"}" title="${esc(rotulo)}">` +
    `${pos ? "▲" : "▼"} ${Math.abs(pct)}%</span>`;
}

// Meses que a origem ainda está publicando (resumo.meses_parciais, "AAAA-MM"):
// ficam fora de comparações e aparecem tracejados nos gráficos.
function mesParcial(ano, mes) {
  return (DADOS.resumo?.meses_parciais || []).includes(`${ano}-${String(mes).padStart(2, "0")}`);
}

function renderStats() {
  const t = DADOS.totais, p = DADOS.periodo, r = DADOS.resumo;
  const anos = Object.keys(t.por_ano || {}).sort();
  const ultimoAno = anos[anos.length - 1];
  const perCapita = t.geral / POP_SANTOS;
  const yoy = r?.yoy, mr = r?.mes_ref; // acumulado jan–mês de referência vs mesmo período do ano anterior
  const per = mr ? `jan–${MESES[mr.mes].toLowerCase()}` : "";
  const cardAno = yoy && mr
    ? { rotulo: `Acumulado ${per}/${mr.ano}`,
        valor: compacto(yoy.atual) + deltaHTML(yoy.pct, `vs ${per}/${mr.ano - 1}`),
        sub: `vs ${compacto(yoy.anterior)} em ${per}/${mr.ano - 1}` +
             (r.meses_parciais?.length ? " · meses parciais fora" : "") }
    : { rotulo: `Total em ${ultimoAno || "—"}`, valor: compacto(t.por_ano?.[ultimoAno] || 0),
        sub: "exercício corrente" };
  // "2025-01" → "jan/2025"
  const mesAno = (s) => s ? `${MESES[+s.slice(5, 7)].toLowerCase()}/${s.slice(0, 4)}` : "—";
  const nConferir = (DADOS.alertas || []).filter(aConferir).length;
  const cards = [
    { rotulo: "Total no período", valor: compacto(t.geral),
      sub: `${mesAno(p.de)} a ${mesAno(p.ate)} · ≈ ${brl(perCapita)} por santista` },
    cardAno,
    // o card que responde "e agora?": o último mês fechado contra o ritmo recente
    mr ? { rotulo: `Pago em ${MESES[mr.mes].toLowerCase()}/${mr.ano}`,
           valor: compacto(mr.valor) + deltaHTML(r.delta_media_pct, "vs média dos 12 meses anteriores"),
           sub: "último mês completo · vs média de 12 meses" }
       : { rotulo: "Pagamentos", valor: t.pagamentos.toLocaleString("pt-BR"), sub: "registros" },
    { rotulo: "Alertas a conferir",
      valor: `<a href="#alertas" class="stat-link">${nConferir.toLocaleString("pt-BR")}</a>`,
      sub: "anomalias e inconsistências → ver" },
  ];
  document.getElementById("stats").innerHTML = cards.map(c =>
    `<div class="stat"><div class="rotulo">${c.rotulo}</div>
     <div class="valor">${c.valor}</div><div class="sub" title="${esc(c.sub)}">${c.sub}</div></div>`).join("");
}

// "Em resumo" — narrativa determinística gerada pelo export (DADOS.resumo)
// A caixa nasce visível com a altura reservada (despesas.html); o texto, em Fraunces,
// só é escrito com a fonte carregada (senão troca de linha ao vê-la chegar — CLS).
function renderResumo() {
  const box = document.getElementById("em-resumo");
  if (!box) return;
  box.hidden = !DADOS.resumo?.texto;
  if (box.hidden) return;
  const t = box.querySelector(".resumo-texto");
  Comum.quandoFonte(['400 20px "Fraunces"', '600 20px "Fraunces"'], () => {
    t.innerHTML = Comum.destacarNumeros(DADOS.resumo.texto);
    t.classList.remove("resumo-reserva");
    t.removeAttribute("aria-hidden");
    // celular: o resumo fica no topo, recolhido em 5 linhas (comum.css); o botão nasce
    // reservado e só some se o texto couber
    const mais = document.getElementById("resumo-mais");
    if (mais && t.scrollHeight <= t.clientHeight + 2) mais.hidden = true;
    else if (mais) {
      mais.onclick = () => {
        const aberto = t.classList.toggle("aberto");
        mais.setAttribute("aria-expanded", String(aberto));
        mais.textContent = aberto ? "Menos ▴" : "Ler o resumo inteiro ▾";
      };
    }
  });
}

// ── Hero: número-manchete — o acumulado do ano (o mesmo do "Em resumo") ──────
// Montado com nós (texto do export não vira HTML). Sem acumulado comparável,
// fica o último mês fechado; sem resumo, o bloco some. Escrito com as fontes já
// carregadas (Comum.quandoFonte): antes disso a frase trocava de linha — CLS.
function renderHero() {
  const r = DADOS.resumo, mr = r?.mes_ref;
  const caixa = document.getElementById("hero-num");
  const grande = document.getElementById("hero-grande"), ctx = document.getElementById("hero-contexto");
  caixa.hidden = !mr;
  if (!mr) return;
  const mes = new Date(mr.ano, mr.mes - 1, 1).toLocaleDateString("pt-BR", { month: "long" });
  Comum.quandoFonte(Comum.FACES_MANCHETE, () => {
    if (r.yoy) {
      grande.textContent = compacto(r.yoy.atual);
      const b = document.createElement("b");
      b.textContent = `${Math.abs(r.yoy.pct)}% ${r.yoy.pct >= 0 ? "acima" : "abaixo"}`;
      ctx.replaceChildren(`pagos pela Prefeitura em ${mr.ano}, de janeiro a ${mes} — `, b,
        ` do mesmo período de ${mr.ano - 1}.`);
    } else {
      grande.textContent = compacto(mr.valor);
      ctx.textContent = `pagos pela Prefeitura em ${mes} de ${mr.ano}, o último mês completo.`;
    }
  });
}

// ── Gráficos (Comum.grafico, ECharts) ────────────────────────────────────────
// Cada gráfico é desenhado quando chega perto da tela — numa aba oculta, quando ela
// aparece. Valor na dica com centavos (brlc), eixo compacto (Comum.compactoEixo).
const rotuloMes = (x) => `${MESES[x.mes]}/${String(x.ano).slice(2)}`;   // "Mar/25" (eixo)
const mesAno = (x) => `${MESES[x.mes]}/${x.ano}`;                        // "Mar/2025" (dica)
const NOTA_PARCIAL = "Mês parcial — a origem ainda está publicando.";
// eixo dos meses nas caixas largas: todos os rótulos, como antes (o "*" do mês parcial
// aparece); os que não couberem somem. No celular, um a cada quatro meses.
const EIXO_MESES = (p) => ({ hideOverlap: true, interval: p.celular ? 3 : 0, margin: 10 });
// cinza da linha de referência (empenhado): #93a0b3 nos dois temas — o `ref` do claro
// é o `muted` do escuro (o `ref` escuro, #5d6675, some numa linha tracejada fina)
const cinzaLinha = (p) => (Comum.temaAtual() === "escuro" ? p.muted : p.ref);
// as 8 cores da rosca (fonte de recurso): navy e dourado do tema + as categóricas que o
// painel já usava; a 8ª (vermelho) é também a das anulações
const coresCategorias = (p) => [p.serie, p.ouro, "#8d9aad", "#5b8def", "#e08a3c", "#2fa79a", "#a78bfa", "#e0564a"];

// Desvio de cada mês vs a média dos até 12 meses anteriores (null = sem base p/ comparar)
function desviosSerie(serie) {
  return serie.map((s, i) => {
    const ant = serie.slice(Math.max(0, i - 12), i);
    if (ant.length < 3) return null;
    const media = ant.reduce((t, x) => t + x.valor, 0) / ant.length;
    return Math.round((s.valor - media) / media * 100);
  });
}

// Linha mensal com meses parciais no fim: duas séries com o MESMO nome (a legenda liga
// e desliga as duas) — os meses completos e o trecho que sai do último mês completo e
// entra nos parciais (tracejado, ponto vazado). "-" = sem ponto (lacuna do ECharts).
function dividirParciais(valores, parcial) {
  const ini = parcial.indexOf(true);
  const de = ini > 0 ? ini - 1 : ini;   // o trecho parte do último mês completo
  return {
    completo: valores.map((v, i) => (parcial[i] || v == null ? "-" : v)),
    parcial: valores.map((v, i) => (ini >= 0 && i >= de && v != null
      ? (i === de && i !== ini ? { value: v, symbol: "none" } : v) : "-")),
  };
}

// Eixo de valor das barras deitadas: até `n` intervalos (os que cabem na largura útil,
// ~80 px por intervalo para o rótulo "R$ 1,5 bi") com passo redondo (1, 2, 2,5, 3, 4, 5,
// 6 ou 8 × 10^k) e o teto mais justo; no empate, mais intervalos. O padrão do ECharts
// esticava o teto (R$ 15.000 para um máximo de R$ 11.139) e, na caixa estreita, os
// rótulos encavalados sumiam. Abaixo de ~140 px úteis só as pontas ganham rótulo.
// Devolve [opção do eixo, margem direita do grid]: o rótulo do teto fica centrado no
// traço e o `containLabel` não o conta — sem a margem ele saía cortado ("R$ 1,75 l").
function eixoValor(maximo, util, fmt) {
  const n = Math.max(2, Math.min(8, Math.floor(util / 80)));
  let esc = { min: 0 };
  if (maximo > 0) {
    const ordem = Math.pow(10, Math.floor(Math.log10(maximo / n)));
    for (const m of [1, 2, 2.5, 3, 4, 5, 6, 8, 10, 20]) {
      const passo = m * ordem, k = Math.ceil(maximo / passo - 1e-9);
      if (k <= n && (!esc.max || k * passo < esc.max)) esc = { min: 0, max: k * passo, interval: passo };
    }
  }
  const soPontas = util < 140 && esc.max;
  const direita = Math.ceil(String(fmt(esc.max ?? maximo)).length * 3.4) + 8;   // meia largura (Plex Mono 11 px)
  return [{ type: "value", ...esc,
    axisLabel: { formatter: soPontas ? (v) => (v === 0 || Math.abs(v - esc.max) < esc.interval / 1e6 ? fmt(v) : "") : fmt,
      hideOverlap: true } }, direita];
}

// Barras deitadas, maior em cima (programa, função, unidade gestora, cidades pares).
// `cores`: uma cor ou uma por barra; `dica(i)`: HTML da dica da barra i. Depende da
// largura (a escala do eixo): registrar com `dependeDaLargura: true`.
function opcaoBarrasDeitadas(p, larg, { nomes, valores, cores, dica, eixo = (v) => Comum.compactoEixo(v),
                                        largRotulo = 230, largRotuloCel = 120 }) {
  const porBarra = Array.isArray(cores);
  const largNomes = Math.min(p.celular ? largRotuloCel : largRotulo, 7 * Math.max(...nomes.map(n => String(n).length)));
  const [eixoX, direita] = eixoValor(Math.max(...valores), larg - largNomes - 40, eixo);
  return {
    grid: { left: 4, right: direita, top: 6, bottom: 4, containLabel: true },
    tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" }, formatter: (ps) => dica(ps[0].dataIndex) },
    xAxis: eixoX,
    yAxis: { type: "category", inverse: true, data: nomes,
      axisLabel: { width: p.celular ? largRotuloCel : largRotulo, overflow: "truncate" } },
    series: [{ type: "bar", barMaxWidth: 22,
      data: porBarra ? valores.map((v, i) => ({ value: v, itemStyle: { color: cores[i] } })) : valores,
      itemStyle: { ...(porBarra ? {} : { color: cores }), borderRadius: [0, 3, 3, 0] } }],
  };
}

function renderGraficos() {
  // Série mensal — pontos fora do padrão (>±25% da média dos 12 meses anteriores)
  // ganham destaque; a média móvel 3m dá a tendência sem o serrilhado dos pagamentos.
  const serie = DADOS.series_mensais;
  const parcial = serie.map(s => mesParcial(s.ano, s.mes));
  const desvios = desviosSerie(serie).map((d, i) => parcial[i] ? null : d);
  const anomalo = desvios.map(d => d != null && Math.abs(d) > 25);
  const mm3 = serie.map((s, i) => i < 2 || parcial[i] ? null :
    (serie[i - 2].valor + serie[i - 1].valor + s.valor) / 3);
  const trechos = dividirParciais(serie.map(s => s.valor), parcial);
  const dicaMensal = (i, p) => {
    const s = serie[i];
    const nota = parcial[i] ? "Mês parcial — a origem ainda está publicando; fora das comparações."
      : anomalo[i] ? `${desvios[i] > 0 ? "+" : ""}${desvios[i]}% vs média 12m — fora do padrão, ver aba Alertas.` : "";
    return Comum.dicaGrafico(mesAno(s) + (parcial[i] ? " (parcial)" : ""), [
      [p.serie, "Pago no mês", brlc(s.valor)],
      mm3[i] != null ? [p.ouroLinha, "Média móvel (3 m)", brlc(mm3[i])] : null,
    ], nota, parcial[i] || anomalo[i]);
  };

  // Equivalentes acessíveis: descrição conclusiva + tabela oculta por gráfico
  const ult = [...serie].reverse().find(s => !mesParcial(s.ano, s.mes));
  const nParciais = parcial.filter(Boolean).length;
  document.querySelectorAll(".nota-parcial").forEach(el => {
    el.hidden = !nParciais;
    el.textContent = "* Mês parcial: o portal publica com semanas de atraso — o trecho tracejado " +
                     "ainda vai subir e fica fora das comparações.";
  });
  // a escala Mensal (o gráfico abaixo) ou a Diária (M8, defDiario) — desenharMensal escolhe
  DEF_MENSAL = {
    eventos: ouvirZoomDiario,   // o mesmo contêiner troca de escala sem recriar o gráfico
    opcao: (p) => {
      const anel = { borderColor: p.card, borderWidth: 2 };
      return {
        grid: { left: 4, right: 20, top: p.celular ? 14 : 40, bottom: p.celular ? 40 : 6, containLabel: true },
        // a média móvel não tem marcador no gráfico: na legenda, só o traço
        legend: { data: ["Pago no mês", { name: "Média móvel (3 m)", itemStyle: { opacity: 0 } }],
          [p.celular ? "bottom" : "top"]: 0, left: 0, itemGap: 18, itemWidth: 22, itemHeight: 10 },
        tooltip: { trigger: "axis", confine: true, formatter: (ps) => dicaMensal(ps[0].dataIndex, p) },
        xAxis: { type: "category", data: serie.map((s, i) => rotuloMes(s) + (parcial[i] ? "*" : "")), boundaryGap: false,
          axisLabel: EIXO_MESES(p) },
        yAxis: { type: "value", min: 0, splitNumber: p.celular ? 4 : 5, axisLabel: { formatter: (v) => Comum.compactoEixo(v) } },
        series: [
          // showAllSymbol: no celular o ECharts some com marcadores que "não cabem" — e os
          // pontos fora do padrão (vermelho acima, âmbar abaixo da média) são dado
          { name: "Pago no mês", type: "line", smooth: 0.25, symbol: "circle", symbolSize: 7, showAllSymbol: true,
            clip: false, z: 4, emphasis: { scale: 1.5 },
            data: trechos.completo.map((v, i) => (v === "-" || !anomalo[i] ? v : { value: v, symbolSize: 11,
              itemStyle: { color: desvios[i] > 0 ? p.vermelho : p.amarelo, ...anel } })),
            lineStyle: { width: 2, color: p.serie }, itemStyle: { color: p.serie, ...anel },
            areaStyle: { color: p.serieFill } },
          { name: "Pago no mês", type: "line", data: trechos.parcial, smooth: 0.25, symbol: "circle", symbolSize: 8,
            showAllSymbol: true, clip: false, z: 3,
            lineStyle: { width: 2, type: [4, 4], color: p.serie },
            itemStyle: { color: p.card, borderColor: p.serie, borderWidth: 2 },   // ponto vazado
            areaStyle: { color: p.serieFill, opacity: 0.55 } },
          { name: "Média móvel (3 m)", type: "line", data: mm3.map(v => (v == null ? "-" : v)), smooth: 0.3,
            symbol: "none", z: 2, lineStyle: { width: 2, type: [6, 4], color: p.ouroLinha }, itemStyle: { color: p.ouroLinha } },
        ],
      };
    },
    acessivel: {
      descricao: `Total pago por mês, com média móvel de três meses. Último mês completo (${ult ? MESES[ult.mes] + "/" + ult.ano : "—"}): ${ult ? compacto(ult.valor) : "—"}.` +
        (nParciais ? ` ${nParciais} mês(es) seguinte(s) ainda parcial(is) na origem.` : "") +
        " Pontos fora do padrão são detalhados na aba Alertas.",
      cabecalhos: ["Mês", "Pago", "Média 3 m", "Desvio vs média 12m"],
      linhas: serie.map((s, i) => [`${MESES[s.mes]}/${s.ano}${parcial[i] ? " (parcial)" : ""}`, compacto(s.valor),
        mm3[i] == null ? "—" : compacto(mm3[i]),
        desvios[i] == null ? "—" : (desvios[i] > 0 ? "+" : "") + desvios[i] + "%"]),
    },
  };
  desenharMensal();

  // Execução: empenhado × liquidado × pago por mês (tríade coletada pelo crawler)
  renderExecucao();

  // Top funções (barra horizontal, com vista R$ / % / per capita)
  renderFuncao();

  // Ano contra ano por função (mesmo período)
  renderComparativo();

  // Por fonte (rosca, 8 maiores) — legenda à direita; no celular, embaixo (à direita
  // ela espremia o anel). Nome longo na legenda é cortado; a dica traz o inteiro.
  const ft = DADOS.por_fonte.slice(0, 8);
  const elFonte = document.getElementById("ch-fonte");
  Comum.grafico(elFonte, {
    dependeDaLargura: true,
    opcao: (p, larg) => {
      const cores = coresCategorias(p);
      const largTexto = p.celular ? Math.max(120, larg - 30) : Math.max(110, Math.round(larg * 0.5) - 28);
      const legenda = { orient: "vertical", itemWidth: 14, itemHeight: 10, itemGap: p.celular ? 7 : 9,
        textStyle: { fontSize: 11.5, overflow: "truncate", width: largTexto }, tooltip: { show: true, confine: true } };
      // o anel ocupa o que a legenda deixa: à esquerda dela (desktop) ou acima (celular, uma
      // linha de ~23 px por fonte) — em % da caixa ele saía cortado nas caixas estreitas
      const alt = elFonte.clientHeight || (p.celular ? 420 : 300);
      const livre = p.celular ? [larg, alt - ft.length * 23 - 12] : [larg - largTexto - 30, alt];
      const raio = Math.max(40, Math.min(livre[0], livre[1]) / 2 - 6);
      return {
        tooltip: { trigger: "item", confine: true,
          formatter: (e) => Comum.dicaGrafico(e.name, [[e.color, "Pago", brlc(e.value), "p"]]) },
        legend: p.celular ? { ...legenda, bottom: 0, left: "center" } : { ...legenda, right: 0, top: "middle" },
        series: [{ type: "pie", radius: [Math.round(raio * 0.58), raio],
          center: p.celular ? [larg / 2, raio + 6] : [livre[0] / 2, alt / 2],
          label: { show: false }, labelLine: { show: false }, emphasis: { scaleSize: 6 },
          itemStyle: { borderColor: p.card, borderWidth: 2 },
          data: ft.map((f, i) => ({ name: f.fonte, value: f.valor, itemStyle: { color: cores[i % cores.length] } })) }],
      };
    },
    acessivel: {
      descricao: "Distribuição do gasto pago por fonte de recurso (oito maiores).",
      cabecalhos: ["Fonte", "Pago"], linhas: ft.map(f => [f.fonte, compacto(f.valor)]),
    },
  });

  // Por unidade gestora (barras deitadas)
  const un = DADOS.por_unidade.slice(0, 8);
  Comum.grafico("ch-unidade", {
    dependeDaLargura: true,
    opcao: (p, larg) => opcaoBarrasDeitadas(p, larg, { nomes: un.map(u => u.unidade), valores: un.map(u => u.valor), cores: p.serie,
      largRotulo: 280, largRotuloCel: 140, dica: (i) => Comum.dicaGrafico(un[i].unidade, [[p.serie, "Pago", brlc(un[i].valor), "p"]]) }),
    acessivel: {
      descricao: `Gasto pago por unidade gestora. Primeira: ${un[0] ? un[0].unidade + ", " + compacto(un[0].valor) : "—"}.`,
      cabecalhos: ["Unidade gestora", "Pago"], linhas: un.map(u => [u.unidade, compacto(u.valor)]),
    },
  });

  renderGraficosAnalises();
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
  const bt = taxas.base_taxa;
  if (taxas.taxa_pagamento != null) {
    const cob = bt?.cobertura_pct != null
      ? ` (taxa calculada sobre ${bt.cobertura_pct}% do empenhado — empenhos cujo original está na base)` : "";
    partes.push(`Dos empenhos de ${ultimo}${cob}: ${Math.round(taxas.taxa_liquidacao)}% liquidado · ` +
                `${Math.round(taxas.taxa_pagamento)}% pago`);
  } else if (taxas.taxa_motivos?.length) {
    // sem teto artificial: os números brutos aparecem com o motivo da não validação
    const brutas = taxas.taxas_brutas
      ? ` Razões brutas: liquidado/empenhado ${taxas.taxas_brutas.liquidacao}%, pago/empenhado ${taxas.taxas_brutas.pagamento}%.` : "";
    partes.push(`Taxa de execução de ${ultimo} NÃO validada — ${taxas.taxa_motivos.join("; ")}.${brutas}`);
  }
  if (bt?.sem_original)
    partes.push(`${bt.sem_original.toLocaleString("pt-BR")} empenhos de ${ultimo} só têm anulações/reforços na base ` +
                `(original emitido antes de ${DADOS.periodo?.de || "2025-01"}): ${compacto(bt.pago_sem_original)} pagos por eles ficam fora da taxa`);
  if (taxas.restos)
    partes.push(`restos a pagar quitados em ${ultimo}: ${compacto(taxas.restos)}`);
  if (taxas.nao_localizado)
    partes.push(`pagamentos orçamentários cujo empenho não está na base: ${compacto(taxas.nao_localizado)}`);
  document.getElementById("exe-taxas").textContent = partes.join(" · ");

  const s = exe.serie;
  const parcial = s.map(x => mesParcial(x.ano, x.mes));
  const labels = s.map((x, i) => `${rotuloMes(x)}${parcial[i] ? "*" : ""}`);
  // estágio sem partição carregada vem null (desconhecido ≠ 0): vira lacuna na linha
  const ESTAGIOS = [["empenhado", "Empenhado"], ["liquidado", "Liquidado"], ["pago", "Pago"]];
  const trechos = Object.fromEntries(ESTAGIOS.map(([k]) => [k, dividirParciais(s.map(x => x[k]), parcial)]));
  const valor = (v) => v == null ? "não carregado" : brlc(v);
  Comum.grafico("ch-execucao", {
    opcao: (p) => {
      const estilo = { empenhado: { cor: cinzaLinha(p), largura: 2, traco: [6, 4] },
                       liquidado: { cor: p.ouroLinha, largura: 2 },
                       pago: { cor: p.serie, largura: 2.5, area: true } };
      return {
        grid: { left: 4, right: 20, top: p.celular ? 14 : 40, bottom: p.celular ? 40 : 6, containLabel: true },
        // linhas sem marcador: na legenda, só o traço (o do empenhado, tracejado)
        legend: { data: ESTAGIOS.map(([, nome]) => ({ name: nome, itemStyle: { opacity: 0 } })),
          [p.celular ? "bottom" : "top"]: 0, left: 0, itemGap: 18, itemWidth: 22, itemHeight: 10 },
        tooltip: { trigger: "axis", confine: true, formatter: (ps) => {
          const i = ps[0].dataIndex, x = s[i];
          return Comum.dicaGrafico(mesAno(x) + (parcial[i] ? " (parcial)" : ""),
            ESTAGIOS.map(([k, nome]) => [estilo[k].cor, nome, valor(x[k])]), parcial[i] ? NOTA_PARCIAL : "", parcial[i]);
        } },
        xAxis: { type: "category", data: labels, boundaryGap: false, axisLabel: EIXO_MESES(p) },
        yAxis: { type: "value", min: 0, splitNumber: p.celular ? 4 : 5, axisLabel: { formatter: (v) => Comum.compactoEixo(v) } },
        // cada estágio: trecho dos meses completos + trecho pontilhado até os parciais
        series: ESTAGIOS.flatMap(([k, nome], z) => {
          const e = estilo[k];
          const base = { name: nome, type: "line", smooth: 0.25, showSymbol: false, symbolSize: 6, z: 2 + z,
            itemStyle: { color: e.cor } };
          return [
            { ...base, data: trechos[k].completo, lineStyle: { width: e.largura, color: e.cor, type: e.traco || "solid" },
              areaStyle: e.area ? { color: p.serieFill } : undefined },
            { ...base, data: trechos[k].parcial, lineStyle: { width: e.largura, color: e.cor, type: [2, 3] },
              areaStyle: e.area ? { color: p.serieFill, opacity: 0.55 } : undefined },
          ];
        }),
      };
    },
    acessivel: {
      descricao: "Empenhado (compromisso assumido), liquidado (entrega atestada) e pago (dinheiro que saiu) " +
        "em cada mês. " + (partes.length ? partes.join("; ") + "." : ""),
      cabecalhos: ["Mês", "Empenhado", "Liquidado", "Pago"],
      linhas: s.map((x, i) => [labels[i].replace("*", " (parcial)"), x.empenhado == null ? "não carregado" : compacto(x.empenhado),
        x.liquidado == null ? "não carregado" : compacto(x.liquidado), x.pago == null ? "não carregado" : compacto(x.pago)]),
    },
  });
}

// Top funções com três vistas: R$ absoluto, % do total e por habitante (padrão
// dos melhores portais — todo número em três escalas). Rerenderizado pelo toggle.
let fnVista = "reais";

function renderFuncao() {
  const fn = DADOS.por_funcao.slice(0, 10);
  const total = DADOS.totais?.geral || 1;
  const conv = fnVista === "pct" ? (v) => 100 * v / total
    : fnVista === "capita" ? (v) => v / POP_SANTOS : (v) => v;
  const fmt = fnVista === "pct" ? (v) => v.toFixed(1).replace(".", ",") + "% do total"
    : (v) => brlc(v);
  const tick = fnVista === "pct" ? (v) => v.toLocaleString("pt-BR") + "%"
    : fnVista === "capita" ? (v) => brl(v) : (v) => Comum.compactoEixo(v);
  const rotuloDica = fnVista === "pct" ? "Participação" : fnVista === "capita" ? "Por habitante" : "Pago";

  const rotuloVista = fnVista === "pct" ? "% do total pago"
    : fnVista === "capita" ? "valor por habitante (IBGE 2022)" : "total pago";
  Comum.grafico("ch-funcao", {
    dependeDaLargura: true,
    opcao: (p, larg) => opcaoBarrasDeitadas(p, larg, {
      nomes: fn.map(f => nomeFuncao(f.funcao)),   // mesmo nome do "De cada R$ 100" e do mapa
      valores: fn.map(f => conv(f.valor)), cores: p.ouro, eixo: tick, largRotulo: 170,
      dica: (i) => Comum.dicaGrafico(nomeFuncao(fn[i].funcao), [[p.ouro, rotuloDica, fmt(conv(fn[i].valor)), "p"]],
        fnVista === "reais" ? "" : compacto(fn[i].valor) + " no total"),
    }),
    acessivel: {
      descricao: `Dez funções com maior gasto no período, em ${rotuloVista}. ` +
        `Primeira: ${fn[0] ? fn[0].funcao + ", " + fmt(conv(fn[0].valor)) : "—"}.`,
      cabecalhos: ["Função", rotuloVista], linhas: fn.map(f => [f.funcao, fmt(conv(f.valor))]),
    },
  });
}

function ligarVistaFuncao() {
  document.querySelectorAll("#fn-vista button").forEach(b =>
    b.addEventListener("click", () => {
      fnVista = b.dataset.vista;
      marcarAlternancia("#fn-vista button", x => x.dataset.vista === fnVista);
      renderFuncao();
    }));
}

// "De cada R$ 100 pagos" — tradução do total em escala humana (barras proporcionais)
// "Para onde vai o dinheiro" usa só o orçamentário (índice novo); índice antigo cai no total
function baseParaOndeVai() {
  const orc = DADOS.por_funcao_orcamentario;
  if (orc?.length) return { fns: orc, total: orc.reduce((s, f) => s + f.valor, 0) };
  return { fns: DADOS.por_funcao || [], total: DADOS.totais?.geral };
}

// link para o raio-X: dossiê pré-computado (top-300) ou a rota por documento/nome
function linkRaiox(f) {
  const top = (DADOS.top_favorecidos || []).find(t => t.chave === f.chave);
  return top?.slug ? `./favorecido.html?f=${encodeURIComponent(top.slug)}`
    : `./favorecido.html?doc=${encodeURIComponent(f.documento || "")}&nome=${encodeURIComponent(f.nome || "")}`;
}
const dias = (d) => d == null ? "—" : `${Number(d).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} d`;

// ── Análises (Lote D5): prazo de pagamento, anulações, fim de exercício ──────
function renderAnalises() {
  const prz = DADOS.prazos_pagamento;
  if (prz?.por_ano && Object.keys(prz.por_ano).length) {
    const anos = Object.keys(prz.por_ano).sort();
    const ult = anos[anos.length - 1], a = prz.por_ano[ult];
    document.getElementById("prazos-resumo").textContent =
      anos.map(k => `${k}: mediana de ${dias(prz.por_ano[k].mediana_dias)} entre a liquidação e o pagamento ` +
                    `(90% em até ${dias(prz.por_ano[k].p90_dias)}; ${prz.por_ano[k].pagamentos.toLocaleString("pt-BR")} pagamentos)`).join(" · ");
    const total = a.faixas.reduce((s, f) => s + f.qtd, 0) || 1;
    const max = Math.max(...a.faixas.map(f => f.qtd)) || 1;
    document.getElementById("prazos-faixas").innerHTML = a.faixas.filter(f => f.qtd || f.faixa !== "antes da liquidação").map(f => `
      <div class="r100-linha">
        <span class="r100-nome">${esc(f.faixa)}${f.faixa === "antes da liquidação" && f.qtd ? " ⚠" : ""}</span>
        <span class="r100-barra" aria-hidden="true"><span class="r100-fill" style="width:${(100 * f.qtd / max).toFixed(1)}%"></span></span>
        <span class="r100-vlr">${Math.round(100 * f.qtd / total)}%</span>
      </div>`).join("");
    const linha = (x) => `<tr><td data-label="Fornecedor"><a href="${linkRaiox(x)}">${esc(x.nome)}</a></td>
      <td data-label="Mediana" class="r">${dias(x.mediana_dias)}</td>
      <td data-label="Pagamentos" class="r">${x.pagamentos}</td>
      <td data-label="Valor" class="r">${compacto(x.valor)}</td></tr>`;
    document.getElementById("prazos-lentos").innerHTML = (prz.mais_lentos || []).map(linha).join("");
    document.getElementById("prazos-rapidos").innerHTML = (prz.mais_rapidos || []).map(linha).join("");
    document.getElementById("prazos-nota").textContent =
      `Distribuição de ${ult}. ${prz.criterio} A Lei 14.133 (art. 141) manda pagar na ordem cronológica, ` +
      "por fonte de recurso, com exceções justificadas: pagamento muito mais rápido ou muito mais lento que a " +
      "fila é triagem para pedir a justificativa — não é conclusão. Os casos extremos viram alertas.";
    document.getElementById("box-prazos").hidden = false;
  }

  const an = DADOS.anulacoes;
  if (an?.por_ano && Object.keys(an.por_ano).length) {
    document.getElementById("anul-resumo").textContent = Object.entries(an.por_ano).map(([k, v]) =>
      `${k}: ${compacto(v.valor)} anulados em ${v.qtd.toLocaleString("pt-BR")} anulações` +
      (v.pct_do_empenhado != null ? ` (${v.pct_do_empenhado.toLocaleString("pt-BR")}% do empenhado na base)` : "")).join(" · ");
    document.getElementById("anul-top").innerHTML = (an.top_favorecidos || []).slice(0, 10).map(x => `
      <tr><td data-label="Favorecido"><a href="${linkRaiox(x)}">${esc(x.nome)}</a>${x.ente_publico ? ' <span class="p" style="color:var(--muted)">· ente público</span>' : ""}</td>
        <td data-label="Anulado" class="r">${compacto(x.valor)}</td>
        <td data-label="% do empenhado" class="r">${x.pct_do_empenhado != null ? x.pct_do_empenhado.toLocaleString("pt-BR") + "%"
          : '<span title="O empenho original é anterior a jan/2025 — fora da base">orig. anterior</span>'}</td></tr>`).join("");
    document.getElementById("box-anulacoes").hidden = false;
  }

  const fim = DADOS.fim_de_exercicio;
  if (fim && Object.keys(fim).length) {
    const rot = { empenhado: "Empenhado (novos)", liquidado: "Liquidado", pago: "Pago", anulado: "Anulado" };
    document.getElementById("fim-corpo").innerHTML = Object.entries(fim).map(([ano, m]) =>
      Object.entries(rot).map(([k, r]) => m[k] ? `<tr><td data-label="Ano · estágio">${ano} · ${r}</td>
        <td data-label="Dezembro" class="r">${compacto(m[k].dezembro)}</td>
        <td data-label="Média jan–nov" class="r">${compacto(m[k].media_jan_nov)}</td>
        <td data-label="Dez ÷ média" class="r"${m[k].razao >= 1.5 ? ' style="font-weight:800"' : ""}>${m[k].razao != null
          ? m[k].razao.toLocaleString("pt-BR") + "×" : "—"}</td></tr>` : "").join("")).join("");
    document.getElementById("fim-nota").textContent =
      "Corrida de liquidação e cancelamento de saldos no encerramento do exercício aparecem aqui: liquidar em " +
      "dezembro garante a inscrição em restos a pagar processados; anular em massa cancela empenhos sem execução. " +
      "Só anos com dezembro completo na base.";
    document.getElementById("box-fim").hidden = false;
  }

  renderPublicidade();
}

// Publicidade: só agregados (quanto, quando e a quem) — nenhum sinal sobre empresas
function renderPublicidade() {
  const pub = DADOS.publicidade;
  if (!pub?.serie?.length) return;
  const c = pub.comparacao, partes = [];
  if (c) {
    const per = `jan–${MESES[c.mes].toLowerCase()}`;
    partes.push(`${per}/${c.ano}: ${compacto(c.atual)} pagos em publicidade` + (c.pct != null
      ? ` — ${Math.abs(c.pct)}% ${c.pct >= 0 ? "acima" : "abaixo"} do mesmo período de ${c.ano - 1} (${compacto(c.anterior)})`
      : ""));
  }
  const anos = Object.keys(pub.por_ano || {}).sort();
  const ultimoMes = pub.serie[pub.serie.length - 1];
  partes.push("Por ano: " + anos.map(a => {
    const v = pub.por_ano[a];
    const ate = +a === ultimoMes.ano && ultimoMes.mes < 12 ? ` (até ${MESES[ultimoMes.mes].toLowerCase()})` : "";
    return `${a}${ate} ${compacto(v.total)} — propaganda ${compacto(v.propaganda)}, publicidade legal ${compacto(v.legal)}`;
  }).join(" · "));
  document.getElementById("pub-resumo").textContent = partes.join(". ") + ".";
  document.getElementById("pub-fav").innerHTML = (pub.favorecidos || []).map(f => `
    <tr><td data-label="Favorecido"><a href="${linkRaiox(f)}">${esc(f.nome)}</a>${f.ente_publico ? ' <span class="p" style="color:var(--muted)">· ente público</span>' : ""}</td>
      <td data-label="Propaganda" class="r">${compacto(f.propaganda)}</td>
      <td data-label="Publicidade legal" class="r">${compacto(f.legal)}</td>
      <td data-label="Total" class="r">${compacto(f.valor)}</td></tr>`).join("");
  const parciais = pub.serie.filter(x => mesParcial(x.ano, x.mes)).length;
  document.getElementById("pub-nota").textContent = (pub.criterio || "") + (parciais
    ? " * Mês parcial (barra mais clara): o portal publica com semanas de atraso e o valor ainda vai subir." : "");
  document.getElementById("box-publicidade").hidden = false;
}

// gráficos das análises (as caixas aparecem em renderAnalises; cada gráfico é desenhado
// quando a sua fica visível e perto da tela)
function renderGraficosAnalises() {
  const an = DADOS.anulacoes;
  if (an?.serie?.length) {
    Comum.grafico("ch-anulacoes", {
      opcao: (p) => {
        const cor = coresCategorias(p)[7];
        return {
          grid: { left: 4, right: 10, top: 14, bottom: 4, containLabel: true },
          tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" }, formatter: (ps) => {
            const s = an.serie[ps[0].dataIndex];
            return Comum.dicaGrafico(mesAno(s), [[cor, "Anulado", brlc(s.valor), "p"],
              [null, "Anulações", s.qtd.toLocaleString("pt-BR")]]);
          } },
          xAxis: { type: "category", data: an.serie.map(rotuloMes), axisLabel: { hideOverlap: true } },
          yAxis: { type: "value", axisLabel: { formatter: (v) => Comum.compactoEixo(v) } },
          series: [{ type: "bar", barMaxWidth: 28, data: an.serie.map(s => s.valor),
            itemStyle: { color: cor, borderRadius: [3, 3, 0, 0] } }],
        };
      },
      acessivel: { descricao: "Valor de empenhos anulados por mês.", cabecalhos: ["Mês", "Anulado", "Anulações"],
        linhas: an.serie.map(s => [`${MESES[s.mes]}/${s.ano}`, compacto(s.valor), String(s.qtd)]) },
    });
  }
  const pr = (DADOS.por_programa || []).slice(0, 12);
  if (pr.length) {
    Comum.grafico("ch-programa", {
      dependeDaLargura: true,
      opcao: (p, larg) => opcaoBarrasDeitadas(p, larg, { nomes: pr.map(x => nomeFuncao(x.programa)), valores: pr.map(x => x.valor),
        cores: p.serie, largRotulo: 260, largRotuloCel: 140,
        dica: (i) => Comum.dicaGrafico(nomeFuncao(pr[i].programa), [[p.serie, "Pago", brlc(pr[i].valor), "p"]]) }),
      acessivel: { descricao: "Pago orçamentário por programa do PPA (doze maiores).", cabecalhos: ["Programa", "Pago"],
        linhas: pr.map(x => [x.programa, compacto(x.valor)]) },
    });
    document.getElementById("box-programa").hidden = false;
  }
  const pub = DADOS.publicidade;
  if (pub?.serie?.length) {
    const s = pub.serie, parcial = s.map(x => mesParcial(x.ano, x.mes));
    const labels = s.map((x, i) => `${rotuloMes(x)}${parcial[i] ? "*" : ""}`);
    const maior = s.reduce((m, x) => (x.propaganda + x.legal > m.propaganda + m.legal ? x : m), s[0]);
    Comum.grafico("ch-publicidade", {
      opcao: (p) => {
        // mês parcial: barra mais clara (o valor ainda vai subir)
        const barras = (campo) => s.map((x, i) => (parcial[i] ? { value: x[campo], itemStyle: { opacity: 0.4 } } : x[campo]));
        return {
          grid: { left: 4, right: 10, top: p.celular ? 14 : 36, bottom: p.celular ? 36 : 4, containLabel: true },
          legend: { [p.celular ? "bottom" : "top"]: 0, left: 0, itemGap: 18, itemWidth: 14, itemHeight: 10 },
          tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" }, formatter: (ps) => {
            const i = ps[0].dataIndex, x = s[i];
            return Comum.dicaGrafico(mesAno(x) + (parcial[i] ? " (parcial)" : ""), [
              [p.serie, "Propaganda", brlc(x.propaganda), "p"], [p.ouro, "Publicidade legal", brlc(x.legal), "p"],
              [null, "Total", brlc(x.propaganda + x.legal)]], parcial[i] ? NOTA_PARCIAL : "", parcial[i]);
          } },
          xAxis: { type: "category", data: labels, axisLabel: EIXO_MESES(p) },
          yAxis: { type: "value", axisLabel: { formatter: (v) => Comum.compactoEixo(v) } },
          series: [
            { name: "Propaganda", type: "bar", stack: "pub", barMaxWidth: 40, data: barras("propaganda"), itemStyle: { color: p.serie } },
            { name: "Publicidade legal", type: "bar", stack: "pub", barMaxWidth: 40, data: barras("legal"), itemStyle: { color: p.ouro } },
          ],
        };
      },
      acessivel: {
        descricao: `Pago por mês em publicidade: propaganda e publicidade legal. Maior mês: ${MESES[maior.mes]}/${maior.ano}, ` +
          `${compacto(maior.propaganda + maior.legal)}.`,
        cabecalhos: ["Mês", "Propaganda", "Publicidade legal", "Total"],
        linhas: s.map((x, i) => [`${MESES[x.mes]}/${x.ano}${parcial[i] ? " (parcial)" : ""}`, compacto(x.propaganda),
          compacto(x.legal), compacto(x.propaganda + x.legal)]),
      },
    });
  }
}

function renderR100() {
  const box = document.getElementById("box-r100");
  const { fns, total } = baseParaOndeVai();
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
    `Distribuição do pago ORÇAMENTÁRIO no período (${compacto(total)}) por função de governo — sem as ` +
    "retenções e consignações extra-orçamentárias, que só transitam pelo caixa.";
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
  const variacao = (f) => {
    const va = soma[anterior][f] || 0;
    if (!va) return "sem base no ano anterior";
    const d = Math.round(100 * ((soma[atual][f] || 0) - va) / va);
    return `${d >= 0 ? "+" : ""}${d}% vs ${anterior}`;
  };

  document.getElementById("comparativo-titulo").textContent =
    `${atual} × ${anterior}, por função`;
  document.getElementById("comparativo-sub").textContent =
    `Acumulado jan–${MESES[mesLim].toLowerCase()} de cada ano (meses completos).`;
  box.hidden = false;

  // barras agrupadas: o ano anterior em cinza de referência, o atual em dourado
  Comum.grafico("ch-comparativo", {
    dependeDaLargura: true,
    opcao: (p, larg) => {
      const [eixoX, direita] = eixoValor(Math.max(...funcoes.flatMap(([f]) => [soma[anterior][f] || 0, soma[atual][f] || 0])),
        larg - (p.celular ? 140 : 160) - 40, (v) => Comum.compactoEixo(v));
      return {
        grid: { left: 4, right: direita, top: 34, bottom: 4, containLabel: true },
        legend: { top: 0, left: 0, itemGap: 18, itemWidth: 14, itemHeight: 10 },
        tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" }, formatter: (ps) => {
          const [f] = funcoes[ps[0].dataIndex];
          return Comum.dicaGrafico(f, [[p.ref, String(anterior), brlc(soma[anterior][f] || 0), "p"],
            [p.ouro, String(atual), brlc(soma[atual][f] || 0), "p"]], variacao(f));
        } },
        xAxis: eixoX,
        yAxis: { type: "category", inverse: true, data: funcoes.map(([f]) => f),
          axisLabel: { width: p.celular ? 140 : 230, overflow: "truncate" } },
        series: [
          { name: String(anterior), type: "bar", barMaxWidth: 12, barGap: "15%", data: funcoes.map(([f]) => soma[anterior][f] || 0),
            itemStyle: { color: p.ref, borderRadius: [0, 3, 3, 0] } },
          { name: String(atual), type: "bar", barMaxWidth: 12, data: funcoes.map(([f]) => soma[atual][f] || 0),
            itemStyle: { color: p.ouro, borderRadius: [0, 3, 3, 0] } },
        ],
      };
    },
    acessivel: {
      descricao: `Gasto pago por função, ${atual} contra ${anterior}, mesmo período (jan–${MESES[mesLim]}).`,
      cabecalhos: ["Função", String(anterior), String(atual), "Variação"],
      linhas: funcoes.map(([f, v]) => {
        const va = soma[anterior][f] || 0;
        const d = va ? Math.round(100 * (v - va) / va) : null;
        return [f, compacto(va), compacto(v), d == null ? "—" : (d >= 0 ? "+" : "") + d + "%"];
      }),
    },
  });
}

// ── Recibo do contribuinte (didático, IPTU → funções) ────────────────────────
function renderRecibo() {
  const box = document.getElementById("box-recibo");
  const { fns, total } = baseParaOndeVai();
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
// Consome despesas/arvore.json (gerado pelo export). Some em silêncio se o arquivo
// faltar — a barra de funções cobre o caso. A navegação entre os níveis é a trilha
// HTML (#mapa-trilha, botões de teclado); o gráfico desenha só o nível atual (sem a
// trilha nativa do ECharts) e a tabela oculta acompanha o nível.
let ARVORE = null;
let mapaPath = [];   // [] = funções · [i] = subfunções da função i · [i,j] = elementos

async function initMapa() {
  try {
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

// Cor da área: o dourado misturado ao fundo do cartão, mais forte quanto maior o valor
// (a escala do mapa antigo, opaca); o texto vai em navy ou claro — o que contrastar mais.
const hexRgb = (h) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16));
const misturar = (a, b, t) => "#" + hexRgb(a).map((x, k) =>
  Math.round(x + (hexRgb(b)[k] - x) * t).toString(16).padStart(2, "0")).join("");
function luminancia(h) {
  const [r, g, b] = hexRgb(h).map((c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contraste = (a, b) => { const [x, y] = [luminancia(a), luminancia(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
const TINTA_ESCURA = "#07111f", TINTA_CLARA = "#e8ecf3";   // o navy e a tinta do tema escuro
const tintaSobre = (fundo) => (contraste(fundo, TINTA_ESCURA) >= contraste(fundo, TINTA_CLARA) ? TINTA_ESCURA : TINTA_CLARA);

// Razão de aspecto buscada pelo "squarified" (padrão do ECharts: a áurea, 1,618). Com 1,4
// as áreas médias saem menos espichadas e mais delas cabem o rótulo inteiro, como no mapa
// antigo (Assistência social e Previdência voltam a ter nome no 1º nível).
const RAZAO_MAPA = 1.4;
// Retângulos de um nível, pelo MESMO "squarified" do treemap do ECharts (ordem
// decrescente, `RAZAO`, área mínima de 10 px², 2 px entre as áreas): saber o tamanho
// de cada área antes de desenhar deixa o rótulo entrar só onde cabe inteiro, como no
// mapa antigo — cortado ("Assi…") ou sem o valor, não. `valores` em ordem decrescente.
function retangulosMapa(larg, alt, valores, RAZAO, folga = 2) {
  const MINIMA = 10, meia = folga / 2;
  const rect = { x: -meia, y: -meia, w: larg + folga, h: alt + folga };
  const areaTotal = rect.w * rect.h;
  let soma = valores.reduce((s, v) => s + v, 0), n = valores.length;
  for (let k = valores.length - 1; k >= 0; k--)   // as menores que nem aparecem saem da conta
    if (valores[k] / soma * areaTotal < MINIMA) { n = k; soma -= valores[k]; }
  const areas = valores.slice(0, n).map((v) => (soma ? v / soma * areaTotal : 0));
  const saida = [];
  const pior = (linha, areaLinha, fixo) => {
    let max = 0, min = Infinity;
    for (const k of linha) if (areas[k]) { min = Math.min(min, areas[k]); max = Math.max(max, areas[k]); }
    const q = areaLinha * areaLinha, f = fixo * fixo * RAZAO;
    return q ? Math.max(f * max / q, q / (f * min)) : Infinity;
  };
  const posicionar = (linha, areaLinha, fixo, ultima) => {
    const deitada = fixo === rect.w;   // a linha corre ao longo da largura
    let corre = deitada ? rect.x : rect.y;
    const fim = deitada ? rect.x + rect.w : rect.y + rect.h;
    let espessura = fixo ? areaLinha / fixo : 0;
    if (ultima || espessura > (deitada ? rect.h : rect.w)) espessura = deitada ? rect.h : rect.w;
    linha.forEach((k, j) => {
      const passo = espessura ? areas[k] / espessura : 0;
      const sobra = fim - corre;
      const comp = j === linha.length - 1 || sobra < passo ? sobra : passo;
      const a = Math.max(comp - folga, 0), b = Math.max(espessura - folga, 0);
      saida[k] = deitada
        ? { x: corre + Math.min(meia, a / 2), y: rect.y + Math.min(meia, b / 2), w: a, h: b }
        : { x: rect.x + Math.min(meia, b / 2), y: corre + Math.min(meia, a / 2), w: b, h: a };
      corre += comp;
    });
    if (deitada) { rect.y += espessura; rect.h -= espessura; } else { rect.x += espessura; rect.w -= espessura; }
  };
  let fixo = Math.min(rect.w, rect.h), melhor = Infinity, linha = [], areaLinha = 0;
  for (let k = 0; k < n;) {
    linha.push(k); areaLinha += areas[k];
    const nota = pior(linha, areaLinha, fixo);
    if (nota <= melhor) { k++; melhor = nota; }
    else {
      linha.pop(); areaLinha -= areas[k];
      posicionar(linha, areaLinha, fixo, false);
      fixo = Math.min(rect.w, rect.h); linha = []; areaLinha = 0; melhor = Infinity;
    }
  }
  if (linha.length) posicionar(linha, areaLinha, fixo, true);
  return saida;
}

// Rótulo de uma área (nome + valor, no canto): o normal, um compacto, o nome em duas
// linhas (área alta e estreita) ou nenhum — o que couber inteiro no retângulo. Devolve
// as opções de label do ECharts (formatter em rich text) ou null.
let medidorTexto = null;
function rotuloMapa(r, nome, valor, celular) {
  if (!r) return null;
  medidorTexto = medidorTexto || document.createElement("canvas").getContext("2d");
  const largura = (texto, fonte) => { medidorTexto.font = fonte; return medidorTexto.measureText(texto).width; };
  // nome em duas linhas: quebra no espaço mais perto do meio (o traço de "x - y" fica no
  // fim da 1ª linha, não abrindo a 2ª)
  const meio = nome.length / 2;
  const espacos = [...nome.matchAll(/ (?!- )/g)].map((m) => m.index);
  const corte = espacos.length ? espacos.reduce((a, b) => (Math.abs(b - meio) < Math.abs(a - meio) ? b : a)) : -1;
  const linhasNome = [[nome], ...(corte > 0 ? [[nome.slice(0, corte), nome.slice(corte + 1)]] : [])];
  const estilos = [
    { n: celular ? 11.5 : 12.5, v: celular ? 10.5 : 11.5, ln: 17, lv: 16, pad: [7, 9] },
    { n: 11, v: 10, ln: 15, lv: 14, pad: [5, 7] },
  ];
  // tentativas na ordem: uma linha (normal, compacto), depois duas linhas (normal, compacto)
  for (const linhas of linhasNome) {
    for (const e of estilos) {
      const texto = Math.max(...linhas.map((l) => largura(l, `600 ${e.n}px Manrope, sans-serif`)),
        largura(valor, `500 ${e.v}px "IBM Plex Mono", monospace`));
      // folga de 6 px: o ECharts reserva um pouco da largura e cortaria a última letra
      if (r.w - 2 * e.pad[1] >= texto + 6 && r.h - 2 * e.pad[0] >= e.ln * linhas.length + e.lv) {
        const rt = (s) => String(s).replace(/[{}|]/g, "");   // chave e barra quebrariam o rich text
        return { padding: e.pad, formatter: linhas.map((l) => `{n|${rt(l)}}`).join("\n") + `\n{v|${rt(valor)}}`,
          rich: { n: { fontFamily: Comum.paleta().sans, fontWeight: 600, fontSize: e.n, lineHeight: e.ln },
            v: { fontFamily: Comum.paleta().mono, fontWeight: 500, fontSize: e.v, lineHeight: e.lv } } };
      }
    }
  }
  return null;
}

// clique numa área: abre o nível de baixo; no elemento, prepara o Detalhamento filtrado
function abrirNoMapa(i) {
  if (i == null || !ARVORE) return;
  const original = nivelMapa().nos[i];
  if (!original) return;
  if (mapaPath.length < 2 && original.f?.length) {
    mapaPath.push(i);
    renderMapa();
  } else if (mapaPath.length === 2 && original.n !== "Demais elementos") {
    // folha (elemento) → Detalhamento filtrado por função+elemento
    irParaDetalhe({ funcao: ARVORE.arvore[mapaPath[0]].n, elemento_despesa: original.n });
  } else {
    Comum.toast(`${original.n} — ${brlc(original.v)}`);
  }
}

function renderMapa() {
  const { nos, rotulo: nomeNivel, nivel } = nivelMapa();
  // em ordem decrescente (a do ECharts e a do layout acima)
  const itens = nos.map((x, i) => ({ n: x.n, v: x.v, i, abre: mapaPath.length < 2 && !!x.f?.length }))
    .filter(x => x.v > 0).sort((a, b) => b.v - a.v);
  const total = itens.reduce((s, x) => s + x.v, 0) || 1;
  const max = Math.max(...itens.map(x => x.v));
  const el = document.getElementById("ch-mapa");
  const cortar = (s, n) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);

  Comum.grafico(el, {
    dependeDaLargura: true,
    opcao: (p, larg) => {
      const rets = retangulosMapa(larg, el.clientHeight || 400, itens.map(x => x.v), RAZAO_MAPA);
      return {
        tooltip: { confine: true, formatter: (info) => {
          const d = info.data || {};
          const nota = d.abre ? "Clique para abrir."
            : mapaPath.length === 2 && d.n !== "Demais elementos" ? "Clique para preparar o Detalhamento já filtrado." : "";
          return Comum.dicaGrafico(d.n || info.name, [[info.color, "Pago", brlc(info.value), "p"],
            [null, "Deste nível", (100 * info.value / total).toFixed(1).replace(".", ",") + "%"]], nota);
        } },
        series: [{
          type: "treemap", nodeClick: false, roam: false, breadcrumb: { show: false },
          top: 0, left: 0, right: 0, bottom: 0, sort: "desc", squareRatio: RAZAO_MAPA,
          // o espaço entre as áreas é a cor de borda do nível de cima (padrão: branco — no
          // escuro virava uma grade branca): o fundo do cartão
          itemStyle: { borderWidth: 0, gapWidth: 2, borderRadius: 3, borderColor: p.card },
          upperLabel: { show: false },
          emphasis: { itemStyle: { borderColor: p.tinta, borderWidth: 1.5 } },
          data: itens.map((x, k) => {
            const fundo = misturar(p.card, p.ouro, Math.min(0.35 + 0.6 * Math.sqrt(x.v / max), 0.95));
            const nome = cortar(nomeFuncao(x.n), 26);
            const rot = rotuloMapa(rets[k], nome, compacto(x.v), p.celular);
            return { name: nome, value: x.v, i: x.i, n: x.n, abre: x.abre, itemStyle: { color: fundo },
              label: rot ? { show: true, position: "insideTopLeft", color: tintaSobre(fundo), overflow: "truncate", ...rot }
                : { show: false } };
          }),
        }],
      };
    },
    eventos: (chart) => chart.on("click", (e) => abrirNoMapa(e.data?.i)),
    acessivel: {
      descricao: `Mapa do gasto por ${nivel} — nível atual: ${nomeNivel}. ` +
        `Maior item: ${itens[0] ? nomeFuncao(itens[0].n) + ", " + compacto(itens[0].v) : "—"}.`,
      cabecalhos: [nivel === "elemento" ? "Elemento de despesa" : nivel === "subfunção" ? "Subfunção" : "Função", "Pago"],
      linhas: itens.map(x => [x.n, compacto(x.v)]),
    },
  });

  // trilha (breadcrumb) clicável
  const trilha = [{ nome: "Todas as áreas", path: [] }];
  if (mapaPath.length >= 1)
    trilha.push({ nome: nomeFuncao(ARVORE.arvore[mapaPath[0]].n), path: [mapaPath[0]] });
  if (mapaPath.length === 2)
    trilha.push({ nome: nomeFuncao(ARVORE.arvore[mapaPath[0]].f[mapaPath[1]].n),
                  path: mapaPath.slice() });
  const trilhaEl = document.getElementById("mapa-trilha");
  trilhaEl.innerHTML = trilha.map((t, i) => {
    const atual = i === trilha.length - 1;
    return `<button class="btn${atual ? " primario" : ""}" type="button" data-path="${t.path.join(",")}"
      ${atual ? 'aria-current="true"' : ""}>${esc(t.nome)}</button>`;
  }).join("");
  trilhaEl.querySelectorAll("button").forEach(b =>
    b.addEventListener("click", () => {
      mapaPath = b.dataset.path ? b.dataset.path.split(",").map(Number) : [];
      renderMapa();
      // os botões foram refeitos: o foco fica no nível escolhido (não volta ao topo da página)
      trilhaEl.querySelector('[aria-current="true"]')?.focus();
    }));
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
  const cidades = PARES.cidades.map(c => ({ nome: c.nome, ibge: c.ibge, v: valorPares(c) }))
    .sort((a, b) => b.v - a.v);
  const rotuloF = paresFuncao ? nomeFuncao(paresFuncao) : "todas as funções";

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

  // Santos em dourado; as cidades pares no cinza de referência
  Comum.grafico("ch-pares", {
    dependeDaLargura: true,
    opcao: (p, larg) => {
      const cor = (c) => (c.ibge === 3548500 ? p.ouro : p.ref);
      return opcaoBarrasDeitadas(p, larg, { nomes: cidades.map(c => c.nome), valores: cidades.map(c => c.v),
        cores: cidades.map(cor), eixo: (v) => brl(v), largRotulo: 170,
        dica: (i) => Comum.dicaGrafico(cidades[i].nome, [[cor(cidades[i]), "Por habitante/ano", brlc(cidades[i].v), "p"]]) });
    },
    acessivel: {
      descricao: `Gasto por habitante em ${rotuloF}, exercício ${PARES.exercicio}: Santos comparada a cinco cidades ` +
        `paulistas. ${frase.textContent}`,
      cabecalhos: ["Cidade", "R$ por habitante"], linhas: cidades.map(c => [c.nome, brl(c.v)]),
    },
  });
}

// "04 - ADMINISTRAÇÃO" → "Administração" (rótulo amigável p/ blocos didáticos)
function nomeFuncao(s) {
  const nice = String(s || "").replace(/^\d+\s*-\s*/, "").trim();
  return nice ? nice.charAt(0) + nice.slice(1).toLowerCase() : "—";
}

// ── Pago por dia, calendário e caminho do dinheiro (M8) ─────────────────────
// despesas/dados/calendario.json (pago e documentos por dia) e dados/fluxo.json (fonte →
// função → favorecido, por ano), gerados pelo export das MESMAS linhas de dados/mov/. O
// índice traz o manifesto (`dados_graficos`); sem ele — o índice publicado antes do 1º
// export com os arquivos — nada é baixado e as caixas dizem quando o gráfico chega.
const DIA_MS = 864e5;
const SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const dataBR = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
const diaSemana = (iso) => SEMANA[new Date(iso + "T12:00:00").getDay()];
// "AAAA-MM-DD" ↔ instante da meia-noite local (é como o ECharts lê a data no eixo de tempo)
const tempoLocal = (iso) => new Date(iso + "T00:00:00").getTime();
const isoLocal = (t) => {
  const d = new Date(t);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const parcialDia = (iso) => mesParcial(+iso.slice(0, 4), +iso.slice(5, 7));
const pctDe = (v, total) => (total ? (100 * v / total).toFixed(1).replace(".", ",") + "%" : "—");
const larguraTexto = (texto, fonte) => {
  medidorTexto = medidorTexto || document.createElement("canvas").getContext("2d");
  medidorTexto.font = fonte;
  return medidorTexto.measureText(texto).width;
};

let CALENDARIO = null, FLUXO = null;
const PROMESSAS_GRAFICOS = {};
function baixarDadosGrafico(nome) {
  const man = DADOS.dados_graficos?.[nome];
  if (!man) return Promise.reject(new Error("índice sem dados_graficos." + nome));
  if (!PROMESSAS_GRAFICOS[nome]) {
    PROMESSAS_GRAFICOS[nome] = fetch("./" + man.arquivo + "?v=" + encodeURIComponent(DADOS.atualizado_em || ""))
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .catch((e) => { delete PROMESSAS_GRAFICOS[nome]; throw e; });   // "Tentar de novo" baixa de novo
  }
  return PROMESSAS_GRAFICOS[nome];
}

// estado do Visão geral na URL (pago=dia, caminho=AAAA, so=privados), sem apagar o resto
function gravarParamGeral(chave, valor) {
  const p = Object.fromEntries(Comum.lerParams());
  if (valor) p[chave] = valor; else delete p[chave];
  Comum.gravarParams(p);
}

// Caixa nova antes do 1º export com os arquivos: um aviso no lugar do gráfico. Fora da tela
// a caixa recolhe; na tela fica a altura reservada — nada se desloca à vista (CLS).
function avisarIndisponivel(box, grafico, outros) {
  const r = box.getBoundingClientRect();
  const naTela = !!box.offsetParent && r.top < innerHeight && r.bottom > 0;
  grafico.insertAdjacentHTML("beforeend",
    '<p class="aviso-grafico">Este gráfico fica disponível a partir da próxima atualização da base (diária).</p>');
  if (naTela) { outros.forEach((el) => { el.style.visibility = "hidden"; }); return; }
  grafico.style.setProperty("--altura-grafico", "48px");
  grafico.style.minWidth = "0";
  outros.forEach((el) => { el.style.display = "none"; });
}

function initGraficosMovimento() {
  ligarEscalaPago();
  ligarCaminho();
  initCalendario();
  initCaminho();
}

// Mesmos dias resumidos por mês (tabela dos leitores de tela do Diário e do calendário):
// ~470 linhas de dias seriam navegáveis só uma a uma; o mês traz o total, os documentos e
// o maior dia — os picos que o desenho mostra. O dia a dia está no Detalhamento.
function resumoCalendarioPorMes() {
  const meses = new Map();
  for (const [dia, v, n] of CALENDARIO.linhas) {
    const m = meses.get(dia.slice(0, 7)) || { v: 0, n: 0, maior: null };
    m.v += v; m.n += n;
    if (!m.maior || v > m.maior[1]) m.maior = [dia, v];
    meses.set(dia.slice(0, 7), m);
  }
  return [...meses].map(([k, m]) => [`${MESES[+k.slice(5)]}/${k.slice(0, 4)}${parcialDia(k + "-01") ? " (parcial)" : ""}`,
    compacto(m.v), m.n.toLocaleString("pt-BR"), `${dataBR(m.maior[0])} (${compacto(m.maior[1])})`]);
}
const CABECALHOS_DIAS = ["Mês", "Pago", "Pagamentos", "Maior dia"];
const maioresDias = (k) => [...CALENDARIO.linhas].sort((a, b) => b[1] - a[1]).slice(0, k);

// Dica de um dia (Diário e calendário): pago, documentos e as notas do dia
function dicaDia([dia, v, n, anul], p, cor) {
  const notas = [];
  if (!n) notas.push("Nenhum pagamento registrado neste dia.");
  else if (!(v > 0)) notas.push("Sem pagamento líquido: as anulações (estornos) igualam ou superam os pagamentos.");
  else if (anul) notas.push(`Inclui ${anul.toLocaleString("pt-BR")} anulaç${anul === 1 ? "ão" : "ões"} (estorno de pagamento).`);
  if (parcialDia(dia)) notas.push(NOTA_PARCIAL);
  return Comum.dicaGrafico(`${diaSemana(dia)}, ${dataBR(dia)}`, [
    [cor || p.serie, "Pago no dia", brlc(v), "p"],
    [null, "Pagamentos", n.toLocaleString("pt-BR")],
  ], notas.join(" "), parcialDia(dia));
}

// ── Pago por mês: Mensal | Diário ──
// A escala Diária desenha o calendário em barras no MESMO contêiner, com régua de zoom
// (começa nos últimos 120 dias); a Mensal é o gráfico do M7, intacto (DEF_MENSAL).
let pagoEscala = Comum.lerParams().get("pago") === "dia" ? "dia" : "mes";
let DEF_MENSAL = null;
let janelaDiario = null;   // [início, fim] do zoom: sobrevive à troca de tema e de escala
const ouvirZoomDiario = (chart) => chart.on("datazoom", Comum.debounce(() => {
  if (pagoEscala !== "dia" || chart.isDisposed()) return;
  const dz = chart.getOption().dataZoom?.[0];
  if (dz && dz.startValue != null) janelaDiario = [dz.startValue, dz.endValue];
}, 120));

function desenharMensal() {
  if (!DEF_MENSAL) return;
  if (pagoEscala === "dia" && !CALENDARIO?.linhas?.length) {
    // escala pedida pelo link (?pago=dia): espera o calendário; sem ele (ou vazio), fica a Mensal
    baixarDadosGrafico("calendario").then((c) => { CALENDARIO = c; if (!c.linhas?.length) pagoEscala = "mes"; },
      () => { pagoEscala = "mes"; })
      .then(() => { marcarAlternancia("#pago-escala button", (b) => b.dataset.escala === pagoEscala); desenharMensal(); });
    return;
  }
  const dia = pagoEscala === "dia";
  Comum.grafico("ch-mensal", dia ? defDiario() : DEF_MENSAL);
  document.querySelector("#box-mensal .nota-parcial").hidden = dia || !(DADOS.resumo?.meses_parciais || []).length;
  document.getElementById("nota-diario").hidden = !dia;
}

function ligarEscalaPago() {
  const tem = !!DADOS.dados_graficos?.calendario;
  marcarAlternancia("#pago-escala button", (b) => b.dataset.escala === pagoEscala);
  document.querySelectorAll("#pago-escala button").forEach((b) => {
    if (b.dataset.escala === "dia" && !tem) {
      b.disabled = true;
      b.title = "O pago por dia fica disponível a partir da próxima atualização da base.";
    }
    b.addEventListener("click", () => definirEscalaPago(b.dataset.escala));
  });
  // Ctrl + roda (e a pinça do trackpad, que chega como roda com Ctrl) aproxima o Diário em
  // torno do cursor; sem o Ctrl a roda rola a página, como em todo gráfico do site
  document.getElementById("ch-mensal").addEventListener("wheel", (e) => {
    const chart = pagoEscala === "dia" && e.ctrlKey && e.deltaY && window.echarts?.getInstanceByDom(e.currentTarget);
    const dz = chart && chart.getOption().dataZoom?.[0];
    if (!dz) return;
    e.preventDefault();   // senão o navegador amplia a página inteira
    const minT = tempoLocal(CALENDARIO.linhas[0][0].slice(0, 8) + "01"), maxT = tempoLocal(CALENDARIO.ate);
    const ini = dz.startValue, fim = dz.endValue;
    const r = e.currentTarget.getBoundingClientRect();
    const t = Math.min(Math.max(chart.convertFromPixel({ xAxisIndex: 0 }, e.clientX - r.left), ini), fim);
    const vao = Math.min(Math.max((fim - ini) * (e.deltaY < 0 ? 0.8 : 1.25), 14 * DIA_MS), maxT - minT);
    const novo = Math.min(Math.max(t - (t - ini) * vao / (fim - ini), minT), maxT - vao);
    chart.dispatchAction({ type: "dataZoom", startValue: novo, endValue: novo + vao });
  }, { passive: false });
  // em tela de toque o arrasto dentro do gráfico prenderia a rolagem da página: só a régua
  document.getElementById("nota-diario").textContent = "Cada barra é um dia (pagamentos pela data). " +
    (matchMedia("(pointer: coarse)").matches
      ? "Arraste as alças da régua abaixo do gráfico para mudar o período."
      : "Arraste a régua abaixo do gráfico, ou o próprio gráfico, para navegar; Ctrl + roda do mouse aproxima.") +
    ((DADOS.resumo?.meses_parciais || []).length ? " * Mês parcial em destaque: o valor ainda vai subir." : "");
}

async function definirEscalaPago(escala) {
  if (escala === pagoEscala) return;
  if (escala === "dia" && !CALENDARIO) {
    try { CALENDARIO = await baixarDadosGrafico("calendario"); }
    catch (e) { Comum.toast("Não foi possível carregar o pago por dia agora. Tente de novo."); return; }
  }
  if (escala === "dia" && !CALENDARIO.linhas?.length) { Comum.toast("Ainda não há pagamentos na base."); return; }
  pagoEscala = escala;
  marcarAlternancia("#pago-escala button", (b) => b.dataset.escala === pagoEscala);
  desenharMensal();
  gravarParamGeral("pago", escala === "dia" ? "dia" : "");
}

const rotuloDiaEixo = (v) => {
  const d = new Date(v);
  return d.getDate() === 1 ? `${MESES[d.getMonth() + 1]}/${String(d.getFullYear()).slice(2)}`
    : `${d.getDate()} ${MESES[d.getMonth() + 1].toLowerCase()}`;
};

function defDiario() {
  return {
    eventos: ouvirZoomDiario,
    opcao: (p) => {
      const { linhas, ate } = CALENDARIO;
      const fim = tempoLocal(ate);
      const [ini, fimJanela] = janelaDiario || [fim - 119 * DIA_MS, fim];
      const parciais = (DADOS.resumo?.meses_parciais || []).slice().sort();
      const zoom = { xAxisIndex: 0, startValue: ini, endValue: fimJanela, minValueSpan: 14 * DIA_MS };
      return {
        grid: { left: 4, right: 14, top: 14, bottom: 58, containLabel: true },
        tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" }, formatter: (ps) => dicaDia(ps[0].value, p) },
        xAxis: { type: "time", min: linhas[0][0].slice(0, 8) + "01", max: ate,
          axisLabel: { hideOverlap: true, margin: 10, formatter: rotuloDiaEixo } },
        yAxis: { type: "value", min: 0, splitNumber: p.celular ? 4 : 5, axisLabel: { formatter: (v) => Comum.compactoEixo(v) } },
        dataZoom: [
          // arrastar o gráfico desloca a janela. zoomLock: o zoom de roda do ECharts captura a roda
          // mesmo sem o Ctrl (a página parava de rolar sobre o gráfico) — o Ctrl + roda é da página
          // (ligarEscalaPago). No toque, arrastar o gráfico rolaria a página: fica só a régua
          { type: "inside", ...zoom, zoomLock: true, moveOnMouseMove: true, disabled: matchMedia("(pointer: coarse)").matches },
          { type: "slider", ...zoom, height: 26, bottom: 6, left: 6, right: 14, brushSelect: false,
            showDetail: !p.celular, labelFormatter: (v) => dataBR(isoLocal(v)),
            dataBackground: { lineStyle: { color: p.muted, width: 0.5, opacity: 0.6 }, areaStyle: { color: p.muted, opacity: 0.18 } },
            selectedDataBackground: { lineStyle: { color: p.ouroLinha, width: 0.6 }, areaStyle: { color: p.ouro, opacity: 0.3 } },
            moveHandleStyle: { color: p.linha, opacity: 1 },
            emphasis: { handleStyle: { borderColor: p.ouroLinha }, moveHandleStyle: { color: p.ouro } } },
        ],
        series: [{
          name: "Pago no dia", type: "bar", barMaxWidth: 12, barMinHeight: 1,
          // mês parcial: barra mais clara e a faixa marcada (o valor ainda vai subir)
          data: linhas.map((l) => (parcialDia(l[0]) ? { value: l, itemStyle: { opacity: 0.5 } } : { value: l })),
          itemStyle: { color: p.serie, borderRadius: [2, 2, 0, 0] }, emphasis: { itemStyle: { color: p.ouroLinha } },
          markArea: parciais.length ? {
            silent: true, itemStyle: { color: p.ouroFill },
            // no celular a faixa é estreita: o rótulo encosta na borda direita e cresce para dentro
            label: { show: true, position: p.celular ? "insideTopRight" : "insideTop", distance: 6, color: p.ouroLinha,
              fontFamily: p.mono, fontSize: 10.5, formatter: "mês parcial*" },
            data: [[{ xAxis: tempoLocal(parciais[0] + "-01") - DIA_MS / 2 }, { xAxis: fim + DIA_MS / 2 }]],
          } : undefined,
        }],
      };
    },
    acessivel: () => {
      const [top] = maioresDias(1);
      return {
        descricao: `Pago por dia, de ${dataBR(CALENDARIO.linhas[0][0])} a ${dataBR(CALENDARIO.ate)}, em barras; a régua ` +
          `abaixo do gráfico muda o período (começa nos últimos 120 dias). Maior dia: ${diaSemana(top[0])}, ` +
          `${dataBR(top[0])}, com ${compacto(top[1])}. A tabela resume os dias por mês, com o maior dia de cada um.`,
        cabecalhos: CABECALHOS_DIAS, linhas: resumoCalendarioPorMes(),
      };
    },
  };
}

// ── Calendário de pagamentos (calendário + mapa de calor) ──
// Um bloco por ano (no celular, por semestre); a cor é a faixa do dia entre os quintis dos
// dias com pagamento (a mesma régua em todos os anos). Altura reservada no CSS (cqw) com
// a mesma conta de medidasCalendario — o desenho não empurra a página.
let quebrasCal = null;
function quebrasCalendario() {
  if (!quebrasCal) {
    const xs = CALENDARIO.linhas.map((l) => l[1]).filter((v) => v > 0).sort((a, b) => a - b);
    const q = (f) => {   // interpolação linear (numpy "linear")
      const pos = (xs.length - 1) * f, i = Math.floor(pos);
      return xs[i] + (xs[Math.min(i + 1, xs.length - 1)] - xs[i]) * (pos - i);
    };
    quebrasCal = xs.length ? [0.2, 0.4, 0.6, 0.8].map(q) : [0, 0, 0, 0];
  }
  return quebrasCal;
}

function anosCalendario() {
  const a0 = +CALENDARIO.linhas[0][0].slice(0, 4), a1 = +CALENDARIO.ate.slice(0, 4);
  return Array.from({ length: a1 - a0 + 1 }, (_, i) => a0 + i);
}
function semanasNoBloco([a, b]) {   // colunas do bloco: do domingo da 1ª semana ao último dia
  const ini = new Date(a + "T12:00:00"), fim = new Date(b + "T12:00:00");
  return Math.floor((fim.getTime() - (ini.getTime() - ini.getDay() * DIA_MS)) / DIA_MS / 7) + 1;
}
// O tamanho da célula sai da largura (as semanas do bloco mais largo) e, por garantia, da
// altura reservada no CSS — as constantes daqui são as do --altura-grafico de #ch-calendario.
function medidasCalendario(larg, alt, celular) {
  const anos = anosCalendario();
  const blocos = celular ? anos.flatMap((a) => [[`${a}-01-01`, `${a}-06-30`], [`${a}-07-01`, `${a}-12-31`]])
    : anos.map((a) => [`${a}-01-01`, `${a}-12-31`]);
  const esq = celular ? 22 : 58, dir = 4, topo = 24, entre = celular ? 34 : 40;
  const pelaLargura = (larg - esq - dir) / Math.max(...blocos.map(semanasNoBloco));
  const pelaAltura = alt ? (alt - topo - 6 - (blocos.length - 1) * entre) / (7 * blocos.length) : Infinity;
  return { blocos, esq, topo, entre, cel: Math.max(5, Math.min(22, pelaLargura, pelaAltura)) };
}

function opcaoCalendario(p, larg) {
  const el = document.getElementById("ch-calendario");
  const m = medidasCalendario(larg, el.clientHeight, p.celular);
  const porDia = new Map(CALENDARIO.linhas.map((l) => [l[0], l]));
  const ate = CALENDARIO.ate;
  const calendar = [], series = [];
  m.blocos.forEach(([a, b], i) => {
    calendar.push({
      range: [a, b], orient: "horizontal", cellSize: [m.cel, m.cel], left: m.esq,
      top: m.topo + i * (7 * m.cel + m.entre),
      itemStyle: { color: p.card, borderColor: p.linha, borderWidth: 0.6 },   // dia ainda sem dado
      splitLine: { show: true, lineStyle: { color: p.muted, width: 1, opacity: 0.45 } },
      dayLabel: { firstDay: 0, nameMap: p.celular ? ["", "S", "", "Q", "", "S", ""] : ["", "seg", "", "qua", "", "sex", ""],
        color: p.muted, fontFamily: p.sans, fontSize: p.celular ? 9.5 : 10.5, margin: 6 },
      monthLabel: { color: p.muted, fontFamily: p.sans, fontSize: p.celular ? 10.5 : 11.5, margin: 6, align: "left",
        formatter: (x) => {   // no celular o ano vai no 1º mês de cada semestre
          const mes = +x.M;
          return MESES[mes] + (p.celular && (mes === 1 || mes === 7) ? "/" + String(x.yyyy).slice(2) : "") +
            (mesParcial(+x.yyyy, mes) ? "*" : "");
        } },
      yearLabel: { show: !p.celular, position: "left", margin: 34, color: p.tinta, fontFamily: p.sans,
        fontSize: 14, fontWeight: 800 },
    });
    const dias = [], parciais = [];
    const ultimo = b < ate ? b : ate;
    for (let t = new Date(a + "T12:00:00").getTime(); ; t += DIA_MS) {   // meio-dia: imune a horário de verão
      const d = isoLocal(t);
      if (d > ultimo) break;
      (parcialDia(d) ? parciais : dias).push(porDia.get(d) || [d, 0, 0, 0]);
    }
    const serie = { type: "heatmap", coordinateSystem: "calendar", calendarIndex: i,
      itemStyle: { borderColor: p.card, borderWidth: p.celular ? 1.5 : 2 },
      emphasis: { itemStyle: { borderColor: p.tinta, borderWidth: 1.5 } } };
    series.push({ ...serie, data: dias });
    // mês parcial: hachurado (o valor do dia ainda pode subir) — numa série à parte, com UMA
    // hachura: hachura por dia, cada uma com a cor da célula, dobrava o custo do desenho
    if (parciais.length) series.push({ ...serie, data: parciais, itemStyle: { ...serie.itemStyle, decal: {
      symbol: "rect", symbolSize: 1, color: `rgba(${hexRgb(p.tinta).join(",")},.35)`, dashArrayX: [1, 0],
      dashArrayY: [2, 3], rotation: Math.PI / 4 } } });
  });
  const q = quebrasCalendario();
  return {
    // centenas de células: sem animação de entrada (cada quadro repintaria todas)
    animation: false,
    tooltip: { confine: true, formatter: (e) => dicaDia(e.value, p, e.color) },
    calendar, series,
    // a cor é a faixa do valor (quintis dos dias com pagamento): uma regra para todas as células,
    // no lugar de um estilo por dia; a legenda escreve as mesmas faixas
    visualMap: { type: "piecewise", show: false, dimension: 1, seriesIndex: series.map((_, k) => k),
      pieces: [{ lte: 0, color: p.neutro }, ...p.rampa.map((cor, k) => ({ gt: k ? q[k - 1] : 0,
        ...(k < 4 ? { lte: q[k] } : {}), color: cor }))] },
  };
}

function pintarLegendaCalendario() {
  const ul = document.getElementById("cal-legenda");
  if (!ul || !CALENDARIO?.linhas?.length) return;
  const p = Comum.paleta(), q = quebrasCalendario();
  ul.querySelectorAll(".sw[data-cor]").forEach((sw) => {
    const c = sw.dataset.cor;
    sw.style.background = c === "neutro" ? p.neutro
      : c === "parcial" ? `repeating-linear-gradient(135deg, ${p.rampa[2]} 0 2px, ${misturar(p.rampa[2], p.tinta, 0.35)} 2px 3px)`
      : p.rampa[+c];
  });
  const faixas = [`até ${compacto(q[0])}`, `${compacto(q[0])} a ${compacto(q[1])}`, `${compacto(q[1])} a ${compacto(q[2])}`,
    `${compacto(q[2])} a ${compacto(q[3])}`, `acima de ${compacto(q[3])}`];
  ul.querySelectorAll(".faixa").forEach((s, i) => { s.textContent = faixas[i]; s.classList.remove("reserva"); });
}
addEventListener("temamudou", pintarLegendaCalendario);

function initCalendario() {
  const box = document.getElementById("box-calendario"), el = document.getElementById("ch-calendario");
  const legenda = document.getElementById("cal-legenda"), nota = document.getElementById("cal-nota");
  if (!DADOS.dados_graficos?.calendario) { avisarIndisponivel(box, el, [legenda, nota]); return; }
  baixarDadosGrafico("calendario").then((c) => {
    CALENDARIO = c;
    if (!c.linhas?.length) { avisarIndisponivel(box, el, [legenda, nota]); return; }
    legenda.style.visibility = "";
    renderCalendario();
  }, () => {
    legenda.style.visibility = "hidden";
    Comum.estadoErro(el, "Não foi possível carregar o calendário de pagamentos agora. " +
      "Os demais gráficos e tabelas da página seguem disponíveis.", initCalendario);
  });
}

function renderCalendario() {
  const el = document.getElementById("ch-calendario");
  const anos = anosCalendario();
  if (anos.length !== 2) el.style.setProperty("--anos", anos.length);   // o CSS reserva 2 anos
  pintarLegendaCalendario();
  Comum.grafico(el, {
    dependeDaLargura: true,
    opcao: opcaoCalendario,
    acessivel: {
      descricao: `Calendário de ${anos.join(" e ")} com o total pago em cada dia, em cinco faixas de dourado ` +
        "(quintis dos dias com pagamento). Maiores dias: " +
        maioresDias(3).map((x) => `${dataBR(x[0])} (${compacto(x[1])})`).join(", ") +
        `. Dados até ${dataBR(CALENDARIO.ate)}. A tabela resume os dias por mês, com o maior dia de cada um.`,
      cabecalhos: CABECALHOS_DIAS, linhas: resumoCalendarioPorMes(),
    },
  });
}

// ── Caminho do dinheiro (Sankey): grupo da fonte → função → favorecido ──
// Um ano por vez, todos os favorecidos ou só os fornecedores privados (sem os entes
// públicos do índice). O clique num favorecido abre o raio-X (link pronto no arquivo).
let fluxoAno = "", fluxoModo = Comum.lerParams().get("so") === "privados" ? "privados" : "todos";
let caminhoPorId = new Map();

// nome da origem em caixa alta → exibição: mesma regra de nomeLegivel (favorecido-app.js),
// só para os rótulos do gráfico — a vitrine aprovada; candidata à camada comum
const SIGLAS_NOME = new Set(["LTDA", "EIRELI", "ME", "EPP", "SA", "S/A", "S.A", "S.A.", "SPE", "CIA", "IPREV", "CET",
  "COHAB", "PRODESAN", "CAPEP", "IPS", "SABESP", "CPFL", "INSS", "FGTS", "SUS", "ONG", "OSC", "OSCIP",
  "APAE", "SESC", "SENAC", "SESI", "SENAI", "UPA", "UBS", "SP", "RJ", "MG", "BR"]);
const CONECTIVOS_NOME = new Set(["A", "O", "AS", "OS", "AO", "AOS", "À", "ÀS", "DE", "DA", "DO", "DAS", "DOS",
  "E", "EM", "NA", "NO", "NAS", "NOS", "PARA", "POR", "COM"]);
function nomeLegivel(nome) {
  if (!nome || /[a-zß-ÿ]/.test(nome)) return nome;
  const inicial = (p) => p.charAt(0) + p.slice(1).toLowerCase();
  return nome.trim().split(/\s+/).map((w, i) => {
    const nu = w.replace(/[.,;:]+$/, "");
    if (SIGLAS_NOME.has(nu) || /\d/.test(w) || !/[AEIOUYÁÉÍÓÚÂÊÔÃÕÀÜ]/.test(w) ||
        /^(I{1,3}|IV|VI{0,3}|IX|X{1,3})$/.test(nu)) return w;
    if (i > 0 && CONECTIVOS_NOME.has(w)) return w.toLowerCase();
    return w.split("-").map((p) => p.split("'").map(inicial).join("'")).join("-");
  }).join(" ");
}

// nome inteiro (dica e tabela) e cor de cada nó: fonte em navy, função em dourado,
// favorecido em cinza; "Demais" no cinza de referência
const nomeNo = (n) => (!n ? "—" : n.demais || n.nivel === 0 ? n.nome : n.nivel === 1 ? nomeFuncao(n.nome) : nomeLegivel(n.nome));
const corNo = (n, p) => (n.demais ? p.ref : [p.serie, p.ouro, p.muted][n.nivel]);
const semCodigoFonte = (f) => String(f).replace(/^\d{2}-\d+\s*-\s*/, "");

function recorteCaminho() {
  const s = FLUXO.anos[fluxoAno][fluxoModo];
  // valor ≤ 0 (anulações acima do pago) não tem espessura: fica na tabela, fora do desenho
  const nos = s.nos.filter((n) => n.valor > 0), ids = new Set(nos.map((n) => n.id));
  return { ...s, nos, ligacoes: s.ligacoes.filter(([a, b, v]) => v > 0 && ids.has(a) && ids.has(b)) };
}

// rótulo "nome  valor" que cabe inteiro: na coluna da direita, a margem reservada; nas
// outras, o vão até a próxima coluna (o rótulo passa por cima das faixas)
function rotulosCaminho(nos, p, larg, direita) {
  const fNome = `600 ${p.celular ? 11 : 12}px Manrope, sans-serif`;
  const fValor = `400 ${p.celular ? 10 : 11}px "IBM Plex Mono", monospace`;
  const vao = (larg - 2 - direita - 3 * 12) / 2;
  const rt = (s) => String(s).replace(/[{}|]/g, "");   // chave e barra quebrariam o rich text
  const mapa = new Map();
  for (const n of nos) {
    const valor = compacto(n.valor);
    const cabe = (n.nivel === 2 ? direita : vao) - 6 - larguraTexto(valor, fValor) - 16;
    let nome = nomeNo(n);
    if (larguraTexto(nome, fNome) > cabe) {
      while (nome.length > 4 && larguraTexto(nome + "…", fNome) > cabe) nome = nome.slice(0, -1);
      nome = nome.trimEnd() + "…";
    }
    mapa.set(n.id, `{n|${rt(nome)}}  {v|${rt(valor)}}`);
  }
  return mapa;
}

function dicaCaminho(e, p) {
  const total = FLUXO.anos[fluxoAno][fluxoModo].total;
  if (e.dataType === "edge") {
    const a = caminhoPorId.get(e.data.source), b = caminhoPorId.get(e.data.target);
    return Comum.dicaGrafico(`${nomeNo(a)} → ${nomeNo(b)}`, [[corNo(a, p), "Pago", brlc(e.value), "p"],
      [null, `Parte de ${nomeNo(a)}`, pctDe(e.value, a.valor)]]);
  }
  const n = caminhoPorId.get(e.name);
  if (!n) return "";
  const doc = n.documento ? [null, n.documento.includes("/") ? "CNPJ" : n.documento.includes("*") ? "CPF" : "Documento",
    n.documento] : null;
  const nota = n.demais
    ? (n.qtd ? `${n.qtd.toLocaleString("pt-BR")} favorecidos fora dos maiores — a lista inteira está na aba Favorecidos.`
      : `Inclui: ${(n.inclui || []).map((x) => (n.nivel === 1 ? nomeFuncao(x) : x)).join(", ")}.`)
    : n.nivel === 0 ? `Principais fontes: ${(n.fontes || []).map(([f]) => semCodigoFonte(f)).join("; ")}.`
    : n.nivel === 2 ? (n.ente_publico ? "Ente público. " : "") + "Clique para abrir o raio-X." : "";
  return Comum.dicaGrafico(nomeNo(n), [[corNo(n, p), `Pago em ${fluxoAno}`, brlc(n.valor), "p"],
    [null, "Do total do gráfico", pctDe(n.valor, total)], doc], nota);
}

function opcaoCaminho(p, larg) {
  const { nos, ligacoes } = recorteCaminho();
  const direita = p.celular ? 238 : 292;
  const rotulos = rotulosCaminho(nos, p, larg, direita);
  const fonte = p.celular ? 11 : 12;
  const contorno = { textBorderColor: p.card, textBorderWidth: 3 };   // legível por cima das faixas
  return {
    animation: false,
    tooltip: { confine: true, formatter: (e) => dicaCaminho(e, p) },
    series: [{
      type: "sankey", left: 2, right: direita, top: 6, bottom: 6, nodeWidth: 12, nodeGap: p.celular ? 14 : 15,
      // a ordem do arquivo (maiores primeiro, "Demais" por último) é a ordem na coluna
      nodeAlign: "justify", layoutIterations: 0, draggable: false,
      data: nos.map((n) => ({ name: n.id, value: n.valor, depth: n.nivel, itemStyle: { color: corNo(n, p), borderWidth: 0 } })),
      links: ligacoes.map(([a, b, v]) => ({ source: a, target: b, value: v })),
      lineStyle: { color: "source", opacity: Comum.temaAtual() === "escuro" ? 0.3 : 0.2, curveness: 0.5 },
      emphasis: { focus: "adjacency", lineStyle: { opacity: 0.55 } },
      blur: { lineStyle: { opacity: 0.06 }, itemStyle: { opacity: 0.35 }, label: { opacity: 0.4 } },
      label: { position: "right", distance: 6, color: p.tinta, fontFamily: p.sans, fontSize: fonte, ...contorno,
        formatter: (e) => rotulos.get(e.name) || "",
        rich: { n: { fontFamily: p.sans, fontWeight: 600, fontSize: fonte, color: p.tinta, ...contorno },
          v: { fontFamily: p.mono, fontSize: fonte - 1, color: p.muted, ...contorno } } },
      labelLayout: { hideOverlap: true },
    }],
  };
}

function ligarCaminho() {
  const sel = document.getElementById("caminho-ano");
  sel.addEventListener("change", () => {
    fluxoAno = sel.value;
    gravarParamGeral("caminho", fluxoAno === sel.options[0]?.value ? "" : fluxoAno);   // o ano mais recente fica fora
    renderCaminho();
  });
  marcarAlternancia("#caminho-modo button", (b) => b.dataset.modo === fluxoModo);
  document.querySelectorAll("#caminho-modo button").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.modo === fluxoModo || !FLUXO) return;
    fluxoModo = b.dataset.modo;
    marcarAlternancia("#caminho-modo button", (x) => x.dataset.modo === fluxoModo);
    gravarParamGeral("so", fluxoModo === "privados" ? "privados" : "");
    renderCaminho();
  }));
  // a caixa que rola entra no Tab só quando rola de fato (no desktop largo não rola)
  addEventListener("resize", Comum.debounce(ajustarRolagemCaminho, 200));
}
function ajustarRolagemCaminho() {
  const w = document.getElementById("caminho-rolagem");
  if (w) w.tabIndex = w.scrollWidth > w.clientWidth + 1 ? 0 : -1;
}

function initCaminho() {
  const box = document.getElementById("box-caminho"), el = document.getElementById("ch-caminho");
  const controles = box.querySelector(".caminho-controles"), nota = document.getElementById("caminho-nota");
  const dica = box.querySelector(".dica-scroll");
  if (!DADOS.dados_graficos?.fluxo) { avisarIndisponivel(box, el, [controles, nota, dica]); ajustarRolagemCaminho(); return; }
  baixarDadosGrafico("fluxo").then((fx) => {
    FLUXO = fx;
    const anos = Object.keys(fx.anos || {}).sort().reverse();
    if (!anos.length) { avisarIndisponivel(box, el, [controles, nota, dica]); return; }
    const pedido = Comum.lerParams().get("caminho");
    fluxoAno = anos.includes(pedido) ? pedido : anos[0];
    const sel = document.getElementById("caminho-ano");
    sel.innerHTML = anos.map((a) => `<option value="${a}">${a}</option>`).join("");
    sel.value = fluxoAno;
    renderCaminho();
  }, () => Comum.estadoErro(el, "Não foi possível carregar o caminho do dinheiro agora. " +
    "Os demais gráficos e tabelas da página seguem disponíveis.", initCaminho));
}

function renderCaminho() {
  const a = FLUXO.anos[fluxoAno], s = a[fluxoModo];
  caminhoPorId = new Map(s.nos.map((n) => [n.id, n]));
  const ate = DADOS.dados_ate && fluxoAno === DADOS.dados_ate.slice(0, 4) ? ` (até ${dataBR(DADOS.dados_ate.slice(0, 10))})` : "";
  const nota = document.getElementById("caminho-nota");
  nota.classList.remove("reserva");
  nota.textContent = fluxoModo === "privados"
    ? `${fluxoAno}${ate}: ${compacto(s.total)} pagos a fornecedores privados. Fora do gráfico: os entes públicos ` +
      `(${compacto(a.todos.total - s.total)} — Município, IPREV, CAPEP, bancos públicos…) e o extra-orçamentário (${compacto(a.extra)}).`
    : `${fluxoAno}${ate}: ${compacto(s.total)} pagos. Fora do gráfico: o extra-orçamentário (${compacto(a.extra)}).`;
  const maior = (k) => s.nos.find((n) => n.nivel === k && !n.demais);
  Comum.grafico("ch-caminho", {
    dependeDaLargura: true,
    opcao: opcaoCaminho,
    eventos: (chart) => chart.on("click", (e) => {
      if (e.dataType !== "node") return;
      const n = caminhoPorId.get(e.name);
      if (n?.link) location.href = n.link;
      else if (n?.demais && n.qtd) Comum.toast(`${n.qtd.toLocaleString("pt-BR")} favorecidos fora dos maiores — veja a aba Favorecidos.`);
    }),
    acessivel: {
      descricao: `Caminho do dinheiro pago em ${fluxoAno}${ate}${fluxoModo === "privados" ? ", só fornecedores privados" : ""}: ` +
        `${compacto(s.total)}, da fonte do recurso para a função e dela para quem recebeu, sem o extra-orçamentário. ` +
        [["Maior fonte", maior(0)], ["maior função", maior(1)], ["maior favorecido", maior(2)]]
          .filter(([, n]) => n).map(([r, n]) => `${r}: ${nomeNo(n)} (${compacto(n.valor)})`).join("; ") + ".",
      cabecalhos: ["De", "Para", "Pago"],
      linhas: s.ligacoes.map(([de, para, v]) => [nomeNo(caminhoPorId.get(de)), nomeNo(caminhoPorId.get(para)), compacto(v)]),
    },
  });
  ajustarRolagemCaminho();
}

// ── Alertas ──────────────────────────────────────────────────────────────────
const ALERTA_LABELS = {
  favorecido_recorrente: "Grande recebedor recorrente", concentracao: "Concentração em função",
  pico_mensal: "Pico mensal", extra_orcamentario: "Extra-orçamentário",
  fracionamento: "Triagem de fracionamento", favorecido_novo: "Favorecido novo",
  crescimento_yoy: "Crescimento no mesmo período", pf_sensivel: "Pessoa física sensível",
  pico_favorecido: "Pico de um favorecido", pico_elemento: "Pico de um elemento",
  dados_duplicidade: "Dados: duplicidade na origem", dados_particao: "Dados: coleta falhou",
  dados_cobertura: "Dados: cobertura incompleta", dados_taxa: "Dados: taxa não validada",
  dados_nao_localizado: "Dados: empenho não localizado",
  prazo_rapido: "Pago bem mais rápido que a fila", prazo_lento: "Pago bem mais devagar que a fila",
  pago_acima_liquidado: "Pago acima do liquidado",
};
const CLASSE_LABELS = { contexto: "Contexto", anomalia: "Anomalia a conferir", inconsistencia: "Inconsistência de dados" };
const ESTADO_LABELS = { novo: "novo", persistente: "persistente", sem_historico: "sem histórico" };
const SEV_LABELS = { alta: "Alta", media: "Média", baixa: "Baixa" };
// etiqueta da triagem de fracionamento, tirada do espelho do PNCP (Preço comparado)
const ETIQUETA_LABELS = { provavel_ata: "provável compra por ata (PNCP)", vencedor_pregao: "venceu pregão (PNCP)",
                          dispensa_pncp: "dispensa no PNCP" };
const GRUPO_MIN = 3;   // regra com ≥ N alertas visíveis vira um grupo recolhível (evita 15 cartões seguidos)
// "A conferir" = anomalias + inconsistências (contexto é informação, não achado) —
// a mesma contagem do hub, do "Em resumo" (resumo.alertas_ativos) e da aba.
const aConferir = (a) => a.classe ? a.classe !== "contexto" : a.severidade !== "baixa";

function popularFiltrosAlertas() {
  const lista = DADOS.alertas || [];
  const tipos = [...new Set(lista.map(a => a.tipo))];
  const selT = document.getElementById("alerta-tipo");
  selT.innerHTML = '<option value="">Tipo (todos)</option>' +
    tipos.map(t => `<option value="${esc(t)}">${esc(ALERTA_LABELS[t] || t)}</option>`).join("");
  // severidade: só os valores que existem na lista (um "Alta" fixo sem nenhum alerta alto
  // levava a uma lista vazia)
  const sevs = ["alta", "media", "baixa"].filter(s => lista.some(a => a.severidade === s));
  document.getElementById("alerta-sev").innerHTML = '<option value="">Severidade (todas)</option>' +
    sevs.map(s => `<option value="${s}">${SEV_LABELS[s]}</option>`).join("");
}

// ── Rascunho de requerimento (texto determinístico, só com os campos do alerta) ──
// Requerimento de informação não pode trazer sugestão ou conselho à autoridade (Regimento
// Interno, art. 121): o rascunho só pergunta e pede documentos. O assessor revisa e protocola.
const PEDIDOS_POR_TIPO = {
  fracionamento: ["cópia dos processos de contratação dos empenhos listados", "informação sobre se as compras foram feitas por ata de registro de preços, com o número da ata"],
  pago_acima_liquidado: ["cópia das notas de liquidação e das ordens de pagamento listadas", "justificativa para o valor pago acima do liquidado", "comprovante de eventual estorno ou devolução do valor pago a mais"],
  pf_sensivel: ["cópia do contrato e dos aditivos com a pessoa física", "processo de contratação e critério de escolha", "memória de cálculo dos reajustes aplicados"],
  favorecido_novo: ["contratos e processos de contratação do favorecido no período", "objeto e modalidade de cada contratação"],
  crescimento_yoy: ["contratos, aditivos e ordens de serviço que explicam o aumento", "objeto e modalidade de cada contratação"],
  concentracao: ["contratos e processos de contratação do favorecido na função", "justificativa para a concentração do gasto"],
  pico_mensal: ["relação dos pagamentos do mês com o objeto de cada um", "motivo da concentração de pagamentos no mês"],
  pico_favorecido: ["relação dos pagamentos do mês ao favorecido com o objeto de cada um", "motivo da concentração de pagamentos no mês"],
  pico_elemento: ["relação dos pagamentos do mês no elemento, com favorecido e objeto", "motivo da concentração de pagamentos no mês"],
  prazo_rapido: ["lista da ordem cronológica de pagamentos da fonte de recurso no período (art. 141 da Lei 14.133)", "justificativa publicada para pagamento fora da ordem, se houve"],
  prazo_lento: ["lista da ordem cronológica de pagamentos da fonte de recurso no período (art. 141 da Lei 14.133)", "motivo do atraso (glosa, pendência documental ou falta de caixa) e eventuais juros pagos"],
};
const PEDIDOS_DADOS = ["esclarecimento sobre a divergência nos dados publicados no Portal da Transparência",
                       "os dados corrigidos, se houver erro na publicação"];

function rascunhoRequerimento(a) {
  const pedidos = [...(PEDIDOS_POR_TIPO[a.tipo] || (a.classe === "inconsistencia" ? PEDIDOS_DADOS : [])),
                   ...(a.informacoes_faltantes || [])];
  if (!pedidos.length) pedidos.push("documentos e informações que esclareçam o fato descrito");
  const docs = (a.documentos || []).slice(0, 8).map(d => "   - " + [d.fase ? `${d.fase} ${d.doc}` : (d.doc ? "documento " + d.doc : ""),
    d.empenho ? "empenho " + d.empenho : "", d.data ? "de " + d.data.split("-").reverse().join("/") : "",
    d.valor != null ? brlc(d.valor) : ""].filter(Boolean).join(", "));
  const base = DADOS.dados_ate ? new Date(DADOS.dados_ate.slice(0, 10) + "T12:00:00").toLocaleDateString("pt-BR") : "";
  const fav = a.filtro?.favorecido ? `${a.filtro.favorecido}${a.filtro.documento ? " (" + a.filtro.documento + ")" : ""}` : "";
  const linhas = [
    "REQUERIMENTO Nº ____/____",
    "",
    "Senhor Presidente,",
    "",
    "Requeiro, com fundamento no art. 58, XVIII, da Lei Orgânica do Município de Santos e na forma do " +
    "art. 121 do Regimento Interno [Verificar], seja oficiado ao Excelentíssimo Senhor Prefeito Municipal " +
    `solicitando as seguintes informações sobre: ${a.titulo}.`,
    "",
    ...pedidos.map((p, i) => `${i + 1}. ${p.charAt(0).toUpperCase() + p.slice(1)}${i === pedidos.length - 1 ? "." : ";"}`),
    "",
    "JUSTIFICATIVA",
    "",
    `Triagem automática dos dados abertos do Portal da Transparência da Prefeitura de Santos` +
    `${base ? ` (pagamentos até ${base})` : ""}, no painel de despesas do gabinete: “${a.detalhe}”`,
    ...(fav ? [`Favorecido: ${fav}.`] : []),
    ...(a.valor ? [`Valor envolvido: ${brlc(a.valor)}.`] : []),
    ...(docs.length ? ["Documentos identificados:", ...docs] : []),
    ...(a.link ? [`Recorte dos dados: ${new URL(a.link, location.href).href}`] : []),
    "",
    "O pedido tem caráter de fiscalização e não pressupõe irregularidade: o padrão acima é uma triagem " +
    "automática feita sobre dados públicos, que as informações solicitadas permitirão esclarecer.",
    "",
    "Sala das Sessões, ____ de ______________ de ______.",
    "",
    "Vereador Rui de Rosis Jr.",
  ];
  return linhas.join("\n");
}

// cópia com fallback: a API de área de transferência exige contexto seguro e permissão
async function copiarTexto(texto, aviso) {
  try {
    await navigator.clipboard.writeText(texto);
    Comum.toast(aviso);
    return;
  } catch (e) { /* cai no método antigo */ }
  const ta = document.createElement("textarea");
  ta.value = texto;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove();
  Comum.toast(ok ? aviso : "Não foi possível copiar automaticamente neste navegador.");
}

// todos os casos que acionaram uma regra (os tetos mostram só parte) → CSV
let CANDIDATOS = null;
async function baixarCandidatos(tipo) {
  try {
    if (!CANDIDATOS) {
      const r = await fetch("./despesas/alertas-candidatos.json?v=" + encodeURIComponent(DADOS.atualizado_em || ""));
      if (!r.ok) throw new Error("HTTP " + r.status);
      CANDIDATOS = await r.json();
    }
  } catch (e) {
    Comum.toast("Não foi possível baixar a lista completa. Tente de novo.");
    return;
  }
  const c = CANDIDATOS.campos, v = (l, k) => l[c.indexOf(k)];
  const linhas = CANDIDATOS.linhas.filter(l => !tipo || v(l, "tipo") === tipo);
  Comum.exportarCsv(`alertas-${tipo || "todos"}-casos.csv`,
    ["Regra", "Classe", "Severidade", "Situação", "Desde", "Publicado no painel", "Valor", "Título", "Favorecido",
     "CPF/CNPJ", "Unidade gestora", "Elemento", "Ano", "Etiqueta PNCP", "Link"],
    linhas.map(l => [ALERTA_LABELS[v(l, "tipo")] || v(l, "tipo"), CLASSE_LABELS[v(l, "classe")] || v(l, "classe"),
      SEV_LABELS[v(l, "severidade")] || v(l, "severidade"), ESTADO_LABELS[v(l, "estado")] || "", v(l, "primeiro_em") || "",
      v(l, "publicado") ? "sim" : "não", centavos(v(l, "valor")), v(l, "titulo"), v(l, "favorecido") || "",
      v(l, "documento") || "", v(l, "unidade") || "", v(l, "elemento") || "", v(l, "ano") || "",
      ETIQUETA_LABELS[v(l, "etiqueta")] || "", v(l, "link") ? new URL(v(l, "link"), location.href).href : ""]));
}

// filtros dos alertas na URL (ac/at/as) — Voltar depois de abrir um recorte restaura a triagem.
// Preserva os demais parâmetros (o Detalhamento grava os seus).
function gravarFiltrosAlerta() {
  const p = Object.fromEntries(Comum.lerParams());
  delete p.ac; delete p.at; delete p.as;
  const cl = document.getElementById("alerta-classe").value;
  if (cl !== "conferir") p.ac = cl || "todas";
  p.at = document.getElementById("alerta-tipo").value;
  p.as = document.getElementById("alerta-sev").value;
  Comum.gravarParams(p);
}

function ligarAlertas() {
  const p = Comum.lerParams();
  const sel = (id, v) => { const el = document.getElementById(id);
    if (v != null && [...el.options].some(o => o.value === v)) el.value = v; };
  sel("alerta-classe", p.get("ac") === "todas" ? "" : p.get("ac"));
  sel("alerta-tipo", p.get("at"));
  sel("alerta-sev", p.get("as"));
  ["alerta-tipo", "alerta-sev", "alerta-classe"].forEach(id =>
    document.getElementById(id).addEventListener("change", () => { gravarFiltrosAlerta(); renderAlertas(); }));
  renderAlertas();
  const h = DADOS.alertas_historico, nota = document.getElementById("alertas-historico");
  if (h && nota) {
    nota.textContent = h.disponivel
      ? `Histórico de alertas desde ${new Date(h.desde + "T12:00:00").toLocaleDateString("pt-BR")}: ` +
        `${h.novos} novo(s), ${h.persistentes} persistente(s), ${(h.resolvidos_recentes || []).length} resolvido(s) recentemente.`
      : (h.nota || "Sem histórico de alertas.");
    nota.hidden = false;
  }
}

function renderAlertas() {
  const lista = DADOS.alertas || [];
  const nConferir = lista.filter(aConferir).length;
  const badge = document.getElementById("badge-alertas");
  badge.textContent = nConferir ? `(${nConferir})` : "";
  badge.title = `${nConferir} a conferir · ${lista.length - nConferir} de contexto`;
  const fTipo = document.getElementById("alerta-tipo").value;
  const fSev = document.getElementById("alerta-sev").value;
  const fCl = document.getElementById("alerta-classe")?.value || "";
  const vis = lista.filter(a => (!fTipo || a.tipo === fTipo) && (!fSev || a.severidade === fSev) &&
                                (!fCl || (fCl === "conferir" ? aConferir(a) : (a.classe || "anomalia") === fCl)));

  const cont = document.getElementById("lista-alertas");
  const vazio = document.getElementById("alertas-vazio");
  vazio.hidden = vis.length > 0;
  if (!vis.length) {
    const filtrado = fTipo || fSev || fCl !== "conferir";
    vazio.innerHTML = lista.length && filtrado
      ? 'Nenhum alerta com esses filtros. <button class="btn" type="button" id="alertas-limpar">Limpar filtros</button>'
      : "Nenhum alerta com os limiares atuais.";
    document.getElementById("alertas-limpar")?.addEventListener("click", () => {
      document.getElementById("alerta-classe").value = "conferir";
      document.getElementById("alerta-tipo").value = "";
      document.getElementById("alerta-sev").value = "";
      gravarFiltrosAlerta();
      renderAlertas();
    });
  }
  const docsHtml = (a) => {
    const docs = a.documentos || [];
    if (!docs.length) return "";
    const li = docs.map(d => {
      const partes = [d.data, d.empenho ? "emp. " + d.empenho : "",
                      d.fase ? `${d.fase.toLowerCase()} ${d.doc}` : (d.doc ? "doc. " + d.doc : ""), d.especie || "",
                      d.ug ? d.ug.replace(/^PREFEITURA MUNICIPAL DE SANTOS$/, "PMS") : "",
                      d.reforcos ? `${d.reforcos} reforço(s)` : "", d.anulacoes ? `${d.anulacoes} anulação(ões)` : "",
                      d.elemento || ""].filter(Boolean).join(" · ");
      return `<li>${esc(partes)} — <span class="num">${brlc(d.valor)}</span></li>`;
    }).join("");
    return `<details class="alerta-docs"><summary>${docs.length} documento(s) que acionaram a regra</summary><ul>${li}</ul></details>`;
  };
  const faltamHtml = (a) => (a.informacoes_faltantes || []).length
    ? `<div class="det">Não constam na fonte: ${esc(a.informacoes_faltantes.join(", "))}.</div>` : "";
  const limiteHtml = (a) => a.limite?.verificacao
    ? `<div class="det">Limite usado: ${esc(a.limite.norma || "não cadastrado")} — ${esc(a.limite.verificacao)}.</div>` : "";
  // ações: recorte, raio-X do favorecido (quando o recorte não é o próprio raio-X), PNCP e rascunho
  const acoesHtml = (a) => {
    const ehRaiox = (a.link || "").startsWith("./favorecido.html");
    const raiox = !ehRaiox && a.filtro?.chave
      ? linkRaiox({ chave: a.filtro.chave, nome: a.filtro.favorecido, documento: a.filtro.documento }) : "";
    const pncp = (a.pncp || []).map(p =>
      `<a class="btn btn-mini" href="${esc(p.link)}" target="_blank" rel="noopener" title="${esc(p.objeto || "")}">PNCP ${esc(p.ncp.split("-").pop())} ↗</a>`);
    return `<div class="alerta-acoes">
      ${a.link ? `<a class="alerta-link" href="${esc(a.link)}">${ehRaiox ? "Abrir o raio-X ↗" : "Abrir o recorte ↗"}</a>` : ""}
      ${raiox ? `<a class="btn btn-mini" href="${esc(raiox)}">Raio-X do favorecido ↗</a>` : ""}
      ${pncp.join("")}
      ${a.classe !== "contexto" ? `<button type="button" class="btn btn-mini" data-rascunho="${esc(a.id)}">Copiar rascunho de requerimento</button>` : ""}
    </div>`;
  };
  const cartao = (a) => `
    <div class="alerta ${a.severidade} classe-${esc(a.classe || "anomalia")}" data-link="${esc(a.link || "")}">
      <div class="top">
        <div class="titulo"><span class="sev ${a.severidade}">${esc(SEV_LABELS[a.severidade] || a.severidade)}</span>
          <span class="classe">${esc(CLASSE_LABELS[a.classe] || "")}</span>
          ${a.estado && a.estado !== "sem_historico" ? `<span class="estado ${esc(a.estado)}">${esc(ESTADO_LABELS[a.estado] || a.estado)}</span>` : ""}
          ${a.etiqueta ? `<span class="classe etiqueta">${esc(ETIQUETA_LABELS[a.etiqueta] || a.etiqueta)}</span>` : ""}
          ${esc(a.titulo)}</div>
        <div class="vlr">${a.valor ? brlc(a.valor) : ""}</div>
      </div>
      <div class="det">${esc(a.detalhe)}</div>
      ${limiteHtml(a)}${faltamHtml(a)}${docsHtml(a)}
      ${acoesHtml(a)}
    </div>`;

  // regra com muitos alertas vira um grupo recolhível, na posição do seu 1º alerta;
  // o teto por regra (alertas_regras) é declarado: "os N prioritários de M casos" + CSV de todos
  const porTipo = new Map();
  vis.forEach(a => { if (!porTipo.has(a.tipo)) porTipo.set(a.tipo, []); porTipo.get(a.tipo).push(a); });
  const agrupar = (tipo) => !fTipo && porTipo.get(tipo).length >= GRUPO_MIN;
  const PRIORIDADE = {
    pf_sensivel: "novos primeiro; depois reajuste acima do IPCA, início recente e valor",
    fracionamento: "novos primeiro, depois maior valor; provável compra por ata por último",
  };
  const tetoHtml = (tipo, n) => {
    const r = DADOS.alertas_regras?.[tipo];
    return r && r.candidatos > r.publicados
      ? `<div class="teto">Mostrando os ${n} prioritários (${PRIORIDADE[tipo] || "novos primeiro, depois maior valor"}) ` +
        `de ${r.candidatos.toLocaleString("pt-BR")} casos que acionaram a regra. ` +
        `<button type="button" class="btn btn-mini" data-csv="${esc(tipo)}">Baixar os ${r.candidatos.toLocaleString("pt-BR")} casos (CSV)</button></div>` : "";
  };
  const feitos = new Set();
  cont.innerHTML = vis.map(a => {
    if (!agrupar(a.tipo)) return cartao(a);
    if (feitos.has(a.tipo)) return "";
    feitos.add(a.tipo);
    const itens = porTipo.get(a.tipo);
    // inconsistência: o valor é o que a origem duplicou, não gasto — somar leria como despesa
    const soma = a.classe === "inconsistencia" ? 0 : itens.reduce((t, x) => t + (x.valor || 0), 0);
    const sevs = new Set(itens.map(x => x.severidade));
    const sevHtml = sevs.size === 1
      ? ` <span class="sev ${a.severidade}">${esc(SEV_LABELS[a.severidade] || a.severidade)}</span>` : "";
    return `<details class="alerta-grupo">
      <summary><span>${esc(ALERTA_LABELS[a.tipo] || a.tipo)} — ${itens.length} alertas${sevHtml}</span>
        <span class="vlr">${soma ? brlc(soma) : ""}</span></summary>
      ${tetoHtml(a.tipo, itens.length)}${itens.map(cartao).join("")}
    </details>`;
  }).join("");
  // filtrado por tipo: a lista é a regra inteira — o teto vai no topo
  if (fTipo && vis.length) cont.insertAdjacentHTML("afterbegin", tetoHtml(fTipo, vis.length));

  // clique no cartão abre o recorte (link citável); cliques nos documentos (<details>), em <a>
  // e nos botões seguem o próprio elemento — o grupo recolhível também é <details>, por isso a classe
  cont.querySelectorAll(".alerta").forEach(el => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".alerta-docs, a, button") || getSelection().toString()) return;
      const link = el.getAttribute("data-link");
      if (link) location.href = link;
    });
  });
  cont.querySelectorAll("[data-rascunho]").forEach(b => b.addEventListener("click", () => {
    const a = lista.find(x => x.id === b.dataset.rascunho);
    if (a) copiarTexto(rascunhoRequerimento(a), "Rascunho de requerimento copiado — revise antes de protocolar.");
  }));
  cont.querySelectorAll("[data-csv]").forEach(b => b.addEventListener("click", () => baixarCandidatos(b.dataset.csv)));
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

// Agrega favorecidos a partir do detalhe (execução) por IDENTIDADE (mesma regra do
// export: CNPJ completo une grafias; CPF mascarado só une com o mesmo nome).
function agregarFavDetalhe(predTipo, elemento) {
  const { campos, rows } = FAV_DETALHE;
  const iN = campos.indexOf("nome_favorecido"), iD = campos.indexOf("documento_favorecido"),
        iP = campos.indexOf("pago"), iData = campos.indexOf("data"), iE = campos.indexOf("elemento_despesa");
  const map = new Map();
  for (const r of rows) {
    const doc = r[iD];
    if (!predTipo(doc)) continue;
    if (elemento && r[iE] !== elemento) continue;
    const chave = chaveFavorecido(r[iN], doc);
    let o = map.get(chave);
    if (!o) { o = { chave, nomes: new Map(), documento: doc, valor: 0, qtd: 0, meses: new Set() }; map.set(chave, o); }
    o.nomes.set(r[iN], (o.nomes.get(r[iN]) || 0) + 1);
    o.valor += (r[iP] || 0);
    o.qtd += 1;
    if (r[iData]) o.meses.add(String(r[iData]).slice(0, 7));
  }
  return [...map.values()]
    .map(o => ({ chave: o.chave, nome: nomeExibicao(o.nomes), documento: o.documento, valor: o.valor, qtd: o.qtd,
                 meses: o.meses.size, grafias: o.nomes.size > 1 ? [...o.nomes.keys()] : undefined }))
    .sort((a, b) => b.valor - a.valor)
    .slice(0, 300);
}

// mesma escolha determinística do export (formato.nome_exibicao): sem U+FFFD > mais
// lançamentos > mais longa > alfabética
function nomeExibicao(nomes) {
  return [...nomes.entries()].sort((a, b) =>
    (a[0].includes("\ufffd") - b[0].includes("\ufffd")) || (b[1] - a[1]) || (b[0].length - a[0].length) ||
    a[0].localeCompare(b[0]))[0][0];
}

// Fonte da tabela conforme modo + elemento (com memo p/ não reagregar a cada render).
function fonteFav() {
  // Sem elemento e em modo CNPJ/Todos/Privados: usa o agregado pronto do index (visão caixa/pago).
  if (!favElemento && favModo !== "pf") {
    const all = DADOS.top_favorecidos || [];
    if (favModo === "pj") return all.filter(f => (f.documento || "").includes("/"));
    if (favModo === "privados") return all.filter(f => !f.ente_publico);   // flag do export (formato.eh_ente_publico)
    return all;
  }
  // PF sem elemento: agregado leve pré-computado (dados/pf-resumo.json).
  if (favModo === "pf" && !favElemento && PF_RESUMO) return PF_RESUMO;
  // Qualquer modo com elemento (ou PF sem o índice leve): agrega do detalhe.
  if (!FAV_DETALHE) return [];
  const chave = favModo + "|" + favElemento;
  if (favMemo.chave !== chave) {
    let lista = agregarFavDetalhe(predTipoFav(), favElemento || null);
    if (favModo === "privados") {
      const publicos = new Set(DADOS.entes_publicos || []);
      lista = lista.filter(f => !publicos.has(f.chave));
    }
    favMemo = { chave, lista };
  }
  return favMemo.lista;
}

function renderFavoridosTabela() {
  const bruto = (document.getElementById("q").value || "").trim();
  const termo = semAcento(bruto);
  const termoDig = soDigitos(bruto);
  const fonte = fonteFav();
  let linhas = fonte.map(f => ({
    nome: f.nome || "—", valor: f.valor, qtd: f.qtd, meses: f.meses, documento: f.documento || "",
    chave: f.chave || chaveFavorecido(f.nome, f.documento), grafias: f.grafias || [],
  }));
  if (termo) linhas = linhas.filter(f =>
    semAcento(f.nome).includes(termo) ||
    f.grafias.some(g => semAcento(g).includes(termo)) ||
    (f.documento && (semAcento(f.documento).includes(termo) ||
      (termoDig && soDigitos(f.documento).includes(termoDig)))));
  const dir = favSort.dir === "asc" ? 1 : -1;
  linhas.sort((a, b) => {
    const va = a[favSort.col], vb = b[favSort.col];
    if (typeof va === "string") return va.localeCompare(vb) * dir;
    return (va - vb) * dir;
  });

  const corpo = document.getElementById("corpo-fav");
  const vazio = document.getElementById("fav-vazio");
  vazio.hidden = linhas.length > 0;
  if (!linhas.length) {
    // a lista é só o top-300 por valor: "não encontrado" aqui não quer dizer "não recebeu" —
    // o raio-X por documento/nome procura na base inteira
    const dig = soDigitos(bruto);
    const alvo = dig.length === 14 || dig.length === 11
      ? "./favorecido.html?doc=" + encodeURIComponent(bruto) + "&nome="
      : "./favorecido.html?doc=&nome=" + encodeURIComponent(bruto);
    vazio.innerHTML = bruto
      ? `Nenhum favorecido com “${esc(bruto)}” entre os ${fonte.length} maiores desta lista. ` +
        `<a class="btn" href="${alvo}">Procurar na base inteira (raio-X) ↗</a>`
      : "Nenhum favorecido encontrado.";
  }
  const visiveis = linhas.slice(0, favVisiveis);
  // o nome abre o raio-X (dossiê do top-300 ou rota por documento/nome); a linha inteira
  // também, como atalho de mouse — o teclado usa o próprio link
  corpo.innerHTML = visiveis.map(f => `
    <tr class="fav-row" style="cursor:pointer" data-href="${esc(linkRaiox(f))}">
      <td data-label="Favorecido"><a class="fav-nome" href="${esc(linkRaiox(f))}">${esc(f.nome)}</a>${f.documento ? `<div class="sub" style="color:var(--muted);font-size:12px">${esc(f.documento)}${f.grafias.length > 1 ? ` · ${f.grafias.length} grafias na origem` : ""}</div>` : ""}</td>
      <td data-label="Valor total" class="r num">${brlc(f.valor)}</td>
      <td data-label="Pagamentos" class="r num">${f.qtd}</td>
      <td data-label="Meses" class="r num">${f.meses}</td>
    </tr>`).join("");
  corpo.querySelectorAll(".fav-row").forEach(tr => tr.addEventListener("click", (e) => {
    if (e.target.closest("a") || getSelection().toString()) return;
    location.href = tr.dataset.href;
  }));
  document.querySelectorAll("#painel-favorecidos th[data-sort]").forEach(th => {
    const ativa = th.dataset.sort === favSort.col;
    if (ativa) th.setAttribute("aria-sort", favSort.dir === "asc" ? "ascending" : "descending");
    else th.removeAttribute("aria-sort");
    const b = th.querySelector("button");
    if (b) b.dataset.seta = ativa ? (favSort.dir === "asc" ? " ▲" : " ▼") : "";
  });
  document.getElementById("fav-mais").hidden = linhas.length <= favVisiveis;
  const rotuloModo = favModo === "pf" ? "pessoa(s) física(s)"
    : favModo === "pj" ? "empresa(s)" : favModo === "privados" ? "fornecedor(es) privado(s)" : "favorecido(s)";
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
      marcarAlternancia("#fav-modos button", x => x.dataset.modo === favModo);
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
const ABAS = ["geral", "alertas", "favorecidos", "detalhe"];
function selecionarAba(nome) {
  document.querySelectorAll(".tab").forEach(t => {
    const ativa = t.dataset.tab === nome;
    t.setAttribute("aria-selected", ativa);
    t.tabIndex = ativa ? 0 : -1;
  });
  document.querySelectorAll(".painel").forEach(p => p.classList.remove("ativo"));
  document.getElementById("painel-" + nome).classList.add("ativo");
  // aba no hash (sem nova entrada de histórico): Voltar depois de abrir um alerta cai
  // na mesma aba; a Visão geral é o padrão e fica sem hash
  const hash = nome === "geral" ? "" : "#" + nome;
  const atual = location.hash.replace("#", "");
  if (location.hash !== hash && (!atual || ABAS.includes(atual)))   // não apaga âncoras de conteúdo
    history.replaceState(null, "", location.pathname + location.search + hash);
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
  // o clique (ou Enter/Espaço no <button> do cabeçalho) sobe até o <th>
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
  data: "Data", fase: "Fase", especie: "Espécie", unidade_gestora: "Unidade gestora", tipo: "Tipo",
  nome_favorecido: "Favorecido", documento_favorecido: "CPF/CNPJ",
  funcao: "Função / área", subfuncao: "Subfunção", programa: "Programa",
  elemento_despesa: "Elemento de despesa", fonte_recurso: "Fonte de recurso",
  grupo_despesa: "Grupo de despesa", empenho: "Nº empenho", documento: "Nº documento",
  empenhado: "Empenhado", liquidado: "Liquidado", pago: "Pago", periodo_empenho: "Mês do empenho",
};
const DET_NUM = new Set(["empenhado", "liquidado", "pago"]);  // colunas de valor
// Duas visões, nunca misturadas (2026-09):
//   exe = "Execução dos empenhos": uma linha por empenho do mês selecionado, com o
//         liquidado/pago acumulados até a data da base (arquivos despesas/dados/AAAA-MM.json)
//   mov = "Movimentação no período": um documento por linha, no mês da SUA data
//         (despesas/dados/mov/AAAA-MM.json, codificado por dicionário)
// URL: ?dv=exe|mov — links antigos sem dv são "exe" (o comportamento que sempre tiveram).
const VISOES = {
  exe: { rotulo: "Execução dos empenhos", filtros: ["tipo", "unidade_gestora", "funcao", "subfuncao", "programa",
           "elemento_despesa", "fonte_recurso", "grupo_despesa"],
         cols: ["data", "nome_favorecido", "unidade_gestora", "funcao", "elemento_despesa", "empenho",
                "empenhado", "liquidado", "pago"],
         somente: [] },
  mov: { rotulo: "Movimentação no período", filtros: ["fase", "especie", "tipo", "unidade_gestora", "funcao",
           "subfuncao", "programa", "elemento_despesa", "fonte_recurso", "grupo_despesa"],
         cols: ["data", "fase", "especie", "nome_favorecido", "unidade_gestora", "elemento_despesa", "empenho",
                "documento", "empenhado", "liquidado", "pago"],
         somente: ["fase", "especie", "documento", "periodo_empenho"] },
};
let detVisao = "exe";
const DET_FILTROS_TODOS = VISOES.mov.filtros;              // todos os selects existentes no HTML
const filtrosAtivos = () => VISOES[detVisao].filtros;
const colunasDisponiveis = () => Object.keys(DET_LABELS).filter(c =>
  !VISOES.mov.somente.includes(c) || detVisao === "mov");
const manifestoAtivo = () => (detVisao === "mov" ? (DADOS.meses_movimento || DADOS.meses) : DADOS.meses) || [];
const FASE_LABEL = { E: "Empenho", L: "Liquidação", P: "Pagamento" };
// chaves curtas na URL (prefixo d p/ não colidir com o ?q= dos Favorecidos)
const DET_URL = { tipo: "dt", unidade_gestora: "du", funcao: "df", subfuncao: "dsf",
                  programa: "dpr", elemento_despesa: "del", fonte_recurso: "dfr",
                  grupo_despesa: "dg", fase: "dfa", especie: "des" };
const DET_COLS_PADRAO = VISOES.exe.cols;
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
let detFav = null;       // filtro por IDENTIDADE do favorecido (dfav=<chave>, vindo dos alertas)
let detIdent = null;     // identidade por linha (calculada só quando há detFav)
let detSomas = { empenhado: 0, liquidado: 0, pago: 0 };  // memoizado por filtragem
let detGrupos = [];      // modo agrupado: [{chave, n, empenhado, liquidado, pago, linhas}]
let detExpandidos = new Set();

// remove acentos e baixa caixa — busca tolerante a acentuação (dados em PT-BR)
const semAcento = Comum.norm;
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
let detColsPorVisao = { exe: null, mov: null };   // memória das colunas por visão nesta sessão

function definirVisao(v, opts) {
  if (!VISOES[v]) v = "exe";
  if (v === "mov" && !DADOS.meses_movimento) v = "exe";   // índice antigo sem movimentação
  if (v !== detVisao) {
    detColsPorVisao[detVisao] = detVisiveis.slice();
    detVisao = v;
    detVisiveis = (detColsPorVisao[v] || VISOES[v].cols).slice();
    if (!opts?.manterMeses) renderSeletorMeses();
  }
  marcarAlternancia("#det-visao button", b => b.dataset.visao === detVisao);
  DET_FILTROS_TODOS.forEach(c => {
    const el = document.getElementById("f-" + c);
    if (el) el.hidden = !filtrosAtivos().includes(c);
  });
  const explica = document.getElementById("det-visao-explica");
  if (explica) explica.textContent = detVisao === "mov"
    ? "Cada lançamento conta no mês da sua própria data: empenhos, liquidações e pagamentos emitidos no período. " +
      "Um empenho de janeiro pago em agosto aparece aqui em agosto (só o pagamento)."
    : "Uma linha por empenho emitido no período, com tudo o que já foi liquidado e pago dele até a data da base — " +
      "inclusive em meses posteriores. Um empenho de janeiro pago em agosto aparece aqui em janeiro.";
}

function ligarVisaoDetalhe() {
  const grupo = document.getElementById("det-visao");
  if (!grupo) return;
  if (!DADOS.meses_movimento) grupo.hidden = true;
  grupo.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    const antes = mesesSelecionados().map(c => c.value);
    definirVisao(b.dataset.visao);
    document.querySelectorAll("#meses-grid input").forEach(c => c.checked = antes.includes(c.value));
    atualizarSelInfo();
    document.getElementById("det-resultado").hidden = true;   // resultado anterior era da outra visão
    sincronizarURL();
  }));
}

// decodifica os arquivos de movimentação (colunas por dicionário → valores)
function decodificarParte(p) {
  if (!p || !p.dicionario) return p;
  const idx = Object.keys(p.dicionario).map(c => [p.campos.indexOf(c), p.dicionario[c]]);
  const linhas = p.linhas.map(r => {
    const o = r.slice();
    for (const [i, dic] of idx) o[i] = dic[o[i]];
    return o;
  });
  return { campos: p.campos, linhas };
}

// ── Estado na URL (consulta citável — padrão Checkbook/CGU) ──────────────────
function estadoDetalhe() {
  const est = {
    dv: detVisao !== "exe" ? detVisao : "",       // padrão (exe) fica fora da URL: links antigos = exe
    dm: mesesSelecionados().map(c => c.value).join(","),
    dq: document.getElementById("det-q").value.trim(),
    dmin: document.getElementById("det-vmin").value,
    dmax: document.getElementById("det-vmax").value,
    dord: `${detSort.col}:${detSort.dir}`,
    dpg: detPagina > 1 ? String(detPagina) : "",
    dgrp: detGrupo,
    dmet: detMetrica !== "pago" ? detMetrica : "",
    dcols: detVisiveis.join(",") === DET_COLS_PADRAO.join(",") ? "" : detVisiveis.join(","),
    dfav: detFav || "",
  };
  for (const c of filtrosAtivos()) est[DET_URL[c]] = document.getElementById("f-" + c).value;
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
  definirVisao(p.get("dv") || "exe");
  const meses = (p.get("dm") || "").split(",").filter(Boolean);
  const chks = [...document.querySelectorAll("#meses-grid input")];
  chks.forEach(c => c.checked = meses.includes(c.value) ||
    meses.some(m => /^\d{4}$/.test(m) && c.value.startsWith(m + "-")));
  atualizarSelInfo();
  if (!chks.some(c => c.checked)) return;
  selecionarAba("detalhe");
  await carregarDetalhe({
    q: p.get("dq") || "",
    filtros: Object.fromEntries(filtrosAtivos().map(c => [c, p.get(DET_URL[c]) || ""])),
    vmin: p.get("dmin") || "", vmax: p.get("dmax") || "",
    ord: p.get("dord") || "", pg: +(p.get("dpg") || 1),
    grp: p.get("dgrp") || "", met: p.get("dmet") || "pago",
    cols: (p.get("dcols") || "").split(",").filter(Boolean),
    emp: p.get("emp") || "",
    fav: p.get("dfav") || "",
  });
}

function renderSeletorMeses() {
  const meses = manifestoAtivo();
  // botões rápidos por ano + último mês
  const anos = [...new Set(meses.map(m => m.ano))].sort();
  const rapido = document.getElementById("periodo-rapido");
  rapido.innerHTML =
    anos.map(a => `<button class="btn" data-ano="${a}" type="button">${a} inteiro</button>`).join("") +
    `<button class="btn" data-ultimo="1" type="button">Último mês completo</button>`;

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
      // último mês completo (resumo.mes_ref); sem ele, o último do manifesto
      const mr = DADOS.resumo?.mes_ref;
      const alvo = mr ? `${mr.ano}-${String(mr.mes).padStart(2, "0")}` : null;
      const tem = alvo && [...chks].some(c => c.value === alvo);
      chks.forEach((c, i) => c.checked = tem ? c.value === alvo : i === chks.length - 1);
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
  let total = 0, bytes = 0;
  sel.forEach(c => {
    const m = manifestoAtivo().find(x => x.arquivo === c.dataset.arquivo);
    total += m ? m.n : 0;
    if (!DET_PARTES.has(c.dataset.arquivo)) bytes += m?.bytes || 0;   // o que já veio não baixa de novo
  });
  // tamanho do download (manifesto.bytes) — abrir o mandato inteiro na movimentação passa de 40 MB
  const mb = bytes >= 1e6 ? ` · download ≈ ${(bytes / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB` +
    (bytes > 15e6 ? " (pesado em celular/3G)" : "") : "";
  document.getElementById("sel-info").textContent = (sel.length
    ? `${sel.length} mês(es) selecionado(s) — ~${total.toLocaleString("pt-BR")} ` +
      (detVisao === "mov" ? "documentos (movimentação)" : "empenhos (execução)") + mb
    : "Nenhum mês selecionado.") + (detPendente ? ` · filtro a aplicar: ${detPendente.rotulo}` : "");
}

// Ponte agregado→transação (padrão Checkbook), usada pelo treemap: marca todos os
// meses da MOVIMENTAÇÃO (a mesma base do mapa: pago pela data do pagamento), deixa os
// filtros PENDENTES e cai na aba sem baixar — o mandato inteiro passa de 40 MB, então
// quem decide é a pessoa, vendo o tamanho em sel-info ("Carregar dados" aplica o filtro).
let detPendente = null;
function irParaDetalhe(filtros, visao) {
  definirVisao(visao || "mov");
  document.querySelectorAll("#meses-grid input").forEach(c => c.checked = true);
  detPendente = {
    q: "", filtros: { ...Object.fromEntries(filtrosAtivos().map(c => [c, ""])), ...filtros },
    vmin: "", vmax: "", ord: "", pg: 1, grp: "", met: "pago", cols: [], emp: "",
    rotulo: Object.values(filtros).filter(Boolean).map(v => String(v).replace(/^\d+\s*-\s*/, "")).join(" · "),
  };
  atualizarSelInfo();
  selecionarAba("detalhe");
  location.hash = "detalhe";
  Comum.toast("Filtro preparado. Ajuste o período se quiser e clique em “Carregar dados”.");
}

// debounce ~150 ms (busca a cada tecla em 57k linhas)
const refiltrar = Comum.debounce(() => { detPagina = 1; filtrarDetalhe(); });

function ligarDetalhe() {
  document.getElementById("det-limpar").addEventListener("click", () => {
    document.querySelectorAll("#meses-grid input").forEach(c => c.checked = false);
    atualizarSelInfo();
  });
  document.getElementById("det-carregar").addEventListener("click", () => {
    const pendente = detPendente;   // filtro preparado pelo mapa do gasto
    detPendente = null;
    carregarDetalhe(pendente || undefined);
  });
  document.getElementById("det-q").addEventListener("input", refiltrar);
  DET_FILTROS_TODOS.forEach(c => document.getElementById("f-" + c)
    ?.addEventListener("change", () => { detPagina = 1; filtrarDetalhe(); }));
  ["det-vmin", "det-vmax"].forEach(id =>
    document.getElementById(id).addEventListener("input", refiltrar));
  document.getElementById("det-grupo").addEventListener("change", (e) => {
    detGrupo = e.target.value; detPagina = 1; detExpandidos.clear(); filtrarDetalhe();
  });
  document.querySelectorAll("#det-metrica button").forEach(b =>
    b.addEventListener("click", () => {
      detMetrica = b.dataset.met;
      marcarAlternancia("#det-metrica button", x => x.dataset.met === detMetrica);
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
  ligarVisaoDetalhe();
}

// Gerenciador de colunas ("Colunas ▾"): default enxuto aprovado; CSV exporta tudo.
function ligarColunas() {
  const caixa = document.getElementById("det-cols-lista");
  caixa.innerHTML = colunasDisponiveis().map(c => `
    <label class="mes-chk"><input type="checkbox" value="${c}"
      ${detVisiveis.includes(c) ? "checked" : ""} />${DET_LABELS[c]}</label>`).join("");
  caixa.querySelectorAll("input").forEach(ch => ch.addEventListener("change", () => {
    const marcadas = [...caixa.querySelectorAll("input:checked")].map(x => x.value);
    if (!marcadas.length) { ch.checked = true; Comum.toast("Mantenha ao menos uma coluna."); return; }
    detVisiveis = colunasDisponiveis().filter(c => marcadas.includes(c));  // ordem canônica
    try { localStorage.setItem("despesas_det_cols", JSON.stringify(detVisiveis)); } catch (e) {}
    montarCabecalho();
    renderDetTabela();
    sincronizarURL();
  }));
  document.getElementById("det-cols-reset").addEventListener("click", () => {
    detVisiveis = VISOES[detVisao].cols.slice();
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
    detIdent = null;
    detFav = estado?.fav || null;
    detVisiveis = detVisiveis.filter(c => detCampos.includes(c));
    if (!detVisiveis.length) detVisiveis = VISOES[detVisao].cols.filter(c => detCampos.includes(c));
    popularFiltros();
    if (estado) {                       // consulta vinda da URL: restaura tudo
      document.getElementById("det-q").value = estado.q;
      filtrosAtivos().forEach(c => { document.getElementById("f-" + c).value = estado.filtros[c] || ""; });
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
      DET_FILTROS_TODOS.forEach(c => { const el = document.getElementById("f-" + c); if (el) el.value = ""; });
      document.getElementById("det-vmin").value = "";
      document.getElementById("det-vmax").value = "";
    }
    renderTituloDetalhe(sel.map(c => c.value));
    document.getElementById("det-grupo").value = detGrupo;
    marcarAlternancia("#det-metrica button", x => x.dataset.met === detMetrica);
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
    console.warn("detalhamento:", e);
    Comum.estadoErro(carregando, e.falhas?.length
      ? `Não foi possível baixar ${e.falhas.length === 1 ? "o mês" : "os meses"} ${e.falhas.join(", ")}. ` +
        "Os demais já estão guardados — a nova tentativa baixa só o que faltou."
      : "Falha ao carregar os dados do período. Verifique a conexão.", () => carregarDetalhe(estado));
  }
}

// Facetas com contagem (cross-filter): cada select conta as linhas que restariam
// sob TODOS os demais filtros; opções com 0 ficam desabilitadas (menos a ativa).
// título explícito do recorte (aparece na tela, no CSV e no link)
function renderTituloDetalhe(meses) {
  const t = document.getElementById("det-titulo");
  if (!t) return;
  const anos = [...new Set(meses.map(m => m.slice(0, 4)))];
  const rot = meses.length > 6 ? `${meses.length} meses (${anos.join(", ")})` :
    meses.map(m => MESES[+m.slice(5, 7)] + "/" + m.slice(0, 4)).join(", ");
  const ate = DADOS.dados_ate ? new Date(DADOS.dados_ate.slice(0, 10) + "T12:00:00").toLocaleDateString("pt-BR") : "a data da base";
  t.textContent = detVisao === "mov"
    ? `Movimentação em ${rot} — lançamentos pela data de cada estágio`
    : `Execução dos empenhos emitidos em ${rot} — liquidado e pago acumulados até ${ate}`;
}

// valores codificados viram rótulo legível nos selects/chips (fase E/L/P)
const rotuloValor = (campo, v) => campo === "fase" ? (FASE_LABEL[v] || v) : v;

function popularFiltros() {
  filtrosAtivos().forEach(campo => {
    const i = detCampos.indexOf(campo);
    const sel = document.getElementById("f-" + campo);
    const rotulo = sel.dataset.rotulo || sel.options[0].text;
    sel.dataset.rotulo = rotulo;
    const vals = [...new Set(detRows.map(r => r[i]).filter(v => v != null && v !== ""))]
      .sort((a, b) => String(a).localeCompare(String(b)));
    const atual = sel.value;
    sel.innerHTML = `<option value="">${esc(rotulo)}</option>` +
      vals.map(v => `<option value="${esc(v)}">${esc(rotuloValor(campo, v))}</option>`).join("");
    sel.value = atual;
  });
}

function atualizarFacetas(indices) {
  indices = indices || indicesBase();
  filtrosAtivos().forEach(campo => {
    const i = detCampos.indexOf(campo);
    const sel = document.getElementById("f-" + campo);
    const base = linhasFiltradas({ ignorar: campo, base: indices });
    const contagem = new Map();
    for (const r of base) {
      const v = r[i];
      if (v != null && v !== "") contagem.set(v, (contagem.get(v) || 0) + 1);
    }
    for (const op of sel.options) {
      if (!op.value) continue;
      const n = contagem.get(op.value) || 0;
      op.textContent = `${rotuloValor(campo, op.value)} (${n.toLocaleString("pt-BR")})`;
      op.disabled = n === 0 && sel.value !== op.value;
    }
  });
}

// Índices das linhas que passam nas condições caras e comuns a todas as facetas
// (busca textual, faixa de valor, identidade) — calculado UMA vez por filtragem;
// antes a busca rodava de novo para cada select (~10 passadas em até 300 mil linhas).
function indicesBase() {
  const termos = semAcento(document.getElementById("det-q").value || "").split(/\s+/).filter(Boolean);
  const iMet = detCampos.indexOf(detMetrica);
  const vmin = parseFloat(document.getElementById("det-vmin").value);
  const vmax = parseFloat(document.getElementById("det-vmax").value);
  const temMin = !isNaN(vmin), temMax = !isNaN(vmax);
  if (detFav && !detIdent) {   // mesma chave do export (Comum.identidadeFavorecido ⇄ formato.py)
    const iN = detCampos.indexOf("nome_favorecido"), iD = detCampos.indexOf("documento_favorecido");
    detIdent = detRows.map(r => Comum.identidadeFavorecido(r[iN], r[iD]));
  }
  const out = [];
  for (let i = 0; i < detRows.length; i++) {
    const r = detRows[i];
    if (detFav && detIdent[i] !== detFav) continue;
    if (temMin && (r[iMet] ?? 0) < vmin) continue;
    if (temMax && (r[iMet] ?? 0) > vmax) continue;
    if (termos.length && !termos.every(t => detNorm[i].includes(t))) continue;
    out.push(i);
  }
  return out;
}

// Uma passada de filtro; `ignorar` exclui um select (p/ contagem de facetas);
// `base` reaproveita os índices de indicesBase().
function linhasFiltradas(opts) {
  const ignorar = opts?.ignorar;
  const base = opts?.base || indicesBase();
  const fixos = filtrosAtivos()
    .filter(c => c !== ignorar)
    .map(c => [detCampos.indexOf(c), document.getElementById("f-" + c).value])
    .filter(([, v]) => v !== "");
  const out = [];
  for (const i of base) {
    const r = detRows[i];
    if (fixos.every(([idx, v]) => r[idx] === v)) out.push(r);
  }
  return out;
}

function montarCabecalho() {
  const tr = document.getElementById("det-cabecalho");
  tr.innerHTML = detVisiveis.map(c => {
    const ordenada = detSort.col === c;
    const seta = ordenada ? (detSort.dir === "asc" ? " ▲" : " ▼") : "";
    const aria = ordenada ? ` aria-sort="${detSort.dir === "asc" ? "ascending" : "descending"}"` : "";
    const destaque = c === detMetrica ? " met-ativa" : "";
    const cls = ` class="${DET_NUM.has(c) ? "r" : ""}${destaque}"`;
    // sem aria-label no <th>: ele substituía o nome da coluna ao ler cada célula;
    // a dica de ordenação vai no title
    return `<th data-col="${c}"${cls}${aria} tabindex="0" role="columnheader" ` +
      `title="Ordenar por ${DET_LABELS[c]}">${DET_LABELS[c]}${seta}</th>`;
  }).join("");
  const ordenar = (th) => {
    const c = th.dataset.col;
    detSort.dir = detSort.col === c && detSort.dir === "desc" ? "asc" : "desc";
    detSort.col = c;
    detPagina = 1;
    montarCabecalho();
    filtrarDetalhe();
    tr.querySelector(`th[data-col="${c}"]`)?.focus();  // o innerHTML acima derrubava o foco
  };
  tr.querySelectorAll("th").forEach(th => {
    th.addEventListener("click", () => ordenar(th));
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ordenar(th); }
    });
  });
}

function filtrarDetalhe() {
  const indices = indicesBase();
  detFiltradas = linhasFiltradas({ base: indices });
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
  atualizarFacetas(indices);
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
  if (detFav) {
    const nome = detFiltradas.length ? detFiltradas[0][detCampos.indexOf("nome_favorecido")]
                                     : detFav.replace(/^[a-z]+:[\d]*\|?/, "");
    chips.push({ id: "fav", texto: `favorecido (todas as grafias): ${String(nome).slice(0, 34)}` });
  }
  filtrosAtivos().forEach(c => {
    const v = document.getElementById("f-" + c).value;
    if (v) chips.push({ id: c, texto: `${DET_LABELS[c]}: ${rotuloValor(c, v).length > 34 ? rotuloValor(c, v).slice(0, 32) + "…" : rotuloValor(c, v)}` });
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
      filtrosAtivos().forEach(c => document.getElementById("f-" + c).value = "");
      document.getElementById("det-vmin").value = "";
      document.getElementById("det-vmax").value = "";
      detFav = null;
    } else if (alvo === "fav") {
      detFav = null;
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
  if (c === "fase") return `<td data-label="${DET_LABELS[c]}">${esc(FASE_LABEL[v] || v || "")}</td>`;
  if (c === "periodo_empenho" && v) return `<td data-label="${DET_LABELS[c]}">${MESES[v % 100]}/${Math.floor(v / 100)}</td>`;
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

// valor numérico arredondado ao centavo — número (não string de toFixed) p/ o CSV sair com vírgula
const centavos = (v) => Math.round((v || 0) * 100) / 100;

function exportarDetCsv() {
  if (!detFiltradas.length) { Comum.toast("Nada para exportar."); return; }
  // o nome do arquivo e uma coluna "Recorte" dizem qual visão foi exportada
  const meses = mesesSelecionados().map(c => c.value);
  const recorte = document.getElementById("det-titulo")?.textContent || VISOES[detVisao].rotulo;
  const sufixo = (detVisao === "mov" ? "movimentacao" : "execucao") + "-" +
    (meses.length === 1 ? meses[0] : `${meses[0]}_a_${meses[meses.length - 1]}`);
  if (detGrupo) {   // modo agrupado: exporta os subtotais
    Comum.exportarCsv(`despesas-agrupado-${sufixo}.csv`,
      [DET_GRUPOS[detGrupo] || "grupo", "Documentos", "Empenhado", "Liquidado", "Pago", "Recorte"],
      detGrupos.map(g => [g.chave, g.n, centavos(g.empenhado), centavos(g.liquidado), centavos(g.pago), recorte]));
    return;
  }
  // códigos viram texto legível na planilha: fase "P" → "Pagamento", 202601 → "2026-01"
  const iPer = detCampos.indexOf("periodo_empenho");
  Comum.exportarCsv(`despesas-${sufixo}.csv`, detCampos.map(c => DET_LABELS[c] || c).concat(["Recorte"]),
    detFiltradas.map(r => r.map((v, i) => i === iPer && v ? `${String(v).slice(0, 4)}-${String(v).slice(4)}`
                                              : rotuloValor(detCampos[i], v)).concat([recorte])));
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
  abrirModal(modal, fecharFichaEmpenho);
  document.getElementById("emp-titulo").textContent =
    v("empenho") ? `Empenho ${v("empenho")}` : v("tipo");
  document.getElementById("emp-sub").textContent = v("unidade_gestora");
  document.getElementById("emp-tipo-linha").textContent =
    v("tipo") !== "Empenho" ? v("tipo") : "";

  // favorecido com ponte p/ o raio-X (slug do top-300 ou rota por documento)
  const fav = document.getElementById("emp-fav");
  const chaveFav = chaveFavorecido(v("nome_favorecido"), v("documento_favorecido"));
  const top = (DADOS.top_favorecidos || []).find(f => f.chave ? f.chave === chaveFav
    : (f.nome === v("nome_favorecido") && (f.documento || "") === (v("documento_favorecido") || "")));
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
  // estágios vivem no arquivo do mês do EMPENHO: na execução é o próprio arquivo da linha;
  // na movimentação a linha traz periodo_empenho (null p/ não localizado/extra sem nº)
  let arquivo = "";
  if (detVisao === "mov") {
    const pe = v("periodo_empenho");
    if (pe) arquivo = `despesas/dados/estagios/${Math.floor(pe / 100)}-${String(pe % 100).padStart(2, "0")}.json`;
  } else {
    arquivo = (detArquivoDaLinha.get(row) || "").replace("despesas/dados/", "despesas/dados/estagios/");
  }
  if (!v("empenho") || !arquivo) {
    const fase = v("fase") || "P";
    const valor = fase === "E" ? v("empenhado") : fase === "L" ? v("liquidado") : v("pago");
    eventos = [[fase, v("documento") || "—", v("data") || "", valor ?? 0]];
  } else {
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

// ── Modais acessíveis ────────────────────────────────────────────────────────
// Foco entra no "Fechar" ao abrir e volta a quem abriu ao fechar; Tab circula
// dentro do modal; Escape fecha só o de cima (pilha: um modal pode abrir outro
// por cima — antes um Escape fechava os dois).
const FOCAVEIS = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';
const pilhaModais = [];   // {overlay, fechar, antes} — o último é o de cima
function abrirModal(overlay, fechar) {
  pilhaModais.push({ overlay, fechar, antes: document.activeElement });
  overlay.hidden = false;
  const alvo = overlay.querySelector('[aria-label="Fechar"]') || overlay.querySelector(FOCAVEIS);
  if (alvo) alvo.focus();
}
function fecharModal(overlay) {
  overlay.hidden = true;
  const i = pilhaModais.findIndex((m) => m.overlay === overlay);
  if (i < 0) return;
  const { antes } = pilhaModais.splice(i, 1)[0];
  if (antes && typeof antes.focus === "function" && document.contains(antes)) antes.focus();
}
document.addEventListener("keydown", (e) => {
  const topo = pilhaModais[pilhaModais.length - 1];
  if (!topo) return;
  if (e.key === "Escape") { e.preventDefault(); topo.fechar(); return; }
  if (e.key !== "Tab") return;
  const itens = [...topo.overlay.querySelectorAll(FOCAVEIS)].filter((x) => !x.hidden && x.offsetParent !== null);
  if (!itens.length) return;
  const primeiro = itens[0], ultimo = itens[itens.length - 1];
  if (e.shiftKey && document.activeElement === primeiro) { e.preventDefault(); ultimo.focus(); }
  else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primeiro.focus(); }
  else if (!topo.overlay.contains(document.activeElement)) { e.preventDefault(); primeiro.focus(); }
});

function fecharFichaEmpenho() {
  fecharModal(document.getElementById("emp-modal"));
  sincronizarURL({ emp: "" });
}

function ligarFichaEmpenho() {
  document.getElementById("emp-fechar").addEventListener("click", fecharFichaEmpenho);
  document.getElementById("emp-modal").addEventListener("click", (e) => {
    if (e.target.id === "emp-modal") fecharFichaEmpenho();
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
        [FASE_NOME[ev[0]] || ev[0], ev[1], ev[2], centavos(ev[3]), ev[4] || "Original"]));
  });
}

// ── Partes mensais do detalhe (cache) ────────────────────────────────────────
let FAV_DETALHE = null;   // { campos, rows } — todos os meses concatenados (cacheado)

// Cache por arquivo mensal: o Detalhamento e `carregarTodoDetalhe` (ranking por
// elemento) reaproveitam o que já veio.
const DET_PARTES = new Map();
async function carregarPartes(arquivos, aoBaixar) {
  const faltam = arquivos.filter(a => !DET_PARTES.has(a));
  arquivos.filter(a => DET_PARTES.has(a)).forEach(() => aoBaixar && aoBaixar());
  // allSettled: um mês fora do ar não descarta os que vieram (ficam no cache p/ a nova tentativa)
  const res = await Promise.allSettled(faltam.map(a =>
    fetch("./" + a + "?v=" + (DADOS.atualizado_em || ""))
      .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(p => { DET_PARTES.set(a, decodificarParte(p)); if (aoBaixar) aoBaixar(); })));
  const falhas = faltam.filter((a, i) => res[i].status === "rejected");
  if (falhas.length) {
    const e = new Error("falha ao baixar " + falhas.join(", "));
    e.falhas = falhas.map(a => a.split("/").pop().replace(".json", ""));
    throw e;
  }
  return arquivos.map(a => DET_PARTES.get(a));
}

async function carregarTodoDetalhe() {
  if (FAV_DETALHE) return FAV_DETALHE;
  const partes = await carregarPartes((DADOS.meses || []).map(m => m.arquivo));
  FAV_DETALHE = { campos: partes[0]?.campos || [], rows: partes.flatMap(p => p.linhas) };
  popularElementosFav();
  return FAV_DETALHE;
}

// mesma chave do export (formato.identidade_favorecido) — espelhada em Comum.identidadeFavorecido
const chaveFavorecido = (nome, doc) => Comum.identidadeFavorecido
  ? Comum.identidadeFavorecido(nome, doc) : (soDigitos(doc || "") || semAcento(nome || ""));

init();
