/* Painel Custo por Resultado — gasto per capita × indicadores (Chart.js).
   Assinatura visual: a "tesoura" — séries em base 100 com a área entre elas
   sombreada em âmbar; a distância entre pagar e receber é a mensagem. */
(function () {
  "use strict";

  const ESCURO = document.documentElement.dataset.tema === "escuro";
  const COR = {
    gasto: "#c9a84c",
    indicador: ESCURO ? "#7fb3e3" : "#1d6fb8",
    ambar: "rgba(201,168,76,0.25)",
    grade: ESCURO ? "rgba(255,255,255,0.08)" : "rgba(7,17,31,0.07)",
    texto: ESCURO ? "#c3cdda" : "#5d6675",
  };

  let DADOS = null;
  let tema = "saude";
  let grafico = null;

  const $ = (id) => document.getElementById(id);
  const brl = (v) => "R$ " + Math.round(v).toLocaleString("pt-BR");
  const num = (v) => (v == null ? "—" : v.toLocaleString("pt-BR"));

  function init() {
    fetch("./indicadores-index.json?v=" + Date.now())
      .then((r) => r.json())
      .then((d) => {
        DADOS = d;
        const p = Comum.lerParams().get("tema");
        if (p && d.temas[p]) tema = p;
        renderAbas();
        renderTema();
      })
      .catch(() => {
        $("pergunta").hidden = false;
        $("pergunta-txt").textContent =
          "Não foi possível carregar os dados. Tente novamente mais tarde.";
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
      b.addEventListener("click", () => {
        tema = slug;
        Comum.gravarParams({ tema });
        renderAbas();
        renderTema();
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
  // cores estáveis para as linhas por município no modo série
  const CORES_MUN = ["#c9a84c", "#1d6fb8", "#17805e", "#a34d6e", "#7a4dbe", "#b8861d"];

  function renderTema() {
    const t = temaAtual();
    $("pergunta").hidden = !t.resumo;
    $("pergunta-txt").innerHTML = Comum.escapar(t.resumo)
      .replace(/(R\$ [\d.,]+|[+−-]\d+%|\d+[\d.,]*\s*\(\d{4}\))/g, "<b>$1</b>");
    $("pergunta-fonte").textContent = t.modo === "serie"
      ? "Comparação entre municípios de porte similar — fontes no rodapé."
      : "Comparação entre as pontas disponíveis de cada série — fontes no rodapé.";

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

    const sobe = ind.melhor === "maior" ? "melhora" : "piora";
    $("legenda").innerHTML =
      `<span><span class="sw" style="background:${COR.gasto}"></span>Gasto por habitante (base ${anoBase} = 100)</span>` +
      `<span><span class="sw" style="background:${COR.indicador}"></span>${Comum.escapar(ind.nome)} — linha subindo = ${sobe}</span>` +
      (temSp ? `<span><span class="sw" style="background:${COR.texto}"></span>tendência da média do Estado de SP</span>` : "") +
      `<span><span class="sw" style="background:${COR.ambar};height:10px"></span>distância gasto × resultado</span>`;

    const datasets = [
      { label: "Gasto por habitante", data: sGasto, borderColor: COR.gasto,
        backgroundColor: COR.gasto, borderWidth: 3, pointRadius: 3, tension: 0.25 },
      { label: ind.nome, data: sInd, borderColor: COR.indicador,
        backgroundColor: COR.ambar, borderWidth: 3, pointRadius: 4, tension: 0.25,
        spanGaps: true, fill: "-1" },
    ];
    if (temSp) {
      datasets.push({ label: "Média SP (tendência)", data: sSp, borderColor: COR.texto,
        borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, tension: 0.25,
        spanGaps: true, fill: false });
    }

    desenhar(anos, datasets, `índice (${anoBase} = 100)`, (c) => {
      const ano = anos[c.dataIndex];
      if (c.datasetIndex === 0)
        return ` Gasto: ${brl(gastoPorAno.get(ano))}/hab (índice ${c.formattedValue})`;
      if (c.datasetIndex === 1) {
        const v = indPorAno.get(ano);
        return v == null ? null : ` ${ind.nome}: ${fmt(ind.formato, v)} (índice ${c.formattedValue})`;
      }
      const v = spPorAno.get(ano);
      return v == null ? null : ` Média SP: ${fmt(ind.formato, v)}`;
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

    const datasets = municipios.map((m, i) => ({
      label: DADOS.comparaveis[m],
      data: ind.serie.map((p) => valorMun(p, m)),
      borderColor: CORES_MUN[i % CORES_MUN.length],
      backgroundColor: CORES_MUN[i % CORES_MUN.length],
      borderWidth: m === "3548500" ? 3.5 : 1.5,
      pointRadius: m === "3548500" ? 3 : 0,
      tension: 0.25, spanGaps: true,
    }));

    $("legenda").innerHTML = municipios.map((m, i) =>
      `<span><span class="sw" style="background:${CORES_MUN[i % CORES_MUN.length]}"></span>${Comum.escapar(DADOS.comparaveis[m])}</span>`
    ).join("");

    desenhar(anos, datasets, ind.nome, (c) =>
      ` ${c.dataset.label}: ${fmt(ind.formato, c.parsed.y)}`, ind.formato);
  }

  // Desenha o gráfico (destrói o anterior). tickFmt opcional formata o eixo Y.
  function desenhar(labels, datasets, tituloY, tooltipLabel, formatoY) {
    if (grafico) grafico.destroy();
    // equivalente acessível: uma coluna por série, gerado dos mesmos datasets
    Comum.chartAcessivel("grafico", `Série anual — ${tituloY}.`,
      ["Ano", ...datasets.map((d) => d.label)],
      labels.map((a, i) => [a, ...datasets.map((d) =>
        d.data[i] == null ? "—" : (formatoY ? fmt(formatoY, d.data[i]) : d.data[i]))]));
    grafico = new Chart($("grafico"), {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: tooltipLabel } },
        },
        scales: {
          x: { grid: { color: COR.grade }, ticks: { color: COR.texto } },
          y: {
            grid: { color: COR.grade },
            ticks: { color: COR.texto,
              callback: formatoY ? (v) => fmt(formatoY, v) : (v) => v },
            title: { display: true, text: tituloY, color: COR.texto },
          },
        },
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
