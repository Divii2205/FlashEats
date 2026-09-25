"""Retrieval mode 1 of 4: SQL against the client's operational SQLite database.

The source is read-only to us. We select whole tables rather than filtering by date because the
client's `orders` table has no reliable updated_at watermark — documented in docs/source_map.md as
a known gap, and the reason this pipeline reloads a full snapshot per run rather than doing CDC.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from ..db import create_table_from_df, replace_partition
from ..run_context import SourceUnreachable
from . import manifest

SQL_TABLES = ["orders", "customers", "drivers", "restaurants"]


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


def land(ctx, tables: list[str] | None = None) -> dict[str, int]:
    """Extract each SQL table and land it verbatim into the raw schema."""
    counts: dict[str, int] = {}
    for table in tables or SQL_TABLES:
        df = extract_table(ctx, table)
        target = f"raw.{table}"
        create_table_from_df(ctx.conn, target, df)
        counts[table] = replace_partition(ctx.conn, target, df, ctx.run_date)
        ctx.log.info("LANDED      %s | %s rows", target, counts[table])
    return counts
