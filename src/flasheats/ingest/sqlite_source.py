"""Retrieval mode 1 of 4: SQL against the client's operational SQLite database.

The source is read-only to us. We select whole tables rather than filtering by date because the
client's `orders` table has no reliable updated_at watermark — documented in docs/source_map.md as
a known gap, and the reason this pipeline reloads a full snapshot per run rather than doing CDC.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from .. import chaos
from ..db import create_table_from_df, replace_partition
from ..run_context import SourceUnreachable
from . import manifest

SQL_TABLES = ["orders", "customers", "drivers", "restaurants"]

# The schema contract with the source system, enforced at ingest rather than at the gate.
#
# It has to be here. The `raw` tables persist across runs, so a column that disappears upstream is
# landed as an all-NULL column rather than an absent one — the table still has the column, and a
# downstream "is this column present?" check passes while every value is silently null. Catching
# drift means comparing against what the source actually sent, before anything is written.
SOURCE_CONTRACT: dict[str, set[str]] = {
    "orders": {
        "order_id", "customer_id", "restaurant_id", "driver_id", "city", "created_at",
        "promised_eta", "pickup_at", "actual_delivery_at", "final_status",
    },
    "customers": {"customer_id"},
    "drivers": {"driver_id"},
    "restaurants": {"restaurant_id", "restaurant_name"},
}


def extract_table(ctx, table: str) -> pd.DataFrame:
    cfg = ctx.cfg
    if not cfg.sqlite_path.exists():
        raise SourceUnreachable(f"SQLite source not found at {cfg.sqlite_path}")

    uri = f"file:{cfg.sqlite_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        expected = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)

    manifest.reconcile(ctx, f"sqlite.{table}", expected, len(df))

    raw_path = cfg.raw_partition(ctx.run_date, "sqlite") / f"{table}.csv"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(raw_path, index=False)

    manifest.record(
        ctx,
        source_name=f"sqlite.{table}",
        retrieval_mode="sql",
        uri=str(cfg.sqlite_path),
        rows_expected=expected,
        rows_landed=len(df),
        sha256=manifest.sha256_file(raw_path),
        detail=f"full snapshot; {len(df.columns)} columns",
    )
    return df


def assert_contract(ctx, table: str, df: pd.DataFrame) -> None:
    """Fail the run if the source stopped sending a column we depend on.

    This is deliberately fail-fast and pre-landing: a schema change upstream is not something to
    warn about and carry on from, because every metric downstream would still compute — just over
    nulls, producing a confidently wrong number instead of an error.
    """
    from ..run_context import ValidationFailed

    required = SOURCE_CONTRACT.get(table, set())
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValidationFailed(
            f"source schema drift in {table}: required column(s) {missing} are no longer supplied "
            f"by the source. Nothing was landed for this run."
        )


def land(ctx, tables: list[str] | None = None) -> dict[str, int]:
    """Extract each SQL table and land it verbatim into the raw schema."""
    counts: dict[str, int] = {}
    for table in tables or SQL_TABLES:
        df = extract_table(ctx, table)
        if table == "orders":
            # Injected AFTER reconciliation and raw preservation, so the raw zone still holds what
            # the source really sent and only the downstream path sees the fault.
            df = chaos.apply_to_orders(df, getattr(ctx, "chaos", None), ctx.log)

        assert_contract(ctx, table, df)
        target = f"raw.{table}"
        create_table_from_df(ctx.conn, target, df)
        counts[table] = replace_partition(ctx.conn, target, df, ctx.run_date)
        ctx.log.info("LANDED      %s | %s rows", target, counts[table])
    return counts
