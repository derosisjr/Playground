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

  function renderTema() {
    const t = temaAtual();
    // cartão-pergunta: números em negrito
    $("pergunta").hidden = !t.resumo;
    $("pergunta-txt").innerHTML = Comum.escapar(t.resumo)
      .replace(/(R\$ [\d.,]+|[+−-]\d+%|\d+[\d.,]*\s*\(\d{4}\))/g, "<b>$1</b>");
    $("pergunta-fonte").textContent =
      "Comparação entre as pontas disponíveis de cada série — fontes no rodapé.";

    // seletor de indicador da tesoura
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

  // ── A tesoura ──────────────────────────────────────────────────────────────
  function renderGrafico() {
    const t = temaAtual();
    const ind = t.indicadores.find((i) => i.slug === $("sel-indicador").value)
      || t.indicadores[0];
    if (!ind) return;

    const gastoPorAno = new Map(t.gasto_per_capita.map((g) => [g.ano, g.santos]));
    const indPorAno = new Map(ind.serie.filter((p) => p.santos != null)
      .map((p) => [p.ano, p.santos]));

    const anos = [...gastoPorAno.keys()].sort((a, b) => a - b);
    const anoBase = anos.find((a) => indPorAno.has(a)) ?? anos[0];
    const baseGasto = gastoPorAno.get(anoBase);
    const baseInd = indPorAno.get(anoBase);

    const sGasto = anos.map((a) => +(gastoPorAno.get(a) / baseGasto * 100).toFixed(1));
    const sInd = anos.map((a) => indPorAno.has(a) && baseInd
      ? +(indPorAno.get(a) / baseInd * 100).toFixed(1) : null);

    const sobe = ind.melhor === "maior" ? "melhora" : "piora";
    $("legenda").innerHTML =
      `<span><span class="sw" style="background:${COR.gasto}"></span>Gasto por habitante (base ${anoBase} = 100)</span>` +
      `<span><span class="sw" style="background:${COR.indicador}"></span>${Comum.escapar(ind.nome)} — linha subindo = ${sobe}</span>` +
      `<span><span class="sw" style="background:${COR.ambar};height:10px"></span>distância gasto × resultado</span>`;

    if (grafico) grafico.destroy();
    grafico = new Chart($("grafico"), {
      type: "line",
      data: {
        labels: anos,
        datasets: [
          {
            label: "Gasto por habitante",
            data: sGasto,
            borderColor: COR.gasto, backgroundColor: COR.gasto,
            borderWidth: 3, pointRadius: 3, tension: 0.25,
          },
          {
            label: ind.nome,
            data: sInd,
            borderColor: COR.indicador, backgroundColor: COR.ambar,
            borderWidth: 3, pointRadius: 4, tension: 0.25,
            spanGaps: true,
            fill: "-1", // sombreia até a série do gasto: a tesoura
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (c) => {
                const ano = anos[c.dataIndex];
                if (c.datasetIndex === 0)
                  return ` Gasto: ${brl(gastoPorAno.get(ano))}/hab (índice ${c.formattedValue})`;
                const v = indPorAno.get(ano);
                return v == null ? null
                  : ` ${ind.nome}: ${num(v)} (índice ${c.formattedValue})`;
              },
            },
          },
        },
        scales: {
          x: { grid: { color: COR.grade }, ticks: { color: COR.texto } },
          y: {
            grid: { color: COR.grade },
            ticks: { color: COR.texto, callback: (v) => v },
            title: { display: true, text: `índice (${anoBase} = 100)`, color: COR.texto },
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
        valores: municipios.map((m) =>
          m === "3548500" ? g.santos : g.comparaveis[m] ?? null),
        formato: brl,
      });
    }
    for (const ind of t.indicadores) {
      const p = [...ind.serie].reverse().find((x) => x.santos != null);
      if (!p) continue;
      linhas.push({
        nome: `${ind.nome} (${p.ano})`, fonte: ind.fonte, melhor: ind.melhor,
        valores: municipios.map((m) =>
          m === "3548500" ? p.santos : p.comparaveis[m] ?? null),
        formato: num,
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
    const tb = $("tabela");
    let html = "<thead><tr><th>Indicador</th>" + municipios.map((m) =>
      `<th>${Comum.escapar(DADOS.comparaveis[m])}</th>`).join("") + "</tr></thead><tbody>";
    for (const l of linhas) {
      const p = posicaoSantos(l);
      html += `<tr><td>${Comum.escapar(l.nome)}` +
        (p ? `<span class="pos-chip">Santos: ${p.pos}º de ${p.de}</span>` : "") +
        `<br><span class="ano-fonte">${Comum.escapar(l.fonte)}</span></td>` +
        l.valores.map((v, i) =>
          `<td${i === 0 ? ' class="santos"' : ""}>${v == null ? "—" : l.formato(v)}</td>`
        ).join("") + "</tr>";
    }
    tb.innerHTML = html + "</tbody>";

    $("csv").onclick = () => {
      const { municipios, linhas } = linhasTabela();
      Comum.exportarCsv(
        `custo-por-resultado-${tema}.csv`,
        ["Indicador", "Fonte", ...municipios.map((m) => DADOS.comparaveis[m])],
        // decimais com vírgula — dialeto Excel pt-BR do exportarCsv
        linhas.map((l) => [l.nome, l.fonte,
          ...l.valores.map((v) => v == null ? "" : String(v).replace(".", ","))])
      );
    };
  }

  init();
})();
