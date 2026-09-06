"""Runtime configuration for the pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# config.py -> statify/ -> pipeline/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    db_path: Path
    odds_api_key: str | None


def _resolve_db_path() -> Path:
    override = os.environ.get("STATIFY_DB_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return REPO_ROOT / "data" / "statify.db"


settings = Settings(
    repo_root=REPO_ROOT,
    db_path=_resolve_db_path(),
    # Secret. Never print it, never let it reach an error message or a log line.
    odds_api_key=os.environ.get("ODDS_API_KEY") or None,
)
