"""Retrieval mode 4 of 4: the paginated Dispatch API.

This is the only source that can fail *transiently*, and it does so deliberately: the mock service
returns HTTP 500 on the first request for page 3 and HTTP 429 on the first request for page 5. That
makes it the right place to prove the pipeline's reliability behaviour rather than assert it.

Rules this module follows:
  - every raw response body is written to the run-date partition before it is parsed
  - retries are bounded and backed off; a retryable status is not a failure until the budget is out
  - pagination follows has_more rather than guessing a page count
  - total_records from the API is reconciled against rows actually landed
"""
from __future__ import annotations

import json
import time

import pandas as pd
import requests

from ..db import create_table_from_df, replace_partition
from ..run_context import SourceUnreachable
from . import manifest

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _get_page(ctx, page: int, statuses: list[str]) -> dict:
    cfg = ctx.cfg
    url = f"{cfg.dispatch_api_url}/dispatch/orders"
    params = {"page": page, "page_size": cfg.api_page_size}

    last_error = None
    for attempt in range(1, cfg.api_max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            last_error = f"transport error: {exc}"
            statuses.append(f"p{page}:ERR")
        else:
            statuses.append(f"p{page}:{response.status_code}")

            # Preserve the raw body for EVERY attempt, including the failures. The evidence that
            # the API misbehaved is as important as the data it eventually returned.
            suffix = "" if attempt == 1 else f".attempt{attempt}"
            manifest.preserve_raw(
                cfg.raw_partition(ctx.run_date, "dispatch") / f"page_{page:03d}{suffix}.json",
                response.content,
            )

            if response.status_code == 200:
                if attempt > 1:
                    ctx.log.info("RECOVERED   dispatch page %s on attempt %s", page, attempt)
                return response.json()

            if response.status_code not in RETRYABLE_STATUSES:
                raise SourceUnreachable(
                    f"dispatch API page {page} returned non-retryable {response.status_code}"
                )
            last_error = f"HTTP {response.status_code}"

        if attempt < cfg.api_max_retries:
            delay = cfg.api_backoff_base_seconds * (2 ** (attempt - 1))
            ctx.log.warning(
                "RETRY       dispatch page %s | %s | attempt %s/%s | sleeping %.1fs",
                page, last_error, attempt, cfg.api_max_retries, delay,
            )
            time.sleep(delay)

    raise SourceUnreachable(
        f"dispatch API page {page} failed after {cfg.api_max_retries} attempts ({last_error})"
    )


def land(ctx) -> int:
    records: list[dict] = []
    statuses: list[str] = []
    total_reported = None
    page = 1

    while True:
        body = _get_page(ctx, page, statuses)
        records.extend(body.get("data", []))
        total_reported = body.get("total_records", total_reported)
        if not body.get("has_more"):
            break
        page += 1

    df = pd.DataFrame(records).astype(str).replace({"None": None, "nan": None})

    # The API tells us how many records exist. If we landed a different number, pagination lost
    # something — the exact failure that produces a quietly wrong metric.
    if total_reported is not None:
        manifest.reconcile(ctx, "api.dispatch", int(total_reported), len(df))

    create_table_from_df(ctx.conn, "raw.dispatch", df)
    landed = replace_partition(ctx.conn, "raw.dispatch", df, ctx.run_date)

    retries = sum(1 for s in statuses if not s.endswith(":200"))
    manifest.record(
        ctx,
        source_name="api.dispatch",
        retrieval_mode="api",
        uri=f"{ctx.cfg.dispatch_api_url}/dispatch/orders",
        rows_expected=int(total_reported) if total_reported is not None else None,
        rows_landed=landed,
        sha256=manifest.sha256_bytes(json.dumps(records, sort_keys=True).encode()),
        http_statuses=",".join(statuses),
        detail=f"{page} pages; {retries} retryable responses recovered",
    )
    ctx.log.info("LANDED      raw.dispatch | %s rows over %s pages | %s retries recovered",
                 landed, page, retries)
    return landed
