// Painel de Requerimentos & Respostas — lê requerimentos-index.json e filtra no cliente.
"use strict";

let ITENS = [];
let filtradas = [];
let pag = null;  // Comum.paginador — montado no init
const CITADO_POR = {};  // nº → nºs de pedidos posteriores que o citam (de `cita`)

// Situações vindas do export (respostas-executivo/classificar.py). "respondido"
// significa resposta de MÉRITO: pedido de prazo e ofício de encaminhamento sem
// anexo não contam.
const ROTULOS = {
  respondido: "Resposta ↗",
  so_prorrogacao: "Prazo prorrogado ↗",
  so_encaminhamento: "Só encaminhamento ↗",
  a_classificar: "Resposta a classificar ↗",
};
// Coluna "Situação": rótulos públicos da classificação (espelho de ROTULOS em
// respostas-executivo/classificar.py). Antes a coluna mostrava o "Status atual"
// da planilha — anotações internas do gabinete, que não são para o público.
const SITUACAO_ROTULO = {
  respondido: "Respondido",
  so_prorrogacao: "Prazo prorrogado",
  so_encaminhamento: "Só encaminhamento",
  a_classificar: "Resposta a classificar",
  pendente: "Sem resposta",
};

// Prazo da Lei Orgânica (art. 58, XVIII): 15 dias, prorrogáveis por igual período
// a pedido do Prefeito. O vencimento de quem está sem resposta vem pronto do export
// (`vence_em`, respostas-executivo/prazos.py); aqui o mesmo número classifica as
// respostas já recebidas. Índice antigo (sem `vence_em`) só perde as marcas de prazo.
const PRAZO_LOM = 15;
const MIN_SECRETARIA = 5;   // no resumo, secretaria com menos pedidos vai para "outras"
const COBERTURA_MIN = 0.5;  // abaixo disso o resumo por secretaria não é mostrado

// A classificação de mérito (classificar.py → colunas "Situação da resposta" e
// "Data da resposta de mérito" da planilha) só vale quando já chegou à base.
// Antes disso o export cai em "tem pasta no Drive" = respondido — o que inclui
// pedidos de prorrogação e ofícios de encaminhamento. Chamar isso de mérito
// inflava o painel (93% "com resposta de mérito" com 0 de 622 classificados).
// Detecção: alguma situação além de respondido/pendente OU alguma data de mérito.
let CLASSIFICADO = true;
function baseClassificada(itens) {
  return itens.some((i) =>
    (i.situacao && i.situacao !== "respondido" && i.situacao !== "pendente")
    || i.data_resposta_merito);
}
const TXT_RETORNO = "com algum retorno da Prefeitura (inclui prorrogações; classificação de mérito pendente)";

const el = (id) => document.getElementById(id);
// utilitários da camada comum (eram cópias locais idênticas em cada painel)
const norm = Comum.norm;
const escapar = Comum.escapar;
const fmt = (n) => n.toLocaleString("pt-BR");

// "dd/mm/aaaa" -> Date (null se inválida)
function dataBR(s) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s || "");
  return m ? new Date(+m[3], +m[2] - 1, +m[1]) : null;
}
const HOJE = (() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; })();
const diasEntre = (a, b) => Math.round((b - a) / 864e5);
// "1729/2026" → número comparável (ano, depois nº)
const chaveNumero = (n) => {
  const m = /^(\d+)\/(\d{4})$/.exec(n || "");
  return m ? +m[2] * 1e5 + +m[1] : 0;
};

// Campos derivados, calculados uma vez no carregamento.
function derivar(i) {
  const ini = dataBR(i.data_sessao);
  const resposta = dataBR(i.data_resposta_merito) || dataBR(i.data_resposta);
  i._ini = ini;
  i._diasMerito = i.respondido && ini && resposta && resposta >= ini ? diasEntre(ini, resposta) : null;
  i._diasSem = !i.respondido && ini ? diasEntre(ini, HOJE) : null;
  i._temPrazo = "vence_em" in i;
  i._vence = dataBR(i.vence_em);
  i._fora = !i.respondido && !!i._vence && HOJE > i._vence;
  i._busca = norm([i.numero, i.assunto, i.ano, i.secretaria].join(" "));
}

function preencherSelects() {
  const anos = [...new Set(ITENS.map((i) => i.ano).filter(Boolean))].sort((a, b) => b - a);
  for (const a of anos) el("ano").add(new Option(a, a));
  // secretarias por nº de pedidos (as mais frequentes primeiro)
  const cont = {};
  for (const i of ITENS) if (i.secretaria) cont[i.secretaria] = (cont[i.secretaria] || 0) + 1;
  const secs = Object.keys(cont).sort((a, b) => cont[b] - cont[a] || a.localeCompare(b));
  for (const s of secs) el("sec").add(new Option(`${s} (${cont[s]})`, s));
  el("sec").hidden = !secs.length;
  // índice antigo, sem vencimento: o filtro de prazo não teria o que filtrar
  if (!ITENS.some((i) => i._temPrazo)) el("prazo").hidden = true;
}

const ORDENS = {
  recentes: (a, b) => (b._ini || 0) - (a._ini || 0) || chaveNumero(b.numero) - chaveNumero(a.numero),
  // sem resposta primeiro, do mais antigo; depois as respostas que mais demoraram
  atraso: (a, b) => (b._diasSem ?? -1) - (a._diasSem ?? -1)
    || (b._diasMerito ?? -1) - (a._diasMerito ?? -1),
  numero: (a, b) => chaveNumero(a.numero) - chaveNumero(b.numero),
};

function passaPrazo(i, prazo) {
  if (prazo === "fora") return i._fora;
  if (prazo === "resp_fora") return i._diasMerito != null && i._diasMerito > PRAZO_LOM;
  if (prazo === "resp_no_prazo") return i._diasMerito != null && i._diasMerito <= PRAZO_LOM;
  return true;
}

function aplicarFiltros() {
  const q = norm(el("q").value).trim();
  const termos = q ? q.split(/\s+/) : [];
  const ano = el("ano").value;
  // "sim"/"nao" continuam valendo: links antigos já circulam com esses valores.
  const status = el("status").value;
  const prazo = el("prazo").value;
  const sec = el("sec").value;
  const ordem = el("ordem").value || "recentes";
  const n = FOCO;

  filtradas = ITENS.filter((i) => {
    // link "ver o Req. X": o pedido e os que o desdobram, ignorando os outros filtros
    if (n) return i.numero === n || (i.cita || []).includes(n);
    if (ano && String(i.ano) !== ano) return false;
    if (status === "sim" && !i.respondido) return false;
    else if (status === "nao" && i.respondido) return false;
    else if (status && status !== "sim" && status !== "nao" && i.situacao !== status)
      return false;
    if (prazo && !passaPrazo(i, prazo)) return false;
    if (sec && i.secretaria !== sec) return false;
    if (termos.length && !termos.every((t) => i._busca.includes(t))) return false;
    return true;
  }).sort(ORDENS[ordem] || ORDENS.recentes);

  el("foco").hidden = !n;
  if (n) el("foco-num").textContent = n;
  pag.reiniciar(filtradas);
  el("vazio").hidden = filtradas.length > 0;
  atualizarResumo();
  atualizarSecretarias(ano);
  el("csv").disabled = filtradas.length === 0;
  el("cobranca").disabled = !filtradas.some((i) => i._fora);
  Comum.gravarParams({ q: el("q").value.trim(), ano, status, prazo, sec,
                       ordem: ordem === "recentes" ? "" : ordem, n });
}

function mediana(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
}

// Número-manchete do topo: a base inteira (os cartões abaixo seguem o filtro).
// Montado com nós; o prazo só aparece com índice que traz `vence_em`. Escrito com
// as fontes já carregadas (Comum.quandoFonte): antes a frase trocava de linha — CLS.
function renderHero() {
  el("hero-num").hidden = false;
  const sem = ITENS.filter((i) => !i.respondido).length;
  const fora = ITENS.filter((i) => i._fora).length;
  const comPrazo = ITENS.some((i) => i._temPrazo);
  const pedidos = sem === 1 ? "requerimento do mandato" : "requerimentos do mandato";
  Comum.quandoFonte(Comum.FACES_MANCHETE, () => {
    el("hero-grande").textContent = fmt(sem);
    const ctx = el("hero-contexto");
    if (!CLASSIFICADO) {
      ctx.textContent = `${pedidos} ainda sem nenhum retorno da Prefeitura.`;
      return;
    }
    ctx.textContent = `${pedidos} sem resposta de mérito da Prefeitura`;
    if (comPrazo && sem && fora) {
      const b = document.createElement("b");
      b.textContent = fora === sem ? "todos fora do prazo" : `${fmt(fora)} fora do prazo`;
      ctx.append(" — ", b, ` de ${PRAZO_LOM} dias da Lei Orgânica.`);
    } else ctx.append(".");
  });
}

// Cards de resumo (respeitam o filtro atual)
function atualizarResumo() {
  const total = filtradas.length;
  const respondidos = filtradas.filter((i) => i.respondido).length;
  const semMerito = total - respondidos;
  const tramite = filtradas.filter(
    (i) => i.situacao === "so_prorrogacao" || i.situacao === "so_encaminhamento"
  ).length;
  const pct = total ? Math.round((respondidos / total) * 100) : 0;
  const fora = filtradas.filter((i) => i._fora).length;
  const velhos = filtradas.filter((i) => i._diasSem != null && i._diasSem > 180).length;
  const comPrazo = filtradas.some((i) => i._temPrazo);

  // Mediana (e não média: meia dúzia de casos de 300+ dias puxava a média) entre a
  // sessão e a resposta de mérito. Antes do backfill da planilha a data de mérito
  // vem vazia; aí vale a data genérica, que é o melhor dado disponível.
  const prazos = filtradas.map((i) => i._diasMerito).filter((d) => d != null);
  const med = mediana(prazos);
  const noPrazo = prazos.filter((d) => d <= PRAZO_LOM).length;

  const de = `${fmt(respondidos)} de ${fmt(total)}`;
  // o .sub tem até 2 linhas (comum.css corta o resto): o essencial vem primeiro e
  // o texto completo fica no `title`
  let subSem = tramite ? `${fmt(tramite)} só receberam trâmite` : "aguardando o Executivo";
  let tituloSem = subSem;
  if (comPrazo && semMerito) {
    subSem = (fora === semMerito ? "todos fora do prazo" : `${fmt(fora)} fora do prazo`)
      + (velhos ? ` · ${fmt(velhos)} há +180 dias` : "");
    tituloSem = (fora === semMerito ? "Todos" : fmt(fora)) + " fora do prazo da Lei Orgânica" +
      (velhos ? `; ${fmt(velhos)} há mais de 180 dias` : "");
  }
  const subMed = prazos.length ? `${fmt(noPrazo)} de ${fmt(prazos.length)} em até ${PRAZO_LOM} dias` : "sem respostas no filtro atual";
  const tituloMed = prazos.length
    ? `Prazo da Lei Orgânica: ${PRAZO_LOM} dias. ${fmt(noPrazo)} de ${fmt(prazos.length)} respostas chegaram dentro dele.`
    : subMed;
  const cards = CLASSIFICADO ? [
    { rotulo: "Requerimentos", valor: fmt(total), sub: "no filtro atual" },
    { rotulo: "Respondidos", valor: `${pct}%`, sub: `${de} — com resposta de mérito` },
    { rotulo: "Sem resposta de mérito", valor: fmt(semMerito), sub: subSem, titulo: tituloSem },
    { rotulo: "Mediana até a resposta", valor: med == null ? "—" : `${med} dias`, sub: subMed, titulo: tituloMed },
  ] : [
    // sem classificação na base: o mesmo número, com o nome que ele tem de fato
    { rotulo: "Requerimentos", valor: fmt(total), sub: "no filtro atual" },
    { rotulo: "Com algum retorno", valor: `${pct}%`, sub: `${de} — ${TXT_RETORNO}` },
    { rotulo: "Sem nenhum retorno", valor: fmt(semMerito), sub: comPrazo && semMerito ? subSem : "aguardando o Executivo" },
    { rotulo: "Mediana até o retorno", valor: med == null ? "—" : `${med} dias`, sub: "entre a sessão e a data de resposta registrada (pode ser prorrogação)" },
  ];
  el("stats").innerHTML = cards
    .map((c) => `<div class="stat">
        <div class="rotulo">${escapar(c.rotulo)}</div>
        <div class="valor">${escapar(c.valor)}</div>
        <div class="sub" title="${escapar(c.titulo || c.sub)}">${escapar(c.sub)}</div>
      </div>`)
    .join("");
}

// Atraso por secretaria — a sigla é a que o gabinete indicou ao registrar o pedido.
// Respeita só o filtro de ano (o resumo é o retrato do ano, não da busca).
function atualizarSecretarias(ano) {
  const caixa = el("secretarias");
  const base = ITENS.filter((i) => !ano || String(i.ano) === ano);
  const com = base.filter((i) => i.secretaria);
  if (!base.length || com.length / base.length < COBERTURA_MIN) { caixa.hidden = true; return; }
  const grupos = {};
  for (const i of com) (grupos[i.secretaria] = grupos[i.secretaria] || []).push(i);
  const linha = (nome, itens, sigla) => {
    const resp = itens.filter((i) => i.respondido).length;
    const sem = itens.length - resp;
    const fora = itens.filter((i) => i._fora).length;
    const med = mediana(itens.map((i) => i._diasMerito).filter((d) => d != null));
    return { nome, sigla, n: itens.length, resp, sem, fora, med };
  };
  const grandes = [], pequenas = [];
  for (const [s, itens] of Object.entries(grupos)) (itens.length >= MIN_SECRETARIA ? grandes : pequenas).push([s, itens]);
  const linhas = grandes.map(([s, itens]) => linha(s, itens, s))
    .sort((a, b) => b.sem - a.sem || (b.med ?? -1) - (a.med ?? -1) || b.n - a.n);
  if (pequenas.length) {
    linhas.push(linha(`Outras (${pequenas.length} siglas)`, pequenas.flatMap(([, itens]) => itens), ""));
  }
  const pct = Math.round((com.length / base.length) * 100);
  el("sec-sub").textContent = `${grandes.length} secretarias · indicada em ${pct}% dos pedidos${ano ? ` de ${ano}` : ""}`;
  desenharSecretarias(grandes, pequenas, ano);
  el("sec-corpo").innerHTML = linhas.map((l) => `<tr>
      <th scope="row">${l.sigla
        ? `<button type="button" class="lnk" data-sec="${escapar(l.sigla)}" aria-label="Filtrar pedidos da ${escapar(l.sigla)}">${escapar(l.nome)}</button>`
        : escapar(l.nome)}</th>
      <td class="n">${fmt(l.n)}</td>
      <td class="n">${fmt(l.resp)}</td>
      <td class="n">${fmt(l.sem)}</td>
      <td class="n${l.fora ? " fora" : ""}">${fmt(l.fora)}</td>
      <td class="n">${l.med == null ? "—" : `${l.med} dias`}</td>
    </tr>`).join("");
  caixa.hidden = false;
}

// Tempo até a resposta, por secretaria: um ponto por pedido (beeswarm do ECharts v6 —
// `jitter` sem sobreposição no eixo de categorias). Cheio = respondido (dias até o
// mérito); vazado = sem resposta de mérito (idade). Eixo LOGARÍTMICO com marcos de
// tempo: na escala linear 70 pedidos de 20–60 dias cabiam em ~60 px e o espalhamento
// desistia de ~140 pontos. Linhas de 15 dias (Lei Orgânica, art. 58, XVIII) e 30 (com
// prorrogação); traço dourado = mediana dos respondidos. Segue o filtro de ano.
const MARCOS_DIAS = [15, 30, 60, 90, 180, 365];
const ROTULO_MARCO = { 15: "15 d", 30: "30 d", 60: "2 meses", 90: "3 meses", 180: "6 meses", 365: "1 ano" };
function desenharSecretarias(grandes, pequenas, ano) {
  const nomeOutras = `Outras (${pequenas.length} siglas)`;
  const pontos = [];
  const grupo = (g, itens) => {
    for (const i of itens) {
      if (i.respondido && i._diasMerito != null) {
        pontos.push({ g, i, sit: "r", dias: Math.max(1, i._diasMerito) });
      } else if (!i.respondido && i._diasSem != null) {
        pontos.push({ g, i, sit: "p", dias: Math.max(1, i._diasSem) });
      }
    }
  };
  grandes.forEach(([s, itens]) => grupo(s, itens));
  if (pequenas.length) grupo(nomeOutras, pequenas.flatMap(([, itens]) => itens));
  const porGrupo = new Map();
  for (const p of pontos) {
    if (!porGrupo.has(p.g)) porGrupo.set(p.g, { g: p.g, n: 0, resp: [] });
    const x = porGrupo.get(p.g);
    x.n++;
    if (p.sit === "r") x.resp.push(p.dias);
  }
  const grupos = [...porGrupo.values()].map((x) => ({ ...x, med: mediana(x.resp) }))
    .sort((a, b) => (a.g === nomeOutras) - (b.g === nomeOutras) || (b.med ?? -1) - (a.med ?? -1) || b.n - a.n);
  const nomes = grupos.map((x) => x.g);
  const rotulos = new Map(grupos.map((x) => [x.g, x]));
  const maxD = Math.max(400, ...pontos.map((p) => p.dias));
  const resp = pontos.filter((p) => p.sit === "r").map((p) => p.dias);
  const dica = (d) => {
    const p = d.ponto;
    const r = p.sit === "r";
    const ref = r ? (p.i.data_resposta_merito || p.i.data_resposta) : p.i.vence_em;
    return Comum.dicaGrafico(`Req. ${p.i.numero} — ${fmt(p.dias)} dias`, [
      [null, "Secretaria", p.i.secretaria],
      r ? [d.cor, p.i.data_resposta_merito ? "Até a resposta de mérito" : "Até a resposta (data genérica)", `${fmt(p.dias)} dias`, "p"]
        : [d.cor, "Sem resposta de mérito há", `${fmt(p.dias)} dias`, "p"],
    ], r ? `Sessão em ${p.i.data_sessao}; resposta em ${ref}.`
      : `Sessão em ${p.i.data_sessao}` + (ref ? `; prazo venceu em ${ref}.` : "."));
  };
  Comum.grafico("ch-secretarias", {
    dependeDaLargura: true,
    altura: () => Math.max(260, nomes.length * 30 + 120),
    opcao: (p, larg) => {
      const cel = p.celular;
      const topo = cel ? 16 : 58, base = cel ? 100 : 56;
      const banda = (Math.max(260, nomes.length * 30 + 120) - topo - base) / Math.max(1, nomes.length);
      const tam = cel ? 6 : 7;
      const item = (pt, cor) => ({ value: [pt.dias, pt.g], ponto: pt, cor });
      return {
        grid: { left: 4, right: 18, top: topo, bottom: base, containLabel: true },
        legend: { data: [
            { name: "Respondido", icon: "circle", itemStyle: { color: p.serie, borderWidth: 0 } },
            { name: "Sem resposta de mérito", icon: "circle", itemStyle: { color: p.card, borderColor: p.vermelho, borderWidth: 1.6 } },
            { name: "Mediana dos respondidos", icon: "path://M0,0 h3 v14 h-3 Z", itemStyle: { color: p.ouroLinha } }],
          [cel ? "bottom" : "top"]: 0, left: 0, itemGap: 18, itemWidth: 12, itemHeight: 12, selectedMode: false },
        tooltip: { trigger: "item", confine: true, formatter: (x) => (x.data && x.data.ponto ? dica(x.data) : "") },
        xAxis: { type: "log", logBase: 10, min: 10, max: Math.ceil(maxD / 100) * 100,
          name: cel ? "dias desde a sessão (escala log.)" : "dias desde a sessão — escala logarítmica",
          nameLocation: "middle", nameGap: 30, nameTextStyle: { color: p.muted, fontFamily: p.sans, fontSize: 11.5 },
          axisLine: { show: true, lineStyle: { color: p.linha } },
          axisTick: { show: true, customValues: MARCOS_DIAS, length: 4, lineStyle: { color: p.linha } },
          axisLabel: { customValues: cel ? [15, 30, 90, 365] : MARCOS_DIAS, hideOverlap: true,
            formatter: (v) => ROTULO_MARCO[v] || fmt(v) },
          splitLine: { show: true, lineStyle: { color: p.grade } }, minorSplitLine: { show: false } },
        yAxis: { type: "category", data: nomes, inverse: true, boundaryGap: true,
          jitter: Math.max(8, banda * 0.9), jitterOverlap: false, jitterMargin: 0.5,
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { show: true, lineStyle: { color: p.grade, width: 1 } },
          axisLabel: { margin: 12, formatter: (g) => `{s|${String(g).replace(/[{}|]/g, "")}} {n|${rotulos.get(g).n}}`,
            rich: { s: { fontFamily: p.sans, fontWeight: 700, fontSize: cel ? 11 : 12, color: p.tinta },
              n: { fontFamily: p.mono, fontSize: cel ? 10 : 10.5, color: p.muted } } } },
        series: [
          { name: "Respondido", type: "scatter", data: pontos.filter((x) => x.sit === "r").map((x) => item(x, p.serie)),
            symbol: "circle", symbolSize: tam, cursor: "pointer",
            itemStyle: { color: p.serie, opacity: 0.82, borderColor: p.card, borderWidth: 1 },
            emphasis: { scale: 1.6, itemStyle: { opacity: 1 } }, z: 3,
            markLine: { silent: true, symbol: ["none", "none"], animation: false, data: [
              { xAxis: 15, lineStyle: { color: p.amarelo, type: [5, 4], width: 1.5 },
                label: { show: true, position: "start", formatter: cel ? "15 d" : "15 dias · prazo da Lei Orgânica", align: "right",
                  color: p.tinta, fontFamily: p.sans, fontSize: 11, fontWeight: 600, distance: 6, padding: [0, 4, 0, 0] } },
              { xAxis: 30, lineStyle: { color: p.vermelho, type: [5, 4], width: 1.5 },
                label: { show: true, position: "start", formatter: cel ? "30 d" : "30 · com prorrogação", align: "left",
                  color: p.tinta, fontFamily: p.sans, fontSize: 11, fontWeight: 600, distance: 6, padding: [0, 0, 0, 4] } },
            ] } },
          { name: "Sem resposta de mérito", type: "scatter", data: pontos.filter((x) => x.sit === "p").map((x) => item(x, p.vermelho)),
            symbol: "circle", symbolSize: tam, cursor: "pointer",
            itemStyle: { color: "rgba(0,0,0,0)", borderColor: p.vermelho, borderWidth: 1.6 },
            emphasis: { scale: 1.6 }, z: 4 },
          { name: "Mediana dos respondidos", type: "custom", silent: true, z: 5, itemStyle: { color: p.ouroLinha },
            data: grupos.filter((x) => x.med != null).map((x) => [x.med, x.g]), encode: { x: 0, y: 1 },
            renderItem: (params, api) => {
              const c = api.coord([api.value(0), api.value(1)]);
              const h = api.size([0, 1], [api.value(0), api.value(1)])[1] * 0.82;
              return { type: "line", shape: { x1: c[0], y1: c[1] - h / 2, x2: c[0], y2: c[1] + h / 2 },
                style: { stroke: p.ouroLinha, lineWidth: 3, lineCap: "round" } };
            } },
        ],
      };
    },
    // clique num ponto: mostra o pedido (mesmo foco do ?n=)
    eventos: (chart) => chart.on("click", (x) => {
      const pt = x.data && x.data.ponto;
      if (!pt) return;
      FOCO = pt.i.numero;
      aplicarFiltros();
      el("foco").scrollIntoView({ block: "nearest" });
    }),
    acessivel: {
      descricao: `Dias entre a sessão e a resposta de mérito de ${fmt(pontos.length)} requerimentos com secretaria indicada` +
        `${ano ? ` em ${ano}` : ""}, um ponto por pedido. Mediana dos respondidos: ${resp.length ? fmt(mediana(resp)) + " dias" : "—"}; ` +
        `${fmt(resp.filter((d) => d <= PRAZO_LOM).length)} de ${fmt(resp.length)} chegaram em até ${PRAZO_LOM} dias (prazo da Lei Orgânica). ` +
        `${fmt(pontos.length - resp.length)} seguem sem resposta de mérito.`,
      cabecalhos: ["Secretaria", "Requerimento", "Situação", "Dias"],
      linhas: pontos.map((x) => [x.i.secretaria, x.i.numero, x.sit === "r" ? "respondido" : "sem resposta de mérito", fmt(x.dias)]),
    },
  });
}

// Exporta o resultado filtrado (mesmas colunas da tabela + prazo)
function exportarCSV() {
  if (!filtradas.length) return;
  const campos = ["numero", "ano", "assunto", "secretaria", "data_sessao", "data_resposta", "data_resposta_merito", "situacao", "respondido", "vence_em", "dias_ate_merito", "dias_sem_resposta", "url_resposta"];
  Comum.exportarCsv(
    `requerimentos-filtro-${new Date().toISOString().slice(0, 10)}.csv`,
    campos,
    filtradas.map((i) => campos.map((c) => (
      c === "respondido" ? (i[c] ? "sim" : "não")
        : c === "situacao" ? (SITUACAO_ROTULO[i[c]] || i[c])
          : c === "dias_ate_merito" ? (i._diasMerito ?? "")
            : c === "dias_sem_resposta" ? (i._diasSem ?? "")
              : (i[c] ?? ""))))
  );
}

// Texto-base de reiteração (o gabinete revisa antes de protocolar).
function textoReiteracao(i) {
  const desde = i._diasSem != null ? ` há ${fmt(i._diasSem)} dias` : "";
  const prorrogado = i.situacao === "so_prorrogacao"
    ? " O Executivo chegou a pedir prorrogação do prazo, que também já se esgotou." : "";
  return "REQUERIMENTO\n\n" +
    "Requeiro, na forma regimental, que seja oficiado ao Excelentíssimo Senhor Prefeito " +
    `Municipal reiterando os termos do Requerimento nº ${i.numero}, aprovado na sessão de ` +
    `${i.data_sessao}, que trata de: "${i.assunto}".\n\n` +
    `O pedido permanece sem resposta de mérito${desde}, além do prazo de quinze dias, ` +
    "prorrogável por igual período a pedido do Prefeito, fixado no art. 58, inciso XVIII, " +
    `da Lei Orgânica do Município de Santos.${prorrogado}`;
}

// Lista de cobrança: os pedidos do filtro atual que estão fora do prazo.
function textoCobranca() {
  const fora = filtradas.filter((i) => i._fora).sort(ORDENS.atraso);
  const corta = (s) => (s.length > 140 ? s.slice(0, 139).trimEnd() + "…" : s);
  return `Requerimentos sem resposta de mérito fora do prazo da Lei Orgânica (art. 58, XVIII) — ` +
    `${HOJE.toLocaleDateString("pt-BR")}\n\n` +
    fora.map((i) => `• Req. ${i.numero} (sessão ${i.data_sessao}${i.secretaria ? `, ${i.secretaria}` : ""}) — ` +
      `${fmt(i._diasSem)} dias — ${corta(i.assunto)}`).join("\n") +
    `\n\nTotal: ${fmt(fora.length)} · Fonte: ${location.href}`;
}

// Base sem classificação de mérito: textos e filtros deixam de prometer mérito.
function semClassificacao() {
  ROTULOS.respondido = "Retorno ↗";
  SITUACAO_ROTULO.respondido = "Com retorno";
  SITUACAO_ROTULO.pendente = "Sem retorno";
  const intro = el("intro-merito");
  if (intro) {
    intro.textContent = "A classificação das respostas (mérito × pedido de prorrogação × " +
      "ofício de encaminhamento) ainda não chegou a esta base: por ora, conta-se como " +
      "retorno qualquer documento enviado pela Prefeitura, inclusive pedidos de prorrogação de prazo.";
  }
  const sel = el("status");
  const opt = (v) => sel.querySelector(`option[value="${v}"]`);
  opt("sim").textContent = "Só com algum retorno";
  opt("nao").textContent = "Sem nenhum retorno";
  // sem classificação as situações de trâmite não existem na base (filtrar daria
  // vazio) e "pendente" coincide com "nao" — links com ?status=pendente caem em "nao"
  for (const v of ["so_prorrogacao", "so_encaminhamento", "pendente"]) {
    const o = opt(v);
    if (o) o.remove();
  }
}

const linkReq = (n) => `<a href="?n=${encodeURIComponent(n)}" data-n="${escapar(n)}">Req. ${escapar(n)}</a>`;

// Prazo em texto (a cor só reforça; o texto diz tudo)
function prazoHTML(i) {
  if (i.respondido) {
    if (i._diasMerito == null) return `<span class="prazo">—</span>`;
    const ok = i._diasMerito <= PRAZO_LOM;
    return `<span class="prazo ${ok ? "ok" : "fora"}">em ${fmt(i._diasMerito)} dias<small>${ok ? "no prazo" : "fora do prazo"}</small></span>`;
  }
  if (i._fora) {
    return `<span class="prazo fora">há ${fmt(i._diasSem)} dias<small>venceu em ${escapar(i.vence_em)}</small></span>`;
  }
  if (i._vence) return `<span class="prazo ok">vence em ${escapar(i.vence_em)}<small>no prazo</small></span>`;
  return i._diasSem != null ? `<span class="prazo">há ${fmt(i._diasSem)} dias</span>` : `<span class="prazo">—</span>`;
}

function linhaHTML(i) {
  const rotulo = ROTULOS[i.situacao];
  const resposta =
    i.url_resposta && rotulo
      ? `<a class="${i.respondido ? "pdf" : "tramite"}" href="${escapar(i.url_resposta)}" target="_blank" rel="noopener">${rotulo}</a>`
      : `<span class="pendente">Pendente</span>`;
  // reiterar só o que já venceu (ou base antiga, sem marca de prazo)
  const reiterar = !i.respondido && (i._fora || !i._temPrazo)
    ? `<button type="button" class="lnk reiterar" data-reiterar="${escapar(i.numero)}" title="Texto-base para revisar antes de protocolar">Copiar reiteração</button>`
    : "";
  const rel = [];
  if (i.cita) rel.push(`desdobra o ${i.cita.map(linkReq).join(", ")}`);
  if (CITADO_POR[i.numero]) rel.push(`desdobrado em ${CITADO_POR[i.numero].map(linkReq).join(", ")}`);
  return `<tr>
    <td data-label="Número" class="num">${escapar(i.numero)}</td>
    <td data-label="Assunto">${escapar(i.assunto)}${rel.length ? `<span class="rel">${rel.join(" · ")}</span>` : ""}${i.secretaria ? `<span class="sec-tag">${escapar(i.secretaria)}</span>` : ""}</td>
    <td data-label="Sessão" class="data">${escapar(i.data_sessao)}</td>
    <td data-label="Resposta em" class="data">${escapar(i.data_resposta_merito || i.data_resposta)}</td>
    <td data-label="Prazo">${prazoHTML(i)}</td>
    <td data-label="Situação" class="status">${escapar(SITUACAO_ROTULO[i.situacao] || "")}</td>
    <td data-label="Resposta">${resposta}${reiterar}</td>
  </tr>`;
}

let FOCO = "";  // ?n= — um pedido e seus desdobramentos

async function init() {
  try {
    const resp = await fetch("./requerimentos-index.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    ITENS = await resp.json();
  } catch (e) {
    el("contagem").textContent = "";
    el("hero-num").hidden = true;  // sem dado, sem esqueleto eterno
    Comum.estadoErro("stats",
      "Não foi possível carregar os requerimentos. Verifique a conexão.", init);
    return;
  }
  for (const i of ITENS) derivar(i);
  for (const i of ITENS) for (const n of i.cita || []) (CITADO_POR[n] = CITADO_POR[n] || []).push(i.numero);
  CLASSIFICADO = baseClassificada(ITENS);
  if (!CLASSIFICADO) semClassificacao();
  renderHero();
  preencherSelects();
  // estado vindo da URL (link compartilhável) — antes do primeiro render
  const p = Comum.lerParams();
  for (const id of ["q", "ano", "status", "prazo", "sec", "ordem"]) {
    let v = p.get(id);
    if (id === "status" && v === "pendente" && !CLASSIFICADO) v = "nao";
    if (v) el(id).value = v;
  }
  FOCO = p.get("n") || "";
  el("q").addEventListener("input", Comum.debounce(aplicarFiltros));
  ["ano", "status", "prazo", "sec", "ordem"].forEach((id) => el(id).addEventListener("input", aplicarFiltros));
  pag = Comum.paginador({
    corpo: "corpo", mais: "mais", contagem: "contagem", linha: linhaHTML,
    rotulo: (lista, mostrando) => {
      const respondidos = lista.filter((i) => i.respondido).length;
      const qual = CLASSIFICADO ? "com resposta de mérito" : "com algum retorno da Prefeitura";
      return `${fmt(lista.length)} requerimento(s) — ${fmt(respondidos)} ${qual} — exibindo ${fmt(mostrando)}`;
    },
  });
  el("csv").addEventListener("click", exportarCSV);
  el("cobranca").addEventListener("click", () =>
    Comum.copiar(textoCobranca(), "Lista de cobrança copiada"));
  el("limpar").addEventListener("click", () => {
    for (const id of ["q", "ano", "status", "prazo", "sec", "ordem"]) el(id).value = "";
    FOCO = "";
    aplicarFiltros();
  });
  el("foco-todos").addEventListener("click", () => { FOCO = ""; aplicarFiltros(); });
  // ações nas linhas (delegação: as linhas são recriadas a cada filtro)
  el("corpo").addEventListener("click", (e) => {
    const r = e.target.closest("[data-reiterar]");
    if (r) {
      const i = ITENS.find((x) => x.numero === r.dataset.reiterar);
      if (i) Comum.copiar(textoReiteracao(i), `Texto de reiteração do Req. ${i.numero} copiado`);
      return;
    }
    const a = e.target.closest("a[data-n]");
    if (a && !(e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1)) {
      e.preventDefault();
      FOCO = a.dataset.n;
      aplicarFiltros();
      el("foco").scrollIntoView({ block: "nearest" });
    }
  });
  el("secretarias").addEventListener("click", (e) => {
    const b = e.target.closest("[data-sec]");
    if (!b) return;
    el("sec").value = b.dataset.sec;
    FOCO = "";
    aplicarFiltros();
  });
  aplicarFiltros();
}

init();
