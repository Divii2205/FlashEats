#!/usr/bin/env python
"""Entry point for the FlashEats pipeline.

Exists so the pipeline can be started with a plain `python run_pipeline.py ...` on any platform.
Invoking it as a module instead would need `PYTHONPATH=src`, and that prefix form is shell
syntax — it works in bash but not in cmd.exe or PowerShell, which is where `make` lands on Windows.

Usage:
    python run_pipeline.py init
    python run_pipeline.py run --run-date 2026-08-29
    python run_pipeline.py run --run-date 2026-08-29 --chaos stale_data
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from flasheats.cli import main  # noqa: E402  (import must follow the path setup)

if __name__ == "__main__":
    sys.exit(main())
