# Workflow Model

How the raw estate is reorganised into a model of the **delivery process**, what each table means,
what travels with a row, and what the model deliberately refuses to contain.

Companion diagrams: `docs/diagrams/erd.mmd` (structure), `docs/diagrams/workflow_states.mmd`
(the state machine), `docs/diagrams/pipeline_dag.mmd` (how it is built).

---

## 1. Why the model is reorganised around the process, not the sources

The client's data is organised the way their *systems* are organised. Orders live in the order
platform's SQLite database, assignment lives in the Dispatch API, kitchen readiness lives in a
manually maintained CSV from restaurant ops, movement lives in a nested JSON export from the driver
app, and customer friction is split across three more CSVs. No single system sees a whole delivery.

That shape answers "what does system X know?" It cannot answer the question leadership actually
asked — *"deliveries are late more often; where is the delay coming from?"* — because the delay is
not inside any one system. It is in the **gaps between** them: the minutes between an order being
created and dispatched, between dispatched and collected, between collected and delivered. Those
intervals only exist once timestamps owned by four different teams are placed on one timeline.

So `marts` is modelled on the business process rather than by source system:

- **one row per order** carrying every stage timestamp side by side, so an interval is a
  subtraction rather than a join written freshly by each analyst;
- **one row per observed state transition**, keeping the source system on the row, because when two
  systems disagree about when something happened, *who said what* is the entire investigation;
- **conformed dimensions** for restaurant, driver and customer, so any metric can be segmented by
  tenure, cuisine or city without re-deriving those attributes.

The payoff is that `metrics` never touches a source table. Every published KPI reads
`marts.fct_order_lifecycle`, so a stage duration has exactly one definition in the project and
changing it changes every number that depends on it at once.

The layering is `raw` (as-received TEXT, no casting) → `staging` (typed, normalised, deduped, with
`quarantine_*` siblings) → `marts` (this model) → `metrics` (published KPI), with `meta` holding the
pipeline's record of itself: `run_log`, `source_manifest`, `validation_results`.

---

## 2. Entities, events and states

Three things are modelled, and they are deliberately kept apart.

**Entities** are the actors that persist between orders: restaurant, driver, customer. They are
slowly changing descriptive context — cuisine, vehicle type, tenure, location — and they belong in
dimensions so that a delay can be attributed to a *kind* of actor rather than only to one order.

**Events** are things that were observed to happen at a point in time by a named system. They are
append-only, they overlap between systems, and they occasionally contradict each other. They belong
in an event fact where that overlap stays visible.

**States** are what an order *is* at a point in the process: created, assigned, ready, picked up,
delivered — or cancelled. A state is not a row that arrives; it is inferred from the events and
timestamps above. The state machine is drawn in `docs/diagrams/workflow_states.mmd`.

The lifecycle fact is the collapse of that state machine onto the order grain: one row per order,
one column per state entry time, one column per interval between them.

---

## 3. Stages, and which system observes each one

| # | Stage | Column | Observed by | Coverage |
| --- | --- | --- | --- | --- |
| 1 | Order created | `created_at` | SQLite `orders` | 1,600 orders |
| 2 | Driver assigned | `assigned_at` | Dispatch API | 1,600 orders |
| 3 | Food ready | `ready_at` | `restaurant_status.csv`, status `ready` | **160 of 1,600** |
| 4 | Collected | `pickup_at` | SQLite `orders` | 1,600 orders |
| 5 | Delivered | `delivered_at` | SQLite `orders` | 1,495 measurable |
| — | Promise | `promised_eta` | SQLite `orders` | the benchmark, not a stage |

Four separate systems have to agree on a single order for a full lifecycle row to exist. Stage 3 is
the weak link and it is the one the business most needs: the kitchen-ready moment exists in **no**
system-generated stream, only in a manually typed CSV covering 10% of orders. That is recorded as
gap G-04 in `docs/source_map.md` and is why the kitchen-versus-courier split is reported as
`UNKNOWN` rather than estimated.

Where the same order appears more than once in `restaurant_status`, the **earliest** `ready` wins,
chosen explicitly with `DISTINCT ON` ordered by timestamp rather than left to join order.

---

## 4. Grain of every marts table

Grain is stated per table because a fact whose grain is ambiguous will eventually be summed twice.

| Table | Grain | Rows | Notes |
| --- | --- | --- | --- |
| `marts.fct_order_lifecycle` | one row per `order_id` per `run_date` | 1,600 | 1,495 measurable; the table the business queries |
| `marts.fct_order_events` | one row per observed state transition per `run_date` | 10,121 | `order_platform` 4,955, `driver_app` 4,664, `restaurant_ops` 502 |
| `marts.dim_restaurant` | one row per `restaurant_id` per `run_date` | 60 | carries `manual_status_updates` — the entry mechanism behind G-04 |
| `marts.dim_driver` | one row per `driver_id` per `run_date` | 120 | `experience_months` banded into `0-5m / 6-11m / 12-23m / 24m+` |
| `marts.dim_customer` | one row per `customer_id` per `run_date` | 900 | location only |

Every table is partitioned by `run_date` and every build is `DELETE` then `INSERT` scoped to that
one partition, so a rerun replaces exactly one logical day and is idempotent.

Driver experience banding is a modelling decision, not a convenience: raw month counts are too
granular to segment a KPI by, and the cut points are the ones operations already uses to talk about
tenure.

---

## 5. Derived durations, and why NULL propagation matters

Five durations are computed once, on the fact, in minutes:

| Duration | Interval | Reads as |
| --- | --- | --- |
| `dispatch_latency_min` | `created_at` → `assigned_at` | how long before anyone was assigned |
| `assign_to_pickup_min` | `assigned_at` → `pickup_at` | driver accepts to food in hand |
| `idle_wait_min` | `ready_at` → `pickup_at` | food sitting on the pass |
| `transit_min` | `pickup_at` → `delivered_at` | road time |
| `end_to_end_min` | `created_at` → `delivered_at` | what the customer experiences |

`dispatch_latency_min`, `assign_to_pickup_min` and `transit_min` partition the journey without
overlap and are what delay attribution sums over. `idle_wait_min` is deliberately **nested inside**
`assign_to_pickup_min`, not a fourth segment: it is the part of the courier's wait that belongs to
the kitchen, and it is the one measure that depends on the 10%-coverage source. `end_to_end_min` is
the whole span and is reported separately.

**Each duration is NULL when either endpoint is missing.** This is the single most consequential
choice in the model. The alternative — `COALESCE(..., 0)` — would turn "we never observed when the
food was ready" into "the food was ready the instant it was collected", which is a factual claim the
data does not support, and it would quietly drag every average toward zero in proportion to how
badly instrumented a stage is. A gap must propagate as an **absence**, so that a metric computed
over it either excludes the row or reports reduced coverage, and never silently reports a better
number because a system was not reporting.

`is_measurable` makes the consequence explicit on the row: an order counts only when
`final_status = 'delivered'` **and** `delay_min IS NOT NULL`. 1,495 of 1,600 orders qualify; the
rest are counted and reported as a caveat rather than dropped without trace.

What the durations produced, on materially late orders versus on-time orders:

| Stage | Share of excess delay | Median excess |
| --- | --- | --- |
| Assigned → pickup | **81.2%** | +17.0 min |
| Transit | 18.8% | +3.9 min |
| Dispatch latency | −1.0% | −0.2 min |

Late orders are dispatched marginally *faster* than on-time ones. Dispatch is not the constraint,
and an ETA prediction model would not move any of the three numbers above.

---

## 6. Data-quality flags travel with the row

Quality findings are columns on the fact, not entries in a log that a consumer will never read:

- **`had_conflicting_dupe`** — 3 orders arrived twice with *different* attribute values
  (`traffic_bucket` differs between copies). The first copy is kept for continuity, the losing copy
  is written to `staging.quarantine_orders` with reason `DUPLICATE_ORDER_ID`, and the survivor is
  flagged. A plain de-duplication would have picked a traffic condition at random with nothing
  downstream able to tell.
- **`has_negative_duration`** — 79 orders have at least one physically impossible stage duration,
  meaning clock skew or manual entry error. Notably, 57 of the 153 computable idle-wait values are
  negative: the driver collected the food before the restaurant recorded it as ready. The flag lets
  any metric exclude those rows *knowingly* instead of averaging nonsense. A NULL duration is not a
  negative one, so an uninstrumented stage never trips this flag.
- **`is_measurable`** — whether this row can legitimately enter a rate at all.

Because they sit on the row, every downstream metric can decide for itself, and any published number
can be traced back to exactly which rows it did and did not trust. Nothing is deleted to make a
number look cleaner.

---

## 7. Interaction → intervention → outcome

The model carries the causal chain the client cannot currently see: the customer reacts, operations
responds, and the delivery ends somehow. All three live on the same fact row, so they can be
correlated without a join:

1. **Interaction** — `interaction_count` and `eta_view_count` from `customer_app_actions.csv`.
   Repeated `ETA_VIEWED` is an anxiety signal that costs the customer nothing to emit, so it appears
   long before a complaint does.
2. **Complaint** — `complaint_count`, counted from `customer_interactions.csv` where
   `interaction_type = 'SUPPORT_TICKET'`, **not** from `support_tickets.csv`. Three tickets carry no
   `order_id` and can never be attributed; counting from the ticket file would inflate some orders
   and silently drop others.
3. **Intervention** — `intervention_count` and `intervention_types` from `order_interventions.csv`:
   what operations actually did about an at-risk order.
4. **Outcome** — `final_status`, `delay_min`, `is_late_strict`, `is_late_material` on the same row.

Counts are coalesced to zero here, and that is correct in a way the durations are not: an order with
no matching interaction row genuinely had zero interactions. Absence of an event is evidence;
absence of a timestamp is not.

This chain is what makes "does intervening help?" answerable, and it is why intervention targeting
is published as a metric in its own right rather than assumed effective.

---

## 8. What the model deliberately does NOT contain

**GPS pings.** `driver_events.json` flattens 120 drivers into 10,035 events, of which **5,371 are
`gps_ping`**. They are excluded from `fct_order_events` at the union. A ping is telemetry: it marks
no change of state, it answers no question the model was built to answer, and at more than half the
driver stream it would swamp the event fact and make every per-order event count meaningless. The
pings stay available in `staging.driver_events` for any future route or dwell analysis — they are
excluded from the *model*, not from the warehouse.

**`order_outcomes.csv` as an input.** This file is presented alongside the raw ones but it is a
**derived** artefact produced by the client's own data team, and it hardcodes one contested
definition of "late": 843 late over 1,495 measurable = **56.39%**, which is precisely the disputed
figure leadership is quoting. Consuming it would mean re-publishing the client's answer back to them
as though the pipeline had independently confirmed it. Instead it is landed into
`staging.client_order_outcomes` and used for **one purpose only** — the
`cross.client_kpi_reconciliation` check, which compares it against the independently computed KPI.
That lets the pipeline say something much stronger than agreement: the leadership figure is
*reproducible*, and it is reproducible only under one of four competing stakeholder definitions.
Nothing in `marts` or `metrics` reads from it.

**A single ratified "late" rate.** The model computes `is_late_strict` and `is_late_material`
separately and publishes both, because no canonical KPI owner is documented. Collapsing them inside
a transform would hide an unresolved business decision in engineering code.

**Anything imputed.** No missing timestamp is back-filled, estimated or interpolated. Where the data
cannot answer a question — principally the kitchen-versus-courier split at 10% coverage — the model
returns NULL and the validation gate records `UNKNOWN`, which is a first-class status precisely so
that an instrumentation gap is never laundered into a confident number.
