"""Matchup and environment multipliers for a week a player has not played
yet, stopping at the multiplier rather than the final number: feature 19
multiplies these onto its opportunity-times-efficiency baseline.

Both multipliers are centered at 1.0 so a league-average matchup or
league-average pace changes nothing. team_matchup_weekly already expresses a
defense as a difference from league average; game_environment_weekly already
has each team's own strictly-prior pace. This module only looks the right
rows up, converts them with a measured constant, and leaves a missing input
as None rather than a default.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import utc_now, write

# Measured on 2024 weeks 6 to 18 by the same grid-sweep style as every prior
# weight in this pipeline, against the ratio of actual yardage to the
# opportunity-times-efficiency baseline. See migration 029 for the full table.
#
# Two of three were measured and rejected, the same honest outcome features
# 15a found for opponent adjustment on team volume. PASS_MATCHUP_K and
# ENVIRONMENT_M both ship at 0.0: every nonzero value tried made MAE worse,
# monotonically, so no adjustment beat any adjustment. RUSH_MATCHUP_K ships
# at the measured 0.5, a genuine interior minimum (12.9706 at 0.0, 12.9300 at
# 0.5, 12.9668 at 0.75), not a boundary artifact, so it ships as measured.
PASS_MATCHUP_K = 0.0
RUSH_MATCHUP_K = 0.5
ENVIRONMENT_M = 0.0

OPPONENT_QUERY = """
SELECT game_id, week, home_team, away_team
FROM games
WHERE season = :season
"""

DRIVER_QUERY = """
SELECT player_id, season, week, team_abbr
FROM player_opportunity_weekly
WHERE season = :season
"""

PLAYERS_QUERY = "SELECT player_id, position FROM players"

MATCHUP_QUERY = """
SELECT team_abbr, week, position, play_type, epa_allowed_over_league_std
FROM team_matchup_weekly
WHERE season = :season
"""

ENVIRONMENT_QUERY = """
SELECT game_id, team_abbr, week, pace, opponent_pace
FROM game_environment_weekly
WHERE season = :season
"""

MATCHUP_ENVIRONMENT_UPSERT = """
INSERT INTO player_matchup_environment_weekly (
  player_id, season, week, team_abbr, opponent_team_abbr, position,
  pass_matchup_multiplier, rush_matchup_multiplier, environment_multiplier,
  opponent_pass_epa_over_league, opponent_rush_epa_over_league,
  own_pace, opponent_pace, league_pace, pace_ratio,
  pass_matchup_k, rush_matchup_k, environment_m,
  updated_at
)
VALUES (
  :player_id, :season, :week, :team_abbr, :opponent_team_abbr, :position,
  :pass_matchup_multiplier, :rush_matchup_multiplier, :environment_multiplier,
  :opponent_pass_epa_over_league, :opponent_rush_epa_over_league,
  :own_pace, :opponent_pace, :league_pace, :pace_ratio,
  :pass_matchup_k, :rush_matchup_k, :environment_m,
  :updated_at
)
ON CONFLICT(player_id, season, week) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  opponent_team_abbr = excluded.opponent_team_abbr,
  position = excluded.position,
  pass_matchup_multiplier = excluded.pass_matchup_multiplier,
  rush_matchup_multiplier = excluded.rush_matchup_multiplier,
  environment_multiplier = excluded.environment_multiplier,
  opponent_pass_epa_over_league = excluded.opponent_pass_epa_over_league,
  opponent_rush_epa_over_league = excluded.opponent_rush_epa_over_league,
  own_pace = excluded.own_pace,
  opponent_pace = excluded.opponent_pace,
  league_pace = excluded.league_pace,
  pace_ratio = excluded.pace_ratio,
  pass_matchup_k = excluded.pass_matchup_k,
  rush_matchup_k = excluded.rush_matchup_k,
  environment_m = excluded.environment_m,
  updated_at = excluded.updated_at
"""


def opponent_map(schedule_rows: list[dict]) -> dict[tuple[str, int], tuple[str, str]]:
    """(team, week) -> (opponent, game_id), for both sides of every game."""
    mapping: dict[tuple[str, int], tuple[str, str]] = {}
    for row in schedule_rows:
        mapping[(row["home_team"], row["week"])] = (row["away_team"], row["game_id"])
        mapping[(row["away_team"], row["week"])] = (row["home_team"], row["game_id"])
    return mapping


def matchup_index(matchup_rows: list[dict]) -> dict[tuple[str, int, str, str], float | None]:
    """(team, week, position, play_type) -> epa_allowed_over_league_std."""
    return {
        (row["team_abbr"], row["week"], row["position"], row["play_type"]): row["epa_allowed_over_league_std"]
        for row in matchup_rows
    }


def environment_index(environment_rows: list[dict]) -> dict[tuple[str, str], dict]:
    """(game_id, team) -> {pace, opponent_pace}."""
    return {(row["game_id"], row["team_abbr"]): row for row in environment_rows}


def combined_pace(own_pace: float | None, opponent_pace: float | None) -> float | None:
    """The game's own-plus-opponent pace, averaged; a single side if that's all there is."""
    sides = [p for p in (own_pace, opponent_pace) if p is not None]
    return sum(sides) / len(sides) if sides else None


def league_pace_by_week(environment_rows: list[dict]) -> dict[int, float]:
    """The cross-sectional mean combined pace across every team with one, per week.

    Each side's own pace is already strictly prior within game_environment_weekly,
    so averaging across teams for the same week introduces no leak.
    """
    by_week: dict[int, list[float]] = {}
    for row in environment_rows:
        value = combined_pace(row["pace"], row["opponent_pace"])
        if value is not None:
            by_week.setdefault(row["week"], []).append(value)
    return {week: sum(values) / len(values) for week, values in by_week.items()}


def pace_ratio(league: float | None, own: float | None) -> float | None:
    """>1 means the game projects faster than league average (lower seconds per play)."""
    if league is None or not own:
        return None
    return league / own


def multiplier(k: float, factor: float | None) -> float | None:
    if factor is None:
        return None
    return 1 + k * factor


def environment_multiplier(m: float, ratio: float | None) -> float | None:
    if ratio is None:
        return None
    return 1 + m * (ratio - 1)


def matchup_environment_row(
    player_id: str,
    season: int,
    week: int,
    team_abbr: str,
    position: str,
    opponent_team_abbr: str,
    game_id: str,
    matchup: dict[tuple[str, int, str, str], float | None],
    environment: dict[tuple[str, str], dict],
    league_pace: dict[int, float],
    pass_k: float,
    rush_k: float,
    env_m: float,
    updated_at: str,
) -> dict:
    opponent_pass_epa = matchup.get((opponent_team_abbr, week, position, "pass"))
    opponent_rush_epa = matchup.get((opponent_team_abbr, week, position, "rush"))

    env_row = environment.get((game_id, team_abbr), {})
    own_pace = env_row.get("pace")
    opponent_pace = env_row.get("opponent_pace")
    own_combined = combined_pace(own_pace, opponent_pace)
    league = league_pace.get(week)
    ratio = pace_ratio(league, own_combined)

    return {
        "player_id": player_id,
        "season": season,
        "week": week,
        "team_abbr": team_abbr,
        "opponent_team_abbr": opponent_team_abbr,
        "position": position,
        "pass_matchup_multiplier": multiplier(pass_k, opponent_pass_epa),
        "rush_matchup_multiplier": multiplier(rush_k, opponent_rush_epa),
        "environment_multiplier": environment_multiplier(env_m, ratio),
        "opponent_pass_epa_over_league": opponent_pass_epa,
        "opponent_rush_epa_over_league": opponent_rush_epa,
        "own_pace": own_pace,
        "opponent_pace": opponent_pace,
        "league_pace": league,
        "pace_ratio": ratio,
        "pass_matchup_k": pass_k,
        "rush_matchup_k": rush_k,
        "environment_m": env_m,
        "updated_at": updated_at,
    }


def matchup_environment_rows(
    driver_rows: list[dict],
    schedule_rows: list[dict],
    matchup_rows: list[dict],
    environment_rows: list[dict],
    positions: dict[str, str],
    season: int,
    updated_at: str | None = None,
) -> list[dict]:
    stamp = updated_at or utc_now()

    opponents = opponent_map(schedule_rows)
    matchup = matchup_index(matchup_rows)
    environment = environment_index(environment_rows)
    league_pace = league_pace_by_week(environment_rows)

    rows = []
    for driver in driver_rows:
        team_abbr = driver["team_abbr"]
        week = driver["week"]
        position = positions.get(driver["player_id"])
        opponent = opponents.get((team_abbr, week))
        if position is None or opponent is None:
            continue
        opponent_team_abbr, game_id = opponent
        rows.append(
            matchup_environment_row(
                driver["player_id"],
                season,
                week,
                team_abbr,
                position,
                opponent_team_abbr,
                game_id,
                matchup,
                environment,
                league_pace,
                PASS_MATCHUP_K,
                RUSH_MATCHUP_K,
                ENVIRONMENT_M,
                stamp,
            )
        )
    return rows


def load_matchup_environment(conn: sqlite3.Connection, season: int, week: int | None = None) -> int:
    opportunity_rows = conn.execute(
        "SELECT COUNT(*) FROM player_opportunity_weekly WHERE season = ?", (season,)
    ).fetchone()[0]
    if opportunity_rows == 0:
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

    schedule_rows = [dict(row) for row in conn.execute(OPPONENT_QUERY, {"season": season}).fetchall()]
    matchup_rows = [dict(row) for row in conn.execute(MATCHUP_QUERY, {"season": season}).fetchall()]
    environment_rows = [dict(row) for row in conn.execute(ENVIRONMENT_QUERY, {"season": season}).fetchall()]
    positions = {row["player_id"]: row["position"] for row in conn.execute(PLAYERS_QUERY).fetchall()}

    rows = matchup_environment_rows(
        driver_rows, schedule_rows, matchup_rows, environment_rows, positions, season
    )
    if rows:
        write(conn, MATCHUP_ENVIRONMENT_UPSERT, rows)
    return len(rows)
