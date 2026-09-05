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


# nflverse is not internally consistent about the Rams: schedules, play-by-play,
# and player_stats say LA, but every Next Gen Stats feed says LAR. The teams
# table holds LA, so inbound feeds normalize onto that. Later feeds (snap counts,
# injuries, depth charts) have not been checked yet; add aliases here as they
# surface rather than per-loader.
TEAM_ALIASES = {"LAR": "LA"}


def normalize_team(team_abbr: str | None) -> str | None:
    """Map a feed's team spelling onto the one teams.team_abbr uses."""
    if team_abbr is None:
        return None
    return TEAM_ALIASES.get(team_abbr, team_abbr)
