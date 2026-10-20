"""Expected yards per target, catch rate, yards per carry and yards per
attempt, for a week a player has not played yet.

Feature 19 multiplies this by feature 15b's expected opportunity. The blend is
the whole point: a player's own trailing rate is noisy on a small sample, so
each rate shrinks toward the league rate at his position over the same prior
weeks, the weight measured per stat and fixed in code.

Rows follow player_opportunity_weekly's row set rather than re-deriving which
(player, week) pairs are worth projecting a second time.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import utc_now, write
from statify.ingest.usage import share
from statify.ingest.volume import blend
from statify.ingest.windows import paired_sum, prior_games

# Measured on 2024 weeks 6 to 18, mean absolute error against the actual
# realized rate that week. See migration 027 for the full table.
#
# Unlike team_volume_weekly and player_opportunity_weekly, where several
# curves came out nearly flat, every rate here has a real minimum: leaning on
# the position baseline clearly beats a player's own trailing rate alone
# (pure own MAE is the worst of the eleven weights tried, for all four
# stats), and blending beats the position baseline alone too, by a smaller
# but real margin. All four argmins land in 0.2-0.4 and are already round
# numbers, so no flat-region judgement call was needed this time.
YARDS_PER_TARGET_OWN_WEIGHT = 0.2
CATCH_RATE_OWN_WEIGHT = 0.4
YARDS_PER_CARRY_OWN_WEIGHT = 0.3
YARDS_PER_ATTEMPT_OWN_WEIGHT = 0.3

# Each rate's numerator, denominator and the own-weight constant that applies
# to it. receiving carries two rates (yards_per_target, catch_rate) over the
# same denominator, which is why receiving_opportunities (not two separate
# counts) describes both.
RATES: dict[str, tuple[str, str, float]] = {
    "yards_per_target": ("receiving_yards", "targets", YARDS_PER_TARGET_OWN_WEIGHT),
    "catch_rate": ("receptions", "targets", CATCH_RATE_OWN_WEIGHT),
    "yards_per_carry": ("rushing_yards", "carries", YARDS_PER_CARRY_OWN_WEIGHT),
    "yards_per_attempt": ("passing_yards", "attempts", YARDS_PER_ATTEMPT_OWN_WEIGHT),
}

# Which opportunity-count column each rate's sample size is reported against.
OPPORTUNITY_COLUMN = {
    "yards_per_target": "receiving_opportunities",
    "catch_rate": "receiving_opportunities",
    "yards_per_carry": "rushing_opportunities",
    "yards_per_attempt": "passing_opportunities",
}

DRIVER_QUERY = """
SELECT player_id, season, week, team_abbr
FROM player_opportunity_weekly
WHERE season = :season
"""

PLAYERS_QUERY = "SELECT player_id, position FROM players"

PLAYER_HISTORY_QUERY = """
SELECT player_id, week, targets, receiving_yards, receptions,
       carries, rushing_yards, attempts, passing_yards
FROM weekly_actuals
WHERE season = :season
ORDER BY player_id, week
"""

OPPORTUNITY_UPSERT = """
INSERT INTO player_efficiency_expected_weekly (
  player_id, season, week, team_abbr, position,
  exp_yards_per_target, exp_catch_rate, exp_yards_per_carry, exp_yards_per_attempt,
  own_yards_per_target, own_catch_rate, own_yards_per_carry, own_yards_per_attempt,
  position_yards_per_target, position_catch_rate, position_yards_per_carry, position_yards_per_attempt,
  receiving_opportunities, rushing_opportunities, passing_opportunities,
  yards_per_target_own_weight, catch_rate_own_weight,
  yards_per_carry_own_weight, yards_per_attempt_own_weight,
  updated_at
)
VALUES (
  :player_id, :season, :week, :team_abbr, :position,
  :exp_yards_per_target, :exp_catch_rate, :exp_yards_per_carry, :exp_yards_per_attempt,
  :own_yards_per_target, :own_catch_rate, :own_yards_per_carry, :own_yards_per_attempt,
  :position_yards_per_target, :position_catch_rate, :position_yards_per_carry, :position_yards_per_attempt,
  :receiving_opportunities, :rushing_opportunities, :passing_opportunities,
  :yards_per_target_own_weight, :catch_rate_own_weight,
  :yards_per_carry_own_weight, :yards_per_attempt_own_weight,
  :updated_at
)
ON CONFLICT(player_id, season, week) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  position = excluded.position,
  exp_yards_per_target = excluded.exp_yards_per_target,
  exp_catch_rate = excluded.exp_catch_rate,
  exp_yards_per_carry = excluded.exp_yards_per_carry,
  exp_yards_per_attempt = excluded.exp_yards_per_attempt,
  own_yards_per_target = excluded.own_yards_per_target,
  own_catch_rate = excluded.own_catch_rate,
  own_yards_per_carry = excluded.own_yards_per_carry,
  own_yards_per_attempt = excluded.own_yards_per_attempt,
  position_yards_per_target = excluded.position_yards_per_target,
  position_catch_rate = excluded.position_catch_rate,
  position_yards_per_carry = excluded.position_yards_per_carry,
  position_yards_per_attempt = excluded.position_yards_per_attempt,
  receiving_opportunities = excluded.receiving_opportunities,
  rushing_opportunities = excluded.rushing_opportunities,
  passing_opportunities = excluded.passing_opportunities,
  yards_per_target_own_weight = excluded.yards_per_target_own_weight,
  catch_rate_own_weight = excluded.catch_rate_own_weight,
  yards_per_carry_own_weight = excluded.yards_per_carry_own_weight,
  yards_per_attempt_own_weight = excluded.yards_per_attempt_own_weight,
  updated_at = excluded.updated_at
"""


def attach_positions(rows: list[dict], positions: dict[str, str]) -> list[dict]:
    return [{**row, "position": positions.get(row["player_id"])} for row in rows]


def position_week_totals(rows: list[dict]) -> dict[tuple[str, int], dict]:
    """Sum every counting stat across all players at a position, per week."""
    totals: dict[tuple[str, int], dict] = {}
    fields = ("targets", "receiving_yards", "receptions", "carries", "rushing_yards", "attempts", "passing_yards")
    for row in rows:
        position = row.get("position")
        if position is None:
            continue
        key = (position, row["week"])
        bucket = totals.setdefault(key, dict.fromkeys(fields, 0))
        for field in fields:
            bucket[field] += row[field]
    return totals


def opportunity_count(games: list[dict], denominator: str) -> int:
    """Prior games where this denominator was actually nonzero.

    Distinct from len(games): a player can have ten prior games and a
    yards-per-carry built from one of them, if the other nine had no carries.
    """
    return sum(1 for game in games if game.get(denominator))


def rate_for(games: list[dict], numerator: str, denominator: str) -> float | None:
    top, bottom = paired_sum(games, numerator, denominator)
    return share(top, bottom)


def position_rate_for(
    position: str, week: int, position_totals: dict[tuple[str, int], dict], numerator: str, denominator: str
) -> float | None:
    """The league rate at `position` over every week strictly before `week`."""
    prior = [totals for (pos, played), totals in position_totals.items() if pos == position and played < week]
    top = sum(t[numerator] for t in prior)
    bottom = sum(t[denominator] for t in prior)
    return share(top, bottom)


def efficiency_row(
    player_id: str,
    season: int,
    week: int,
    team_abbr: str,
    position: str,
    history: list[dict],
    position_totals: dict[tuple[str, int], dict],
    updated_at: str,
) -> dict:
    prior = prior_games(history, week)

    row = {
        "player_id": player_id,
        "season": season,
        "week": week,
        "team_abbr": team_abbr,
        "position": position,
        "updated_at": updated_at,
    }

    counts = {
        "receiving_opportunities": opportunity_count(prior, "targets"),
        "rushing_opportunities": opportunity_count(prior, "carries"),
        "passing_opportunities": opportunity_count(prior, "attempts"),
    }
    row.update(counts)

    for stat, (numerator, denominator, weight) in RATES.items():
        own = rate_for(prior, numerator, denominator)
        position_rate = position_rate_for(position, week, position_totals, numerator, denominator)
        row[f"own_{stat}"] = own
        row[f"position_{stat}"] = position_rate
        row[f"exp_{stat}"] = blend(own, position_rate, weight)
        row[f"{stat}_own_weight"] = weight

    return row


def expected_efficiency_rows(
    driver_rows: list[dict],
    player_rows: list[dict],
    positions: dict[str, str],
    season: int,
    updated_at: str | None = None,
) -> list[dict]:
    """One row per driver row (season, week, player, team), reusing
    player_opportunity_weekly's row set as the eligibility rule."""
    stamp = updated_at or utc_now()

    with_positions = attach_positions(player_rows, positions)
    position_totals = position_week_totals(with_positions)

    histories: dict[str, list[dict]] = {}
    for row in player_rows:
        histories.setdefault(row["player_id"], []).append(row)

    rows = []
    for driver in driver_rows:
        player_id = driver["player_id"]
        position = positions.get(player_id)
        if position is None:
            continue
        history = histories.get(player_id, [])
        rows.append(
            efficiency_row(
                player_id,
                season,
                driver["week"],
                driver["team_abbr"],
                position,
                history,
                position_totals,
                stamp,
            )
        )
    return rows


def load_expected_efficiency(conn: sqlite3.Connection, season: int, week: int | None = None) -> int:
    opportunity_count_rows = conn.execute(
        "SELECT COUNT(*) FROM player_opportunity_weekly WHERE season = ?", (season,)
    ).fetchone()[0]
    if opportunity_count_rows == 0:
        raise RuntimeError(
            f"no player opportunity rows for {season}; this table reuses that row "
            f"set. Run: statify compute opportunity --season {season}"
        )

    driver_query = DRIVER_QUERY
    params: dict = {"season": season}
    if week is not None:
        driver_query += " AND week = :week"
        params["week"] = week
    driver_rows = [dict(row) for row in conn.execute(driver_query, params).fetchall()]

    player_rows = [dict(row) for row in conn.execute(PLAYER_HISTORY_QUERY, {"season": season}).fetchall()]
    positions = {row["player_id"]: row["position"] for row in conn.execute(PLAYERS_QUERY).fetchall()}

    rows = expected_efficiency_rows(driver_rows, player_rows, positions, season)
    if rows:
        write(conn, OPPORTUNITY_UPSERT, rows)
    return len(rows)
