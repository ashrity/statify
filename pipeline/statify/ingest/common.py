"""Helpers shared by the ingest loaders."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_all(conn: sqlite3.Connection, batches: list[tuple[str, list[dict]]]) -> None:
    """Run several statements in one transaction, in order."""
    conn.execute("BEGIN")
    try:
        for statement, rows in batches:
            conn.executemany(statement, rows)
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise


def write(conn: sqlite3.Connection, statement: str, rows: list[dict]) -> None:
    """Run one statement over many rows in a single explicit transaction."""
    write_all(conn, [(statement, rows)])
