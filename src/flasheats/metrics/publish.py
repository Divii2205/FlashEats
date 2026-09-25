"""Publish the metric set to files a human or a BI tool can consume."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def publish(ctx, metrics: pd.DataFrame, validation_report: dict) -> dict[str, Path]:
    out = ctx.cfg.out_dir
    out.mkdir(parents=True, exist_ok=True)

    csv_path = out / "metrics.csv"
    metrics.to_csv(csv_path, index=False)

    md_path = out / "evidence_table.md"
    lines = [
        "# FlashEats — Evidence Table",
        "",
        f"- **Run ID:** `{ctx.run_id}`",
        f"- **Logical run date:** {ctx.run_date}",
        f"- **Validation gate:** **{validation_report['overall_status']}** "
        f"({validation_report['counts']})",
        "",
        "## Metrics",
        "",
        metrics.to_markdown(index=False),
        "",
        "## Validation results",
        "",
        pd.DataFrame(validation_report["results"])[
            ["rule_id", "severity", "status", "owner", "detail"]
        ].to_markdown(index=False),
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    ctx.log.info("PUBLISHED   %s and %s", csv_path.name, md_path.name)
    return {"metrics_csv": csv_path, "evidence_table": md_path}
