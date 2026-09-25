# FlashEats — From Fragmented Client Systems to a Defensible Late-Delivery KPI

> **Client escalation:** *"Late deliveries are increasing and customers say our ETA is unreliable.
> Figure out what is happening before we invest in a new AI delay-prediction system."*

This repository is the FDE response to that escalation: a small, repeatable pipeline that takes four
fragmented FlashEats source systems and produces a late-delivery KPI that can be defended in front of
the people who disagree about it.

## The headline finding

Leadership's claim is **"Late Delivery Rate is 56%."** That number is reproducible — and it is not
safe to act on.

| Definition of "late" | Rate |
| --- | --- |
| Any delay past promised ETA (VP Operations) | **56.4%** |
| More than 10 minutes past promised ETA (Support Lead) | **23.3%** |

Median delay is **1.4 minutes**. The 56% headline is dominated by orders that arrived seconds late.
`client_metric_definitions.json` records four stakeholders with four definitions and states that
**no canonical KPI owner is documented** — so the pipeline publishes both figures side by side and
raises the ownership gap as a standing `UNKNOWN` check, rather than silently picking a side.

Full narrative, metrics, and the Known / Unknown / Assumption / Limitation register are in `docs/`.

## Status

Built in phases. See `docs/decision_log.md` for the judgement calls behind each one.

- [x] **Phase 1** — repo skeleton, Dockerised Postgres warehouse, end-to-end slice
- [ ] Phase 2 — source map + all four retrieval modes + manifest reconciliation
- [ ] Phase 3 — full validation gate + quarantine
- [ ] Phase 4 — workflow model (order lifecycle + event facts)
- [ ] Phase 5 — metrics M1–M5 + definition sensitivity
- [ ] Phase 6 — evidence dashboard + K/U/A/L register
- [ ] Phase 7 — hardening, chaos tests, demo

## Quickstart

```bash
cp .env.example .env     # defaults work as-is
make up                  # Postgres warehouse + mock Dispatch API
make install             # dependencies
make init                # create schemas and tables (safe to rerun)
make run                 # run the pipeline for RUN_DATE
make test                # run the test suite
```

Prefer no local Python at all? `make up && make docker-run` runs the pipeline in a container
against the same warehouse.

Outputs land in `out/` (`metrics.csv`, `evidence_table.md`, `validation_report.json`); logs in
`logs/<run_id>.log`. Reruns are idempotent — the same `--run-date` replaces its partition rather
than appending, so `make run` twice produces byte-identical output.

## Warehouse layering

| Schema | Trust boundary |
| --- | --- |
| `raw` | landed exactly as retrieved — TEXT columns, no casting, no cleaning |
| `staging` | typed, normalised, deduplicated, with `quarantine_*` siblings for rejected rows |
| `marts` | the workflow model — facts and dimensions organised around the order lifecycle |
| `metrics` | published KPI output |
| `meta` | the pipeline's own record: run log, source manifest, validation results |

## Data provenance

All source data is vendored under `sources/` from the course
[classroom pack](https://github.com/manangupta12/flasheats-classroom-pack). The Class 8 reference
pipeline at [flasheats-data-pipeline](https://github.com/manangupta12/flasheats-data-pipeline) was
read for the expected shape of the exercise; the implementation here is independent.
