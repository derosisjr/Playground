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
};
// Coluna "Situação": rótulos públicos da classificação (espelho de ROTULOS em
// respostas-executivo/classificar.py). Antes a coluna mostrava o "Status atual"
// da planilha — anotações internas do gabinete, que não são para o público.
const SITUACAO_ROTULO = {
  respondido: "Respondido",
  so_prorrogacao: "Prazo prorrogado",
  so_encaminhamento: "Só encaminhamento",
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
  // o .sub é de uma linha só (comum.css corta com reticências): o essencial vem
  // primeiro e o texto completo fica no `title`
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
    Comum.estadoErro("stats",
      "Não foi possível carregar os requerimentos. Verifique a conexão.", init);
    return;
  }
  for (const i of ITENS) derivar(i);
  for (const i of ITENS) for (const n of i.cita || []) (CITADO_POR[n] = CITADO_POR[n] || []).push(i.numero);
  CLASSIFICADO = baseClassificada(ITENS);
  if (!CLASSIFICADO) semClassificacao();
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
