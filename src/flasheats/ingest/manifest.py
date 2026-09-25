"""Retrieval evidence.

'We pulled the data' is not a claim worth trusting on its own. For every source we record where it
came from, how many rows we expected, how many landed, and a checksum of exactly what we received.
Reconciliation turns retrieval completeness from an assumption into an assertion.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preserve_raw(path: Path, payload: bytes) -> Path:
    """Write the untouched source payload into the run-date partition before any parsing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def record(
    ctx,
    source_name: str,
    retrieval_mode: str,
    uri: str,
    rows_landed: int,
    rows_expected: int | None = None,
    sha256: str | None = None,
    http_statuses: str | None = None,
    detail: str | None = None,
) -> None:
    with ctx.conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meta.source_manifest
                (run_id, run_date, source_name, retrieval_mode, uri,
                 rows_expected, rows_landed, sha256, http_statuses, detail)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (ctx.run_id, ctx.run_date, source_name, retrieval_mode, uri,
             rows_expected, rows_landed, sha256, http_statuses, detail),
        )


def reconcile(ctx, source_name: str, rows_expected: int, rows_landed: int) -> None:
    """Hard stop on a count mismatch.

    A silent short read is the most dangerous retrieval failure there is: the pipeline succeeds,
    the metric moves, and nobody knows why. We would rather fail the run.
    """
    if rows_expected != rows_landed:
        from ..run_context import SourceUnreachable

        raise SourceUnreachable(
            f"{source_name}: retrieval incomplete — expected {rows_expected} rows, landed {rows_landed}"
        )
    ctx.log.info("RECONCILED  %s | %s rows expected == landed", source_name, rows_landed)
