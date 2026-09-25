-- Typed, deduplicated order grain. One row per order_id.
CREATE TABLE IF NOT EXISTS staging.orders (
    order_id              TEXT NOT NULL,
    customer_id           TEXT,
    restaurant_id         TEXT,
    driver_id             TEXT,
    city                  TEXT,
    created_at            TIMESTAMP,
    promised_eta          TIMESTAMP,
    pickup_at             TIMESTAMP,
    actual_delivery_at    TIMESTAMP,
    final_status_raw      TEXT,
    final_status          TEXT,
    distance_km_estimate  NUMERIC,
    traffic_bucket        TEXT,
    weather_bucket        TEXT,
    had_conflicting_dupe  BOOLEAN NOT NULL DEFAULT FALSE,
    run_date              DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_staging_orders_run ON staging.orders (run_date);

-- Rejected rows are never deleted. They are moved here with a reason so the volume and the
-- nature of what we dropped stays visible and trendable instead of vanishing silently.
CREATE TABLE IF NOT EXISTS staging.quarantine_orders (
    order_id       TEXT,
    reason_code    TEXT NOT NULL,
    reason_detail  TEXT,
    payload        JSONB,
    run_date       DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_quarantine_orders_run ON staging.quarantine_orders (run_date);
