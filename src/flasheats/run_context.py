"""A run is a first-class object: it has an id, a logical date, a ledger, and exit semantics."""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from datetime import date

import psycopg

from .config import Config
from .logging_utils import get_logger


# Exit codes are part of the pipeline's contract with whatever schedules it.
EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_SOURCE_UNREACHABLE = 2
EXIT_CONFIG_ERROR = 3


class PipelineError(RuntimeError):
    exit_code = EXIT_OK


class ValidationFailed(PipelineError):
    exit_code = EXIT_VALIDATION_FAILED


class SourceUnreachable(PipelineError):
    exit_code = EXIT_SOURCE_UNREACHABLE


class ConfigError(PipelineError):
    exit_code = EXIT_CONFIG_ERROR


class RunContext:
    def __init__(self, cfg: Config, run_date: str, conn: psycopg.Connection):
        self.cfg = cfg
        self.run_date = run_date
        self.conn = conn
        self.run_id = f"{run_date}__{uuid.uuid4().hex[:8]}"
        self.log = get_logger(self.run_id, cfg.log_dir)

    @contextmanager
    def step(self, name: str):
        """Wrap a pipeline stage so its outcome is recorded whether it succeeds or throws."""
        started = time.perf_counter()
        self.log.info("STEP START  %s", name)
        self._write(name, "STARTED")
        result: dict = {}
        try:
            yield result
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            self._write(name, "FAILED", elapsed_ms=elapsed, error_text=f"{type(exc).__name__}: {exc}")
            self.log.error("STEP FAILED %s after %sms | %s", name, elapsed, exc)
            raise
        else:
            elapsed = int((time.perf_counter() - started) * 1000)
            self._write(
                name,
                result.get("status", "OK"),
                elapsed_ms=elapsed,
                rows_in=result.get("rows_in"),
                rows_out=result.get("rows_out"),
                detail=result.get("detail"),
            )
            self.log.info(
                "STEP OK     %s in %sms | rows_out=%s %s",
                name, elapsed, result.get("rows_out"), result.get("detail") or "",
            )

    def _write(self, step, status, elapsed_ms=None, rows_in=None, rows_out=None,
               detail=None, error_text=None) -> None:
        # The ledger is committed on its own connection state immediately: a run that crashes
        # must still leave evidence of how far it got.
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO meta.run_log
                    (run_id, run_date, step, status, ended_at, duration_ms,
                     rows_in, rows_out, detail, error_text)
                VALUES (%s, %s, %s, %s, now(), %s, %s, %s, %s, %s)
                """,
                (self.run_id, self.run_date, step, status, elapsed_ms,
                 rows_in, rows_out, detail, error_text),
            )
        self.conn.commit()
