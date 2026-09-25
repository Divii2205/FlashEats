"""raw (TEXT, as-received) -> staging (typed, normalised, deduplicated).

Every cleaning decision in this module is a business judgement, so each one is commented with the
reasoning and mirrored in docs/decision_log.md. Nothing is cleaned "because pandas made it easy".
"""
from __future__ import annotations

import json

import pandas as pd

from ..db import read_df, replace_partition

TIMESTAMP_COLUMNS = ["created_at", "promised_eta", "pickup_at", "actual_delivery_at"]

# Attributes that must agree between duplicate rows of the same order. If they disagree, the
# duplicate is not a harmless double-write and picking either copy silently changes an answer.
DUPE_CONFLICT_COLUMNS = ["traffic_bucket", "weather_bucket", "distance_km_estimate",
                         "restaurant_id", "driver_id", "final_status"]


def _quarantine(ctx, rows: pd.DataFrame, reason_code: str, reason_detail: str) -> int:
    if rows.empty:
        return 0
    payload = rows.apply(lambda r: json.dumps({k: (None if pd.isna(v) else str(v))
                                               for k, v in r.items()}), axis=1)
    frame = pd.DataFrame({
        "order_id": rows.get("order_id"),
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "payload": payload,
    })
    with ctx.conn.cursor() as cur:
        cur.execute(
            "DELETE FROM staging.quarantine_orders WHERE run_date = %s AND reason_code = %s",
            (ctx.run_date, reason_code),
        )
    frame["run_date"] = ctx.run_date
    with ctx.conn.cursor() as cur:
        for _, r in frame.iterrows():
            cur.execute(
                """INSERT INTO staging.quarantine_orders
                   (order_id, reason_code, reason_detail, payload, run_date)
                   VALUES (%s,%s,%s,%s,%s)""",
                (r.order_id, r.reason_code, r.reason_detail, r.payload, r.run_date),
            )
    ctx.log.warning("QUARANTINE  %s rows | %s | %s", len(frame), reason_code, reason_detail)
    return len(frame)


def build_orders(ctx) -> dict:
    raw = read_df(ctx.conn, "SELECT * FROM raw.orders WHERE run_date = %s", (ctx.run_date,))
    rows_in = len(raw)
    df = raw.drop(columns=["run_date"], errors="ignore").copy()

    # --- Timestamps -------------------------------------------------------------------------
    # The source mixes minute-precision and microsecond-precision strings (two different writers),
    # so format="mixed" is required. Unparseable values become NaT rather than raising: an
    # unreadable timestamp is a data quality finding for the validation gate, not a crash.
    for col in TIMESTAMP_COLUMNS:
        df[col] = pd.to_datetime(df[col], format="mixed", errors="coerce")

    df["distance_km_estimate"] = pd.to_numeric(df["distance_km_estimate"], errors="coerce")

    # --- Status normalisation ---------------------------------------------------------------
    # 'Delivered' and 'delivered' are the same operational state recorded by different writers.
    # We keep the raw value alongside the normalised one so the fix is auditable, not invisible.
    df["final_status_raw"] = df["final_status"]
    df["final_status"] = df["final_status"].astype(str).str.strip().str.lower()

    # --- Duplicate order_id -----------------------------------------------------------------
    # Not all duplicates are equal. Rows identical on every business attribute are a safe
    # double-write and we keep the first. Rows that DISAGREE (this source has 3 such pairs, where
    # traffic_bucket differs) cannot be resolved by the pipeline: choosing a copy silently picks
    # an answer. We keep the first for continuity, FLAG it, and quarantine the losing copy so the
    # conflict is reviewable by the source owner.
    dupe_mask = df.duplicated("order_id", keep=False)
    conflicting_ids: set[str] = set()
    if dupe_mask.any():
        for order_id, grp in df[dupe_mask].groupby("order_id"):
            present = [c for c in DUPE_CONFLICT_COLUMNS if c in grp.columns]
            if grp[present].astype(str).drop_duplicates().shape[0] > 1:
                conflicting_ids.add(order_id)

    losers = df[df.duplicated("order_id", keep="first")]
    quarantined = _quarantine(
        ctx, losers,
        reason_code="DUPLICATE_ORDER_ID",
        reason_detail="second copy of a duplicated order_id; first copy retained at order grain",
    )

    df = df.drop_duplicates("order_id", keep="first").copy()
    df["had_conflicting_dupe"] = df["order_id"].isin(conflicting_ids)

    columns = [
        "order_id", "customer_id", "restaurant_id", "driver_id", "city",
        "created_at", "promised_eta", "pickup_at", "actual_delivery_at",
        "final_status_raw", "final_status", "distance_km_estimate",
        "traffic_bucket", "weather_bucket", "had_conflicting_dupe",
    ]
    out = df[columns]
    rows_out = replace_partition(ctx.conn, "staging.orders", out, ctx.run_date)

    return {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "detail": (f"deduped={quarantined} conflicting_dupes={len(conflicting_ids)} "
                   f"unparsed_delivery_ts={int(out.actual_delivery_at.isna().sum())}"),
        "conflicting_dupes": len(conflicting_ids),
    }
