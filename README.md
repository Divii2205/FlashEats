# FlashEats — From Fragmented Client Systems to a Defensible Late-Delivery KPI

> **Client escalation:** *"Late deliveries are increasing and customers say our ETA is unreliable.
> Figure out what is happening before we invest in a new AI delay-prediction system."*

A small, repeatable pipeline that takes four fragmented FlashEats source systems and produces a
late-delivery KPI that can be defended in front of the people who disagree about it — then uses the
reconstructed order workflow to answer the question underneath the escalation: **is a delay
*prediction* model actually the thing worth buying?**

Short answer: no. Four fifths of the excess delay sits in a stage a better ETA model cannot touch.

---

## The problem

FlashEats operations span four systems that were never designed to be read together: an operational
order database, a dispatch service behind an HTTP API, a driver mobile app emitting nested event
JSON, and a set of CSVs maintained by support and restaurant-ops teams. Leadership has a number —
**"Late Delivery Rate is 56%"** — and a proposed investment. Nobody can say where the 56% comes
from, which system is authoritative, or which part of the delivery journey is actually slow.

## Stakeholders

| Who | What they need from this |
| --- | --- |
| **VP Operations** | Where delay accumulates, and which lever reduces it |
| **Support Lead** | Whether complaint volume tracks the operational metric |
| **Finance** | A defensible denominator — cancellations excluded from operational performance |
| **Data Team** | A metric definition that can be owned, reproduced and rerun |
| **Engineering leadership** | Whether the proposed AI delay-prediction system addresses the real constraint |

These four stakeholders are also the problem: `sources/data/client_metric_definitions.json` records
that each defines "late" differently, and states that **no canonical KPI owner is documented**.

## Project KPI

**Late Delivery Rate**, published under both contested definitions, with delay attributed to the
workflow stage that causes it.

---

## Headline findings

**1. The 56% claim is reproducible, and not safe to act on.**

| Definition of "late" | Rate |
| --- | --- |
| Any delay past promised ETA — *VP Operations* | **56.39%** (843 / 1,495) |
| More than 10 minutes past ETA — *Support Lead* | **23.34%** (349 / 1,495) |

Median delay is **1.41 minutes**. The 56% headline is dominated by orders that arrived seconds
late. Our independent count reproduces the client's own derived `order_outcomes.csv` exactly, so
the figure is arithmetically correct — the dispute is over the definition, not the computation.

**2. Delay is created between driver assignment and pickup.** Median minutes, materially late
orders versus on time:

| Stage | Late | On-time | Excess | Share of excess |
| --- | --- | --- | --- | --- |
| order → driver assigned | 2.16 | 2.36 | **−0.20** | −1.0% |
| driver assigned → pickup | 37.47 | 20.47 | **+17.01** | **81.2%** |
| pickup → delivered | 50.32 | 46.39 | +3.94 | 18.8% |

Dispatch latency is not a minor contributor — it is *negative*. Late orders are dispatched
marginally faster than on-time ones. **A better ETA prediction model would estimate the delay more
accurately and remove none of it.**

**3. Customers feel it, and intervention is untargeted.** Complaints run 26.9 per 100 materially
late orders versus 7.2 on time — independent corroboration from a different source system.
Operational interventions, however, run at 26.9 versus 27.1: effort is spent at the same rate on
orders that are fine as on orders that are not.

**4. What we cannot prove.** Splitting that 17-minute gap into *kitchen was slow* versus *driver
arrived early* needs a food-ready timestamp. It exists for 160 of 1,600 orders, is manually typed,
and 60 of those are recorded *after* pickup — physically impossible. That is an instrumentation
gap, not an analysis gap, and it is the highest-value next investment.

## What decision this supports

Whether to fund an AI delay-prediction system. The evidence says the binding constraint is
operational, not predictive, and that the cheapest next step is a system-generated food-ready event
that would make the largest known problem actionable rather than merely located.

Full register of what is known, unknown, assumed and limited: **[`ASSUMPTIONS.md`](ASSUMPTIONS.md)**.

---

## Sources

Four retrieval modes — the assignment requires at least two, and the client estate genuinely has
four. **24,929 rows** landed per run across 14 sources.

| Mode | Source | Grain | Rows |
| --- | --- | --- | --- |
| **SQL** | SQLite `flasheats.db` → `orders`, `customers`, `drivers`, `restaurants` | order / entity | 2,683 |
| **API** | Dispatch service, paginated, 32 pages | order | 1,600 |
| **File** | 8 operational CSVs (events, status, tickets, interactions, interventions) | event / ticket | 10,611 |
| **File (nested)** | `driver_events.json`, flattened 120 drivers → events | driver-event | 10,035 |

The Dispatch API deliberately returns **HTTP 500 on page 3** and **429 on page 5**; both are
retried with exponential backoff and recovered. Every raw response body is preserved before
parsing — including the failures.

Owners, grain, trust ranking and six named gaps: **[`docs/source_map.md`](docs/source_map.md)**.

---

## Quickstart

```bash
cp .env.example .env     # defaults work as-is
make up                  # Postgres warehouse + mock Dispatch API
make install             # dependencies
make init                # create schemas and tables (safe to rerun)
make run                 # run the pipeline for RUN_DATE
make test                # 33 tests
```

No local Python? `make up && make docker-run` runs the pipeline containerised against the same
warehouse.

Outputs land in `out/` — `metrics.csv`, `evidence_table.md`, `dashboard.html`,
`validation_report.json`. Logs in `logs/<run_id>.log`.

**Open `out/dashboard.html` for the evidence pack.**

### Reruns are idempotent

```bash
make run RUN_DATE=2026-08-29
make run RUN_DATE=2026-08-29   # byte-identical output
```

Each partition is replaced in a single transaction rather than appended, so a rerun converges
rather than accumulating.

### Failure handling

```bash
make run --chaos missing_column    # exit 1 — schema drift caught at ingest, nothing landed
make run --chaos stale_data        # exit 1 — freshness check fails, nothing published
make run --chaos duplicate_order   # exit 0 — WARN, order grain held
make run --chaos api_down          # exit 2 — bounded retries, then source unreachable
```

Exit codes: `0` ok · `1` validation failure · `2` source unreachable · `3` config error.

---

## How it works

```
ingest.sqlite → ingest.files → ingest.dispatch_api
    → transform.staging_orders → transform.staging_sources → transform.marts
    → validate → metrics → publish
```

| Schema | Trust boundary |
| --- | --- |
| `raw` | landed exactly as retrieved — TEXT columns, no casting, no cleaning |
| `staging` | typed, normalised, deduplicated, with `quarantine_*` siblings for rejected rows |
| `marts` | the workflow model — order lifecycle fact, event fact, dimensions |
| `metrics` | published KPI output |
| `meta` | the pipeline's own record: `run_log`, `source_manifest`, `validation_results` |

`sql/ddl/` holds structure; `sql/transform/` holds the per-run scripts, parameterised on the
logical run date.

### Validation gate

15 rules across four severities. **Only a FAIL blocks publication** — WARN and UNKNOWN travel with
the number so the consumer sees what was known to be wrong with it.

Current run: **8 PASS · 5 WARN · 2 UNKNOWN**.

`UNKNOWN` is a first-class status, and two rules are permanently UNKNOWN by design:
`kpi.definition_owner` (no ratified definition exists) and `restaurant_status.ready_coverage` (the
instrumentation gap). Forcing either into PASS or FAIL would misrepresent it.

---

## Repository map

| Path | What is in it |
| --- | --- |
| [`ASSUMPTIONS.md`](ASSUMPTIONS.md) | Known / Unknown / Assumption / Limitation register |
| [`docs/source_map.md`](docs/source_map.md) | Business question → source system, owners, grain, gaps |
| [`docs/workflow_model.md`](docs/workflow_model.md) | The order lifecycle model and why it is shaped that way |
| [`docs/metric_definitions.md`](docs/metric_definitions.md) | M1–M5: exact definitions, SQL, hand-checks |
| [`docs/validation_rules.md`](docs/validation_rules.md) | All 15 rules, severities, owners |
| [`docs/decision_log.md`](docs/decision_log.md) | 8 judgement calls, with reasoning and reversal conditions |
| [`docs/DEMO.md`](docs/DEMO.md) | The 3–5 minute demo script |
| [`docs/diagrams/`](docs/diagrams) | Source map, workflow states, ERD, pipeline DAG (Mermaid) |
| `src/flasheats/` | ingest · validate · transform · metrics · cli |
| `sql/` | `ddl/` structure · `transform/` per-run scripts |
| `tests/` | 33 tests over rules, splitter, contract, fault injection |

## Data provenance

Source data under `sources/` is vendored from the course
[classroom pack](https://github.com/manangupta12/flasheats-classroom-pack). The Class 8 reference
pipeline at [flasheats-data-pipeline](https://github.com/manangupta12/flasheats-data-pipeline) was
read for the expected shape of the exercise; the implementation here is independent — a layered
Postgres warehouse with quarantine tables, a run/validation ledger, cross-source reconciliation and
fault injection.
