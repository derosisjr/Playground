/* Escuta Pública — a cédula: uma proposta por vez, três botões de polegar.
   Votos vão ao Worker (Cloudflare KV); resultados parciais vêm do
   consulta-resultados.json publicado pela apuração (consulta/apurar.py). */
(function () {
  "use strict";

  // Preencher após o deploy do worker (workers/consulta/README.md).
  const WORKER_URL = "";
  const CONSULTA = "prioridades-2026";

  let DEF = null;          // definição da consulta (propostas, bairros)
  let fila = [];           // propostas ainda não votadas nesta sessão
  let idx = 0;
  let bairro = "nao-informado";

  const $ = (id) => document.getElementById(id);
  const chaveLocal = (p) => `consulta:${CONSULTA}:${p}`;

  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.add("ver");
    setTimeout(() => t.classList.remove("ver"), 2200);
  }

  async function enviar(rota, corpo) {
    if (!WORKER_URL) return { offline: true }; // consulta ainda não ativada
    try {
      const r = await fetch(WORKER_URL + rota, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo),
      });
      return await r.json();
    } catch {
      return { erro: "rede" };
    }
  }

  function init() {
    fetch(`./consulta/consultas/${CONSULTA}.json?v=` + Date.now())
      .then((r) => r.json())
      .then((d) => {
        DEF = d;
        $("titulo").textContent = d.titulo;
        $("descricao").textContent = d.descricao;
        const hoje = new Date().toISOString().slice(0, 10);
        if (!d.ativa || hoje > d.periodo.fim) {
          $("inicio").hidden = true;
          $("encerrada").hidden = false;
          carregarResultados();
          return;
        }
        const sel = $("bairro");
        sel.innerHTML = "<option value=''>Prefiro não dizer</option>" +
          d.bairros.map((b) => `<option>${b}</option>`).join("");
        $("comecar").addEventListener("click", comecar);
      });
    $("sug-enviar").addEventListener("click", sugerir);
  }

  function comecar() {
    bairro = $("bairro").value || "nao-informado";
    fila = DEF.propostas.filter((p) => !localStorage.getItem(chaveLocal(p.id)));
    if (!fila.length) { terminar(); return; }
    idx = 0;
    $("inicio").hidden = true;
    $("votacao").hidden = false;
    $("v-sim").onclick = () => votar("sim");
    $("v-nao").onclick = () => votar("nao");
    $("v-pular").onclick = () => votar("pular");
    render();
  }

  function render() {
    const total = DEF.propostas.length;
    const feitas = total - (fila.length - idx);
    $("pontos").innerHTML = DEF.propostas.map((_, i) =>
      `<span class="ponto${i < feitas ? " feito" : i === feitas ? " atual" : ""}"></span>`
    ).join("");
    $("num").textContent = `Proposta ${feitas + 1} de ${total}`;
    $("texto").textContent = fila[idx].texto;
  }

  async function votar(voto) {
    const p = fila[idx];
    for (const b of ["v-sim", "v-nao", "v-pular"]) $(b).disabled = true;
    localStorage.setItem(chaveLocal(p.id), voto);
    await enviar("/voto", { consulta: CONSULTA, proposta: p.id, voto, bairro });
    for (const b of ["v-sim", "v-nao", "v-pular"]) $(b).disabled = false;
    idx += 1;
    if (idx >= fila.length) terminar();
    else render();
  }

  function terminar() {
    $("votacao").hidden = true;
    $("inicio").hidden = true;
    $("fim").hidden = false;
    carregarResultados();
  }

  // Fita de consenso: resultados parciais publicados pela apuração.
  function carregarResultados() {
    const alvo = document.querySelector("#fim").hidden ? null : $("fita");
    fetch("./consulta-resultados.json?v=" + Date.now())
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((res) => {
        const c = res.consultas && res.consultas[CONSULTA];
        if (!c) throw new Error();
        renderFita(c, alvo || $("encerrada"));
      })
      .catch(() => {
        if (alvo) alvo.innerHTML =
          "<h2>Obrigado por participar!</h2><p class='quando'>Os resultados " +
          "parciais serão publicados aqui conforme a apuração.</p>";
      });
  }

  function renderFita(c, alvo) {
    const linhas = DEF.propostas.map((p) => {
      const v = c.propostas[p.id] || { sim: 0, nao: 0 };
      const tot = v.sim + v.nao;
      const pct = tot ? Math.round(v.sim / tot * 100) : 0;
      return { p, v, tot, pct };
    }).sort((a, b) => b.pct - a.pct);
    alvo.innerHTML = "<h2>Onde a cidade concorda</h2>" +
      `<p class="quando">Apuração de ${c.apurado_em} · ${c.total_votos} votos</p>` +
      linhas.map(({ p, v, tot, pct }) => `
        <div class="barra">
          <div class="rotulo">${p.texto}</div>
          <div class="trilho" role="img" aria-label="${pct}% concordam">
            <span class="sim" style="width:${pct}%"></span>
            <span class="nao" style="width:${tot ? 100 - pct : 0}%"></span>
          </div>
          <div class="num">${pct}% concordam · ${tot} votos</div>
        </div>`).join("");
  }

  async function sugerir() {
    const texto = $("sug-texto").value.trim();
    if (texto.length < 10) { toast("Escreva um pouco mais (mín. 10 caracteres)"); return; }
    const r = await enviar("/sugestao", { consulta: CONSULTA, texto, bairro });
    if (r.ok) { $("sug-texto").value = ""; toast("Sugestão enviada"); }
    else if (r.offline) toast("Consulta ainda não está no ar — em breve");
    else toast("Não foi possível enviar agora — tente de novo");
  }

  init();
})();
