"""Combine opportunity, efficiency, the touchdown model and the matchup/
environment multipliers into one raw projected value per player per week per
stat type.

No new weight is fitted here. Four stat types are a product of tables already
built; touchdowns is feature 17's anytime_td_prob, copied through
undecorated, because no matchup/environment multiplier was ever measured
against a probability.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import utc_now, write

# Each product stat type: which opportunity count and efficiency rate
# multiply together, and which of feature 18's two matchup multipliers
# applies. touchdowns is handled separately, since it is not a product.
STAT_FORMULAS: dict[str, tuple[str, str, str]] = {
    "receiving_yards": ("exp_targets", "exp_yards_per_target", "pass_matchup_multiplier"),
    "receptions": ("exp_targets", "exp_catch_rate", "pass_matchup_multiplier"),
    "rushing_yards": ("exp_carries", "exp_yards_per_carry", "rush_matchup_multiplier"),
    "passing_yards": ("exp_attempts", "exp_yards_per_attempt", "pass_matchup_multiplier"),
}

STAT_TYPES = (*STAT_FORMULAS.keys(), "touchdowns")

OPPORTUNITY_QUERY = """
SELECT player_id, season, week, team_abbr, exp_targets, exp_carries, exp_attempts
FROM player_opportunity_weekly
WHERE season = :season
"""

EFFICIENCY_QUERY = """
SELECT player_id, week, exp_yards_per_target, exp_catch_rate, exp_yards_per_carry, exp_yards_per_attempt
FROM player_efficiency_expected_weekly
WHERE season = :season
"""

TOUCHDOWN_QUERY = """
SELECT player_id, week, anytime_td_prob, exp_touchdowns
FROM player_touchdown_expected_weekly
WHERE season = :season
"""

MATCHUP_QUERY = """
SELECT player_id, week, position, pass_matchup_multiplier, rush_matchup_multiplier, environment_multiplier
FROM player_matchup_environment_weekly
WHERE season = :season
"""

PROJECTION_UPSERT = """
INSERT INTO player_raw_projection_weekly (
  player_id, season, week, stat_type, team_abbr, position,
  raw_projection, baseline_value, matchup_multiplier_used, environment_multiplier_used,
  updated_at
)
VALUES (
  :player_id, :season, :week, :stat_type, :team_abbr, :position,
  :raw_projection, :baseline_value, :matchup_multiplier_used, :environment_multiplier_used,
  :updated_at
)
ON CONFLICT(player_id, season, week, stat_type) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  position = excluded.position,
  raw_projection = excluded.raw_projection,
  baseline_value = excluded.baseline_value,
  matchup_multiplier_used = excluded.matchup_multiplier_used,
  environment_multiplier_used = excluded.environment_multiplier_used,
  updated_at = excluded.updated_at
"""


def neutral(value: float | None) -> float:
    """A missing multiplier becomes 1.0, feature 18's deferred decision, made here."""
    return 1.0 if value is None else value


def product_row(
    opportunity_count: float | None,
    efficiency_rate: float | None,
    matchup_multiplier: float | None,
    environment_multiplier: float | None,
) -> tuple[float | None, float | None, float, float]:
    """baseline, raw_projection, matchup_used, environment_used for one product stat type."""
    matchup_used = neutral(matchup_multiplier)
    environment_used = neutral(environment_multiplier)
    if opportunity_count is None or efficiency_rate is None:
        return None, None, matchup_used, environment_used
    baseline = opportunity_count * efficiency_rate
    return baseline, baseline * matchup_used * environment_used, matchup_used, environment_used


def projection_rows_for_player_week(
    player_id: str,
    season: int,
    week: int,
    team_abbr: str,
    opportunity: dict,
    efficiency: dict | None,
    touchdown: dict | None,
    matchup: dict | None,
    updated_at: str,
) -> list[dict]:
    position = (matchup or {}).get("position")
    if position is None:
        return []

    pass_mult = (matchup or {}).get("pass_matchup_multiplier")
    rush_mult = (matchup or {}).get("rush_matchup_multiplier")
    env_mult = (matchup or {}).get("environment_multiplier")

    sources = {"pass_matchup_multiplier": pass_mult, "rush_matchup_multiplier": rush_mult}

    rows = []
    for stat_type, (opp_field, eff_field, mult_field) in STAT_FORMULAS.items():
        opportunity_count = opportunity.get(opp_field)
        efficiency_rate = (efficiency or {}).get(eff_field)
        baseline, raw, matchup_used, environment_used = product_row(
            opportunity_count, efficiency_rate, sources[mult_field], env_mult
        )
        rows.append(
            {
                "player_id": player_id,
                "season": season,
                "week": week,
                "stat_type": stat_type,
                "team_abbr": team_abbr,
                "position": position,
                "raw_projection": raw,
                "baseline_value": baseline,
                "matchup_multiplier_used": matchup_used,
                "environment_multiplier_used": environment_used,
                "updated_at": updated_at,
            }
        )

    td_prob = (touchdown or {}).get("anytime_td_prob")
    td_baseline = (touchdown or {}).get("exp_touchdowns")
    rows.append(
        {
            "player_id": player_id,
            "season": season,
            "week": week,
            "stat_type": "touchdowns",
            "team_abbr": team_abbr,
            "position": position,
            "raw_projection": td_prob,
            "baseline_value": td_baseline,
            "matchup_multiplier_used": None,
            "environment_multiplier_used": None,
            "updated_at": updated_at,
        }
    )
    return rows


def projection_rows(
    opportunity_rows: list[dict],
    efficiency_rows: list[dict],
    touchdown_rows: list[dict],
    matchup_rows: list[dict],
    season: int,
    updated_at: str | None = None,
) -> list[dict]:
    stamp = updated_at or utc_now()

    efficiency_by_key = {(row["player_id"], row["week"]): row for row in efficiency_rows}
    touchdown_by_key = {(row["player_id"], row["week"]): row for row in touchdown_rows}
    matchup_by_key = {(row["player_id"], row["week"]): row for row in matchup_rows}

    rows = []
    for opportunity in opportunity_rows:
        key = (opportunity["player_id"], opportunity["week"])
        rows.extend(
            projection_rows_for_player_week(
                opportunity["player_id"],
                season,
                opportunity["week"],
                opportunity["team_abbr"],
                opportunity,
                efficiency_by_key.get(key),
                touchdown_by_key.get(key),
                matchup_by_key.get(key),
                stamp,
            )
        )
    return rows


REQUIRED_TABLES = {
    "player_opportunity_weekly": "statify compute opportunity",
    "player_efficiency_expected_weekly": "statify compute expected-efficiency",
    "player_touchdown_expected_weekly": "statify compute touchdowns",
    "player_matchup_environment_weekly": "statify compute matchup-adjustment",
}


def load_projections(conn: sqlite3.Connection, season: int, week: int | None = None) -> int:
    for table, command in REQUIRED_TABLES.items():
        count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE season = ?", (season,)).fetchone()[0]
        if count == 0:
            raise RuntimeError(f"no rows in {table} for {season}. Run: {command} --season {season}")

    opportunity_query = OPPORTUNITY_QUERY
    params: dict = {"season": season}
    if week is not None:
        opportunity_query += " AND week = :week"
        params["week"] = week
    opportunity_rows = [dict(row) for row in conn.execute(opportunity_query, params).fetchall()]

    efficiency_rows = [dict(row) for row in conn.execute(EFFICIENCY_QUERY, {"season": season}).fetchall()]
    touchdown_rows = [dict(row) for row in conn.execute(TOUCHDOWN_QUERY, {"season": season}).fetchall()]
    matchup_rows = [dict(row) for row in conn.execute(MATCHUP_QUERY, {"season": season}).fetchall()]

    rows = projection_rows(opportunity_rows, efficiency_rows, touchdown_rows, matchup_rows, season)
    if rows:
        write(conn, PROJECTION_UPSERT, rows)
    return len(rows)
