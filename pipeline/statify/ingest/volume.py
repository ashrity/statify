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

# Feature 30. cross_season_weight = games_played / (games_played + k): 0 at
# week 1 (pure prior season), approaching 1 as the season goes on. Measured
# on 2026 weeks 1-5 against actual team volume. See migration 035 for the
# full table. One shared k across targets/carries/attempts rather than three
# separately fit constants: a single 2026 is not enough data to trust three
# noisy per-quantity optima, and all three cluster near this value anyway.
# Shrinkage beat no shrinkage for every quantity (6.26 to 5.88 for targets,
# 5.94 to 5.30 for carries, 6.45 to 6.13 for attempts); 10.0 is a round
# number inside the broad, shallow flat region every curve shared.
CROSS_SEASON_K = 10.0

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
  pass_own_weight, rush_own_weight,
  prior_season, prior_season_targets_pg, prior_season_carries_pg, prior_season_attempts_pg,
  cross_season_weight, updated_at
)
VALUES (
  :team_abbr, :season, :week, :games_played,
  :exp_targets, :exp_carries, :exp_attempts,
  :own_targets_pg, :own_carries_pg, :own_attempts_pg,
  :league_targets_pg, :league_carries_pg, :league_attempts_pg,
  :pass_own_weight, :rush_own_weight,
  :prior_season, :prior_season_targets_pg, :prior_season_carries_pg, :prior_season_attempts_pg,
  :cross_season_weight, :updated_at
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
  prior_season = excluded.prior_season,
  prior_season_targets_pg = excluded.prior_season_targets_pg,
  prior_season_carries_pg = excluded.prior_season_carries_pg,
  prior_season_attempts_pg = excluded.prior_season_attempts_pg,
  cross_season_weight = excluded.cross_season_weight,
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


def prior_season_rates(prior_season_totals: list[dict], team_abbr: str) -> dict[str, float | None]:
    """A team's full prior-season per-game rate, feature 30's cross-season prior.

    None for a team absent from that season entirely (relocation, expansion),
    the same "no data, no guess" rule every rate in this project follows.
    """
    games = [row for row in prior_season_totals if row["team_abbr"] == team_abbr]
    return {field: _rate(games, field) for field in COUNTED}


def cross_season_weight(games_played: int, k: float) -> float:
    """0 at games_played=0 (pure prior season), approaching 1 as the season
    goes on (pure current season)."""
    return games_played / (games_played + k)


def volume_row(
    team_abbr: str,
    season: int,
    week: int,
    history: list[dict],
    totals: dict[tuple[str, int], dict],
    updated_at: str,
    prior_season: int | None = None,
    prior_season_totals: list[dict] | None = None,
    cross_season_k: float = CROSS_SEASON_K,
) -> dict:
    played, own = own_rates(history, week)
    league = league_rates(totals, week)

    prior = (
        prior_season_rates(prior_season_totals, team_abbr)
        if prior_season is not None and prior_season_totals is not None
        else dict.fromkeys(COUNTED)
    )
    weight = cross_season_weight(played, cross_season_k)
    # own_targets_pg etc. (stored separately below) stay pure in-season;
    # shrunk_own only feeds exp_targets, never overwrites that definition.
    shrunk_own = {field: blend(own[field], prior[field], weight) for field in COUNTED}

    has_prior = prior_season is not None and any(v is not None for v in prior.values())

    return {
        "team_abbr": team_abbr,
        "season": season,
        "week": week,
        "games_played": played,
        "exp_targets": blend(shrunk_own["targets"], league["targets"], PASS_OWN_WEIGHT),
        "exp_carries": blend(shrunk_own["carries"], league["carries"], RUSH_OWN_WEIGHT),
        "exp_attempts": blend(shrunk_own["attempts"], league["attempts"], PASS_OWN_WEIGHT),
        "own_targets_pg": own["targets"],
        "own_carries_pg": own["carries"],
        "own_attempts_pg": own["attempts"],
        "league_targets_pg": league["targets"],
        "league_carries_pg": league["carries"],
        "league_attempts_pg": league["attempts"],
        "pass_own_weight": PASS_OWN_WEIGHT,
        "rush_own_weight": RUSH_OWN_WEIGHT,
        "prior_season": prior_season if has_prior else None,
        "prior_season_targets_pg": prior["targets"],
        "prior_season_carries_pg": prior["carries"],
        "prior_season_attempts_pg": prior["attempts"],
        "cross_season_weight": weight if has_prior else None,
        "updated_at": updated_at,
    }


def volume_rows(
    actuals: list[dict],
    schedule: list[dict],
    season: int,
    week: int | None = None,
    updated_at: str | None = None,
    prior_season: int | None = None,
    prior_season_actuals: list[dict] | None = None,
) -> list[dict]:
    """One row per team per scheduled game, oldest week first."""
    stamp = updated_at or utc_now()
    totals = team_week_totals(actuals)
    history: dict[str, list[dict]] = {}
    for (team_abbr, played), row in totals.items():
        history.setdefault(team_abbr, []).append({**row, "week": played})
    prior_season_totals = (
        [dict(row) for row in prior_season_actuals] if prior_season_actuals is not None else None
    )
    wanted = sorted(scheduled(schedule), key=lambda pair: (pair[1], pair[0]))
    return [
        volume_row(
            team_abbr,
            season,
            played,
            history.get(team_abbr, []),
            totals,
            stamp,
            prior_season=prior_season,
            prior_season_totals=prior_season_totals,
        )
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

    # The most recent earlier season this database has weekly_actuals for,
    # not necessarily season - 1: a gap year would otherwise silently look
    # like "no prior season" instead of reaching back further.
    prior_row = conn.execute(
        "SELECT MAX(season) AS season FROM weekly_actuals WHERE season < ?", (season,)
    ).fetchone()
    prior_season = prior_row["season"] if prior_row and prior_row["season"] is not None else None
    prior_season_actuals = (
        [dict(row) for row in conn.execute(ACTUALS_QUERY, {"season": prior_season}).fetchall()]
        if prior_season is not None
        else None
    )

    rows = volume_rows(
        actuals, schedule, season, week, prior_season=prior_season, prior_season_actuals=prior_season_actuals
    )
    if rows:
        write(conn, VOLUME_UPSERT, rows)
    return len(rows)
