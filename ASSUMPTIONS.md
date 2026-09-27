# Known / Unknown / Assumption / Limitation

The register the evidence pack is read against. Everything the pipeline could not resolve is here
rather than silently fixed in a transform.

Figures are from run date `2026-08-29` over 1,600 orders (2026-08-01 → 2026-08-28).

---

## KNOWN — established from the data, with evidence

| # | What we know | Evidence |
| --- | --- | --- |
| K-1 | The "56% late" claim is **arithmetically reproducible** | Our independent count of delivered orders past promised ETA is 843 of 1,495 measurable — 56.39%, matching the client's own `order_outcomes.csv` exactly. Checked every run by `cross.client_kpi_reconciliation`. |
| K-2 | The same rows also support **23.34%** | Applying the Support Lead's ">10 minutes" definition to the identical population. Median delay is **1.41 min**, so the strict rate is dominated by orders late by seconds. |
| K-3 | Delay is created **between driver assignment and pickup** | Median 37.47 min on materially late orders vs 20.47 on-time — **+17.0 min**, which is **81.2%** of all excess delay (M3). |
| K-4 | **Dispatch latency is not the problem** | 2.16 min on late orders vs 2.36 on-time. Late orders are dispatched *marginally faster*. Its contribution to excess is **negative** (−1.0%). |
| K-5 | Transit is a **minor** contributor | +3.94 min, 18.8% of excess. |
| K-6 | Customers feel the delay | Complaints run **26.9 per 100** materially late orders vs **7.2** on-time — a 3.7× difference, from a different source system than the timestamps. |
| K-7 | Operational intervention is **not risk-targeted** | Interventions run at **26.9 per 100** late orders vs **27.1** on-time. Effort is spent at the same rate on orders that are fine as on orders that are not. |
| K-8 | The lateness rate is **worst at dinner** | Dinner 25.2%, lunch 22.5%, late night 18.9% (material definition). |

---

## UNKNOWN — cannot be answered with the data as instrumented

| # | Open question | Why it cannot be closed | What would close it |
| --- | --- | --- | --- |
| U-1 | **Who owns the definition of "late"?** | `client_metric_definitions.json` records four stakeholders with four definitions and states outright that no canonical KPI owner is documented. | A named owner ratifying one definition. Until then the pipeline publishes both and raises `kpi.definition_owner` as a standing UNKNOWN. |
| U-2 | Within the assigned→pickup gap, is the **kitchen slow** or does the **driver arrive early**? | Needs a food-ready timestamp. It exists for **160 of 1,600 orders (10%)**, comes from manual entry, and **60 of those are recorded *after* the pickup timestamp** — physically impossible. | A system-generated food-ready event from the restaurant tablet. This is an instrumentation ask, not an analysis task. |
| U-3 | Do interventions **cause** better outcomes? | The data is observational with no control group, and interventions are applied to late and on-time orders at nearly identical rates (K-7). Any raw comparison confounds "was intervened on" with "was already in trouble". | A holdout or staggered rollout. |
| U-4 | Is the ETA *model* itself biased? | Only one `eta_model_version` (`eta-v3.2`) appears in the data, so there is nothing to compare against. | Version-tagged predictions across at least two model versions. |
| U-5 | What happened to the **37 delivered orders with no completion timestamp**? | The order is marked delivered but carries no `actual_delivery_at`. Nothing in any other source resolves it. | An explanation from the Order Platform team for the write failure. |
| U-6 | Are the **3 unattributable support tickets** about late orders? | They carry no `order_id` and cannot be joined to anything. | A required `order_id` at ticket creation. |

---

## ASSUMPTION — choices made to proceed, each reversible

| # | Assumption | Why | If wrong |
| --- | --- | --- | --- |
| A-1 | Cancelled orders are **excluded** from every rate | Finance's stated rule: a cancellation is not an operational delivery outcome. | Counting all 68 cancellations as late moves the strict rate 56.39% → **58.29%** (911/1,563). |
| A-2 | Delivered-but-untimestamped orders are excluded from **both** numerator and denominator | Counting them late asserts a fact not in evidence; counting them on-time understates. Exclusion states honestly that 2.4% cannot be assessed. | Counting all 37 as late moves the strict rate to **57.44%** (880/1,532). Treating *every* unmeasurable order — all 105, cancellations included — as late over the full 1,600 gives **59.25%**, the widest defensible reading. |
| A-3 | For duplicated `order_id`, the **first** copy is retained | Three duplicate pairs disagree on `traffic_bucket`, so no copy is objectively correct. First-copy retention is deterministic and the losing copy is quarantined, not deleted. | Affects 3 of 1,600 orders (0.19%); no material KPI effect, but the *mechanism* would matter at higher duplicate volume. |
| A-4 | `restaurant_status` casing variants are the **same** state | `ready`, `ready `, `READY`, `Ready` differ only by manual typing; `handoff` and `handed_off` likewise. | Would change which orders have a food-ready timestamp — already flagged low-confidence under U-2. |
| A-5 | The **earliest** READY per order is the food-ready moment | The source has duplicate rows per order; earliest is the conservative reading of when food was first ready. | Latest-READY would increase measured idle wait. |
| A-6 | `interaction_type = 'SUPPORT_TICKET'` is the complaint signal | Counted from `customer_interactions` rather than `support_tickets` because 3 tickets have no `order_id` and would be silently dropped from a per-order rate. | Complaint rates shift slightly; the 3.7× late-vs-on-time gap (K-6) is far too large to be explained by it. |
| A-7 | Source ownership in `docs/source_map.md` is **inferred** | No system-of-record register was supplied. Owners are reasoned from data shape. | Would be confirmed with the client in a real engagement; affects who gets escalated to, not any number. |
| A-8 | A **full snapshot** is reloaded each run | `orders` has no reliable `updated_at`, so incremental extraction would miss late-arriving updates. | At 1,600 rows the full reload is free. Revisit at a volume where it is not. |
| A-9 | The 10-minute "material" threshold is the **Support Lead's stated figure**, not our recommendation | It is one stakeholder's position, used to make the sensitivity visible. | The dashboard publishes the full 0–30 min curve precisely so this assumption is not load-bearing. |

---

## LIMITATION — boundaries on how far these numbers travel

| # | Limitation |
| --- | --- |
| L-1 | **28 days, one city (Bengaluru).** No seasonality, no festival peaks, no cross-city comparison. Nothing here should be extrapolated to an annual figure. |
| L-2 | **Observational, not causal.** Stage durations are correlated with lateness. The pipeline shows *where* delay accumulates, never *why*. "Fix the assigned→pickup gap" is a hypothesis with strong evidence, not a proven cause. |
| L-3 | **79 orders carry an impossible negative stage duration** from clock skew or manual entry. They are flagged (`has_negative_duration`) and retained rather than dropped, so medians are computed over a population known to contain them. Medians are used throughout partly for this reason. |
| L-4 | **The idle-wait figure (5.41 min) is directional only.** 153 orders, manual source, 57 negative values. It is published with `LOW CONFIDENCE` in its own metric row and is explicitly not a basis for investment. |
| L-5 | **No cost data.** We can size the delay but not the money. "26.9 complaints per 100 late orders" cannot be converted into a refund or churn figure without finance inputs. |
| L-6 | **Weather and traffic are pre-bucketed** (`clear`/`severe`, `medium`/`high`) by an upstream system with no documented methodology, and the duplicate-order conflict is *in this very field* — so they are carried as context but not used to adjust any metric. |
| L-7 | **Single logical run date.** The pipeline is built for repeated daily runs and is idempotent per partition, but this evidence pack covers one snapshot. Trend claims need a run history. |

---

## The one thing to do next

U-2 is the highest-value gap. Everything points at the assigned→pickup stage, and the business
cannot act precisely on it — dispatch earlier, or push restaurants harder — without knowing which
half of that gap is which. A system-generated food-ready event is a small engineering change that
converts the largest known problem from *located* to *actionable*.

That is a better next investment than an AI delay-prediction system, which would improve the
estimate of a delay whose cause would remain unmeasured.
