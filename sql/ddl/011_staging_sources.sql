-- Staging tables for every source other than orders.
-- Orders is built in Python because its duplicate-conflict logic is a business rule that needs to
-- be unit tested; these are declarative normalisations and read better as SQL.

CREATE TABLE IF NOT EXISTS staging.dispatch (
    order_id             TEXT NOT NULL,
    driver_id            TEXT,
    original_driver_id   TEXT,
    assigned_at          TIMESTAMP,
    reassigned_at        TIMESTAMP,
    estimated_pickup_at  TIMESTAMP,
    current_delivery_eta TIMESTAMP,
    dispatch_status      TEXT,
    eta_model_version    TEXT,
    was_reassigned       BOOLEAN,
    run_date             DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS staging.restaurant_status (
    order_id        TEXT NOT NULL,
    restaurant_id   TEXT,
    status_raw      TEXT,
    status          TEXT,
    last_updated_at TIMESTAMP,
    run_date        DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS staging.order_events (
    event_id      TEXT,
    order_id      TEXT NOT NULL,
    event_type    TEXT,
    event_time    TIMESTAMP,
    actor_type    TEXT,
    actor_id      TEXT,
    source_system TEXT,
    run_date      DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS staging.driver_events (
    driver_id  TEXT,
    order_id   TEXT,
    event_type TEXT,
    event_time TIMESTAMP,
    lat        NUMERIC,
    lon        NUMERIC,
    run_date   DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS staging.support_tickets (
    ticket_id        TEXT,
    order_id         TEXT,
    created_at       TIMESTAMP,
    category_raw     TEXT,
    category         TEXT,
    customer_message TEXT,
    is_joinable      BOOLEAN,
    run_date         DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS staging.customer_interactions (
    interaction_id   TEXT,
    order_id         TEXT,
    interaction_type TEXT,
    interaction_at   TIMESTAMP,
    channel          TEXT,
    detail_raw       TEXT,
    detail           TEXT,
    run_date         DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS staging.order_interventions (
    intervention_id   TEXT,
    order_id          TEXT NOT NULL,
    intervention_type TEXT,
    intervention_at   TIMESTAMP,
    initiated_by      TEXT,
    reason            TEXT,
    run_date          DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS staging.customer_app_actions (
    action_id   TEXT,
    order_id    TEXT,
    customer_id TEXT,
    action_type TEXT,
    action_at   TIMESTAMP,
    channel     TEXT,
    run_date    DATE NOT NULL
);

-- The client's own derived outcome file. Staged ONLY so the pipeline can reconcile its
-- independently computed KPI against the number already circulating in the business.
CREATE TABLE IF NOT EXISTS staging.client_order_outcomes (
    order_id          TEXT NOT NULL,
    final_status_norm TEXT,
    delivered_flag    INTEGER,
    late_flag         NUMERIC,
    delay_min         NUMERIC,
    outcome_bucket    TEXT,
    run_date          DATE NOT NULL
);
