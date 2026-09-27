# Decision Log

Every non-obvious choice this pipeline makes, why it was made, and what it would take to change it.
The point of this file is that none of these are technical defaults — each one moves a number that
someone will present to leadership.

---

## D-001 — Publish both definitions of "late" instead of choosing one

**Context.** `sources/data/client_metric_definitions.json` records four stakeholders:

| Stakeholder | Their definition |
| --- | --- |
| VP Operations | any delivered order after the promised ETA is late |
| Support Lead | only more than 10 minutes beyond ETA is *meaningfully* late |
| Finance | cancelled/refunded orders must not count in operational performance |
| Data Team | delivered orders with a non-null actual delivery time |

The file explicitly notes: *"No canonical KPI owner is formally documented."*

**Measured impact.** Same rows, different definitions:

| Definition | Late rate |
| --- | --- |
| delivered, delay > 0 | **56.39%** — reproduces the leadership claim exactly |
| delivered, delay > 10 min | **23.34%** |
| all orders, unmeasurable counted late | 59.25% |

Median delay is **1.41 minutes**.

**Decision.** Publish the strict and material rates side by side, each with its own numerator and
denominator, and raise `kpi.definition_owner` as a permanent `UNKNOWN` check.

**Why.** A pipeline that picks one number here is not being decisive, it is concealing an unresolved
business decision inside a transform. The threshold is a policy question owned by VP Operations, not
an engineering default. Publishing both makes the ambiguity a visible input to the decision.

**To change this:** once an owner ratifies a definition, set `MATERIAL_LATE_THRESHOLD_MIN` and demote
`kpi.definition_owner` from `UNKNOWN` to a `FAIL` rule asserting the ratified rule is applied.

---

## D-002 — Conflicting duplicates are flagged, not silently resolved

**Context.** `orders` has 1,603 rows for 1,600 order IDs. Three IDs appear twice. The pairs are
**not identical** — `traffic_bucket` differs between copies (e.g. `severe` vs `medium` for `O00120`).

**Decision.** Keep the first copy at order grain for continuity, write the losing copy to
`staging.quarantine_orders` with reason `DUPLICATE_ORDER_ID`, and set a `had_conflicting_dupe` flag
on the surviving row. Report the count as a `WARN`.

**Why.** `drop_duplicates("order_id")` is the obvious move and it is wrong in a specific way: it
picks a traffic condition at random and no downstream consumer can tell it happened. Three rows will
not move the KPI — but the same pattern at 3% of volume would, and the mechanism that would let it
pass unnoticed is what is being fixed here.

---

## D-003 — Raw is landed as TEXT with no casting

**Decision.** The `raw` schema stores every column as `TEXT`, exactly as the source emitted it.
All casting happens on the way into `staging`.

**Why.** Casting is a judgement call. `actual_delivery_at` has 105 nulls and mixed precision
(minute-level and microsecond-level strings from two different writers). If the cast happens during
retrieval, a parse failure is indistinguishable from a transport failure, and the evidence of what
the source actually sent is destroyed. Landing verbatim keeps retrieval auditable and lets parse
failures surface as data quality findings in the validation gate.

---

## D-004 — Unmeasurable deliveries are excluded from both numerator and denominator

**Context.** 37 orders are marked `delivered` but carry no `actual_delivery_at`.

**Decision.** Exclude them from the M1 population entirely and report the excluded count as a caveat
attached to the metric.

**Why.** There are three options and each is a different claim: count them late (KPI → 59.25%,
asserts a fact not in evidence), count them on-time (understates), or exclude (states honestly that
2.4% of deliveries cannot be assessed). Only the third is defensible without new data. The caveat
travels with the metric so the exclusion cannot be forgotten.

---

## D-005 — A full snapshot per run, not incremental extraction

**Context.** `orders` has no reliable `updated_at` column, so there is no watermark to extract from.

**Decision.** Reload a full snapshot into the run-date partition on every run.

**Why.** Incremental extraction without a trustworthy watermark silently misses late-arriving
updates. At 1,600 rows a full reload costs nothing, and it makes reruns trivially idempotent. This
is recorded as a source gap in `docs/source_map.md`; it would need revisiting at a volume where a
full scan stops being free.

---

## D-006 — `UNKNOWN` is a first-class validation status

**Decision.** The gate has four states — `PASS`, `WARN`, `FAIL`, `UNKNOWN` — rather than the usual
pass/fail binary.

**Why.** Some questions genuinely cannot be answered with the data available. Splitting the
assigned→pickup delay into *kitchen was slow* versus *driver arrived early* requires restaurant
READY timestamps, which exist for only 160 of 1,600 orders and are 37% negative where present.
Forcing that into `PASS` or `FAIL` would misrepresent it. `UNKNOWN` says the honest thing: this is
an instrumentation gap, and the answer is not available at current coverage.

---

## D-007 — Dimensions are built directly from `raw`, bypassing `staging`

**Context.** The warehouse is described as `raw → staging → marts`, and the three *facts* follow
that path. The three dimensions (`dim_restaurant`, `dim_driver`, `dim_customer`) do not — they are
built straight from `raw` in `sql/transform/020_marts.sql` with inline casts.

**Decision.** Keep it, and document it as a deliberate exception rather than claim a layering the
code does not follow.

**Why.** `staging` exists to hold work that has to happen *before* modelling and that can fail:
type coercion that may reject rows, cross-source key normalisation, deduplication, and quarantine.
The dimension sources have none of that. They are small, single-sourced, have no duplicate keys and
no cross-source reconciliation, so a staging hop for them would contain a type cast and nothing
else — a layer that exists only to satisfy a diagram.

The modelling that *is* applied to them — banding `experience_months` into tenure buckets, casting
`manual_status_updates` to a boolean, trimming names — is dimensional attribute design, which
belongs in the marts layer by definition.

**To change this:** the moment a dimension needs conflict resolution across two sources (for
example if `restaurants.csv` and the `restaurants` table start disagreeing — currently checked by
`cross.restaurant_agreement` and currently in agreement), it earns a staging table, because that
reconciliation can reject rows and rejected rows need somewhere to go.

---

## D-008 — Source schema drift is caught at ingest, not at the validation gate

**Context.** Fault-injecting a dropped column (`--chaos missing_column`) exposed a real defect. The
run passed the validation gate and then crashed several steps later inside metric computation with
`float() argument must be a string or a real number, not 'NoneType'`.

**Root cause.** The `raw` tables persist between runs. When a column stops arriving from the
source, the table still *has* that column — every value for the new run is simply NULL. A gate rule
asking "is this column present?" therefore passes, every downstream metric still computes, and the
pipeline produces a confidently wrong number instead of an error.

**Decision.** Enforce a schema contract at ingest, against the dataframe as extracted, before
anything is written. `assert_contract()` in `src/flasheats/ingest/sqlite_source.py` checks
`SOURCE_CONTRACT` and raises `ValidationFailed` (exit 1) with a message naming the missing column
and stating that nothing was landed. `orders.required_columns` stays in the gate as a second line
of defence.

**Also added:** `orders.measurable_population`, a FAIL rule that stops the run when the measurable
population collapses to zero or falls below half of all orders. A rate computed over a collapsed
denominator is not a performance signal, and failing at the gate names the real problem where the
original crash did not.

**Why this matters beyond the injected fault.** The failure was not that the pipeline broke — it
was that it very nearly *didn't*. Schema drift is a routine upstream event, and the shape of this
bug is one where the run goes green and a wrong number reaches a decision-maker.
