// Semáforo Fiscal — painel de endividamento (vanilla + ECharts via Comum.grafico)
// Consome endividamento-index.json (gerado por endividamento/export.py).

// gráficos pela camada comum (Comum.grafico, ECharts): tema, troca de tema, celular e
// falha do CDN são tratados lá; aqui só as séries e as regras de leitura do painel
let DADOS = null;
let SD = null;   // serviço da dívida (despesas/servico-divida.json; cacheado p/ repintar)

// ── Formatação ───────────────────────────────────────────────────────────────
// camada comum: mesma escala de moeda do hub (R$ 8,61 bi · R$ 641,1 mi)
const brl = Comum.brl;
const compacto = Comum.compacto;
const pct = (v, casas = 1) =>
  v == null ? "—" : v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }) + "%";
const esc = Comum.escapar;

// ── Inicialização ────────────────────────────────────────────────────────────
async function init() {
  try {
    const r = await fetch("./endividamento-index.json", { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    DADOS = await r.json();
  } catch (e) {
    Comum.estadoErro("semaforo-cards",
      "Não foi possível carregar os dados do painel. Se persistir, a fonte pode estar fora do ar.", init);
    document.getElementById("dados-vivos").hidden = true;
    document.getElementById("hero-num").hidden = true;  // sem dado, sem esqueleto eterno
    return;
  }
  renderHero();
  renderSemaforo();
  renderResumo();
  renderGraficos();
  renderNotasQuebra();
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

// Nasce com esqueleto (endividamento.html) e é escrito com as fontes já carregadas
// (Comum.quandoFonte): antes a frase trocava de linha quando a fonte chegava — CLS.
function renderHero() {
  const t = DADOS.totais, u = DADOS.ultimo;
  document.getElementById("hero-num").hidden = !t.divida;
  if (!t.divida) return;
  Comum.quandoFonte(Comum.FACES_MANCHETE, () => {
    document.getElementById("hero-divida").textContent = compacto(t.divida);
    document.getElementById("hero-contexto").innerHTML =
      `é a <b>dívida consolidada</b> da Prefeitura no ${esc(rotuloLongo(u))} — ` +
      `${esc(pct(t.dc_pct))} da receita corrente líquida, ` +
      `ou <b>${esc(brl(t.divida / POP_SANTOS))} por santista</b>.`;
  });
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
  box.querySelector(".resumo-texto").innerHTML = Comum.destacarNumeros(DADOS.resumo);
  box.hidden = false;
}

// ── Gráficos ─────────────────────────────────────────────────────────────────
// Eixo x NUMÉRICO (0…n-1, rótulo = ano no 1º quadrimestre): é o que permite a quebra
// contábil ficar ENTRE dois quadrimestres (markLine em i − 0,5), como antes.
const rotuloQ = (p) => `${p.q}º/${String(p.ano).slice(2)}`;

// Quebras de série (DADOS.quebras, curadas em endividamento/export.py). Comparar
// valores através dela mede a mudança de critério contábil, não a dívida.
function indicesQuebra() {
  const S = DADOS.serie || [];
  return S.map((p, i) => (p.quebra ? i : -1)).filter(i => i > 0);
}

// teto do eixo num valor redondo (senão o ECharts rotula o máximo cru: "R$ 658,3 mi")
function arredondarCima(x) {
  if (!(x > 0)) return x;
  const passo = Math.pow(10, Math.floor(Math.log10(x))) / 2;
  return Math.ceil(x / passo) * passo;
}

function limitesDe(slug) {
  return (DADOS.semaforo || []).find((m) => m.slug === slug) || null;
}

// Uma série quadrimestral: linhas (área na 1ª, opcional) ou barras, com limites
// (markLine com rótulo na própria linha) e a quebra contábil (linha tracejada +
// pílula horizontal). `fmt` formata o valor na dica; o eixo usa `fmtEixo`.
function opcaoQuadrimestral(p, larg, { series, fmt, fmtEixo, limites = [], quebra = false, barras = false, legenda = true }) {
  const S = DADOS.serie || [];
  const n = S.length;
  const qs = quebra ? indicesQuebra() : [];
  const traco = (cor, tipo = [6, 5]) => ({ color: cor, type: tipo, width: 1.5 });
  const rotLim = (cor, txt) => ({ show: true, fontFamily: p.sans, fontSize: 11.5,
    formatter: `{d|——} {t|${txt}}`,
    rich: { d: { color: cor, fontWeight: 800, fontSize: 11 }, t: { color: p.tinta, fontWeight: 600, fontSize: 11.5 } } });
  const valores = series.flatMap((s) => s.dados).filter((v) => v != null);
  const topo = Math.max(...valores, ...limites.map((l) => l.valor));
  const piso = Math.min(0, ...valores);   // DCL fica negativa quando o caixa supera a dívida
  // etiqueta da quebra no trecho mais vazio da vertical da quebra (linhas: onde a
  // série passa NO MEIO dos dois quadrimestres; barras: acima de todas, num respiro
  // aberto no topo do eixo — ao lado, o texto cobria as barras ou saía pela borda)
  const alturaPilula = (i) => {
    if (barras) return topo * 1.12;
    const meio = series.map((s) => {
      const a = s.dados[i - 1], b = s.dados[i];
      return a != null && b != null ? (a + b) / 2 : (b ?? a);
    }).filter((v) => v != null).concat(limites.map((l) => l.valor));  // longe das linhas de limite também
    const cands = [0.85, 0.5, 0.15].map((f) => piso + (topo - piso) * f);
    return cands.reduce((melhor, y) => {
      const folga = Math.min(...meio.map((v) => Math.abs(v - y)), Infinity);
      return folga > melhor.folga ? { y, folga } : melhor;
    }, { y: cands[0], folga: -1 }).y;
  };
  const ladoPilula = (i) => (i > n * 0.6 ? "left" : "right");
  // rótulo do limite em cima da linha; o do alerta desce para baixo dela quando a série
  // começa longe (senão o texto fica espremido entre as duas linhas tracejadas)
  const posicaoLimite = (l, k) => {
    if (k === 0) return "insideStartTop";
    const inicio = series[0].dados.slice(0, 3).filter((v) => v != null);
    return inicio.every((v) => Math.abs(v - l.valor) > (topo - piso) * 0.12) ? "insideStartBottom" : "insideStartTop";
  };
  const largBarra = Math.max(6, Math.min(26, Math.floor((larg - 80) / n * 0.55)));
  const marcas = [
    ...limites.map((l, k) => ({ yAxis: l.valor, lineStyle: traco(l.cor),
      label: { ...rotLim(l.cor, l.rotulo), position: posicaoLimite(l, k) } })),
    ...qs.map((i) => ({ xAxis: i - 0.5, lineStyle: traco(p.amarelo, [4, 4]), label: { show: false } })),
  ];
  const pilulas = qs.map((i) => ({
    coord: [i - 0.5, alturaPilula(i)], symbol: "circle", symbolSize: 8,
    itemStyle: { color: p.amarelo, borderColor: p.card, borderWidth: 2 },
    label: { show: true, position: ladoPilula(i), distance: 8,
      formatter: `quebra contábil · ${S[i].rotulo}`, color: p.tinta, fontFamily: p.sans, fontWeight: 600,
      fontSize: 11, backgroundColor: p.card, borderColor: p.amarelo, borderWidth: 1, borderRadius: 999, padding: [4, 9] },
  }));
  return {
    grid: { left: 4, right: 14, top: legenda && series.length > 1 ? 34 : 22, bottom: 6, containLabel: true },
    legend: legenda && series.length > 1
      ? { top: 0, left: 0, itemWidth: 18, itemHeight: 8, selectedMode: false, textStyle: { fontSize: p.celular ? 11.5 : 12 } }
      : undefined,
    tooltip: { trigger: "axis", confine: true, axisPointer: { type: barras ? "shadow" : "line", snap: true },
      formatter: (ps) => {
        const i = Math.max(0, Math.min(n - 1, Math.round(ps[0].axisValue)));
        const pt = S[i];
        return Comum.dicaGrafico(pt.rotulo,
          series.map((s) => [s.cor, s.nome, s.dados[i] == null ? "—" : fmt(s.dados[i])]),
          pt.quebra ? "Quebra contábil: não compare com os pontos anteriores." : "", !!pt.quebra);
      } },
    xAxis: { type: "value", min: barras ? -0.5 : 0, max: barras ? n - 0.5 : n - 1, interval: 1, splitLine: { show: false },
      axisLine: { show: true, lineStyle: { color: p.linha } }, axisTick: { show: false },
      axisLabel: { fontFamily: p.sans, fontSize: 11.5, color: p.muted, margin: 10,
        formatter: (v) => { const pt = S[v]; if (!pt || pt.q !== 1) return ""; return p.celular && pt.ano % 2 ? "" : String(pt.ano); } } },
    yAxis: { type: "value", min: piso < 0 ? null : 0,
      max: limites.length ? (v) => arredondarCima(Math.max(v.max, ...limites.map((l) => l.valor)) * 1.04)
        : barras && qs.length ? (v) => arredondarCima(v.max * 1.22) : null,
      axisLabel: { formatter: fmtEixo } },
    series: series.map((s, k) => {
      const dados = s.dados.map((v, i) => [i, v]);
      const base = { name: s.nome, data: dados, z: 3 + k,
        markLine: k === 0 && marcas.length ? { silent: true, symbol: ["none", "none"], animation: false, data: marcas } : undefined,
        markPoint: k === 0 && pilulas.length ? { silent: true, animation: false, data: pilulas } : undefined };
      if (barras) return { ...base, type: "bar", barWidth: largBarra,
        itemStyle: { color: s.cor, borderRadius: [3, 3, 0, 0] } };
      return { ...base, type: "line", smooth: 0.25, connectNulls: false,
        symbol: p.celular ? "none" : "circle", symbolSize: 5, showAllSymbol: true,
        lineStyle: { width: 2, color: s.cor }, itemStyle: { color: s.cor, borderColor: p.card, borderWidth: 1.5 },
        areaStyle: s.area ? { color: p.serieFill } : undefined };
    }),
  };
}

function renderGraficos() {
  const S = DADOS.serie || [];
  const u = S[S.length - 1] || {};
  const vc = (v) => (v != null ? compacto(v) : "—");
  const aviso = avisoQuebraTexto();
  const rotA = (p) => p.rotulo + (p.quebra ? " (quebra contábil)" : "");
  const eixoR = (v) => Comum.compactoEixo(v);
  const eixoP = (v) => pct(v, 0);
  const div = limitesDe("divida"), pes = limitesDe("pessoal");
  const lim = (m, p) => (m ? [
    { valor: m.limite, cor: p.vermelho, rotulo: `Limite legal · ${pct(m.limite, m.limite % 1 ? 1 : 0)}` },
    { valor: m.alerta, cor: p.amarelo, rotulo: `Alerta · ${pct(m.alerta, m.alerta % 1 ? 1 : 0)}` },
  ] : []);

  // Dívida bruta × líquida
  Comum.grafico("ch-divida", {
    dependeDaLargura: false,
    opcao: (p, larg) => opcaoQuadrimestral(p, larg, { quebra: true, fmt: vc, fmtEixo: eixoR, series: [
      { nome: "Dívida bruta (DC)", dados: S.map((x) => x.dc), cor: p.serie, area: true },
      { nome: "Dívida líquida (DCL)", dados: S.map((x) => x.dcl), cor: p.ouroLinha },
    ] }),
    acessivel: { descricao: `Dívida bruta e líquida por quadrimestre. Em ${u.rotulo || "—"}: bruta ${vc(u.dc)}, líquida ${vc(u.dcl)}.${aviso}`,
      cabecalhos: ["Quadrimestre", "Dívida bruta", "Dívida líquida"], linhas: S.map((x) => [rotA(x), vc(x.dc), vc(x.dcl)]) },
  });

  // DCL % da RCL × limites (lidos do semáforo do índice — antes fixos no JS)
  Comum.grafico("ch-dcl-pct", {
    opcao: (p, larg) => opcaoQuadrimestral(p, larg, { quebra: true, fmt: (v) => pct(v), fmtEixo: eixoP, limites: lim(div, p),
      series: [{ nome: "DCL / RCL", dados: S.map((x) => x.dcl_pct), cor: p.serie, area: true }] }),
    acessivel: { descricao: `Dívida consolidada líquida em percentual da RCL${div ? `, contra o limite legal de ${pct(div.limite, 0)} e o alerta de ${pct(div.alerta, 0)}` : ""}. Em ${u.rotulo || "—"}: ${pct(u.dcl_pct)}.${aviso}`,
      cabecalhos: ["Quadrimestre", "DCL/RCL"], linhas: S.map((x) => [rotA(x), pct(x.dcl_pct)]) },
  });

  // Pessoal % da RCL × limites
  Comum.grafico("ch-pessoal", {
    opcao: (p, larg) => opcaoQuadrimestral(p, larg, { fmt: (v) => pct(v), fmtEixo: eixoP, limites: lim(pes, p),
      series: [{ nome: "Pessoal / RCL", dados: S.map((x) => x.pessoal_pct), cor: p.serie, area: true }] }),
    acessivel: { descricao: `Despesa com pessoal em percentual da RCL${pes ? `, contra o limite legal de ${pct(pes.limite, 0)} e o alerta de ${pct(pes.alerta, 1)}` : ""}. Em ${u.rotulo || "—"}: ${pct(u.pessoal_pct)}.`,
      cabecalhos: ["Quadrimestre", "Pessoal/RCL"], linhas: S.map((x) => [x.rotulo, pct(x.pessoal_pct)]) },
  });

  // Precatórios vencidos
  Comum.grafico("ch-precatorios", {
    dependeDaLargura: true,
    opcao: (p, larg) => opcaoQuadrimestral(p, larg, { quebra: true, barras: true, legenda: false, fmt: vc, fmtEixo: eixoR,
      series: [{ nome: "Precatórios vencidos e não pagos", dados: S.map((x) => x.precatorios), cor: p.ouro }] }),
    acessivel: { descricao: `Precatórios vencidos e não pagos por quadrimestre. Em ${u.rotulo || "—"}: ${vc(u.precatorios)}.${aviso}`,
      cabecalhos: ["Quadrimestre", "Precatórios vencidos"], linhas: S.map((x) => [rotA(x), vc(x.precatorios)]) },
  });

  // Restos a pagar × caixa
  Comum.grafico("ch-caixa", {
    opcao: (p, larg) => opcaoQuadrimestral(p, larg, { fmt: vc, fmtEixo: eixoR, series: [
      { nome: "Caixa bruto", dados: S.map((x) => x.caixa_bruta), cor: p.verde },
      { nome: "Restos a pagar", dados: S.map((x) => x.rp), cor: p.vermelho },
    ] }),
    acessivel: { descricao: `Caixa bruto contra restos a pagar por quadrimestre. Em ${u.rotulo || "—"}: caixa ${vc(u.caixa_bruta)}, restos a pagar ${vc(u.rp)}.`,
      cabecalhos: ["Quadrimestre", "Caixa bruto", "Restos a pagar"], linhas: S.map((x) => [x.rotulo, vc(x.caixa_bruta), vc(x.rp)]) },
  });
}

function renderNotasQuebra() {
  const qs = DADOS.quebras || [];
  document.querySelectorAll("[data-quebra]").forEach(el => {
    if (!qs.length) { el.hidden = true; return; }
    el.innerHTML = qs.map(q =>
      `<b>⚠ Quebra contábil no ${esc(q.rotulo)}${el.dataset.quebra === "tabela" ? " (†)" : ""}:</b> ${esc(q.nota)}`).join("<br>");
    el.hidden = false;
  });
}

// frase curta p/ as descrições acessíveis dos gráficos afetados
function avisoQuebraTexto() {
  const qs = DADOS.quebras || [];
  return qs.length
    ? " Atenção: quebra contábil em " + qs.map(q => q.rotulo).join(", ") +
      " (reclassificação dos precatórios); não compare valores de antes e depois."
    : "";
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
    // recorte de ~1 KB gerado pelo despesas/export.py; se ainda não existir (404),
    // cai no índice inteiro (~400 KB), de onde o recorte é tirado
    let sd;
    const r = await fetch("./despesas/servico-divida.json", { cache: "no-cache" });
    if (r.ok) sd = await r.json();
    else {
      const ri = await fetch("./despesas-index.json", { cache: "no-cache" });
      if (!ri.ok) throw new Error("HTTP " + ri.status);
      sd = (await ri.json()).servico_divida;
    }
    if (!sd || !sd.credores || !sd.credores.length) return;
    SD = sd;
  } catch (e) { return; }  // sem a base de despesas, a seção simplesmente não aparece
  document.getElementById("sec-servico").hidden = false;
  desenharServicoDivida();
}

// desenho separado da carga (a troca de tema é tratada pela camada comum)
function desenharServicoDivida() {
  if (!SD) return;
  const sd = SD;

  // Credores (barra horizontal, maior em cima)
  const cred = sd.credores.filter(c => c.valor >= 1e5).slice(0, 8);
  Comum.grafico("ch-credores", {
    altura: () => Math.max(180, cred.length * 34 + 30),
    opcao: (p) => ({
      grid: { left: 4, right: 22, top: 6, bottom: 4, containLabel: true },
      tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" },
        formatter: (ps) => Comum.dicaGrafico(nomeCredor(cred[ps[0].dataIndex].nome),
          [[p.ouro, "Pago no mandato", compacto(cred[ps[0].dataIndex].valor), "p"]]) },
      xAxis: { type: "value", axisLabel: { formatter: (v) => Comum.compactoEixo(v), alignMaxLabel: "right" } },
      yAxis: { type: "category", inverse: true, data: cred.map(c => nomeCredor(c.nome)),
        axisLabel: { width: p.celular ? 120 : 240, overflow: "truncate" } },
      series: [{ type: "bar", barMaxWidth: 22, data: cred.map(c => c.valor),
        itemStyle: { color: p.ouro, borderRadius: [0, 3, 3, 0] } }],
    }),
    acessivel: { descricao: "Maiores credores do serviço da dívida no mandato (juros e amortização pagos).",
      cabecalhos: ["Credor", "Pago no mandato"], linhas: cred.map(c => [nomeCredor(c.nome), compacto(c.valor)]) },
  });

  // Juros × amortização por ano (barras agrupadas)
  const anos = [...new Set(sd.por_ano.map(p => p.ano))].sort();
  const serie = (tipo) => anos.map(a =>
    (sd.por_ano.find(p => p.ano === a && p.tipo === tipo) || {}).valor || 0);
  const vJuros = serie("juros"), vAmort = serie("amortizacao");
  Comum.grafico("ch-servico-ano", {
    opcao: (p) => ({
      grid: { left: 4, right: 10, top: 34, bottom: 4, containLabel: true },
      legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 10, selectedMode: false },
      tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" },
        formatter: (ps) => Comum.dicaGrafico(String(anos[ps[0].dataIndex]), [
          [p.serie, "Juros e encargos", compacto(vJuros[ps[0].dataIndex]), "p"],
          [p.ouro, "Amortização", compacto(vAmort[ps[0].dataIndex]), "p"]]) },
      xAxis: { type: "category", data: anos.map(String) },
      yAxis: { type: "value", axisLabel: { formatter: (v) => Comum.compactoEixo(v) } },
      series: [
        { name: "Juros e encargos", type: "bar", barMaxWidth: 40, data: vJuros, itemStyle: { color: p.serie, borderRadius: [3, 3, 0, 0] } },
        { name: "Amortização", type: "bar", barMaxWidth: 40, data: vAmort, itemStyle: { color: p.ouro, borderRadius: [3, 3, 0, 0] } },
      ],
    }),
    acessivel: { descricao: "Juros e encargos contra amortização pagos por ano.",
      cabecalhos: ["Ano", "Juros e encargos", "Amortização"],
      linhas: anos.map((a, i) => [a, compacto(vJuros[i]), compacto(vAmort[i])]) },
  });
}

// ── Tabela + CSV ─────────────────────────────────────────────────────────────
function renderTabela() {
  const S = [...(DADOS.serie || [])].reverse();   // mais recente primeiro
  document.getElementById("tab-corpo").innerHTML = S.map(p => `
    <tr${p.quebra ? ' class="linha-quebra"' : ""}>
      <td>${esc(p.rotulo)}${p.quebra
        ? ` <span class="marca-quebra" title="${esc(p.quebra)}">† quebra contábil</span>` : ""}</td>
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
     "DCL/RCL (%)", "Pessoal/RCL (%)", "Op. crédito/RCL (%)", "Precatórios vencidos (R$)", "Observação"],
    S.map(p => [p.rotulo, p.dc, p.dcl, p.rcl, p.dcl_pct, p.pessoal_pct, p.opcred_pct, p.precatorios,
                p.quebra ? "Quebra contábil: " + p.quebra : ""]));
}

init();
