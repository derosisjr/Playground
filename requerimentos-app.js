// Painel de Requerimentos & Respostas — lê requerimentos-index.json e filtra no cliente.
"use strict";

let ITENS = [];
let filtradas = [];
let pag = null;  // Comum.paginador — montado no init

// Situações vindas do export (respostas-executivo/classificar.py). "respondido"
// significa resposta de MÉRITO: pedido de prazo e ofício de encaminhamento sem
// anexo não contam.
const ROTULOS = {
  respondido: "Resposta ↗",
  so_prorrogacao: "Prazo prorrogado ↗",
  so_encaminhamento: "Só encaminhamento ↗",
};

const el = (id) => document.getElementById(id);
// utilitários da camada comum (eram cópias locais idênticas em cada painel)
const norm = Comum.norm;
const escapar = Comum.escapar;

function preencherSelects() {
  const anos = [...new Set(ITENS.map((i) => i.ano).filter(Boolean))].sort((a, b) => b - a);
  for (const a of anos) el("ano").add(new Option(a, a));
}

function aplicarFiltros() {
  const q = norm(el("q").value).trim();
  const termos = q ? q.split(/\s+/) : [];
  const ano = el("ano").value;
  // "sim"/"nao" continuam valendo: links antigos já circulam com esses valores.
  const status = el("status").value;

  filtradas = ITENS.filter((i) => {
    if (ano && String(i.ano) !== ano) return false;
    if (status === "sim" && !i.respondido) return false;
    else if (status === "nao" && i.respondido) return false;
    else if (status && status !== "sim" && status !== "nao" && i.situacao !== status)
      return false;
    if (termos.length && !termos.every((t) => i._busca.includes(t))) return false;
    return true;
  });

  pag.reiniciar(filtradas);
  el("vazio").hidden = filtradas.length > 0;
  atualizarResumo();
  el("csv").disabled = filtradas.length === 0;
  Comum.gravarParams({ q: el("q").value.trim(), ano, status });
}

// "dd/mm/aaaa" -> Date (null se inválida)
function dataBR(s) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s || "");
  return m ? new Date(+m[3], +m[2] - 1, +m[1]) : null;
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

  // Tempo médio até a resposta DE MÉRITO. Antes do backfill da planilha o campo
  // vem vazio; aí vale a data genérica, que é o melhor dado disponível.
  const prazos = filtradas
    .filter((i) => i.respondido)
    .map((i) => {
      const a = dataBR(i.data_sessao);
      const b = dataBR(i.data_resposta_merito) || dataBR(i.data_resposta);
      return a && b ? (b - a) / 864e5 : null;
    })
    .filter((d) => d != null && d >= 0);
  const media = prazos.length
    ? Math.round(prazos.reduce((s, d) => s + d, 0) / prazos.length)
    : null;

  const cards = [
    { rotulo: "Requerimentos", valor: total.toLocaleString("pt-BR"), sub: "no filtro atual" },
    { rotulo: "Respondidos", valor: `${pct}%`, sub: `${respondidos.toLocaleString("pt-BR")} de ${total.toLocaleString("pt-BR")} — com resposta de mérito` },
    { rotulo: "Sem resposta de mérito", valor: semMerito.toLocaleString("pt-BR"), sub: tramite ? `${tramite.toLocaleString("pt-BR")} só receberam trâmite` : "aguardando o Executivo" },
    { rotulo: "Tempo médio de resposta", valor: media == null ? "—" : `${media} dias`, sub: "entre a sessão e a resposta de mérito" },
  ];
  el("stats").innerHTML = cards
    .map((c) => `<div class="stat">
        <div class="rotulo">${escapar(c.rotulo)}</div>
        <div class="valor">${escapar(c.valor)}</div>
        <div class="sub">${escapar(c.sub)}</div>
      </div>`)
    .join("");
}

// Exporta o resultado filtrado (mesmas colunas da tabela)
function exportarCSV() {
  if (!filtradas.length) return;
  const campos = ["numero", "ano", "assunto", "data_sessao", "data_resposta", "data_resposta_merito", "situacao", "status", "respondido", "url_resposta"];
  Comum.exportarCsv(
    `requerimentos-filtro-${new Date().toISOString().slice(0, 10)}.csv`,
    campos,
    filtradas.map((i) => campos.map((c) => (c === "respondido" ? (i[c] ? "sim" : "não") : i[c])))
  );
}

function linhaHTML(i) {
  const rotulo = ROTULOS[i.situacao];
  const resposta =
    i.url_resposta && rotulo
      ? `<a class="${i.respondido ? "pdf" : "tramite"}" href="${escapar(i.url_resposta)}" target="_blank" rel="noopener">${rotulo}</a>`
      : `<span class="pendente">Pendente</span>`;
  return `<tr>
    <td data-label="Número" class="num">${escapar(i.numero)}</td>
    <td data-label="Assunto">${escapar(i.assunto)}</td>
    <td data-label="Sessão" class="data">${escapar(i.data_sessao)}</td>
    <td data-label="Resposta em" class="data">${escapar(i.data_resposta)}</td>
    <td data-label="Situação" class="status">${escapar(i.status)}</td>
    <td data-label="Resposta">${resposta}</td>
  </tr>`;
}

async function init() {
  try {
    const resp = await fetch("./requerimentos-index.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    ITENS = await resp.json();
  } catch (e) {
    el("contagem").textContent = "";
    Comum.estadoErro("stats",
      "Não foi possível carregar os requerimentos. Verifique a conexão.", init);
    return;
  }
  for (const i of ITENS) i._busca = norm([i.numero, i.assunto, i.status, i.ano].join(" "));
  preencherSelects();
  // estado vindo da URL (link compartilhável) — antes do primeiro render
  const p = Comum.lerParams();
  for (const id of ["q", "ano", "status"]) {
    const v = p.get(id);
    if (v) el(id).value = v;
  }
  el("q").addEventListener("input", Comum.debounce(aplicarFiltros));
  ["ano", "status"].forEach((id) => el(id).addEventListener("input", aplicarFiltros));
  pag = Comum.paginador({
    corpo: "corpo", mais: "mais", contagem: "contagem", linha: linhaHTML,
    rotulo: (lista, mostrando) => {
      const respondidos = lista.filter((i) => i.respondido).length;
      return `${lista.length.toLocaleString("pt-BR")} requerimento(s) — ${respondidos.toLocaleString("pt-BR")} com resposta de mérito — exibindo ${mostrando.toLocaleString("pt-BR")}`;
    },
  });
  el("csv").addEventListener("click", exportarCSV);
  el("limpar").addEventListener("click", () => {
    for (const id of ["q", "ano", "status"]) el(id).value = "";
    aplicarFiltros();
  });
  aplicarFiltros();
}

init();
