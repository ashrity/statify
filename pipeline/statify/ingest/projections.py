"""Give feature 19's raw projection a storage identity and a history.

Unlike every table since feature 15a, this one accumulates rows rather than
overwriting them: a re-run inserts a new row only when projected_value
actually changed since the latest stored row for a given player/week/
stat_type/model_version, the same content-based novelty rule ingest market
and ingest forecast already follow.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import utc_now, write

MODEL_VERSION = "v1"

RAW_PROJECTION_QUERY = """
SELECT player_id, season, week, stat_type, raw_projection
FROM player_raw_projection_weekly
WHERE season = :season AND raw_projection IS NOT NULL
"""

LATEST_QUERY = """
SELECT player_id, season, week, stat_type, projected_value, MAX(generated_at) AS generated_at
FROM projections
WHERE season = :season AND model_version = :model_version
GROUP BY player_id, season, week, stat_type
"""

PROJECTIONS_INSERT = """
INSERT INTO projections (
  player_id, season, week, stat_type, model_version, projected_value,
  market_line, prop_line_id, edge, confidence, generated_at
)
VALUES (
  :player_id, :season, :week, :stat_type, :model_version, :projected_value,
  NULL, NULL, NULL, NULL, :generated_at
)
"""


def latest_values(rows: list[dict]) -> dict[tuple[str, int, int, str], float]:
    """The most recently stored projected_value per (player, season, week, stat_type).

    Built from a GROUP BY MAX(generated_at), so only one row per key reaches
    here regardless of how many generations are already stored.
    """
    return {
        (row["player_id"], row["season"], row["week"], row["stat_type"]): row["projected_value"]
        for row in rows
    }


def new_rows(
    candidates: list[dict],
    latest: dict[tuple[str, int, int, str], float],
    model_version: str,
    updated_at: str | None = None,
) -> list[dict]:
    """Candidates whose value is new or has actually changed since the last stored row."""
    stamp = updated_at or utc_now()
    rows = []
    for candidate in candidates:
        key = (candidate["player_id"], candidate["season"], candidate["week"], candidate["stat_type"])
        if latest.get(key) == candidate["raw_projection"]:
            continue
        rows.append(
            {
                "player_id": candidate["player_id"],
                "season": candidate["season"],
                "week": candidate["week"],
                "stat_type": candidate["stat_type"],
                "model_version": model_version,
                "projected_value": candidate["raw_projection"],
                "generated_at": stamp,
            }
        )
    return rows


def generate_projections(conn: sqlite3.Connection, season: int, week: int | None = None) -> int:
    raw_count = conn.execute(
        "SELECT COUNT(*) FROM player_raw_projection_weekly WHERE season = ?", (season,)
    ).fetchone()[0]
    if raw_count == 0:
        raise RuntimeError(
            f"no raw projection rows for {season}; this table reuses that row "
            f"set. Run: statify compute projection --season {season}"
        )

    query = RAW_PROJECTION_QUERY
    params: dict = {"season": season}
    if week is not None:
        query += " AND week = :week"
        params["week"] = week
    candidates = [dict(row) for row in conn.execute(query, params).fetchall()]

    latest_rows = [
        dict(row)
        for row in conn.execute(LATEST_QUERY, {"season": season, "model_version": MODEL_VERSION}).fetchall()
    ]
    latest = latest_values(latest_rows)

    rows = new_rows(candidates, latest, MODEL_VERSION)
    if rows:
        write(conn, PROJECTIONS_INSERT, rows)
    return len(rows)
