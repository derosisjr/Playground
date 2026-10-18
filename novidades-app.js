// Novidades das bases — lê novidades.json (gerado 1×/dia por .github/scripts/novidades.py).
// Títulos vêm de texto de crawler: tudo montado com textContent, nunca innerHTML.
"use strict";

const BASES = {
  requerimentos: "Requerimentos",
  proposituras: "Proposituras",
  legis: "Legislação",
  despesas: "Despesas",
};
const TIPOS = {
  resposta: "Resposta recebida",
  prorrogacao: "Prazo prorrogado",
  vencido: "Prazo vencido",
  nova: "Novo",
  andamento: "Andamento",
  revogada: "Revogação",
  alerta: "Alerta novo",
  alerta_resolvido: "Alerta resolvido",
  mes_fechado: "Mês fechado",
};
// "Novo" = surgiu depois da última visita a esta página (aaaa-mm-dd, neste aparelho);
// o hub usa a mesma chave para dizer quantas novidades há desde então
const CHAVE_VISTO = "novidades:visto_ate";

const el = (id) => document.getElementById(id);
const no = (tag, cls, texto) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (texto != null) e.textContent = texto;
  return e;
};
const dataBR = (iso) => (iso || "").split("-").reverse().join("/");
const DIAS = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];
const rotuloDia = (iso) => {
  const [a, m, d] = iso.split("-").map(Number);
  return `${DIAS[new Date(a, m - 1, d).getDay()]}, ${dataBR(iso)}`;
};

let EVENTOS = [];
let VISTO_ANTES = "";
const filtro = { base: "", mandato: false };

function lerVisto() { try { return localStorage.getItem(CHAVE_VISTO) || ""; } catch { return ""; } }
function gravarVisto(iso) { try { localStorage.setItem(CHAVE_VISTO, iso); } catch { /* modo privado */ } }

// mandato: requerimentos são todos do gabinete; proposituras trazem `mandato: true`
const doMandato = (e) => e.base === "requerimentos" || e.mandato === true;

function montarFiltros() {
  const cont = el("filtros");
  const conta = (f) => EVENTOS.filter(f).length;
  const botoes = [["", "Todas", conta(() => true)]]
    .concat(Object.keys(BASES).map((b) => [b, BASES[b], conta((e) => e.base === b)]))
    .filter(([b, , n]) => !b || n);
  cont.replaceChildren(...botoes.map(([b, rotulo, n]) => {
    const bt = no("button", "chip");
    bt.type = "button";
    bt.dataset.base = b;
    bt.append(rotulo + " ", no("span", "n", n.toLocaleString("pt-BR")));
    return bt;
  }));
  const m = no("button", "chip");
  m.type = "button";
  m.dataset.mandato = "1";
  m.append("Só do mandato ", no("span", "n", conta(doMandato).toLocaleString("pt-BR")));
  cont.append(m);
  cont.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.mandato) filtro.mandato = !filtro.mandato;
    else filtro.base = b.dataset.base;
    render();
  });
}

function render() {
  for (const b of el("filtros").querySelectorAll("button")) {
    const ativo = b.dataset.mandato ? filtro.mandato : (b.dataset.base || "") === filtro.base;
    b.setAttribute("aria-pressed", String(ativo));
  }
  const lista = EVENTOS.filter((e) =>
    (!filtro.base || e.base === filtro.base) && (!filtro.mandato || doMandato(e)));
  const porDia = new Map();
  for (const e of lista) {
    if (!porDia.has(e.visto_em)) porDia.set(e.visto_em, []);
    porDia.get(e.visto_em).push(e);
  }
  const blocos = [];
  for (const [dia, evs] of porDia) {
    const ul = no("ul", "eventos");
    for (const e of evs) {
      const li = no("li", "ev");
      li.append(no("span", "ev-tipo " + e.tipo, `${BASES[e.base] || e.base} · ${TIPOS[e.tipo] || e.tipo}`));
      const corpo = no("span");
      const a = no("a", null, e.titulo);
      a.href = "./" + e.link;
      corpo.append(a);
      if (e.mandato) corpo.append(no("span", "mandato", "do mandato"));
      if (VISTO_ANTES && e.visto_em > VISTO_ANTES) corpo.append(no("span", "novo", "novo"));
      li.append(corpo);
      ul.append(li);
    }
    blocos.push(no("h2", "dia", rotuloDia(dia)), ul);
  }
  el("lista").replaceChildren(...blocos);
  const vazio = el("vazio");
  vazio.hidden = lista.length > 0;
  vazio.textContent = EVENTOS.length
    ? "Nada com esses filtros nos últimos 60 dias."
    : "A lista começa a ser preenchida no dia seguinte à primeira atualização das bases.";
  Comum.gravarParams({ base: filtro.base, mandato: filtro.mandato ? "1" : "" });
}

function resumo() {
  const novos = VISTO_ANTES ? EVENTOS.filter((e) => e.visto_em > VISTO_ANTES).length : 0;
  const r = el("resumo");
  r.replaceChildren();
  if (!EVENTOS.length) { r.textContent = "Sem novidades registradas ainda."; return; }
  if (VISTO_ANTES) {
    r.append(no("b", null, novos.toLocaleString("pt-BR")),
      ` ${novos === 1 ? "novidade" : "novidades"} desde a sua última visita (${dataBR(VISTO_ANTES)}) · `,
      no("b", null, EVENTOS.length.toLocaleString("pt-BR")), " nos últimos 60 dias");
  } else {
    r.append(no("b", null, EVENTOS.length.toLocaleString("pt-BR")), " novidades nos últimos 60 dias");
  }
}

async function init() {
  let d;
  try {
    const r = await fetch("./novidades.json", { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    d = await r.json();
  } catch (e) {
    el("resumo").textContent = "";
    Comum.estadoErro("lista", "Não foi possível carregar as novidades. Verifique a conexão.", init);
    return;
  }
  EVENTOS = Array.isArray(d.eventos) ? d.eventos : [];
  VISTO_ANTES = lerVisto();
  if (d.gerado_em) {
    const g = new Date(d.gerado_em);
    el("gerado").textContent = `Lista montada em ${g.toLocaleDateString("pt-BR")} às ` +
      g.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  const p = Comum.lerParams();
  filtro.base = BASES[p.get("base")] ? p.get("base") : "";
  filtro.mandato = p.get("mandato") === "1";
  montarFiltros();
  resumo();
  render();
  // a partir de agora, "novo" é o que vier depois do evento mais recente desta visita
  if (EVENTOS.length) gravarVisto(EVENTOS[0].visto_em);
}

init();
