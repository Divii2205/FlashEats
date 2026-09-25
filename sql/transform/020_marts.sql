-- Per-run build of the workflow model. Partition-scoped on :run_date throughout.

-- ── Dimensions ──────────────────────────────────────────────────────────────────────────────

DELETE FROM marts.dim_restaurant WHERE run_date = %(run_date)s;
INSERT INTO marts.dim_restaurant
SELECT restaurant_id, btrim(restaurant_name), btrim(cuisine),
       NULLIF(lat,'')::numeric, NULLIF(lon,'')::numeric,
       NULLIF(manual_status_updates,'')::numeric > 0,
       run_date
FROM raw.restaurants WHERE run_date = %(run_date)s;

DELETE FROM marts.dim_driver WHERE run_date = %(run_date)s;
INSERT INTO marts.dim_driver
SELECT driver_id, NULLIF(rating,'')::numeric, btrim(vehicle_type),
       NULLIF(experience_months,'')::numeric::integer,
       -- Banding is a modelling choice: raw month counts are too granular to segment a KPI by,
       -- and these cut points are what operations already uses to talk about tenure.
       CASE
           WHEN NULLIF(experience_months,'')::numeric < 6  THEN '0-5m'
           WHEN NULLIF(experience_months,'')::numeric < 12 THEN '6-11m'
           WHEN NULLIF(experience_months,'')::numeric < 24 THEN '12-23m'
           ELSE '24m+'
       END,
       run_date
FROM raw.drivers WHERE run_date = %(run_date)s;

DELETE FROM marts.dim_customer WHERE run_date = %(run_date)s;
INSERT INTO marts.dim_customer
SELECT customer_id, NULLIF(lat,'')::numeric, NULLIF(lon,'')::numeric, run_date
FROM raw.customers WHERE run_date = %(run_date)s;

-- ── Event fact: three systems unioned into one timeline ─────────────────────────────────────

DELETE FROM marts.fct_order_events WHERE run_date = %(run_date)s;
INSERT INTO marts.fct_order_events
SELECT order_id, event_type, event_time, actor_type, actor_id, 'order_platform', run_date
FROM staging.order_events
WHERE run_date = %(run_date)s AND order_id IS NOT NULL

UNION ALL
-- GPS pings are excluded: they are telemetry, not state transitions, and would swamp the fact
-- table at 5,371 rows without marking any change in the workflow.
SELECT order_id, upper(event_type), event_time, 'driver', driver_id, 'driver_app', run_date
FROM staging.driver_events
WHERE run_date = %(run_date)s AND order_id IS NOT NULL AND event_type <> 'gps_ping'

UNION ALL
SELECT order_id, 'RESTAURANT_' || upper(status), last_updated_at, 'restaurant', restaurant_id,
       'restaurant_ops', run_date
FROM staging.restaurant_status
WHERE run_date = %(run_date)s AND order_id IS NOT NULL;

-- ── Lifecycle fact ──────────────────────────────────────────────────────────────────────────

DELETE FROM marts.fct_order_lifecycle WHERE run_date = %(run_date)s;
INSERT INTO marts.fct_order_lifecycle
WITH ready AS (
    -- Earliest READY per order. The source has duplicate order_ids, so DISTINCT ON makes the
    -- choice explicit rather than leaving it to join order.
    SELECT DISTINCT ON (order_id) order_id, last_updated_at AS ready_at
    FROM staging.restaurant_status
    WHERE run_date = %(run_date)s AND status = 'ready'
    ORDER BY order_id, last_updated_at
),
actions AS (
    SELECT order_id,
           count(*)                                          AS interaction_count,
           count(*) FILTER (WHERE action_type = 'ETA_VIEWED') AS eta_view_count
    FROM staging.customer_app_actions
    WHERE run_date = %(run_date)s AND order_id IS NOT NULL
    GROUP BY order_id
),
complaints AS (
    -- A complaint is counted from the interactions stream rather than support_tickets because 3
    -- tickets carry no order_id and can never be attributed. Counting them here would inflate
    -- some orders and silently drop others.
    SELECT order_id, count(*) AS complaint_count
    FROM staging.customer_interactions
    WHERE run_date = %(run_date)s AND order_id IS NOT NULL
      AND interaction_type = 'SUPPORT_TICKET'
    GROUP BY order_id
),
interventions AS (
    SELECT order_id,
           count(*) AS intervention_count,
           string_agg(DISTINCT intervention_type, ',' ORDER BY intervention_type) AS intervention_types
    FROM staging.order_interventions
    WHERE run_date = %(run_date)s AND order_id IS NOT NULL
    GROUP BY order_id
),
base AS (
    SELECT
        o.order_id, o.customer_id, o.restaurant_id, o.driver_id, o.city,
        CASE
            WHEN extract(hour FROM o.created_at) BETWEEN  6 AND 10 THEN 'breakfast'
            WHEN extract(hour FROM o.created_at) BETWEEN 11 AND 15 THEN 'lunch'
            WHEN extract(hour FROM o.created_at) BETWEEN 16 AND 20 THEN 'dinner'
            ELSE 'late_night'
        END AS daypart,
        o.created_at, d.assigned_at, r.ready_at, o.pickup_at,
        o.actual_delivery_at AS delivered_at, o.promised_eta,

        -- Stage durations. Each is NULL when either endpoint is missing, so a gap propagates as
        -- an absence rather than as a zero that would silently drag an average down.
        round(extract(epoch FROM (d.assigned_at        - o.created_at))   / 60.0, 2) AS dispatch_latency_min,
        round(extract(epoch FROM (o.pickup_at          - d.assigned_at))  / 60.0, 2) AS assign_to_pickup_min,
        round(extract(epoch FROM (o.pickup_at          - r.ready_at))     / 60.0, 2) AS idle_wait_min,
        round(extract(epoch FROM (o.actual_delivery_at - o.pickup_at))    / 60.0, 2) AS transit_min,
        round(extract(epoch FROM (o.actual_delivery_at - o.created_at))   / 60.0, 2) AS end_to_end_min,

        o.final_status,
        round(extract(epoch FROM (o.actual_delivery_at - o.promised_eta)) / 60.0, 2) AS delay_min,
        o.traffic_bucket, o.weather_bucket, o.distance_km_estimate,
        d.eta_model_version, d.was_reassigned,
        COALESCE(a.interaction_count, 0)  AS interaction_count,
        COALESCE(c.complaint_count, 0)    AS complaint_count,
        COALESCE(a.eta_view_count, 0)     AS eta_view_count,
        COALESCE(i.intervention_count, 0) AS intervention_count,
        i.intervention_types,
        o.had_conflicting_dupe,
        o.run_date
    FROM staging.orders o
    LEFT JOIN staging.dispatch d ON d.order_id = o.order_id AND d.run_date = o.run_date
    LEFT JOIN ready         r ON r.order_id = o.order_id
    LEFT JOIN actions       a ON a.order_id = o.order_id
    LEFT JOIN complaints    c ON c.order_id = o.order_id
    LEFT JOIN interventions i ON i.order_id = o.order_id
    WHERE o.run_date = %(run_date)s
)
SELECT
    order_id, customer_id, restaurant_id, driver_id, city, daypart,
    created_at, assigned_at, ready_at, pickup_at, delivered_at, promised_eta,
    dispatch_latency_min, assign_to_pickup_min, idle_wait_min, transit_min, end_to_end_min,
    final_status, delay_min,
    delay_min > 0                                        AS is_late_strict,
    delay_min > %(material_threshold)s                   AS is_late_material,
    -- Measurable means: a completed delivery we can actually time. Cancelled orders and delivered
    -- orders with no completion timestamp are excluded from every rate, and counted separately.
    (final_status = 'delivered' AND delay_min IS NOT NULL) AS is_measurable,
    traffic_bucket, weather_bucket, distance_km_estimate, eta_model_version, was_reassigned,
    interaction_count, complaint_count, eta_view_count, intervention_count, intervention_types,
    had_conflicting_dupe,
    -- A negative stage duration is physically impossible and marks clock skew or manual entry
    -- error. The flag travels with the row so any metric can choose to exclude it knowingly.
    (COALESCE(dispatch_latency_min, 0) < 0
     OR COALESCE(assign_to_pickup_min, 0) < 0
     OR COALESCE(idle_wait_min, 0) < 0
     OR COALESCE(transit_min, 0) < 0)                     AS has_negative_duration,
    run_date
FROM base;
