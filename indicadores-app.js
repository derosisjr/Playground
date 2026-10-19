/* Painel Custo por Resultado — gasto per capita × indicadores (ECharts via Comum.grafico).
   Assinatura visual: a "tesoura" — séries em base 100 com a área entre elas
   sombreada em âmbar; a distância entre pagar e receber é a mensagem. */
(function () {
  "use strict";

  // cores do tema vêm de Comum.paleta() (gasto = dourado, indicador = navy do site;
  // não confundir o tema claro/escuro com o `tema` do painel = saúde/educação). A
  // legenda é HTML: na troca de tema ela é refeita junto com o gráfico.
  const cor = (p) => ({ gasto: p.ouroLinha, indicador: p.serie, ambar: p.ambar, texto: p.ref });

  let DADOS = null;
  let tema = "saude";

  window.addEventListener("temamudou", () => {
    if (DADOS) renderGrafico();
  });

  const $ = (id) => document.getElementById(id);
  const brl = Comum.brl;
  const num = (v) => (v == null ? "—" : v.toLocaleString("pt-BR"));

  function init() {
    fetch("./indicadores-index.json", { cache: "no-cache" })
      .then((r) => r.json())
      .then((d) => {
        DADOS = d;
        const p = Comum.lerParams().get("tema");
        if (p && d.temas[p]) tema = p;
        renderAbas();
        renderNotaValores();
        renderTema();
      })
      .catch(() => {
        // #abas é seguro para o retry: renderAbas() o reconstrói no sucesso
        Comum.estadoErro("abas",
          "Não foi possível carregar os dados dos indicadores. Verifique a conexão.", init);
      });
  }

  function renderAbas() {
    const abas = $("abas");
    abas.innerHTML = "";
    for (const [slug, t] of Object.entries(DADOS.temas)) {
      const b = document.createElement("button");
      b.className = "aba" + (slug === tema ? " ativa" : "");
      b.textContent = t.nome;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", slug === tema);
      b.tabIndex = slug === tema ? 0 : -1;   // só a aba ativa entra no Tab (padrão APG)
      b.addEventListener("click", () => {
        tema = slug;
        Comum.gravarParams({ tema });
        renderAbas();
        renderTema();
        abas.querySelector('[aria-selected="true"]')?.focus();
      });
      // setas trocam de aba, como nas abas de despesas.html
      b.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        e.preventDefault();
        const todas = [...abas.querySelectorAll('[role="tab"]')];
        const i = todas.indexOf(b);
        todas[(i + (e.key === "ArrowRight" ? 1 : -1) + todas.length) % todas.length].click();
      });
      abas.appendChild(b);
    }
  }

  function temaAtual() { return DADOS.temas[tema]; }

  // formatadores por tipo de indicador
  const FMT = {
    num: (v) => v == null ? "—" : v.toLocaleString("pt-BR"),
    brl: (v) => v == null ? "—" : "R$ " + Math.round(v).toLocaleString("pt-BR"),
    pct: (v) => v == null ? "—" : v.toLocaleString("pt-BR") + "%",
  };
  const fmt = (formato, v) => (FMT[formato] || FMT.num)(v);
  // cores estáveis para as linhas por município no modo série (Santos = dourado; a 2ª
  // é o navy do tema, no lugar do azul fora da paleta)
  const coresMun = (p) => [cor(p).gasto, cor(p).indicador, "#17805e", "#a34d6e", "#7a4dbe", "#b8861d"];

  // Ano-base dos valores em R$ (o export corrige pelo IPCA médio anual); null
  // em índice antigo, ainda em valores correntes — aí o painel diz isso.
  function anoBaseReal() {
    return (DADOS.deflator && DADOS.deflator.ano_base) || null;
  }

  function renderNotaValores() {
    const base = anoBaseReal();
    $("nota-valores").textContent = base
      ? `Valores em reais de ${base}, corrigidos pela inflação (média anual do IPCA/IBGE) — ` +
        "comparar anos em valores correntes confundiria inflação com aumento de gasto. " +
        "Percentuais e indicadores de resultado não são corrigidos."
      : "Valores em reais correntes, sem correção pela inflação.";
  }

  function renderTema() {
    const t = temaAtual();
    const base = anoBaseReal();
    // a manchete é em Fraunces: escrita antes de a fonte chegar, ela trocava de linha
    // na troca de fonte e empurrava o gráfico (CLS) — espera a fonte, no máximo 2,5 s
    Comum.quandoFonte(['500 21px "Fraunces"', '700 21px "Fraunces"'], () => {
      $("pergunta").hidden = !t.resumo;
      $("pergunta-txt").innerHTML = Comum.escapar(t.resumo)
        .replace(/(R\$ [\d.,]+|[+−-]\d+%|\d+[\d.,]*\s*\(\d{4}\))/g, "<b>$1</b>");
    });
    $("pergunta-fonte").textContent = (t.modo === "serie"
      ? "Comparação entre municípios de porte similar — fontes no rodapé."
      : "Comparação entre as pontas disponíveis de cada série — fontes no rodapé.") +
      (base ? ` Valores em R$ de ${base}, corrigidos pelo IPCA.` : "");

    // título do cartão do gráfico muda conforme o modo
    $("titulo-grafico").textContent = t.modo === "serie"
      ? "Santos frente às comparáveis, ano a ano"
      : "A tesoura: gasto × resultado";
    $("sub-grafico").textContent = t.modo === "serie"
      ? "Cada linha é um município. Santos em destaque — quanto mais alto, maior o valor do indicador no ano."
      : "As duas séries começam em 100 no primeiro ano. Quando elas se afastam, a área âmbar mostra a distância entre o que se paga e o que se recebe.";

    const sel = $("sel-indicador");
    sel.innerHTML = "";
    for (const ind of t.indicadores) {
      const o = document.createElement("option");
      o.value = ind.slug;
      o.textContent = ind.nome;
      if (ind.slug === t.indicador_chave) o.selected = true;
      sel.appendChild(o);
    }
    sel.onchange = renderGrafico;

    renderGrafico();
    renderTabela();
  }

  function indSelecionado() {
    const t = temaAtual();
    return t.indicadores.find((i) => i.slug === $("sel-indicador").value)
      || t.indicadores[0];
  }

  function renderGrafico() {
    if (temaAtual().modo === "serie") renderSerie();
    else renderTesoura();
  }

  // ── A tesoura (saúde/educação): gasto × indicador em base 100, +linha SP ────
  // A faixa âmbar entre as linhas = série "base" (mínimo) invisível + diferença
  // empilhada, com os pontos de cruzamento inseridos (retas, para a área ficar
  // exatamente entre as duas linhas).
  function renderTesoura() {
    const t = temaAtual();
    const ind = indSelecionado();
    if (!ind) return;

    const gastoPorAno = new Map(t.gasto_per_capita.map((g) => [g.ano, g.santos]));
    const indPorAno = new Map(ind.serie.filter((p) => p.santos != null)
      .map((p) => [p.ano, p.santos]));
    const spPorAno = new Map(ind.serie.filter((p) => p.sp != null)
      .map((p) => [p.ano, p.sp]));

    const anos = [...gastoPorAno.keys()].sort((a, b) => a - b);
    const anoBase = anos.find((a) => indPorAno.has(a)) ?? anos[0];
    const baseGasto = gastoPorAno.get(anoBase);
    const baseInd = indPorAno.get(anoBase);
    const baseSp = spPorAno.get(anoBase);

    const sGasto = anos.map((a) => +(gastoPorAno.get(a) / baseGasto * 100).toFixed(1));
    const sInd = anos.map((a) => indPorAno.has(a) && baseInd
      ? +(indPorAno.get(a) / baseInd * 100).toFixed(1) : null);
    const temSp = baseSp != null && spPorAno.size >= 2;
    const sSp = anos.map((a) => temSp && spPorAno.has(a)
      ? +(spPorAno.get(a) / baseSp * 100).toFixed(1) : null);

    // faixa: base (mínimo) + diferença, com os cruzamentos
    const lo = [], dif = [];
    for (let k = 0; k < anos.length; k++) {
      if (sInd[k] == null) continue;
      lo.push([anos[k], Math.min(sGasto[k], sInd[k])]);
      dif.push([anos[k], Math.abs(sGasto[k] - sInd[k])]);
      const k2 = k + 1;
      if (k2 < anos.length && sInd[k2] != null) {
        const d1 = sGasto[k] - sInd[k], d2 = sGasto[k2] - sInd[k2];
        if (d1 * d2 < 0) {
          const f = d1 / (d1 - d2);
          lo.push([anos[k] + f * (anos[k2] - anos[k]), sGasto[k] + f * (sGasto[k2] - sGasto[k])]);
          dif.push([anos[k] + f * (anos[k2] - anos[k]), 0]);
        }
      }
    }

    const sobe = ind.melhor === "maior" ? "melhora" : "piora";
    const real = anoBaseReal();
    const C = cor(Comum.paleta());
    $("legenda").innerHTML =
      `<span><span class="sw" style="background:${C.gasto}"></span>Gasto por habitante${real ? " corrigido pelo IPCA" : ""} (base ${anoBase} = 100)</span>` +
      `<span><span class="sw" style="background:${C.indicador}"></span>${Comum.escapar(ind.nome)} — linha subindo = ${sobe}</span>` +
      (temSp ? `<span><span class="sw" style="background:${C.texto}"></span>tendência da média do Estado de SP</span>` : "") +
      `<span><span class="sw" style="background:${C.ambar};height:10px"></span>distância gasto × resultado</span>`;

    const todos = [...sGasto, ...sInd, ...sSp].filter((v) => v != null);
    const minY = Math.floor((Math.min(...todos) - 2) / 20) * 20, maxY = Math.ceil((Math.max(...todos) + 2) / 20) * 20;
    const dica = (ano, p) => {
      const k = anos.indexOf(ano);
      const v = indPorAno.get(ano), vs = spPorAno.get(ano);
      return Comum.dicaGrafico(String(ano), [
        [cor(p).gasto, `Gasto/hab${real ? ` (R$ de ${real})` : ""}`, `${brl(gastoPorAno.get(ano))} · ${num(sGasto[k])}`],
        [cor(p).indicador, ind.nome, v == null ? "—" : `${fmt(ind.formato, v)} · ${num(sInd[k])}`],
        temSp ? [cor(p).texto, "Média SP", vs == null ? "—" : fmt(ind.formato, vs)] : null,
      ], "Depois do “·”, o índice (base 100).");
    };

    Comum.grafico("grafico", {
      opcao: (p) => {
        const C = cor(p);
        const anel = { borderColor: p.card, borderWidth: 2 };
        return {
          grid: { left: 6, right: 16, top: 30, bottom: 6, containLabel: true },
          tooltip: { trigger: "axis", confine: true, axisPointer: { type: "line", snap: true },
            formatter: (ps) => dica(Math.round(ps[0].axisValue), p) },
          xAxis: { type: "value", min: anos[0], max: anos[anos.length - 1], interval: 1, splitLine: { show: false },
            axisLine: { show: true, lineStyle: { color: p.linha } },
            axisLabel: { fontFamily: p.sans, fontSize: 11.5, color: p.muted, margin: 10, formatter: (v) => String(v) } },
          yAxis: { type: "value", min: minY, max: maxY, interval: 20, name: `índice (${anoBase} = 100)`,
            nameLocation: "end", nameGap: 12,
            nameTextStyle: { color: p.muted, fontFamily: p.sans, fontSize: 11.5, align: "left", padding: [0, 0, 0, -30] },
            axisLabel: { formatter: (v) => num(v) } },
          series: [
            { name: "base", type: "line", data: lo, stack: "faixa", symbol: "none", lineStyle: { opacity: 0 },
              areaStyle: { opacity: 0 }, silent: true, tooltip: { show: false }, emphasis: { disabled: true }, z: 1 },
            { name: "faixa", type: "line", data: dif, stack: "faixa", symbol: "none", lineStyle: { opacity: 0 },
              areaStyle: { color: C.ambar, opacity: 1 }, silent: true, tooltip: { show: false }, emphasis: { disabled: true }, z: 1 },
            ...(temSp ? [{ name: "Média SP", type: "line", data: anos.map((a, k) => [a, sSp[k]]), connectNulls: true,
              symbol: "none", lineStyle: { width: 1.5, type: [5, 4], color: C.texto }, itemStyle: { color: C.texto }, z: 2 }] : []),
            { name: "Gasto por habitante", type: "line", data: anos.map((a, k) => [a, sGasto[k]]), symbol: "circle",
              symbolSize: 8, lineStyle: { width: 3, color: C.gasto }, itemStyle: { color: C.gasto, ...anel }, z: 4 },
            { name: ind.nome, type: "line", data: anos.map((a, k) => [a, sInd[k]]), connectNulls: true, symbol: "circle",
              symbolSize: 8, lineStyle: { width: 3, color: C.indicador }, itemStyle: { color: C.indicador, ...anel }, z: 5 },
          ],
        };
      },
      acessivel: {
        descricao: `Série anual — índice (${anoBase} = 100): gasto por habitante${real ? " corrigido pelo IPCA" : ""} e ${ind.nome}. Para este indicador, linha subindo significa ${sobe}.`,
        cabecalhos: ["Ano", "Gasto por habitante (índice)", `${ind.nome} (índice)`, ...(temSp ? ["Média SP (índice)"] : [])],
        linhas: anos.map((a, k) => [String(a), num(sGasto[k]), sInd[k] == null ? "—" : num(sInd[k]),
          ...(temSp ? [sSp[k] == null ? "—" : num(sSp[k])] : [])]),
      },
    });
  }

  // ── Modo série (fiscal): valores absolutos, uma linha por município ─────────
  function renderSerie() {
    const ind = indSelecionado();
    if (!ind) return;
    const municipios = ["3548500", ...Object.keys(DADOS.comparaveis)
      .filter((m) => m !== "3548500")];
    const anos = ind.serie.map((p) => p.ano);
    const valorMun = (p, m) => m === "3548500" ? p.santos : (p.comparaveis[m] ?? null);
    const CORES = coresMun(Comum.paleta());

    $("legenda").innerHTML = municipios.map((m, i) =>
      `<span><span class="sw" style="background:${CORES[i % CORES.length]}"></span>${Comum.escapar(DADOS.comparaveis[m])}</span>`
    ).join("");

    Comum.grafico("grafico", {
      opcao: (p) => {
        const CS = coresMun(p);
        return {
          grid: { left: 6, right: 16, top: 30, bottom: 6, containLabel: true },
          tooltip: { trigger: "axis", confine: true,
            formatter: (ps) => Comum.dicaGrafico(String(anos[ps[0].dataIndex]),
              ps.map((x) => [x.color, x.seriesName, fmt(ind.formato, x.value)])) },
          xAxis: { type: "category", data: anos.map(String), boundaryGap: false },
          yAxis: { type: "value", name: ind.nome, nameLocation: "end", nameGap: 12,
            nameTextStyle: { color: p.muted, fontFamily: p.sans, fontSize: 11.5, align: "left", padding: [0, 0, 0, -30] },
            axisLabel: { formatter: (v) => fmt(ind.formato, v) } },
          series: municipios.map((m, i) => ({
            name: DADOS.comparaveis[m], type: "line", connectNulls: true,
            data: ind.serie.map((pt) => valorMun(pt, m)),
            symbol: m === "3548500" ? "circle" : "none", symbolSize: 6,
            lineStyle: { width: m === "3548500" ? 3.5 : 1.5, color: CS[i % CS.length] },
            itemStyle: { color: CS[i % CS.length] }, z: m === "3548500" ? 5 : 2,
          })),
        };
      },
      acessivel: {
        descricao: `Série anual — ${ind.nome}, Santos e municípios comparáveis.`,
        cabecalhos: ["Ano", ...municipios.map((m) => DADOS.comparaveis[m])],
        linhas: anos.map((a, k) => [String(a), ...municipios.map((m) => {
          const v = valorMun(ind.serie[k], m);
          return v == null ? "—" : fmt(ind.formato, v);
        })]),
      },
    });
  }

  // ── Tabela de comparáveis ──────────────────────────────────────────────────
  function linhasTabela() {
    const t = temaAtual();
    const municipios = ["3548500", ...Object.keys(DADOS.comparaveis)
      .filter((m) => m !== "3548500")];
    const linhas = [];

    const g = t.gasto_per_capita[t.gasto_per_capita.length - 1];
    if (g) {
      linhas.push({
        nome: `Gasto por habitante (${g.ano})`, fonte: "SICONFI", melhor: null,
        formato: "brl", sp: null,
        valores: municipios.map((m) =>
          m === "3548500" ? g.santos : g.comparaveis[m] ?? null),
      });
    }
    for (const ind of t.indicadores) {
      const p = [...ind.serie].reverse().find((x) => x.santos != null);
      if (!p) continue;
      linhas.push({
        nome: `${ind.nome} (${p.ano})`, fonte: ind.fonte, melhor: ind.melhor,
        formato: ind.formato, sp: p.sp ?? null,
        valores: municipios.map((m) =>
          m === "3548500" ? p.santos : p.comparaveis[m] ?? null),
      });
    }
    return { municipios, linhas };
  }

  function posicaoSantos(l) {
    if (!l.melhor) return null;
    const validos = l.valores.filter((v) => v != null);
    const ordem = [...validos].sort((a, b) => l.melhor === "maior" ? b - a : a - b);
    return { pos: ordem.indexOf(l.valores[0]) + 1, de: validos.length };
  }

  function renderTabela() {
    const { municipios, linhas } = linhasTabela();
    const temSp = linhas.some((l) => l.sp != null);
    const tb = $("tabela");
    let html = "<thead><tr><th>Indicador</th>" + municipios.map((m) =>
      `<th>${Comum.escapar(DADOS.comparaveis[m])}</th>`).join("") +
      (temSp ? "<th>Média SP</th>" : "") + "</tr></thead><tbody>";
    for (const l of linhas) {
      const p = posicaoSantos(l);
      html += `<tr><td>${Comum.escapar(l.nome)}` +
        (p ? `<span class="pos-chip">Santos: ${p.pos}º de ${p.de}</span>` : "") +
        `<br><span class="ano-fonte">${Comum.escapar(l.fonte)}</span></td>` +
        l.valores.map((v, i) =>
          `<td${i === 0 ? ' class="santos"' : ""}>${fmt(l.formato, v)}</td>`
        ).join("") +
        (temSp ? `<td class="ano-fonte">${l.sp == null ? "—" : fmt(l.formato, l.sp)}</td>` : "") +
        "</tr>";
    }
    tb.innerHTML = html + "</tbody>";

    $("csv").onclick = () => {
      const { municipios, linhas } = linhasTabela();
      const temSp = linhas.some((l) => l.sp != null);
      Comum.exportarCsv(
        `custo-por-resultado-${tema}.csv`,
        ["Indicador", "Fonte", ...municipios.map((m) => DADOS.comparaveis[m]),
          ...(temSp ? ["Média SP"] : [])],
        linhas.map((l) => [l.nome, l.fonte,
          ...l.valores.map((v) => v == null ? "" : String(v).replace(".", ",")),
          ...(temSp ? [l.sp == null ? "" : String(l.sp).replace(".", ",")] : [])])
      );
    };
  }

  init();
})();
