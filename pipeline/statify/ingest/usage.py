"""Compute each player's share of his team's weekly opportunity.

Unlike the other computed features, this one can be checked: nflverse publishes
target_share, air_yards_share and wopr independently, so step 3 compares our
numbers against theirs row by row.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from statify.ingest.common import utc_now, write
from statify.sources import nflverse

SEASON_TYPES = frozenset({"REG", "POST"})

# WOPR's published weights. Verified against nflverse to 1e-10 over 249 rows.
TARGET_SHARE_WEIGHT = 1.5
AIR_YARDS_SHARE_WEIGHT = 0.7

# The two denominators come from different places, and both choices were settled
# by measuring against the values nflverse publishes rather than by reasoning.
#
# Air yards: play-by-play, over every pass attempt including throwaways that
# reach no receiver. Restricting to plays with a credited receiver understates it
# by 3.4% (137,849 against 142,665 for 2024) and WOPR carries 0.7 of that error.
#
# Targets: the sum of our own player rows. Counting play-by-play targets instead
# looks more principled, since it would include the tackle-eligible catches that
# players does not store, and it was tried: agreement with nflverse fell from 98%
# to 89%. nflverse builds its denominator from its own player rows too, so the
# player sum is the definition the rest of the world is using.
PBP_COLUMNS = [
    "game_id",
    "season_type",
    "posteam",
    "pass",
    "air_yards",
    "qb_dropback",
    "special_teams_play",
]

USAGE_UPSERT = """
INSERT INTO player_usage_weekly (
  player_id, game_id, season, week, team_abbr,
  targets, team_targets, target_share,
  air_yards, team_air_yards, air_yards_share,
  wopr, adot,
  red_zone_touches, team_red_zone_touches, red_zone_touch_share,
  routes, team_dropbacks, route_participation, targets_per_route,
  updated_at
)
VALUES (
  :player_id, :game_id, :season, :week, :team_abbr,
  :targets, :team_targets, :target_share,
  :air_yards, :team_air_yards, :air_yards_share,
  :wopr, :adot,
  :red_zone_touches, :team_red_zone_touches, :red_zone_touch_share,
  :routes, :team_dropbacks, :route_participation, :targets_per_route,
  :updated_at
)
ON CONFLICT(player_id, game_id) DO UPDATE SET
  team_targets = excluded.team_targets,
  target_share = excluded.target_share,
  air_yards = excluded.air_yards,
  team_air_yards = excluded.team_air_yards,
  air_yards_share = excluded.air_yards_share,
  wopr = excluded.wopr,
  adot = excluded.adot,
  red_zone_touches = excluded.red_zone_touches,
  team_red_zone_touches = excluded.team_red_zone_touches,
  red_zone_touch_share = excluded.red_zone_touch_share,
  routes = excluded.routes,
  team_dropbacks = excluded.team_dropbacks,
  route_participation = excluded.route_participation,
  targets_per_route = excluded.targets_per_route,
  targets = excluded.targets,
  updated_at = excluded.updated_at
"""


def share(numerator: float | None, denominator: float | None) -> float | None:
    """A share, or None when there was nothing to take a share of.

    Zero denominator and zero numerator are different states. A team that
    attempted no passes has no target share to give, which is not the same as a
    player who was on the field and drew none of them.
    """
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def weighted_opportunity(target_share: float | None, air_yards_share: float | None) -> float | None:
    """WOPR. None if either input is None, rather than treating absence as zero."""
    if target_share is None or air_yards_share is None:
        return None
    return TARGET_SHARE_WEIGHT * target_share + AIR_YARDS_SHARE_WEIGHT * air_yards_share


def team_air_yards(plays: list[dict]) -> dict[tuple[str, str], int]:
    """Team air yards per game, over every pass attempt."""
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for play in plays:
        if (
            play.get("posteam")
            and play.get("season_type") in SEASON_TYPES
            and play.get("pass") == 1
            and play.get("air_yards") is not None
        ):
            totals[(play["posteam"], play["game_id"])] += play["air_yards"]
    return totals


def team_dropbacks(plays: list[dict]) -> dict[tuple[str, str], int]:
    """Dropbacks per team per game, the denominator for route participation.

    Matches the rule feature 10b counts routes on, so a participation rate can
    never exceed 1 through a definition mismatch.
    """
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for play in plays:
        if (
            play.get("posteam")
            and play.get("season_type") in SEASON_TYPES
            and play.get("qb_dropback") == 1
            and play.get("special_teams_play") != 1
        ):
            totals[(play["posteam"], play["game_id"])] += 1
    return totals


def usage_row(actual: dict, team: dict, updated_at: str) -> dict:
    """One player's shares for one game."""
    target_share = share(actual["targets"], team["targets"])
    air_yards_share = share(actual["air_yards"], team["air_yards"])
    return {
        "player_id": actual["player_id"],
        "game_id": actual["game_id"],
        "season": actual["season"],
        "week": actual["week"],
        "team_abbr": actual["team_abbr"],
        "targets": actual["targets"],
        "team_targets": team["targets"],
        "target_share": target_share,
        "air_yards": actual["air_yards"],
        "team_air_yards": team["air_yards"],
        "air_yards_share": air_yards_share,
        "wopr": weighted_opportunity(target_share, air_yards_share),
        "adot": share(actual["air_yards"], actual["targets"]),
        "red_zone_touches": actual["red_zone_touches"],
        "team_red_zone_touches": team["red_zone_touches"],
        "red_zone_touch_share": share(actual["red_zone_touches"], team["red_zone_touches"]),
        "routes": actual["routes_run"],
        "team_dropbacks": team["dropbacks"],
        "route_participation": share(actual["routes_run"], team["dropbacks"]),
        "targets_per_route": share(actual["targets"], actual["routes_run"]),
        "updated_at": updated_at,
    }


def aggregate_usage(
    actuals: list[dict],
    air_yards_by_team: dict[tuple[str, str], int],
    dropbacks_by_team: dict[tuple[str, str], int],
    updated_at: str,
) -> list[dict]:
    """Turn weekly actuals into usage rows, one per input row."""
    team_totals: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"targets": 0, "air_yards": 0, "red_zone_touches": 0}
    )
    for actual in actuals:
        totals = team_totals[(actual["team_abbr"], actual["game_id"])]
        totals["targets"] += actual["targets"]
        # A NULL red zone count means the play-by-play pass has not run for this
        # game, not that the player had none, so it must not join the total.
        if actual["red_zone_touches"] is not None:
            totals["red_zone_touches"] += actual["red_zone_touches"]

    rows = []
    for actual in actuals:
        key = (actual["team_abbr"], actual["game_id"])
        team = dict(team_totals[key])
        team["air_yards"] = air_yards_by_team.get(key, 0)
        team["dropbacks"] = dropbacks_by_team.get(key, 0)
        rows.append(usage_row(actual, team, updated_at))
    return rows


def load_usage(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, int]:
    """Compute and upsert one season's usage shares. Returns (rows, rows_missing_air_yards)."""
    query = (
        "SELECT player_id, game_id, season, week, team_abbr, targets, air_yards, "
        "red_zone_touches, routes_run FROM weekly_actuals WHERE season = ?"
    )
    params: tuple = (season,)
    if week is not None:
        query += " AND week = ?"
        params = (season, week)
    actuals = [dict(row) for row in conn.execute(query, params)]

    plays = list(nflverse.pbp(season, PBP_COLUMNS).iter_rows(named=True))
    rows = aggregate_usage(actuals, team_air_yards(plays), team_dropbacks(plays), utc_now())

    write(conn, USAGE_UPSERT, rows)
    return len(rows), sum(1 for row in rows if not row["team_air_yards"])
