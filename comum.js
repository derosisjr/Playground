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
    ["explorador.html", null, "Explorador de pagamentos", "Bases de dados"],
    ["endividamento.html", "Semáforo Fiscal", "Semáforo Fiscal", "Bases de dados"],
    ["precos.html", "Preços", "Preço comparado", "Bases de dados"],
    ["proposituras.html", "Proposituras", "Base de Proposituras", "Bases de dados"],
    ["legis.html", "Legislação", "Base de Legislação", "Bases de dados"],
    ["requerimentos.html", "Requerimentos", "Requerimentos & Respostas", "Bases de dados"],
    // fora da faixa do desktop (sem folga): menu do celular, cartão do hub e a alternância
    // "Requerimentos | Indicações" no topo das duas páginas
    ["indicacoes.html", null, "Indicações & Respostas", "Bases de dados"],
    ["regimento.html", "Regimento", "Regimento Interno", "Bases de dados"],
    ["lei-organica.html", null, "Lei Orgânica", "Bases de dados"],
    ["indicadores.html", "Indicadores", "Custo por Resultado", "Leituras e participação"],
    ["retrospectiva.html", null, "O ano em gastos", "Leituras e participação"],
    ["consulta.html", "Escuta Pública", "Escuta pública", "Leituras e participação"],
    ["novidades.html", null, "Novidades das bases", "Acompanhamento"],
  ];
  let paginaAtual = null;
  // estado do modo apresentação (Comum.apresentar, mais abaixo) — aqui em cima porque
  // toast() e os atalhos globais consultam AP.aberto
  const AP = { dlg: null, quadro: null, palco: null, barra: null, slides: [], i: 0, passo: 0,
    aberto: false, montando: false, origem: null, temaAntes: null, buffer: "", tBuffer: 0, tBarra: 0,
    toque: null, impressao: null, gerando: 0 };

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
    aplicarTema(temaAtual() === "escuro" ? "claro" : "escuro", true);
  }
  // `persistir` = false: a apresentação troca o tema só enquanto está aberta, sem mexer
  // na preferência salva de quem lê o painel
  function aplicarTema(novo, persistir) {
    if (persistir) try { localStorage.setItem("tema", novo); } catch (e) { /* modo privado */ }
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
    }
    // com a apresentação aberta o aviso vai dentro dela (a página fica atrás do modal
    // e, em tela cheia, só o quadro da apresentação aparece)
    const pai = AP.aberto ? AP.quadro : document.body;
    if (toastEl.parentNode !== pai) pai.appendChild(toastEl);
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

  // ── Gráficos: Apache ECharts 6.1.0 sob demanda (M4, 2026-10) ────────────────
  // Uma camada só para os gráficos do site, no lugar do Chart.js:
  //  • a biblioteca (~370 KB gzip) só é baixada quando o 1º gráfico vai aparecer —
  //    promessa única, com SRI —, e cada gráfico só é desenhado quando chega perto
  //    da tela: avaliar o ECharts custa 5–10× o Chart.js na thread principal; longe
  //    da tela não trava a carga (medido no M0: bloqueio a 1× de 88 ms → 0);
  //  • tema claro/escuro registrados a partir dos tokens (nenhuma cor nova) e locale
  //    pt-BR próprio (o do pacote tem erros de português). Número sempre pelos
  //    formatadores da casa (compacto, brl…): o padrão do ECharts escreve "1,000";
  //  • a tabela oculta para leitor de tela (chartAcessivel) entra na hora, sem
  //    esperar a biblioteca; repinta no "temamudou" e ao cruzar 640 px (legenda
  //    embaixo no celular); se o CDN falhar, aviso com "Tentar de novo" no lugar.
  // Uso: Comum.grafico(idOuElemento, {
  //   opcao(p, largura, ctx) → option do ECharts (p = Comum.paleta(): cores do tema + `celular`;
  //     ctx = {altura, apresentacao}: altura do quadro e se é o slide de Comum.apresentar),
  //   acessivel: {descricao, cabecalhos, linhas} (ou função que os devolve),
  //   altura?(largura) → px, eventos?(chart), dependeDaLargura?, renderer? ("canvas" | "svg") })
  // Chamar de novo com o mesmo alvo atualiza o gráfico (dado novo, filtro).
  const ECHARTS_URL = "https://cdnjs.cloudflare.com/ajax/libs/echarts/6.1.0/echarts.min.js";
  const ECHARTS_SRI = "sha512-Uyq/AgtqFM4vT+unIGTDr4wMJDTUK9O5w2PXMQeBCSR8koqHpVz+qBmcQ+9Oeo5H+EmvT4pp/5QrsqhIbyjHTQ==";
  const FONTE_SANS = 'Manrope, "Segoe UI", system-ui, sans-serif';
  const FONTE_MONO = '"IBM Plex Mono", ui-monospace, Consolas, monospace';
  const FACES_GRAFICO = ["400 12px Manrope", "600 12px Manrope", '500 11px "IBM Plex Mono"'];
  // Cores por tema. Claro: linha dourada fina em --gold-texto (#8a6d1f, 4,8:1 sobre o
  // cartão; o #c9a84c dá 2,3:1 e fica para áreas e barras). Escuro: o navy vira #9fb6d9.
  // Status (verde/âmbar/vermelho) = o ramp semântico do Semáforo, nos dois temas.
  const PALETAS = {
    claro: {
      card: "#fffdf8", tinta: "#0c1626", muted: "#5d6675", linha: "#e2dccd", grade: "rgba(7,17,31,.08)",
      serie: "#07111f", serieFill: "rgba(10,22,40,.08)", ouro: "#c9a84c", ouroLinha: "#8a6d1f",
      ouroClaro: "#e3c977", verde: "#067647", amarelo: "#b54708", vermelho: "#b42318",
      ref: "#93a0b3", ambar: "rgba(201,168,76,.26)", ouroFill: "rgba(201,168,76,.12)",
      rampa: ["#e8dab4", "#d8c07e", "#c9a84c", "#aa8a36", "#8a6d1f"], neutro: "#eceae4",
      sombra: "0 10px 30px -12px rgba(7,17,31,.35)",
    },
    escuro: {
      card: "#101f36", tinta: "#e8ecf3", muted: "#93a0b3", linha: "#22375c", grade: "rgba(147,160,179,.16)",
      serie: "#9fb6d9", serieFill: "rgba(159,182,217,.10)", ouro: "#c9a84c", ouroLinha: "#c9a84c",
      ouroClaro: "#e3c977", verde: "#4ade80", amarelo: "#fbbf24", vermelho: "#f87171",
      ref: "#5d6675", ambar: "rgba(201,168,76,.24)", ouroFill: "rgba(201,168,76,.13)",
      rampa: ["#4f4e3d", "#786c42", "#a08a47", "#c9a84c", "#e3c977"], neutro: "#1a2940",
      sombra: "0 12px 34px -10px rgba(0,0,0,.6)",
    },
  };
  const CELULAR_GRAF = matchMedia("(max-width: 640px)");
  const MOVIMENTO_REDUZIDO = matchMedia("(prefers-reduced-motion: reduce)");
  const paleta = () => ({ ...PALETAS[temaAtual() === "escuro" ? "escuro" : "claro"],
    celular: CELULAR_GRAF.matches, sans: FONTE_SANS, mono: FONTE_MONO });

  function temaEcharts(p) {
    const eixoCat = {
      axisLine: { show: true, lineStyle: { color: p.linha } }, axisTick: { show: false },
      axisLabel: { color: p.muted, fontFamily: FONTE_SANS, fontSize: 11.5 }, splitLine: { show: false },
      nameTextStyle: { color: p.muted, fontFamily: FONTE_SANS, fontSize: 11.5 },
    };
    const eixoVal = {
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: p.muted, fontFamily: FONTE_MONO, fontSize: 11 },
      splitLine: { show: true, lineStyle: { color: p.grade, width: 1, type: "solid" } },
      nameTextStyle: { color: p.muted, fontFamily: FONTE_SANS, fontSize: 11.5 },
    };
    return {
      color: [p.serie, p.ouroLinha, p.ref, p.vermelho, p.amarelo, p.verde],
      backgroundColor: "transparent",
      textStyle: { fontFamily: FONTE_SANS, color: p.tinta },
      legend: { textStyle: { color: p.tinta, fontFamily: FONTE_SANS, fontSize: 12 }, inactiveColor: p.linha,
        pageTextStyle: { color: p.muted }, pageIconColor: p.tinta, pageIconInactiveColor: p.linha },
      tooltip: {
        backgroundColor: p.card, borderColor: p.linha, borderWidth: 1, padding: [9, 12],
        textStyle: { color: p.tinta, fontFamily: FONTE_SANS, fontSize: 12.5 },
        extraCssText: `border-radius:10px;box-shadow:${p.sombra};`,
        axisPointer: { lineStyle: { color: p.muted, width: 1 }, crossStyle: { color: p.muted },
          shadowStyle: { color: p.ouroFill } },
      },
      categoryAxis: eixoCat, valueAxis: eixoVal, logAxis: eixoVal,
      dataZoom: {
        borderColor: p.linha, backgroundColor: "transparent", fillerColor: p.ouroFill,
        handleStyle: { color: p.card, borderColor: p.ouroLinha, borderWidth: 1.5 },
        textStyle: { color: p.muted, fontFamily: FONTE_MONO, fontSize: 10.5 },
      },
      markLine: { label: { color: p.tinta } },
    };
  }

  // locale pt-BR (o do pacote tem "entitulado", "As primeiros"…)
  const LOCALE_PT = {
    time: { month: ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
      "outubro", "novembro", "dezembro"],
    monthAbbr: ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
    dayOfWeek: ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"],
    dayOfWeekAbbr: ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"] },
    legend: { selector: { all: "Todos", inverse: "Inverter" } },
    toolbox: { restore: { title: "Restaurar" }, saveAsImage: { title: "Salvar imagem", lang: ["Clique com o botão direito para salvar"] },
      dataZoom: { title: { zoom: "Zoom", back: "Desfazer zoom" } } },
    aria: {
      general: { withTitle: "Gráfico sobre “{title}”", withoutTitle: "Gráfico" },
      series: { single: { prefix: "", withName: " do tipo {seriesType} chamado {seriesName}.", withoutName: " do tipo {seriesType}." },
        multiple: { prefix: ". Tem {seriesCount} séries.", withName: " A série {seriesId} é {seriesType} e representa {seriesName}.",
          withoutName: " A série {seriesId} é {seriesType}.", separator: { middle: "", end: "" } } },
      data: { allData: "Os dados são: ", partialData: "Os primeiros {displayCnt} itens são: ",
        withName: "{name}: {value}", withoutName: "{value}", separator: { middle: ", ", end: ". " } },
    },
  };

  let promessaEcharts = null;
  function carregarEcharts() {
    if (!promessaEcharts) {
      promessaEcharts = new Promise((ok, falha) => {
        if (window.echarts) { ok(window.echarts); return; }
        const s = document.createElement("script");
        s.src = ECHARTS_URL;
        s.integrity = ECHARTS_SRI;
        s.crossOrigin = "anonymous";
        s.referrerPolicy = "no-referrer";
        s.onload = () => (window.echarts ? ok(window.echarts) : falha(new Error("ECharts sem global")));
        s.onerror = () => { s.remove(); falha(new Error("ECharts indisponível")); };
        document.head.appendChild(s);
      }).then((ec) => {
        ec.registerLocale("PT-BR", LOCALE_PT);
        ec.registerTheme("gabinete-claro", temaEcharts(PALETAS.claro));
        ec.registerTheme("gabinete-escuro", temaEcharts(PALETAS.escuro));
        return ec;
      }).catch((e) => { promessaEcharts = null; throw e; });  // permite "Tentar de novo"
    }
    return promessaEcharts;
  }

  const GRAFICOS = new Map();   // elemento → {el, def, chart, tema, larg, celular, visivel}
  let observadorGraf = null;
  function grafico(alvo, def) {
    const el = typeof alvo === "string" ? document.getElementById(alvo) : alvo;
    if (!el) return null;
    let reg = GRAFICOS.get(el);
    if (!reg) {
      reg = { el, def, chart: null, larg: 0 };
      GRAFICOS.set(el, reg);
      el.classList.add("grafico");
      new ResizeObserver(() => redimensionarGrafico(reg)).observe(el);
      if (!observadorGraf) observadorGraf = new IntersectionObserver(aoAparecer, { rootMargin: "300px 0px" });
      observadorGraf.observe(el);
    } else reg.def = def;
    const a = typeof def.acessivel === "function" ? def.acessivel() : def.acessivel;
    if (a) chartAcessivel(el, a.descricao, a.cabecalhos, a.linhas);
    if (reg.chart) montarGrafico(reg);
    else if (reg.visivel) desenharGrafico(reg);
    return reg;
  }
  function aoAparecer(entradas) {
    for (const e of entradas) {
      if (!e.isIntersecting) continue;
      observadorGraf.unobserve(e.target);
      const reg = GRAFICOS.get(e.target);
      if (reg) { reg.visivel = true; desenharGrafico(reg); }
    }
  }
  function desenharGrafico(reg) {
    carregarEcharts()
      .then(() => quandoFonte(FACES_GRAFICO, () => montarGrafico(reg)))
      .catch(() => estadoErro(reg.el, "Não foi possível carregar o gráfico agora (biblioteca fora do ar). " +
        "Os números continuam no texto e nas tabelas da página.", () => desenharGrafico(reg)));
  }
  function montarGrafico(reg) {
    const ec = window.echarts;
    if (!ec) return;
    const tema = temaAtual() === "escuro" ? "gabinete-escuro" : "gabinete-claro";
    const erro = reg.el.querySelector(":scope > .estado-erro");
    if (erro) erro.remove();
    if (reg.chart && reg.tema !== tema) { reg.chart.dispose(); reg.chart = null; }
    const larg = Math.round(reg.el.getBoundingClientRect().width);
    if (reg.def.altura) reg.el.style.height = reg.def.altura(larg) + "px";
    if (!reg.chart) {
      reg.chart = ec.init(reg.el, tema, { locale: "PT-BR", renderer: reg.def.renderer || "canvas" });
      reg.tema = tema;
      if (reg.def.eventos) reg.def.eventos(reg.chart);
    } else reg.chart.resize();
    reg.larg = larg;
    reg.celular = CELULAR_GRAF.matches;
    const op = reg.def.opcao(paleta(), larg, { altura: reg.el.clientHeight, apresentacao: false });
    if (MOVIMENTO_REDUZIDO.matches) op.animation = false;
    reg.chart.setOption(op, { notMerge: true });
  }
  function redimensionarGrafico(reg) {
    if (!reg.chart) return;
    const larg = Math.round(reg.el.getBoundingClientRect().width);
    if (!larg || larg === reg.larg) return;
    if (reg.def.dependeDaLargura || CELULAR_GRAF.matches !== reg.celular) montarGrafico(reg);
    else { reg.larg = larg; reg.chart.resize(); }
  }
  const repintarGraficos = () => { for (const reg of GRAFICOS.values()) if (reg.chart) montarGrafico(reg); };
  window.addEventListener("temamudou", repintarGraficos);
  CELULAR_GRAF.addEventListener("change", repintarGraficos);
  // impressão: desenha também os que ainda não apareceram na tela (se a biblioteca já veio)
  window.addEventListener("beforeprint", () => {
    if (!window.echarts) return;
    for (const reg of GRAFICOS.values()) if (!reg.chart && reg.el.offsetParent) montarGrafico(reg);
  });

  // Tooltip padrão dos gráficos (HTML; todo texto escapado — rótulos vêm de crawler).
  // linhas: [cor, rótulo, valor, forma ("p" = bolinha)]; a cor só na chave, o valor em destaque.
  function dicaGrafico(titulo, linhas, nota, alerta) {
    return `<div class="ec-dica"><div class="ec-dica-t">${escapar(titulo)}</div>` +
      linhas.filter(Boolean).map(([cor, rot, val, forma]) =>
        `<div class="ec-dica-l"><span class="r">${cor ? `<span class="k${forma === "p" ? " p" : ""}" style="background:${escapar(cor)}"></span>` : ""}` +
        `${escapar(rot)}</span><b>${escapar(val)}</b></div>`).join("") +
      (nota ? `<div class="ec-dica-n${alerta ? " ec-dica-alerta" : ""}">${escapar(nota)}</div>` : "") + "</div>";
  }

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
    else if (b.dataset.acao === "apresentar") apresentar({ origem: b });
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

  function aoCarregar() { preencherBases(); recolherHero(); abrirApresentacaoPeloLink(); }
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
    // Lei Orgânica (~0,5 MB): "lom 58" / "lei orgânica 58" abrem o artigo; "art 58" lista
    // as duas leis, o Regimento primeiro. As Disposições Transitórias (numeração própria,
    // recomeça no 1) entram pela busca de texto, não pelo número.
    { id: "lom", rotulo: "Lei Orgânica", url: "./lei-organica-index.json", grande: true,
      paginas: ["lei-organica.html"],
      mapear: (d) => d.map((a) => ({
        t: (a.adt ? "Disposições Transitórias, art. " : "Art. ") + a.numero,
        s: ((a.blocos && a.blocos[0] && a.blocos[0].texto) || "").slice(0, 110),
        url: "./lei-organica.html#" + a.id,
        h: norm("lom lei organica art artigo " + a.numero + " " + (a.texto_busca || "")),
        numArt: a.adt ? null : String(a.numero).toLowerCase(),
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
    // ~0,2 MB, como requerimentos: entra na 1ª abertura. O bairro entra na busca
    // ("poda gonzaga"); o link mostra só a indicação, com "Ver a lista inteira"
    { id: "indicacoes", rotulo: "Indicações", url: "./indicacoes-index.json",
      mapear: (d) => d.map((i) => ({
        t: "Indicação " + i.numero,
        s: (i.assunto || "").slice(0, 110),
        url: "./indicacoes.html?n=" + encodeURIComponent(i.numero || ""),
        h: norm([i.numero, i.assunto, i.ano, i.bairro, i.regiao].join(" ")),
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
      }, {
        t: "Explorador de pagamentos (tabela dinâmica e SQL)",
        s: "cruze função, favorecido, mês e unidade gestora no navegador",
        url: "./explorador.html",
        h: norm("explorador pagamentos tabela dinamica pivo cruzar sql consulta funcao favorecido mes unidade"),
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

  // "art 79" / "artigo 23-a" / "79" → nº de artigo no Regimento e na Lei Orgânica;
  // "lom 58" / "lei orgânica 58" / "lom, art. 58" → só na Lei Orgânica
  function alvoArtigo(q) {
    const m = norm(q).trim().match(/^(lom|lei organica)?[\s,]*(?:art(?:igo)?\.?\s*)?(\d+(?:-[a-z])?)$/);
    return m ? { num: m[2], lom: !!m[1] } : null;
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
      if (art && art.lom && f.id === "regimento") continue;  // "lom 58": só a Lei Orgânica
      const itens = cacheFontes[f.id];
      if (itens === "erro") continue;
      if (!itens) { grupos.push({ f, carregando: true, hits: [] }); continue; }
      let hits;
      if (art && (f.id === "regimento" || f.id === "lom")) {
        hits = itens.filter((i) => i.numArt === art.num);
        if (!hits.length) hits = itens.filter((i) => termos.every((t) => i.h.includes(t)));
      } else {
        hits = itens.filter((i) => termos.every((t) => i.h.includes(t)));
      }
      if (f.porDocumento) hits = hits.filter((i) => !i.dg || !vistos.has(i.dg));
      for (const i of hits) if (i.dg) vistos.add(i.dg);
      if (hits.length) grupos.push({ f, hits: hits.slice(0, 5) });
    }
    // nº de artigo: as leis primeiro — o Regimento antes da Lei Orgânica ("lom 58": o contrário)
    if (art) {
      const ordem = art.lom ? ["lom", "regimento"] : ["regimento", "lom"];
      const peso = (g) => { const k = ordem.indexOf(g.f.id); return k < 0 ? ordem.length : k; };
      grupos.sort((a, b) => peso(a) - peso(b));
    }
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
        "Proposituras, Legislação, Requerimentos, Indicações, Regimento, Lei Orgânica, Endividamento, Indicadores e Preço comparado.<br>" +
        'Dica: <b>art 79</b> abre o artigo do Regimento e <b>lom 58</b>, o da Lei Orgânica; um <b>CNPJ</b> ' +
        'abre o raio-X do favorecido.</div>' + avisoFalhas;
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
    if (AP.aberto) return;   // a apresentação (modal) tem os seus atalhos
    const digitando = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      (paletaFundo && !paletaFundo.hidden) ? fecharPaleta() : abrirPaleta();
    } else if (e.key === "/" && !digitando && !["regimento.html", "lei-organica.html"].includes(paginaAtual)) {
      // no Regimento e na Lei Orgânica, "/" foca a busca local (atalho de plenário) — não interceptar
      e.preventDefault();
      abrirPaleta();
    }
  });

  // ── Modo apresentação (Comum.apresentar — M10, out/2026) ────────────────────
  // O painel vira slides para projetar em sessão, comissão ou reunião de bairro
  // (passador de slides, teclado ou toque) e para salvar em PDF. Nada é inventado: os
  // slides saem dos elementos marcados com data-slide (contrato no site-frontend.md) —
  // capa automática, número-manchete, "Em resumo" frase a frase, cartões, gráficos
  // REDESENHADOS grandes com a mesma `opcao` do registro GRAFICOS (não são capturas) e
  // listas curtas —, no recorte (filtros) em que a página está. Tamanhos em --u (1% da
  // altura do slide 16:9): o mesmo desenho a 1920×1080, a 1366×768 e no PDF (1280×720);
  // no celular em pé o slide ocupa a tela e empilha. Abre no "Noturno" (tema escuro)
  // sem mexer na preferência salva; "Fundo claro" serve a sala muito iluminada.
  const AP_TEMA = "apresentacao:tema";        // tema da apresentação (à parte do tema do site)
  const AP_PAPEL = { larg: 1280, alt: 720 };  // página do PDF, 16:9
  const AP_EMPILHADO = matchMedia("screen and (orientation: portrait) and (max-width: 820px), screen and (orientation: landscape) and (max-height: 500px)");
  // "art. 58", "2º quad. 2026", "Res. Senado": o ponto não fecha a frase
  const ABREVIACOES = /(?:^|[\s(])(?:arts?|inc|quad|res|n|nº|sra?|dra?|av|p|pág|fls|cap|ex|vs|aprox|[a-z])\.$/i;

  const criar = (tag, cls, texto) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (texto != null) e.textContent = texto;
    return e;
  };
  const maiuscula = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
  const semPontaInicial = (s) => (s || "").replace(/^[·\s—–-]+/, "");
  const naPagina = (el) => !!el && !el.closest("[hidden]");

  // Texto visível de um nó: some com o que `ignorar` pegar (selos, contadores, botões) e
  // separa com " · " o que a página mostra em linhas (prazo · vencimento, p. ex.)
  function textoLimpo(el, ignorar) {
    if (!el) return "";
    let s = "";
    const andar = (n) => {
      for (const f of n.childNodes) {
        if (f.nodeType === 3) { s += f.nodeValue; continue; }
        if (f.nodeType !== 1 || f.matches("script, style, template, .sr-only, .skel, [aria-hidden='true']")
            || (ignorar && f.matches(ignorar))) continue;
        if (f.tagName === "BR") { s += " "; continue; }
        const d = getComputedStyle(f).display;
        const sep = d === "inline" || d === "contents" ? "" : " ¶ ";   // selo, bloco, linha própria
        s += sep;
        andar(f);
        s += sep;
      }
    };
    andar(el);
    return s.replace(/\s+/g, " ").replace(/^[\s¶]+|[\s¶]+$/g, "").replace(/\s*(¶\s*)+/g, " · ").trim();
  }

  function frasesDe(texto) {
    const out = [];
    let ini = 0;
    const re = /[.!?…]+["”’»]?(?=\s+["“«(]?[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ0-9])/g;
    for (let m; (m = re.exec(texto));) {
      if (ABREVIACOES.test(texto.slice(Math.max(ini, m.index - 7), m.index + 1))) continue;
      const fim = m.index + m[0].length;
      out.push(texto.slice(ini, fim).trim());
      ini = fim;
    }
    out.push(texto.slice(ini).trim());
    return out.filter(Boolean);
  }
  // "2" ou "1,2" (1 = a primeira frase); sem escolha válida, a 1ª frase com número
  // (a que costuma trazer a conclusão) ou a 1ª — se `padrao`
  function escolherFrases(frases, escolha, padrao = true) {
    const idx = String(escolha || "").split(",").map((x) => parseInt(x, 10) - 1)
      .filter((k) => k >= 0 && k < frases.length);
    if (idx.length) return idx.map((k) => frases[k]);
    if (!padrao || !frases.length) return [];
    return [frases.find((f) => /\d/.test(f)) || frases[0]];
  }

  // Valor que um filtro mostra agora ("" = sem filtro): select fora da 1ª opção, busca
  // preenchida, item ligado (aria-pressed/selected/current) ou o texto de um aviso
  // (foco num item). `sempre` = mostra mesmo na 1ª opção (tema, indicador escolhido).
  function valorDoFiltro(el, sempre) {
    if (!el) return "";
    if (el.matches("select")) {
      const op = el.selectedOptions[0];
      return op && (sempre || el.selectedIndex > 0) ? op.textContent.trim() : "";
    }
    if (el.matches("input, textarea")) { const v = el.value.trim(); return v ? `“${v}”` : ""; }
    const ligado = el.querySelector('[aria-pressed="true"], [aria-selected="true"], [aria-current]:not([aria-current="false"])');
    if (ligado) return textoLimpo(ligado, ".n");
    if (el.querySelector("[aria-pressed], [aria-selected], [aria-current]")) return "";
    return semPontaInicial(textoLimpo(el, "button"));
  }

  function enderecoCurto() {
    const p = new URLSearchParams(location.search);
    p.delete("apresentar");
    p.delete("slide");
    let qs = p.toString();
    try { qs = decodeURIComponent(qs.replace(/\+/g, " ")); } catch (e) { /* fica codificado */ }
    return (location.host + location.pathname).replace(/^www\./, "").replace(/\/index\.html$/, "/") + (qs ? "?" + qs : "");
  }

  // Dados da página para a capa e o rodapé: etiqueta e título do topo, recorte (filtros
  // marcados com data-slide-filtro), linhas de identificação (data-slide-capa), fonte e
  // data da base (data-slide-fonte e data-slide-base no botão "Apresentar")
  function infoApresentacao() {
    const botao = document.querySelector('[data-acao="apresentar"]');
    const titulo = textoLimpo(document.querySelector("header.hero h1") || document.querySelector("h1")) || document.title;
    const filtros = [...document.querySelectorAll("[data-slide-filtro]")];
    return {
      titulo,
      olho: textoLimpo(document.querySelector("header.hero .eyebrow")),
      base: maiuscula(textoLimpo(document.querySelector((botao && botao.dataset.slideBase) || ".base-de"))),
      fonte: (botao && botao.dataset.slideFonte) || "",
      url: enderecoCurto(),
      site: (document.querySelector('meta[property="og:site_name"]') || {}).content || "",
      capa: [...document.querySelectorAll("[data-slide-capa]")].filter(naPagina)
        .map((e) => semPontaInicial(textoLimpo(e))).filter(Boolean),
      temFiltros: filtros.length > 0,
      recorte: filtros.filter(naPagina).map((e) => valorDoFiltro(e, e.dataset.slideFiltro === "sempre")).filter(Boolean),
    };
  }

  // elementos marcados, na ordem: data-slide="N" primeiro (por N), depois a do documento
  function marcadosParaSlides() {
    return [...document.querySelectorAll("[data-slide]")]
      .filter((el) => naPagina(el) && !el.closest(".ap, .ap-impressao"))
      .map((el, k) => ({ el, k, n: parseFloat(el.dataset.slide) }))
      .sort((a, b) => ((isNaN(a.n) ? Infinity : a.n) - (isNaN(b.n) ? Infinity : b.n)) || a.k - b.k)
      .map((x) => x.el);
  }
  function tiposDe(el) {
    const t = (el.dataset.slideTipo || "").trim();
    if (t) return t.split(/\s+/);
    if (el.matches(".hero-num")) return ["manchete"];
    if (el.matches(".stats")) return ["kpis"];
    if (GRAFICOS.has(el) || el.matches(".grafico")) return ["grafico"];
    if (el.matches("table, ul, ol") || el.querySelector("table")) return ["lista"];
    if (el.matches(".resumo-box, p") || el.querySelector(".resumo-texto")) return ["texto"];
    return ["bloco"];
  }
  // título: data-slide-titulo ("{#id}" vira o valor daquele controle) ou o cabeçalho da caixa
  function tituloDe(el, padrao) {
    const t = el.dataset.slideTitulo;
    if (t) return t.replace(/\{([^}]+)\}/g, (_, sel) => valorDoFiltro(document.querySelector(sel), true)).trim();
    const caixa = el.closest(".box, .cartao, .caixa, details, section");
    const h = caixa && caixa.querySelector("h2, h3, summary");
    return (textoLimpo(h, ".sub, .pos-chip, .contagem") || padrao).replace(/^[⚠\s]+/, "");
  }
  // texto de apoio (nota): data-slide-nota-de="<seletor>", procurado na caixa do elemento
  function textoDeApoio(el, sel) {
    if (!sel) return "";
    const raiz = sel.startsWith("#") ? document : (el.closest(".box, .cartao, .caixa, section, details") || document);
    const alvo = raiz.querySelector(sel);
    return naPagina(alvo) ? textoLimpo(alvo) : "";
  }
  // só texto e negrito: o slide não herda botões nem estilos da página
  function fragmentoTexto(el) {
    const f = document.createDocumentFragment();
    if (!el) return f;
    for (const n of el.childNodes) {
      if (n.nodeType === 3) f.append(n.nodeValue);
      else if (n.nodeType === 1 && !n.matches(".skel, .sr-only, [aria-hidden='true']"))
        f.append(/^(B|STRONG)$/.test(n.tagName) ? criar("b", "", n.textContent) : textoLimpo(n));
    }
    return f;
  }
  // valor de um cartão: o número e a variação (▲/▼, com a cor da página)
  function fragmentoValor(el) {
    const f = document.createDocumentFragment();
    if (!el) return f;
    for (const n of el.childNodes) {
      if (n.nodeType === 3) f.append(n.nodeValue);
      else if (n.nodeType === 1 && n.matches(".delta")) f.append(criar("span", n.className, n.textContent.trim()));
      else if (n.nodeType === 1 && !n.matches(".skel, .sr-only")) f.append(n.textContent);
    }
    return f;
  }
  // Cópia só para ver: sem ids (não duplicar), sem foco nem papéis de controle; links e
  // botões viram texto — a ação continua na página
  const PAPEIS_OK = /^(img|group|list|listitem|table|row|cell|columnheader|rowheader|note|presentation|none|figure|term|definition)$/;
  function clonarLimpo(el) {
    const c = el.cloneNode(true);
    for (const n of [c, ...c.querySelectorAll("*")]) {
      for (const a of [...n.attributes]) {
        if (/^(id|for|name|tabindex|contenteditable|draggable|data-slide.*|data-acao|on.*|aria-(live|controls|describedby|labelledby|expanded|pressed|selected|current|busy|haspopup|activedescendant|sort))$/.test(a.name))
          n.removeAttribute(a.name);
      }
      const r = n.getAttribute("role");
      if (r && !PAPEIS_OK.test(r)) n.removeAttribute("role");
    }
    c.querySelectorAll(".skel, table.sr-only, script, template, input, select, textarea").forEach((n) => n.remove());
    c.querySelectorAll("a, button, summary, label").forEach((n) => {
      const sp = criar("span", n.matches("a") ? "" : n.className);
      sp.append(...n.childNodes);
      n.replaceWith(sp);
    });
    c.querySelectorAll("details").forEach((d) => d.setAttribute("open", ""));
    return c;
  }
  // células de um item de lista que não é tabela: os nós com texto (rótulo, valor…) ou,
  // com data-slide-celulas, um seletor por célula, na ordem pedida
  function celulasDe(it, seletores, ignorar) {
    if (seletores) return seletores.split(",").map((sel) => semPontaInicial(textoLimpo(it.querySelector(sel.trim()), ignorar)));
    const out = [];
    for (const n of it.childNodes) {
      let t = "";
      if (n.nodeType === 3) t = n.nodeValue.replace(/\s+/g, " ").trim();
      else if (n.nodeType === 1 && n.tagName !== "BR" && !(ignorar && n.matches(ignorar))
               && !n.matches(".sr-only, .skel, [aria-hidden='true']")) t = textoLimpo(n, ignorar);
      if (t) out.push(semPontaInicial(t));
    }
    return out;
  }
  // coluna numérica (à direita, em Plex Mono): todas as células com cara de número
  // ("R$ 4,2 mi", "37 dias", "12%", "9,04") — "—" e vazio não decidem
  const NUMERICO = /^[−+–-]?\s*(R\$\s*)?\d[\d.,]*\s*(mi|bi|mil|%|dias?|d|×)?$/;
  function tabelaDe(cab, linhas, legenda) {
    const t = criar("table", "ap-tabela");
    if (legenda) t.append(criar("caption", "sr-only", legenda));
    const ncol = Math.max(cab.length, ...linhas.map((l) => l.length));
    const numerica = Array.from({ length: ncol }, (_, k) => {
      const vals = linhas.map((l) => (l[k] || "").trim()).filter((v) => v && v !== "—");
      return k > 0 && vals.length > 0 && vals.every((v) => NUMERICO.test(v));
    });
    if (cab.some(Boolean)) {
      const tr = criar("tr");
      for (let k = 0; k < ncol; k++) {
        const th = criar("th", numerica[k] ? "ap-num" : "", cab[k] || "");
        th.scope = "col";
        tr.append(th);
      }
      const thead = criar("thead");
      thead.append(tr);
      t.append(thead);
    }
    const tb = criar("tbody");
    for (const l of linhas) {
      const tr = criar("tr");
      for (let k = 0; k < ncol; k++) {
        const v = l[k] || "";
        const td = criar("td", numerica[k] ? "ap-num" : "");
        td.append(criar("span", "ap-celula", v));
        tr.append(td);
      }
      tb.append(tr);
    }
    t.append(tb);
    return t;
  }

  // ── construtores de slide ──
  function novoSlide(tipo, titulo, { noturno = false, olho = "" } = {}) {
    const sec = criar("section", `ap-slide ap-${tipo}${noturno ? " ap-noturno" : ""}`);
    sec.setAttribute("role", "group");
    sec.setAttribute("aria-roledescription", "slide");
    if (olho) sec.append(criar("p", "ap-olho", olho));
    const corpo = criar("div", "ap-corpo");
    sec.append(corpo);
    return { tipo, titulo, sec, corpo, passos: 0 };
  }
  const tituloH2 = (texto, cls = "ap-titulo") => criar("h2", cls, texto);

  function slideCapa(info) {
    const s = novoSlide("capa", info.titulo, { noturno: true, olho: info.olho });
    if (info.titulo.length > 28) s.sec.classList.add("ap-longo");
    s.corpo.append(tituloH2(info.titulo, "ap-capa-titulo"), criar("div", "ap-capa-fio"));
    for (const linha of info.capa) s.corpo.append(criar("p", "ap-capa-linha", linha));
    if (info.temFiltros) {
      const p = criar("p", "ap-recorte");
      p.append(criar("span", "ap-recorte-rot", "Recorte"),
        info.recorte.length ? info.recorte.join(" · ") : "a base inteira, sem filtros");
      s.corpo.append(p);
    }
    if (info.site) s.corpo.append(criar("p", "ap-capa-site", info.site));
    return s;
  }

  // número-manchete (.hero-num) ou o 1º cartão de um .stats ("manchete kpis")
  function slideManchete(el, info) {
    let grande, contexto;
    const stat = el.matches(".hero-num") ? null : el.querySelector(".stat");
    if (stat) {
      if (stat.querySelector(".skel")) return null;
      grande = textoLimpo(stat.querySelector(".valor"), ".delta");
      const rot = textoLimpo(stat.querySelector(".rotulo"));
      contexto = document.createTextNode([rot.charAt(0).toLowerCase() + rot.slice(1),
        textoLimpo(stat.querySelector(".sub"))].filter(Boolean).join(" · "));
    } else {
      const g = el.querySelector(".grande");
      if (!g || g.querySelector(".skel")) return null;
      grande = textoLimpo(g);
      contexto = fragmentoTexto(el.querySelector(".contexto"));
    }
    if (!grande) return null;
    const frase = contexto.textContent.trim();
    const s = novoSlide("manchete", `${grande} ${frase}`.trim(), { noturno: true, olho: info.titulo });
    const c = criar("p", "ap-contexto");
    c.append(contexto);
    s.corpo.append(criar("p", "ap-grande", grande), c);
    return s;
  }

  // texto corrido ("Em resumo", a regra da Lei Orgânica): uma frase por passo do passador
  function slideTexto(el, info) {
    const fonte = el.querySelector("[data-slide-texto], .resumo-texto") || (el.matches("p") ? el : el.querySelector("p")) || el;
    if (fonte.querySelector(".skel") || fonte.classList.contains("resumo-reserva")) return null;
    let frases = frasesDe(textoLimpo(fonte, el.dataset.slideIgnorar));
    const escolha = escolherFrases(frases, el.dataset.slideFrase, false);
    if (escolha.length) frases = escolha;
    if (!frases.length) return null;
    frases[0] = maiuscula(frases[0]);
    const titulo = tituloDe(el, "Em resumo");
    const s = novoSlide("texto", titulo, { noturno: true, olho: info.titulo });
    const lista = criar("ul", "ap-frases");
    frases.forEach((f, k) => {
      const li = criar("li", "ap-frase");
      li.innerHTML = destacarNumeros(f);
      li.dataset.passo = k;
      lista.append(li);
    });
    s.corpo.append(tituloH2(titulo), lista);
    s.passos = frases.length - 1;
    s.frases = frases;
    return s;
  }

  function slideKpis(el, info, { semPrimeiro } = {}) {
    let cards = [...el.querySelectorAll(".stat")].filter((c) => !c.querySelector(".skel"));
    if (semPrimeiro) cards = cards.slice(1);   // o 1º já foi a manchete
    if (!cards.length) return null;
    const titulo = tituloDe(el, "Em números");
    const s = novoSlide("kpis", titulo, { olho: info.titulo });
    const grade = criar("div", "ap-grade");
    grade.style.setProperty("--ap-cols", cards.length === 4 ? 2 : Math.min(cards.length, 3));
    for (const c of cards) {
      const k = criar("div", "ap-kpi");
      const v = criar("div", "ap-kpi-valor");
      v.append(fragmentoValor(c.querySelector(".valor")));
      k.append(criar("div", "ap-kpi-rotulo", textoLimpo(c.querySelector(".rotulo"))), v);
      // "→ ver" é o convite do link da página; no slide não há para onde ir
      const sub = textoLimpo(c.querySelector(".sub")).replace(/\s*→\s*ver$/i, "");
      if (sub) k.append(criar("div", "ap-kpi-sub", sub));
      grade.append(k);
    }
    s.corpo.append(tituloH2(titulo), grade);
    return s;
  }

  // gráfico do registro, redesenhado grande (desenharNoSlide) com a frase-síntese tirada
  // da descrição acessível (data-slide-frase escolhe qual)
  function slideGrafico(el, info) {
    const reg = GRAFICOS.get(el);
    if (!reg) return null;
    const a = (typeof reg.def.acessivel === "function" ? reg.def.acessivel() : reg.def.acessivel) || {};
    const frases = frasesDe(a.descricao || "");
    const titulo = tituloDe(el, "Gráfico");
    const lateral = el.dataset.slideLayout ? el.dataset.slideLayout === "lateral" : !!reg.def.altura;
    const s = novoSlide("grafico", titulo, { olho: info.titulo });
    if (lateral) s.sec.classList.add("ap-lateral");
    const texto = criar("div", "ap-texto");
    texto.append(tituloH2(titulo));
    const sintese = escolherFrases(frases, el.dataset.slideFrase).join(" ");
    if (sintese) {
      const p = criar("p", "ap-sintese");
      p.innerHTML = destacarNumeros(sintese);
      texto.append(p);
    }
    const cartao = criar("div", "ap-cartao");
    const caixa = criar("div", "ap-caixa-grafico");
    const moldura = criar("div", "ap-moldura");
    const alvo = criar("div", "ap-alvo");
    alvo.id = "ap-grafico-" + (++AP.gerando);
    moldura.append(alvo);
    caixa.append(moldura);
    cartao.append(caixa);
    const leg = el.dataset.slideLegenda && document.querySelector(el.dataset.slideLegenda);
    if (naPagina(leg) && leg.textContent.trim()) {
      const l = criar("div", "ap-legenda");
      l.append(clonarLimpo(leg));
      cartao.append(l);
    }
    const nota = el.dataset.slideNota || escolherFrases(frases, el.dataset.slideNotaFrase, false).join(" ")
      || textoDeApoio(el, el.dataset.slideNotaDe);
    s.corpo.append(texto, cartao);
    if (nota) (lateral ? texto : s.corpo).append(criar("p", "ap-nota", nota));
    if (a.descricao) chartAcessivel(alvo, a.descricao, a.cabecalhos || [], a.linhas || []);
    s.grafico = { el, alvo, moldura, caixa, cartao, acessivel: a, inst: null, chave: "" };
    return s;
  }

  // lista curta (os N primeiros, na ordem da página): tabela ou itens (data-slide-itens)
  function slideLista(el, info) {
    const max = parseInt(el.dataset.slideMax, 10) || 6;
    const ign = el.dataset.slideIgnorar;
    const tabela = el.matches("table") ? el : el.querySelector("table");
    let cab = [], linhas;
    if (tabela && !el.dataset.slideItens) {
      cab = [...tabela.querySelectorAll("thead th")].map((th) => textoLimpo(th, ign));
      linhas = [...tabela.querySelectorAll("tbody > tr")].map((tr) => [...tr.children].map((c) => textoLimpo(c, ign)));
      const cols = (el.dataset.slideColunas || "").split(",").map((x) => parseInt(x, 10) - 1).filter((k) => k >= 0);
      if (cols.length) {
        cab = cols.map((k) => cab[k] || "");
        linhas = linhas.map((l) => cols.map((k) => l[k] || ""));
      }
    } else {
      linhas = [...el.querySelectorAll(el.dataset.slideItens || ":scope > *")]
        .map((it) => celulasDe(it, el.dataset.slideCelulas, ign));
    }
    linhas = linhas.filter((l) => l.some(Boolean));
    if (!linhas.length) return null;
    const titulo = tituloDe(el, "Lista");
    const s = novoSlide("lista", titulo, { olho: info.titulo });
    s.corpo.append(tituloH2(titulo), tabelaDe(cab, linhas.slice(0, max), titulo));
    const notas = [];
    if (linhas.length > max) notas.push(`e mais ${linhas.length - max} na página`);
    if (el.dataset.slideNota) notas.push(el.dataset.slideNota);
    if (notas.length) s.corpo.append(criar("p", "ap-nota", notas.join(" · ")));
    return s;
  }

  // bloco da página copiado e ampliado (o semáforo, p. ex.): o CSS da página vale aqui
  function slideBloco(el, info) {
    if (el.querySelector(".skel") || !el.textContent.trim()) return null;
    const titulo = tituloDe(el, "");
    const s = novoSlide("bloco", titulo || info.titulo, { olho: info.titulo });
    const w = criar("div", "ap-clone");
    w.dataset.zoom = el.dataset.slideZoom || "1";
    w.append(clonarLimpo(el));
    if (titulo) s.corpo.append(tituloH2(titulo));
    s.corpo.append(w);
    return s;
  }

  function rodapeSlide(info, fonte, n, total) {
    const f = criar("footer", "ap-rodape");
    f.append(criar("span", "ap-rodape-fonte", [fonte && "Fonte: " + fonte, info.base].filter(Boolean).join(" · ")),
      criar("span", "ap-url", info.url), criar("span", "ap-n", `${n}/${total}`));
    return f;
  }

  const CONSTRUTORES = { manchete: slideManchete, texto: slideTexto, kpis: slideKpis, grafico: slideGrafico,
    lista: slideLista, bloco: slideBloco };
  function montarDeck(paraImpressao) {
    const info = infoApresentacao();
    const slides = [slideCapa(info)];
    for (const el of marcadosParaSlides()) {
      const tipos = tiposDe(el);
      for (const tipo of tipos) {
        try {
          const s = CONSTRUTORES[tipo] && CONSTRUTORES[tipo](el, info,
            { semPrimeiro: tipo === "kpis" && tipos.includes("manchete") });
          if (s) { s.fonte = el.dataset.slideFonte || info.fonte; slides.push(s); }
        } catch (e) { console.warn("apresentação: slide pulado —", e); }
      }
    }
    slides.forEach((s, k) => {
      s.sec.append(rodapeSlide(info, s.fonte ?? info.fonte, k + 1, slides.length));
      s.sec.setAttribute("aria-label", `${k + 1} de ${slides.length}: ${s.titulo}`);
      s.sec.hidden = !paraImpressao;
    });
    return slides;
  }

  // ── ajuste ao tamanho: número numa linha só, texto que não cabe encolhe, gráfico ──
  function unidadeAp(impressao) {
    if (impressao) return AP_PAPEL.alt / 100;
    const r = AP.palco.getBoundingClientRect();
    return Math.min(r.height / 100, (r.width * 0.5625) / 100);
  }
  function encaixarLinha(el) {
    el.style.fontSize = "";
    const w = el.clientWidth, sw = el.scrollWidth;
    if (w && sw > w + 1) el.style.fontSize = (parseFloat(getComputedStyle(el).fontSize) * w / sw * 0.98).toFixed(1) + "px";
  }
  function encaixarAltura(sec) {
    let k = 1;
    sec.style.removeProperty("--ap-k");
    while (k > 0.64 && sec.scrollHeight > sec.clientHeight + 1) {
      k = +(k - 0.06).toFixed(2);
      sec.style.setProperty("--ap-k", k);
    }
  }
  function ajustarSlide(s, impressao = false) {
    if (!s || !s.sec.isConnected) return;
    const empilhado = AP_EMPILHADO.matches && !impressao;
    const u = unidadeAp(impressao);
    s.sec.querySelectorAll(".ap-clone").forEach((c) => {
      c.style.zoom = empilhado ? "" : String(((u / 5.6) * (parseFloat(c.dataset.zoom) || 1)).toFixed(3));
    });
    // legenda HTML da página (~12 px) a ~1,75% da altura do slide
    s.sec.querySelectorAll(".ap-legenda").forEach((l) => { l.style.zoom = empilhado ? "1.1" : ((u * 1.75) / 12).toFixed(3); });
    s.sec.querySelectorAll(".ap-grande, .ap-kpi-valor").forEach(encaixarLinha);
    if (!empilhado) encaixarAltura(s.sec);
    if (s.grafico) desenharNoSlide(s, impressao);
    if (!impressao) marcarRolagem(s);
  }
  // no celular, o slide que passa da tela rola: ganha foco pelo teclado (as setas ↑/↓
  // rolam; PageUp/PageDown, do passador, continuam trocando de slide)
  function marcarRolagem(s) {
    if (AP_EMPILHADO.matches && s.sec.scrollHeight > s.sec.clientHeight + 1) s.sec.tabIndex = 0;
    else s.sec.removeAttribute("tabindex");
  }

  // Altura em que o gráfico foi pensado: a definição (altura) ou a do quadro na página.
  // O desenho no slide usa ESSA altura, ampliada por escala — o `opcao` que mede o próprio
  // quadro (mapa do gasto, rosca, mapa dos bairros) continua coerente.
  function alturaNatural(reg, larg) {
    if (reg.def.altura) return reg.def.altura(larg);
    if (reg.el.clientHeight) return reg.el.clientHeight;
    const css = getComputedStyle(reg.el).getPropertyValue("--altura-grafico").trim();
    return /px$/.test(css) ? parseFloat(css) : 300;
  }
  function desenharNoSlide(s, impressao) {
    const g = s.grafico;
    const reg = GRAFICOS.get(g.el);
    if (!reg || g.reserva) return;
    if (!window.echarts) {
      if (impressao) { tabelaNoLugar(s, true); return; }
      carregarEcharts()
        .then(() => quandoFonte(FACES_GRAFICO, () => { if (s.sec.isConnected && !s.sec.hidden) desenharNoSlide(s); }))
        .catch(() => tabelaNoLugar(s));
      return;
    }
    const empilhado = AP_EMPILHADO.matches && !impressao;
    if (empilhado) g.caixa.style.height = alturaNatural(reg, g.caixa.clientWidth) + "px";
    else g.caixa.style.height = "";
    const r = g.caixa.getBoundingClientRect();
    if (r.width < 40 || r.height < 40) return;
    // escala: fontes do gráfico (~11,5 px na página) ≈ 2% da altura do slide, limitada pelo
    // que cabe na caixa; largura virtual de no mínimo 520 px (o desenho de desktop).
    // data-slide-altura="livre" (gráfico cujo `opcao` não mede o próprio quadro): a altura
    // virtual acompanha a caixa e a escala fica no alvo
    const livre = g.el.dataset.slideAltura === "livre" && !reg.def.altura && !empilhado;
    let esc = 1;
    if (!empilhado) {
      const alvoEsc = unidadeAp(impressao) / 5.6;
      esc = livre ? Math.min(alvoEsc, r.width / 520)
        : Math.max(0.6, Math.min(r.height / alturaNatural(reg, r.width / alvoEsc), r.width / 520, alvoEsc * 1.3));
    }
    const vw = Math.round(r.width / esc);
    const vh = Math.round(livre ? r.height / esc : alturaNatural(reg, vw));
    if (!empilhado) esc = Math.min(esc, r.height / vh);
    const tema = temaAtual() === "escuro" ? "gabinete-escuro" : "gabinete-claro";
    const chave = [vw, vh, esc.toFixed(3), tema, impressao].join("|");
    if (g.inst && g.chave === chave) return;
    g.chave = chave;
    Object.assign(g.moldura.style, { width: vw * esc + "px", height: vh * esc + "px",
      left: Math.max(0, (r.width - vw * esc) / 2) + "px", top: Math.max(0, (r.height - vh * esc) / 2) + "px" });
    Object.assign(g.alvo.style, { width: vw + "px", height: vh + "px", transform: esc === 1 ? "" : `scale(${esc})` });
    try {
      if (g.inst) g.inst.dispose();
      g.inst = window.echarts.init(g.alvo, tema, { renderer: "svg", locale: "PT-BR", width: vw, height: vh });
      const op = reg.def.opcao({ ...paleta(), celular: empilhado }, vw, { altura: vh, apresentacao: true });
      if (impressao || MOVIMENTO_REDUZIDO.matches) op.animation = false;
      g.inst.setOption(op, { notMerge: true });
      if (!impressao) marcarRolagem(s);   // a altura do gráfico pode ter feito o slide rolar
    } catch (e) {
      console.warn("apresentação: gráfico", e);
      tabelaNoLugar(s, impressao);
    }
  }
  // biblioteca fora do ar (ou dado inesperado): a tabela equivalente, à vista, no lugar
  function tabelaNoLugar(s, impressao) {
    const g = s.grafico, a = g.acessivel;
    if (g.reserva) return;
    g.reserva = true;
    if (g.inst) { g.inst.dispose(); g.inst = null; }
    g.caixa.replaceChildren(criar("p", "ap-aviso", "Gráfico indisponível agora (biblioteca fora do ar) — os números estão na tabela."));
    const area = criar("div", "ap-reserva");
    if (!impressao) {
      area.tabIndex = 0;
      area.setAttribute("role", "region");
      area.setAttribute("aria-label", "Tabela: " + s.titulo);
    }
    area.append(tabelaDe(a.cabecalhos || [], a.linhas || [], a.descricao || s.titulo));
    g.caixa.append(area);
    g.caixa.classList.add("ap-sem-grafico");
  }

  // ── a moldura: <dialog> modal com o palco, a barra e os atalhos ──
  const ICONES = {
    tela: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/></svg>',
    pdf: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
    tema: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/></svg>',
  };
  function montarDialogo() {
    if (AP.dlg) return;
    const d = criar("dialog", "ap");
    d.innerHTML =
      '<div class="ap-quadro">' +
      '<div class="ap-palco" tabindex="-1"></div>' +
      '<p class="ap-carregando" role="status">Preparando a apresentação…</p>' +
      '<div class="ap-irpara" hidden></div>' +
      '<div class="ap-ajuda" id="ap-ajuda" role="region" aria-labelledby="ap-ajuda-tit" hidden>' +
      '<h2 id="ap-ajuda-tit">Atalhos</h2><dl>' +
      "<div><dt>→ · PageDown · Espaço</dt><dd>avançar</dd></div>" +
      "<div><dt>← · PageUp</dt><dd>voltar</dd></div>" +
      "<div><dt>Home · End</dt><dd>primeiro · último slide</dd></div>" +
      "<div><dt>número + Enter</dt><dd>ir para o slide</dd></div>" +
      "<div><dt>F</dt><dd>tela cheia</dd></div>" +
      "<div><dt>?</dt><dd>estes atalhos</dd></div>" +
      "<div><dt>Esc</dt><dd>sair</dd></div></dl>" +
      "<p>No celular, deslize para os lados.</p></div>" +
      '<div class="ap-barra">' +
      '<button type="button" class="ap-ant" aria-label="Slide anterior">‹</button>' +
      '<span class="ap-prog"><span class="sr-only">Slide </span><span class="ap-prog-n">1</span>' +
      '<span aria-hidden="true"> / </span><span class="sr-only"> de </span><span class="ap-prog-t">1</span></span>' +
      '<button type="button" class="ap-prox" aria-label="Próximo slide">›</button>' +
      `<button type="button" class="ap-tema">${ICONES.tema}<span class="ap-rot"></span></button>` +
      `<button type="button" class="ap-tela" aria-label="Tela cheia (F)" aria-pressed="false">${ICONES.tela}<span class="ap-rot">Tela cheia</span></button>` +
      `<button type="button" class="ap-pdf" aria-label="Salvar PDF">${ICONES.pdf}<span class="ap-rot">Salvar PDF</span></button>` +
      '<button type="button" class="ap-ajuda-b" aria-expanded="false" aria-controls="ap-ajuda" aria-label="Atalhos do teclado (?)">?</button>' +
      '<button type="button" class="ap-fechar" aria-label="Sair da apresentação (Esc)">✕<span class="ap-rot">Sair</span></button>' +
      "</div>" +
      '<div class="ap-anuncio sr-only" aria-live="polite"></div></div>';
    document.body.append(d);
    const $ = (sel) => d.querySelector(sel);
    Object.assign(AP, { dlg: d, quadro: $(".ap-quadro"), palco: $(".ap-palco"), barra: $(".ap-barra"),
      carregando: $(".ap-carregando"), irParaEl: $(".ap-irpara"), ajuda: $(".ap-ajuda"), anuncio: $(".ap-anuncio"),
      progN: $(".ap-prog-n"), progT: $(".ap-prog-t"), btAnt: $(".ap-ant"), btProx: $(".ap-prox"), btTema: $(".ap-tema"),
      btTela: $(".ap-tela"), btAjuda: $(".ap-ajuda-b") });
    if (!document.fullscreenEnabled) AP.btTela.hidden = true;   // iPhone: sem tela cheia de página
    AP.btAnt.addEventListener("click", voltarAp);
    AP.btProx.addEventListener("click", avancarAp);
    AP.btTema.addEventListener("click", alternarTemaAp);
    AP.btTela.addEventListener("click", alternarTelaCheia);
    $(".ap-pdf").addEventListener("click", salvarPdf);
    AP.btAjuda.addEventListener("click", () => alternarAjuda());
    $(".ap-fechar").addEventListener("click", fecharApresentacao);
    d.addEventListener("keydown", teclaAp);
    d.addEventListener("cancel", (e) => { e.preventDefault(); fecharApresentacao(); });
    d.addEventListener("close", () => { if (AP.aberto) fecharApresentacao(); });
    d.addEventListener("pointermove", mostrarBarra);
    d.addEventListener("focusin", mostrarBarra);
    // deslizar (toque/caneta): para o lado avança ou volta; na vertical o slide rola
    AP.palco.addEventListener("pointerdown", (e) => {
      AP.toque = e.pointerType === "mouse" ? null : { x: e.clientX, y: e.clientY, t: performance.now() };
    });
    AP.palco.addEventListener("pointerup", (e) => {
      const t = AP.toque;
      AP.toque = null;
      if (!t) return;
      const dx = e.clientX - t.x, dy = e.clientY - t.y;
      if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy) && performance.now() - t.t < 900) (dx < 0 ? avancarAp : voltarAp)();
    });
    AP.palco.addEventListener("pointercancel", () => { AP.toque = null; });
  }

  // Espera a página terminar de desenhar: sem esqueleto à vista e o DOM quieto por um
  // instante (o índice, o mapa e os gráficos chegam em tempos diferentes). Teto de 8 s.
  function aguardarPagina(maxMs = 8000) {
    return new Promise((ok) => {
      const t0 = performance.now();
      let ultima = t0;
      const obs = new MutationObserver((ms) => {
        if (ms.some((m) => !(m.target.closest ? m.target : m.target.parentElement)?.closest(".ap, .toast-comum"))) ultima = performance.now();
      });
      obs.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["hidden"] });
      const esqueleto = () => [...document.querySelectorAll(".skel")].some((s) => !s.closest(".ap") && s.getClientRects().length);
      const passo = () => {
        const agora = performance.now();
        if (agora - t0 > maxMs || (document.readyState === "complete" && !esqueleto() && agora - ultima > 250)) {
          obs.disconnect();
          ok();
        } else setTimeout(passo, 100);
      };
      passo();
    });
  }

  // Abre a apresentação da página (botão data-acao="apresentar" ou ?apresentar=1&slide=N)
  async function apresentar(op = {}) {
    if (AP.aberto) return;
    montarDialogo();
    AP.aberto = true;
    AP.montando = true;
    AP.origem = op.origem || document.querySelector('[data-acao="apresentar"]');
    AP.temaAntes = temaAtual();
    let temaAp = "escuro";
    try { temaAp = localStorage.getItem(AP_TEMA) || "escuro"; } catch (e) { /* modo privado */ }
    if (temaAp !== AP.temaAntes) aplicarTema(temaAp, false);
    document.documentElement.classList.add("ap-ativo");
    AP.dlg.setAttribute("aria-label", "Apresentação: " +
      (textoLimpo(document.querySelector("header.hero h1") || document.querySelector("h1")) || document.title));
    AP.palco.replaceChildren();
    AP.carregando.hidden = false;
    AP.barra.classList.remove("ap-oculta");
    AP.dlg.showModal();
    AP.palco.focus();
    carregarEcharts().catch(() => { /* cada gráfico cai na tabela */ });
    await aguardarPagina();
    AP.montando = false;
    if (!AP.aberto) return;
    construirDeck(op.slide ? op.slide - 1 : 0, op.slide ? "fim" : 0);
    AP.carregando.hidden = true;
    anunciar(`Apresentação com ${AP.slides.length} slides. Setas ou passador avançam e voltam; Esc sai.`);
    if (matchMedia("(pointer: coarse)").matches) toast("Deslize para os lados para trocar de slide.");
  }
  function construirDeck(i, passo) {
    for (const s of AP.slides) if (s.grafico && s.grafico.inst) s.grafico.inst.dispose();
    AP.slides = montarDeck(false);
    AP.palco.replaceChildren(...AP.slides.map((s) => s.sec));
    AP.i = -1;
    irPara(i, passo, false);
  }
  function fecharApresentacao() {
    if (!AP.aberto) return;
    AP.aberto = false;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    for (const s of AP.slides) if (s.grafico && s.grafico.inst) s.grafico.inst.dispose();
    AP.slides = [];
    AP.palco.replaceChildren();
    alternarAjuda(false);
    limparBuffer();
    if (AP.dlg.open) AP.dlg.close();
    document.documentElement.classList.remove("ap-ativo");
    if (temaAtual() !== AP.temaAntes) aplicarTema(AP.temaAntes, false);
    gravarUrlApresentacao();
    const o = AP.origem;
    if (o && o.isConnected && typeof o.focus === "function") o.focus();
  }

  function irPara(i, passo = 0, anunciarTroca = true) {
    const n = AP.slides.length;
    if (!n) return;
    i = Math.max(0, Math.min(n - 1, i));
    const ant = AP.slides[AP.i], s = AP.slides[i];
    const troca = ant !== s;
    if (ant && troca) ant.sec.hidden = true;
    AP.passo = passo === "fim" ? s.passos : Math.max(0, Math.min(s.passos, passo));
    s.sec.hidden = false;
    s.sec.classList.remove("ap-entra", "ap-volta");
    if (troca && ant && !MOVIMENTO_REDUZIDO.matches) {
      void s.sec.offsetWidth;   // reinicia a animação
      s.sec.classList.add(i > AP.i ? "ap-entra" : "ap-volta");
    }
    AP.i = i;
    aplicarPassos(s);
    ajustarSlide(s);
    atualizarBarra();
    gravarUrlApresentacao();
    if (troca && anunciarTroca) anunciar(`Slide ${i + 1} de ${n}: ${s.titulo}`);
  }
  function aplicarPassos(s) {
    if (!s.passos) return;
    s.sec.querySelectorAll(".ap-frase").forEach((li) => {
      const k = +li.dataset.passo;
      li.classList.toggle("ap-visto", k < AP.passo);
      li.classList.toggle("ap-agora", k === AP.passo);
      li.classList.toggle("ap-futuro", k > AP.passo);
    });
  }
  function avancarAp() {
    const s = AP.slides[AP.i];
    if (!s) return;
    if (AP.passo < s.passos) {
      AP.passo++;
      aplicarPassos(s);
      atualizarBarra();
      anunciar(s.frases[AP.passo]);
    } else if (AP.i < AP.slides.length - 1) irPara(AP.i + 1, 0);
  }
  function voltarAp() {
    const s = AP.slides[AP.i];
    if (!s) return;
    if (AP.passo > 0) {
      AP.passo--;
      aplicarPassos(s);
      atualizarBarra();
    } else if (AP.i > 0) irPara(AP.i - 1, "fim");
  }
  function atualizarBarra() {
    const n = AP.slides.length, s = AP.slides[AP.i];
    AP.progN.textContent = String(AP.i + 1);
    AP.progT.textContent = String(n);
    AP.btAnt.setAttribute("aria-disabled", String(AP.i <= 0 && AP.passo === 0));
    AP.btProx.setAttribute("aria-disabled", String(!s || (AP.i >= n - 1 && AP.passo >= s.passos)));
    const escuro = temaAtual() === "escuro";
    AP.btTema.setAttribute("aria-label", escuro ? "Fundo claro (sala iluminada)" : "Fundo escuro");
    AP.btTema.querySelector(".ap-rot").textContent = escuro ? "Fundo claro" : "Fundo escuro";
  }
  function gravarUrlApresentacao() {
    const p = new URLSearchParams(location.search);
    if (AP.aberto) { p.set("apresentar", "1"); p.set("slide", String(AP.i + 1)); }
    else { p.delete("apresentar"); p.delete("slide"); }
    const qs = p.toString();
    history.replaceState(history.state, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
  }
  function anunciar(msg) {
    if (!AP.anuncio) return;
    AP.anuncio.textContent = "";
    setTimeout(() => { AP.anuncio.textContent = msg; }, 30);   // repetir a mesma frase também é lido
  }

  function teclaAp(e) {
    if (!AP.aberto || e.altKey || e.ctrlKey || e.metaKey) return;   // Ctrl+P etc. seguem para o navegador
    const k = e.key;
    const emBotao = !!(e.target.closest && e.target.closest("button"));
    // ↑/↓ rolam o que rola (tabela de reserva, slide comprido no celular)
    const emTabela = !!(e.target.closest && e.target.closest(".ap-reserva, .ap-slide[tabindex='0']"));
    if (k === "Tab") { prenderFoco(e); return; }
    if (k === "Escape") {
      e.preventDefault();
      if (AP.buffer) limparBuffer();
      else if (!AP.ajuda.hidden) alternarAjuda(false);
      else fecharApresentacao();
      return;
    }
    if (!AP.slides.length) return;
    if (/^[0-9]$/.test(k)) { e.preventDefault(); digitar(k); return; }
    if (k === "Backspace" && AP.buffer) { e.preventDefault(); digitar(null); return; }
    if (k === "Enter" && AP.buffer) { e.preventDefault(); irParaBuffer(); return; }
    const avanca = k === "ArrowRight" || k === "PageDown" || (k === "ArrowDown" && !emTabela)
      || (k === " " && !e.shiftKey && !emBotao) || (k === "Enter" && !emBotao);
    const volta = k === "ArrowLeft" || k === "PageUp" || (k === "ArrowUp" && !emTabela) || (k === " " && e.shiftKey && !emBotao);
    if (avanca || volta) { e.preventDefault(); (avanca ? avancarAp : voltarAp)(); return; }
    if (k === "Home") { e.preventDefault(); irPara(0, 0); }
    else if (k === "End") { e.preventDefault(); irPara(AP.slides.length - 1, "fim"); }
    else if (k === "f" || k === "F") { e.preventDefault(); alternarTelaCheia(); }
    else if (k === "?") { e.preventDefault(); alternarAjuda(); }
  }
  // foco preso no diálogo: Tab circula entre os controles visíveis
  function prenderFoco(e) {
    const itens = [...AP.dlg.querySelectorAll("button, [tabindex='0']")]
      .filter((x) => !x.closest("[hidden]") && x.getClientRects().length);
    if (!itens.length) return;
    e.preventDefault();
    const k = itens.indexOf(document.activeElement);
    itens[e.shiftKey ? (k <= 0 ? itens.length - 1 : k - 1) : (k < 0 || k >= itens.length - 1 ? 0 : k + 1)].focus();
  }
  function digitar(d) {
    AP.buffer = d === null ? AP.buffer.slice(0, -1) : (AP.buffer + d).slice(-3);
    clearTimeout(AP.tBuffer);
    if (!AP.buffer) { limparBuffer(); return; }
    AP.irParaEl.hidden = false;
    AP.irParaEl.innerHTML = `Ir para o slide <b>${escapar(AP.buffer)}</b> · <kbd>Enter</kbd>`;
    AP.tBuffer = setTimeout(limparBuffer, 3000);
  }
  function limparBuffer() {
    AP.buffer = "";
    clearTimeout(AP.tBuffer);
    if (AP.irParaEl) AP.irParaEl.hidden = true;
  }
  function irParaBuffer() {
    const n = parseInt(AP.buffer, 10);
    limparBuffer();
    if (n >= 1) irPara(n - 1, 0);
  }
  function alternarAjuda(mostrar) {
    if (!AP.ajuda) return;
    const m = mostrar ?? AP.ajuda.hidden;
    AP.ajuda.hidden = !m;
    AP.btAjuda.setAttribute("aria-expanded", String(m));
  }
  // em tela cheia a barra some depois de 2,6 s parada (o rodapé do slide já diz "3/8")
  function mostrarBarra() {
    if (!AP.barra) return;
    AP.barra.classList.remove("ap-oculta");
    AP.quadro.classList.remove("ap-sem-cursor");
    clearTimeout(AP.tBarra);
    if (document.fullscreenElement !== AP.quadro) return;
    AP.tBarra = setTimeout(() => {
      if (AP.barra.contains(document.activeElement) && document.activeElement.matches(":focus-visible")) return;
      AP.barra.classList.add("ap-oculta");
      AP.quadro.classList.add("ap-sem-cursor");
    }, 2600);
  }
  function alternarTelaCheia() {
    if (document.fullscreenElement) { document.exitFullscreen().catch(() => {}); return; }
    const aviso = () => toast("Tela cheia indisponível neste navegador — use a tecla F11.");
    if (!AP.quadro.requestFullscreen) { aviso(); return; }
    try { AP.quadro.requestFullscreen({ navigationUI: "hide" }).catch(aviso); } catch (e) { aviso(); }
  }
  document.addEventListener("fullscreenchange", () => {
    if (!AP.btTela) return;
    const cheia = document.fullscreenElement === AP.quadro;
    AP.btTela.setAttribute("aria-pressed", String(cheia));
    AP.btTela.setAttribute("aria-label", cheia ? "Sair da tela cheia (F)" : "Tela cheia (F)");
    mostrarBarra();
  });
  function alternarTemaAp() {
    const novo = temaAtual() === "escuro" ? "claro" : "escuro";
    try { localStorage.setItem(AP_TEMA, novo); } catch (e) { /* modo privado */ }
    aplicarTema(novo, false);
  }
  // tema trocado: refaz os slides DEPOIS dos outros ouvintes (a página repinta as legendas
  // HTML que o slide copia) — mesmo slide e mesmo passo
  window.addEventListener("temamudou", () => {
    if (!AP.aberto || AP.montando) return;
    setTimeout(() => { if (AP.aberto && !AP.montando) construirDeck(AP.i, AP.passo); }, 60);
  });
  let tAjusteAp = 0;
  window.addEventListener("resize", () => {
    if (!AP.aberto) return;
    clearTimeout(tAjusteAp);
    tAjusteAp = setTimeout(() => ajustarSlide(AP.slides[AP.i]), 120);
  });

  // ── PDF: todos os slides, um por página 16:9, gráficos em SVG e as cores da tela ──
  // Uma cópia dos slides (.ap-impressao) é montada fora da tela, medida e desenhada
  // antes da impressão; o @page 16:9 só existe enquanto ela existe — o "Imprimir" da
  // página continua como era.
  function prepararImpressao() {
    desfazerImpressao();
    const caixa = criar("div", "ap-impressao");
    caixa.setAttribute("aria-hidden", "true");
    const slides = montarDeck(true);
    caixa.append(...slides.map((s) => s.sec));
    document.body.append(caixa);
    for (const s of slides) ajustarSlide(s, true);
    const estilo = criar("style");
    estilo.textContent = `@page { size: ${AP_PAPEL.larg}px ${AP_PAPEL.alt}px; margin: 0; }`;
    document.head.append(estilo);
    document.documentElement.classList.add("ap-imprimindo");
    AP.impressao = { caixa, slides, estilo };
  }
  function desfazerImpressao() {
    const im = AP.impressao;
    if (!im) return;
    for (const s of im.slides) if (s.grafico && s.grafico.inst) s.grafico.inst.dispose();
    im.caixa.remove();
    im.estilo.remove();
    document.documentElement.classList.remove("ap-imprimindo");
    AP.impressao = null;
  }
  async function salvarPdf() {
    toast("Preparando o PDF…");
    try { await carregarEcharts(); } catch (e) { /* sem biblioteca: as tabelas vão no lugar dos gráficos */ }
    await new Promise((ok) => quandoFonte(FACES_GRAFICO, ok));
    if (!AP.aberto) return;
    prepararImpressao();
    toast("Na janela de impressão, escolha “Salvar como PDF”.");
    window.print();
  }
  // Ctrl+P com a apresentação aberta também imprime os slides
  window.addEventListener("beforeprint", () => { if (AP.aberto && !AP.impressao) prepararImpressao(); });
  window.addEventListener("afterprint", desfazerImpressao);

  // link ?apresentar=1&slide=N (só em página que tem o botão)
  function abrirApresentacaoPeloLink() {
    const p = lerParams();
    if (p.get("apresentar") !== "1" || !document.querySelector('[data-acao="apresentar"]')) return;
    // depois de a camada comum terminar de carregar (aoCarregar pode rodar durante ela)
    setTimeout(() => apresentar({ slide: parseInt(p.get("slide"), 10) || 1 }), 0);
  }

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
           alternarTema, temaAtual, chartAcessivel, toast, copiar, compartilhar, estadoErro, quandoFonte, FACES_MANCHETE, grafico, paleta, dicaGrafico, carregarEcharts, identidadeFavorecido,
           nomeNormalizado, visorPdf, apresentar, POP_SANTOS };
})();
