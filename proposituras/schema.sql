-- Base de Proposituras (Câmara Municipal de Santos) — tipo "Projeto"
-- A PK de `proposituras` é o `cod` do documento (detalhes.php?cod={cod}).

CREATE TABLE IF NOT EXISTS proposituras (
    cod              INTEGER PRIMARY KEY,  -- cod do detalhes.php
    tipo             TEXT,                 -- sempre "Projeto" (nesta fase)
    subtipo          TEXT,                 -- "Projeto de Lei", "Projeto de Decreto Legislativo", ...
    numero           TEXT,                 -- ex.: "204/2026"
    ano              INTEGER,
    processo         TEXT,                 -- nº do processo administrativo, quando houver
    data_propositura TEXT,                 -- DD/MM/AAAA
    autor            TEXT,
    ementa           TEXT,
    local_atual      TEXT,                 -- localização atual na Casa (campo "Local")
    situacao         TEXT,                 -- situação atual (campo "Situação" da listagem)
    data_situacao    TEXT,                 -- data do último despacho (da tramitação)
    url_detalhes     TEXT,                 -- detalhes.php?cod={cod}
    url_pdf          TEXT,                 -- PDF do projeto (quando houver)
    fonte            TEXT,                 -- "Câmara Municipal de Santos"
    data_coleta      TEXT                  -- ISO datetime da coleta
);

CREATE TABLE IF NOT EXISTS tramitacao (
    prop_cod    INTEGER,
    ordem       INTEGER,  -- ordem do despacho na página (0 = mais recente)
    data        TEXT,
    local       TEXT,
    despacho    TEXT,
    url_arquivo TEXT,
    PRIMARY KEY (prop_cod, ordem),
    FOREIGN KEY (prop_cod) REFERENCES proposituras(cod)
);

CREATE INDEX IF NOT EXISTS idx_prop_subtipo_ano ON proposituras(subtipo, ano);
CREATE INDEX IF NOT EXISTS idx_prop_autor       ON proposituras(autor);
CREATE INDEX IF NOT EXISTS idx_prop_numero      ON proposituras(numero);
