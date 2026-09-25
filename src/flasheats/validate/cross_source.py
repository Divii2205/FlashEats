"""Cross-source integrity checks.

Single-source checks catch broken files. These catch something more dangerous: sources that are
each internally valid but disagree with one another. That is where a metric quietly becomes wrong,
because every individual system looks healthy.
"""
from __future__ import annotations

from ..db import scalar
from .rules import Rule, RuleResult


def _restaurant_agreement(ctx=None, **_) -> RuleResult:
    """The same restaurants exist in the operational DB and in an ops-maintained CSV."""
    mismatched = scalar(ctx.conn, """
        SELECT count(*) FROM raw.restaurants d
        JOIN raw.restaurants_csv c USING (restaurant_id)
        WHERE d.run_date = %(d)s AND c.run_date = %(d)s
          AND (btrim(d.restaurant_name) IS DISTINCT FROM btrim(c.restaurant_name)
            OR btrim(d.cuisine)         IS DISTINCT FROM btrim(c.cuisine))
    """, {"d": ctx.run_date})
    missing = scalar(ctx.conn, """
        SELECT count(*) FROM raw.restaurants d
        WHERE d.run_date = %(d)s AND NOT EXISTS (
            SELECT 1 FROM raw.restaurants_csv c
            WHERE c.restaurant_id = d.restaurant_id AND c.run_date = %(d)s)
    """, {"d": ctx.run_date})
    total = mismatched + missing
    if total:
        return RuleResult("WARN", total, 0,
                          f"{mismatched} restaurants disagree between the database and the ops CSV; "
                          f"{missing} exist in the database only")
    return RuleResult("PASS", 0, 0, "database and ops CSV agree on every restaurant")


def _dispatch_coverage(ctx=None, **_) -> RuleResult:
    """Every order should have a dispatch record; a gap means lost stage timestamps."""
    orders = scalar(ctx.conn, "SELECT count(*) FROM staging.orders WHERE run_date=%s",
                    (ctx.run_date,))
    covered = scalar(ctx.conn, """
        SELECT count(*) FROM staging.orders o
        WHERE o.run_date = %(d)s AND EXISTS (
            SELECT 1 FROM staging.dispatch p
            WHERE p.order_id = o.order_id AND p.run_date = %(d)s)
    """, {"d": ctx.run_date})
    gap = orders - covered
    pct = covered / orders * 100 if orders else 0
    if gap:
        return RuleResult("WARN", gap, 0,
                          f"{gap} of {orders} orders have no dispatch record ({pct:.1f}% covered); "
                          f"their assignment stage cannot be measured")
    return RuleResult("PASS", 0, 0, f"all {orders} orders have a dispatch record")


def _event_stream_agreement(ctx=None, **_) -> RuleResult:
    """Two systems independently claim to know when an order was delivered. Do they agree?"""
    disagree = scalar(ctx.conn, """
        SELECT count(*) FROM staging.orders o
        WHERE o.run_date = %(d)s AND o.final_status = 'delivered'
          AND o.actual_delivery_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM staging.order_events e
              WHERE e.order_id = o.order_id AND e.run_date = %(d)s
                AND e.event_type = 'DELIVERED')
    """, {"d": ctx.run_date})
    if disagree:
        return RuleResult("WARN", disagree, 0,
                          f"{disagree} orders are delivered in the order database but have no "
                          f"DELIVERED event in the event stream")
    return RuleResult("PASS", 0, 0, "order database and event stream agree on delivery")


def _client_kpi_reconciliation(ctx=None, **_) -> RuleResult:
    """Reconcile our independently computed late count against the client's derived file.

    order_outcomes.csv already circulates in the business carrying the 56% figure. Landing it and
    reconciling against it is how we can say the leadership claim is *reproducible* — which is a
    different and more useful statement than saying it is right.
    """
    client_late = scalar(ctx.conn, """
        SELECT count(*) FROM staging.client_order_outcomes
        WHERE run_date = %s AND outcome_bucket = 'delivered_late'
    """, (ctx.run_date,))
    ours = scalar(ctx.conn, """
        SELECT count(*) FROM staging.orders
        WHERE run_date = %s AND final_status = 'delivered'
          AND actual_delivery_at IS NOT NULL
          AND actual_delivery_at > promised_eta
    """, (ctx.run_date,))
    delta = abs((client_late or 0) - (ours or 0))
    if delta:
        return RuleResult("WARN", delta, 0,
                          f"our strict late count ({ours}) differs from the client's derived "
                          f"order_outcomes.csv ({client_late}) by {delta}")
    return RuleResult("PASS", 0, 0,
                      f"our strict late count reproduces the client's derived file exactly "
                      f"({ours}); the 56% claim is arithmetically reproducible, so the dispute is "
                      f"over the definition, not the computation")


def _orphan_foreign_keys(ctx=None, **_) -> RuleResult:
    orphans = scalar(ctx.conn, """
        SELECT count(*) FROM staging.orders o
        WHERE o.run_date = %(d)s AND o.restaurant_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM raw.restaurants r
                          WHERE r.restaurant_id = o.restaurant_id AND r.run_date = %(d)s)
    """, {"d": ctx.run_date})
    nulls = scalar(ctx.conn, """
        SELECT count(*) FROM staging.orders
        WHERE run_date = %s AND (restaurant_id IS NULL OR driver_id IS NULL)
    """, (ctx.run_date,))
    if orphans or nulls:
        return RuleResult("WARN", orphans + nulls, 0,
                          f"{orphans} orders reference a restaurant that does not exist; "
                          f"{nulls} orders have a null restaurant_id or driver_id")
    return RuleResult("PASS", 0, 0, "all order foreign keys resolve")


def _unjoinable_tickets(ctx=None, **_) -> RuleResult:
    """Support tickets with no order_id can never be attributed to a delivery."""
    total = scalar(ctx.conn, "SELECT count(*) FROM staging.support_tickets WHERE run_date=%s",
                   (ctx.run_date,))
    orphan = scalar(ctx.conn, """
        SELECT count(*) FROM staging.support_tickets
        WHERE run_date = %s AND NOT is_joinable
    """, (ctx.run_date,))
    if orphan:
        return RuleResult("WARN", orphan, 0,
                          f"{orphan} of {total} support tickets carry no order_id and are "
                          f"structurally unattributable to any delivery")
    return RuleResult("PASS", 0, 0, f"all {total} tickets join to an order")


def _ready_timestamp_coverage(ctx=None, **_) -> RuleResult:
    """The instrumentation gap that blocks the most valuable question in this engagement.

    Splitting the assigned-to-pickup delay into 'kitchen was slow' versus 'driver arrived early'
    needs a food-ready timestamp. It exists for a small minority of orders, is manually entered,
    and frequently lands AFTER the recorded pickup — which is physically impossible. This is
    reported UNKNOWN rather than WARN because the honest answer is that the question cannot be
    settled with the data as instrumented today.
    """
    orders = scalar(ctx.conn, "SELECT count(*) FROM staging.orders WHERE run_date=%s",
                    (ctx.run_date,))
    with_ready = scalar(ctx.conn, """
        SELECT count(DISTINCT order_id) FROM staging.restaurant_status
        WHERE run_date = %s AND status = 'ready'
    """, (ctx.run_date,))
    impossible = scalar(ctx.conn, """
        SELECT count(*) FROM staging.orders o
        JOIN (SELECT DISTINCT ON (order_id) order_id, last_updated_at
              FROM staging.restaurant_status
              WHERE run_date = %(d)s AND status = 'ready'
              ORDER BY order_id, last_updated_at) r USING (order_id)
        WHERE o.run_date = %(d)s AND o.pickup_at < r.last_updated_at
    """, {"d": ctx.run_date})
    pct = with_ready / orders * 100 if orders else 0
    return RuleResult(
        "UNKNOWN", round(pct, 1), 100.0,
        f"food-ready timestamps exist for {with_ready} of {orders} orders ({pct:.1f}%), and "
        f"{impossible} of those are recorded AFTER pickup. Kitchen-versus-driver attribution "
        f"cannot be resolved at this coverage — an instrumentation gap, not an analysis gap",
    )


CROSS_SOURCE_RULES: list[Rule] = [
    Rule("cross.client_kpi_reconciliation", "WARN", "staging vs client file", "Data Team",
         "If we cannot reproduce the circulating number, we cannot discuss it credibly.",
         _client_kpi_reconciliation),
    Rule("cross.restaurant_agreement", "WARN", "raw.restaurants vs raw.restaurants_csv",
         "Restaurant Ops", "Two systems of record for the same entity will drift.",
         _restaurant_agreement),
    Rule("cross.dispatch_coverage", "WARN", "staging.orders vs staging.dispatch",
         "Dispatch platform", "Missing dispatch rows silently remove a lifecycle stage.",
         _dispatch_coverage),
    Rule("cross.event_stream_agreement", "WARN", "staging.orders vs staging.order_events",
         "Order Platform team", "Disagreeing systems of record undermine any lifecycle model.",
         _event_stream_agreement),
    Rule("orders.orphan_foreign_keys", "WARN", "staging.orders", "Order Platform team",
         "Unresolvable keys break dimensional joins and drop rows from segmented metrics.",
         _orphan_foreign_keys),
    Rule("tickets.unjoinable", "WARN", "staging.support_tickets", "Support",
         "Unattributable complaints understate the customer impact of late orders.",
         _unjoinable_tickets),
    Rule("restaurant_status.ready_coverage", "UNKNOWN", "staging.restaurant_status",
         "Restaurant Ops", "Delay attribution below the pickup stage depends entirely on this.",
         _ready_timestamp_coverage),
]
