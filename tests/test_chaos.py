"""Fault injection.

The point of these switches is to prove the pipeline's documented failure response rather than
assert it, so the switches themselves need to actually corrupt what they claim to corrupt.
"""
from __future__ import annotations

import logging

import pandas as pd
import pytest

from flasheats import chaos


@pytest.fixture
def logger():
    log = logging.getLogger("test.chaos")
    log.addHandler(logging.NullHandler())
    return log


@pytest.fixture
def orders():
    return pd.DataFrame({
        "order_id": [f"O{i:05d}" for i in range(1, 41)],
        "created_at": ["2026-08-13T12:56:00"] * 40,
        "promised_eta": ["2026-08-13T14:10:00"] * 40,
        "pickup_at": ["2026-08-13T13:35:49.825561"] * 40,
        "actual_delivery_at": ["2026-08-13T14:05:00"] * 40,
        "final_status": ["delivered"] * 40,
    })


def test_no_mode_is_a_passthrough(orders, logger):
    out = chaos.apply_to_orders(orders, None, logger)
    assert out.equals(orders)


def test_missing_column_removes_a_required_column(orders, logger):
    out = chaos.apply_to_orders(orders, "missing_column", logger)
    assert "promised_eta" not in out.columns
    assert len(out) == len(orders)


def test_duplicate_order_adds_duplicate_ids(orders, logger):
    out = chaos.apply_to_orders(orders, "duplicate_order", logger)
    assert len(out) > len(orders)
    assert out.duplicated("order_id").sum() == 25


def test_stale_data_ages_every_timestamp(orders, logger):
    out = chaos.apply_to_orders(orders, "stale_data", logger)
    before = pd.to_datetime(orders["created_at"], format="mixed")
    after = pd.to_datetime(out["created_at"], format="mixed")
    assert (before - after).dt.days.eq(365).all()


def test_stale_data_preserves_row_count_and_columns(orders, logger):
    """Staleness must be undetectable row-by-row — that is why it needs its own check."""
    out = chaos.apply_to_orders(orders, "stale_data", logger)
    assert len(out) == len(orders)
    assert list(out.columns) == list(orders.columns)


def test_api_down_redirects_the_endpoint(logger):
    assert chaos.dispatch_url("http://localhost:8000", "api_down", logger) != "http://localhost:8000"


def test_api_url_untouched_without_the_mode(logger):
    assert chaos.dispatch_url("http://localhost:8000", None, logger) == "http://localhost:8000"
    assert chaos.dispatch_url("http://localhost:8000", "stale_data", logger) == "http://localhost:8000"


def test_every_documented_mode_is_described():
    assert set(chaos.MODES) == {"missing_column", "duplicate_order", "stale_data", "api_down"}
    for mode in chaos.MODES:
        assert mode in chaos.describe()
