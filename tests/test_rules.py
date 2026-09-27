"""Rules are the pipeline's opinion about the data, so they get tested like any other logic."""
from __future__ import annotations

import pandas as pd
import pytest

from flasheats.validate import rules


def _orders(**overrides) -> pd.DataFrame:
    base = pd.DataFrame({
        "order_id": ["O1", "O2"],
        "customer_id": ["C1", "C2"],
        "restaurant_id": ["R1", "R2"],
        "created_at": pd.to_datetime(["2026-08-01 10:00", "2026-08-01 11:00"]),
        "promised_eta": pd.to_datetime(["2026-08-01 10:45", "2026-08-01 11:45"]),
        "pickup_at": pd.to_datetime(["2026-08-01 10:15", "2026-08-01 11:15"]),
        "actual_delivery_at": pd.to_datetime(["2026-08-01 10:50", "2026-08-01 11:40"]),
        "final_status": ["delivered", "delivered"],
        "had_conflicting_dupe": [False, False],
    })
    for k, v in overrides.items():
        base[k] = v
    return base


def test_required_columns_passes_on_complete_frame():
    assert rules._required_columns(_orders()).status == "PASS"


def test_required_columns_fails_when_a_column_is_dropped():
    result = rules._required_columns(_orders().drop(columns=["promised_eta"]))
    assert result.status == "FAIL"
    assert "promised_eta" in result.detail


def test_duplicate_order_ids_warn_not_fail():
    """Duplicates are a known, accepted defect with an agreed cleaning rule — they must not
    block publication, only be recorded."""
    df = pd.concat([_orders(), _orders().head(1)], ignore_index=True)
    result = rules._order_id_unique(raw_orders=df)
    assert result.status == "WARN"
    assert result.observed == 2


def test_delivery_before_creation_fails():
    df = _orders(actual_delivery_at=pd.to_datetime(["2026-07-01 09:00", "2026-08-01 11:40"]))
    assert rules._delivery_after_creation(df).status == "FAIL"


def test_delivered_without_timestamp_warns_and_counts():
    df = _orders(actual_delivery_at=[pd.NaT, pd.Timestamp("2026-08-01 11:40")])
    result = rules._delivered_has_timestamp(df)
    assert result.status == "WARN"
    assert result.observed == 1


def test_freshness_fails_when_source_is_stale():
    result = rules._freshness(_orders(), run_date="2026-12-01", max_age_days=30)
    assert result.status == "FAIL"


def test_freshness_passes_inside_the_window():
    result = rules._freshness(_orders(), run_date="2026-08-05", max_age_days=30)
    assert result.status == "PASS"


def test_kpi_definition_owner_is_unknown_by_design():
    """This rule must never report PASS: the ambiguity is real until a human resolves it."""
    assert rules._kpi_definition_owner(_orders()).status == "UNKNOWN"


def test_measurable_population_passes_on_a_healthy_frame():
    result = rules._measurable_population(_orders())
    assert result.status == "PASS"
    assert result.observed == 100.0


def test_measurable_population_fails_when_it_collapses_to_zero():
    """Without this the run does not stop — it emits null metrics and fails later with an error
    that says nothing about the cause."""
    df = _orders(promised_eta=[pd.NaT, pd.NaT])
    assert rules._measurable_population(df).status == "FAIL"


def test_measurable_population_fails_below_half_coverage():
    """Three orders, one measurable: 33% coverage says more about instrumentation than delivery."""
    df = pd.concat([_orders(), _orders().head(1)], ignore_index=True)
    df["actual_delivery_at"] = [pd.Timestamp("2026-08-01 10:50"), pd.NaT, pd.NaT]
    result = rules._measurable_population(df)
    assert result.status == "FAIL"
    assert result.observed == pytest.approx(33.3, abs=0.1)


def test_measurable_population_passes_at_exactly_half():
    """The threshold is 'below half', so the boundary itself is acceptable."""
    df = _orders(actual_delivery_at=[pd.NaT, pd.Timestamp("2026-08-01 11:40")])
    assert rules._measurable_population(df).status == "PASS"
