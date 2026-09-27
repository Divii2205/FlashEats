"""One command runs the whole thing. That is the point of the class 8 brief:
`can this run tomorrow without the person who wrote the notebook?`
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

import pandas as pd

from . import chaos
from .config import CONFIG
from .db import connect, read_df, run_sql_dir
from .ingest import dispatch_api, files, sqlite_source
from .metrics import compute, publish
from .run_context import EXIT_OK, PipelineError, RunContext
from .transform import staging
from .validate import engine
from .validate.cross_source import CROSS_SOURCE_RULES
from .validate.rules import ORDER_RULES


def cmd_init(_args) -> int:
    """Create schemas and every DDL object. Safe to run repeatedly.

    Only `sql/ddl` is applied here. `sql/transform` holds the per-run scripts, which are
    parameterised on the logical run date and are meaningless without one — keeping the two in
    separate directories is what stops a setup command from executing pipeline logic.
    """
    with connect(CONFIG) as conn:
        applied = run_sql_dir(conn, CONFIG.sql_dir / "ddl")
        conn.commit()
    print(f"warehouse initialised — applied {len(applied)} DDL files: {', '.join(applied)}")
    return EXIT_OK


def cmd_run(args) -> int:
    run_date = args.run_date or date.today().isoformat()

    with connect(CONFIG) as conn:
        ctx = RunContext(CONFIG, run_date, conn, chaos=args.chaos)
        ctx.log.info("RUN START   run_id=%s run_date=%s%s", ctx.run_id, run_date,
                     f" chaos={args.chaos}" if args.chaos else "")
        try:
            with ctx.step("ingest.sqlite") as r:
                counts = sqlite_source.land(ctx)
                r["rows_out"] = sum(counts.values())
                r["detail"] = ", ".join(f"{k}={v}" for k, v in counts.items())
            conn.commit()

            with ctx.step("ingest.files") as r:
                counts = files.land_all(ctx)
                r["rows_out"] = sum(counts.values())
                r["detail"] = f"{len(counts)} file sources"
            conn.commit()

            with ctx.step("ingest.dispatch_api") as r:
                r["rows_out"] = dispatch_api.land(ctx)
            conn.commit()

            with ctx.step("transform.staging_orders") as r:
                r.update(staging.build_orders(ctx))
            conn.commit()

            with ctx.step("transform.staging_sources") as r:
                r.update(staging.build_sources(ctx))
            conn.commit()

            with ctx.step("transform.marts") as r:
                r.update(staging.build_marts(ctx))
            conn.commit()

            with ctx.step("validate") as r:
                orders = read_df(
                    ctx.conn, "SELECT * FROM staging.orders WHERE run_date = %s", (run_date,)
                )
                for col in ["created_at", "promised_eta", "pickup_at", "actual_delivery_at"]:
                    orders[col] = pd.to_datetime(orders[col], errors="coerce")
                raw_orders = read_df(
                    ctx.conn, "SELECT * FROM raw.orders WHERE run_date = %s", (run_date,)
                )
                results = engine.evaluate(
                    ctx, ORDER_RULES + CROSS_SOURCE_RULES,
                    orders=orders,
                    raw_orders=raw_orders,
                    run_date=run_date,
                    max_age_days=CONFIG.freshness_max_age_days,
                )
                report = engine.gate(ctx, results, CONFIG.out_dir / "validation_report.json")
                r["rows_in"] = len(orders)
                r["detail"] = f"gate={report['overall_status']} {report['counts']}"
                r["status"] = "OK" if report["overall_status"] != "WARN" else "DEGRADED"

            with ctx.step("metrics") as r:
                metrics = compute.compute_all(ctx)
                r["rows_out"] = len(metrics)
            conn.commit()

            with ctx.step("publish") as r:
                paths = publish.publish(ctx, metrics, report)
                r["detail"] = ", ".join(p.name for p in paths.values())
            conn.commit()

        except PipelineError as exc:
            conn.commit()
            ctx.log.error("RUN FAILED  %s (exit %s)", exc, exc.exit_code)
            return exc.exit_code
        except Exception as exc:
            conn.commit()
            ctx.log.exception("RUN FAILED  unexpected: %s", exc)
            return 1

        ctx.log.info("RUN OK      run_id=%s", ctx.run_id)
        print(f"\n{metrics.to_string(index=False)}\n")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flasheats", description="FlashEats KPI pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create warehouse schemas and tables")

    run = sub.add_parser(
        "run",
        help="run the pipeline for a logical run date",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="fault injection (--chaos):\n" + chaos.describe(),
    )
    run.add_argument("--run-date", help="logical partition date, YYYY-MM-DD")
    run.add_argument(
        "--chaos", choices=sorted(chaos.MODES),
        help="deliberately corrupt an input to demonstrate the documented failure response",
    )

    args = parser.parse_args(argv)
    return {"init": cmd_init, "run": cmd_run}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
