"""Expected team targets, carries and pass attempts for a week.

Feature 15b multiplies a player's trailing share by these. The whole value of
the table is in one measured asymmetry, recorded in full in migration 025:
passing volume is barely a team property, so it shrinks hard toward the league,
while rushing volume is one, so it mostly trusts the team. The two weights pull
in opposite directions on purpose.

Rows follow the schedule rather than the results. The expectation worth having
is for the week nobody has played yet, and a loader driven by `weekly_actuals`
would emit a row for every week except that one.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import utc_now, write
from statify.ingest.windows import prior_games

# Measured on 2024 weeks 6 to 18. See migration 025 for the full table.
#
# The pass curve has a sharp minimum at 0.30 and rises in both directions. The
# rush curve is flat from 0.7 to 1.0, so its argmin of 0.90 is one season's
# noise and 0.8 is a round number inside the flat region. The finding is
# "mostly the team", not "0.90".
PASS_OWN_WEIGHT = 0.3
RUSH_OWN_WEIGHT = 0.8

# Summed per team-week from weekly_actuals, which is the same source
# compute usage builds team_targets from, so the two cannot disagree about
# what a team target is.
COUNTED = ("targets", "carries", "attempts")

ACTUALS_QUERY = """
SELECT team_abbr, week,
       SUM(COALESCE(targets, 0))  AS targets,
       SUM(COALESCE(carries, 0))  AS carries,
       SUM(COALESCE(attempts, 0)) AS attempts
FROM weekly_actuals
WHERE season = :season
GROUP BY team_abbr, week
"""

SCHEDULE_QUERY = """
SELECT week, home_team, away_team
FROM games
WHERE season = :season
"""

VOLUME_UPSERT = """
INSERT INTO team_volume_weekly (
  team_abbr, season, week, games_played,
  exp_targets, exp_carries, exp_attempts,
  own_targets_pg, own_carries_pg, own_attempts_pg,
  league_targets_pg, league_carries_pg, league_attempts_pg,
  pass_own_weight, rush_own_weight, updated_at
)
VALUES (
  :team_abbr, :season, :week, :games_played,
  :exp_targets, :exp_carries, :exp_attempts,
  :own_targets_pg, :own_carries_pg, :own_attempts_pg,
  :league_targets_pg, :league_carries_pg, :league_attempts_pg,
  :pass_own_weight, :rush_own_weight, :updated_at
)
ON CONFLICT(team_abbr, season, week) DO UPDATE SET
  games_played = excluded.games_played,
  exp_targets = excluded.exp_targets,
  exp_carries = excluded.exp_carries,
  exp_attempts = excluded.exp_attempts,
  own_targets_pg = excluded.own_targets_pg,
  own_carries_pg = excluded.own_carries_pg,
  own_attempts_pg = excluded.own_attempts_pg,
  league_targets_pg = excluded.league_targets_pg,
  league_carries_pg = excluded.league_carries_pg,
  league_attempts_pg = excluded.league_attempts_pg,
  pass_own_weight = excluded.pass_own_weight,
  rush_own_weight = excluded.rush_own_weight,
  updated_at = excluded.updated_at
"""


def blend(own: float | None, league: float | None, weight: float) -> float | None:
    """Shrink a team's own rate toward the league's.

    Either side missing collapses to the other rather than to a zero. In week 1
    both are missing and the answer is None: nobody has played, so there is no
    honest number, and the cross-season prior that would supply one is feature
    30's job.
    """
    if own is None:
        return league
    if league is None:
        return own
    return weight * own + (1 - weight) * league


def team_week_totals(rows: list[dict]) -> dict[tuple[str, int], dict]:
    """Index the per team-week sums by team and week."""
    return {(row["team_abbr"], row["week"]): row for row in rows}


def scheduled(rows: list[dict]) -> set[tuple[str, int]]:
    """Every team-week that has a game, from both sides of each one.

    A bye is simply an absence here, which is why games drive the rows: it
    needs no special case and cannot be mistaken for a zero-volume week.
    """
    weeks: set[tuple[str, int]] = set()
    for row in rows:
        weeks.add((row["home_team"], row["week"]))
        weeks.add((row["away_team"], row["week"]))
    return weeks


def _rate(games: list[dict], field: str) -> float | None:
    if not games:
        return None
    return sum(game[field] for game in games) / len(games)


def own_rates(history: list[dict], week: int) -> tuple[int, dict[str, float | None]]:
    """A team's per-game rates over the games it played before `week`.

    Per game played, never per week elapsed. A team that had its bye has fewer
    games than weeks, and dividing by weeks would quietly read the bye as a
    week it produced nothing.
    """
    prior = prior_games(history, week)
    return len(prior), {field: _rate(prior, field) for field in COUNTED}


def league_rates(totals: dict[tuple[str, int], dict], week: int) -> dict[str, float | None]:
    """The league's per-team-game rates over every game played before `week`.

    Over the same weeks a team's own window covers, which is the rule
    `compute matchup` follows: an early-season row compared against a
    full-season league average would be measuring the calendar, not the team.
    """
    prior = [row for (_, played), row in totals.items() if played < week]
    return {field: _rate(prior, field) for field in COUNTED}


def volume_row(
    team_abbr: str,
    season: int,
    week: int,
    history: list[dict],
    totals: dict[tuple[str, int], dict],
    updated_at: str,
) -> dict:
    played, own = own_rates(history, week)
    league = league_rates(totals, week)
    return {
        "team_abbr": team_abbr,
        "season": season,
        "week": week,
        "games_played": played,
        "exp_targets": blend(own["targets"], league["targets"], PASS_OWN_WEIGHT),
        "exp_carries": blend(own["carries"], league["carries"], RUSH_OWN_WEIGHT),
        "exp_attempts": blend(own["attempts"], league["attempts"], PASS_OWN_WEIGHT),
        "own_targets_pg": own["targets"],
        "own_carries_pg": own["carries"],
        "own_attempts_pg": own["attempts"],
        "league_targets_pg": league["targets"],
        "league_carries_pg": league["carries"],
        "league_attempts_pg": league["attempts"],
        "pass_own_weight": PASS_OWN_WEIGHT,
        "rush_own_weight": RUSH_OWN_WEIGHT,
        "updated_at": updated_at,
    }


def volume_rows(
    actuals: list[dict],
    schedule: list[dict],
    season: int,
    week: int | None = None,
    updated_at: str | None = None,
) -> list[dict]:
    """One row per team per scheduled game, oldest week first."""
    stamp = updated_at or utc_now()
    totals = team_week_totals(actuals)
    history: dict[str, list[dict]] = {}
    for (team_abbr, played), row in totals.items():
        history.setdefault(team_abbr, []).append({**row, "week": played})
    wanted = sorted(scheduled(schedule), key=lambda pair: (pair[1], pair[0]))
    return [
        volume_row(team_abbr, season, played, history.get(team_abbr, []), totals, stamp)
        for team_abbr, played in wanted
        if week is None or played == week
    ]


def load_team_volume(conn: sqlite3.Connection, season: int, week: int | None = None) -> int:
    actuals = [
        dict(row) for row in conn.execute(ACTUALS_QUERY, {"season": season}).fetchall()
    ]
    schedule = [
        dict(row) for row in conn.execute(SCHEDULE_QUERY, {"season": season}).fetchall()
    ]
    rows = volume_rows(actuals, schedule, season, week)
    if rows:
        write(conn, VOLUME_UPSERT, rows)
    return len(rows)
