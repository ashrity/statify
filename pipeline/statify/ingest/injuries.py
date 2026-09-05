"""Load weekly injury reports and practice participation."""

from __future__ import annotations

import sqlite3

from statify.ingest.common import normalize_team, utc_now, write
from statify.sources import nflverse

# The feed writes practice participation as a sentence. Storing that verbatim
# would leave every downstream comparison one upstream copy edit from breaking.
PRACTICE_STATUSES = {
    "Did Not Participate In Practice": "DNP",
    "Limited Participation in Practice": "Limited",
    "Full Participation in Practice": "Full",
}

DESIGNATIONS = {"Out", "Doubtful", "Questionable"}

# 'Note' appears in both status columns as a report annotation rather than a
# status, and a handful of rows carry only whitespace.
NON_STATUSES = {"Note"}

SOURCE_COLUMNS = [
    "season",
    "week",
    "team",
    "gsis_id",
    "report_status",
    "practice_status",
    "date_modified",
]

INJURY_UPSERT = """
INSERT INTO injuries (
  player_id, season, week, team_abbr, designation, practice_status,
  report_at, updated_at
)
VALUES (
  :player_id, :season, :week, :team_abbr, :designation, :practice_status,
  :report_at, :updated_at
)
ON CONFLICT(player_id, season, week, report_at) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  designation = excluded.designation,
  practice_status = excluded.practice_status,
  updated_at = excluded.updated_at
"""


def _blank(value: str | None) -> bool:
    return value is None or not value.strip() or value.strip() in NON_STATUSES


def normalize_practice_status(value: str | None) -> str | None:
    """Map the feed's sentence to the short form, or raise on an unknown one.

    Raising matters more than the mapping. A new upstream wording that silently
    became NULL would read as "no practice report" for a player who did not
    practise at all.
    """
    if _blank(value):
        return None
    status = PRACTICE_STATUSES.get(value.strip())
    if status is None:
        raise RuntimeError(f"unrecognized practice status: {value!r}")
    return status


def normalize_designation(value: str | None) -> str | None:
    """Keep a real game designation, drop annotations, raise on an unknown one."""
    if _blank(value):
        return None
    designation = value.strip()
    if designation not in DESIGNATIONS:
        raise RuntimeError(f"unrecognized injury designation: {designation!r}")
    return designation


def injury_row(source: dict, updated_at: str) -> dict:
    return {
        "player_id": source["gsis_id"],
        "season": source["season"],
        "week": source["week"],
        "team_abbr": normalize_team(source["team"]),
        "designation": normalize_designation(source["report_status"]),
        "practice_status": normalize_practice_status(source["practice_status"]),
        "report_at": source["date_modified"].isoformat(timespec="seconds"),
        "updated_at": updated_at,
    }


def load_injuries(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, int]:
    """Upsert one season's injury reports. Returns (upserted, skipped)."""
    frame = nflverse.injuries(season).select(SOURCE_COLUMNS)
    known_players = {row[0] for row in conn.execute("SELECT player_id FROM players")}
    updated_at = utc_now()

    rows: list[dict] = []
    skipped = 0
    for source in frame.iter_rows(named=True):
        if week is not None and source["week"] != week:
            continue
        if source["gsis_id"] not in known_players:
            skipped += 1
            continue
        if source["date_modified"] is None:
            skipped += 1
            continue

        rows.append(injury_row(source, updated_at))

    write(conn, INJURY_UPSERT, rows)
    return len(rows), skipped
