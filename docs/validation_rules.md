# Validation Rules

The rule set that stands between the warehouse and anything published, what each rule checks, who
owns the underlying problem, and what each one reported on run date **2026-08-29**.

Rules live in two modules. `src/flasheats/validate/rules.py` holds the eight single-source checks,
which run against a dataframe. `src/flasheats/validate/cross_source.py` holds the seven cross-source
checks, which query the warehouse directly because their whole purpose is to compare one system
against another. `src/flasheats/validate/engine.py` runs both sets and applies the gate.

Every outcome is written to `meta.validation_results` — one row per rule per run, with the observed
value, the threshold, the owner and the detail string. Validation results are data, not log lines,
so the gate is queryable and trendable rather than something you reconstruct by reading `logs/`.

```sql
CREATE TABLE IF NOT EXISTS meta.validation_results (
    result_id    BIGSERIAL PRIMARY KEY,
    run_id       TEXT        NOT NULL,
    run_date     DATE        NOT NULL,
    rule_id      TEXT        NOT NULL,
    severity     TEXT        NOT NULL CHECK (severity IN ('FAIL','WARN','UNKNOWN')),
    status       TEXT        NOT NULL CHECK (status IN ('PASS','WARN','FAIL','UNKNOWN')),
    scope        TEXT        NOT NULL,
    observed     NUMERIC,
    threshold    NUMERIC,
    detail       TEXT,
    owner        TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Note that `severity` and `status` are separate columns. Severity is the rule's declared class — what
this rule is *allowed* to do to the run. Status is what actually happened this time. A rule declared
`WARN` that finds nothing reports `PASS`; it does not report `WARN` merely because that is its
class. Nine of the fifteen rules below are declared `WARN` and four of those passed cleanly on
this run.

---

## The severity contract

Four states, not the usual pass/fail binary.

| Severity | Effect on the run | When it is used |
| --- | --- | --- |
| **FAIL** | Blocks publication. The run aborts and nothing is written to `metrics.kpi`. | The metric cannot be trusted at all: a required column is gone, timestamps are internally contradictory, the measurable population has collapsed, or the extract is stale enough to republish an old number as today's. |
| **WARN** | Recorded and carried forward onto the report; the run continues. | A known, accepted defect operating under a stated cleaning rule. The number is still publishable, but only alongside the statement of what is wrong with it. |
| **UNKNOWN** | Recorded and carried forward; the run continues. Never silently upgraded to PASS. | The check cannot be evaluated at current data coverage. The honest answer is neither yes nor no. |
| **QUARANTINE** | Not a gate severity. Rows that cannot be admitted at the target grain are diverted to `staging.quarantine_orders` with a reason code, and the volume is then reported by a rule. | Row-level rejection during the staging transform, where a rule-level pass/fail would be too coarse. |

The gate itself is deliberately short, in `engine.py`:

```python
def gate(ctx, results: list[dict], report_path: Path) -> dict:
    """The publish gate.

    Only a FAIL blocks. WARN and UNKNOWN are carried forward onto the report so the consumer sees
    exactly what was known to be wrong with the number they are being handed.
    """
    counts = pd.Series([r["status"] for r in results]).value_counts().to_dict()
    failed = [r for r in results if r["status"] == "FAIL"]
    overall = "FAIL" if failed else ("WARN" if counts.get("WARN") or counts.get("UNKNOWN") else "PASS")
```

Two consequences worth stating plainly:

- A run with any `WARN` or `UNKNOWN` cannot report an overall status of `PASS`. The best it can
  report is `WARN`. Publication proceeds, but never under a clean bill of health.
- A check that raises an exception is itself recorded as a `FAIL`, not allowed to crash the run:

```python
try:
    outcome: RuleResult = rule.check(**inputs)
except Exception as exc:  # a broken check is itself a finding, not a crash
    outcome = RuleResult("FAIL", None, None, f"check raised {type(exc).__name__}: {exc}")
```

A broken check is a finding about the pipeline, and it blocks publication for the same reason a
failed check does: in neither case can the number be vouched for.

### Result for this run

**Overall status: WARN — 8 PASS, 5 WARN, 2 UNKNOWN, 0 FAIL, across 15 rules.** Publication
proceeded. The full machine-readable record is at `out/validation_report.json`.

---

## What the gate does not catch: source schema drift

One class of defect is checked before the gate ever runs, and the reason is worth stating because it
is not obvious.

`assert_contract()` in `src/flasheats/ingest/sqlite_source.py` compares each extracted dataframe
against `SOURCE_CONTRACT` and raises `ValidationFailed` — exit code 1 — before anything is landed:

```python
def assert_contract(ctx, table: str, df: pd.DataFrame) -> None:
    """Fail the run if the source stopped sending a column we depend on.

    This is deliberately fail-fast and pre-landing: a schema change upstream is not something to
    warn about and carry on from, because every metric downstream would still compute — just over
    nulls, producing a confidently wrong number instead of an error.
    """
```

It cannot live in the gate. The `raw` tables persist between runs and are rebuilt per run-date
partition, so a column dropped upstream does not arrive as an *absent* column — it arrives as an
all-NULL one, because the table already exists with that column defined. A gate check asking "is
this column present?" would look at the warehouse, find the column, and pass, while every value
underneath it is null. The only place the absence is still visible is in the dataframe as extracted,
before it touches the warehouse, which is where the contract is asserted.

`orders.required_columns` remains in the gate as a second line of defence: it covers sources that do
not pass through this path and the case where the raw table is being created for the first time.

---

## The fifteen rules

`observed` is the numeric value the check recorded in `meta.validation_results` for this run. Where
the units are not obvious from the count, the detail column says what is being counted.

### Single-source rules — `src/flasheats/validate/rules.py`

| Rule ID | Severity | Scope | Owner | What it checks | Status | Observed |
| --- | --- | --- | --- | --- | --- | --- |
| `orders.required_columns` | FAIL | `raw.orders` | Data Engineering | All eight columns the downstream model depends on are present in the source extract. Schema drift breaks every metric, so it is caught before anything else runs. | **PASS** | 0 missing (all 8 present) |
| `orders.delivery_after_creation` | FAIL | `staging.orders` | Data Engineering | No order carries a delivery timestamp earlier than its creation timestamp. A negative order lifespan means the timestamps cannot be trusted at all, and every duration in the model is derived from them. | **PASS** | 0 orders |
| `orders.freshness` | FAIL | `staging.orders` | Platform / Ops | The newest `created_at` is within `FRESHNESS_MAX_AGE_DAYS` (30) of the run date. A stale extract silently republishes yesterday's number as today's, which is worse than publishing nothing. | **PASS** | 1 day (latest `created_at` 2026-08-28 23:33) |
| `orders.measurable_population` | FAIL | `staging.orders` | VP Operations | That enough orders survive to be measured at all: delivered, with both `actual_delivery_at` and `promised_eta`. FAILs outright at zero, and FAILs below 50% of all orders, because a rate computed over a collapsed population is not a performance signal. | **PASS** | 93.4% (1,495 of 1,600; threshold 50) |
| `orders.order_id_unique` | WARN | `raw.orders` | Order Platform team | Whether the *source* is still emitting duplicate `order_id` values. Duplicate writes inflate any volume-based denominator. | **WARN** | 6 rows (3 IDs, two copies each) |
| `orders.conflicting_duplicates` | WARN | `staging.orders` | Order Platform team | Among duplicated orders, how many have copies that *disagree* on a business attribute. A disagreeing duplicate cannot be resolved by the pipeline: picking a copy silently picks an answer. | **WARN** | 3 orders |
| `orders.delivered_has_timestamp` | WARN | `staging.orders` | VP Operations | How many orders marked `delivered` carry no `actual_delivery_at`, and are therefore unmeasurable for the KPI. | **WARN** | 37 of 1,532 delivered (2.4%) |
| `kpi.definition_owner` | UNKNOWN | business | VP Operations (unassigned) | Whether a canonical owner of the "late delivery" definition is documented. Four stakeholders hold four definitions and the source file states no owner exists. | **UNKNOWN** | — (not quantifiable) |

**`orders.measurable_population` exists because of a real failure, not a hypothetical one.** Under
`--chaos missing_column` the pipeline used to pass the gate cleanly and then die in the metrics step
with `float() argument must be a string or a real number, not 'NoneType'`. Every `promised_eta` was
null, so `delay_min` was null for every order, so the measurable population collapsed to zero, so
every rate became a division by nothing — and the error finally surfaced several steps away from the
cause, phrased in a way that named none of it. The rule stops the run at the gate instead, with a
message that names the actual problem:

```python
    if measurable == 0:
        return RuleResult("FAIL", 0, 1, "no measurable deliveries at all — no KPI can be computed")
    if share < 50:
        return RuleResult("FAIL", round(share, 1), 50.0,
                          f"only {measurable} of {total} orders ({share:.1f}%) are measurable; "
                          f"below half, the rate says more about coverage than about performance")
```

The 50% floor is the more interesting half of the rule. Zero measurable orders is an outage and
would eventually announce itself somehow. A population quietly halved would not: the pipeline would
publish a perfectly well-formed rate that had become a statement about coverage rather than about
delivery performance, and nothing in the output would say so. It is owned by VP Operations for the
same reason `orders.delivered_has_timestamp` is — the threshold at which a shrinking population
stops being reportable is an operational judgement, not an engineering one.

Two further rules deserve a note on *where* they are evaluated, because the choice is deliberate.

**`orders.order_id_unique` runs against raw, not staging.** Staging has already applied the agreed
one-row-per-order rule, so a uniqueness check there could never fire — it would report a permanent,
meaningless `PASS` for the rest of the pipeline's life. The question worth asking is whether the
source is *still* emitting duplicates, which is a signal about the upstream system rather than about
our own transform. The docstring says so in the code:

```python
def _order_id_unique(raw_orders: pd.DataFrame = None, **_) -> RuleResult:
    """Deliberately evaluated against RAW, not staging.

    Staging has already applied the agreed one-row-per-order rule, so a uniqueness check there can
    never fire — it would report a permanent, meaningless PASS. The question worth asking is
    whether the SOURCE is still emitting duplicates, which is a signal about the upstream system.
    """
```

It counts rows, not IDs: `raw_orders.duplicated("order_id", keep=False).sum()` returns 6, being the
three duplicated IDs times two copies each. The companion rule `orders.conflicting_duplicates`
counts affected *orders*, which is why it reports 3 for the same underlying defect. Both numbers are
correct; they answer different questions.

**`orders.delivered_has_timestamp` is owned by VP Operations, not by Data Engineering.** The
pipeline can measure the gap but cannot decide how those 37 orders should be treated in the KPI, and
treating them differently moves the headline rate from 56.39% to 59.25%. That is an operational
policy decision, so the rule names the person who has to make it.

### Cross-source rules — `src/flasheats/validate/cross_source.py`

Single-source checks catch broken files. These catch something more dangerous: sources that are each
internally valid but disagree with one another. That is where a metric quietly becomes wrong,
because every individual system looks healthy.

| Rule ID | Severity | Scope | Owner | What it checks | Status | Observed |
| --- | --- | --- | --- | --- | --- | --- |
| `cross.client_kpi_reconciliation` | WARN | staging vs client file | Data Team | Our independently computed strict late count against the client's own derived `order_outcomes.csv`, which already circulates in the business carrying the 56% figure. | **PASS** | 0 delta (843 vs 843) |
| `cross.restaurant_agreement` | WARN | `raw.restaurants` vs `raw.restaurants_csv` | Restaurant Ops | Whether the operational database and the ops-maintained CSV agree on every restaurant's name and cuisine, and whether any restaurant exists in only one of them. Two systems of record for the same entity will drift. | **PASS** | 0 mismatched, 0 missing |
| `cross.dispatch_coverage` | WARN | `staging.orders` vs `staging.dispatch` | Dispatch platform | Whether every order has a dispatch record. A gap silently removes the assignment stage from the lifecycle model for those orders. | **PASS** | 0 gap (1,600 of 1,600 covered) |
| `cross.event_stream_agreement` | WARN | `staging.orders` vs `staging.order_events` | Order Platform team | Whether every order the order database calls delivered also has a `DELIVERED` event in the independent event stream. Two systems both claim to know when an order completed. | **PASS** | 0 disagreements |
| `orders.orphan_foreign_keys` | WARN | `staging.orders` | Order Platform team | Orders referencing a restaurant that does not exist, plus orders with a null `restaurant_id` or `driver_id`. Unresolvable keys break dimensional joins and drop rows from segmented metrics. | **WARN** | 6 (0 orphans + 6 nulls) |
| `tickets.unjoinable` | WARN | `staging.support_tickets` | Support | Support tickets carrying no `order_id`, which can never be attributed to a delivery and so understate the customer impact of late orders. | **WARN** | 3 of 202 |
| `restaurant_status.ready_coverage` | UNKNOWN | `staging.restaurant_status` | Restaurant Ops | Coverage of the food-ready timestamp, and how many of the present ones are recorded after the pickup they precede. Delay attribution below the pickup stage depends entirely on this field. | **UNKNOWN** | 10.0% coverage (160 of 1,600; 60 recorded after pickup) |

**On `cross.client_kpi_reconciliation` passing.** This is the rule that makes the engagement
tractable. Our count of delivered orders past the promised ETA is 843; the client's derived file
says 843. The detail string it writes is the finding itself:

> our strict late count reproduces the client's derived file exactly (843); the 56% claim is
> arithmetically reproducible, so the dispute is over the definition, not the computation

Being able to say the leadership number is *reproducible* is a different and far more useful
statement than saying it is right or wrong. It moves the conversation off arithmetic and onto the
definition, which is where the actual disagreement lives.

---

## Why UNKNOWN is a first-class status

Most validation frameworks offer pass and fail. This one offers four states, and the fourth carries
real weight: two of the fifteen rules are `UNKNOWN` by design, and neither is expected to resolve
without an external change.

The argument is simple. Some questions genuinely cannot be answered with the data available.
Forcing such a question into `PASS` claims a clean result that was never established. Forcing it
into `FAIL` blocks a run over something that is not broken, and — worse — invites someone to
suppress the rule to get the pipeline green again. `UNKNOWN` says the accurate thing: the check ran,
the answer is not available at current coverage, and here is what would make it available.

`UNKNOWN` is enforced in the schema, not merely by convention — it is in the `CHECK` constraint on
`meta.validation_results.status`, and the DDL comment records why:

```sql
-- Validation outcomes are data, not log lines, so the gate is queryable and trendable.
-- UNKNOWN is a first-class status: the check could not be evaluated at current coverage.
```

### `kpi.definition_owner` — an unresolved business decision, not a data defect

This rule is permanently `UNKNOWN` and returns its result without querying anything:

```python
def _kpi_definition_owner(orders: pd.DataFrame, **_) -> RuleResult:
    """The single most important finding in this dataset, encoded as a standing check.

    client_metric_definitions.json records four stakeholders with four different definitions of
    'late' and states no canonical KPI owner is documented. Until that is resolved, the headline
    number is a choice, not a measurement — so this rule is permanently UNKNOWN by design and
    forces the ambiguity onto the report instead of letting the pipeline pick a side.
    """
```

There is nothing to measure. The defect is the absence of a documented owner, and no volume of data
will supply one. Encoding it as a standing check does two things a comment in a README would not: it
puts the ambiguity on the validation report attached to every run, next to the number it qualifies,
and it gives the resolution a concrete mechanical form. Once an owner ratifies a definition, this
rule is demoted from `UNKNOWN` to a `FAIL` rule asserting that the ratified definition is the one
applied. The ambiguity does not quietly expire; it is closed by someone.

### `restaurant_status.ready_coverage` — an instrumentation gap, not an analysis gap

This rule reports `UNKNOWN` unconditionally, and its observed value is a coverage percentage rather
than a defect count:

```python
    return RuleResult(
        "UNKNOWN", round(pct, 1), 100.0,
        f"food-ready timestamps exist for {with_ready} of {orders} orders ({pct:.1f}%), and "
        f"{impossible} of those are recorded AFTER pickup. Kitchen-versus-driver attribution "
        f"cannot be resolved at this coverage — an instrumentation gap, not an analysis gap",
    )
```

For this run: 160 of 1,600 orders (10.0%) carry a food-ready timestamp, and 60 of those are recorded
*after* the pickup they are supposed to precede, which is physically impossible. The field is
manually entered by restaurant staff.

This blocks the most valuable question in the engagement. M3 attributes 81.2% of excess delay to the
assigned→pickup stage, but splitting that stage into *the kitchen was slow* versus *the driver
arrived early* requires exactly this timestamp. At 10% coverage with 37% of the present values
impossible, it cannot be settled. Reporting it as `WARN` would suggest the analysis simply needs
more care; reporting it as `FAIL` would suggest something is broken that could be repaired in the
pipeline. Neither is true. What is true is that the instrumentation does not exist yet, and the fix
is a system-generated food-ready event from the restaurant tablet — an engineering ask on the
client's side, not a task for this pipeline.

The metric it constrains, M4b, is published anyway, carrying a `LOW CONFIDENCE` marker and its own
coverage count, so the rule and the metric tell the reader the same thing from two directions.

---

## Quarantine: `staging.quarantine_orders`

Quarantine is the row-level counterpart to the rule-level gate. A rule answers "is this dataset
admissible?"; quarantine answers "which specific rows could not be admitted, and why?".

```sql
-- Rejected rows are never deleted. They are moved here with a reason so the volume and the
-- nature of what we dropped stays visible and trendable instead of vanishing silently.
CREATE TABLE IF NOT EXISTS staging.quarantine_orders (
    order_id       TEXT,
    reason_code    TEXT NOT NULL,
    reason_detail  TEXT,
    payload        JSONB,
    run_date       DATE NOT NULL
);
```

The full rejected row is preserved verbatim in `payload` as JSON, alongside a machine-readable
`reason_code` and a human-readable `reason_detail`. The table is partitioned by `run_date` and the
writer clears only its own `(run_date, reason_code)` slice before inserting, so a rerun is idempotent
without destroying other runs' evidence:

```python
cur.execute(
    "DELETE FROM staging.quarantine_orders WHERE run_date = %s AND reason_code = %s",
    (ctx.run_date, reason_code),
)
```

### Reason codes in use

| Reason code | Written by | Meaning |
| --- | --- | --- |
| `DUPLICATE_ORDER_ID` | `build_orders` in `src/flasheats/transform/staging.py` | Second copy of a duplicated `order_id`; the first copy is retained at order grain. Three such rows this run. |

### Why rejected rows are never deleted

Three reasons, in ascending order of importance.

**The volume is itself a metric.** A quarantine table partitioned by run date is trendable.
"Three duplicates this run" is unremarkable; "three duplicates a run for six months, then ninety" is
an incident, and you can only see the second if the rejected rows were kept. `drop_duplicates()`
throws that signal away permanently.

**The decision is reviewable by the person who owns it.** The three duplicated orders here are not
harmless double-writes — their copies *disagree*, with `traffic_bucket` differing between them (for
example `severe` against `medium` for `O00120`). The pipeline cannot resolve that: choosing a copy
silently picks a traffic condition, and therefore silently picks an answer. It keeps the first copy
for deterministic continuity, sets `had_conflicting_dupe` on the surviving row so the qualifier
travels downstream with the data, and puts the losing copy in quarantine where the Order Platform
team can see precisely what was discarded and adjudicate it.

**Deletion destroys the evidence that a decision was made at all.** This is the general principle
the whole pipeline is built on and it recurs at every layer: `raw` lands every column as `TEXT`
exactly as the source emitted it so that a parse failure remains distinguishable from a transport
failure; `final_status_raw` is retained beside the normalised `final_status`; `has_negative_duration`
flags impossible rows rather than dropping them. Quarantine is the same principle applied to whole
rows. The comment in the staging transform states the reasoning at the point of the decision:

```python
    # Not all duplicates are equal. Rows identical on every business attribute are a safe
    # double-write and we keep the first. Rows that DISAGREE (this source has 3 such pairs, where
    # traffic_bucket differs) cannot be resolved by the pipeline: choosing a copy silently picks
    # an answer. We keep the first for continuity, FLAG it, and quarantine the losing copy so the
    # conflict is reviewable by the source owner.
```

Three rows out of 1,600 will not move any KPI. The mechanism is what is being built, not the fix:
the same pattern at 3% of volume would move the KPI, and it is exactly the kind of defect that
passes unnoticed unless something is designed to notice it.

---

## Adding a new rule

Rules are data, not scattered `if` statements. A rule is a frozen dataclass pairing metadata with a
check function; adding one means appending a `Rule` to a list, and the engine, the persistence, the
logging and the gate all pick it up with no further change.

```python
@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: str               # FAIL | WARN | UNKNOWN
    scope: str
    owner: str
    rationale: str
    check: Callable[..., RuleResult]


@dataclass(frozen=True)
class RuleResult:
    status: str                 # PASS | WARN | FAIL | UNKNOWN
    observed: float | None = None
    threshold: float | None = None
    detail: str = ""
```

**The steps.**

1. Write a check function taking `**_` and returning a `RuleResult`. Single-source checks receive
   the dataframes passed to `evaluate` as keyword arguments (`orders`, `raw_orders`); cross-source
   checks take `ctx=None` and query the warehouse through `ctx.conn`, since the run context is
   injected by the engine rather than at each call site. Always accept `**_` so that adding a new
   input later does not break existing checks.
2. Return a status the check actually established. `PASS` when the condition holds, the rule's own
   severity when it does not, and `UNKNOWN` when the check could not be evaluated — the pattern
   `_conflicting_duplicates` uses when the flag column is not present at the stage it was given.
3. Populate `observed` and `threshold` as numbers wherever the finding is quantifiable. They are
   stored as `NUMERIC` in `meta.validation_results` and are what makes the rule trendable across
   runs. Write `detail` as a sentence a non-engineer can act on; it is what appears on the report.
4. Append the `Rule` to `ORDER_RULES` or `CROSS_SOURCE_RULES`.

**Four conventions worth following.**

- **Name a real owner.** Most of the issues in this dataset are unresolved business rules, not
  technical defects, and a pipeline that quietly fixes them is hiding the decision that someone
  actually needs to make. `owner` is the person the finding escalates to, so
  `orders.delivered_has_timestamp` names VP Operations and `tickets.unjoinable` names Support.
- **Write the rationale in terms of the number it protects.** `rationale` should say what breaks
  downstream, not what the code does — "a stale extract silently republishes yesterday's number as
  today's" rather than "checks freshness".
- **Choose severity by consequence, not by severity of feeling.** `FAIL` is reserved for the cases
  where no publishable number survives. If the metric can still be published with a stated caveat, it
  is a `WARN`.
- **Thresholds belong in config.** `freshness_max_age_days` and `material_late_threshold_min` are
  read from `Config`, not written into the rule, so policy can change without a code change. The
  comment in `config.py` puts it directly: *"Thresholds are config, not magic numbers buried in
  rules."*
