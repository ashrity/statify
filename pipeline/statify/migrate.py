"""Numbered SQL migration runner.

Migrations are append-only: once a file is applied, never edit it, add the next
number instead.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
FILENAME_PATTERN = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
)
"""


def discover(migrations_dir: Path | None = None) -> list[tuple[str, Path]]:
    directory = MIGRATIONS_DIR if migrations_dir is None else migrations_dir
    if not directory.exists():
        return []

    found: list[tuple[str, Path]] = []
    for path in sorted(directory.iterdir()):
        if path.suffix != ".sql":
            continue
        match = FILENAME_PATTERN.match(path.name)
        if match is None:
            raise ValueError(
                f"migration filename must look like 001_name.sql, got {path.name!r}"
            )
        found.append((match.group(1), path))

    versions = [version for version, _ in found]
    duplicates = {v for v in versions if versions.count(v) > 1}
    if duplicates:
        raise ValueError(f"duplicate migration version(s): {sorted(duplicates)}")

    return found


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    conn.execute(LEDGER_DDL)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[str]:
    """Apply every pending migration. Returns the versions applied, in order."""
    already = applied_versions(conn)
    newly_applied: list[str] = []

    for version, path in discover(migrations_dir):
        if version in already:
            continue

        applied_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # executescript() commits any open transaction before it runs, so BEGIN and
        # COMMIT have to live inside the script itself for the migration and its
        # ledger row to land atomically. Interpolation is safe here: version is
        # regex-checked digits and applied_at is generated, never user input.
        script = (
            "BEGIN;\n"
            f"{path.read_text(encoding='utf-8')}\n"
            "INSERT INTO schema_migrations (version, applied_at) "
            f"VALUES ('{version}', '{applied_at}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            # execute(), never executescript(): executescript() issues an implicit
            # COMMIT first, which would persist the half-applied migration instead
            # of discarding it.
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise RuntimeError(
                f"migration {path.name} failed and was rolled back"
            ) from exc

        newly_applied.append(version)

    return newly_applied
