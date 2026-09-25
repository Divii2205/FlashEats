"""Retrieval mode 2 of 4: flat files dropped by operational teams.

These are the lowest-trust sources in the estate — several are manually maintained — so the
priority here is faithful capture plus a checksum. Nothing is cleaned on the way in.
"""
from __future__ import annotations

import pandas as pd

from ..db import create_table_from_df, replace_partition
from ..run_context import SourceUnreachable
from . import manifest

# filename -> (logical source name, whether it is safe to consume downstream)
CSV_SOURCES: dict[str, tuple[str, bool]] = {
    "order_events.csv":          ("order_events", True),
    "restaurant_status.csv":     ("restaurant_status", True),
    "support_tickets.csv":       ("support_tickets", True),
    "customer_interactions.csv": ("customer_interactions", True),
    "customer_app_actions.csv":  ("customer_app_actions", True),
    "order_interventions.csv":   ("order_interventions", True),
    "restaurants.csv":           ("restaurants_csv", True),
    # Derived, not raw. It hardcodes one contested definition of "late" (843/1495 = 56.39%).
    # We land it so we can RECONCILE our own number against the client's, never as a metric input.
    "order_outcomes.csv":        ("order_outcomes", False),
}


def land_csv(ctx, filename: str, source_name: str) -> int:
    path = ctx.cfg.files_dir / filename
    if not path.exists():
        raise SourceUnreachable(f"expected file source not found: {path}")

    payload = path.read_bytes()
    raw_path = ctx.cfg.raw_partition(ctx.run_date, "files") / filename
    manifest.preserve_raw(raw_path, payload)

    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])

    # Line count minus header is an independent check that the parser saw every record,
    # catching embedded newlines or a truncated file rather than trusting pandas silently.
    expected = payload.decode("utf-8", errors="replace").rstrip("\n").count("\n")
    if expected != len(df):
        ctx.log.warning(
            "PARSE DRIFT %s | %s newline-delimited records vs %s parsed rows "
            "(embedded newlines or quoted fields)", filename, expected, len(df)
        )

    target = f"raw.{source_name}"
    create_table_from_df(ctx.conn, target, df)
    landed = replace_partition(ctx.conn, target, df, ctx.run_date)

    manifest.record(
        ctx,
        source_name=f"file.{source_name}",
        retrieval_mode="file",
        uri=str(path),
        rows_expected=expected,
        rows_landed=landed,
        sha256=manifest.sha256_bytes(payload),
        detail=f"{len(df.columns)} columns",
    )
    ctx.log.info("LANDED      %s | %s rows", target, landed)
    return landed


def land_driver_events(ctx) -> int:
    """Retrieval mode 3 of 4: a nested JSON document.

    The file is driver-grain with an embedded events array. Flattening it to event grain is the
    first modelling decision of the pipeline: the analytical question is about order lifecycle, not
    about drivers, so the natural key becomes (driver_id, order_id, type, timestamp).
    """
    import json

    path = ctx.cfg.files_dir / "driver_events.json"
    if not path.exists():
        raise SourceUnreachable(f"expected nested source not found: {path}")

    payload = path.read_bytes()
    manifest.preserve_raw(ctx.cfg.raw_partition(ctx.run_date, "files") / "driver_events.json", payload)

    document = json.loads(payload)
    rows = [
        {
            "driver_id": driver["driver_id"],
            "order_id": event.get("order_id"),
            "event_type": event.get("type"),
            "event_time": event.get("timestamp"),
            "lat": event.get("lat"),
            "lon": event.get("lon"),
        }
        for driver in document
        for event in driver.get("events", [])
    ]
    df = pd.DataFrame(rows).astype(str).replace({"None": None, "nan": None})

    expected = sum(len(d.get("events", [])) for d in document)
    manifest.reconcile(ctx, "file.driver_events", expected, len(df))

    create_table_from_df(ctx.conn, "raw.driver_events", df)
    landed = replace_partition(ctx.conn, "raw.driver_events", df, ctx.run_date)

    manifest.record(
        ctx,
        source_name="file.driver_events",
        retrieval_mode="file_nested",
        uri=str(path),
        rows_expected=expected,
        rows_landed=landed,
        sha256=manifest.sha256_bytes(payload),
        detail=f"flattened {len(document)} drivers to {landed} events",
    )
    ctx.log.info("LANDED      raw.driver_events | %s rows from %s drivers", landed, len(document))
    return landed


def land_all(ctx) -> dict[str, int]:
    counts = {name: land_csv(ctx, filename, name)
              for filename, (name, _) in CSV_SOURCES.items()}
    counts["driver_events"] = land_driver_events(ctx)
    return counts
