"""Warehouse access. Deliberately thin: raw SQL stays visible in sql/, not hidden behind an ORM."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Iterable

import pandas as pd
import psycopg

from .config import Config


def connect(cfg: Config) -> psycopg.Connection:
    return psycopg.connect(cfg.dsn, autocommit=False)


def run_sql_file(conn: psycopg.Connection, path: Path, params: dict | None = None) -> int:
    """Execute a .sql file.

    When parameters are supplied, statements are executed one at a time: psycopg's extended
    protocol (which is what makes parameter binding safe) does not accept multiple statements in a
    single execute. Splitting here keeps the SQL files readable as ordinary scripts.
    """
    sql = path.read_text(encoding="utf-8")
    if params is None:
        with conn.cursor() as cur:
            cur.execute(sql)
        return 1

    statements = [s.strip() for s in sql.split(";")]
    statements = [s for s in statements
                  if s and not all(line.strip().startswith("--") or not line.strip()
                                   for line in s.splitlines())]
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement, params)
    return len(statements)


def run_sql_dir(conn: psycopg.Connection, directory: Path) -> list[str]:
    """Apply every .sql file in a directory in filename order (hence the NNN_ prefixes)."""
    applied = []
    for path in sorted(directory.glob("*.sql")):
        run_sql_file(conn, path)
        applied.append(path.name)
    return applied


def scalar(conn: psycopg.Connection, sql: str, params: Iterable | None = None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return row[0] if row else None


def read_df(conn: psycopg.Connection, sql: str, params: Iterable | None = None) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def replace_partition(
    conn: psycopg.Connection,
    table: str,
    df: pd.DataFrame,
    run_date: str,
    partition_column: str = "run_date",
) -> int:
    """Idempotent load: delete this logical partition and reinsert, inside one transaction.

    Rerunning the same --run-date therefore converges to the same state instead of appending
    duplicates. The caller owns the transaction boundary, so a later failure rolls this back too.
    """
    df = df.copy()
    df[partition_column] = run_date

    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {table} WHERE {partition_column} = %s", (run_date,))
        if df.empty:
            return 0

        buf = io.StringIO()
        df.to_csv(buf, index=False, header=False, na_rep="", quoting=csv.QUOTE_MINIMAL)
        buf.seek(0)

        cols = ", ".join(f'"{c}"' for c in df.columns)
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, NULL '')") as copy:
            copy.write(buf.read())

    return len(df)


def create_table_from_df(conn: psycopg.Connection, table: str, df: pd.DataFrame) -> None:
    """Land raw data as TEXT columns.

    Raw is a faithful capture of what the source sent, so we do not cast here: casting is a
    judgement call and belongs in staging where it can fail loudly and be quarantined.
    """
    cols = ", ".join(f'"{c}" TEXT' for c in df.columns)
    with conn.cursor() as cur:
        cur.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols}, run_date DATE NOT NULL)")
