"""The SQL statement splitter.

This exists because the obvious implementation — `sql.split(";")` — silently corrupts any script
containing a semicolon inside a string literal, and several metric caveats are prose that does.
The failure mode was a runtime syntax error on an unterminated quoted string, so it is worth
pinning down.
"""
from __future__ import annotations

from flasheats.db import split_statements


def test_splits_plain_statements():
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_trailing_semicolon_does_not_produce_an_empty_statement():
    assert len(split_statements("SELECT 1;")) == 1


def test_semicolon_inside_a_string_literal_is_not_a_terminator():
    sql = "INSERT INTO t SELECT 'delivered only; excludes cancelled' AS caveat; SELECT 2;"
    statements = split_statements(sql)
    assert len(statements) == 2
    assert "excludes cancelled" in statements[0]


def test_semicolon_inside_a_line_comment_is_not_a_terminator():
    sql = "SELECT 1 -- a comment; with a semicolon\n; SELECT 2;"
    assert len(split_statements(sql)) == 2


def test_escaped_quote_inside_a_literal_is_handled():
    """SQL escapes a quote by doubling it; a naive quote-toggle would desynchronise here."""
    sql = "SELECT 'it''s late; really' AS x; SELECT 2;"
    statements = split_statements(sql)
    assert len(statements) == 2
    assert "it''s late; really" in statements[0]


def test_comment_only_fragments_are_dropped():
    sql = "-- header comment\nSELECT 1;\n-- trailing comment only\n"
    assert split_statements(sql) == ["-- header comment\nSELECT 1"]


def test_block_comment_containing_a_semicolon():
    sql = "/* setup; notes */ SELECT 1; SELECT 2;"
    assert len(split_statements(sql)) == 2


def test_real_metric_file_parses_into_statements(tmp_path):
    """Guards the specific script that triggered the original failure."""
    from pathlib import Path

    from flasheats.config import CONFIG

    candidates = [
        CONFIG.sql_dir / "transform" / "030_metrics.sql",
        CONFIG.sql_dir / "metrics" / "010_compute.sql",
    ]
    path = next((p for p in candidates if p.exists()), None)
    assert path is not None, "metric SQL file not found in either expected location"

    text = path.read_text(encoding="utf-8")
    statements = split_statements(text)
    assert len(statements) >= 8
    assert all(s.strip() for s in statements)

    # The specific regression: a caveat literal containing a semicolon must survive intact inside
    # a single statement rather than being cut in half. (Quote counts are not a useful check here,
    # because SQL comments legitimately contain apostrophes and are not parsed for quoting.)
    literals_with_semicolons = [
        line for line in text.splitlines()
        if line.count("'") >= 2 and ";" in line[line.find("'"): line.rfind("'")]
    ]
    for literal_line in literals_with_semicolons:
        fragment = literal_line.strip()[:40]
        assert any(fragment in s for s in statements), f"literal was split apart: {fragment}"
