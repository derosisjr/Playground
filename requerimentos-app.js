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

  const de = `${respondidos.toLocaleString("pt-BR")} de ${total.toLocaleString("pt-BR")}`;
  const cards = CLASSIFICADO ? [
    { rotulo: "Requerimentos", valor: total.toLocaleString("pt-BR"), sub: "no filtro atual" },
    { rotulo: "Respondidos", valor: `${pct}%`, sub: `${de} — com resposta de mérito` },
    { rotulo: "Sem resposta de mérito", valor: semMerito.toLocaleString("pt-BR"), sub: tramite ? `${tramite.toLocaleString("pt-BR")} só receberam trâmite` : "aguardando o Executivo" },
    { rotulo: "Tempo médio de resposta", valor: media == null ? "—" : `${media} dias`, sub: "entre a sessão e a resposta de mérito" },
  ] : [
    // sem classificação na base: o mesmo número, com o nome que ele tem de fato
    { rotulo: "Requerimentos", valor: total.toLocaleString("pt-BR"), sub: "no filtro atual" },
    { rotulo: "Com algum retorno", valor: `${pct}%`, sub: `${de} — ${TXT_RETORNO}` },
    { rotulo: "Sem nenhum retorno", valor: semMerito.toLocaleString("pt-BR"), sub: "aguardando o Executivo" },
    { rotulo: "Tempo médio de retorno", valor: media == null ? "—" : `${media} dias`, sub: "entre a sessão e a data de resposta registrada (pode ser prorrogação)" },
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

// Base sem classificação de mérito: textos e filtros deixam de prometer mérito.
function semClassificacao() {
  ROTULOS.respondido = "Retorno ↗";
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
  CLASSIFICADO = baseClassificada(ITENS);
  if (!CLASSIFICADO) semClassificacao();
  preencherSelects();
  // estado vindo da URL (link compartilhável) — antes do primeiro render
  const p = Comum.lerParams();
  for (const id of ["q", "ano", "status"]) {
    let v = p.get(id);
    if (id === "status" && v === "pendente" && !CLASSIFICADO) v = "nao";
    if (v) el(id).value = v;
  }
  el("q").addEventListener("input", Comum.debounce(aplicarFiltros));
  ["ano", "status"].forEach((id) => el(id).addEventListener("input", aplicarFiltros));
  pag = Comum.paginador({
    corpo: "corpo", mais: "mais", contagem: "contagem", linha: linhaHTML,
    rotulo: (lista, mostrando) => {
      const respondidos = lista.filter((i) => i.respondido).length;
      const qual = CLASSIFICADO ? "com resposta de mérito" : "com algum retorno da Prefeitura";
      return `${lista.length.toLocaleString("pt-BR")} requerimento(s) — ${respondidos.toLocaleString("pt-BR")} ${qual} — exibindo ${mostrando.toLocaleString("pt-BR")}`;
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
