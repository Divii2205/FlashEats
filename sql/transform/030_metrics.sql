-- Metric computation. Every metric reads from marts.fct_order_lifecycle so there is exactly one
-- definition of a stage duration in the project, and every row carries its own numerator,
-- denominator and caveat, because a KPI without its denominator is not auditable.

DELETE FROM metrics.kpi WHERE run_date = %(run_date)s;

-- ── M1: Late Delivery Rate, under BOTH contested definitions ────────────────────────────────
-- The client's four stakeholders disagree and no KPI owner is documented, so the pipeline
-- publishes both rather than silently selecting one. See docs/decision_log.md D-001.
INSERT INTO metrics.kpi
SELECT 'M1', 'Late Delivery Rate',
       'strict (>0 min past promised ETA) — VP Operations',
       'ALL',
       round(100.0 * count(*) FILTER (WHERE is_late_strict) / NULLIF(count(*), 0), 2),
       'pct',
       count(*) FILTER (WHERE is_late_strict),
       count(*),
       'delivered orders with a completion timestamp only; excludes ' ||
       (SELECT count(*) FROM marts.fct_order_lifecycle
        WHERE run_date = %(run_date)s AND NOT is_measurable) ||
       ' unmeasurable orders. No documented KPI owner for "late".',
       %(run_date)s
FROM marts.fct_order_lifecycle
WHERE run_date = %(run_date)s AND is_measurable;

INSERT INTO metrics.kpi
SELECT 'M1', 'Late Delivery Rate',
       'material (>' || %(material_threshold)s || ' min past promised ETA) — Support Lead',
       'ALL',
       round(100.0 * count(*) FILTER (WHERE is_late_material) / NULLIF(count(*), 0), 2),
       'pct',
       count(*) FILTER (WHERE is_late_material),
       count(*),
       'Same population as the strict definition. Median delay is ' ||
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY delay_min)::numeric, 2) ||
       ' min, so the strict rate is dominated by orders late by seconds.',
       %(run_date)s
FROM marts.fct_order_lifecycle
WHERE run_date = %(run_date)s AND is_measurable;

-- M1 segmented by daypart: where the KPI actually moves.
INSERT INTO metrics.kpi
SELECT 'M1', 'Late Delivery Rate', 'material — by daypart', daypart,
       round(100.0 * count(*) FILTER (WHERE is_late_material) / NULLIF(count(*), 0), 2),
       'pct',
       count(*) FILTER (WHERE is_late_material), count(*),
       'segment of the material definition',
       %(run_date)s
FROM marts.fct_order_lifecycle
WHERE run_date = %(run_date)s AND is_measurable
GROUP BY daypart;

-- ── M2: P90 order-to-door minutes ───────────────────────────────────────────────────────────
-- The tail is what customers complain about; a median hides it.
INSERT INTO metrics.kpi
SELECT 'M2', 'Order-to-door time', label, 'ALL', value, 'minutes', NULL, denom,
       'end-to-end: order creation to delivery, measurable orders only',
       %(run_date)s
FROM (
    SELECT 'P50 (median)' AS label,
           round(percentile_cont(0.50) WITHIN GROUP (ORDER BY end_to_end_min)::numeric, 2) AS value,
           count(*) AS denom
    FROM marts.fct_order_lifecycle WHERE run_date = %(run_date)s AND is_measurable
    UNION ALL
    SELECT 'P90',
           round(percentile_cont(0.90) WITHIN GROUP (ORDER BY end_to_end_min)::numeric, 2),
           count(*)
    FROM marts.fct_order_lifecycle WHERE run_date = %(run_date)s AND is_measurable
) s;

-- ── M3: Delay attribution by stage ──────────────────────────────────────────────────────────
-- The decision metric. Excess = median duration on materially late orders minus the same median
-- on on-time orders. Share is that excess as a proportion of all excess, which is what tells
-- leadership where an intervention would actually pay.
INSERT INTO metrics.kpi
WITH stage_medians AS (
    SELECT
        percentile_cont(0.5) WITHIN GROUP (ORDER BY dispatch_latency_min)
            FILTER (WHERE is_late_material)     AS dispatch_late,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY dispatch_latency_min)
            FILTER (WHERE NOT is_late_material) AS dispatch_ontime,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY assign_to_pickup_min)
            FILTER (WHERE is_late_material)     AS pickup_late,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY assign_to_pickup_min)
            FILTER (WHERE NOT is_late_material) AS pickup_ontime,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY transit_min)
            FILTER (WHERE is_late_material)     AS transit_late,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY transit_min)
            FILTER (WHERE NOT is_late_material) AS transit_ontime,
        count(*) FILTER (WHERE is_late_material) AS n_late
    FROM marts.fct_order_lifecycle
    WHERE run_date = %(run_date)s AND is_measurable
),
excess AS (
    SELECT 'order -> driver assigned' AS stage, 'Dispatch' AS owner,
           round((dispatch_late - dispatch_ontime)::numeric, 2) AS excess_min, n_late FROM stage_medians
    UNION ALL
    SELECT 'driver assigned -> pickup', 'Courier supply + kitchen',
           round((pickup_late - pickup_ontime)::numeric, 2), n_late FROM stage_medians
    UNION ALL
    SELECT 'pickup -> delivered', 'Transit / routing',
           round((transit_late - transit_ontime)::numeric, 2), n_late FROM stage_medians
)
SELECT 'M3', 'Delay attribution by stage', owner, stage,
       round(100.0 * excess_min / NULLIF((SELECT sum(excess_min) FROM excess WHERE excess_min > 0), 0), 1),
       'pct_of_excess', excess_min, n_late,
       'excess = median stage duration on materially late orders minus the same median on on-time orders',
       %(run_date)s
FROM excess;

-- ── M4: The lever — assigned-to-pickup, and the idle wait inside it ─────────────────────────
INSERT INTO metrics.kpi
SELECT 'M4', 'Assigned-to-pickup minutes', 'median, all measurable orders', 'ALL',
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY assign_to_pickup_min)::numeric, 2),
       'minutes', NULL, count(*),
       'the stage carrying most of the excess delay; driver travel plus wait at the restaurant',
       %(run_date)s
FROM marts.fct_order_lifecycle
WHERE run_date = %(run_date)s AND is_measurable;

-- The sub-metric that would isolate kitchen wait from driver travel — published WITH the coverage
-- caveat attached, because reporting it bare would imply a confidence the data does not support.
INSERT INTO metrics.kpi
SELECT 'M4', 'Courier idle wait at restaurant', 'median, orders with a food-ready timestamp', 'ALL',
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY idle_wait_min)::numeric, 2),
       'minutes', NULL, count(*),
       'LOW CONFIDENCE — computable for only ' || count(*) || ' of ' ||
       (SELECT count(*) FROM marts.fct_order_lifecycle WHERE run_date = %(run_date)s) ||
       ' orders, from manually entered restaurant status. ' ||
       count(*) FILTER (WHERE idle_wait_min < 0) ||
       ' of these are negative (pickup recorded before food ready), which is impossible. '
       'Directional only; not a basis for investment.',
       %(run_date)s
FROM marts.fct_order_lifecycle
WHERE run_date = %(run_date)s AND is_measurable AND idle_wait_min IS NOT NULL;

-- ── M5: Customer impact — complaints per 100 orders ─────────────────────────────────────────
-- Independent, customer-side corroboration that the delay is actually felt.
INSERT INTO metrics.kpi
SELECT 'M5', 'Complaints per 100 orders',
       CASE WHEN is_late_material THEN 'materially late orders' ELSE 'on-time orders' END,
       'ALL',
       round(100.0 * sum(complaint_count) / NULLIF(count(*), 0), 1),
       'per_100_orders', sum(complaint_count), count(*),
       'support-ticket interactions attributed to an order; excludes 3 tickets with no order_id',
       %(run_date)s
FROM marts.fct_order_lifecycle
WHERE run_date = %(run_date)s AND is_measurable
GROUP BY is_late_material;

-- ── M5b: Are operational interventions targeted at risk? ────────────────────────────────────
INSERT INTO metrics.kpi
SELECT 'M5', 'Interventions per 100 orders',
       CASE WHEN is_late_material THEN 'materially late orders' ELSE 'on-time orders' END,
       'ALL',
       round(100.0 * sum(intervention_count) / NULLIF(count(*), 0), 1),
       'per_100_orders', sum(intervention_count), count(*),
       'if these two rates are equal, intervention effort is not risk-targeted',
       %(run_date)s
FROM marts.fct_order_lifecycle
WHERE run_date = %(run_date)s AND is_measurable
GROUP BY is_late_material;
