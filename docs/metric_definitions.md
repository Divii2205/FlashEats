# Metric Definitions

The five published metrics, stated precisely enough that a second analyst could reproduce every
figure from the raw sources without asking a question.

All figures on this page are from run date **2026-08-29**, covering 1,600 orders created between
2026-08-01 and 2026-08-28. Every metric is computed by `sql/transform/030_metrics.sql` and reads from
a single table, `marts.fct_order_lifecycle`, so there is exactly one definition of a stage duration
in the project. Metrics are written to `metrics.kpi` in long format — one row per metric per
definition per segment — each row carrying its own numerator, denominator and caveat, because a
rate without its denominator cannot be audited.

Two parameters are injected at run time from `src/flasheats/config.py`:

| Parameter | Env var | Value used here |
| --- | --- | --- |
| `%(run_date)s` | — | `2026-08-29` |
| `%(material_threshold)s` | `MATERIAL_LATE_THRESHOLD_MIN` | `10` (minutes) |

---

## The shared population: `is_measurable`

Every rate on this page uses the same denominator population. It is defined once, in
`sql/transform/020_marts.sql`, and stored as a column on the lifecycle fact:

```sql
-- Measurable means: a completed delivery we can actually time. Cancelled orders and delivered
-- orders with no completion timestamp are excluded from every rate, and counted separately.
(final_status = 'delivered' AND delay_min IS NOT NULL) AS is_measurable,
```

where `delay_min` is itself:

```sql
round(extract(epoch FROM (o.actual_delivery_at - o.promised_eta)) / 60.0, 2) AS delay_min,
```

`final_status` is lower-cased and trimmed in staging (`build_orders` in
`src/flasheats/transform/staging.py`), with the untouched original retained as `final_status_raw`,
so `Delivered` and `delivered` collapse to one state without the normalisation becoming invisible.

### How the 1,600 reduce to 1,495

| Population | Count | Why it is or is not measurable |
| --- | --- | --- |
| Orders at order grain | 1,600 | 1,603 raw rows deduplicated to 1,600 unique `order_id` |
| Not `delivered` (cancelled) | 68 | A cancellation is not a delivery outcome; it has no delivery time to compare against an ETA |
| `delivered` with no `actual_delivery_at` | 37 | `delay_min` is NULL, so lateness is unknowable, not zero |
| **Measurable** | **1,495** | Delivered, and timed end to end |

105 orders are excluded in total (68 + 37), which is the figure quoted in the M1 caveat.

### Why these exclusions, and not some other treatment

**Cancelled orders (68).** Finance's stated position in
`sources/data/client_metric_definitions.json` is that cancelled and refunded orders must not count
in operational delivery performance. Including all 68 as late would move the strict rate from
56.39% to 58.25%. See ASSUMPTIONS A-1.

**Delivered but untimestamped (37).** There are three possible treatments and each asserts something
different:

| Treatment | Strict late rate | What it claims |
| --- | --- | --- |
| Count them late | 59.25% | That 37 orders we cannot time were late — a fact not in evidence |
| Count them on time | below 56.39% | The mirror-image unfounded claim, understating the rate |
| Exclude from both numerator and denominator | **56.39%** | That 2.4% of deliveries cannot be assessed |

Only the third is defensible without new data, so it is what the pipeline does, and the excluded
count travels inside the metric's own caveat string so the exclusion cannot be quietly forgotten.
See decision log D-004 and ASSUMPTIONS A-2.

**Null handling generally.** Stage durations are computed as timestamp differences and are NULL
whenever either endpoint is missing, never zero. A NULL propagates as an absence: `percentile_cont`
ignores it, and the denominator reported alongside each percentile is the count of rows in the
population, so any gap between that denominator and the number of non-null observations is visible
rather than silently averaged away.

**A qualifier that is carried, not cleaned.** 79 orders have at least one physically impossible
negative stage duration. They are flagged with `has_negative_duration` and retained, not dropped, so
medians are computed over a population known to contain them. Medians rather than means are used
throughout partly for this reason. See ASSUMPTIONS L-3.

---

## M1 — Late Delivery Rate

**Definition.** The percentage of measurable orders delivered after the promised ETA. Published
under two thresholds simultaneously, plus a daypart segmentation of the material definition.

**Grain.** One row per order, aggregated to a single rate per definition per segment.

**Population.** `marts.fct_order_lifecycle` where `run_date = 2026-08-29 AND is_measurable` —
1,495 orders.

**Null handling.** Orders with a NULL `delay_min` are already excluded by `is_measurable`, so the
comparison never evaluates against a NULL. `NULLIF(count(*), 0)` guards the denominator so an empty
partition yields NULL rather than a division error.

### M1a — strict (> 0 minutes past promised ETA)

```sql
SELECT 'M1', 'Late Delivery Rate',
       'strict (>0 min past promised ETA) — VP Operations',
       'ALL',
       round(100.0 * count(*) FILTER (WHERE is_late_strict) / NULLIF(count(*), 0), 2),
       'pct',
       count(*) FILTER (WHERE is_late_strict),
       count(*),
       ...
FROM marts.fct_order_lifecycle
WHERE run_date = %(run_date)s AND is_measurable;
```

with, from the mart build:

```sql
delay_min > 0                                        AS is_late_strict,
delay_min > %(material_threshold)s                   AS is_late_material,
```

| | |
| --- | --- |
| Numerator | 843 measurable orders with `delay_min > 0` |
| Denominator | 1,495 measurable orders |
| **Value** | **56.39%** |

**Caveat as published.** *"delivered orders with a completion timestamp only; excludes 105
unmeasurable orders. No documented KPI owner for 'late'."*

This figure reproduces the client's own derived `order_outcomes.csv` exactly — 843 against 843 —
which is checked every run by `cross.client_kpi_reconciliation`. The leadership claim of 56% is
therefore arithmetically correct. The dispute is over the definition, not the computation.

### M1b — material (> 10 minutes past promised ETA)

```sql
       round(100.0 * count(*) FILTER (WHERE is_late_material) / NULLIF(count(*), 0), 2),
```

| | |
| --- | --- |
| Numerator | 349 measurable orders with `delay_min > 10` |
| Denominator | 1,495 measurable orders |
| **Value** | **23.34%** |

**Caveat as published.** *"Same population as the strict definition. Median delay is 1.41 min, so
the strict rate is dominated by orders late by seconds."*

That median is computed inline in the caveat itself, from the same population, so the qualifier
cannot drift away from the number it qualifies.

### M1c — material rate by daypart

```sql
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
```

`daypart` is derived in the mart build from the hour of `created_at`: 06–10 breakfast, 11–15 lunch,
16–20 dinner, anything else late night.

| Segment | Numerator | Denominator | Value |
| --- | --- | --- | --- |
| dinner | 203 | 805 | **25.22%** |
| lunch | 99 | 441 | **22.45%** |
| late_night | 47 | 249 | **18.88%** |

No `breakfast` row is published because no measurable order in this window was created between
06:00 and 10:59. The three segments sum to the full population (805 + 441 + 249 = 1,495) and to the
full numerator (203 + 99 + 47 = 349), which is the arithmetic check on the segmentation.

### How to hand-check M1

1. Take `orders` from the source SQLite database. Confirm 1,603 rows and 1,600 distinct
   `order_id`.
2. Keep rows where lower-cased `final_status = 'delivered'` → 1,532.
3. Drop rows with a null `actual_delivery_at` → 1,495.
4. Compute `delay = actual_delivery_at - promised_eta` in minutes. Count `delay > 0` → 843;
   843 / 1,495 = 56.39%. Count `delay > 10` → 349; 349 / 1,495 = 23.34%.
5. Cross-check the strict count against `sources/data/order_outcomes.csv`: the count of
   `outcome_bucket = 'delivered_late'` should also be 843.

---

## M2 — Order-to-door time

**Definition.** End-to-end elapsed minutes from order creation to delivery, published at the median
and the 90th percentile. The tail is what customers complain about, and a median alone conceals it,
so both are published as separate rows of the same metric.

**Grain.** One row per percentile, over the whole measurable population.

**Population.** Measurable orders — 1,495.

**Null handling.** `end_to_end_min` is NULL when either `created_at` or `actual_delivery_at` is
missing. `is_measurable` already requires a delivery timestamp, so within this population the
measure is fully populated. `percentile_cont` would ignore NULLs in any case.

**SQL** — the duration, from `sql/transform/020_marts.sql`:

```sql
round(extract(epoch FROM (o.actual_delivery_at - o.created_at))   / 60.0, 2) AS end_to_end_min,
```

and the metric, from `sql/transform/030_metrics.sql`:

```sql
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
```

| Definition | Numerator | Denominator | Value |
| --- | --- | --- | --- |
| P50 (median) | — (not a ratio) | 1,495 | **73.96 minutes** |
| P90 | — (not a ratio) | 1,495 | **93.27 minutes** |

The numerator column is deliberately NULL: a percentile has no numerator, and writing one would
imply a ratio that does not exist. The denominator is still recorded, because the population a
percentile was taken over is exactly what a reader needs to judge it.

**Caveat as published.** *"end-to-end: order creation to delivery, measurable orders only"*

### How to hand-check M2

Sort the 1,495 measurable orders by `(actual_delivery_at - created_at)` in minutes. The value at
the 50th percentile should be 73.96 and at the 90th, 93.27. Note that `percentile_cont`
interpolates between adjacent observations, so a nearest-rank percentile from a spreadsheet may
differ in the second decimal place. A gap of more than a minute means the population is wrong, not
the interpolation.

---

## M3 — Delay attribution by stage

**Definition.** For each of the three lifecycle stages, the *excess* is the median duration of that
stage on materially late orders minus the median of the same stage on on-time orders. The published
value is that excess expressed as a percentage of all positive excess, which is what indicates where
an intervention would actually pay.

This is the decision metric. M1 says how often the business is late; M3 says where the lateness is
manufactured.

**Grain.** One row per stage (three rows), over the measurable population split by
`is_late_material`.

**Population.** Measurable orders — 349 materially late, 1,146 on time.

**Null handling.** Each stage duration is independently NULL when either of its endpoints is
missing, so a stage can be measured over a smaller set than another without the metric collapsing.
`percentile_cont ... FILTER (...)` ignores NULLs within each side of the comparison. The share
denominator is guarded with `NULLIF(..., 0)`.

**The three stages and their durations**, from `sql/transform/020_marts.sql`:

```sql
round(extract(epoch FROM (d.assigned_at        - o.created_at))   / 60.0, 2) AS dispatch_latency_min,
round(extract(epoch FROM (o.pickup_at          - d.assigned_at))  / 60.0, 2) AS assign_to_pickup_min,
round(extract(epoch FROM (o.actual_delivery_at - o.pickup_at))    / 60.0, 2) AS transit_min,
```

**The metric**, from `sql/transform/030_metrics.sql` (abridged to one stage; the other two follow the
identical pattern):

```sql
WITH stage_medians AS (
    SELECT
        percentile_cont(0.5) WITHIN GROUP (ORDER BY assign_to_pickup_min)
            FILTER (WHERE is_late_material)     AS pickup_late,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY assign_to_pickup_min)
            FILTER (WHERE NOT is_late_material) AS pickup_ontime,
        count(*) FILTER (WHERE is_late_material) AS n_late
    FROM marts.fct_order_lifecycle
    WHERE run_date = %(run_date)s AND is_measurable
),
excess AS (
    SELECT 'driver assigned -> pickup', 'Courier supply + kitchen',
           round((pickup_late - pickup_ontime)::numeric, 2), n_late FROM stage_medians
)
SELECT 'M3', 'Delay attribution by stage', owner, stage,
       round(100.0 * excess_min / NULLIF((SELECT sum(excess_min) FROM excess WHERE excess_min > 0), 0), 1),
       'pct_of_excess', excess_min, n_late,
       'excess = median stage duration on materially late orders minus the same median on on-time orders',
       %(run_date)s
FROM excess;
```

Note the share denominator: `sum(excess_min) FROM excess WHERE excess_min > 0`. Only positive
excess is summed, so a stage that is *faster* on late orders correctly reports a negative share
rather than distorting the base that the other stages are measured against. Here that base is
17.01 + 3.94 = 20.95 minutes.

| Stage | Owner | Median, materially late | Median, on time | Excess (numerator) | Denominator | Share of excess |
| --- | --- | --- | --- | --- | --- | --- |
| order → driver assigned | Dispatch | 2.16 min | 2.36 min | −0.20 min | 349 | **−1.0%** |
| driver assigned → pickup | Courier supply + kitchen | 37.47 min | 20.47 min | +17.01 min | 349 | **81.2%** |
| pickup → delivered | Transit / routing | 50.32 min | 46.39 min | +3.94 min | 349 | **18.8%** |

The denominator column carries `n_late` (349), the count of materially late orders the late-side
medians were taken over.

**Caveat as published.** *"excess = median stage duration on materially late orders minus the same
median on on-time orders"*

**The caveat that matters more than the published string.** This is an observational comparison, not
a causal one. It establishes *where* delay accumulates on orders that end up late; it does not
establish that compressing that stage would prevent the lateness. "Fix the assigned→pickup gap" is a
hypothesis with strong evidence behind it, not a proven cause. See ASSUMPTIONS L-2. The negative
dispatch excess is a genuine finding and should be read literally: orders that end up materially
late are dispatched *marginally faster* than orders that arrive on time, which is direct evidence
against dispatch latency being the binding constraint.

### How to hand-check M3

1. Split the 1,495 measurable orders on `delay > 10` into 349 late and 1,146 on time.
2. For each group take the median of each of the three durations. You should get
   2.16 / 37.47 / 50.32 for the late group and 2.36 / 20.47 / 46.39 for the on-time group.
3. Subtract: −0.20, +17.01, +3.94.
4. Sum only the positives: 20.95. Then 17.01 / 20.95 = 81.2%, 3.94 / 20.95 = 18.8%,
   −0.20 / 20.95 = −1.0%.
5. Sanity check: the positive shares must sum to 100.0%.

---

## M4 — Assigned-to-pickup minutes, and the idle wait inside it

**Definition.** Two rows. The headline is the median minutes from driver assignment to pickup across
all measurable orders — the stage M3 identifies as carrying most of the excess. The second row
attempts to split that stage into courier travel versus waiting at the restaurant, and is published
with a low-confidence marker attached.

**Grain.** One row per sub-metric, over the whole measurable population (headline) or over the
subset with a food-ready timestamp (idle wait).

### M4a — median assigned-to-pickup

```sql
INSERT INTO metrics.kpi
SELECT 'M4', 'Assigned-to-pickup minutes', 'median, all measurable orders', 'ALL',
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY assign_to_pickup_min)::numeric, 2),
       'minutes', NULL, count(*),
       'the stage carrying most of the excess delay; driver travel plus wait at the restaurant',
       %(run_date)s
FROM marts.fct_order_lifecycle
WHERE run_date = %(run_date)s AND is_measurable;
```

| | |
| --- | --- |
| Numerator | — (not a ratio) |
| Denominator | 1,495 measurable orders |
| **Value** | **23.07 minutes** |

**Population and null handling.** All measurable orders. `assign_to_pickup_min` is NULL where either
`assigned_at` (from the Dispatch API) or `pickup_at` is missing; `cross.dispatch_coverage` confirms
every one of the 1,600 orders has a dispatch record, so assignment coverage is complete.

### M4b — courier idle wait at the restaurant

**Definition.** Minutes from the restaurant marking food ready to the courier recording pickup. If
it is large, kitchens are fast and couriers are arriving late; if small or negative, the courier is
waiting on the kitchen.

**Population.** Measurable orders that also have a non-null `idle_wait_min` — **153 orders**, out of
1,600. `ready_at` is taken as the *earliest* `READY` row per order, chosen explicitly with
`DISTINCT ON` in the mart build rather than being left to join order, because the source contains
duplicate status rows per order:

```sql
WITH ready AS (
    -- Earliest READY per order. The source has duplicate order_ids, so DISTINCT ON makes the
    -- choice explicit rather than leaving it to join order.
    SELECT DISTINCT ON (order_id) order_id, last_updated_at AS ready_at
    FROM staging.restaurant_status
    WHERE run_date = %(run_date)s AND status = 'ready'
    ORDER BY order_id, last_updated_at
),
```

```sql
round(extract(epoch FROM (o.pickup_at - r.ready_at)) / 60.0, 2) AS idle_wait_min,
```

```sql
INSERT INTO metrics.kpi
SELECT 'M4', 'Courier idle wait at restaurant', 'median, orders with a food-ready timestamp', 'ALL',
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY idle_wait_min)::numeric, 2),
       'minutes', NULL, count(*),
       'LOW CONFIDENCE — computable for only ' || count(*) || ' of ' || ... || ' orders, ...',
       %(run_date)s
FROM marts.fct_order_lifecycle
WHERE run_date = %(run_date)s AND is_measurable AND idle_wait_min IS NOT NULL;
```

| | |
| --- | --- |
| Numerator | — (not a ratio) |
| Denominator | 153 orders with a food-ready timestamp |
| **Value** | **5.41 minutes — LOW CONFIDENCE** |

**Caveat as published.** *"LOW CONFIDENCE — computable for only 153 of 1600 orders, from manually
entered restaurant status. 57 of these are negative (pickup recorded before food ready), which is
impossible. Directional only; not a basis for investment."*

The coverage and the negative count are both computed inline from the same population that produces
the median, so the caveat cannot become stale relative to the number.

**Why it is published at all.** Suppressing it would hide the most decision-relevant gap in the
engagement; publishing it bare would imply a confidence the data does not support. Publishing it
with the coverage stapled to it is the only honest option. The corresponding validation rule,
`restaurant_status.ready_coverage`, is permanently `UNKNOWN` for the same reason.

### How to hand-check M4

1. Median of `(pickup_at - assigned_at)` in minutes over the 1,495 measurable orders → 23.07.
2. For the idle wait: normalise `restaurant_status.status` for casing and whitespace
   (`ready`, `ready `, `READY`, `Ready` are the same state — ASSUMPTIONS A-4), take the earliest
   `ready` row per `order_id`, join to measurable orders, and compute `pickup_at - ready_at`.
   You should get 153 non-null values, of which 57 are negative, with a median of 5.41.
3. The 153 will not match the 160 orders reported as having a food-ready timestamp by
   `restaurant_status.ready_coverage`: that rule counts ready timestamps across all 1,600 orders,
   whereas this metric additionally requires the order to be measurable and to have a `pickup_at`.

---

## M5 — Customer impact and intervention targeting

Two rows, deliberately paired. The first establishes that the delay is actually felt by customers;
the second asks whether the operation is already responding to it. Both are computed from a
different source system than the timestamps, which is what makes them corroboration rather than
restatement.

**Grain.** One row per `is_late_material` group, for each of the two sub-metrics.

**Population.** Measurable orders, grouped: 349 materially late, 1,146 on time.

### M5a — complaints per 100 orders

```sql
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
```

`complaint_count` is built in the mart, and the choice of source is itself a decision:

```sql
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
```

| Segment | Numerator (complaints) | Denominator (orders) | Value |
| --- | --- | --- | --- |
| materially late orders | 94 | 349 | **26.9 per 100** |
| on-time orders | 82 | 1,146 | **7.2 per 100** |

A 3.7× difference. **Null handling:** `complaint_count` is `COALESCE(..., 0)` at mart build, so an
order with no complaints contributes zero to the numerator and one to the denominator, which is the
correct treatment for a rate per order.

**Caveat as published.** *"support-ticket interactions attributed to an order; excludes 3 tickets
with no order_id"* — the rule `tickets.unjoinable` reports this every run.

### M5b — interventions per 100 orders

```sql
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
```

| Segment | Numerator (interventions) | Denominator (orders) | Value |
| --- | --- | --- | --- |
| materially late orders | 94 | 349 | **26.9 per 100** |
| on-time orders | 310 | 1,146 | **27.1 per 100** |

**Caveat as published.** *"if these two rates are equal, intervention effort is not risk-targeted"*

The two rates are equal to within a rounding place. Operations is spending intervention effort at
the same rate on orders that are fine as on orders that are not, which is the evidence that
interventions are not currently risk-targeted. It also means no causal read of intervention
effectiveness is available from this data: with no control group and near-identical application
rates, any raw comparison confounds "was intervened on" with "was already in trouble". See
ASSUMPTIONS U-3.

A presentational note for anyone reading the table: the complaint numerator for late orders and the
intervention numerator for late orders are both 94. They are counts of different things from
different source files that happen to coincide at this run date. Do not read the coincidence as a
relationship.

### How to hand-check M5

1. From `customer_interactions.csv`, keep rows with a non-null `order_id` and
   `interaction_type = 'SUPPORT_TICKET'`, count per order.
2. From `order_interventions.csv`, count rows per order.
3. Join both to the 1,495 measurable orders, filling absent orders with zero.
4. Split on `delay > 10` and sum: complaints 94 / 82, interventions 94 / 310.
5. Divide by the group sizes and multiply by 100: 94/349 → 26.9, 82/1,146 → 7.2,
   94/349 → 26.9, 310/1,146 → 27.1.
6. Sanity check: 349 + 1,146 = 1,495.

---

## Why M1 ships with two definitions

The pipeline does not choose between the stakeholder definitions of "late". This is the single most
consequential design decision in the project, so it is recorded here as well as in decision log
D-001.

`sources/data/client_metric_definitions.json` records four stakeholders holding four different
positions:

| Stakeholder | Their definition |
| --- | --- |
| VP Operations | any delivered order after the promised ETA is late |
| Support Lead | only more than 10 minutes beyond ETA is *meaningfully* late |
| Finance | cancelled and refunded orders must not count in operational performance |
| Data Team | delivered orders with a non-null actual delivery time |

The same file states outright that **no canonical KPI owner is formally documented**.

Applied to the identical rows, these positions produce materially different headline numbers:

| Definition | Late rate |
| --- | --- |
| delivered, delay > 0 | **56.39%** — reproduces the leadership claim exactly |
| delivered, delay > 10 min | **23.34%** |
| all orders, unmeasurable counted late | 59.25% |

Median delay is **1.41 minutes**. That single figure is why the two headline rates diverge so far:
the strict rate is dominated by orders late by seconds, which no customer experiences as a failure
and no investment would sensibly target.

The Finance and Data Team positions are not competing thresholds — they are population rules, and
both are already applied, in the `is_measurable` definition at the top of this page. What remains
genuinely contested is the threshold, and that is a policy question, not an engineering default.

**So the pipeline publishes both, side by side, each with its own numerator, denominator and
caveat, and raises `kpi.definition_owner` as a permanent `UNKNOWN` check.** A pipeline that picks
one number here is not being decisive; it is concealing an unresolved business decision inside a
transform, where no downstream consumer can see that a choice was made at all. Publishing both makes
the ambiguity a visible input to the decision rather than a silent assumption inside it.

Two supporting details make the ambiguity cheap to resolve rather than permanent:

- The 10-minute threshold is the Support Lead's stated figure, not a recommendation from this
  analysis (ASSUMPTIONS A-9). The dashboard publishes the full 0–30 minute sensitivity curve
  precisely so that no single threshold is load-bearing.
- The threshold is configuration, not code: `MATERIAL_LATE_THRESHOLD_MIN` in `.env`, read through
  `Config.material_late_threshold_min` and injected as `%(material_threshold)s`.

**To close this.** Once a named owner ratifies a definition, set `MATERIAL_LATE_THRESHOLD_MIN` to the
ratified value and demote `kpi.definition_owner` from an `UNKNOWN` rule to a `FAIL` rule asserting
that the ratified definition is the one applied. At that point the second published definition
becomes redundant and can be dropped. Until then, two numbers is the accurate answer, and one number
would be a choice presented as a measurement.
