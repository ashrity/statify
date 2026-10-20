"""Expected player targets, carries, attempts and routes for a week.

Feature 16 multiplies this by expected efficiency. The whole value of the
table is in the blend: targets, carries and attempts each weigh the player's
own trailing per-game average against his trailing share of his team's
expectation (team_volume_weekly, feature 15a), with the weight measured per
stat and fixed in code. Routes has no team-level expectation to share against,
so it is the player's own trailing average, unconditionally.

Rows follow the player's own history crossed with his team's schedule, not his
results. The expectation worth having is for the week he has not played, and
nothing here depends on a roster source: depth_charts would normally supply
one, but it fails outright on 2026, so a player's row exists only once he has
at least one game this season to build it from.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import utc_now, write
from statify.ingest.usage import share
from statify.ingest.volume import ACTUALS_QUERY as TEAM_ACTUALS_QUERY
from statify.ingest.volume import SCHEDULE_QUERY, blend, scheduled, team_week_totals
from statify.ingest.windows import paired_sum, prior_games

# Measured on 2024 weeks 6 to 18, the same window feature 15a measured on, over
# every player-week where both the own-trailing estimate and the team-share
# estimate were present (4,761 rows). See migration 026 for the full table.
#
# Unlike team_volume_weekly's sharp pass/rush asymmetry, all three curves here
# are close to flat: a player's own trailing rate and his trailing share of
# the team's expectation mostly agree, because the team's expectation is
# itself built from recent weeks that correlate with his own. The weight
# barely matters for targets and carries; it matters a little more for
# attempts, where who starts at quarterback is sticky enough that leaning on
# his own rate past ~0.3 own-weight makes things worse, not better.
#
#   weight   targets   carries   attempts
#     0.0     1.3358    1.0858     0.8285
#     0.3     1.3338    1.0837     0.8286
#     0.5     1.3336    1.0831     0.8311
#     1.0     1.3385    1.0840     0.8425
#
# Argmins were 0.4 (targets), 0.5 (carries) and 0.1 (attempts), each inside a
# flat band rather than a sharp minimum, so round numbers inside those bands
# are shipped rather than one season's argmin, the same judgement 15a made
# for rush_own_weight.
TARGETS_OWN_WEIGHT = 0.5
CARRIES_OWN_WEIGHT = 0.5
ATTEMPTS_OWN_WEIGHT = 0.2

PLAYER_HISTORY_QUERY = """
SELECT player_id, week, team_abbr, targets, carries, attempts, routes_run
FROM weekly_actuals
WHERE season = :season
ORDER BY player_id, week
"""

TEAM_VOLUME_QUERY = """
SELECT team_abbr, week, exp_targets, exp_carries, exp_attempts
FROM team_volume_weekly
WHERE season = :season
"""

OPPORTUNITY_UPSERT = """
INSERT INTO player_opportunity_weekly (
  player_id, season, week, team_abbr, games_played,
  exp_targets, exp_carries, exp_attempts, exp_routes,
  own_targets_pg, own_carries_pg, own_attempts_pg, own_routes_pg,
  target_share, carries_share, attempts_share,
  team_exp_targets, team_exp_carries, team_exp_attempts,
  targets_own_weight, carries_own_weight, attempts_own_weight,
  updated_at
)
VALUES (
  :player_id, :season, :week, :team_abbr, :games_played,
  :exp_targets, :exp_carries, :exp_attempts, :exp_routes,
  :own_targets_pg, :own_carries_pg, :own_attempts_pg, :own_routes_pg,
  :target_share, :carries_share, :attempts_share,
  :team_exp_targets, :team_exp_carries, :team_exp_attempts,
  :targets_own_weight, :carries_own_weight, :attempts_own_weight,
  :updated_at
)
ON CONFLICT(player_id, season, week) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  games_played = excluded.games_played,
  exp_targets = excluded.exp_targets,
  exp_carries = excluded.exp_carries,
  exp_attempts = excluded.exp_attempts,
  exp_routes = excluded.exp_routes,
  own_targets_pg = excluded.own_targets_pg,
  own_carries_pg = excluded.own_carries_pg,
  own_attempts_pg = excluded.own_attempts_pg,
  own_routes_pg = excluded.own_routes_pg,
  target_share = excluded.target_share,
  carries_share = excluded.carries_share,
  attempts_share = excluded.attempts_share,
  team_exp_targets = excluded.team_exp_targets,
  team_exp_carries = excluded.team_exp_carries,
  team_exp_attempts = excluded.team_exp_attempts,
  targets_own_weight = excluded.targets_own_weight,
  carries_own_weight = excluded.carries_own_weight,
  attempts_own_weight = excluded.attempts_own_weight,
  updated_at = excluded.updated_at
"""


def attach_team_totals(rows: list[dict], totals: dict[tuple[str, int], dict]) -> list[dict]:
    """Add each game's team totals onto the player's own row for that game.

    Lets carries_share and attempts_share reuse paired_sum exactly the way
    player_form_weekly's shares do, rather than a second share implementation.
    """
    attached = []
    for row in rows:
        team = totals.get((row["team_abbr"], row["week"]), {})
        attached.append(
            {
                **row,
                "team_targets": team.get("targets"),
                "team_carries": team.get("carries"),
                "team_attempts": team.get("attempts"),
            }
        )
    return attached


def build_histories(rows: list[dict]) -> dict[str, list[dict]]:
    """Index attached player rows by player, each list already week-ordered."""
    histories: dict[str, list[dict]] = {}
    for row in rows:
        histories.setdefault(row["player_id"], []).append(row)
    return histories


def _mean(games: list[dict], field: str) -> float | None:
    """A plain mean over games where the field is present.

    targets, carries and attempts are NOT NULL DEFAULT 0 in weekly_actuals, so
    this never drops a game for them. routes_run is nullable (every 2026 row,
    every QB), and a missing value there leaves the game out rather than
    counting it as a zero.
    """
    present = [game[field] for game in games if game.get(field) is not None]
    return sum(present) / len(present) if present else None


def trailing_share(games: list[dict], numerator: str, denominator: str) -> float | None:
    top, bottom = paired_sum(games, numerator, denominator)
    return share(top, bottom)


def _team_share_estimate(team_exp: float | None, player_share: float | None) -> float | None:
    """His trailing share of the team's expectation, or None if either side is unknown."""
    if team_exp is None or player_share is None:
        return None
    return team_exp * player_share


def opportunity_row(
    player_id: str,
    season: int,
    week: int,
    prior: list[dict],
    team_exp: dict,
    updated_at: str,
) -> dict:
    """One player's expected opportunity for one week, built only from `prior`."""
    team_abbr = prior[-1]["team_abbr"]

    own_targets_pg = _mean(prior, "targets")
    own_carries_pg = _mean(prior, "carries")
    own_attempts_pg = _mean(prior, "attempts")
    own_routes_pg = _mean(prior, "routes_run")

    target_share = trailing_share(prior, "targets", "team_targets")
    carries_share = trailing_share(prior, "carries", "team_carries")
    attempts_share = trailing_share(prior, "attempts", "team_attempts")

    team_exp_targets = team_exp.get("exp_targets")
    team_exp_carries = team_exp.get("exp_carries")
    team_exp_attempts = team_exp.get("exp_attempts")

    return {
        "player_id": player_id,
        "season": season,
        "week": week,
        "team_abbr": team_abbr,
        "games_played": len(prior),
        "exp_targets": blend(
            own_targets_pg, _team_share_estimate(team_exp_targets, target_share), TARGETS_OWN_WEIGHT
        ),
        "exp_carries": blend(
            own_carries_pg, _team_share_estimate(team_exp_carries, carries_share), CARRIES_OWN_WEIGHT
        ),
        "exp_attempts": blend(
            own_attempts_pg, _team_share_estimate(team_exp_attempts, attempts_share), ATTEMPTS_OWN_WEIGHT
        ),
        "exp_routes": own_routes_pg,
        "own_targets_pg": own_targets_pg,
        "own_carries_pg": own_carries_pg,
        "own_attempts_pg": own_attempts_pg,
        "own_routes_pg": own_routes_pg,
        "target_share": target_share,
        "carries_share": carries_share,
        "attempts_share": attempts_share,
        "team_exp_targets": team_exp_targets,
        "team_exp_carries": team_exp_carries,
        "team_exp_attempts": team_exp_attempts,
        "targets_own_weight": TARGETS_OWN_WEIGHT,
        "carries_own_weight": CARRIES_OWN_WEIGHT,
        "attempts_own_weight": ATTEMPTS_OWN_WEIGHT,
        "updated_at": updated_at,
    }


def opportunity_rows(
    player_rows: list[dict],
    team_actuals_rows: list[dict],
    schedule_rows: list[dict],
    team_volume_rows: list[dict],
    season: int,
    week: int | None = None,
    updated_at: str | None = None,
) -> list[dict]:
    """One row per player per week he has prior history and his team is scheduled."""
    stamp = updated_at or utc_now()

    totals = team_week_totals(team_actuals_rows)
    histories = build_histories(attach_team_totals(player_rows, totals))

    scheduled_weeks = scheduled(schedule_rows)
    weeks = sorted({w for _, w in scheduled_weeks} if week is None else {week})

    team_exp = {(row["team_abbr"], row["week"]): row for row in team_volume_rows}

    rows: list[dict] = []
    for player_id, history in histories.items():
        for w in weeks:
            prior = prior_games(history, w)
            if not prior:
                continue
            team_abbr = prior[-1]["team_abbr"]
            if (team_abbr, w) not in scheduled_weeks:
                continue
            rows.append(
                opportunity_row(
                    player_id, season, w, prior, team_exp.get((team_abbr, w), {}), stamp
                )
            )
    return rows


def load_player_opportunity(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> int:
    volume_count = conn.execute(
        "SELECT COUNT(*) FROM team_volume_weekly WHERE season = ?", (season,)
    ).fetchone()[0]
    if volume_count == 0:
        raise RuntimeError(
            f"no team volume rows for {season}; exp_targets/carries/attempts come "
            f"from that table. Run: statify compute volume --season {season}"
        )

    player_rows = [
        dict(row) for row in conn.execute(PLAYER_HISTORY_QUERY, {"season": season}).fetchall()
    ]
    team_actuals_rows = [
        dict(row) for row in conn.execute(TEAM_ACTUALS_QUERY, {"season": season}).fetchall()
    ]
    schedule_rows = [
        dict(row) for row in conn.execute(SCHEDULE_QUERY, {"season": season}).fetchall()
    ]
    team_volume_rows = [
        dict(row) for row in conn.execute(TEAM_VOLUME_QUERY, {"season": season}).fetchall()
    ]

    rows = opportunity_rows(
        player_rows, team_actuals_rows, schedule_rows, team_volume_rows, season, week
    )
    if rows:
        write(conn, OPPORTUNITY_UPSERT, rows)
    return len(rows)
