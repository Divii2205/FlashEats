"""The ingest-time schema contract.

This check cannot live in the validation gate. The `raw` tables persist between runs, so a column
that vanishes upstream is landed as an all-NULL column rather than an absent one: a gate check
asking "is this column present?" passes while every value is null, and the pipeline goes on to
compute a confidently wrong number over nothing.
"""
from __future__ import annotations

import pandas as pd
import pytest

from flasheats.ingest import sqlite_source
from flasheats.run_context import ValidationFailed


class _Ctx:
    run_date = "2026-08-29"


def _orders_frame():
    return pd.DataFrame({c: ["x"] for c in sqlite_source.SOURCE_CONTRACT["orders"]})


def test_complete_frame_satisfies_the_contract():
    sqlite_source.assert_contract(_Ctx(), "orders", _orders_frame())


def test_missing_required_column_raises_before_landing():
    df = _orders_frame().drop(columns=["promised_eta"])
    with pytest.raises(ValidationFailed, match="promised_eta"):
        sqlite_source.assert_contract(_Ctx(), "orders", df)


def test_failure_message_states_nothing_was_landed():
    df = _orders_frame().drop(columns=["actual_delivery_at"])
    with pytest.raises(ValidationFailed, match="Nothing was landed"):
        sqlite_source.assert_contract(_Ctx(), "orders", df)


def test_extra_columns_are_allowed():
    """Additive upstream change is not a breakage; only removal of a depended-on column is."""
    df = _orders_frame()
    df["newly_added_upstream"] = ["x"]
    sqlite_source.assert_contract(_Ctx(), "orders", df)


def test_table_outside_the_contract_is_not_constrained():
    sqlite_source.assert_contract(_Ctx(), "some_other_table", pd.DataFrame({"a": [1]}))
