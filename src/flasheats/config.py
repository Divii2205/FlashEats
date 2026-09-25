"""Configuration lives outside core logic so the pipeline can be repointed without a code change."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")


def _path(env_key: str, default: str) -> Path:
    raw = os.getenv(env_key, default)
    p = Path(raw)
    return p if p.is_absolute() else REPO_ROOT / p


@dataclass(frozen=True)
class Config:
    # Warehouse
    pg_host: str = os.getenv("PGHOST", "localhost")
    pg_port: int = int(os.getenv("PGPORT", "5432"))
    pg_user: str = os.getenv("PGUSER", "flasheats")
    pg_password: str = os.getenv("PGPASSWORD", "flasheats")
    pg_database: str = os.getenv("PGDATABASE", "flasheats_wh")

    # Sources
    sqlite_path: Path = _path("SQLITE_PATH", "sources/database/flasheats.db")
    files_dir: Path = _path("FILES_DIR", "sources/data")
    dispatch_api_url: str = os.getenv("DISPATCH_API_URL", "http://localhost:8000")

    # Retrieval behaviour
    api_page_size: int = int(os.getenv("API_PAGE_SIZE", "50"))
    api_max_retries: int = int(os.getenv("API_MAX_RETRIES", "4"))
    api_backoff_base_seconds: float = float(os.getenv("API_BACKOFF_BASE_SECONDS", "0.5"))

    # Validation policy. Thresholds are config, not magic numbers buried in rules.
    freshness_max_age_days: int = int(os.getenv("FRESHNESS_MAX_AGE_DAYS", "30"))
    material_late_threshold_min: float = float(os.getenv("MATERIAL_LATE_THRESHOLD_MIN", "10"))

    # Layout
    repo_root: Path = REPO_ROOT
    raw_dir: Path = REPO_ROOT / "data" / "raw"
    out_dir: Path = REPO_ROOT / "out"
    log_dir: Path = REPO_ROOT / "logs"
    sql_dir: Path = REPO_ROOT / "sql"

    @property
    def dsn(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} user={self.pg_user} "
            f"password={self.pg_password} dbname={self.pg_database}"
        )

    def raw_partition(self, run_date: str, source_name: str) -> Path:
        """Raw zone is partitioned by logical run date so reruns overwrite one partition only."""
        return self.raw_dir / f"run_date={run_date}" / source_name


CONFIG = Config()
