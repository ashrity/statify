"""Expected touchdowns for a week a player has not played yet.

A rushing TD rate per carry and a receiving TD rate per target, each blended
toward the league rate at the player's position, multiplied by feature 15b's
expected carries and targets, combined into one Poisson rate and converted to
the probability of scoring at least one, which is what feature 7b's
anytime-touchdown market prices.

Rows follow player_opportunity_weekly's row set, reusing its exp_targets and
exp_carries as the volume this model's rates multiply.
"""

from __future__ import annotations

import math
import sqlite3

from statify.ingest.common import utc_now, write
from statify.ingest.usage import share
from statify.ingest.volume import blend
from statify.ingest.windows import paired_sum, prior_games

# Measured on 2024 weeks 6 to 18, mean absolute error against the actual
# realized rate that week. See migration 028 for the full table.
#
# The opposite signal from feature 16: both curves improve monotonically as
# the own-weight rises, with argmins at the edge of the grid (1.0 for
# rushing, 0.9 for receiving, where the top of each curve is close to flat).
# A boundary argmin from one season's grid search is the textbook overfitting
# signal, so neither weight ships at the literal edge; 0.8 sits inside both
# flat high-weight plateaus, the same round number RUSH_OWN_WEIGHT uses for
# the same reason in team_volume_weekly. Shrinking toward the position barely
# helps and at the rushing rate actively hurts, likely because a touchdown
# role (goal-line back, slot-fade target) varies more within a position than
# yardage efficiency does, so pooling the position washes out exactly the
# signal that matters here.
RUSHING_TD_RATE_OWN_WEIGHT = 0.8
RECEIVING_TD_RATE_OWN_WEIGHT = 0.8

RATES: dict[str, tuple[str, str, float]] = {
    "rushing_td_rate": ("rushing_tds", "carries", RUSHING_TD_RATE_OWN_WEIGHT),
    "receiving_td_rate": ("receiving_tds", "targets", RECEIVING_TD_RATE_OWN_WEIGHT),
}

DRIVER_QUERY = """
SELECT player_id, season, week, team_abbr, exp_targets, exp_carries
FROM player_opportunity_weekly
WHERE season = :season
"""

PLAYERS_QUERY = "SELECT player_id, position FROM players"

PLAYER_HISTORY_QUERY = """
SELECT player_id, week, carries, rushing_tds, targets, receiving_tds
FROM weekly_actuals
WHERE season = :season
ORDER BY player_id, week
"""

TOUCHDOWN_UPSERT = """
INSERT INTO player_touchdown_expected_weekly (
  player_id, season, week, team_abbr, position,
  exp_rushing_tds, exp_receiving_tds, exp_touchdowns, anytime_td_prob,
  exp_rushing_td_rate, exp_receiving_td_rate,
  own_rushing_td_rate, own_receiving_td_rate,
  position_rushing_td_rate, position_receiving_td_rate,
  rushing_opportunities, receiving_opportunities,
  rushing_td_rate_own_weight, receiving_td_rate_own_weight,
  updated_at
)
VALUES (
  :player_id, :season, :week, :team_abbr, :position,
  :exp_rushing_tds, :exp_receiving_tds, :exp_touchdowns, :anytime_td_prob,
  :exp_rushing_td_rate, :exp_receiving_td_rate,
  :own_rushing_td_rate, :own_receiving_td_rate,
  :position_rushing_td_rate, :position_receiving_td_rate,
  :rushing_opportunities, :receiving_opportunities,
  :rushing_td_rate_own_weight, :receiving_td_rate_own_weight,
  :updated_at
)
ON CONFLICT(player_id, season, week) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  position = excluded.position,
  exp_rushing_tds = excluded.exp_rushing_tds,
  exp_receiving_tds = excluded.exp_receiving_tds,
  exp_touchdowns = excluded.exp_touchdowns,
  anytime_td_prob = excluded.anytime_td_prob,
  exp_rushing_td_rate = excluded.exp_rushing_td_rate,
  exp_receiving_td_rate = excluded.exp_receiving_td_rate,
  own_rushing_td_rate = excluded.own_rushing_td_rate,
  own_receiving_td_rate = excluded.own_receiving_td_rate,
  position_rushing_td_rate = excluded.position_rushing_td_rate,
  position_receiving_td_rate = excluded.position_receiving_td_rate,
  rushing_opportunities = excluded.rushing_opportunities,
  receiving_opportunities = excluded.receiving_opportunities,
  rushing_td_rate_own_weight = excluded.rushing_td_rate_own_weight,
  receiving_td_rate_own_weight = excluded.receiving_td_rate_own_weight,
  updated_at = excluded.updated_at
"""


def attach_positions(rows: list[dict], positions: dict[str, str]) -> list[dict]:
    return [{**row, "position": positions.get(row["player_id"])} for row in rows]


def position_week_totals(rows: list[dict]) -> dict[tuple[str, int], dict]:
    """Sum rushing and receiving TDs/opportunities across a position, per week."""
    totals: dict[tuple[str, int], dict] = {}
    fields = ("carries", "rushing_tds", "targets", "receiving_tds")
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
    return sum(1 for game in games if game.get(denominator))


def rate_for(games: list[dict], numerator: str, denominator: str) -> float | None:
    top, bottom = paired_sum(games, numerator, denominator)
    return share(top, bottom)


def position_rate_for(
    position: str, week: int, position_totals: dict[tuple[str, int], dict], numerator: str, denominator: str
) -> float | None:
    prior = [totals for (pos, played), totals in position_totals.items() if pos == position and played < week]
    top = sum(t[numerator] for t in prior)
    bottom = sum(t[denominator] for t in prior)
    return share(top, bottom)


def anytime_probability(exp_touchdowns: float | None) -> float | None:
    """Poisson probability of at least one touchdown, or None if the rate is unknown."""
    if exp_touchdowns is None:
        return None
    return 1 - math.exp(-exp_touchdowns)


def touchdown_row(
    player_id: str,
    season: int,
    week: int,
    team_abbr: str,
    position: str,
    exp_targets: float | None,
    exp_carries: float | None,
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
        "rushing_opportunities": opportunity_count(prior, "carries"),
        "receiving_opportunities": opportunity_count(prior, "targets"),
    }

    rates: dict[str, float | None] = {}
    for stat, (numerator, denominator, weight) in RATES.items():
        own = rate_for(prior, numerator, denominator)
        position_rate = position_rate_for(position, week, position_totals, numerator, denominator)
        row[f"own_{stat}"] = own
        row[f"position_{stat}"] = position_rate
        exp_rate = blend(own, position_rate, weight)
        row[f"exp_{stat}"] = exp_rate
        row[f"{stat}_own_weight"] = weight
        rates[stat] = exp_rate

    exp_rushing_tds = (
        exp_carries * rates["rushing_td_rate"] if exp_carries is not None and rates["rushing_td_rate"] is not None else None
    )
    exp_receiving_tds = (
        exp_targets * rates["receiving_td_rate"]
        if exp_targets is not None and rates["receiving_td_rate"] is not None
        else None
    )
    row["exp_rushing_tds"] = exp_rushing_tds
    row["exp_receiving_tds"] = exp_receiving_tds

    if exp_rushing_tds is None or exp_receiving_tds is None:
        exp_touchdowns = None
    else:
        exp_touchdowns = exp_rushing_tds + exp_receiving_tds
    row["exp_touchdowns"] = exp_touchdowns
    row["anytime_td_prob"] = anytime_probability(exp_touchdowns)

    return row


def touchdown_rows(
    driver_rows: list[dict],
    player_rows: list[dict],
    positions: dict[str, str],
    season: int,
    updated_at: str | None = None,
) -> list[dict]:
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
            touchdown_row(
                player_id,
                season,
                driver["week"],
                driver["team_abbr"],
                position,
                driver["exp_targets"],
                driver["exp_carries"],
                history,
                position_totals,
                stamp,
            )
        )
    return rows


def load_touchdowns(conn: sqlite3.Connection, season: int, week: int | None = None) -> int:
    opportunity_rows = conn.execute(
        "SELECT COUNT(*) FROM player_opportunity_weekly WHERE season = ?", (season,)
    ).fetchone()[0]
    if opportunity_rows == 0:
        raise RuntimeError(
            f"no player opportunity rows for {season}; this table reuses that row "
            f"set and its exp_targets/exp_carries. Run: statify compute opportunity --season {season}"
        )

    driver_query = DRIVER_QUERY
    params: dict = {"season": season}
    if week is not None:
        driver_query += " AND week = :week"
        params["week"] = week
    driver_rows = [dict(row) for row in conn.execute(driver_query, params).fetchall()]

    player_rows = [dict(row) for row in conn.execute(PLAYER_HISTORY_QUERY, {"season": season}).fetchall()]
    positions = {row["player_id"]: row["position"] for row in conn.execute(PLAYERS_QUERY).fetchall()}

    rows = touchdown_rows(driver_rows, player_rows, positions, season)
    if rows:
        write(conn, TOUCHDOWN_UPSERT, rows)
    return len(rows)
