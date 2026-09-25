-- Every run gets a run_id. Every step of every run writes one row here.
-- This is what makes "did last night's run actually work?" answerable without reading logs.
CREATE TABLE IF NOT EXISTS meta.run_log (
    run_log_id   BIGSERIAL PRIMARY KEY,
    run_id       TEXT        NOT NULL,
    run_date     DATE        NOT NULL,
    step         TEXT        NOT NULL,
    status       TEXT        NOT NULL CHECK (status IN ('STARTED','OK','FAILED','SKIPPED','DEGRADED')),
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at     TIMESTAMPTZ,
    duration_ms  INTEGER,
    rows_in      INTEGER,
    rows_out     INTEGER,
    detail       TEXT,
    error_text   TEXT
);
CREATE INDEX IF NOT EXISTS ix_run_log_run    ON meta.run_log (run_id);
CREATE INDEX IF NOT EXISTS ix_run_log_date   ON meta.run_log (run_date);

-- Retrieval completeness evidence: what we pulled, from where, how much, and its checksum.
-- Reconciliation compares rows_expected vs rows_landed; a mismatch fails the run.
CREATE TABLE IF NOT EXISTS meta.source_manifest (
    manifest_id     BIGSERIAL PRIMARY KEY,
    run_id          TEXT        NOT NULL,
    run_date        DATE        NOT NULL,
    source_name     TEXT        NOT NULL,
    retrieval_mode  TEXT        NOT NULL CHECK (retrieval_mode IN ('sql','file','file_nested','api')),
    uri             TEXT        NOT NULL,
    rows_expected   INTEGER,
    rows_landed     INTEGER     NOT NULL,
    sha256          TEXT,
    http_statuses   TEXT,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    detail          TEXT
);
CREATE INDEX IF NOT EXISTS ix_manifest_run ON meta.source_manifest (run_id);

-- Validation outcomes are data, not log lines, so the gate is queryable and trendable.
-- UNKNOWN is a first-class status: the check could not be evaluated at current coverage.
CREATE TABLE IF NOT EXISTS meta.validation_results (
    result_id    BIGSERIAL PRIMARY KEY,
    run_id       TEXT        NOT NULL,
    run_date     DATE        NOT NULL,
    rule_id      TEXT        NOT NULL,
    severity     TEXT        NOT NULL CHECK (severity IN ('FAIL','WARN','UNKNOWN')),
    status       TEXT        NOT NULL CHECK (status IN ('PASS','WARN','FAIL','UNKNOWN')),
    scope        TEXT        NOT NULL,
    observed     NUMERIC,
    threshold    NUMERIC,
    detail       TEXT,
    owner        TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_validation_run ON meta.validation_results (run_id);
