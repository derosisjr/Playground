-- Base de Legislação Municipal (LEGIS Santos) — índice enxuto (só metadados)
-- A PK de `normas` é o ID do documento no Legis (/legis/documents/{id}).

CREATE TABLE IF NOT EXISTS normas (
    id          INTEGER PRIMARY KEY,   -- ID do documento no Legis
    tipo        TEXT,                  -- Lei ordinária, Lei complementar, Decreto, ...
    numero      TEXT,                  -- ex.: "4.450"
    ano         INTEGER,
    data_norma  TEXT,                  -- DD/MM/AAAA (best-effort)
    titulo      TEXT,                  -- texto do título (h1) após o "»"
    ementa      TEXT,                  -- descrição longa, quando houver
    tags        TEXT,                  -- temas curtos, separados por "; " (denormalizado)
    situacao    TEXT,                  -- vazio na fase 1 (vigente/revogada vem depois)
    url_legis   TEXT,                  -- /legis/documents/{id}
    url_pdf     TEXT,                  -- /legis/documents/{id}/download
    fonte       TEXT,                  -- "Legis Prefeitura de Santos"
    data_coleta TEXT                   -- ISO datetime da coleta
);

CREATE TABLE IF NOT EXISTS temas (
    norma_id INTEGER,
    tema     TEXT,
    PRIMARY KEY (norma_id, tema),
    FOREIGN KEY (norma_id) REFERENCES normas(id)
);

CREATE INDEX IF NOT EXISTS idx_normas_tipo_ano ON normas(tipo, ano);
CREATE INDEX IF NOT EXISTS idx_normas_numero   ON normas(numero);
