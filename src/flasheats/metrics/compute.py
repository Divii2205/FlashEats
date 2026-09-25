"""Metric computation.

All five metrics are defined in sql/metrics/010_compute.sql and read from
marts.fct_order_lifecycle, so there is exactly one definition of a stage duration in the project
and the definitions are reviewable as SQL rather than buried in dataframe code.
"""
from __future__ import annotations

import pandas as pd

from ..db import read_df, run_sql_file


def compute_all(ctx) -> pd.DataFrame:
    run_sql_file(
        ctx.conn,
        ctx.cfg.sql_dir / "metrics" / "010_compute.sql",
        {
            "run_date": ctx.run_date,
            "material_threshold": ctx.cfg.material_late_threshold_min,
        },
    )
    return read_df(
        ctx.conn,
        """SELECT metric_id, metric_name, definition, segment, value, unit,
                  numerator, denominator, caveat
           FROM metrics.kpi
           WHERE run_date = %s
           ORDER BY metric_id, definition, segment""",
        (ctx.run_date,),
    )
