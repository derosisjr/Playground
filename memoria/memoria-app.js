/* Memória do Gabinete — busca lexical local (uso interno).
   Assinatura visual: o carimbo de origem — cada documento leva o selo da fonte. */
(function () {
  "use strict";

  const ORIGENS = {
    "": "Tudo",
    requerimento: "Requerimentos",
    resposta_executivo: "Respostas do Executivo",
    dom: "Diário Oficial",
    propositura: "Proposituras",
  };
  const CARIMBO = {
    requerimento: "Requerimento",
    resposta_executivo: "Resposta Exec.",
    dom: "DOM",
    propositura: "Propositura",
    briefing: "Briefing",
  };
  const PAGINA = 60;

  let DOCS = [];
  let filtrados = [];
  let origem = "";
  let mostrando = 0;

  const $ = (id) => document.getElementById(id);
  const norm = (s) => (s || "").toString().toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "");
  const esc = (s) => (s || "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function init() {
    fetch("./memoria-index.json?v=" + Date.now())
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((d) => {
        DOCS = d.documentos.map((doc) => ({
          ...doc, h: norm(doc.titulo + " " + doc.texto),
        }));
        montarFiltros();
        aplicar();
      })
      .catch(() => {
        $("contagem").textContent = "memoria-index.json não encontrado — rode " +
          "python memoria/indexar.py e python memoria/export.py";
      });

    $("q").addEventListener("input", aplicar);
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement !== $("q")) {
        e.preventDefault(); $("q").focus();
      } else if (e.key === "Escape") { $("q").value = ""; aplicar(); }
    });
    $("mais").addEventListener("click", renderMais);
  }

  function montarFiltros() {
    const box = $("filtros");
    for (const [o, rotulo] of Object.entries(ORIGENS)) {
      const b = document.createElement("button");
      b.className = "chip" + (o === origem ? " ativo" : "");
      b.dataset.o = o;
      b.textContent = rotulo;
      b.addEventListener("click", () => {
        origem = o;
        box.querySelectorAll(".chip").forEach((c) =>
          c.classList.toggle("ativo", c.dataset.o === origem));
        aplicar();
      });
      box.insertBefore(b, $("contagem"));
    }
    box.querySelector('.chip[data-o=""]').classList.add("ativo");
  }

  function aplicar() {
    const termos = norm($("q").value).split(/\s+/).filter(Boolean);
    filtrados = DOCS.filter((d) => {
      if (origem && d.origem !== origem) return false;
      return termos.every((t) => d.h.includes(t));
    });
    $("contagem").textContent = filtrados.length.toLocaleString("pt-BR") + " documentos";
    $("vazio").hidden = filtrados.length > 0;
    $("lista").innerHTML = "";
    mostrando = 0;
    renderMais();
  }

  function realcar(texto, termos) {
    let html = esc(texto);
    for (const t of termos) {
      if (t.length < 2) continue;
      // realce sem acento: acha o termo no texto normalizado e marca no original
      const alvoN = norm(texto);
      let i = alvoN.indexOf(t);
      if (i >= 0) {
        html = esc(texto.slice(0, i)) + "<mark>" + esc(texto.slice(i, i + t.length)) +
          "</mark>" + esc(texto.slice(i + t.length));
        break; // um realce por trecho é suficiente p/ orientação
      }
    }
    return html;
  }

  function trechoRelevante(d, termos) {
    if (!termos.length) return d.texto.slice(0, 220);
    const alvo = norm(d.texto);
    const i = Math.max(0, alvo.indexOf(termos[0]));
    const ini = Math.max(0, i - 80);
    return (ini > 0 ? "…" : "") + d.texto.slice(ini, ini + 260);
  }

  function renderMais() {
    const termos = norm($("q").value).split(/\s+/).filter(Boolean);
    const fim = Math.min(mostrando + PAGINA, filtrados.length);
    const html = filtrados.slice(mostrando, fim).map((d) => {
      const titulo = d.url
        ? `<a href="${esc(d.url)}" target="_blank" rel="noopener">${realcar(d.titulo, termos)}</a>`
        : realcar(d.titulo, termos);
      return `<div class="doc" data-o="${esc(d.origem)}">
        <span class="carimbo">${esc(CARIMBO[d.origem] || d.origem)}
          <span class="dt">${esc(d.data || "s/ data")}</span></span>
        <div><h3>${titulo}</h3>
          <p class="trecho">${realcar(trechoRelevante(d, termos), termos)}</p></div>
      </div>`;
    }).join("");
    $("lista").insertAdjacentHTML("beforeend", html);
    mostrando = fim;
    $("mais").hidden = mostrando >= filtrados.length;
  }

  init();
})();
