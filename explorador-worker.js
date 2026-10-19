// Explorador de pagamentos — SQLite-WASM num Web Worker (módulo, mesma origem).
// A thread principal só manda pedidos e recebe resultados pequenos; baixar o cubo,
// montar a tabela e rodar as consultas acontece aqui (no M0: 0,9–1,2 s de montagem sem
// nenhuma tarefa longa na página).
//
// Integridade da biblioteca. `import()` de um CDN não aceita SRI; então cada arquivo do
// pacote @sqlite.org/sqlite-wasm, numa versão EXATA (3.53.4-build1, publicada no npm em
// 2026-09-08), é baixado com `fetch(url, { integrity })` — o navegador confere o SHA-384
// e recusa o arquivo se não bater (os hashes são os do .tgz do npm, conferido contra o
// `integrity` do registro; o jsDelivr serve os mesmos bytes). O módulo conferido vira um
// Blob URL para o `import()`, e o .wasm conferido entra como `wasmBinary`: a biblioteca
// não baixa mais nada sozinha (`locateFile` só evita resolver caminho relativo a blob:).
// Trocar de versão = atualizar VERSAO_SQLITE e os dois hashes juntos.
"use strict";

const VERSAO_SQLITE = "3.53.4-build1";
const CDN = `https://cdn.jsdelivr.net/npm/@sqlite.org/sqlite-wasm@${VERSAO_SQLITE}/dist/`;
const SRI = {
  "index.mjs": "sha384-j+gbV/w2zeGv9WgmsnVPrKK5J4gE96kxDRDMpGJTnRgI68fZrprxhjFdcuoaGIdC",
  "sqlite3.wasm": "sha384-zML1l9maR5lcyboDPcoNcYzQnFUv0o9WvMB8Pn16kfu9F+YX+62NQVuTzV0f3/07",
};

// Guarda das consultas digitadas ("Ver SQL"): só SELECT/WITH, um comando, leitura
// (sqlite3_stmt_readonly + PRAGMA query_only), no máximo LIMITE_LINHAS linhas devolvidas.
// O teto de 10 s fica na página (termina este worker e cria outro). Os tetos de memória
// seguram consultas que gerariam texto ou resultado gigante antes dos 10 s.
const LIMITE_LINHAS = 5000;
const LIMITE_TEXTO = 2000;              // caracteres por célula devolvida à página
const LIMITE_SQL = 20000;               // caracteres da consulta
const TETO_HEAP = 256 * 1024 * 1024;    // PRAGMA hard_heap_limit (o banco inteiro tem ~20 MB)
const TETO_VALOR = 16 * 1024 * 1024;    // SQLITE_LIMIT_LENGTH: maior texto/blob (o cubo tem ~2 MB)

let sqlite3 = null;
let db = null;
let prontoSqlite = null;     // promessa da inicialização (os pedidos esperam por ela)
const anos = new Map();      // ano → {linhas, pago}

// Tabela que a página e as consultas veem. Cada linha soma os pagamentos (documentos da
// fase P) iguais em todas as dimensões dentro do mês: SUM(n) conta documentos.
const ESQUEMA = `CREATE TABLE pagamentos (
  ano INTEGER NOT NULL,          -- ano do pagamento
  mes INTEGER NOT NULL,          -- mês do pagamento (1 a 12)
  periodo TEXT NOT NULL,         -- 'AAAA-MM'
  unidade_gestora TEXT,          -- Prefeitura, CAPEP, IPS, fundações
  tipo TEXT,                     -- Orçamentário, Restos a pagar, Extra-orçamentário, Empenho não localizado na base
  chave_favorecido TEXT,         -- identidade do favorecido (CNPJ; CPF mascarado + nome)
  favorecido TEXT,               -- nome de exibição
  documento TEXT,                -- CNPJ ou CPF mascarado, como a origem publica
  funcao TEXT, subfuncao TEXT, programa TEXT,
  elemento TEXT, fonte TEXT, grupo TEXT,
  pago REAL NOT NULL,            -- R$ (soma; anulações entram negativas)
  n INTEGER NOT NULL             -- nº de documentos de pagamento
)`;
// cubo: [mes, unidade_gestora, tipo, favorecido, funcao, subfuncao, programa, elemento_despesa,
// fonte_recurso, grupo_despesa, pago, n] — colunas 1..9 são índices no dicionário
const DIC = ["unidade_gestora", "tipo", "favorecido", "funcao", "subfuncao", "programa",
             "elemento_despesa", "fonte_recurso", "grupo_despesa"];

async function baixarVerificado(arquivo) {
  const r = await fetch(CDN + arquivo, { integrity: SRI[arquivo], credentials: "omit", referrerPolicy: "no-referrer" });
  if (!r.ok) throw new Error(`${arquivo}: HTTP ${r.status}`);
  return r.arrayBuffer();
}

async function iniciar() {
  const t0 = performance.now();
  let codigo, wasm;
  try {
    [codigo, wasm] = await Promise.all([baixarVerificado("index.mjs"), baixarVerificado("sqlite3.wasm")]);
  } catch (e) {
    throw Object.assign(new Error("biblioteca SQLite indisponível ou não conferiu com o hash publicado (" +
      (e && e.message || e) + ")"), { codigo: "cdn" });
  }
  const t1 = performance.now();
  const url = URL.createObjectURL(new Blob([codigo], { type: "text/javascript" }));
  let mod;
  try { mod = await import(url); } finally { URL.revokeObjectURL(url); }
  sqlite3 = await mod.default({ print: () => {}, printErr: () => {}, wasmBinary: wasm, locateFile: (f) => CDN + f });
  db = new sqlite3.oo1.DB(":memory:", "c");
  const capi = sqlite3.capi;
  capi.sqlite3_limit(db.pointer, capi.SQLITE_LIMIT_LENGTH, TETO_VALOR);
  capi.sqlite3_limit(db.pointer, capi.SQLITE_LIMIT_SQL_LENGTH, 1024 * 1024);
  db.exec(`PRAGMA hard_heap_limit = ${TETO_HEAP}; PRAGMA temp_store = MEMORY;`);
  db.exec(ESQUEMA);
  db.exec("PRAGMA query_only = 1");
  return { versao: sqlite3.version.libVersion, ms_baixar: t1 - t0, ms_iniciar: performance.now() - t1 };
}

// Monta o ano na tabela: o JSON vai inteiro para o SQLite (jsonb uma vez, json_each nas
// linhas e nos dicionários) — sem decodificar 30 mil linhas em JS nem atravessar a fronteira
// JS↔WASM coluna a coluna (no M0 o INSERT com bind por linha levava 0,9 s).
async function carregar({ id, ano, url, esperado }) {
  const t0 = performance.now();
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status} em ${url}`), { codigo: "dados" });
  const texto = await r.text();
  const t1 = performance.now();
  await prontoSqlite;          // o download do cubo corre junto com o da biblioteca
  const t2 = performance.now();
  postMessage({ op: "etapa", id, etapa: "montando" });
  db.exec("PRAGMA query_only = 0");
  try {
    db.exec("BEGIN");
    try {
      db.exec({ sql: "DELETE FROM pagamentos WHERE ano = ?", bind: [ano] });
      db.exec("CREATE TEMP TABLE src (j BLOB)");
      db.exec({ sql: "INSERT INTO src VALUES (jsonb(?))", bind: [texto] });
      const cab = db.exec({ sql: "SELECT j->>'$.versao', j->>'$.ano', json_array_length(j, '$.linhas') FROM src",
                            rowMode: "array", returnValue: "resultRows" })[0];
      if (cab[0] !== 1 || cab[1] !== ano) throw new Error(`cubo inesperado (versão ${cab[0]}, ano ${cab[1]})`);
      for (const c of DIC) {
        const extra = c === "favorecido" ? ", nome TEXT, doc TEXT" : "";
        db.exec(`CREATE TEMP TABLE "d_${c}" (i INTEGER PRIMARY KEY, v TEXT${extra})`);
        db.exec(c === "favorecido"
          ? `INSERT INTO "d_${c}" SELECT key, value->>0, value->>1, value->>2 FROM src, json_each(src.j, '$.dicionario.favorecido')`
          : `INSERT INTO "d_${c}" SELECT key, value FROM src, json_each(src.j, '$.dicionario.${c}')`);
      }
      // cada linha vira jsonb UMA vez (CTE materializada) antes das 12 extrações: 170 ms
      // contra 255 ms extraindo do texto de cada linha (medido a 1×, 29,7 mil linhas)
      db.exec(`CREATE TEMP TABLE f AS WITH r(v) AS MATERIALIZED (SELECT jsonb(value) FROM src, json_each(src.j, '$.linhas'))
        SELECT v->>0 mes, v->>1 ug, v->>2 tp, v->>3 fv, v->>4 fn, v->>5 sf, v->>6 pr, v->>7 el, v->>8 fo, v->>9 gr,
          v->>10 pago, v->>11 n FROM r`);
      db.exec({ sql: `INSERT INTO pagamentos SELECT ?1, f.mes, printf('%04d-%02d', ?1, f.mes), ug.v, tp.v,
          fv.v, fv.nome, fv.doc, fn.v, sf.v, pr.v, el.v, fo.v, gr.v, f.pago, f.n
        FROM f JOIN d_unidade_gestora ug ON ug.i = f.ug JOIN d_tipo tp ON tp.i = f.tp
          JOIN d_favorecido fv ON fv.i = f.fv JOIN d_funcao fn ON fn.i = f.fn JOIN d_subfuncao sf ON sf.i = f.sf
          JOIN d_programa pr ON pr.i = f.pr JOIN d_elemento_despesa el ON el.i = f.el
          JOIN d_fonte_recurso fo ON fo.i = f.fo JOIN d_grupo_despesa gr ON gr.i = f.gr`, bind: [ano] });
      const [linhas, pago, nf] = db.exec({ sql: "SELECT COUNT(*), ROUND(SUM(pago), 2), (SELECT COUNT(*) FROM f) FROM pagamentos WHERE ano = ?",
                                            bind: [ano], rowMode: "array", returnValue: "resultRows" })[0];
      // índice fora do dicionário perderia a linha no JOIN: a contagem e o pago têm de fechar
      if (linhas !== nf || linhas !== cab[2]) throw new Error(`montagem incompleta (${linhas} de ${cab[2]} linhas)`);
      if (esperado && (linhas !== esperado.linhas || Math.abs(pago - esperado.pago) > 0.005)) {
        throw new Error(`o cubo não confere com o índice (${linhas} linhas, R$ ${pago} × ${esperado.linhas}, R$ ${esperado.pago})`);
      }
      db.exec("COMMIT");
      anos.set(ano, { linhas, pago });
      return { ano, linhas, pago, bytes: texto.length, ms_baixar: t1 - t0, ms_espera: t2 - t1, ms_montar: performance.now() - t2 };
    } catch (e) {
      db.exec("ROLLBACK");
      throw Object.assign(e, { codigo: e.codigo || "dados" });
    } finally {
      db.exec("DROP TABLE IF EXISTS temp.src; DROP TABLE IF EXISTS temp.f;" +
        DIC.map((c) => `DROP TABLE IF EXISTS temp."d_${c}";`).join(""));
    }
  } finally {
    db.exec("PRAGMA query_only = 1");
  }
}

// Consulta: devolve nomes das colunas e linhas (arrays); textos longos cortados.
function executar(sql, limite) {
  const t0 = performance.now();
  const stmt = db.prepare(sql);
  const linhas = [];
  let truncado = false;
  try {
    const colunas = stmt.getColumnNames();
    while (stmt.step()) {
      if (linhas.length >= limite) { truncado = true; break; }
      const l = stmt.get([]);
      for (let i = 0; i < l.length; i++) {
        const v = l[i];
        if (typeof v === "string" && v.length > LIMITE_TEXTO) l[i] = v.slice(0, LIMITE_TEXTO) + "…";
        else if (typeof v === "bigint") l[i] = Number(v);
        else if (v instanceof Uint8Array) l[i] = `[blob de ${v.length} bytes]`;
      }
      linhas.push(l);
    }
    return { colunas, linhas, truncado, ms: performance.now() - t0 };
  } finally {
    stmt.finalize();
  }
}

// Comentários e espaços no início não contam para "começa com SELECT/WITH"
const INICIO = /^(?:\s+|--[^\n]*(?:\n|$)|\/\*[\s\S]*?\*\/)*/;

// Conta os comandos com o próprio analisador do SQLite (prepare_v3 + pzTail): "SELECT 1;
// DROP TABLE x" tem dois — o oo1 prepara só o primeiro e ignoraria o resto em silêncio.
function analisar(sql) {
  const { wasm, capi } = sqlite3;
  const pilha = wasm.scopedAllocPush();
  try {
    let n = wasm.jstrlen(sql);
    const ppStmt = wasm.scopedAlloc(2 * wasm.ptr.size + n + 1);
    const pzTail = wasm.ptr.add(ppStmt, wasm.ptr.size);
    let pSql = wasm.ptr.add(pzTail, wasm.ptr.size);
    const fim = wasm.ptr.add(pSql, n);
    wasm.jstrcpy(sql, wasm.heap8(), pSql, n, false);
    wasm.poke8(fim, 0);
    let comandos = 0, leitura = true;
    while (pSql && wasm.peek8(pSql)) {
      wasm.pokePtr([ppStmt, pzTail], 0);
      const rc = capi.sqlite3_prepare_v3(db.pointer, pSql, n, 0, ppStmt, pzTail);
      if (rc) return { erro: capi.sqlite3_errmsg(db.pointer) };
      const pStmt = wasm.peekPtr(ppStmt);
      pSql = wasm.peekPtr(pzTail);
      n = Number(wasm.ptr.add(fim, -pSql));
      if (!pStmt) continue;              // só espaço ou comentário
      comandos += 1;
      if (!capi.sqlite3_stmt_readonly(pStmt)) leitura = false;
      capi.sqlite3_finalize(pStmt);
    }
    return { comandos, leitura };
  } finally {
    wasm.scopedAllocPop(pilha);
  }
}

function guarda(msg) { return Object.assign(new Error(msg), { codigo: "guarda" }); }

function consultaDoUsuario(sql) {
  if (typeof sql !== "string" || !sql.trim()) throw guarda("Escreva uma consulta.");
  if (sql.length > LIMITE_SQL) throw guarda(`Consulta longa demais (máximo de ${LIMITE_SQL.toLocaleString("pt-BR")} caracteres).`);
  const corpo = sql.replace(INICIO, "");
  if (!/^(select|with)\b/i.test(corpo)) {
    const palavra = (corpo.match(/^[a-z]+/i) || ["?"])[0].toUpperCase();
    throw guarda(`Só consultas de leitura: comece com SELECT ou WITH (recebido: ${palavra}).`);
  }
  const a = analisar(sql);
  if (a.erro) throw Object.assign(new Error(a.erro), { codigo: "sqlite" });
  if (a.comandos !== 1) throw guarda(`Um comando por vez (a consulta tem ${a.comandos}). Tire o “;” do meio.`);
  if (!a.leitura) throw guarda("Só consultas de leitura são aceitas.");
  return executar(sql, LIMITE_LINHAS);
}

prontoSqlite = iniciar();
prontoSqlite.then(
  (info) => postMessage({ op: "pronto", ok: true, ...info }),
  (e) => postMessage({ op: "pronto", ok: false, erro: String(e && e.message || e), codigo: e && e.codigo || "init" }));
prontoSqlite.catch(() => {});

self.onmessage = async (ev) => {
  const { id, op } = ev.data || {};
  try {
    let resultado;
    if (op === "carregar") resultado = await carregar(ev.data);
    else {
      await prontoSqlite;
      if (op === "consultar") resultado = executar(ev.data.sql, ev.data.limite || 20000);   // SQL montado pela página
      else if (op === "sql") resultado = consultaDoUsuario(ev.data.sql);
      else throw new Error("operação desconhecida: " + op);
    }
    postMessage({ id, ok: true, ...resultado });
  } catch (e) {
    postMessage({ id, ok: false, erro: String(e && e.message || e), codigo: e && e.codigo || "sqlite" });
  }
};
