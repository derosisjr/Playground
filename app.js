const sampleAgenda = `SESSAO ORDINARIA - 08/04/2026

PROJETO DE LEI 123/2026 - Autor: Poder Executivo - Institui mutirao municipal de exames e consultas especializadas para reduzir a fila de espera na rede publica.
REQUERIMENTO 44/2026 - Autor: Vereador Carlos Silva - Solicita informacoes detalhadas sobre o cronograma das obras de drenagem e pavimentacao no bairro Jardim Esperanca.
INDICACAO 88/2026 - Autor: Vereadora Ana Souza - Indica ao Executivo reforco da iluminacao publica e poda de arvores no entorno da Escola Municipal Rui Barbosa.
PROJETO DE RESOLUCAO 11/2026 - Autor: Mesa Diretora - Reorganiza o rito de uso da tribuna popular e atualiza regras de participacao social.
MOCAO 09/2026 - Autor: Vereador Marcos Lima - Apresenta mocao de aplauso aos agentes comunitarios de saude pelo trabalho de vacinacao nos bairros.`;

const agendaInput = document.querySelector("#agendaInput");
const generateButton = document.querySelector("#generateButton");
const loadSampleButton = document.querySelector("#loadSampleButton");
const fileInput = document.querySelector("#fileInput");
const councilorNameInput = document.querySelector("#councilorName");
const mandateFocusInput = document.querySelector("#mandateFocus");
const sessionStatus = document.querySelector("#sessionStatus");
const summaryCards = document.querySelector("#summaryCards");
const politicalRead = document.querySelector("#politicalRead");
const itemsList = document.querySelector("#itemsList");
const briefingOutput = document.querySelector("#briefingOutput");

loadSampleButton.addEventListener("click", () => {
  agendaInput.value = sampleAgenda;
  runAnalysis();
});

generateButton.addEventListener("click", () => {
  runAnalysis();
});

fileInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];

  if (!file) {
    return;
  }

  const text = await file.text();
  agendaInput.value = text;
  runAnalysis();
});

function runAnalysis() {
  const rawText = agendaInput.value.trim();

  if (!rawText) {
    sessionStatus.textContent = "Pauta vazia";
    renderEmpty();
    return;
  }

  const councilorName = councilorNameInput.value.trim() || "Vereador(a)";
  const mandateFocus = mandateFocusInput.value
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);

  const items = parseAgenda(rawText);
  const analyzedItems = items.map((item) => analyzeItem(item, mandateFocus));
  const summary = buildSummary(analyzedItems, councilorName, mandateFocus);

  renderSummary(summary);
  renderItems(analyzedItems);
  renderBriefing(summary, analyzedItems, councilorName);
}

function parseAgenda(rawText) {
  return rawText
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => /(PROJETO|REQUERIMENTO|INDICACAO|MOC(?:AO|ÃO))/i.test(line))
    .map((line, index) => {
      const typeMatch = line.match(
        /(PROJETO DE LEI|PROJETO DE RESOLUCAO|REQUERIMENTO|INDICACAO|MOC(?:AO|ÃO))/i
      );
      const numberMatch = line.match(/(\d+\/\d{4})/);
      const authorMatch = line.match(/Autor:\s*([^-]+)/i);
      const theme = line.split("-").slice(2).join("-").trim() || line;

      return {
        id: index + 1,
        raw: line,
        type: normalizeType(typeMatch?.[1] || "Materia"),
        number: numberMatch?.[1] || "s/n",
        author: authorMatch?.[1]?.trim() || "Autor nao identificado",
        theme,
      };
    });
}

function normalizeType(type) {
  const upperType = type.toUpperCase();

  if (upperType.includes("PROJETO DE LEI")) {
    return "Projeto de Lei";
  }

  if (upperType.includes("PROJETO DE RESOLUCAO")) {
    return "Projeto de Resolucao";
  }

  if (upperType.includes("REQUERIMENTO")) {
    return "Requerimento";
  }

  if (upperType.includes("INDICACAO")) {
    return "Indicacao";
  }

  if (upperType.includes("MOC")) {
    return "Mocao";
  }

  return type.replace(/\s+/g, " ").trim();
}

function analyzeItem(item, mandateFocus) {
  const text = `${item.type} ${item.theme}`.toLowerCase();
  const tags = [];
  let priority = "Media";
  let impact = "Impacto localizado";

  if (includesAny(text, ["saude", "consulta", "exames", "hospital"])) {
    tags.push("Saude");
    priority = "Alta";
    impact = "Impacto direto em atendimento ao cidadao";
  }

  if (includesAny(text, ["bairro", "pavimentacao", "drenagem", "iluminacao", "poda", "zeladoria"])) {
    tags.push("Territorio");
  }

  if (includesAny(text, ["transparencia", "informacoes", "cronograma"])) {
    tags.push("Fiscalizacao");
    priority = priority === "Alta" ? "Alta" : "Media-Alta";
  }

  if (includesAny(text, ["tribuna", "participacao social", "mesa diretora"])) {
    tags.push("Rito da Camara");
    impact = "Pode gerar repercussao politica e institucional";
  }

  if (includesAny(text, ["aplauso", "homenagem"])) {
    tags.push("Simbolico");
    priority = "Baixa";
    impact = "Baixo risco, valor de relacionamento";
  }

  const matchedFocus = mandateFocus.filter((focus) => text.includes(focus));

  if (matchedFocus.length) {
    tags.push("Alinhado ao mandato");
  }

  if (!tags.length) {
    tags.push("Monitorar");
  }

  return {
    ...item,
    tags,
    matchedFocus,
    priority,
    impact,
    summary: summarizeTheme(item.theme),
    suggestedPosition: buildSuggestedPosition(item, tags, matchedFocus),
    shortSpeech: buildSpeech(item, "short"),
    mediumSpeech: buildSpeech(item, "medium"),
  };
}

function includesAny(text, terms) {
  return terms.some((term) => text.includes(term));
}

function summarizeTheme(theme) {
  if (theme.length <= 140) {
    return theme;
  }

  return `${theme.slice(0, 137)}...`;
}

function buildSuggestedPosition(item, tags, matchedFocus) {
  if (tags.includes("Fiscalizacao")) {
    return "Cobrar prazo, dados e execucao concreta antes de encerrar a discussao.";
  }

  if (tags.includes("Saude")) {
    return "Defender urgencia, foco no usuario do SUS e monitoramento publico da fila.";
  }

  if (tags.includes("Territorio")) {
    return "Relacionar a materia com demandas reais dos bairros e cobrar calendario de entrega.";
  }

  if (matchedFocus.length) {
    return "Aproximar a fala das prioridades do mandato e mostrar consistencia com pautas anteriores.";
  }

  return "Manter posicionamento objetivo, registrando apoio ou ressalvas com base no impacto local.";
}

function buildSpeech(item, size) {
  const prefix =
    size === "short"
      ? "Fala curta:"
      : "Fala media:";

  if (item.tags.includes("Saude")) {
    return `${prefix} esta materia toca uma dor concreta da populacao. O foco precisa ser reduzir fila, garantir transparencia e mostrar quando o servico vai chegar na ponta.`;
  }

  if (item.tags.includes("Fiscalizacao")) {
    return `${prefix} nao basta anunciar obra ou acao. O gabinete vai cobrar cronograma, prazo, custo e resultado real para cada bairro afetado.`;
  }

  if (item.tags.includes("Rito da Camara")) {
    return `${prefix} alteracoes institucionais exigem cuidado. Vale defender participacao social, previsibilidade e respeito ao papel do plenario.`;
  }

  if (item.tags.includes("Simbolico")) {
    return `${prefix} reconhecer quem entrega servico a cidade e importante, mas sem perder de vista os desafios concretos que ainda precisam de resposta.`;
  }

  return `${prefix} esta pauta merece avaliacao pratica: quem sera beneficiado, quando o efeito aparece e como a populacao vai acompanhar a execucao.`;
}

function buildSummary(items, councilorName, mandateFocus) {
  const highPriorityCount = items.filter((item) => item.priority === "Alta").length;
  const oversightCount = items.filter((item) => item.tags.includes("Fiscalizacao")).length;
  const mandateMatches = items.filter((item) => item.matchedFocus.length > 0).length;

  let openingTone = `${councilorName} chega a sessao com ${items.length} materias mapeadas`;

  if (highPriorityCount > 0) {
    openingTone += `, incluindo ${highPriorityCount} tema(s) de alta urgencia.`;
  } else {
    openingTone += ", sem materia explosiva, mas com pontos de monitoramento.";
  }

  const focusText = mandateFocus.length
    ? `Ha aderencia direta com as prioridades do mandato em ${mandateMatches} item(ns).`
    : "As prioridades do mandato ainda nao foram definidas neste briefing.";

  const oversightText =
    oversightCount > 0
      ? `Vale preparar cobranca objetiva em ${oversightCount} item(ns) de fiscalizacao.`
      : "A sessao pede mais posicionamento politico do que cobranca tecnica.";

  return {
    totalItems: items.length,
    highPriorityCount,
    oversightCount,
    mandateMatches,
    politicalRead: `${openingTone} ${focusText} ${oversightText}`,
  };
}

function renderSummary(summary) {
  sessionStatus.textContent = `${summary.totalItems} itens lidos`;
  politicalRead.textContent = summary.politicalRead;

  summaryCards.innerHTML = `
    <article class="summary-card">
      <p class="meta-label">Materias</p>
      <strong>${summary.totalItems}</strong>
    </article>
    <article class="summary-card">
      <p class="meta-label">Alta urgencia</p>
      <strong>${summary.highPriorityCount}</strong>
    </article>
    <article class="summary-card">
      <p class="meta-label">Fiscalizacao</p>
      <strong>${summary.oversightCount}</strong>
    </article>
  `;
}

function renderItems(items) {
  if (!items.length) {
    itemsList.className = "items-list empty-state";
    itemsList.textContent = "Nenhuma materia reconhecida no texto informado.";
    return;
  }

  itemsList.className = "items-list";
  itemsList.innerHTML = items
    .map(
      (item) => `
        <article class="item-card">
          <header>
            <div>
              <p class="meta-label">${item.type}</p>
              <h3 class="item-title">${item.number} - ${item.summary}</h3>
            </div>
            <span class="tag ${item.priority === "Alta" ? "tag-warning" : "tag-success"}">${item.priority}</span>
          </header>
          <div class="item-meta">
            <span class="tag">Autor: ${item.author}</span>
            <span class="tag">${item.impact}</span>
          </div>
          <p>${item.suggestedPosition}</p>
          <div class="item-tags">
            ${item.tags.map((tag) => `<span class="tag">${tag}</span>`).join("")}
          </div>
        </article>
      `
    )
    .join("");
}

function renderBriefing(summary, items, councilorName) {
  if (!items.length) {
    briefingOutput.innerHTML = `
      <p>Sem itens validos para briefing.</p>
    `;
    return;
  }

  const firstPriorityItem =
    items.find((item) => item.priority === "Alta") || items[0];
  const oversightItem =
    items.find((item) => item.tags.includes("Fiscalizacao")) || items[0];

  briefingOutput.innerHTML = `
    <article class="speech-card">
      <p class="meta-label">Mensagem de abertura</p>
      <h3>Tom sugerido para ${councilorName}</h3>
      <p>${summary.politicalRead}</p>
    </article>
    <article class="speech-card">
      <p class="meta-label">Fala curta</p>
      <h3>${firstPriorityItem.type} ${firstPriorityItem.number}</h3>
      <p>${firstPriorityItem.shortSpeech}</p>
    </article>
    <article class="speech-card">
      <p class="meta-label">Fala media</p>
      <h3>${oversightItem.type} ${oversightItem.number}</h3>
      <p>${oversightItem.mediumSpeech}</p>
    </article>
    <article class="speech-card">
      <p class="meta-label">Pontos de atencao</p>
      <p>
        Priorize o que afeta servico na ponta, cobre prazo sempre que houver
        execucao do Executivo e transforme temas de bairro em exemplos concretos
        durante a fala.
      </p>
    </article>
  `;
}

function renderEmpty() {
  summaryCards.innerHTML = "";
  politicalRead.textContent =
    "Nenhuma pauta processada ainda. Carregue um exemplo para ver a leitura do dia.";
  itemsList.className = "items-list empty-state";
  itemsList.textContent = "Nenhum item processado ainda.";
  briefingOutput.innerHTML = `
    <p>O briefing aparecera aqui com fala curta, fala media e pontos de atencao assim que a pauta for analisada.</p>
  `;
}
