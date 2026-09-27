"""Deliberate fault injection.

A pipeline that has only ever been run on good data has untested failure behaviour. These switches
corrupt a specific thing on the way in so the documented response can be demonstrated rather than
claimed. Each one maps to a real failure this estate could actually produce.

Nothing here runs unless --chaos is passed explicitly.
"""
from __future__ import annotations

import pandas as pd

MODES = {
    "missing_column": "drop a required column, as an upstream schema change would",
    "duplicate_order": "duplicate order rows, as an at-least-once writer would",
    "stale_data": "age the source past the freshness SLA, as a stalled export would",
    "api_down": "point the dispatch API at a dead endpoint, as an outage would",
}


def describe() -> str:
    return "\n".join(f"  {k:<16} {v}" for k, v in MODES.items())


def apply_to_orders(df: pd.DataFrame, mode: str | None, logger) -> pd.DataFrame:
    """Corrupt the orders extract in flight. Called between retrieval and landing."""
    if mode is None:
        return df

    if mode == "missing_column":
        # A required column disappearing is the classic silent schema drift. The gate must FAIL
        # here rather than compute a metric from whatever columns happen to remain.
        logger.warning("CHAOS       dropping required column promised_eta from orders")
        return df.drop(columns=["promised_eta"], errors="ignore")

    if mode == "duplicate_order":
        # More duplicates than the 3 the source already carries, to show the WARN scales and the
        # agreed one-row-per-order rule still holds the grain.
        extra = df.head(25).copy()
        logger.warning("CHAOS       injecting %s duplicate order rows", len(extra))
        return pd.concat([df, extra], ignore_index=True)

    if mode == "stale_data":
        # Shift every timestamp a year into the past: the data parses fine and every row looks
        # individually valid, which is exactly why freshness has to be checked explicitly.
        logger.warning("CHAOS       ageing every order timestamp back by 365 days")
        out = df.copy()
        for col in ["created_at", "promised_eta", "pickup_at", "actual_delivery_at"]:
            parsed = pd.to_datetime(out[col], format="mixed", errors="coerce")
            out[col] = (parsed - pd.Timedelta(days=365)).astype(str).replace("NaT", None)
        return out

    return df


def dispatch_url(configured: str, mode: str | None, logger) -> str:
    if mode == "api_down":
        logger.warning("CHAOS       redirecting dispatch API to a dead endpoint")
        return "http://127.0.0.1:59999"
    return configured
