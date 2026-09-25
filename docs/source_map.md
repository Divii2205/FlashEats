# Source Map

Business question → information required → source system → owner → grain → known gaps.

## The question chain

| Leadership asks | Which requires knowing | Which lives in |
| --- | --- | --- |
| "Are we late more often?" | promised vs actual delivery time per order | SQLite `orders` |
| "Where does the delay come from?" | timestamp at each lifecycle stage | SQLite `orders` + Dispatch API + `restaurant_status.csv` + `driver_events.json` |
| "Is it the restaurants or the drivers?" | when food became ready vs when the driver arrived | `restaurant_status.csv` — **10% coverage, see gap G-04** |
| "Are customers actually suffering?" | complaints attributable to an order | `support_tickets.csv`, `customer_interactions.csv`, `customer_app_actions.csv` |
| "Does intervening help?" | what ops did and what happened after | `order_interventions.csv`, `order_outcomes.csv` |
| "Should we buy an AI ETA model?" | whether prediction error is the binding constraint | all of the above |

## Sources

| # | Source | Mode | Owner (assumed) | Grain | Rows | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | `sources/database/flasheats.db` → `orders` | **SQL** | Order Platform team | one row per order | 1,603 (1,600 unique) | the spine; carries promised vs actual |
| S2 | same DB → `customers`, `drivers`, `restaurants` | **SQL** | Order Platform team | one row per entity | 900 / 120 / 60 | dimension sources |
| S3 | Mock Dispatch API `/dispatch/orders` | **API** | Dispatch/Logistics platform | one row per order | 1,600 | `assigned_at`, ETA model version, reassignment |
| S4 | `sources/data/driver_events.json` | **File (nested)** | Driver app team | driver → events[] | 120 drivers / 10,035 events | `assigned`/`picked_up`/`delivered` + GPS pings |
| S5 | `sources/data/order_events.csv` | **File** | Order Platform team | one row per event | 4,955 | lifecycle + intervention events |
| S6 | `sources/data/restaurant_status.csv` | **File** | Restaurant ops (manual) | order × status update | 502 | **manually entered**; see G-04 |
| S7 | `sources/data/support_tickets.csv` | **File** | Support | one row per ticket | 202 | 3 rows have no `order_id` |
| S8 | `sources/data/customer_interactions.csv` | **File** | Support / CX | one row per interaction | 497 | free-text `detail`, inconsistent casing |
| S9 | `sources/data/customer_app_actions.csv` | **File** | Mobile app analytics | one row per action | 2,365 | `ETA_VIEWED` volume is a dissatisfaction proxy |
| S10 | `sources/data/order_interventions.csv` | **File** | Operations | one row per intervention | 430 | what ops did about a late-risk order |
| S11 | `sources/data/order_outcomes.csv` | **File** | Data team (derived) | one row per order | 1,600 | **derived, not raw** — see G-05 |
| S12 | `sources/data/client_metric_definitions.json` | **File** | *unowned* | document | — | the four conflicting KPI definitions |

Retrieval modes in use: **SQL, API, flat file, nested file** — the assignment requires at least two.

## Known gaps

**G-01 — No watermark on `orders`.** There is no reliable `updated_at`, so incremental extraction
would silently miss late-arriving updates. The pipeline reloads a full snapshot per run (see D-005).

**G-02 — No canonical KPI owner.** `client_metric_definitions.json` states this outright. Four
stakeholders hold four definitions that differ by 33 percentage points on the same rows (D-001).

**G-03 — No food-ready event in the primary lifecycle stream.** `order_events.csv` carries
`ORDER_CREATED`, `PICKED_UP`, `DELIVERED` only. The kitchen-ready moment exists solely in S6.

**G-04 — `restaurant_status.csv` is manually maintained and thin.** READY timestamps resolve for
160 of 1,600 orders (10%), and 57 of the 153 computable idle-wait values are **negative** — the
driver picked up before the restaurant recorded the food as ready. `restaurants.manual_status_updates`
confirms the entry mechanism. This is the single largest blocker to answering "restaurant or driver?"

**G-05 — `order_outcomes.csv` is a derived file presented alongside raw ones.** It hardcodes one
definition of late (843 late / 1,495 measurable = 56.39%), which is exactly the disputed figure. It
is treated here as a *claim to be reconciled against*, never as an input to the metric.

**G-06 — Ownership is inferred, not documented.** No system-of-record register was supplied, so the
owners above are reasoned from the data's shape and would be confirmed with the client in a real
engagement.

## Trust ranking

| Trust | Sources | Reasoning |
| --- | --- | --- |
| High | S1, S2, S3 | system-generated, complete, internally consistent |
| Medium | S4, S5, S9, S10 | system-generated but partially redundant; event streams overlap and disagree at the margins |
| Low | S6, S7, S8 | manual or free-text entry; casing variants, trailing whitespace, unjoinable rows |
| Do not consume | S11 | derived output encoding a contested definition |
