"""Convert a projection's edge and a player's own week-to-week volatility
into a 0.5-to-1.0 confidence reading, filling projections.confidence, locked
since feature 20 and NULL on every row until now.

Four stat types use the standard normal CDF of how many standard deviations
the edge represents (math.erf only, no new dependency, the same math-only
discipline feature 17 used for its Poisson tail). touchdowns reuses feature
17's own anytime_td_prob directly rather than fitting a second, worse model
to a 0/1 outcome.

Driven by the projections that need scoring, not by weeks a player has
already played: the week that matters most is the one not yet played, and a
variance computation that only walked a player's history would never reach
it.
"""

from __future__ import annotations

import math
import sqlite3

from statify.ingest.common import utc_now, write
from statify.ingest.windows import prior_games

ACTUAL_COLUMN = {
    "receiving_yards": "receiving_yards",
    "receptions": "receptions",
    "rushing_yards": "rushing_yards",
    "passing_yards": "passing_yards",
}

MIN_GAMES_FOR_STDDEV = 2

PLAYER_HISTORY_QUERY = """
SELECT player_id, week, receiving_yards, receptions, rushing_yards, passing_yards
FROM weekly_actuals
WHERE season = :season
ORDER BY player_id, week
"""

PROJECTIONS_QUERY = """
SELECT id, player_id, season, week, stat_type, edge
FROM projections
WHERE season = :season AND edge IS NOT NULL
"""

TOUCHDOWN_QUERY = """
SELECT player_id, week, anytime_td_prob
FROM player_touchdown_expected_weekly
WHERE season = :season
"""

VARIANCE_UPSERT = """
INSERT INTO player_variance_weekly (player_id, season, week, stat_type, own_stddev, games_measured, updated_at)
VALUES (:player_id, :season, :week, :stat_type, :own_stddev, :games_measured, :updated_at)
ON CONFLICT(player_id, season, week, stat_type) DO UPDATE SET
  own_stddev = excluded.own_stddev,
  games_measured = excluded.games_measured,
  updated_at = excluded.updated_at
"""

CONFIDENCE_UPDATE = "UPDATE projections SET confidence = :confidence WHERE id = :id"


def sample_stddev(values: list[float]) -> float | None:
    """Sample standard deviation, or None below the 2-game floor.

    One game gives a trivial 0, which would read as perfect certainty, the
    opposite of what a single game actually tells you about volatility.
    """
    if len(values) < MIN_GAMES_FOR_STDDEV:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def yardage_confidence(edge: float | None, own_stddev: float | None) -> float | None:
    """Phi(|edge| / own_stddev): 0.5 at a zero edge, approaching 1.0 as the
    edge grows relative to the player's own volatility on that stat."""
    if edge is None or own_stddev is None or own_stddev == 0:
        return None
    return normal_cdf(abs(edge) / own_stddev)


def touchdown_confidence(anytime_td_prob: float | None) -> float | None:
    """How far feature 17's own probability sits from a coin flip, either way."""
    if anytime_td_prob is None:
        return None
    return max(anytime_td_prob, 1 - anytime_td_prob)


def variance_row(player_id: str, season: int, week: int, stat_type: str, history: list[dict], updated_at: str) -> dict:
    prior = prior_games(history, week)
    column = ACTUAL_COLUMN[stat_type]
    values = [float(game[column]) for game in prior]
    return {
        "player_id": player_id,
        "season": season,
        "week": week,
        "stat_type": stat_type,
        "own_stddev": sample_stddev(values),
        "games_measured": len(prior),
        "updated_at": updated_at,
    }


def confidence_rows(
    projection_rows: list[dict],
    player_histories: dict[str, list[dict]],
    touchdown_index: dict[tuple[str, int], float | None],
    updated_at: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Returns (variance_rows_to_store, confidence_updates), computed together
    so a variance row is only ever built for a (player, week, stat_type) a
    projection actually needs scored."""
    stamp = updated_at or utc_now()

    variance_rows: list[dict] = []
    variance_by_key: dict[tuple[str, int, str], float | None] = {}
    updates: list[dict] = []

    for row in projection_rows:
        if row["stat_type"] == "touchdowns":
            prob = touchdown_index.get((row["player_id"], row["week"]))
            confidence = touchdown_confidence(prob)
        else:
            key = (row["player_id"], row["week"], row["stat_type"])
            if key not in variance_by_key:
                history = player_histories.get(row["player_id"], [])
                built = variance_row(row["player_id"], row["season"], row["week"], row["stat_type"], history, stamp)
                variance_rows.append(built)
                variance_by_key[key] = built["own_stddev"]
            confidence = yardage_confidence(row["edge"], variance_by_key[key])

        if confidence is not None:
            updates.append({"id": row["id"], "confidence": confidence})

    return variance_rows, updates


def load_confidence(conn: sqlite3.Connection, season: int, week: int | None = None) -> int:
    edge_count = conn.execute(
        "SELECT COUNT(*) FROM projections WHERE season = ? AND edge IS NOT NULL", (season,)
    ).fetchone()[0]
    if edge_count == 0:
        raise RuntimeError(
            f"no projections with an edge for {season}; this feature has nothing to be "
            f"confident about yet. Run: statify compute edge --season {season}"
        )

    player_rows = [dict(row) for row in conn.execute(PLAYER_HISTORY_QUERY, {"season": season}).fetchall()]
    histories: dict[str, list[dict]] = {}
    for row in player_rows:
        histories.setdefault(row["player_id"], []).append(row)

    touchdown_index = {
        (row["player_id"], row["week"]): row["anytime_td_prob"]
        for row in conn.execute(TOUCHDOWN_QUERY, {"season": season}).fetchall()
    }

    query = PROJECTIONS_QUERY
    params: dict = {"season": season}
    if week is not None:
        query += " AND week = :week"
        params["week"] = week
    projection_rows = [dict(row) for row in conn.execute(query, params).fetchall()]

    variance, updates = confidence_rows(projection_rows, histories, touchdown_index)
    if variance:
        write(conn, VARIANCE_UPSERT, variance)
    if updates:
        write(conn, CONFIDENCE_UPDATE, updates)
    return len(updates)
