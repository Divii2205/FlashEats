"""Metric computation.

Phase 1 implements M1 only; M2-M5 land in the metrics phase. The shape is deliberate: every metric
returns rows carrying its own numerator, denominator and caveat, because a KPI without its
denominator is not auditable.
"""
from __future__ import annotations

import pandas as pd

from ..db import read_df, replace_partition


def _measurable(orders: pd.DataFrame) -> pd.DataFrame:
    """The measurable population: delivered orders that actually have a completion timestamp.

    Cancelled orders are excluded (Finance's rule: they are not an operational delivery outcome).
    Delivered-but-untimestamped orders are excluded from the numerator AND denominator here, and
    reported separately as a coverage caveat — counting them either way silently moves the KPI.
    """
    delivered = orders[orders["final_status"] == "delivered"]
    return delivered[delivered["delay_min"].notna()]


def compute_m1(ctx, orders: pd.DataFrame) -> list[dict]:
    """M1 — Late Delivery Rate, published under BOTH contested definitions.

    The client's leadership claim is '56% late'. That figure is reproducible, but it counts an
    order late if it arrives one second past the promised ETA, and the median delay in this data is
    ~1.4 minutes. The Support Lead's 'more than 10 minutes' definition gives a materially different
    number from the same rows. Neither is wrong; nobody owns the choice. So the pipeline refuses to
    pick one and publishes both, each with its denominator.
    """
    threshold = ctx.cfg.material_late_threshold_min
    meas = _measurable(orders)
    denom = len(meas)

    delivered_total = int((orders["final_status"] == "delivered").sum())
    unmeasurable = delivered_total - denom

    rows = []
    for definition, label, mask in [
        ("strict_gt_0min", "any delay beyond promised ETA (VP Operations)", meas["delay_min"] > 0),
        (f"material_gt_{threshold:g}min",
         f"delay beyond promised ETA by more than {threshold:g} min (Support Lead)",
         meas["delay_min"] > threshold),
    ]:
        num = int(mask.sum())
        rows.append({
            "metric_id": "M1",
            "metric_name": "Late Delivery Rate",
            "definition": f"{definition} — {label}",
            "segment": "ALL",
            "value": round(num / denom * 100, 2) if denom else None,
            "unit": "pct",
            "numerator": num,
            "denominator": denom,
            "caveat": (f"excludes {unmeasurable} delivered orders with no delivery timestamp "
                       f"and all cancelled orders; no documented KPI owner for 'late'"),
        })
    return rows


def compute_all(ctx) -> pd.DataFrame:
    orders = read_df(
        ctx.conn,
        """SELECT order_id, final_status, created_at, promised_eta,
                  pickup_at, actual_delivery_at
           FROM staging.orders WHERE run_date = %s""",
        (ctx.run_date,),
    )
    for col in ["created_at", "promised_eta", "pickup_at", "actual_delivery_at"]:
        orders[col] = pd.to_datetime(orders[col], errors="coerce")

    orders["delay_min"] = (
        orders["actual_delivery_at"] - orders["promised_eta"]
    ).dt.total_seconds() / 60

    rows: list[dict] = []
    rows += compute_m1(ctx, orders)

    df = pd.DataFrame(rows)
    replace_partition(ctx.conn, "metrics.kpi", df, ctx.run_date)
    return df
