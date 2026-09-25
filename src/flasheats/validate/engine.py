"""Runs the rule set, records every outcome, and decides whether the run may publish."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..run_context import ValidationFailed
from .rules import Rule, RuleResult


def evaluate(ctx, rules: list[Rule], **inputs) -> list[dict]:
    results: list[dict] = []
    for rule in rules:
        try:
            outcome: RuleResult = rule.check(**inputs)
        except Exception as exc:  # a broken check is itself a finding, not a crash
            outcome = RuleResult("FAIL", None, None, f"check raised {type(exc).__name__}: {exc}")

        row = {
            "rule_id": rule.rule_id,
            "severity": rule.severity,
            "status": outcome.status,
            "scope": rule.scope,
            "observed": outcome.observed,
            "threshold": outcome.threshold,
            "detail": outcome.detail,
            "owner": rule.owner,
            "rationale": rule.rationale,
        }
        results.append(row)

        with ctx.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO meta.validation_results
                   (run_id, run_date, rule_id, severity, status, scope,
                    observed, threshold, detail, owner)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ctx.run_id, ctx.run_date, rule.rule_id, rule.severity, outcome.status,
                 rule.scope, outcome.observed, outcome.threshold, outcome.detail, rule.owner),
            )

        level = {"PASS": ctx.log.info, "WARN": ctx.log.warning,
                 "UNKNOWN": ctx.log.warning, "FAIL": ctx.log.error}[outcome.status]
        level("CHECK %-7s %-32s %s", outcome.status, rule.rule_id, outcome.detail)

    ctx.conn.commit()
    return results


def gate(ctx, results: list[dict], report_path: Path) -> dict:
    """The publish gate.

    Only a FAIL blocks. WARN and UNKNOWN are carried forward onto the report so the consumer sees
    exactly what was known to be wrong with the number they are being handed.
    """
    counts = pd.Series([r["status"] for r in results]).value_counts().to_dict()
    failed = [r for r in results if r["status"] == "FAIL"]
    overall = "FAIL" if failed else ("WARN" if counts.get("WARN") or counts.get("UNKNOWN") else "PASS")

    report = {
        "run_id": ctx.run_id,
        "run_date": ctx.run_date,
        "overall_status": overall,
        "counts": counts,
        "results": results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if failed:
        names = ", ".join(r["rule_id"] for r in failed)
        raise ValidationFailed(f"validation gate FAILED on: {names} — nothing published")

    ctx.log.info("GATE %s | %s", overall, counts)
    return report
