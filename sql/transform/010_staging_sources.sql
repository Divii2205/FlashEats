-- Per-run staging load. Every statement is partition-scoped on :run_date, so a rerun replaces
-- exactly one logical partition. Executed inside the caller's transaction.

-- ── Dispatch (API) ──────────────────────────────────────────────────────────────────────────
DELETE FROM staging.dispatch WHERE run_date = %(run_date)s;
INSERT INTO staging.dispatch
SELECT order_id, driver_id, original_driver_id,
       assigned_at::timestamp, reassigned_at::timestamp,
       estimated_pickup_at::timestamp, current_delivery_eta::timestamp,
       dispatch_status, eta_model_version,
       reassigned_at IS NOT NULL AS was_reassigned,
       run_date
FROM raw.dispatch WHERE run_date = %(run_date)s;

-- ── Restaurant status (manual entry — the messiest source in the estate) ────────────────────
-- Casing and whitespace variants (`ready`, `ready `, `READY`, `Ready`) are the same operational
-- state typed by different people. `handoff` and `handed_off` likewise. The raw value is retained
-- so the normalisation stays auditable rather than invisible.
DELETE FROM staging.restaurant_status WHERE run_date = %(run_date)s;
INSERT INTO staging.restaurant_status
SELECT order_id, restaurant_id, status AS status_raw,
       CASE lower(btrim(status))
            WHEN 'handoff' THEN 'handed_off'
            ELSE lower(btrim(status))
       END AS status,
       last_updated_at::timestamp, run_date
FROM raw.restaurant_status WHERE run_date = %(run_date)s;

-- ── Order events ────────────────────────────────────────────────────────────────────────────
DELETE FROM staging.order_events WHERE run_date = %(run_date)s;
INSERT INTO staging.order_events
SELECT event_id, order_id, upper(btrim(event_type)), event_time::timestamp,
       actor_type, actor_id, source_system, run_date
FROM raw.order_events WHERE run_date = %(run_date)s;

-- ── Driver events (flattened nested JSON) ───────────────────────────────────────────────────
DELETE FROM staging.driver_events WHERE run_date = %(run_date)s;
INSERT INTO staging.driver_events
SELECT driver_id, order_id, lower(btrim(event_type)), event_time::timestamp,
       NULLIF(lat,'')::numeric, NULLIF(lon,'')::numeric, run_date
FROM raw.driver_events WHERE run_date = %(run_date)s;

-- ── Support tickets ─────────────────────────────────────────────────────────────────────────
-- Free-text categories arrive as `late_delivery`, `Late Delivery`, `late_delivery ` and
-- `ETA issue`. Normalisation collapses casing, whitespace and spaces-to-underscores.
-- is_joinable records that 3 tickets carry no order_id and can never reach an order.
DELETE FROM staging.support_tickets WHERE run_date = %(run_date)s;
INSERT INTO staging.support_tickets
SELECT ticket_id, NULLIF(btrim(order_id),'') AS order_id, created_at::timestamp,
       category AS category_raw,
       replace(lower(btrim(category)), ' ', '_') AS category,
       customer_message,
       NULLIF(btrim(order_id),'') IS NOT NULL AS is_joinable,
       run_date
FROM raw.support_tickets WHERE run_date = %(run_date)s;

-- ── Customer interactions ───────────────────────────────────────────────────────────────────
DELETE FROM staging.customer_interactions WHERE run_date = %(run_date)s;
INSERT INTO staging.customer_interactions
SELECT interaction_id, order_id, upper(btrim(interaction_type)), interaction_at::timestamp,
       channel, detail AS detail_raw,
       NULLIF(replace(lower(btrim(detail)), ' ', '_'), '') AS detail,
       run_date
FROM raw.customer_interactions WHERE run_date = %(run_date)s;

-- ── Interventions ───────────────────────────────────────────────────────────────────────────
DELETE FROM staging.order_interventions WHERE run_date = %(run_date)s;
INSERT INTO staging.order_interventions
SELECT intervention_id, order_id, upper(btrim(intervention_type)),
       intervention_at::timestamp, initiated_by, reason, run_date
FROM raw.order_interventions WHERE run_date = %(run_date)s;

-- ── Customer app actions ────────────────────────────────────────────────────────────────────
DELETE FROM staging.customer_app_actions WHERE run_date = %(run_date)s;
INSERT INTO staging.customer_app_actions
SELECT action_id, order_id, customer_id, upper(btrim(action_type)),
       action_at::timestamp, channel, run_date
FROM raw.customer_app_actions WHERE run_date = %(run_date)s;

-- ── Client's derived outcomes (reconciliation only) ─────────────────────────────────────────
DELETE FROM staging.client_order_outcomes WHERE run_date = %(run_date)s;
INSERT INTO staging.client_order_outcomes
SELECT order_id, final_status_norm,
       NULLIF(delivered_flag,'')::numeric::integer,
       NULLIF(late_flag,'')::numeric,
       NULLIF(delay_min,'')::numeric,
       outcome_bucket, run_date
FROM raw.order_outcomes WHERE run_date = %(run_date)s;
