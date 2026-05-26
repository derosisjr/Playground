// ── State ─────────────────────────────────────────────────────────────────
let allRows = [];       // parsed CSV rows (objects)
let headers = [];       // original CSV headers
let colMap = {};        // normalized column mapping
let filteredRows = [];  // rows after filters
let sortState = { col: null, dir: 'asc' };

const PAGE_SIZE = 50;
let currentPage = 1;

// Chart instances – keep refs to destroy on redraw
const charts = {};

// ── Column detection ───────────────────────────────────────────────────────
// Maps semantic roles to possible CSV column name patterns (case-insensitive)
const COL_PATTERNS = {
  secretaria: [/secret|org[aã]o|unidade.gest|departamento/i],
  funcao:     [/fun[cç][aã]o|finalidade/i],
  subfuncao:  [/subfun/i],
  natureza:   [/natureza|elemento|categoria.*econ/i],
  credor:     [/favor|credor|nome.*fav|raz[aã]o.soc|fornec/i],
  cnpj:       [/cnpj|cpf/i],
  empenho:    [/empenha|vl.*emp|valor.*emp/i],
  liquidado:  [/liquid/i],
  pago:       [/pag[oa]|realiz/i],
  data:       [/data|dt_/i],
  ano:        [/^ano$|exerc[ií]cio/i],
  numero:     [/n[uú]m|numero.*emp|nr_/i],
  historico:  [/hist[oó]rico|descri|objeto/i],
};

function detectColumns(hdrs) {
  const map = {};
  for (const [role, patterns] of Object.entries(COL_PATTERNS)) {
    for (const h of hdrs) {
      if (patterns.some(p => p.test(h))) {
        map[role] = h;
        break;
      }
    }
  }
  return map;
}

// ── Number helpers ─────────────────────────────────────────────────────────
function parseBRL(str) {
  if (!str) return 0;
  const s = String(str).trim()
    .replace(/[R$\s]/g, '')
    .replace(/\./g, '')
    .replace(',', '.');
  const n = parseFloat(s);
  return isNaN(n) ? 0 : n;
}

function formatBRL(val) {
  return val.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2 });
}

function formatK(val) {
  if (Math.abs(val) >= 1e9) return `R$ ${(val / 1e9).toFixed(1)}B`;
  if (Math.abs(val) >= 1e6) return `R$ ${(val / 1e6).toFixed(1)}M`;
  if (Math.abs(val) >= 1e3) return `R$ ${(val / 1e3).toFixed(0)}K`;
  return formatBRL(val);
}

// ── CSV Upload / Drag & Drop ───────────────────────────────────────────────
const fileInput = document.getElementById('fileInput');
const dropArea  = document.getElementById('dropArea');

fileInput.addEventListener('change', e => {
  const file = e.target.files?.[0];
  if (file) loadFile(file);
});

dropArea.addEventListener('dragover', e => {
  e.preventDefault();
  dropArea.classList.add('drag-over');
});
dropArea.addEventListener('dragleave', () => dropArea.classList.remove('drag-over'));
dropArea.addEventListener('drop', e => {
  e.preventDefault();
  dropArea.classList.remove('drag-over');
  const file = e.dataTransfer.files?.[0];
  if (file) loadFile(file);
});

function loadFile(file) {
  document.getElementById('uploadHint').textContent = `Carregando: ${file.name}…`;
  Papa.parse(file, {
    header: true,
    skipEmptyLines: true,
    encoding: 'UTF-8',
    complete: result => onParsed(result, file.name),
    error: err => alert('Erro ao ler CSV: ' + err.message),
  });
}

function onParsed(result, fileName) {
  headers = result.meta.fields || [];
  colMap  = detectColumns(headers);
  allRows = result.data;

  document.getElementById('uploadHint').textContent = `✓ ${fileName} — ${allRows.length.toLocaleString('pt-BR')} registros`;
  document.getElementById('emptyState').hidden = true;

  // Show UI
  ['kpiBar','filtersBar','chartsGrid','tablePanel'].forEach(id => {
    document.getElementById(id).hidden = false;
  });

  buildFilters();
  applyFilters();
}

// ── Filters ────────────────────────────────────────────────────────────────
function buildFilters() {
  populateSelect('filterSecretaria', colMap.secretaria, 'Todas as secretarias');
  populateSelect('filterFuncao',     colMap.funcao,     'Todas as funções');
  populateSelect('filterAno',        colMap.ano || colMap.data, 'Todos os anos', extractYear);
}

function populateSelect(id, col, placeholder, transform) {
  const sel = document.getElementById(id);
  sel.innerHTML = `<option value="">${placeholder}</option>`;
  if (!col) return;
  const values = [...new Set(allRows.map(r => transform ? transform(r[col]) : r[col]).filter(Boolean))].sort();
  values.forEach(v => {
    const o = document.createElement('option');
    o.value = v;
    o.textContent = v;
    sel.appendChild(o);
  });
}

function extractYear(val) {
  if (!val) return null;
  const m = String(val).match(/\d{4}/);
  return m ? m[0] : null;
}

['filterSecretaria','filterFuncao','filterAno','filterCredor'].forEach(id => {
  document.getElementById(id).addEventListener('input', () => {
    currentPage = 1;
    applyFilters();
  });
});

document.getElementById('resetFilters').addEventListener('click', () => {
  ['filterSecretaria','filterFuncao','filterAno'].forEach(id => {
    document.getElementById(id).value = '';
  });
  document.getElementById('filterCredor').value = '';
  currentPage = 1;
  applyFilters();
});

function applyFilters() {
  const fSec    = document.getElementById('filterSecretaria').value;
  const fFun    = document.getElementById('filterFuncao').value;
  const fAno    = document.getElementById('filterAno').value;
  const fCredor = document.getElementById('filterCredor').value.toLowerCase().trim();

  filteredRows = allRows.filter(r => {
    if (fSec && r[colMap.secretaria] !== fSec) return false;
    if (fFun && r[colMap.funcao] !== fFun) return false;
    if (fAno && extractYear(r[colMap.ano] || r[colMap.data]) !== fAno) return false;
    if (fCredor && colMap.credor) {
      if (!String(r[colMap.credor]).toLowerCase().includes(fCredor)) return false;
    }
    return true;
  });

  renderKPIs();
  renderCharts();
  renderTable();
}

// ── KPIs ───────────────────────────────────────────────────────────────────
function sum(rows, col) {
  return col ? rows.reduce((acc, r) => acc + parseBRL(r[col]), 0) : 0;
}

function renderKPIs() {
  const empenhado = sum(filteredRows, colMap.empenho);
  const pago      = sum(filteredRows, colMap.pago) || sum(filteredRows, colMap.liquidado);
  const secretarias = colMap.secretaria
    ? new Set(filteredRows.map(r => r[colMap.secretaria]).filter(Boolean)).size
    : '—';
  const credores = colMap.credor
    ? new Set(filteredRows.map(r => r[colMap.credor]).filter(Boolean)).size
    : '—';

  document.getElementById('kpiEmpenhado').textContent  = formatK(empenhado);
  document.getElementById('kpiPago').textContent        = formatK(pago);
  document.getElementById('kpiRegistros').textContent   = filteredRows.length.toLocaleString('pt-BR');
  document.getElementById('kpiSecretarias').textContent = secretarias;
  document.getElementById('kpiCredores').textContent    = credores;
}

// ── Charts ─────────────────────────────────────────────────────────────────
const PALETTE = [
  '#0e7490','#2563eb','#7c3aed','#b45309','#15803d',
  '#db2777','#0891b2','#4f46e5','#d97706','#16a34a',
  '#e11d48','#0369a1','#6d28d9','#92400e','#065f46',
];

function groupBySum(rows, groupCol, valueCol) {
  if (!groupCol || !valueCol) return {};
  const map = {};
  rows.forEach(r => {
    const key = r[groupCol]?.trim() || '(sem categoria)';
    map[key] = (map[key] || 0) + parseBRL(r[valueCol]);
  });
  return map;
}

function topN(obj, n) {
  return Object.entries(obj)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n);
}

function makeOrDestroy(id, type, data, options) {
  if (charts[id]) { charts[id].destroy(); }
  const ctx = document.getElementById(id).getContext('2d');
  charts[id] = new Chart(ctx, { type, data, options });
}

const baseOptions = (fmt = formatBRL) => ({
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      callbacks: {
        label: ctx => ' ' + fmt(ctx.parsed.y ?? ctx.parsed ?? 0),
      }
    }
  },
  scales: {
    x: { ticks: { font: { family: 'Manrope', size: 11 } }, grid: { display: false } },
    y: { ticks: { callback: v => formatK(v), font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
  }
});

function renderCharts() {
  chartSecretaria();
  chartFuncao();
  chartCredores();
  chartMensal();
  chartNatureza();
}

function chartSecretaria() {
  const valueCol = colMap.empenho || colMap.pago || colMap.liquidado;
  const grouped = groupBySum(filteredRows, colMap.secretaria, valueCol);
  const entries = topN(grouped, 20);

  makeOrDestroy('chartSecretaria', 'bar', {
    labels: entries.map(([k]) => truncate(k, 40)),
    datasets: [{
      data: entries.map(([, v]) => v),
      backgroundColor: entries.map((_, i) => PALETTE[i % PALETTE.length] + 'cc'),
      borderRadius: 6,
    }]
  }, {
    ...baseOptions(),
    indexAxis: 'y',
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ' ' + formatBRL(ctx.parsed.x) } } },
    scales: {
      x: { ticks: { callback: v => formatK(v), font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      y: { ticks: { font: { family: 'Manrope', size: 11 } }, grid: { display: false } },
    }
  });
}

function chartFuncao() {
  const valueCol = colMap.empenho || colMap.pago || colMap.liquidado;
  const grouped = groupBySum(filteredRows, colMap.funcao, valueCol);
  const entries = topN(grouped, 10);

  makeOrDestroy('chartFuncao', 'doughnut', {
    labels: entries.map(([k]) => truncate(k, 30)),
    datasets: [{
      data: entries.map(([, v]) => v),
      backgroundColor: entries.map((_, i) => PALETTE[i % PALETTE.length]),
      borderWidth: 2,
      borderColor: '#fff',
    }]
  }, {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: true, position: 'right', labels: { font: { family: 'Manrope', size: 11 }, boxWidth: 14 } },
      tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${formatBRL(ctx.parsed)}` } }
    }
  });
}

function chartCredores() {
  const valueCol = colMap.empenho || colMap.pago || colMap.liquidado;
  const grouped = groupBySum(filteredRows, colMap.credor, valueCol);
  const entries = topN(grouped, 10);

  makeOrDestroy('chartCredores', 'bar', {
    labels: entries.map(([k]) => truncate(k, 30)),
    datasets: [{
      data: entries.map(([, v]) => v),
      backgroundColor: PALETTE[1] + 'cc',
      borderRadius: 6,
    }]
  }, {
    ...baseOptions(),
    indexAxis: 'y',
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ' ' + formatBRL(ctx.parsed.x) } } },
    scales: {
      x: { ticks: { callback: v => formatK(v), font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      y: { ticks: { font: { family: 'Manrope', size: 11 } }, grid: { display: false } },
    }
  });
}

function chartMensal() {
  const valueCol = colMap.empenho || colMap.pago || colMap.liquidado;
  const dateCol  = colMap.data;
  if (!dateCol || !valueCol) {
    charts['chartMensal']?.destroy();
    return;
  }

  const map = {};
  filteredRows.forEach(r => {
    const raw = r[dateCol];
    const m = String(raw).match(/(\d{4})[\/\-](\d{2})|(\d{2})[\/\-](\d{2})[\/\-](\d{4})/);
    let label;
    if (m) {
      // ISO yyyy-mm or dd/mm/yyyy
      label = m[1] ? `${m[1]}-${m[2]}` : `${m[5]}-${m[4]}`;
    } else {
      label = String(raw).slice(0, 7);
    }
    if (label) map[label] = (map[label] || 0) + parseBRL(r[valueCol]);
  });

  const sorted = Object.entries(map).sort(([a], [b]) => a.localeCompare(b));

  makeOrDestroy('chartMensal', 'line', {
    labels: sorted.map(([k]) => k),
    datasets: [{
      data: sorted.map(([, v]) => v),
      borderColor: PALETTE[0],
      backgroundColor: PALETTE[0] + '22',
      fill: true,
      tension: 0.35,
      pointRadius: sorted.length > 36 ? 0 : 3,
    }]
  }, baseOptions());
}

function chartNatureza() {
  const valueCol = colMap.empenho || colMap.pago || colMap.liquidado;
  const grouped = groupBySum(filteredRows, colMap.natureza, valueCol);
  const entries = topN(grouped, 12);

  makeOrDestroy('chartNatureza', 'bar', {
    labels: entries.map(([k]) => truncate(k, 35)),
    datasets: [{
      data: entries.map(([, v]) => v),
      backgroundColor: entries.map((_, i) => PALETTE[i % PALETTE.length] + 'bb'),
      borderRadius: 6,
    }]
  }, {
    ...baseOptions(),
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ' ' + formatBRL(ctx.parsed.y) } } },
  });
}

// ── Table ──────────────────────────────────────────────────────────────────
// Columns to show (up to 8, preferring semantic roles)
function getTableColumns() {
  const preferred = ['numero','data','secretaria','funcao','natureza','credor','empenho','pago'];
  const cols = [];
  for (const role of preferred) {
    if (colMap[role]) cols.push({ role, header: colMap[role] });
    if (cols.length >= 8) break;
  }
  if (!cols.length) {
    // Fallback: first 6 headers
    headers.slice(0, 6).forEach(h => cols.push({ role: h, header: h }));
  }
  return cols;
}

function renderTable() {
  const tableCols = getTableColumns();
  const numericRoles = new Set(['empenho','liquidado','pago']);

  // Head
  const thead = document.getElementById('tableHead');
  thead.innerHTML = `<tr>${tableCols.map(c => `<th data-col="${c.header}">${c.header}</th>`).join('')}</tr>`;

  // Sorting
  thead.querySelectorAll('th').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (sortState.col === col) {
        sortState.dir = sortState.dir === 'asc' ? 'desc' : 'asc';
      } else {
        sortState.col = col;
        sortState.dir = 'asc';
      }
      thead.querySelectorAll('th').forEach(t => t.classList.remove('sort-asc','sort-desc'));
      th.classList.add(sortState.dir === 'asc' ? 'sort-asc' : 'sort-desc');
      currentPage = 1;
      renderTableBody(tableCols, numericRoles);
      renderPagination(tableCols, numericRoles);
    });
  });

  renderTableBody(tableCols, numericRoles);
  renderPagination(tableCols, numericRoles);

  document.getElementById('tableCount').textContent =
    `${filteredRows.length.toLocaleString('pt-BR')} registros`;
}

function getSortedRows() {
  if (!sortState.col) return filteredRows;
  const col = sortState.col;
  return [...filteredRows].sort((a, b) => {
    const aVal = parseBRL(a[col]) || a[col] || '';
    const bVal = parseBRL(b[col]) || b[col] || '';
    if (typeof aVal === 'number' && typeof bVal === 'number') {
      return sortState.dir === 'asc' ? aVal - bVal : bVal - aVal;
    }
    return sortState.dir === 'asc'
      ? String(aVal).localeCompare(String(bVal), 'pt-BR')
      : String(bVal).localeCompare(String(aVal), 'pt-BR');
  });
}

function renderTableBody(tableCols, numericRoles) {
  const sorted = getSortedRows();
  const start  = (currentPage - 1) * PAGE_SIZE;
  const page   = sorted.slice(start, start + PAGE_SIZE);
  const tbody  = document.getElementById('tableBody');

  tbody.innerHTML = page.map(row =>
    `<tr>${tableCols.map(c => {
      const raw = row[c.header] ?? '';
      const isNum = numericRoles.has(c.role) && parseBRL(raw) !== 0;
      const display = isNum ? formatBRL(parseBRL(raw)) : raw;
      return `<td class="${isNum ? 'num' : ''}" title="${escHtml(String(raw))}">${escHtml(String(display))}</td>`;
    }).join('')}</tr>`
  ).join('');
}

function renderPagination(tableCols, numericRoles) {
  const total = Math.ceil(getSortedRows().length / PAGE_SIZE);
  const pag   = document.getElementById('pagination');
  if (total <= 1) { pag.innerHTML = ''; return; }

  const pages = pageRange(currentPage, total);
  pag.innerHTML = pages.map(p =>
    p === '…'
      ? `<span style="padding:6px 4px;color:var(--muted)">…</span>`
      : `<button class="page-btn${p === currentPage ? ' active' : ''}" data-p="${p}">${p}</button>`
  ).join('');

  pag.querySelectorAll('.page-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      currentPage = Number(btn.dataset.p);
      renderTableBody(tableCols, numericRoles);
      renderPagination(tableCols, numericRoles);
      document.getElementById('tablePanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

function pageRange(cur, total) {
  const delta = 2;
  const range = [];
  for (let i = Math.max(1, cur - delta); i <= Math.min(total, cur + delta); i++) range.push(i);
  const result = [];
  if (range[0] > 1) { result.push(1); if (range[0] > 2) result.push('…'); }
  result.push(...range);
  if (range[range.length - 1] < total) {
    if (range[range.length - 1] < total - 1) result.push('…');
    result.push(total);
  }
  return result;
}

// ── Export ─────────────────────────────────────────────────────────────────
document.getElementById('exportCsv').addEventListener('click', () => {
  const csv = Papa.unparse(getSortedRows(), { columns: headers });
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url;
  a.download = `gastos-santos-filtrado.csv`;
  a.click();
  URL.revokeObjectURL(url);
});

// ── Utils ──────────────────────────────────────────────────────────────────
function truncate(str, max) {
  return str.length <= max ? str : str.slice(0, max - 1) + '…';
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
