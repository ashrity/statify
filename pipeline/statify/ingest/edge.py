"""Match each projection to its market line and calculate the edge.

No new table: projections' own migration comment already names this feature
as the one that fills in market_line, prop_line_id and edge, left NULL by
feature 20.

The match is temporal, not just by key. A projection generated Tuesday must
not be scored against a line not captured until Thursday, so the match is
the latest prop_lines capture at or before the projection's own
generated_at, the strictly-prior instinct every earlier feature applies to
weeks, extended to a second clock: the order two independent processes
actually ran in.
"""

from __future__ import annotations

import sqlite3

PROJECTIONS_QUERY = """
SELECT id, player_id, week, stat_type, projected_value, generated_at
FROM projections
WHERE season = :season AND market_line IS NULL
"""

PROP_LINES_QUERY = """
SELECT id, player_id, week, stat_type, line, captured_at
FROM prop_lines
WHERE season = :season
"""

EDGE_UPDATE = """
UPDATE projections
SET market_line = :market_line, prop_line_id = :prop_line_id, edge = :edge
WHERE id = :id
"""


def prop_lines_by_key(prop_lines: list[dict]) -> dict[tuple[str, int, str], list[dict]]:
    """Group prop_lines by (player, week, stat_type), each list sorted by
    (captured_at, id) so the latest-at-or-before search can walk it in order."""
    grouped: dict[tuple[str, int, str], list[dict]] = {}
    for row in prop_lines:
        key = (row["player_id"], row["week"], row["stat_type"])
        grouped.setdefault(key, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: (r["captured_at"], r["id"]))
    return grouped


def latest_at_or_before(candidates: list[dict], generated_at: str) -> dict | None:
    """The candidate with the latest captured_at that is <= generated_at.

    candidates must already be sorted by (captured_at, id). A capture at the
    exact same instant as generation counts as available (<=, not <): the
    tie-break is id, the deterministic order candidates were sorted in.
    """
    match = None
    for candidate in candidates:
        if candidate["captured_at"] <= generated_at:
            match = candidate
        else:
            break
    return match


def edge_update(projection: dict, prop_line: dict) -> dict:
    return {
        "id": projection["id"],
        "market_line": prop_line["line"],
        "prop_line_id": prop_line["id"],
        "edge": projection["projected_value"] - prop_line["line"],
    }


def edge_updates(projections: list[dict], prop_lines: list[dict]) -> list[dict]:
    grouped = prop_lines_by_key(prop_lines)
    updates = []
    for projection in projections:
        key = (projection["player_id"], projection["week"], projection["stat_type"])
        candidates = grouped.get(key, [])
        match = latest_at_or_before(candidates, projection["generated_at"])
        if match is None or match["line"] is None:
            continue
        updates.append(edge_update(projection, match))
    return updates


def load_edges(conn: sqlite3.Connection, season: int, week: int | None = None) -> int:
    projections_count = conn.execute(
        "SELECT COUNT(*) FROM projections WHERE season = ?", (season,)
    ).fetchone()[0]
    if projections_count == 0:
        raise RuntimeError(
            f"no projections for {season}. Run: statify compute generate-projections --season {season}"
        )

    query = PROJECTIONS_QUERY
    params: dict = {"season": season}
    if week is not None:
        query += " AND week = :week"
        params["week"] = week
    projections = [dict(row) for row in conn.execute(query, params).fetchall()]

    prop_lines = [dict(row) for row in conn.execute(PROP_LINES_QUERY, {"season": season}).fetchall()]

    updates = edge_updates(projections, prop_lines)
    if updates:
        conn.execute("BEGIN")
        try:
            conn.executemany(EDGE_UPDATE, updates)
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise
    return len(updates)
