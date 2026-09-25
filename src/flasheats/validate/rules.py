"""Validation rules as data, not scattered if-statements.

Each rule names an owner. That is deliberate: most of the issues in this dataset are unresolved
*business* rules, not technical defects, and a pipeline that quietly fixes them is hiding the
decision that someone actually needs to make.

Severity contract:
  FAIL     the metric cannot be trusted; abort the run and publish nothing
  WARN     a known, accepted defect; record it and continue under a stated cleaning rule
  UNKNOWN  the check cannot be evaluated at current data coverage — an honest fourth state
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class RuleResult:
    status: str                 # PASS | WARN | FAIL | UNKNOWN
    observed: float | None = None
    threshold: float | None = None
    detail: str = ""


@dataclass(frozen=True)
class Rule:
    rule_id: str
    severity: str               # FAIL | WARN | UNKNOWN
    scope: str
    owner: str
    rationale: str
    check: Callable[..., RuleResult]


REQUIRED_ORDER_COLUMNS = {
    "order_id", "customer_id", "restaurant_id", "created_at",
    "promised_eta", "pickup_at", "actual_delivery_at", "final_status",
}


def _required_columns(orders: pd.DataFrame, **_) -> RuleResult:
    missing = sorted(REQUIRED_ORDER_COLUMNS - set(orders.columns))
    if missing:
        return RuleResult("FAIL", len(missing), 0, f"missing required columns: {missing}")
    return RuleResult("PASS", 0, 0, f"all {len(REQUIRED_ORDER_COLUMNS)} required columns present")


def _order_id_unique(raw_orders: pd.DataFrame = None, **_) -> RuleResult:
    """Deliberately evaluated against RAW, not staging.

    Staging has already applied the agreed one-row-per-order rule, so a uniqueness check there can
    never fire — it would report a permanent, meaningless PASS. The question worth asking is
    whether the SOURCE is still emitting duplicates, which is a signal about the upstream system.
    """
    if raw_orders is None:
        return RuleResult("UNKNOWN", None, None, "raw orders not supplied to the check")
    dupes = int(raw_orders.duplicated("order_id", keep=False).sum())
    if dupes:
        return RuleResult("WARN", dupes, 0,
                          f"{dupes} rows share an order_id; agreed rule keeps the first copy")
    return RuleResult("PASS", 0, 0, "order_id is unique")


def _conflicting_duplicates(orders: pd.DataFrame, **_) -> RuleResult:
    """A duplicate whose business attributes disagree is unresolvable by the pipeline."""
    if "had_conflicting_dupe" not in orders.columns:
        return RuleResult("UNKNOWN", None, None, "conflict flag not present at this stage")
    n = int(orders["had_conflicting_dupe"].sum())
    if n:
        return RuleResult("WARN", n, 0,
                          f"{n} orders had duplicate copies disagreeing on business attributes "
                          f"(e.g. traffic_bucket); first copy retained, losing copy quarantined")
    return RuleResult("PASS", 0, 0, "no conflicting duplicates")


def _delivered_has_timestamp(orders: pd.DataFrame, **_) -> RuleResult:
    delivered = orders["final_status"].eq("delivered")
    missing = int((delivered & orders["actual_delivery_at"].isna()).sum())
    total = int(delivered.sum())
    pct = (missing / total * 100) if total else 0.0
    if missing:
        return RuleResult("WARN", missing, 0,
                          f"{missing} of {total} delivered orders ({pct:.1f}%) have no delivery "
                          f"timestamp and are therefore unmeasurable for the KPI")
    return RuleResult("PASS", 0, 0, "every delivered order has a delivery timestamp")


def _delivery_after_creation(orders: pd.DataFrame, **_) -> RuleResult:
    both = orders.actual_delivery_at.notna() & orders.created_at.notna()
    impossible = int((orders.actual_delivery_at < orders.created_at)[both].sum())
    if impossible:
        return RuleResult("FAIL", impossible, 0,
                          f"{impossible} orders delivered before they were created")
    return RuleResult("PASS", 0, 0, "no orders delivered before creation")


def _freshness(orders: pd.DataFrame, run_date=None, max_age_days=None, **_) -> RuleResult:
    latest = orders["created_at"].max()
    if pd.isna(latest):
        return RuleResult("FAIL", None, max_age_days, "no parseable created_at values")
    age = (pd.Timestamp(run_date) - latest.normalize()).days
    status = "FAIL" if age > max_age_days else "PASS"
    return RuleResult(status, age, max_age_days,
                      f"latest created_at={latest}; age_days={age}; allowed={max_age_days}")


def _kpi_definition_owner(orders: pd.DataFrame, **_) -> RuleResult:
    """The single most important finding in this dataset, encoded as a standing check.

    client_metric_definitions.json records four stakeholders with four different definitions of
    'late' and states no canonical KPI owner is documented. Until that is resolved, the headline
    number is a choice, not a measurement — so this rule is permanently UNKNOWN by design and
    forces the ambiguity onto the report instead of letting the pipeline pick a side.
    """
    return RuleResult(
        "UNKNOWN", None, None,
        "no documented KPI owner for 'late delivery'; four stakeholder definitions in conflict. "
        "Pipeline publishes strict (>0 min) and material (>threshold) side by side rather than "
        "silently selecting one.",
    )


ORDER_RULES: list[Rule] = [
    Rule("orders.required_columns", "FAIL", "raw.orders", "Data Engineering",
         "Schema drift in the source breaks every downstream metric.", _required_columns),
    Rule("orders.delivery_after_creation", "FAIL", "staging.orders", "Data Engineering",
         "A negative order lifespan means timestamps cannot be trusted at all.", _delivery_after_creation),
    Rule("orders.freshness", "FAIL", "staging.orders", "Platform / Ops",
         "A stale extract silently republishes yesterday's number as today's.", _freshness),
    Rule("orders.order_id_unique", "WARN", "raw.orders", "Order Platform team",
         "Duplicate writes inflate volume-based denominators.", _order_id_unique),
    Rule("orders.conflicting_duplicates", "WARN", "staging.orders", "Order Platform team",
         "Disagreeing duplicates make the retained copy an arbitrary choice.", _conflicting_duplicates),
    Rule("orders.delivered_has_timestamp", "WARN", "staging.orders", "VP Operations",
         "Unmeasurable deliveries change the KPI depending on how they are counted.",
         _delivered_has_timestamp),
    Rule("kpi.definition_owner", "UNKNOWN", "business", "VP Operations (unassigned)",
         "An undefined KPI cannot be validated, only reported with its ambiguity.",
         _kpi_definition_owner),
]
