// Explorador de pagamentos — tabela dinâmica e SQL de leitura sobre o cubo de pagamentos
// (despesas/dados/cubo/AAAA.json), num SQLite-WASM dentro de um Web Worker
// (explorador-worker.js). A página só monta o SQL, conversa com o worker e desenha o
// resultado (≤ 51 linhas); baixar, montar e consultar não ocupam a thread principal.
// Dados vindos da origem entram na página por textContent (nunca innerHTML).
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const WORKER_URL = "./explorador-worker.js?v=1";
  const LIMITE_SQL_MS = 10000;      // consulta digitada: passou disso, o worker é recriado
  const LIMITE_PIVO_MS = 30000;     // consultas da própria página (rede de segurança)
  const LIMITE_INICIO_MS = 45000;   // baixar e iniciar a biblioteca
  const COLUNAS_MAX = 8;            // colunas de dimensão não temporal (o resto vira "Demais")
  const BARRAS_MAX = 20;            // barras no gráfico (a tabela vai a 50 + demais)
  const SERIES_MAX = 6;             // séries empilhadas no gráfico de colunas (+ "Outros")
  const PAGINA_SQL = 200;           // linhas do resultado SQL por vez ("Mostrar mais")
  const T0 = performance.now();
  const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

  // Dimensões da tabela: coluna no SQLite, rótulo do vazio (null na origem) e a chave do
  // filtro no Detalhamento do Radar de Despesas (DET_URL de despesas-app.js; dfav = identidade)
  const DIMS = {
    funcao: { rotulo: "Função", col: "funcao", vazio: "(sem função)", det: "df", plural: "funções" },
    subfuncao: { rotulo: "Subfunção", col: "subfuncao", vazio: "(sem subfunção)", det: "dsf", plural: "subfunções" },
    programa: { rotulo: "Programa", col: "programa", vazio: "(sem programa)", det: "dpr", plural: "programas" },
    elemento: { rotulo: "Elemento de despesa", col: "elemento", vazio: "(sem elemento)", det: "del", plural: "elementos" },
    grupo: { rotulo: "Grupo de despesa", col: "grupo", vazio: "(sem grupo)", det: "dg", plural: "grupos" },
    fonte: { rotulo: "Fonte de recurso", col: "fonte", vazio: "(sem fonte)", det: "dfr", plural: "fontes" },
    unidade: { rotulo: "Unidade gestora", col: "unidade_gestora", vazio: "(sem unidade)", det: "du", plural: "unidades gestoras" },
    tipo: { rotulo: "Tipo", col: "tipo", vazio: "(sem tipo)", det: "dt", plural: "tipos" },
    favorecido: { rotulo: "Favorecido", col: "chave_favorecido", det: "dfav", plural: "favorecidos", fav: true },
    mes: { rotulo: "Mês", col: "periodo", temporal: true, plural: "meses" },
    ano: { rotulo: "Ano", col: "ano", temporal: true, numerico: true, plural: "anos" },
  };
  const ORDEM_DIMS = ["funcao", "subfuncao", "programa", "elemento", "grupo", "fonte", "unidade", "tipo",
                      "favorecido", "mes", "ano"];
  const DIMS_FILTRO = ORDEM_DIMS.filter((d) => d !== "ano");   // ano = botões de ano
  const MEDIDAS = { pago: "Pago (R$)", n: "Nº de pagamentos", pct: "% do total" };
  const TOPS = [10, 20, 50];
  const PADRAO = { linhas: "funcao", colunas: "", medida: "pago", top: 10 };

  const COLUNAS_SQL = [
    ["ano", "INTEGER", "Ano do pagamento"],
    ["mes", "INTEGER", "Mês do pagamento (1 a 12)"],
    ["periodo", "TEXT", "Ano e mês, 'AAAA-MM'"],
    ["unidade_gestora", "TEXT", "Entidade que pagou (Prefeitura, CAPEP, IPS, fundações)"],
    ["tipo", "TEXT", "Orçamentário, Restos a pagar, Extra-orçamentário ou Empenho não localizado na base"],
    ["chave_favorecido", "TEXT", "Identidade do favorecido: cnpj:… ou cpf:…|NOME (agrupe por ela)"],
    ["favorecido", "TEXT", "Nome do favorecido (grafia de exibição)"],
    ["documento", "TEXT", "CNPJ ou CPF mascarado, como a origem publica"],
    ["funcao", "TEXT", "Função (NULL no extra-orçamentário)"],
    ["subfuncao", "TEXT", "Subfunção"],
    ["programa", "TEXT", "Programa do PPA"],
    ["elemento", "TEXT", "Elemento de despesa"],
    ["fonte", "TEXT", "Fonte de recurso"],
    ["grupo", "TEXT", "Grupo de despesa"],
    ["pago", "REAL", "Valor pago em R$ (anulações entram negativas)"],
    ["n", "INTEGER", "Nº de documentos de pagamento somados na linha"],
  ];
  const EXEMPLOS = [
    ["Pago por mês e tipo",
     "-- Pago por mês e por tipo de despesa\nSELECT periodo, tipo, ROUND(SUM(pago), 2) AS pago, SUM(n) AS pagamentos\n" +
     "FROM pagamentos\nGROUP BY periodo, tipo\nORDER BY periodo, pago DESC;"],
    ["Favorecidos pagos por mais de uma unidade",
     "-- Favorecidos que receberam de mais de uma unidade gestora\nSELECT MAX(favorecido) AS favorecido, MAX(documento) AS documento,\n" +
     "       COUNT(DISTINCT unidade_gestora) AS unidades, ROUND(SUM(pago), 2) AS pago\nFROM pagamentos\n" +
     "GROUP BY chave_favorecido\nHAVING COUNT(DISTINCT unidade_gestora) > 1\nORDER BY pago DESC\nLIMIT 50;"],
    ["Maior favorecido de cada função",
     "-- O maior favorecido de cada função e quanto ele leva da função\nWITH f AS (\n" +
     "  SELECT funcao, chave_favorecido, MAX(favorecido) AS favorecido, SUM(pago) AS pago\n" +
     "  FROM pagamentos WHERE funcao IS NOT NULL\n  GROUP BY funcao, chave_favorecido\n), r AS (\n" +
     "  SELECT *, ROW_NUMBER() OVER (PARTITION BY funcao ORDER BY pago DESC) AS pos,\n" +
     "         100.0 * pago / SUM(pago) OVER (PARTITION BY funcao) AS pct\n  FROM f\n)\n" +
     "SELECT funcao, favorecido, ROUND(pago, 2) AS pago, ROUND(pct, 1) AS \"% da função\"\n" +
     "FROM r WHERE pos = 1\nORDER BY pago DESC;"],
  ];

  let INDICE = null;                 // despesas-index.json: manifesto `cubos`, top_favorecidos, meses parciais
  let estado = null;
  const carregados = new Map();      // ano → {linhas, pago}
  let modelo = null;                 // último resultado da tabela dinâmica
  let geracao = 0;                   // descarta respostas de uma tabela que já mudou
  let sqlEditado = false;
  let sqlResultado = null;
  let falhou = false;
  let primeiraTabela = true;

  // ── Formatação ────────────────────────────────────────────────────────────
  const inteiro = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR"));
  const reais = (v) => (v == null ? "—" : Comum.brl(v, 2));
  const pct = (v) => {   // 1 casa; abaixo de 0,1% duas; abaixo de 0,01% não vira "0,00%" (existe)
    if (v == null) return "—";
    if (v !== 0 && Math.abs(v) < 0.005) return v > 0 ? "< 0,01%" : "> −0,01%";
    const casas = Math.abs(v) < 0.1 && v !== 0 ? 2 : 1;
    return `${Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas })}%`;
  };
  const mb = (bytes) => `${(bytes / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1, minimumFractionDigits: bytes < 1e6 ? 1 : 0 })} MB`;
  const parciais = () => new Set(INDICE?.resumo?.meses_parciais || []);
  const rotuloPeriodo = (p, curto) => {
    const m = /^(\d{4})-(\d{2})$/.exec(String(p || ""));
    if (!m) return String(p ?? "");
    return `${MESES[+m[2] - 1]}/${curto ? m[1].slice(2) : m[1]}` + (parciais().has(p) ? "*" : "");
  };
  // na matriz o "R$" de cada célula sai (o título e o cabeçalho dizem a medida): "96,6 mi"
  const semRS = (v) => Comum.compacto(v).replace(/^R\$\s?/, "");
  const fmtMedida = (medida, v, compacto) =>
    medida === "n" ? inteiro(v) : medida === "pct" ? pct(v) : (v == null ? "—" : compacto ? semRS(v) : reais(v));
  const listaAnos = (anos) => anos.length > 1 ? anos.slice(0, -1).join(", ") + " e " + anos[anos.length - 1] : String(anos[0]);
  const plural = (n, um, varios) => `${inteiro(n)} ${n === 1 ? um : varios}`;

  // ── SQL ───────────────────────────────────────────────────────────────────
  const lit = (v) => "'" + String(v).replace(/'/g, "''") + "'";
  const alias = (s) => '"' + String(s).replace(/"/g, '""') + '"';
  const rotuloSql = (D) => (D.fav ? "favorecido" : D.vazio ? `COALESCE(${D.col}, ${lit(D.vazio)})` : D.col);
  const valorSql = (D, v) => (v === null ? null : D.numerico ? String(Number(v)) : lit(v));

  function porDimensao(filtros, exceto) {
    const m = new Map();
    for (const f of filtros) {
      if (f.dim === exceto) continue;
      if (!m.has(f.dim)) m.set(f.dim, []);
      m.get(f.dim).push(f.valor);
    }
    return m;
  }

  function condicoes(e, exceto) {
    const c = [`ano IN (${e.anos.join(", ")})`];
    for (const [dim, valores] of porDimensao(e.filtros, exceto)) {
      const D = DIMS[dim];
      const comValor = valores.filter((v) => v !== null);
      const partes = [];
      if (comValor.length) partes.push(`${D.col} IN (${comValor.map((v) => valorSql(D, v)).join(", ")})`);
      if (comValor.length !== valores.length) partes.push(`${D.col} IS NULL`);
      c.push(partes.length > 1 ? `(${partes.join(" OR ")})` : partes[0]);
    }
    return c;
  }

  function tituloPivo(e) {
    const L = DIMS[e.linhas], C = e.colunas ? DIMS[e.colunas] : null;
    const med = e.medida === "n" ? "Nº de pagamentos" : e.medida === "pct" ? "% do total pago" : "Pago";
    const por = L.rotulo.toLowerCase() + (C ? ` e ${C.rotulo.toLowerCase()}` : "");
    const top = L.temporal ? "" : ` · ${e.top} maiores + demais`;
    return `${med} por ${por} — ${listaAnos(e.anos)}${top}`;
  }

  // Valores escolhidos da dimensão das colunas: todos os períodos; nas demais, as
  // COLUNAS_MAX maiores pela medida (o resto numa coluna "Demais").
  function sqlColunas(e) {
    const C = DIMS[e.colunas];
    const base = e.medida === "n" ? "SUM(n)" : "SUM(pago)";
    return `SELECT ${C.col} AS coluna, MAX(${rotuloSql(C)}) AS rotulo, ${C.fav ? "MAX(documento)" : "NULL"} AS documento, ` +
      `${base} AS valor FROM pagamentos WHERE ${condicoes(e).join(" AND ")} GROUP BY coluna ` +
      `ORDER BY ${C.temporal ? "coluna" : "valor DESC, coluna"}`;
  }

  function escolherColunas(e, linhas) {
    const C = DIMS[e.colunas];
    const todas = linhas.map(([chave, rotulo, doc]) => ({ chave, rotulo: C.temporal && !C.numerico ? rotuloPeriodo(chave) : String(rotulo), doc }));
    if (C.fav) {   // homônimos entre as colunas: o documento desempata o cabeçalho
      const vistos = new Map();
      todas.forEach((c) => vistos.set(c.rotulo, (vistos.get(c.rotulo) || 0) + 1));
      todas.forEach((c) => { if (vistos.get(c.rotulo) > 1 && c.doc) c.rotulo += ` (${c.doc})`; });
    }
    if (C.temporal || todas.length <= COLUNAS_MAX + 1) return { cols: todas, demais: false };
    return { cols: todas.slice(0, COLUNAS_MAX), demais: true };
  }

  // A consulta que monta a tabela — a MESMA mostrada em "Ver SQL".
  function sqlPivo(e, cols) {
    const L = DIMS[e.linhas], C = e.colunas ? DIMS[e.colunas] : null;
    const top = L.temporal ? 0 : e.top;
    const ordemPor = e.medida === "n" ? "n" : "pago";
    const s = [`-- ${tituloPivo(e)}`, "-- Explorador de pagamentos · Prefeitura de Santos (pagamentos pela data do pagamento)",
      "WITH filtrado AS (", "  SELECT * FROM pagamentos", "  WHERE " + condicoes(e).join("\n    AND "), "),", "celulas AS ("];
    const sel = [`${L.col} AS linha`, `MAX(${rotuloSql(L)}) AS rotulo`];
    if (L.fav) sel.push("MAX(documento) AS documento");
    if (C) sel.push(`${C.col} AS coluna`);
    sel.push("SUM(pago) AS pago", "SUM(n) AS n");
    s.push(`  SELECT ${sel.join(", ")}`, "  FROM filtrado", `  GROUP BY linha${C ? ", coluna" : ""}`, top ? ")," : ")");
    if (top) {
      s.push("ranking AS (",
        "  SELECT *, DENSE_RANK() OVER (ORDER BY total DESC, linha) AS posicao",
        `  FROM (SELECT *, SUM(${ordemPor}) OVER (PARTITION BY linha) AS total FROM celulas)`, ")");
    }
    const noTop = top ? `MIN(posicao) <= ${top}` : null;
    const out = [top ? `CASE WHEN ${noTop} THEN MAX(rotulo) ELSE 'Demais' END AS ${alias(L.rotulo)}`
                     : `MAX(rotulo) AS ${alias(L.rotulo)}`];
    if (L.fav) out.push(top ? `CASE WHEN ${noTop} THEN MAX(documento) END AS "Documento"` : `MAX(documento) AS "Documento"`);
    const total = "(SELECT SUM(pago) FROM filtrado)";
    const valor = (medida, cond) => {
      const x = (campo) => (cond ? `CASE WHEN ${cond} THEN ${campo} END` : campo);
      if (medida === "n") return `SUM(${x("n")})`;
      if (medida === "pct") return `ROUND(100.0 * SUM(${x("pago")}) / ${total}, 4)`;
      return `ROUND(SUM(${x("pago")}), 2)`;
    };
    if (!C) {
      out.push(`${valor("pago")} AS "Pago (R$)"`, `${valor("pct")} AS "% do total"`, `${valor("n")} AS "Pagamentos"`);
    } else {
      const nulo = cols.cols.some((c) => c.chave === null);
      for (const c of cols.cols) {
        out.push(`${valor(e.medida, c.chave === null ? "coluna IS NULL" : `coluna = ${valorSql(C, c.chave)}`)} AS ${alias(c.rotulo)}`);
      }
      if (cols.demais) {
        const fora = cols.cols.filter((c) => c.chave !== null).map((c) => valorSql(C, c.chave)).join(", ");
        const cond = nulo ? `coluna IS NOT NULL AND coluna NOT IN (${fora})` : `(coluna IS NULL OR coluna NOT IN (${fora}))`;
        out.push(`${valor(e.medida, cond)} AS "Demais"`);
      }
      out.push(`${valor(e.medida)} AS "Total"`);
    }
    if (top) out.push('COUNT(DISTINCT posicao) AS "Itens agrupados"');
    s.push("SELECT", "  " + out.join(",\n  "), `FROM ${top ? "ranking" : "celulas"}`,
      top ? `GROUP BY CASE WHEN posicao <= ${top} THEN posicao END` : "GROUP BY linha",
      top ? "ORDER BY MIN(posicao);" : "ORDER BY linha;");
    return s.join("\n");
  }

  const sqlResumo = (e) => {
    const c = condicoes(e).join(" AND ");
    return `SELECT ROUND(SUM(pago), 2), SUM(n), (SELECT COUNT(*) FROM (SELECT 1 FROM pagamentos WHERE ${c} ` +
      `GROUP BY ${DIMS[e.linhas].col})) FROM pagamentos WHERE ${c}`;
  };

  // ── Estado na URL ─────────────────────────────────────────────────────────
  // anos=2025,2026 · l=funcao · c=mes · m=pago|n|pct · top=10|20|50 · f1, f2… = "dim:valor"
  // (valor vazio = sem valor na origem) · o=coluna:asc|desc · sql=1 (painel aberto) · q=consulta
  function lerEstado() {
    const p = Comum.lerParams();
    const anosManifesto = (INDICE.cubos || []).map((m) => m.ano);
    const ultimo = Math.max(...anosManifesto);
    let anos = (p.get("anos") || "").split(",").map(Number).filter((a) => anosManifesto.includes(a));
    if (!anos.length) anos = [ultimo];
    const dim = (v, padrao) => (DIMS[v] ? v : padrao);
    const linhas = dim(p.get("l"), PADRAO.linhas);
    let colunas = p.get("c") && DIMS[p.get("c")] ? p.get("c") : "";
    if (colunas === linhas) colunas = "";
    const filtros = [...p.keys()].filter((k) => /^f\d+$/.test(k)).sort((a, b) => a.slice(1) - b.slice(1))
      .map((k) => {
        const v = p.get(k), i = v.indexOf(":");
        const d = i > 0 ? v.slice(0, i) : "";
        return DIMS_FILTRO.includes(d) ? { dim: d, valor: v.slice(i + 1) === "" ? null : v.slice(i + 1) } : null;
      }).filter(Boolean);
    const [oc, od] = (p.get("o") || "").split(":");
    return {
      anos: [...new Set(anos)].sort(), linhas, colunas,
      medida: MEDIDAS[p.get("m")] ? p.get("m") : PADRAO.medida,
      top: TOPS.includes(+p.get("top")) ? +p.get("top") : PADRAO.top,
      filtros: filtros.filter((f, i) => filtros.findIndex((g) => g.dim === f.dim && g.valor === f.valor) === i),
      ordem: /^\d+$/.test(oc || "") ? { col: +oc, dir: od === "asc" ? "asc" : "desc" } : null,
      sqlAberto: p.get("sql") === "1", sqlTexto: p.get("q") || "",
    };
  }

  function gravarEstado() {
    const e = estado, ultimo = Math.max(...(INDICE.cubos || []).map((m) => m.ano));
    const obj = {
      anos: e.anos.length === 1 && e.anos[0] === ultimo ? "" : e.anos.join(","),
      l: e.linhas !== PADRAO.linhas ? e.linhas : "", c: e.colunas,
      m: e.medida !== PADRAO.medida ? e.medida : "", top: e.top !== PADRAO.top ? String(e.top) : "",
      o: e.ordem ? `${e.ordem.col}:${e.ordem.dir}` : "",
      sql: e.sqlAberto ? "1" : "", q: e.sqlAberto && sqlEditado ? e.sqlTexto : "",
    };
    e.filtros.forEach((f, i) => { obj["f" + (i + 1)] = `${f.dim}:${f.valor ?? ""}`; });
    Comum.gravarParams(obj);
  }

  // ── Worker (fila de pedidos, teto de tempo, recriação) ─────────────────────
  let worker = null, workerPronto = null, seq = 0;
  const pendentes = new Map();
  const erro = (msg, codigo) => Object.assign(new Error(msg), { codigo });

  function criarWorker() {
    // quem lê a opção `type` sabe abrir worker de módulo; os navegadores antigos a ignoram (e
    // rodariam o arquivo como script clássico) — a detecção é no próprio worker, sem um extra
    let w, leuTipo = false;
    const recusar = (motivo) => {
      workerPronto = Promise.reject(erro("este navegador não abre o worker do SQLite (" + motivo + ")", "navegador"));
      workerPronto.catch(() => {});
    };
    if (typeof Worker !== "function" || typeof WebAssembly !== "object") { recusar("sem Worker ou WebAssembly"); return; }
    try { w = new Worker(WORKER_URL, { get type() { leuTipo = true; return "module"; } }); } catch (e) { recusar(e.message); return; }
    if (!leuTipo) { w.terminate(); recusar("sem worker de módulo"); return; }
    worker = w;
    workerPronto = new Promise((ok, falha) => {
      const t = setTimeout(() => falha(erro("a biblioteca SQLite não respondeu em 45 s", "init")), LIMITE_INICIO_MS);
      w.addEventListener("message", (ev) => {
        const m = ev.data || {};
        if (m.op === "pronto") { clearTimeout(t); m.ok ? ok(m) : falha(erro(m.erro, m.codigo)); return; }
        if (m.op === "etapa") { const p = pendentes.get(m.id); if (p && p.etapa) p.etapa(m.etapa); return; }
        const p = pendentes.get(m.id);
        if (!p) return;
        pendentes.delete(m.id);
        clearTimeout(p.timer);
        m.ok ? p.ok(m) : p.falha(erro(m.erro, m.codigo));
      });
      w.addEventListener("error", (ev) => {
        clearTimeout(t);
        ev.preventDefault();
        const e = erro(ev.message || "o worker do SQLite parou", "worker");
        falha(e);
        for (const [id, p] of pendentes) { clearTimeout(p.timer); p.falha(e); pendentes.delete(id); }
        if (w === worker && !falhou && carregados.size) reiniciar("O SQLite do navegador parou. Recarregando os dados…");
      });
    });
    workerPronto.catch(() => {});
  }

  function pedir(op, dados, { limiteMs = LIMITE_PIVO_MS, etapa } = {}) {
    if (!worker) return Promise.reject(erro("worker indisponível", "worker"));
    const id = ++seq;
    return new Promise((ok, falha) => {
      const p = { ok, falha, etapa, timer: null };
      if (limiteMs) {
        p.timer = setTimeout(() => {
          pendentes.delete(id);
          falha(erro(`passou de ${limiteMs / 1000} s`, "tempo"));
          reiniciar(op === "sql"
            ? "A consulta passou de 10 segundos e foi interrompida. Recarregando os dados…"
            : "O SQLite não respondeu. Recarregando os dados…");
        }, limiteMs);
      }
      pendentes.set(id, p);
      worker.postMessage({ id, op, ...dados });
    });
  }

  let reiniciando = null;
  function reiniciar(msg) {
    if (reiniciando) return reiniciando;
    status(msg);
    const anos = [...carregados.keys()];
    if (worker) worker.terminate();
    for (const [id, p] of pendentes) { clearTimeout(p.timer); p.falha(erro("reiniciado", "reiniciado")); pendentes.delete(id); }
    carregados.clear();
    criarWorker();
    reiniciando = (async () => {
      try {
        await workerPronto;
        for (const a of anos) await carregarAno(a, true);
        status("Explorador pronto de novo — os dados foram recarregados.");
        await atualizar();
      } catch (e) {
        mostrarFalha(e);
      } finally {
        reiniciando = null;
      }
    })();
    return reiniciando;
  }

  // ── Carga dos anos ────────────────────────────────────────────────────────
  const emCarga = new Map();
  function carregarAno(ano, silencioso) {
    if (carregados.has(ano)) return Promise.resolve(carregados.get(ano));
    if (emCarga.has(ano)) return emCarga.get(ano);
    const m = INDICE.cubos.find((c) => c.ano === ano);
    if (!silencioso) status(`Baixando os pagamentos de ${ano} (≈ ${mb(m.gzip || m.bytes)})…`);
    const t = performance.now();
    const p = pedir("carregar", { ano, url: new URL("./" + m.arquivo, location.href).href,
      esperado: { linhas: m.linhas, pago: m.pago } }, {
      limiteMs: 0,
      etapa: () => { if (!silencioso) status(`Montando a tabela de ${ano} no navegador…`); },
    }).then((r) => {
      carregados.set(ano, { linhas: r.linhas, pago: r.pago });
      try {
        performance.measure(`explorador:carregar-${ano}`, { start: t, end: performance.now() });
        performance.measure(`explorador:baixar-${ano}`, { start: t, duration: r.ms_baixar });
        performance.measure(`explorador:montar-${ano}`, { start: t + r.ms_baixar + r.ms_espera, duration: r.ms_montar });
      } catch (e) { /* navegador sem User Timing nível 3 */ }
      renderAnos();
      return r;
    }).finally(() => emCarga.delete(ano));
    emCarga.set(ano, p);
    return p;
  }

  // ── Status (role=status, altura reservada) ────────────────────────────────
  function status(texto, destaque) {
    const el = $("ex-status");
    el.replaceChildren(texto);
    if (destaque) { const b = document.createElement("b"); b.textContent = destaque; el.append(" ", b); }
  }

  // ── Controles ─────────────────────────────────────────────────────────────
  function marcar(seletor, ativo) {
    document.querySelectorAll(seletor).forEach((b) => {
      const on = !!ativo(b);
      b.classList.toggle("primario", on);
      b.setAttribute("aria-pressed", String(on));
    });
  }

  function renderAnos() {
    const caixa = $("ex-anos");
    const foco = caixa.contains(document.activeElement) ? document.activeElement.dataset.ano : null;
    const anos = [...INDICE.cubos].sort((a, b) => b.ano - a.ano);
    caixa.replaceChildren(...anos.map((m) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn";
      b.dataset.ano = m.ano;
      const dentro = estado.anos.includes(m.ano);
      b.append(dentro || carregados.has(m.ano) ? String(m.ano) : `+ ${m.ano}`);
      if (!carregados.has(m.ano) && !dentro) {
        const t = document.createElement("span");
        t.className = "tam";
        t.textContent = ` · ≈ ${mb(m.gzip || m.bytes)}`;
        b.append(t);
        b.title = `Baixa os pagamentos de ${m.ano} (${inteiro(m.linhas)} linhas, ≈ ${mb(m.gzip || m.bytes)}) e soma à tabela`;
      } else b.title = dentro ? `Tirar ${m.ano} da tabela` : `Incluir ${m.ano} na tabela`;
      return b;
    }));
    marcar("#ex-anos button", (b) => estado.anos.includes(+b.dataset.ano));
    if (foco) caixa.querySelector(`button[data-ano="${foco}"]`)?.focus();   // o botão foi recriado
  }

  function opcoes(sel, lista, atual) {
    sel.replaceChildren(...lista.map(([v, t]) => {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = t;
      return o;
    }));
    sel.value = atual;
  }

  function renderControles() {
    const e = estado;
    opcoes($("ex-linhas"), ORDEM_DIMS.map((d) => [d, DIMS[d].rotulo]), e.linhas);
    opcoes($("ex-colunas"), [["", "nenhuma"], ...ORDEM_DIMS.filter((d) => d !== e.linhas).map((d) => [d, DIMS[d].rotulo])], e.colunas);
    $("ex-top").value = String(e.top);
    const temporal = DIMS[e.linhas].temporal;
    $("ex-top").disabled = temporal;
    $("ex-top").title = temporal ? "Mês e ano mostram todos os períodos, em ordem" : "";
    marcar("#ex-medida button", (b) => b.dataset.medida === e.medida);
    renderAnos();
    renderChips();
  }

  function rotuloFiltro(f) {
    const D = DIMS[f.dim];
    if (f.valor === null) return D.vazio || "(vazio)";
    if (f.dim === "mes") return rotuloPeriodo(f.valor);
    if (D.fav) return nomesFav.get(f.valor) || f.valor;
    return f.valor;
  }

  const nomesFav = new Map();   // chave → nome (rótulo dos chips de favorecido)

  function renderChips() {
    const caixa = $("ex-chips");
    const chips = estado.filtros.map((f, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.dataset.i = i;
      const t = document.createElement("span");
      t.className = "v";
      t.textContent = `${DIMS[f.dim].rotulo}: ${rotuloFiltro(f)}`;
      const x = document.createElement("span");
      x.className = "x";
      x.setAttribute("aria-hidden", "true");
      x.textContent = "×";
      b.append(t, x);
      b.setAttribute("aria-label", `Remover o filtro ${DIMS[f.dim].rotulo}: ${rotuloFiltro(f)}`);
      b.title = `${DIMS[f.dim].rotulo}: ${rotuloFiltro(f)}`;
      return b;
    });
    if (estado.filtros.length > 1) {
      const l = document.createElement("button");
      l.type = "button";
      l.className = "chip chip-limpar";
      l.dataset.limpar = "1";
      l.textContent = "Limpar filtros";
      chips.push(l);
    }
    if (!chips.length) {
      const s = document.createElement("span");
      s.className = "nota";
      s.style.margin = "0";
      s.textContent = "nenhum — todos os pagamentos dos anos escolhidos";
      chips.push(s);
    }
    caixa.replaceChildren(...chips);
  }

  function ligarControles() {
    $("ex-anos").addEventListener("click", async (ev) => {
      const b = ev.target.closest("button[data-ano]");
      if (!b) return;
      const ano = +b.dataset.ano;
      if (estado.anos.includes(ano)) {
        if (estado.anos.length === 1) { Comum.toast("A tabela precisa de ao menos um ano."); return; }
        estado.anos = estado.anos.filter((a) => a !== ano);
      } else {
        estado.anos = [...estado.anos, ano].sort();
      }
      renderAnos();
      mudou();
    });
    $("ex-linhas").addEventListener("change", (ev) => {
      estado.linhas = ev.target.value;
      if (estado.colunas === estado.linhas) estado.colunas = "";
      estado.ordem = null;
      renderControles();
      mudou();
    });
    $("ex-colunas").addEventListener("change", (ev) => { estado.colunas = ev.target.value; estado.ordem = null; mudou(); });
    $("ex-top").addEventListener("change", (ev) => { estado.top = +ev.target.value; mudou(); });
    $("ex-medida").addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-medida]");
      if (!b || b.dataset.medida === estado.medida) return;
      estado.medida = b.dataset.medida;
      estado.ordem = null;
      marcar("#ex-medida button", (x) => x.dataset.medida === estado.medida);
      mudou();
    });
    $("ex-chips").addEventListener("click", (ev) => {
      const b = ev.target.closest("button");
      if (!b) return;
      if (b.dataset.limpar) estado.filtros = [];
      else estado.filtros = estado.filtros.filter((_, i) => i !== +b.dataset.i);
      renderChips();
      mudou();
      ($("ex-chips").querySelector("button") || $("ex-add-filtro")).focus();
    });
    ligarEditorFiltro();
  }

  // ── Editor de filtro: dimensão + busca com sugestões (combobox ARIA) ──────
  let sugestoes = [], sugAtiva = -1, valoresDim = { chave: "", lista: [] };

  function ligarEditorFiltro() {
    const abrir = $("ex-add-filtro"), editor = $("ex-editor"), q = $("ex-filtro-q"), dim = $("ex-filtro-dim");
    opcoes(dim, DIMS_FILTRO.map((d) => [d, DIMS[d].rotulo]), "funcao");
    abrir.addEventListener("click", () => {
      const ver = editor.hidden;
      editor.hidden = !ver;
      abrir.setAttribute("aria-expanded", String(ver));
      if (ver) { q.value = ""; q.focus(); buscarValores(); }
    });
    $("ex-filtro-fechar").addEventListener("click", fecharEditor);
    dim.addEventListener("change", () => { q.value = ""; buscarValores(); q.focus(); });
    q.addEventListener("input", () => filtrarSugestoes());
    q.addEventListener("focus", () => filtrarSugestoes());
    q.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        if ($("ex-sugestoes").hidden) filtrarSugestoes();
        if (!sugestoes.length) return;
        sugAtiva = ev.key === "ArrowDown" ? Math.min(sugAtiva + 1, sugestoes.length - 1) : Math.max(sugAtiva - 1, 0);
        marcarSugestao();
      } else if (ev.key === "Enter") {
        ev.preventDefault();
        if (sugestoes[sugAtiva >= 0 ? sugAtiva : 0]) escolher(sugestoes[sugAtiva >= 0 ? sugAtiva : 0]);
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        if (!$("ex-sugestoes").hidden) fecharSugestoes(); else fecharEditor();
      }
    });
    $("ex-sugestoes").addEventListener("mousedown", (ev) => {
      const li = ev.target.closest("li[data-i]");
      if (!li) return;
      ev.preventDefault();
      escolher(sugestoes[+li.dataset.i]);
    });
    document.addEventListener("click", (ev) => {
      if (!ev.target.closest(".combo")) fecharSugestoes();
    });
  }

  function fecharEditor() {
    $("ex-editor").hidden = true;
    $("ex-add-filtro").setAttribute("aria-expanded", "false");
    fecharSugestoes();
    $("ex-add-filtro").focus();
  }
  function fecharSugestoes() {
    $("ex-sugestoes").hidden = true;
    $("ex-filtro-q").setAttribute("aria-expanded", "false");
    $("ex-filtro-q").removeAttribute("aria-activedescendant");
    sugAtiva = -1;
  }

  // valores da dimensão sob os OUTROS filtros (cross-filter), do maior para o menor
  async function buscarValores() {
    const d = $("ex-filtro-dim").value, D = DIMS[d];
    const chave = d + "|" + condicoes(estado, d).join("&");
    if (valoresDim.chave === chave) { filtrarSugestoes(); return; }
    valoresDim = { chave, lista: null };
    filtrarSugestoes();
    try {
      const r = await pedir("consultar", {
        sql: `SELECT ${D.col} AS chave, MAX(${rotuloSql(D)}) AS rotulo, ${D.fav ? "MAX(documento)" : "NULL"} AS doc, ` +
          `ROUND(SUM(pago), 2) AS pago FROM pagamentos WHERE ${condicoes(estado, d).join(" AND ")} GROUP BY chave ` +
          `ORDER BY ${D.temporal ? "chave" : "pago DESC"}`, limite: 50000,
      });
      if (valoresDim.chave !== chave) return;
      valoresDim.lista = r.linhas.map(([v, rotulo, doc, pago]) => ({
        valor: v === null ? null : String(v), rotulo: d === "mes" ? rotuloPeriodo(v) : String(rotulo), doc: doc || "", pago,
        busca: Comum.norm(`${d === "mes" ? rotuloPeriodo(v) + " " + v : rotulo} ${doc || ""} ${(doc || "").replace(/\D/g, "")}`),
      }));
      filtrarSugestoes();
    } catch (e) {
      if (e.codigo !== "reiniciado") valoresDim = { chave: "", lista: [] };
    }
  }

  function filtrarSugestoes() {
    if ($("ex-editor").hidden) return;
    const ul = $("ex-sugestoes"), q = $("ex-filtro-q");
    const termos = Comum.norm(q.value).trim().split(/\s+/).filter(Boolean);
    const d = $("ex-filtro-dim").value;
    const ja = new Set(estado.filtros.filter((f) => f.dim === d).map((f) => f.valor));
    let itens = [];
    if (valoresDim.lista) itens = valoresDim.lista.filter((v) => !ja.has(v.valor) && termos.every((t) => v.busca.includes(t))).slice(0, 30);
    sugestoes = itens;
    sugAtiva = itens.length ? 0 : -1;
    const lis = itens.map((v, i) => {
      const li = document.createElement("li");
      li.id = "ex-sug-" + i;
      li.setAttribute("role", "option");
      li.dataset.i = i;
      const a = document.createElement("span");
      a.textContent = v.rotulo;
      if (v.doc) { const doc = document.createElement("span"); doc.className = "doc"; doc.textContent = v.doc; a.append(doc); }
      const vl = document.createElement("span");
      vl.className = "vl";
      vl.textContent = Comum.compacto(v.pago);
      li.append(a, vl);
      return li;
    });
    if (!lis.length) {
      const li = document.createElement("li");
      li.className = "vazia";
      li.setAttribute("role", "option");
      li.setAttribute("aria-disabled", "true");
      li.textContent = valoresDim.lista ? "Nada encontrado com esse texto." : "Carregando os valores…";
      lis.push(li);
    }
    ul.replaceChildren(...lis);
    ul.hidden = false;
    q.setAttribute("aria-expanded", "true");
    marcarSugestao();
  }

  function marcarSugestao() {
    const q = $("ex-filtro-q");
    $("ex-sugestoes").querySelectorAll("li[data-i]").forEach((li) => {
      const on = +li.dataset.i === sugAtiva;
      li.classList.toggle("ativa", on);
      li.setAttribute("aria-selected", String(on));
      if (on) li.scrollIntoView({ block: "nearest" });
    });
    if (sugAtiva >= 0) q.setAttribute("aria-activedescendant", "ex-sug-" + sugAtiva);
    else q.removeAttribute("aria-activedescendant");
  }

  function escolher(v) {
    const d = $("ex-filtro-dim").value;
    if (DIMS[d].fav && v.valor) nomesFav.set(v.valor, v.rotulo);
    estado.filtros = [...estado.filtros, { dim: d, valor: v.valor }];
    $("ex-filtro-q").value = "";
    fecharSugestoes();
    renderChips();
    status(`Filtro aplicado: ${DIMS[d].rotulo} = ${v.rotulo}.`);
    mudou();
  }

  // ── Tabela dinâmica ───────────────────────────────────────────────────────
  const mudou = Comum.debounce(() => { gravarEstado(); atualizar(); }, 60);

  async function atualizar() {
    if (falhou) return;
    const e = estado, minha = ++geracao;
    try {
      await workerPronto;
      const novos = e.anos.filter((a) => !carregados.has(a)), tAnos = performance.now();
      for (const a of e.anos) await carregarAno(a);
      if (minha !== geracao) return;
      const t = performance.now();
      const cols = e.colunas ? escolherColunas(e, (await pedir("consultar", { sql: sqlColunas(e) })).linhas) : null;
      const sql = sqlPivo(e, cols);
      const [r, res] = await Promise.all([pedir("consultar", { sql }), pedir("consultar", { sql: sqlResumo(e) })]);
      if (minha !== geracao) return;
      modelo = montarModelo(e, cols, r, res.linhas[0]);
      modelo.sql = sql;
      modelo.ms = performance.now() - t;
      renderTabela();
      renderGrafico();
      if (!sqlEditado) $("ex-sql-texto").value = sql;
      $("ex-csv").disabled = false;
      if (primeiraTabela) {
        primeiraTabela = false;
        const total = performance.now() - T0;
        try { performance.measure("explorador:pronto", { start: T0, end: performance.now() }); } catch (x) { /* idem */ }
        const linhas = e.anos.reduce((s, a) => s + (carregados.get(a)?.linhas || 0), 0);
        status(`Pronto em ${(total / 1000).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s ·`,
          `${inteiro(linhas)} linhas de ${listaAnos(e.anos)} no seu navegador.`);
        if (e.sqlAberto && sqlEditado) rodarSql();
      } else if (novos.length) {   // um ano a mais na tabela: quanto levou e o que está carregado
        const linhas = e.anos.reduce((s, a) => s + (carregados.get(a)?.linhas || 0), 0);
        status(`${listaAnos(novos)} somado em ${((performance.now() - tAnos) / 1000).toLocaleString("pt-BR",
          { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s ·`, `${inteiro(linhas)} linhas de ${listaAnos(e.anos)} no seu navegador.`);
      } else {
        status(`Tabela atualizada em ${Math.round(modelo.ms)} ms ·`, `${plural(modelo.linhas.length, "linha", "linhas")}.`);
      }
    } catch (err) {
      if (minha !== geracao || err.codigo === "reiniciado") return;
      if (err.codigo === "tempo") return;   // reiniciar() já avisou e refaz a tabela
      if (["cdn", "init", "worker", "navegador"].includes(err.codigo)) { mostrarFalha(err); return; }
      console.warn("explorador:", err);
      Comum.estadoErro($("ex-corpo-erro") || criarAreaErro(), err.codigo === "dados"
        ? `Não foi possível carregar os pagamentos (${err.message}). Verifique a conexão.`
        : `A tabela não pôde ser montada: ${err.message}`, () => { removerAreaErro(); atualizar(); });
      status("Algo deu errado — veja o aviso abaixo.");
    }
  }

  function criarAreaErro() {   // logo abaixo do status: visível mesmo com a tabela escondida
    const d = document.createElement("div");
    d.id = "ex-corpo-erro";
    $("ex-status").after(d);
    return d;
  }
  function removerAreaErro() { $("ex-corpo-erro")?.remove(); }

  // Resultado do SQL → modelo da tabela (cabeçalhos, linhas, totais)
  function montarModelo(e, cols, r, resumo) {
    removerAreaErro();
    const L = DIMS[e.linhas], C = e.colunas ? DIMS[e.colunas] : null;
    const top = L.temporal ? 0 : e.top;
    const cab = [{ texto: L.rotulo, tipo: "rotulo" }];
    if (L.fav) cab.push({ texto: "Documento", tipo: "doc" });
    if (!C) {
      cab.push({ texto: "Pago (R$)", tipo: "valor", medida: "pago" }, { texto: "% do total", tipo: "valor", medida: "pct" },
        { texto: "Pagamentos", tipo: "valor", medida: "n" });
    } else {
      cols.cols.forEach((c) => cab.push({ texto: c.rotulo, tipo: "valor", medida: e.medida, coluna: c }));
      if (cols.demais) cab.push({ texto: "Demais", tipo: "valor", medida: e.medida, demais: true });
      cab.push({ texto: "Total", tipo: "valor", medida: e.medida, total: true });
    }
    const iItens = top ? cab.length : -1;
    const linhas = r.linhas.map((l, pos) => {
      const itens = iItens >= 0 ? l[iItens] : 1;
      const demais = !!top && pos === r.linhas.length - 1 && (l[0] === "Demais" && (itens > 1 || pos >= top));
      const rotulo = l[0], doc = L.fav ? l[1] : null;
      let chave = null;
      if (!demais) {
        if (L.fav) chave = Comum.identidadeFavorecido(rotulo, doc);
        else if (L.numerico) chave = Number(rotulo);
        else chave = L.vazio && rotulo === L.vazio ? null : String(rotulo);
      }
      return { pos, celulas: l.slice(0, cab.length), itens, demais, rotulo, doc, chave };
    });
    const totais = cab.map((c, i) => (c.tipo === "valor"
      ? linhas.reduce((s, l) => (l.celulas[i] == null ? s : s + l.celulas[i]), 0) : null));
    cab.forEach((c, i) => {
      if (c.tipo !== "valor") return;
      totais[i] = c.medida === "n" ? Math.round(totais[i]) : c.medida === "pct" ? totais[i] : Math.round(totais[i] * 100) / 100;
    });
    const destaque = !C ? cab.findIndex((c) => c.medida === (e.medida === "pct" ? "pct" : e.medida)) : cab.length - 1;
    return { e: { ...e, filtros: e.filtros.slice(), anos: e.anos.slice() }, cab, linhas, totais, destaque,
      resumo: { pago: resumo[0], n: resumo[1], grupos: resumo[2] }, top };
  }

  function linhasOrdenadas() {
    const o = estado.ordem, m = modelo;
    const base = m.linhas.filter((l) => !l.demais), demais = m.linhas.filter((l) => l.demais);
    if (!o || o.col >= m.cab.length) return base.concat(demais);
    const i = o.col, dir = o.dir === "asc" ? 1 : -1;
    const ord = base.slice().sort((a, b) => {
      const va = a.celulas[i], vb = b.celulas[i];
      if (va == null && vb == null) return a.pos - b.pos;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir || a.pos - b.pos;
      return String(va).localeCompare(String(vb), "pt-BR") * dir || a.pos - b.pos;
    });
    return ord.concat(demais);
  }

  function textoCelula(c, v, compacto) {
    if (c.tipo === "rotulo" || c.tipo === "doc") return v == null ? "—" : String(v);
    return fmtMedida(c.medida, v, compacto);
  }

  // Link de uma linha: raio-X (favorecido) ou Detalhamento em movimentação, só pagamentos,
  // com o recorte — o mesmo contrato de _link_detalhe (export.py) e irParaDetalhe (despesas-app.js)
  function linkLinha(l) {
    const e = modelo.e, L = DIMS[e.linhas];
    if (l.demais) return null;
    if (L.fav) {
      const top = (INDICE.top_favorecidos || []).find((t) => t.chave === l.chave);
      return { href: top?.slug ? `./favorecido.html?f=${encodeURIComponent(top.slug)}`
        : `./favorecido.html?doc=${encodeURIComponent(l.doc || "")}&nome=${encodeURIComponent(l.rotulo || "")}`,
        titulo: "Abrir o raio-X do favorecido" };
    }
    if (l.chave === null) return null;   // "(sem função)" etc.: o Detalhamento não filtra o vazio
    const p = new URLSearchParams({ dv: "mov" });
    const porDim = porDimensao(e.filtros);
    let meses;
    if (e.linhas === "mes") meses = [l.chave];
    else if (e.linhas === "ano") meses = [String(l.chave)];
    else if (porDim.has("mes")) meses = porDim.get("mes").filter(Boolean).sort();
    else meses = e.anos.map(String);
    p.set("dm", meses.join(","));
    p.set("dfa", "P");
    const ignorados = [];
    for (const [dim, vals] of porDim) {
      const D = DIMS[dim];
      if (!D.det) continue;
      if (vals.length === 1 && vals[0] !== null) p.set(D.det, vals[0]);
      else ignorados.push(D.rotulo.toLowerCase());
    }
    if (L.det) p.set(L.det, String(l.chave));
    const bytes = (INDICE.meses_movimento || []).filter((m) => meses.some((x) =>
      x === String(m.ano) || x === `${m.ano}-${String(m.mes).padStart(2, "0")}`)).reduce((s, m) => s + (m.bytes || 0), 0);
    return { href: `./despesas.html?${p.toString()}#detalhe`,
      titulo: `Abrir no Detalhamento (movimentação, só pagamentos)${bytes ? ` — download ≈ ${mb(bytes)}` : ""}` +
        (ignorados.length ? `. Filtro com mais de um valor fica de fora: ${ignorados.join(", ")}` : "") };
  }

  function renderTabela() {
    const m = modelo, e = m.e, L = DIMS[e.linhas], C = e.colunas ? DIMS[e.colunas] : null;
    const compacto = !!C && e.medida === "pago";
    $("ex-titulo").textContent = tituloPivo(e);
    const res = $("ex-resumo");
    const b1 = document.createElement("b"), b2 = document.createElement("b");
    b1.textContent = reais(m.resumo.pago);
    b2.textContent = inteiro(m.resumo.n);
    res.replaceChildren(b1, " em ", b2, ` pagamentos · ${plural(m.resumo.grupos, L.rotulo.toLowerCase(), L.plural)}` +
      (e.filtros.length ? ` · ${plural(e.filtros.length, "filtro", "filtros")}` : ""));
    $("ex-legenda").textContent = `${tituloPivo(e)}. ` + (e.filtros.length
      ? "Filtros: " + e.filtros.map((f) => `${DIMS[f.dim].rotulo} = ${rotuloFiltro(f)}`).join("; ") + ". " : "") +
      "Os cabeçalhos ordenam a tabela; a última linha é o total.";

    // cabeçalho com botões de ordenação (aria-sort na coluna ordenada)
    const ordem = estado.ordem && estado.ordem.col < m.cab.length ? estado.ordem
      : { col: L.temporal ? 0 : m.destaque, dir: L.temporal ? "asc" : "desc", padrao: true };
    const tr = document.createElement("tr");
    m.cab.forEach((c, i) => {
      const th = document.createElement("th");
      th.scope = "col";
      if (c.tipo === "valor") th.className = "r";
      if (i === m.destaque) th.classList.add("ativa");
      if (i === ordem.col) th.setAttribute("aria-sort", ordem.dir === "asc" ? "ascending" : "descending");
      const bt = document.createElement("button");
      bt.type = "button";
      bt.dataset.col = i;
      bt.textContent = c.texto;
      if (i === ordem.col) {
        const s = document.createElement("span");
        s.className = "seta";
        s.setAttribute("aria-hidden", "true");
        s.textContent = ordem.dir === "asc" ? " ▲" : " ▼";
        bt.append(s);
      }
      th.append(bt);
      tr.append(th);
    });
    $("ex-cabecalho").replaceChildren(tr);

    const corpo = [];
    for (const l of linhasOrdenadas()) {
      const linha = document.createElement("tr");
      const link = linkLinha(l);
      if (l.demais) linha.className = "demais";
      if (link) { linha.className = "ex-linha-link"; linha.dataset.href = link.href; }
      m.cab.forEach((c, i) => {
        const td = document.createElement("td");
        td.dataset.label = c.texto;
        const v = l.celulas[i];
        if (i === 0) {
          const texto = l.demais ? `Demais (${plural(l.itens, L.rotulo.toLowerCase(), L.plural)})`
            : e.linhas === "mes" ? rotuloPeriodo(v) : textoCelula(c, v);
          if (link) {
            const a = document.createElement("a");
            a.className = "ex-nome";
            a.href = link.href;
            a.title = link.titulo;
            a.textContent = texto;
            td.append(a);
          } else td.textContent = texto;
        } else {
          td.textContent = textoCelula(c, v, compacto);
          if (c.tipo === "valor") {
            td.className = "r num";
            if (typeof v === "number" && v < 0) td.classList.add("neg");
            if (compacto && v != null) td.title = reais(v);
          } else if (c.tipo === "doc") td.className = "num";
        }
        if (i === m.destaque) td.classList.add("ativa");
        linha.append(td);
      });
      corpo.push(linha);
    }
    $("ex-corpo").replaceChildren(...corpo);
    if (!corpo.length) {
      const trv = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = m.cab.length;
      td.className = "vazio";
      td.textContent = "Nenhum pagamento com esses filtros — remova um filtro para ampliar.";
      trv.append(td);
      $("ex-corpo").replaceChildren(trv);
    }
    // total (soma das linhas exibidas, inclusive "Demais")
    const tt = document.createElement("tr");
    m.cab.forEach((c, i) => {
      const td = document.createElement("td");
      td.dataset.label = c.texto;
      if (i === 0) td.textContent = "Total";
      else if (c.tipo === "valor") {
        td.className = "r num";
        td.textContent = textoCelula(c, m.totais[i], compacto);
        if (compacto) td.title = reais(m.totais[i]);
      }
      if (i === m.destaque) td.classList.add("ativa");
      tt.append(td);
    });
    $("ex-rodape-tabela").replaceChildren(tt);
    $("ex-tabela").classList.toggle("matriz", !!C);
    // tabela mais larga que a caixa (matriz em tela média): dica visual e foco por teclado
    // para rolar (área rolável sem nada focável não se alcança pelo teclado)
    const wrap = $("ex-tabela-wrap"), rola = wrap.scrollWidth > wrap.clientWidth + 2;
    $("ex-dica-scroll").hidden = !rola;
    if (rola) {
      wrap.tabIndex = 0;
      wrap.setAttribute("role", "region");
      wrap.setAttribute("aria-label", "Tabela dinâmica — role para os lados para ver todas as colunas");
    } else ["tabindex", "role", "aria-label"].forEach((a) => wrap.removeAttribute(a));
    const temParcial = (e.linhas === "mes" || e.colunas === "mes") && m.linhas.length &&
      [...parciais()].some((p) => e.anos.includes(+p.slice(0, 4)));
    $("ex-nota-parcial").hidden = !temParcial;
    if (temParcial) $("ex-nota-parcial").textContent = `* Mês parcial (${[...parciais()].map((p) => rotuloPeriodo(p).replace("*", "")).join(", ")}): ` +
      "o portal publica com semanas de atraso — o valor ainda vai subir.";
  }

  function ligarTabela() {
    $("ex-cabecalho").addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-col]");
      if (!b || !modelo) return;
      const col = +b.dataset.col;
      const atual = estado.ordem;
      const ehValor = modelo.cab[col].tipo === "valor";
      estado.ordem = atual && atual.col === col ? { col, dir: atual.dir === "asc" ? "desc" : "asc" }
        : { col, dir: ehValor ? "desc" : "asc" };
      gravarEstado();
      renderTabela();
      $("ex-cabecalho").querySelector(`button[data-col="${col}"]`)?.focus();
    });
    $("ex-corpo").addEventListener("click", (ev) => {
      const tr = ev.target.closest("tr[data-href]");
      if (!tr || ev.target.closest("a, button") || getSelection().toString()) return;
      location.href = tr.dataset.href;
    });
    $("ex-csv").addEventListener("click", exportarCsv);
  }

  function recorteTexto(e) {
    const partes = [`Pagamentos de ${listaAnos(e.anos)} (pela data do pagamento)`];
    e.filtros.forEach((f) => partes.push(`${DIMS[f.dim].rotulo} = ${rotuloFiltro(f)}`));
    if (!DIMS[e.linhas].temporal) partes.push(`${e.top} maiores + demais`);
    partes.push("Explorador de pagamentos — Portal da Transparência de Santos");
    return partes.join(" · ");
  }

  function exportarCsv() {
    if (!modelo) return;
    const m = modelo, e = m.e, L = DIMS[e.linhas];
    const cab = m.cab.map((c) => c.texto + (e.colunas && c.tipo === "valor" && !c.total
      ? (e.medida === "pago" ? " (R$)" : e.medida === "pct" ? " (%)" : " (nº)") : ""));
    const recorte = recorteTexto(e);
    const linhas = m.linhas.map((l) => l.celulas.map((v, i) => {
      if (i === 0) return l.demais ? `Demais (${l.itens} ${l.itens === 1 ? L.rotulo.toLowerCase() : L.plural})` : v ?? "";
      return v ?? "";
    }).concat([recorte]));
    linhas.push(m.totais.map((v, i) => (i === 0 ? "Total" : v ?? "")).concat([recorte]));
    const nome = `explorador-pagamentos-${e.linhas}${e.colunas ? "-por-" + e.colunas : ""}-${e.anos.join("-")}` +
      (e.filtros.length ? "-filtrado" : "") + ".csv";
    Comum.exportarCsv(nome, cab.concat(["Recorte"]), linhas);
  }

  // ── Gráfico (Comum.grafico, ECharts) ──────────────────────────────────────
  const CORES = (p) => [p.serie, p.ouro, "#8d9aad", "#5b8def", "#e08a3c", "#2fa79a", "#a78bfa"];
  const corOutros = (p) => (Comum.temaAtual() === "escuro" ? "#3b4a63" : "#d5d0c4");
  const eixoMedida = (medida) => (v) => (medida === "n" ? inteiro(v) : medida === "pct" ? `${v.toLocaleString("pt-BR")}%` : Comum.compactoEixo(v));
  const cortar = (s, n) => (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s));

  function rotuloLinha(l, e) {
    if (l.demais) return "Demais";
    if (e.linhas === "mes") return rotuloPeriodo(l.celulas[0]);
    return String(l.celulas[0] ?? "—");
  }

  function renderGrafico() {
    const m = modelo, e = m.e, L = DIMS[e.linhas], C = e.colunas ? DIMS[e.colunas] : null;
    const medida = e.medida;
    const iValor = C ? m.cab.length - 1 : m.cab.findIndex((c) => c.medida === medida);
    const nomeMedida = MEDIDAS[medida];
    if (!m.linhas.length) {
      Comum.grafico("ex-grafico", { opcao: () => ({ title: { text: "Sem pagamentos com esses filtros", left: "center", top: "middle",
        textStyle: { fontSize: 13, fontWeight: 500 } } }), acessivel: { descricao: "Sem dados para o gráfico.", cabecalhos: ["—"], linhas: [] } });
      return;
    }
    if (!C) {
      // uma medida por linha: barras deitadas (maiores em cima) ou em pé, em ordem, para mês/ano
      const itens = L.temporal ? m.linhas : m.linhas.filter((l) => !l.demais).slice(0, BARRAS_MAX);
      const nomes = itens.map((l) => rotuloLinha(l, e));
      const valores = itens.map((l) => l.celulas[iValor]);
      const iPct = m.cab.findIndex((c) => c.medida === "pct");
      const desc = L.temporal
        ? `Gráfico de barras: ${nomeMedida.toLowerCase()} por ${L.rotulo.toLowerCase()} em ${listaAnos(e.anos)}, em ordem cronológica.`
        : `Gráfico de barras: ${nomeMedida.toLowerCase()} por ${L.rotulo.toLowerCase()} em ${listaAnos(e.anos)} — ` +
          `${itens.length === m.linhas.filter((l) => !l.demais).length ? `os ${itens.length}` : `os ${itens.length} maiores`}` +
          ` (sem a linha “Demais”). Maior: ${nomes[0]}, ${fmtMedida(medida, valores[0])}` +
          (iPct >= 0 && medida !== "pct" ? ` (${pct(itens[0].celulas[iPct])} do total).` : ".");
      Comum.grafico("ex-grafico", {
        dependeDaLargura: true,
        opcao: (p, larg) => L.temporal ? {
          grid: { left: 4, right: 12, top: 16, bottom: 4, containLabel: true },
          tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" },
            formatter: (ps) => Comum.dicaGrafico(nomes[ps[0].dataIndex], [[p.serie, nomeMedida, fmtMedida(medida, valores[ps[0].dataIndex])]],
              e.linhas === "mes" && parciais().has(itens[ps[0].dataIndex].celulas[0]) ? "Mês parcial — a origem ainda está publicando." : "") },
          xAxis: { type: "category", data: e.linhas === "mes" ? itens.map((l) => rotuloPeriodo(l.celulas[0], true)) : nomes,
            axisLabel: { hideOverlap: true, interval: p.celular && itens.length > 12 ? 1 : 0 } },
          yAxis: { type: "value", axisLabel: { formatter: eixoMedida(medida) }, splitNumber: 4 },
          series: [{ type: "bar", barMaxWidth: 34, data: valores.map((v, i) => ({ value: v,
            itemStyle: { color: e.linhas === "mes" && parciais().has(itens[i].celulas[0]) ? p.ouroClaro : p.serie } })),
            itemStyle: { borderRadius: [3, 3, 0, 0] } }],
        } : {
          // o rótulo do teto do eixo fica centrado no traço e o containLabel não o conta;
          // no celular a margem é a do valor na ponta da barra
          grid: { left: 4, right: p.celular ? 64 : 30, top: 6, bottom: 4, containLabel: true },
          tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" },
            formatter: (ps) => {
              const i = ps[0].dataIndex, l = itens[i];
              return Comum.dicaGrafico(nomes[i], [[p.serie, nomeMedida, fmtMedida(medida, valores[i])],
                iPct >= 0 && medida !== "pct" ? [null, "% do total", pct(l.celulas[iPct])] : null], L.fav && l.doc ? l.doc : "");
            } },
          // celular: a caixa útil das barras fica com ~150 px e o eixo só cabia 2 rótulos —
          // sai o eixo e o valor (compacto) vai na ponta de cada barra
          xAxis: p.celular ? { type: "value", show: false }
            : { type: "value", splitNumber: larg < 700 ? 3 : 5, axisLabel: { formatter: eixoMedida(medida), hideOverlap: true } },
          yAxis: { type: "category", inverse: true, data: nomes.map((n) => cortar(n, p.celular ? 20 : 40)),
            axisLabel: { width: p.celular ? 118 : 260, overflow: "truncate" } },
          series: [{ type: "bar", barMaxWidth: 22, data: valores, itemStyle: { color: p.serie, borderRadius: [0, 3, 3, 0] },
            label: { show: p.celular, position: "right", color: p.tinta, fontFamily: p.mono, fontSize: 10.5,
              formatter: (x) => (medida === "n" ? inteiro(x.value) : medida === "pct" ? pct(x.value) : Comum.compacto(x.value)) } }],
        },
        acessivel: { descricao: desc, cabecalhos: [L.rotulo, nomeMedida], linhas: itens.map((l, i) => [nomes[i], fmtMedida(medida, valores[i])]) },
      });
      return;
    }
    // com colunas: barras empilhadas — o tempo sempre no eixo x
    const valCols = m.cab.map((c, i) => [c, i]).filter(([c]) => c.tipo === "valor" && !c.total);
    const linhasSemDemais = m.linhas.filter((l) => !l.demais);
    let categorias, series;
    if (L.temporal) {
      categorias = m.linhas.map((l) => (e.linhas === "mes" ? rotuloPeriodo(l.celulas[0], true) : rotuloLinha(l, e)));
      series = valCols.map(([c, i]) => ({ nome: c.texto, dados: m.linhas.map((l) => l.celulas[i]) }));
    } else {
      categorias = valCols.map(([c]) => (C.temporal && !C.numerico && c.coluna ? rotuloPeriodo(c.coluna.chave, true) : c.texto));
      const principais = linhasSemDemais.slice(0, SERIES_MAX);
      const resto = m.linhas.filter((l) => !principais.includes(l));
      series = principais.map((l) => ({ nome: rotuloLinha(l, e), dados: valCols.map(([, i]) => l.celulas[i]) }));
      if (resto.length) {
        series.push({ nome: "Outros", outros: true, dados: valCols.map(([, i]) => {
          const vs = resto.map((l) => l.celulas[i]).filter((v) => v != null);
          return vs.length ? vs.reduce((s, v) => s + v, 0) : null;
        }) });
      }
    }
    const desc = `Gráfico de barras empilhadas: ${nomeMedida.toLowerCase()} por ${L.temporal ? L.rotulo.toLowerCase() : C.rotulo.toLowerCase()}, ` +
      `dividido por ${L.temporal ? C.rotulo.toLowerCase() : L.rotulo.toLowerCase()}` +
      (L.temporal ? "" : ` (os ${Math.min(SERIES_MAX, linhasSemDemais.length)} maiores${series.some((s) => s.outros) ? " e os outros juntos" : ""})`) +
      `, em ${listaAnos(e.anos)}.`;
    Comum.grafico("ex-grafico", {
      dependeDaLargura: true,
      opcao: (p) => {
        const cores = CORES(p);
        return {
          grid: { left: 4, right: 12, top: p.celular ? 12 : 48, bottom: p.celular ? 70 : 4, containLabel: true },
          legend: { type: "scroll", [p.celular ? "bottom" : "top"]: 0, left: 0, right: 0, itemWidth: 12, itemHeight: 10,
            formatter: (n) => cortar(n, p.celular ? 24 : 34) },
          tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" },
            formatter: (ps) => Comum.dicaGrafico(categorias[ps[0].dataIndex] + "", ps.filter((x) => x.value != null)
              .map((x) => [x.color, cortar(x.seriesName, 40), fmtMedida(medida, x.value), "p"])) },
          xAxis: { type: "category", data: categorias, axisLabel: { hideOverlap: true, interval: 0, rotate: categorias.length > 8 && !L.temporal && !C.temporal ? 30 : 0,
            formatter: (v) => cortar(v, 16) } },
          yAxis: { type: "value", axisLabel: { formatter: eixoMedida(medida) }, splitNumber: 4 },
          series: series.map((s, k) => ({ name: s.nome, type: "bar", stack: "total", barMaxWidth: 40, data: s.dados,
            itemStyle: { color: s.outros ? corOutros(p) : cores[k % cores.length] }, emphasis: { focus: "series" } })),
        };
      },
      acessivel: { descricao: desc, cabecalhos: [L.temporal ? L.rotulo : C.rotulo, ...series.map((s) => s.nome)],
        linhas: categorias.map((c, j) => [c, ...series.map((s) => fmtMedida(medida, s.dados[j]))]) },
    });
  }

  // ── Ver SQL ───────────────────────────────────────────────────────────────
  function ligarSql() {
    const painel = $("ex-sql"), botao = $("ex-ver-sql"), texto = $("ex-sql-texto");
    const abrir = (ver, focar) => {
      painel.hidden = !ver;
      botao.setAttribute("aria-expanded", String(ver));
      botao.textContent = ver ? "Esconder SQL" : "Ver SQL";
      estado.sqlAberto = ver;
      gravarEstado();
      if (ver && focar) texto.focus();
    };
    botao.addEventListener("click", () => abrir(painel.hidden, true));
    if (estado.sqlAberto) abrir(true, false);
    if (estado.sqlTexto) { texto.value = estado.sqlTexto; sqlEditado = true; $("ex-sql-voltar").hidden = false; }
    texto.addEventListener("input", () => {
      sqlEditado = texto.value !== (modelo?.sql || "");
      $("ex-sql-voltar").hidden = !sqlEditado;
    });
    texto.addEventListener("keydown", (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") { ev.preventDefault(); rodarSql(); }
    });
    $("ex-sql-rodar").addEventListener("click", rodarSql);
    $("ex-sql-voltar").addEventListener("click", () => {
      texto.value = modelo?.sql || "";
      sqlEditado = false;
      $("ex-sql-voltar").hidden = true;
      estado.sqlTexto = "";
      gravarEstado();
      texto.focus();
    });
    $("ex-sql-csv").addEventListener("click", () => {
      if (!sqlResultado) return;
      Comum.exportarCsv("explorador-consulta-sql.csv", sqlResultado.colunas, sqlResultado.linhas.map((l) => l.map((v) => v ?? "")));
    });
    $("ex-sql-mais").addEventListener("click", () => mostrarMaisSql());
    const ex = $("ex-exemplos");
    EXEMPLOS.forEach(([rotulo, sql]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "lnk";
      b.textContent = rotulo;
      b.addEventListener("click", () => {
        texto.value = sql;
        sqlEditado = true;
        $("ex-sql-voltar").hidden = false;
        rodarSql();
      });
      ex.append(b);
    });
    $("ex-esquema-corpo").replaceChildren(...COLUNAS_SQL.map(([c, t, d]) => {
      const tr = document.createElement("tr");
      [c, t, d].forEach((v, i) => {
        const td = document.createElement("td");
        td.dataset.label = ["Coluna", "Tipo", "O que é"][i];
        if (i < 2) { const code = document.createElement("code"); code.textContent = v; td.append(code); } else td.textContent = v;
        tr.append(td);
      });
      return tr;
    }));
  }

  function statusSql(texto, ehErro) {
    const el = $("ex-sql-status");
    el.textContent = texto;
    el.classList.toggle("erro", !!ehErro);
  }

  async function rodarSql() {
    const sql = $("ex-sql-texto").value;
    if (sqlEditado) { estado.sqlTexto = sql; gravarEstado(); }
    statusSql("Executando…");
    $("ex-sql-rodar").disabled = true;
    try {
      await workerPronto;
      const r = await pedir("sql", { sql }, { limiteMs: LIMITE_SQL_MS });
      sqlResultado = r;
      renderSqlResultado();
      statusSql(`${plural(r.linhas.length, "linha", "linhas")} em ${Math.round(r.ms).toLocaleString("pt-BR")} ms` +
        (r.truncado ? ` — mostrando as primeiras ${inteiro(r.linhas.length)} (limite de 5.000 linhas).` : "."));
      $("ex-sql-csv").disabled = !r.linhas.length;
    } catch (e) {
      sqlResultado = null;
      $("ex-sql-csv").disabled = true;
      $("ex-sql-res").hidden = true;
      $("ex-sql-mais").hidden = true;
      if (e.codigo === "tempo") statusSql("A consulta passou de 10 segundos e foi interrompida. Os dados estão sendo recarregados — simplifique a consulta (um LIMIT, menos junções) e tente de novo.", true);
      else if (e.codigo === "reiniciado") statusSql("O explorador foi reiniciado durante a consulta. Tente de novo.", true);
      else statusSql((e.codigo === "guarda" ? "Consulta recusada: " : "Erro do SQLite: ") + e.message, true);
    } finally {
      $("ex-sql-rodar").disabled = false;
    }
  }

  let sqlMostradas = 0;
  function renderSqlResultado() {
    const r = sqlResultado, tabela = $("ex-sql-tabela");
    const tr = document.createElement("tr");
    r.colunas.forEach((c) => { const th = document.createElement("th"); th.scope = "col"; th.textContent = c; tr.append(th); });
    tabela.tHead.replaceChildren(tr);
    tabela.tBodies[0].replaceChildren();
    sqlMostradas = 0;
    $("ex-sql-res").hidden = !r.colunas.length;
    mostrarMaisSql();
  }

  function mostrarMaisSql() {
    const r = sqlResultado, corpo = $("ex-sql-tabela").tBodies[0];
    const fim = Math.min(sqlMostradas + PAGINA_SQL, r.linhas.length);
    const frag = document.createDocumentFragment();
    for (let k = sqlMostradas; k < fim; k++) {
      const tr = document.createElement("tr");
      r.linhas[k].forEach((v) => {
        const td = document.createElement("td");
        if (v === null) { td.textContent = "NULL"; td.className = "nulo"; }
        else if (typeof v === "number") {   // inteiro sem casas; fracionário com 2 a 6 (R$ 596,70)
          td.textContent = v.toLocaleString("pt-BR", Number.isInteger(v) ? { maximumFractionDigits: 0 }
            : { minimumFractionDigits: 2, maximumFractionDigits: 6 });
          td.className = "r num";
        } else td.textContent = String(v);
        if (typeof v === "string" && v.length > 60) td.title = v;
        tr.append(td);
      });
      frag.append(tr);
    }
    corpo.append(frag);
    sqlMostradas = fim;
    $("ex-sql-mais").hidden = sqlMostradas >= r.linhas.length;
    if (!$("ex-sql-mais").hidden) $("ex-sql-mais").textContent = `Mostrar mais (${inteiro(r.linhas.length - sqlMostradas)} restantes)`;
  }

  // ── Falha: sem SQLite (CDN fora, navegador antigo) → CSV do cubo em JS puro ──
  function mostrarFalha(e) {
    if (falhou) return;
    falhou = true;
    if (worker) { worker.terminate(); worker = null; }
    console.warn("explorador: SQLite indisponível —", e && e.message);
    status("O explorador não abriu — veja as alternativas abaixo.");
    if (e && e.codigo === "navegador") $("ex-falha-titulo").textContent = "O explorador não abre neste navegador";
    $("ex-falha-motivo").textContent = e && e.codigo === "navegador"
      ? "Este navegador não roda a tabela dinâmica (falta suporte a Web Worker de módulo ou WebAssembly). Atualize o navegador ou use outro."
      : "A biblioteca SQLite, que monta a tabela no seu navegador, não pôde ser carregada agora (sem conexão com o CDN ou arquivo diferente do publicado). Tente de novo mais tarde.";
    avisoAlternativas(true);
  }

  // Caixa de aviso com as saídas: CSV de cada cubo (se houver), Detalhamento e "Tentar de novo"
  function avisoAlternativas(comCsv) {
    const acoes = $("ex-falha-acoes");
    const botoes = (comCsv ? [...(INDICE?.cubos || [])] : []).sort((a, b) => b.ano - a.ano).map((m) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn primario";
      b.textContent = `Baixar o cubo de ${m.ano} (CSV)`;
      b.addEventListener("click", () => baixarCuboCsv(m, b));
      return b;
    });
    const tentar = document.createElement("button");
    tentar.type = "button";
    tentar.className = "btn";
    tentar.textContent = "Tentar de novo";
    tentar.addEventListener("click", () => location.reload());
    const det = document.createElement("a");
    det.className = "btn";
    det.href = "./despesas.html#detalhe";
    det.textContent = "Abrir o Detalhamento";
    acoes.replaceChildren(...botoes, det, tentar);
    $("ex-falha").hidden = false;
    $("ex-falha").setAttribute("role", "alert");
    $("ex-resultado").hidden = true;
    $("ex-controles").hidden = true;
  }

  async function baixarCuboCsv(m, botao) {
    const antes = botao.textContent;
    botao.disabled = true;
    botao.textContent = `Baixando ${m.ano}…`;
    try {
      const r = await fetch("./" + m.arquivo, { cache: "no-cache" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const c = await r.json();
      const d = c.dicionario, C = c.campos;
      const i = (campo) => C.indexOf(campo);
      const linhas = c.linhas.map((l) => {
        const fav = d.favorecido[l[i("favorecido")]] || [];
        return [c.ano, l[0], `${c.ano}-${String(l[0]).padStart(2, "0")}`, d.unidade_gestora[l[i("unidade_gestora")]] ?? "",
          d.tipo[l[i("tipo")]] ?? "", fav[0] ?? "", fav[1] ?? "", fav[2] ?? "",
          d.funcao[l[i("funcao")]] ?? "", d.subfuncao[l[i("subfuncao")]] ?? "", d.programa[l[i("programa")]] ?? "",
          d.elemento_despesa[l[i("elemento_despesa")]] ?? "", d.fonte_recurso[l[i("fonte_recurso")]] ?? "",
          d.grupo_despesa[l[i("grupo_despesa")]] ?? "", l[i("pago")], l[i("n")]];
      });
      Comum.exportarCsv(`pagamentos-${c.ano}-cubo.csv`, COLUNAS_SQL.map(([nome]) => nome), linhas);
      botao.textContent = antes;
    } catch (e) {
      botao.textContent = antes;
      Comum.toast(`Não foi possível baixar o cubo de ${m.ano} (${e.message}).`);
    } finally {
      botao.disabled = false;
    }
  }

  // ── Início ────────────────────────────────────────────────────────────────
  async function iniciar() {
    // o worker sai já: baixar e conferir a biblioteca corre junto com o índice
    criarWorker();
    try {
      const r = await fetch("./despesas-index.json", { cache: "no-cache" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      INDICE = await r.json();
    } catch (e) {
      status("Não foi possível carregar o índice de despesas.");
      Comum.estadoErro(criarAreaErro(), "Não foi possível carregar o índice da Base de Despesas. Verifique a conexão.",
        () => location.reload());
      return;
    }
    if (INDICE.dados_ate) {
      $("ex-dados-ate").textContent = "Pagamentos publicados até " +
        new Date(INDICE.dados_ate.slice(0, 10) + "T12:00:00").toLocaleDateString("pt-BR") + ".";
    }
    if (!INDICE.cubos || !INDICE.cubos.length) {   // export anterior ao explorador
      falhou = true;
      if (worker) { worker.terminate(); worker = null; }
      status("O explorador ainda não tem dados publicados.");
      $("ex-falha-titulo").textContent = "Os pagamentos ainda não foram publicados para o explorador";
      $("ex-falha-motivo").textContent = "Os cubos de pagamentos saem na atualização diária da Base de Despesas; " +
        "a próxima atualização publica os arquivos. Enquanto isso, a mesma base está no Detalhamento do Radar de Despesas.";
      $("ex-falha").querySelector("p:not(#ex-falha-motivo)").hidden = true;
      avisoAlternativas(false);
      return;
    }
    const links = $("ex-json-links");
    links.replaceChildren(" (JSON: ", ...[...INDICE.cubos].sort((a, b) => b.ano - a.ano).flatMap((m, k) => {
      const a = document.createElement("a");
      a.href = "./" + m.arquivo;
      a.textContent = String(m.ano);
      return k ? [", ", a] : [a];
    }), ")");
    estado = lerEstado();
    renderControles();
    ligarControles();
    ligarTabela();
    ligarSql();
    workerPronto.then((info) => {
      try { performance.measure("explorador:sqlite", { start: T0, end: performance.now() }); } catch (x) { /* idem */ }
      console.info(`explorador: SQLite ${info.versao} (biblioteca ${Math.round(info.ms_baixar)} ms, início ${Math.round(info.ms_iniciar)} ms)`);
    }, mostrarFalha);
    // favorecidos dos filtros vindos da URL: o chip mostra o nome assim que a tabela existir
    const favs = estado.filtros.filter((f) => f.dim === "favorecido" && f.valor);
    await atualizar();
    if (favs.length && !falhou) {
      try {
        const r = await pedir("consultar", { sql: `SELECT chave_favorecido, MAX(favorecido) FROM pagamentos WHERE chave_favorecido IN (` +
          favs.map((f) => lit(f.valor)).join(", ") + ") GROUP BY 1" });
        r.linhas.forEach(([k, nome]) => nomesFav.set(k, nome));
        renderChips();
        if (modelo) renderTabela();
      } catch (e) { /* o chip fica com a chave */ }
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
