-- The workflow model.
--
-- Raw systems are organised by SOURCE. This layer reorganises them around the BUSINESS PROCESS:
-- an order moves through stages, actors intervene, and an outcome results. Every metric in the
-- metrics schema reads from here, so the definitions live in one place.

-- ── Dimensions ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS marts.dim_restaurant (
    restaurant_id         TEXT NOT NULL,
    restaurant_name       TEXT,
    cuisine               TEXT,
    lat                   NUMERIC,
    lon                   NUMERIC,
    manual_status_updates BOOLEAN,
    run_date              DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS marts.dim_driver (
    driver_id         TEXT NOT NULL,
    rating            NUMERIC,
    vehicle_type      TEXT,
    experience_months INTEGER,
    experience_band   TEXT,
    run_date          DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS marts.dim_customer (
    customer_id TEXT NOT NULL,
    lat         NUMERIC,
    lon         NUMERIC,
    run_date    DATE NOT NULL
);

-- ── Event fact ──────────────────────────────────────────────────────────────────────────────
-- One row per observed state transition, unioned across three systems that each see part of the
-- journey. source_system is retained because when two systems disagree, knowing who said what is
-- the whole investigation.

CREATE TABLE IF NOT EXISTS marts.fct_order_events (
    order_id      TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    event_time    TIMESTAMP,
    actor_type    TEXT,
    actor_id      TEXT,
    source_system TEXT NOT NULL,
    run_date      DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fct_events_order ON marts.fct_order_events (order_id, run_date);

-- ── Lifecycle fact ──────────────────────────────────────────────────────────────────────────
-- One row per order carrying every stage timestamp, every derived duration, the outcome, and the
-- data-quality flags that qualify it. This is the table the business actually asks questions of.

CREATE TABLE IF NOT EXISTS marts.fct_order_lifecycle (
    order_id              TEXT NOT NULL,
    customer_id           TEXT,
    restaurant_id         TEXT,
    driver_id             TEXT,
    city                  TEXT,
    daypart               TEXT,

    -- stage timestamps, in workflow order
    created_at            TIMESTAMP,
    assigned_at           TIMESTAMP,
    ready_at              TIMESTAMP,
    pickup_at             TIMESTAMP,
    delivered_at          TIMESTAMP,
    promised_eta          TIMESTAMP,

    -- stage durations, in minutes
    dispatch_latency_min  NUMERIC,
    assign_to_pickup_min  NUMERIC,
    idle_wait_min         NUMERIC,
    transit_min           NUMERIC,
    end_to_end_min        NUMERIC,

    -- outcome
    final_status          TEXT,
    delay_min             NUMERIC,
    is_late_strict        BOOLEAN,
    is_late_material      BOOLEAN,
    is_measurable         BOOLEAN,

    -- context
    traffic_bucket        TEXT,
    weather_bucket        TEXT,
    distance_km_estimate  NUMERIC,
    eta_model_version     TEXT,
    was_reassigned        BOOLEAN,

    -- interaction -> intervention -> outcome
    interaction_count     INTEGER,
    complaint_count       INTEGER,
    eta_view_count        INTEGER,
    intervention_count    INTEGER,
    intervention_types    TEXT,

    -- data quality qualifiers travelling with the row
    had_conflicting_dupe  BOOLEAN,
    has_negative_duration BOOLEAN,

    run_date              DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fct_lifecycle_order ON marts.fct_order_lifecycle (order_id, run_date);
CREATE INDEX IF NOT EXISTS ix_fct_lifecycle_run   ON marts.fct_order_lifecycle (run_date);
