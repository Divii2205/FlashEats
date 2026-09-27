-- Published KPI output. Long format (one row per metric per definition) so a new metric or a new
-- definition variant does not require a schema change.
CREATE TABLE IF NOT EXISTS metrics.kpi (
    metric_id     TEXT NOT NULL,
    metric_name   TEXT NOT NULL,
    definition    TEXT NOT NULL,
    segment       TEXT NOT NULL DEFAULT 'ALL',
    value         NUMERIC,
    unit          TEXT,
    numerator     NUMERIC,
    denominator   NUMERIC,
    caveat        TEXT,
    run_date      DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_metrics_kpi_run ON metrics.kpi (run_date);
