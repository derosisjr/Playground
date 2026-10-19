// Camada comum do site — topbar, estado na URL, export CSV e busca universal (⌘K).
// Sem build: script clássico, expõe window.Comum.
"use strict";

window.Comum = (() => {
  const POP_SANTOS = 418608; // IBGE, Censo 2022 definitivo (per capita nos painéis; mesma base do benchmark)

  // [arquivo, rótulo na faixa do desktop (null = só no menu), nome do cartão no hub, seção]
  // A faixa do desktop não tem folga (10 itens + busca + tema em 1140px úteis): os
  // rótulos curtos ficam, com o nome do cartão no `title`. O menu do celular usa o
  // nome e as seções dos cartões do hub — antes o celular mostrava 2 de 10 itens e
  // "Endividamento"/"Indicadores" não batiam com "Semáforo Fiscal"/"Custo por Resultado".
  const PAGINAS = [
    ["index.html", "Início", "Início", ""],
    ["despesas.html", "Despesas", "Radar de Despesas", "Bases de dados"],
    ["endividamento.html", "Semáforo Fiscal", "Semáforo Fiscal", "Bases de dados"],
    ["precos.html", "Preços", "Preço comparado", "Bases de dados"],
    ["proposituras.html", "Proposituras", "Base de Proposituras", "Bases de dados"],
    ["legis.html", "Legislação", "Base de Legislação", "Bases de dados"],
    ["requerimentos.html", "Requerimentos", "Requerimentos & Respostas", "Bases de dados"],
    ["regimento.html", "Regimento", "Regimento Interno", "Bases de dados"],
    ["indicadores.html", "Indicadores", "Custo por Resultado", "Leituras e participação"],
    ["retrospectiva.html", null, "O ano em gastos", "Leituras e participação"],
    ["consulta.html", "Escuta Pública", "Escuta pública", "Leituras e participação"],
    ["novidades.html", null, "Novidades das bases", "Acompanhamento"],
  ];
  let paginaAtual = null;

  const escapar = (s) =>
    (s == null ? "" : String(s)).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Narrativa com os números em negrito (valores em R$ e percentuais) — o "Em resumo"
  // dos painéis. Devolve HTML: escapa ANTES de marcar (o texto vem do export).
  const RE_NUMEROS = /([+−-]?R\$\s?[\d.,]*\d(?:\s(?:milhões|milhão|bilhões|bilhão|mil|mi|bi)\b)?|[+−-]?\d+(?:,\d+)?%)/g;
  const destacarNumeros = (texto) => escapar(texto).replace(RE_NUMEROS, "<b>$1</b>");

  const norm = (s) =>
    (s || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

  // Identidade canônica do favorecido — ESPELHO de despesas/formato.py
  // (identidade_favorecido): CNPJ completo → "cnpj:<14 dígitos>"; CPF mascarado →
  // "cpf:<dígitos visíveis>|<NOME NORMALIZADO>" (dígitos parciais não bastam);
  // documento atípico → "doc:…|nome"; sem documento → "nome:<NOME>". Nome
  // normalizado = maiúsculas, sem acento, espaços colapsados. Mudar um lado
  // exige mudar o outro (o índice de favorecidos e os dossiês usam esta chave).
  const nomeNormalizado = (nome) =>
    (nome || "").toString().normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase()
      .split(/\s+/).filter(Boolean).join(" ");
  const identidadeFavorecido = (nome, doc) => {
    doc = (doc || "").toString().trim();
    const dig = doc.replace(/\D/g, "");
    if (!doc.includes("*") && dig.length === 14) return "cnpj:" + dig;
    const n = nomeNormalizado(nome);
    if (doc.includes("*")) return "cpf:" + dig + "|" + n;
    if (dig) return "doc:" + dig + "|" + n;
    return "nome:" + n;
  };

  // Formatação de moeda — UMA escala para o site inteiro (a mesma de
  // despesas/formato.py e do hub): R$ 8,61 bi · R$ 157,0 mi · R$ 500 mil · R$ 123.
  // Antes havia quatro variantes (1 ou 2 casas no "bi", 0 ou 1 no "mi") e o
  // mesmo valor saía diferente entre o hub e o painel.
  const brl = (v, casas = 0) => (v ?? 0).toLocaleString("pt-BR",
    { style: "currency", currency: "BRL", minimumFractionDigits: casas, maximumFractionDigits: casas });
  const compacto = (v) => {
    v = v || 0;
    const a = Math.abs(v);
    if (a >= 1e9) return "R$ " + (v / 1e9).toFixed(2).replace(".", ",") + " bi";
    if (a >= 1e6) return "R$ " + (v / 1e6).toFixed(1).replace(".", ",") + " mi";
    if (a >= 1e3) return "R$ " + Math.round(v / 1e3) + " mil";
    return brl(v);
  };
  // Eixo dos gráficos: os ticks são números redondos e as casas zeradas sobravam
  // ("R$ 600,0 mi" → "R$ 600 mi"; "R$ 1,50 bi" → "R$ 1,5 bi"). Tooltip segue com compacto.
  const compactoEixo = (v) => compacto(v).replace(/,(\d*?)0+ (mi|bi)$/, (_, d, u) => (d ? "," + d : "") + " " + u);
  const digitos = (s) => (s || "").toString().replace(/\D/g, "");
  // adia `fn` até parar de chamar por `ms` — busca a cada tecla em milhares de linhas
  const debounce = (fn, ms = 150) => {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  };

  // ── Topbar ──────────────────────────────────────────────────────────────────
  // Injeta a barra de navegação no topo. `atual` = nome do arquivo da página.
  function topbar(atual) {
    paginaAtual = atual;
    const nav = document.createElement("nav");
    nav.className = "topnav";
    nav.setAttribute("aria-label", "Painéis do site");
    const link = (arq, rotulo, nome) => {
      const cls = [arq === "index.html" ? "inicio" : "", arq === atual ? "atual" : ""].filter(Boolean).join(" ");
      return `<a href="./${arq}"` + (cls ? ` class="${cls}"` : "") +
        (arq === atual ? ' aria-current="page"' : "") +
        (nome !== rotulo ? ` title="${escapar(nome)}"` : "") + `>${escapar(rotulo)}</a>`;
    };
    // menu do celular: nome do cartão, nas seções do hub
    let secao = null, lista = "";
    for (const [arq, , nome, sec] of PAGINAS) {
      if (!sec) continue;
      if (sec !== secao) { lista += (secao ? "</ul>" : "") + `<p class="topnav-secao">${escapar(sec)}</p><ul>`; secao = sec; }
      lista += `<li>${link(arq, nome, nome)}</li>`;
    }
    // os links rolam numa faixa própria; busca e tema ficam fixos à direita
    // (antes rolavam junto e saíam cortados no desktop de 1280–1440px)
    nav.innerHTML = '<div class="topnav-in"><div class="topnav-links">' +
      PAGINAS.filter(([, rotulo]) => rotulo).map(([arq, rotulo, nome]) => link(arq, rotulo, nome)).join("") +
      "</div>" +
      '<button type="button" class="topnav-menu" aria-expanded="false" aria-controls="topnav-lista">' +
      'Painéis <span aria-hidden="true">▾</span></button>' +
      '<button type="button" class="topnav-busca" aria-label="Buscar em todas as bases">' +
      'Buscar <kbd>Ctrl K</kbd></button>' +
      '<button type="button" class="topnav-tema" aria-label="Alternar tema claro/escuro">' +
      (temaAtual() === "escuro" ? "☀" : "🌙") + "</button></div>" +
      `<div class="topnav-lista" id="topnav-lista" hidden>${lista}</ul></div>`;
    document.body.prepend(nav);
    nav.querySelector(".topnav-busca").addEventListener("click", abrirPaleta);
    nav.querySelector(".topnav-tema").addEventListener("click", alternarTema);
    // menu "Painéis" (só aparece no celular — ver .topnav-menu no comum.css)
    const botaoMenu = nav.querySelector(".topnav-menu"), painel = nav.querySelector(".topnav-lista");
    const fecharMenu = (devolverFoco) => {
      painel.hidden = true;
      botaoMenu.setAttribute("aria-expanded", "false");
      if (devolverFoco) botaoMenu.focus();
    };
    botaoMenu.addEventListener("click", () => {
      const abrir = painel.hidden;
      painel.hidden = !abrir;
      botaoMenu.setAttribute("aria-expanded", String(abrir));
      if (abrir) (painel.querySelector("a.atual") || painel.querySelector("a")).focus();
    });
    painel.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); fecharMenu(true); }
    });
    document.addEventListener("click", (e) => {
      if (!painel.hidden && !nav.contains(e.target)) fecharMenu(false);
    });
    // celular: com 10 itens a faixa rola na horizontal e o item da página atual
    // ficava fora da tela — centraliza-o. Mexe só no scrollLeft da faixa (efeito
    // de scrollIntoView({inline:"center"}) sem nenhum risco de rolar a página na
    // vertical, p.ex. quando a URL traz âncora como #art-79). Se o item já está
    // inteiro à vista (desktop), não mexe. Repete após as fontes carregarem, que
    // mudam a largura dos itens.
    const centralizarAtual = () => {
      const faixa = nav.querySelector(".topnav-links"), ativo = faixa.querySelector("a.atual");
      if (!ativo || faixa.scrollWidth <= faixa.clientWidth) return;
      const a = ativo.getBoundingClientRect(), f = faixa.getBoundingClientRect();
      // 26px = esmaecimento da máscara na borda direita (ver .topnav-links no comum.css)
      if (a.left >= f.left && a.right <= f.right - 26) return;
      faixa.scrollLeft += (a.left + a.width / 2) - (f.left + faixa.clientWidth / 2);
    };
    centralizarAtual();
    if (document.fonts) document.fonts.ready.then(centralizarAtual);
  }

  // ── Tema claro/escuro ───────────────────────────────────────────────────────
  // O atributo inicial é aplicado por um snippet inline no <head> (anti-flash);
  // aqui fica só a troca. Páginas com Chart.js escutam "temamudou" e repintam
  // os gráficos em memória — sem reload, preservando rolagem e aba ativa.
  function temaAtual() {
    return document.documentElement.dataset.tema === "escuro" ? "escuro" : "claro";
  }
  function alternarTema() {
    const novo = temaAtual() === "escuro" ? "claro" : "escuro";
    try { localStorage.setItem("tema", novo); } catch (e) { /* modo privado */ }
    if (novo === "escuro") document.documentElement.dataset.tema = "escuro";
    else delete document.documentElement.dataset.tema;
    document.querySelectorAll(".topnav-tema, .hub-tema").forEach((b) =>
      b.textContent = novo === "escuro" ? "☀" : "🌙");
    window.dispatchEvent(new CustomEvent("temamudou", { detail: { escuro: novo === "escuro" } }));
  }

  // ── Estado na URL (links compartilháveis) ───────────────────────────────────
  function lerParams() {
    return new URLSearchParams(location.search);
  }
  function gravarParams(obj) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(obj)) if (v) p.set(k, v);
    const qs = p.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
  }

  // ── CSV no dialeto Excel pt-BR (`;`, BOM, CRLF) ─────────────────────────────
  function exportarCsv(nomeArquivo, cabecalhos, linhas) {
    const sep = ";";
    const esc = (v) => {
      // número → vírgula decimal: com `;` como separador o Excel pt-BR lia "73298.35"
      // como texto (não somava); sem separador de milhar para continuar numérico
      const s = typeof v === "number" && Number.isFinite(v) ? String(v).replace(".", ",") : String(v ?? "");
      return /[";\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const out = [cabecalhos.map(esc).join(sep)];
    for (const r of linhas) out.push(r.map(esc).join(sep));
    const blob = new Blob(["﻿" + out.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = nomeArquivo;
    a.style.display = "none";
    document.body.appendChild(a);  // Firefox só baixa com o <a> no DOM
    a.click();
    // revogar depois de o clique ser processado — síncrono, o Firefox cancelava o download
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }

  // ── Toast (aviso passageiro, no lugar de alert()) ───────────────────────────
  let toastEl = null, toastTimer = null;
  function toast(msg) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "toast-comum";
      toastEl.setAttribute("role", "status");
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.add("ver");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("ver"), 2600);
  }

  // ── Copiar texto (rascunhos de requerimento, links, citações) ───────────────
  // A API da área de transferência exige contexto seguro e permissão; fora disso
  // (http local, navegador antigo) cai no textarea + execCommand. Devolve true/false
  // e avisa por toast nos dois casos.
  async function copiar(texto, aviso = "Copiado para a área de transferência") {
    try {
      await navigator.clipboard.writeText(texto);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = texto;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch { /* sem cópia neste navegador */ }
      ta.remove();
      if (!ok) { toast("Não foi possível copiar — selecione o texto à mão"); return false; }
    }
    toast(aviso);
    return true;
  }

  // ── Estado de erro padrão com "Tentar de novo" ──────────────────────────────
  // alvo: elemento ou id; aoTentar: callback que refaz a carga (ex.: init).
  function estadoErro(alvo, mensagem, aoTentar) {
    const el = typeof alvo === "string" ? document.getElementById(alvo) : alvo;
    if (!el) return;
    el.hidden = false;
    el.innerHTML = `<div class="estado-erro" role="alert"><p>${escapar(mensagem)}</p>` +
      '<button type="button" class="btn">Tentar de novo</button></div>';
    el.querySelector("button").addEventListener("click", aoTentar);
  }

  // ── Texto grande em fonte web: escrever só com a fonte carregada ─────────────
  // Pintado com a fonte de reserva (Georgia), um parágrafo em Fraunces troca de
  // linha quando a fonte chega — trechos pulam de uma linha para outra e o que vem
  // embaixo desce (CLS de 0,3–0,4 medido no "Em resumo" e no Custo por Resultado).
  // Espera as faces pedidas (ex.: '400 20px "Fraunces"'), no máximo `ms`, e chama fn.
  function quandoFonte(faces, fn, ms = 2500) {
    const carga = document.fonts ? Promise.all(faces.map((f) => document.fonts.load(f))) : Promise.resolve();
    Promise.race([carga, new Promise((ok) => setTimeout(ok, ms))]).catch(() => {}).then(fn);
  }
  // faces do número-manchete do hero (.hero-num): o número e a frase, com negrito
  const FACES_MANCHETE = ['600 52px "IBM Plex Mono"', '400 13.5px Manrope', '700 13.5px Manrope'];

  // ── Visualizador de PDF embutido (Comum.visorPdf) ───────────────────────────
  // PDF.js 6 (ESM no cdnjs), carregado sob demanda no 1º uso. Os PDFs da Câmara
  // (proposituras) vêm com CORS aberto e renderizam em <canvas>, página a página
  // conforme a rolagem. Se a biblioteca não carregar (CDN fora do ar), o visor cai
  // para <iframe> com o visualizador nativo. "Abrir ↗" (nova aba) é a saída garantida.
  // Só serve para PDF servido inline: o Legis da Prefeitura manda
  // `Content-Disposition: attachment` (e sem CORS), então lá o link segue direto.
  const PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/6.3.289/";
  let pdfjsPromessa = null, visorFundo = null, visorFocoAnterior = null;
  let visorDoc = null, visorTask = null, visorObs = null;

  function carregarPdfjs() {
    if (!pdfjsPromessa) {
      pdfjsPromessa = import(PDFJS + "pdf.min.mjs")
        .then((m) => { m.GlobalWorkerOptions.workerSrc = PDFJS + "pdf.worker.min.mjs"; return m; })
        .catch((e) => { pdfjsPromessa = null; throw e; });
    }
    return pdfjsPromessa;
  }

  function montarVisor() {
    if (visorFundo) return;
    visorFundo = document.createElement("div");
    visorFundo.className = "visor-fundo";
    visorFundo.hidden = true;
    visorFundo.innerHTML =
      '<div class="visor" role="dialog" aria-modal="true" aria-labelledby="visor-titulo">' +
      '<div class="visor-cab">' +
      '<div class="visor-tit"><strong id="visor-titulo"></strong>' +
      '<span class="visor-pag" aria-live="polite"></span></div>' +
      '<div class="visor-acoes">' +
      '<a class="btn visor-abrir" target="_blank" rel="noopener">Abrir ↗</a>' +
      '<button type="button" class="btn visor-fechar" aria-label="Fechar visualizador">✕</button>' +
      "</div></div>" +
      '<div class="visor-corpo" tabindex="0"></div>' +
      "</div>";
    document.body.appendChild(visorFundo);
    visorFundo.querySelector(".visor-fechar").addEventListener("click", fecharVisor);
    visorFundo.addEventListener("mousedown", (e) => { if (e.target === visorFundo) fecharVisor(); });
    visorFundo.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); fecharVisor(); return; }
      if (e.key !== "Tab") return;
      // foco preso no diálogo (mesmo padrão da paleta): Tab circula pelos controles
      const focaveis = [...visorFundo.querySelectorAll("a[href], button, .visor-corpo")];
      const i = focaveis.indexOf(document.activeElement);
      const prox = e.shiftKey ? (i <= 0 ? focaveis.length - 1 : i - 1)
                              : (i >= focaveis.length - 1 ? 0 : i + 1);
      e.preventDefault();
      focaveis[prox].focus();
    });
  }

  function fecharVisor() {
    if (!visorFundo || visorFundo.hidden) return;
    visorFundo.hidden = true;
    document.body.style.overflow = "";
    if (visorObs) { visorObs.disconnect(); visorObs = null; }
    // PDF.js 6: o descarte é da tarefa de carga (PDFDocumentProxy não tem destroy)
    if (visorTask) { visorTask.destroy(); visorTask = null; }
    visorDoc = null;
    visorFundo.querySelector(".visor-corpo").innerHTML = "";
    if (visorFocoAnterior && typeof visorFocoAnterior.focus === "function") visorFocoAnterior.focus();
    visorFocoAnterior = null;
  }

  async function visorPdf(url, titulo) {
    montarVisor();
    fecharVisor();
    visorFocoAnterior = document.activeElement;
    const corpo = visorFundo.querySelector(".visor-corpo");
    const pagEl = visorFundo.querySelector(".visor-pag");
    visorFundo.querySelector("#visor-titulo").textContent = titulo || "Documento";
    visorFundo.querySelector(".visor-abrir").href = url;
    pagEl.textContent = "";
    corpo.innerHTML = '<p class="visor-aviso">Carregando o PDF…</p>';
    visorFundo.hidden = false;
    document.body.style.overflow = "hidden";
    visorFundo.querySelector(".visor-fechar").focus();

    let doc, task;
    try {
      const pdfjs = await carregarPdfjs();
      task = pdfjs.getDocument({ url });
      doc = await task.promise;
    } catch (e) {
      console.warn("visor pdf: visualizador nativo (sem CORS ou biblioteca indisponível):", e.message);
      if (visorFundo.hidden) return;  // fechado antes de carregar
      // navegador sem visualizador nativo (celular) mostra o quadro em branco: a
      // dica aponta a saída
      corpo.innerHTML = '<p class="visor-aviso visor-dica">Visualizador do navegador — se o documento não aparecer, use "Abrir ↗".</p>';
      const f = document.createElement("iframe");
      f.className = "visor-iframe";
      f.src = url;
      f.title = titulo || "Documento";
      corpo.appendChild(f);
      return;
    }
    if (visorFundo.hidden) { task.destroy(); return; }
    visorDoc = doc;
    visorTask = task;
    corpo.innerHTML = "";
    const total = doc.numPages;
    const largura = Math.max(corpo.clientWidth - 32, 200);  // desconta o padding do corpo
    const dpr = Math.min(window.devicePixelRatio || 1, 2);   // nitidez sem canvas gigante
    const paginas = [];
    for (let n = 1; n <= total; n++) {
      const c = document.createElement("canvas");
      c.className = "visor-pagina";
      c.dataset.n = n;
      c.setAttribute("role", "img");
      c.setAttribute("aria-label", "Página " + n + " de " + total);
      corpo.appendChild(c);
      paginas.push(c);
    }
    // a 1ª página dá a proporção às demais: placeholders com a altura certa
    // evitam salto de rolagem enquanto cada página renderiza ao entrar na tela
    const primeira = await doc.getPage(1);
    const vp1 = primeira.getViewport({ scale: 1 });
    const escala = largura / vp1.width;
    const alturaPagina = Math.round(vp1.height * escala);
    for (const c of paginas) { c.style.width = largura + "px"; c.style.height = alturaPagina + "px"; }
    pagEl.textContent = "1 / " + total;

    async function renderizar(c) {
      if (c.dataset.ok || visorDoc !== doc) return;
      c.dataset.ok = "1";
      const page = await doc.getPage(+c.dataset.n);
      const vp = page.getViewport({ scale: escala });
      c.width = Math.round(vp.width * dpr);
      c.height = Math.round(vp.height * dpr);
      c.style.height = Math.round(vp.height) + "px";
      const params = { canvas: c, canvasContext: c.getContext("2d"), viewport: vp };
      if (dpr !== 1) params.transform = [dpr, 0, 0, dpr, 0, 0];
      try { await page.render(params).promise; }
      catch (e) { if (visorDoc === doc) throw e; }  // fechar no meio cancela o render: esperado
    }
    visorObs = new IntersectionObserver((ents) => {
      for (const en of ents) if (en.isIntersecting) renderizar(en.target);
    }, { root: corpo, rootMargin: "600px 0px" });
    paginas.forEach((c) => visorObs.observe(c));
    corpo.onscroll = () => {
      const n = Math.min(total, Math.floor((corpo.scrollTop + corpo.clientHeight / 2) / (alturaPagina + 12)) + 1);
      pagEl.textContent = n + " / " + total;
    };
  }

  // ── Lista paginada com "Mostrar mais" ───────────────────────────────────────
  // legis, proposituras e requerimentos tinham o mesmo renderizarMais copiado.
  // corpo/mais/contagem: ids; linha(item) → HTML; rotulo(lista, mostrando) → texto.
  const PAGINADORES = [];  // a impressão expande todos (ver "beforeprint")
  function paginador({ corpo, mais, contagem, linha, rotulo, tamanho = 200 }) {
    const $ = (id) => document.getElementById(id);
    let lista = [], mostrando = 0;
    function maisLinhas() {
      const fim = Math.min(mostrando + tamanho, lista.length);
      $(corpo).insertAdjacentHTML("beforeend", lista.slice(mostrando, fim).map(linha).join(""));
      mostrando = fim;
      $(mais).hidden = mostrando >= lista.length;
      const c = $(contagem);
      c.textContent = rotulo(lista, mostrando);
      c.classList.remove("pulsa"); void c.offsetWidth;  // reinicia a animação
      c.classList.add("pulsa");
    }
    function reiniciar(nova) { lista = nova; mostrando = 0; $(corpo).innerHTML = ""; maisLinhas(); }
    // mostra até `limite` linhas de uma vez (impressão: o papel não tem "Mostrar mais")
    function tudo(limite) { while (mostrando < Math.min(lista.length, limite)) maisLinhas(); }
    $(mais).addEventListener("click", maisLinhas);
    const api = { reiniciar, mais: maisLinhas, tudo, total: () => lista.length, mostrando: () => mostrando };
    PAGINADORES.push(api);
    return api;
  }

  // ── Compartilhar e imprimir (botões com data-acao nas barras dos painéis) ────
  // Os filtros já estão na URL (gravarParams): compartilhar é mandar o endereço.
  // No celular abre a folha de compartilhamento do sistema; no resto, copia.
  async function compartilhar() {
    if (navigator.share && matchMedia("(pointer: coarse)").matches) {
      try { await navigator.share({ title: document.title, url: location.href }); return; }
      catch (e) { if (e && e.name === "AbortError") return; }
    }
    copiar(location.href, "Link copiado — os filtros vão junto");
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-acao]");
    if (!b) return;
    if (b.dataset.acao === "compartilhar") compartilhar();
    else if (b.dataset.acao === "imprimir") window.print();
  });

  // Impressão (material de sessão/comissão): a folha leva a lista inteira até
  // LIMITE_IMPRESSAO linhas e, no topo, data e endereço da consulta (com filtros).
  const LIMITE_IMPRESSAO = 2000;
  window.addEventListener("beforeprint", () => {
    for (const p of PAGINADORES) p.tudo(LIMITE_IMPRESSAO);
    let linha = document.querySelector(".so-impressao");
    if (!linha) {
      linha = document.createElement("p");
      linha.className = "so-impressao";
      (document.querySelector("main") || document.body).prepend(linha);
    }
    const cortada = PAGINADORES.find((p) => p.total() > p.mostrando());
    linha.textContent = `Impresso em ${new Date().toLocaleString("pt-BR")} · ${location.href}` +
      (cortada ? ` · lista com ${cortada.mostrando()} de ${cortada.total()} linhas: refine os filtros para imprimir o resto` : "");
  });

  // ── "Base atualizada em…" (elementos com data-base="<arquivo do índice>") ────
  // Mesma fonte do hub (bases-atualizacao.json, data do último commit da base):
  // com o service worker servindo o JSON do cache, o painel precisa dizer de quando
  // é o que está na tela.
  function preencherBases() {
    const alvos = document.querySelectorAll("[data-base]");
    if (!alvos.length) return;
    fetch("./bases-atualizacao.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((m) => {
        for (const e of alvos) {
          const iso = m.bases && m.bases[e.dataset.base];
          if (!iso) continue;
          const d = new Date(iso);
          e.textContent = `Base atualizada em ${d.toLocaleDateString("pt-BR")} às ` +
            d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
        }
      })
      .catch(() => { /* sem o índice de datas a linha fica vazia (altura já reservada) */ });
  }

  // ── Celular: texto do hero recolhido em 3 linhas (o 1º resultado ficava abaixo da dobra)
  function recolherHero() {
    if (!matchMedia("(max-width: 600px)").matches) return;
    const hero = document.querySelector("header.hero");
    const sub = hero && hero.querySelector(".hero-sub");
    if (!sub) return;
    // painel com número-manchete: o parágrafo nasce escondido (comum.css) e o botão
    // vem depois do número — título, número, "Sobre este painel", data da base
    const manchete = hero.classList.contains("com-manchete") && hero.querySelector(".hero-num");
    if (!manchete && sub.scrollHeight <= sub.clientHeight + 2) return;  // cabe nas 3 linhas
    // painel com manchete traz o botão pronto no HTML (.sobre-painel) — sem "pulo"
    const pronto = hero.querySelector(".sobre-painel");
    const b = pronto || document.createElement("button");
    b.type = "button";
    b.className = pronto ? "hero-mais sobre-painel" : "hero-mais";
    b.setAttribute("aria-expanded", "false");
    b.textContent = "Sobre este painel ▾";
    b.addEventListener("click", () => {
      const aberto = sub.classList.toggle("aberto");
      b.setAttribute("aria-expanded", String(aberto));
      b.textContent = aberto ? "Menos ▴" : "Sobre este painel ▾";
    });
    if (!pronto) (manchete || sub).after(b);
  }

  // ── Aviso de dados novos (mensagem do sw.js) ────────────────────────────────
  // O service worker serve os *.json do cache e revalida por trás; quando a versão
  // da rede é outra, a página está mostrando a base anterior — avisa uma vez.
  let avisoDados = null;
  function avisarDadosNovos() {
    if (avisoDados) return;
    avisoDados = document.createElement("div");
    avisoDados.className = "faixa-dados-novos";
    avisoDados.setAttribute("role", "status");
    avisoDados.innerHTML = '<span>Há dados mais novos desta página.</span>' +
      '<button type="button" class="dn-atualizar">Atualizar</button>' +
      '<button type="button" class="dn-fechar" aria-label="Dispensar aviso">×</button>';
    avisoDados.querySelector(".dn-atualizar").addEventListener("click", () => location.reload());
    avisoDados.querySelector(".dn-fechar").addEventListener("click", () => avisoDados.remove());
    document.body.appendChild(avisoDados);
  }

  function aoCarregar() { preencherBases(); recolherHero(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", aoCarregar);
  else aoCarregar();

  // ── Acessibilidade de gráficos ──────────────────────────────────────────────
  // Canvas é invisível para leitor de tela (padrão USWDS): dá role="img" +
  // descrição conclusiva e anexa uma tabela equivalente visualmente oculta,
  // gerada do MESMO array que alimenta o gráfico.
  function chartAcessivel(canvas, descricao, cabecalhos, linhas) {
    const c = typeof canvas === "string" ? document.getElementById(canvas) : canvas;
    if (!c || !c.parentNode) return;
    c.setAttribute("role", "img");
    c.setAttribute("aria-label", descricao);
    const marca = c.id || c.getAttribute("aria-label") || "";
    const ant = c.parentNode.querySelector(`table.sr-only[data-de="${marca}"]`);
    if (ant) ant.remove(); // rerender (troca de filtro/ano) não duplica a tabela
    const t = document.createElement("table");
    t.className = "sr-only";
    t.dataset.de = marca;
    t.innerHTML = "<caption>" + escapar(descricao) + "</caption><thead><tr>" +
      cabecalhos.map((h) => '<th scope="col">' + escapar(h) + "</th>").join("") +
      "</tr></thead><tbody>" +
      linhas.map((r) => "<tr>" + r.map((v) => "<td>" + escapar(v) + "</td>").join("") + "</tr>").join("") +
      "</tbody></table>";
    c.insertAdjacentElement("afterend", t);
  }

  // ── Busca universal (⌘K / Ctrl+K / "/") ─────────────────────────────────────
  // Fontes carregadas SOB DEMANDA e cacheadas em memória. As pequenas vêm na 1ª
  // abertura; as `grande: true` (proposituras ~5 MB, legislação ~1,4 MB, despesas
  // ~0,4 MB — antes eram ~7 MB baixados e parseados a cada 1º Ctrl+K) só quando a
  // busca tem MIN_GRANDES caracteres, ou de imediato na própria página da base.
  // Cada item vira {t: título, s: subtítulo, url, h: haystack normalizado}.
  const FONTES = [
    { id: "regimento", rotulo: "Regimento Interno", url: "./regimento-index.json",
      mapear: (d) => d.map((a) => ({
        t: "Art. " + a.numero,
        s: ((a.blocos && a.blocos[0] && a.blocos[0].texto) || "").slice(0, 110),
        url: "./regimento.html#" + a.id,
        h: norm("art artigo " + a.numero + " " + (a.texto_busca || "")),
        numArt: String(a.numero).toLowerCase(),
      })) },
    { id: "proposituras", rotulo: "Proposituras", url: "./proposituras-index.json", grande: true,
      paginas: ["proposituras.html"],
      // link pela chave estável (`cod`): "?q=1/2026" casava também 11/2026, 101/2026…
      mapear: (d) => d.map((p) => ({
        t: (p.subtipo || "Projeto") + " " + p.numero,
        s: (p.ementa || "").slice(0, 110),
        url: p.cod ? "./proposituras.html?cod=" + encodeURIComponent(p.cod)
                   : "./proposituras.html?q=" + encodeURIComponent(p.numero || ""),
        h: norm([p.subtipo, p.numero, p.ementa, p.autor].join(" ")),
      })) },
    { id: "legis", rotulo: "Legislação", url: "./legis-index.json", grande: true,
      paginas: ["legis.html"],
      // norma sem número no índice virava "Decreto /2026" e abria o ano inteiro
      mapear: (d) => d.map((n) => ({
        t: n.numero ? (n.tipo || "Norma") + " " + n.numero + "/" + n.ano : (n.titulo || n.tipo || "Norma"),
        s: (n.ementa || n.titulo || "").slice(0, 110),
        url: "./legis.html?id=" + encodeURIComponent(n.id),
        h: norm([n.tipo, n.numero, n.ano, n.titulo, n.ementa, n.tags].join(" ")),
      })) },
    { id: "requerimentos", rotulo: "Requerimentos", url: "./requerimentos-index.json",
      mapear: (d) => d.map((i) => ({
        t: "Requerimento " + i.numero,
        s: (i.assunto || "").slice(0, 110),
        url: "./requerimentos.html?n=" + encodeURIComponent(i.numero || ""),
        h: norm([i.numero, i.assunto, i.ano].join(" ")),
      })) },
    { id: "favorecidos", rotulo: "Despesas · favorecidos", url: "./despesas-index.json", grande: true,
      paginas: ["despesas.html", "favorecido.html"],
      mapear: (d) => (d.top_favorecidos || []).map((f) => ({
        t: f.nome,
        s: compacto(f.valor) + " no mandato",
        // com dossiê pré-computado abre o raio-X; sem, cai na busca do painel
        url: f.slug ? "./favorecido.html?f=" + encodeURIComponent(f.slug)
                    : "./despesas.html?q=" + encodeURIComponent(f.nome) + "#favorecidos",
        // o documento entra na busca (formatado e só dígitos): antes o CNPJ não achava nada
        h: norm([f.nome, f.documento, digitos(f.documento)].join(" ")),
        dg: digitos(f.documento),
      })).concat([{
        t: "Detalhamento de despesas (execução por empenho)",
        s: "consulta com filtros, ficha do empenho e link citável",
        url: "./despesas.html#detalhe",
        h: norm("detalhamento despesas empenho liquidacao pagamento consulta lancamentos documentos"),
      }]) },
    // CPF/CNPJ de TODOS os favorecidos (o ranking acima só tem os 300 maiores) —
    // ~0,7 MB, por isso só entra quando a busca tem MIN_DIGITOS dígitos ou mais.
    { id: "documentos", rotulo: "Despesas · por CPF/CNPJ", url: "./despesas/dados/nomes-favorecidos.json",
      grande: true, porDocumento: true,
      mapear: (d) => Object.values(d).map(([nome, doc]) => ({
        t: nome,
        s: doc || "sem documento",
        url: "./favorecido.html?doc=" + encodeURIComponent(doc || "") + "&nome=" + encodeURIComponent(nome),
        h: norm([nome, doc, digitos(doc)].join(" ")),
        dg: digitos(doc),
      })) },
    { id: "endividamento", rotulo: "Endividamento", url: "./endividamento-index.json",
      mapear: (d) => (d.semaforo || []).map((m) => ({
        t: m.nome,
        s: (m.pct != null ? m.pct.toLocaleString("pt-BR") + "% da RCL · " : "") +
           (m.cor === "verde" ? "dentro do limite" : m.cor === "amarelo" ? "zona de alerta" : "acima do limite"),
        url: "./endividamento.html#semaforo",
        h: norm([m.nome, "divida endividamento lrf semaforo fiscal rcl limite", m.base_legal].join(" ")),
      })).concat([{
        t: "Dívida consolidada de Santos",
        s: d.totais && d.totais.divida ? compacto(d.totais.divida) + " · " + (d.ultimo ? d.ultimo.rotulo : "") : "evolução e limites da LRF",
        url: "./endividamento.html",
        h: norm("divida consolidada endividamento precatorios rcl santos"),
      }]) },
    { id: "precos", rotulo: "Preço comparado", url: "./precos-index.json",
      // preço unitário de material de consumo vive nos centavos: compacto
      // arredondaria R$ 0,0737 para "R$ 0" e a comparação sumiria da paleta
      mapear: (d) => (d.comparacoes || []).map((c) => ({
        t: c.titulo,
        s: "Santos R$ " + Number(c.santos.preco).toLocaleString("pt-BR", {
             minimumFractionDigits: c.santos.preco < 1 ? 4 : 2,
             maximumFractionDigits: c.santos.preco < 1 ? 4 : 2 }) + "/" + c.unidade +
           (c.razao ? " · " + c.razao.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) +
                      "× a mediana de " + c.pares.n_cidades + " cidades"
                    : " · " + c.pares.n + " referência(s)"),
        url: "./precos.html?c=" + encodeURIComponent(c.slug),
        h: norm([c.titulo, c.unidade, "preco unitario comparacao pncp licitacao pregao",
                 c.santos.objeto].join(" ")),
      })) },
    { id: "indicadores", rotulo: "Custo por Resultado", url: "./indicadores-index.json",
      mapear: (d) => Object.entries(d.temas || {}).flatMap(([slug, t]) =>
        (t.indicadores || []).map((i) => ({
          t: i.nome,
          s: (t.nome + " — Santos vs comparáveis · " + (i.fonte || "")).slice(0, 110),
          url: "./indicadores.html?tema=" + slug,
          h: norm([i.nome, t.nome, "indicador custo resultado gasto"].join(" ")),
        })).concat([{
          t: "Gasto por habitante em " + t.nome.toLowerCase(),
          s: "série anual vs cidades de porte similar",
          url: "./indicadores.html?tema=" + slug,
          h: norm("gasto per capita habitante " + t.nome),
        }])) },
  ];
  const MIN_GRANDES = 3;      // nº de caracteres da busca que libera as fontes grandes
  const MIN_DIGITOS = 8;      // nº de dígitos que libera a busca por CPF/CNPJ
  const cacheFontes = {};     // id -> array de itens (ou "erro")
  const pedidas = new Set();  // ids cujo fetch já saiu (carregando ou prontas)
  let paletaFundo = null, paletaInput = null, paletaRes = null, paletaStatus = null;
  let planos = [];            // resultados achatados p/ navegação por teclado
  let sel = 0;

  const paginaDaBase = (f) => (f.paginas || []).includes(
    paginaAtual || location.pathname.split("/").pop() || "index.html");
  const liberaGrandes = (q) => norm(q).trim().length >= MIN_GRANDES;
  // a fonte entra na busca agora? (grande só com busca longa ou na própria página;
  // a de documentos, só com cara de CPF/CNPJ)
  // busca que é só um CPF/CNPJ não precisa baixar proposituras (5 MB) nem legislação
  const ehDocumento = (q) => digitos(q).length >= MIN_DIGITOS && /^[\d.\/\-\s]+$/.test(q.trim());
  const fonteAtiva = (f, q) => (f.porDocumento ? digitos(q).length >= MIN_DIGITOS
    : !f.grande || paginaDaBase(f) || (liberaGrandes(q) && (!ehDocumento(q) || f.id === "favorecidos")));

  function carregarFontes(q) {
    for (const f of FONTES) {
      if (pedidas.has(f.id) || !fonteAtiva(f, q)) continue;
      pedidas.add(f.id);
      fetch(f.url, { cache: "no-cache" })
        .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then((d) => { cacheFontes[f.id] = f.mapear(d); })
        .catch((e) => { cacheFontes[f.id] = "erro"; console.warn("paleta:", f.id, e.message); })
        .finally(() => { if (paletaFundo && !paletaFundo.hidden) renderPaleta(); });
    }
  }

  // "art 79" / "artigo 23-a" / "79" → busca direta por número de artigo
  function alvoArtigo(q) {
    const m = q.trim().match(/^(?:art(?:igo)?\.?\s*)?(\d+(?:-[a-z])?)$/i);
    return m ? m[1].toLowerCase() : null;
  }

  function buscarPaleta(q) {
    const nq = norm(q).trim();
    if (!nq) return [];
    const termos = nq.split(/\s+/);
    const art = alvoArtigo(q);
    const grupos = [];
    const vistos = new Set();  // documentos já listados no ranking (não repetir no grupo por CPF/CNPJ)
    for (const f of FONTES) {
      if (!fonteAtiva(f, q)) continue;
      const itens = cacheFontes[f.id];
      if (itens === "erro") continue;
      if (!itens) { grupos.push({ f, carregando: true, hits: [] }); continue; }
      let hits;
      if (art && f.id === "regimento") {
        hits = itens.filter((i) => i.numArt === art);
        if (!hits.length) hits = itens.filter((i) => termos.every((t) => i.h.includes(t)));
      } else {
        hits = itens.filter((i) => termos.every((t) => i.h.includes(t)));
      }
      if (f.porDocumento) hits = hits.filter((i) => !i.dg || !vistos.has(i.dg));
      for (const i of hits) if (i.dg) vistos.add(i.dg);
      if (hits.length) grupos.push({ f, hits: hits.slice(0, 5) });
    }
    if (art) grupos.sort((a, b) => (b.f.id === "regimento") - (a.f.id === "regimento"));
    // CNPJ completo digitado: o raio-X abre direto, mesmo fora do índice (a página
    // resolve a identidade e diz se não houver pagamento)
    const dq = digitos(q);
    if (dq.length === 14 && /^[\d.\/\-\s]+$/.test(q.trim())) {
      grupos.unshift({ f: { id: "raiox", rotulo: "Raio-X" }, hits: [{
        t: "Abrir o raio-X do CNPJ " + dq.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5"),
        s: "pagamentos da Prefeitura a este CNPJ, alertas e consultas externas",
        url: "./favorecido.html?doc=" + dq,
      }] });
    }
    return grupos;
  }

  function renderPaleta() {
    const q = paletaInput.value;
    const grupos = buscarPaleta(q);
    planos = [];
    // aviso honesto quando alguma base falhou (antes era omitida em silêncio)
    const falhas = FONTES.filter((f) => cacheFontes[f.id] === "erro").map((f) => f.rotulo);
    let avisoFalhas = falhas.length
      ? `<div class="paleta-vazio paleta-falhas" role="presentation">⚠ Fora do ar agora: ${escapar(falhas.join(", "))}.</div>`
      : "";
    // anúncio p/ leitor de tela (role=status): carga das bases e nº de resultados
    const pendentes = FONTES.filter((f) => pedidas.has(f.id) && !cacheFontes[f.id]).map((f) => f.rotulo);
    paletaRes.setAttribute("aria-busy", String(pendentes.length > 0));
    const status = !norm(q).trim() ? ""
      : pendentes.length ? "Carregando " + pendentes.join(", ") + "…"
      : grupos.reduce((n, g) => n + g.hits.length, 0) + " resultado(s).";
    if (paletaStatus.textContent !== status) paletaStatus.textContent = status;
    const adiadas = FONTES.filter((f) => !f.porDocumento && !fonteAtiva(f, q)).map((f) => f.rotulo);
    if (norm(q).trim() && adiadas.length) {
      avisoFalhas += `<div class="paleta-vazio" role="presentation">Digite ${MIN_GRANDES} letras ou mais ` +
        `para buscar também em ${escapar(adiadas.join(", "))}.</div>`;
    }
    if (!norm(q).trim()) {
      paletaRes.innerHTML = '<div class="paleta-vazio" role="presentation">Digite para buscar em Despesas, ' +
        "Proposituras, Legislação, Requerimentos, Regimento, Endividamento, Indicadores e Preço comparado.<br>" +
        'Dica: <b>art 79</b> abre o artigo direto; um <b>CNPJ</b> abre o raio-X do favorecido.</div>' + avisoFalhas;
      atualizarAtivo();
      return;
    }
    if (!grupos.length) {
      paletaRes.innerHTML = '<div class="paleta-vazio" role="presentation">Nada encontrado nas bases do site.</div>' + avisoFalhas;
      atualizarAtivo();
      return;
    }
    let html = "";
    for (const g of grupos) {
      // listbox só aceita option/group como filhos: o título vira presentation e as
      // opções da fonte ficam num group nomeado (antes o ARIA era inválido)
      html += `<div role="group" aria-label="${escapar(g.f.rotulo)}">` +
        `<div class="paleta-grupo" role="presentation">${escapar(g.f.rotulo)}` +
        (g.carregando ? ' <span class="paleta-carregando">carregando…</span>' : "") + "</div>";
      for (const h of g.hits) {
        const i = planos.length;
        planos.push(h);
        html += `<a class="paleta-item${i === sel ? " sel" : ""}" id="paleta-op-${i}" href="${escapar(h.url)}" ` +
          `data-i="${i}" role="option" aria-selected="${i === sel}">` +
          `<span class="pi-t">${escapar(h.t)}</span>` +
          (h.s ? `<span class="pi-s">${escapar(h.s)}</span>` : "") + "</a>";
      }
      html += "</div>";
    }
    paletaRes.innerHTML = html + avisoFalhas;
    atualizarAtivo();
  }

  // combobox: aponta o leitor de tela para a opção ativa sem mover o foco
  function atualizarAtivo() {
    if (!paletaInput) return;
    if (planos.length) paletaInput.setAttribute("aria-activedescendant", "paleta-op-" + sel);
    else paletaInput.removeAttribute("aria-activedescendant");
  }

  function montarPaleta() {
    if (paletaFundo) return;
    paletaFundo = document.createElement("div");
    paletaFundo.className = "paleta-fundo";
    paletaFundo.hidden = true;
    paletaFundo.innerHTML =
      '<div class="paleta" role="dialog" aria-modal="true" aria-label="Busca em todas as bases">' +
      '<input class="paleta-q" type="search" autocomplete="off" spellcheck="false" ' +
      'role="combobox" aria-expanded="true" aria-haspopup="listbox" ' +
      'aria-controls="paleta-listbox" aria-autocomplete="list" ' +
      'placeholder="Buscar em tudo: favorecido, lei, projeto, art. 79…" />' +
      '<div class="paleta-res" id="paleta-listbox" role="listbox" aria-label="Resultados"></div>' +
      '<div class="paleta-status sr-only" role="status" aria-live="polite"></div>' +
      '<div class="paleta-dicas"><span>↑↓ navegar</span><span>↵ abrir</span><span>esc fechar</span></div>' +
      "</div>";
    document.body.appendChild(paletaFundo);
    paletaInput = paletaFundo.querySelector(".paleta-q");
    paletaRes = paletaFundo.querySelector(".paleta-res");
    paletaStatus = paletaFundo.querySelector(".paleta-status");

    paletaInput.addEventListener("input", () => {
      sel = 0;
      carregarFontes(paletaInput.value);  // libera as fontes grandes ao chegar a MIN_GRANDES
      renderPaleta();
    });
    paletaFundo.addEventListener("mousedown", (e) => {
      if (e.target === paletaFundo) fecharPaleta();
    });
    paletaRes.addEventListener("mousemove", (e) => {
      const a = e.target.closest(".paleta-item");
      if (a && +a.dataset.i !== sel) { sel = +a.dataset.i; marcarSel(); }
    });
    paletaInput.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, planos.length - 1); marcarSel(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); marcarSel(); }
      else if (e.key === "Enter" && planos[sel]) { e.preventDefault(); location.href = planos[sel].url; }
      else if (e.key === "Escape") { e.preventDefault(); fecharPaleta(); }
      // paleta de comandos: o foco fica preso no input (setas navegam, Tab não escapa
      // do diálogo — sem isso o Tab vazava p/ a página atrás do modal).
      else if (e.key === "Tab") { e.preventDefault(); }
    });
  }

  function marcarSel() {
    paletaRes.querySelectorAll(".paleta-item").forEach((a) => {
      const ativo = +a.dataset.i === sel;
      a.classList.toggle("sel", ativo);
      a.setAttribute("aria-selected", String(ativo));
      if (ativo) a.scrollIntoView({ block: "nearest" });
    });
    atualizarAtivo();
  }

  let focoAnterior = null;  // p/ devolver o foco a quem abriu a paleta

  function abrirPaleta() {
    montarPaleta();
    carregarFontes("");
    focoAnterior = document.activeElement;
    paletaFundo.hidden = false;
    document.body.style.overflow = "hidden";
    sel = 0;
    paletaInput.value = "";
    renderPaleta();
    paletaInput.focus();
  }

  function fecharPaleta() {
    if (!paletaFundo) return;
    paletaFundo.hidden = true;
    document.body.style.overflow = "";
    // restaura o foco ao elemento que abriu (a11y de teclado/leitor de tela)
    if (focoAnterior && typeof focoAnterior.focus === "function") focoAnterior.focus();
    focoAnterior = null;
  }

  // Atalhos globais: Ctrl+K / ⌘K sempre; "/" onde não conflita com atalho local
  document.addEventListener("keydown", (e) => {
    const digitando = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      (paletaFundo && !paletaFundo.hidden) ? fecharPaleta() : abrirPaleta();
    } else if (e.key === "/" && !digitando && paginaAtual !== "regimento.html") {
      // no Regimento, "/" foca a busca local (atalho de plenário) — não interceptar
      e.preventDefault();
      abrirPaleta();
    }
  });

  // ── PWA: service worker (offline com a última versão vista) ─────────────────
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", (ev) => {
      if (ev.data && ev.data.tipo === "dados-novos") avisarDadosNovos();
    });
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js")
        .catch(() => { /* contexto sem suporte: o site segue normal, só sem offline */ });
    });
  }

  return { topbar, lerParams, gravarParams, exportarCsv, escapar, destacarNumeros, norm, compacto, compactoEixo, brl, debounce, paginador, abrirPaleta,
           alternarTema, temaAtual, chartAcessivel, toast, copiar, compartilhar, estadoErro, quandoFonte, FACES_MANCHETE, identidadeFavorecido,
           nomeNormalizado, visorPdf, POP_SANTOS };
})();
