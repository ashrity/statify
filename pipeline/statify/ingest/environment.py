"""What kind of game each team is walking into.

Feature 18 multiplies opportunity by these. A 30-point implied total against a
fast opponent is a very different projection from 17 against a slow one, and
neither number means anything without the other.

No weather here. Migration 008 records that the stored reading is the settled
game-time condition rather than a forecast, so using it would leak the result
of the game being projected. Feature 14b adds a forecast source first.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from statify.ingest.common import utc_now, write
from statify.ingest.market import implied_team_total
from statify.ingest.usage import share
from statify.ingest.windows import paired_sum, prior_games


def median(values: list[float]) -> float | None:
    """Middle value, or the mean of the middle two. None when there is nothing.

    Preferred over a mean because one book posting a stale line should not move
    the consensus. Eight books at 52.5 and one at 44.0 is a stale book, not a
    47.6-point game.
    """
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def latest_per_book(rows: list[dict]) -> list[dict]:
    """One row per book, the most recent capture it posted.

    Lines move all week and every move is stored, so a book appears several
    times. Averaging across a book's own history would weight the books that
    moved most, which is the opposite of what a consensus wants.
    """
    best: dict[str, dict] = {}
    for row in rows:
        book = row["book"]
        if book not in best or row["captured_at"] > best[book]["captured_at"]:
            best[book] = row
    return list(best.values())


def consensus(rows: list[dict]) -> dict:
    """One line for one team in one game, from however many books posted it.

    The implied total is DERIVED from the two consensus numbers rather than
    taken as a third median. Three independent medians over books that disagree
    need not satisfy `total / 2 - spread / 2`, and that identity is the one
    property of this table worth being able to check.
    """
    latest = latest_per_book(rows)
    spread = median([r["spread"] for r in latest if r["spread"] is not None])
    total = median([r["game_total"] for r in latest if r["game_total"] is not None])
    return {
        "spread": spread,
        "game_total": total,
        "implied_team_total": implied_team_total(total, spread),
        "books": len(latest),
        "market_captured_at": max((r["captured_at"] for r in latest), default=None),
    }


# Each trailing rate with the denominator it must be weighted by. The numerator
# is a product rather than a stored column: team_tempo_weekly keeps the rate
# and its denominator, so the total is recovered by multiplying them back
# together. That is what makes a ratio of sums possible instead of a mean of
# weekly rates, in which a blowout week with 4 neutral snaps would weigh the
# same as a close one with 30.
TEMPO_RATES = {
    "pace": ("neutral_seconds", "neutral_intervals"),
    "proe": ("proe_total", "plays"),
}


def tempo_history_row(row: dict) -> dict:
    """One stored tempo week, with the products the weighting needs.

    neutral_seconds_per_play is preferred over seconds_per_play: feature 9b
    measured the raw figure at 29.1s against a 36.0s median and identified the
    gap as an artifact of incompletions stopping the clock.
    """
    pace_rate = row.get("neutral_seconds_per_play")
    intervals = row.get("neutral_intervals")
    proe_rate = row.get("proe")
    plays = row.get("plays")
    return {
        "week": row["week"],
        "neutral_intervals": intervals,
        "neutral_seconds": None if pace_rate is None or intervals is None
        else pace_rate * intervals,
        "plays": plays,
        "proe_total": None if proe_rate is None or plays is None else proe_rate * plays,
    }


def trailing_tempo(history: list[dict], week: int) -> dict:
    """A team's pace and PROE going into `week`, from earlier weeks only.

    Strictly prior, the same rule as features 11a, 13a and 13b. A week 7 row
    built with week 7's own pace would be describing the game it is meant to
    project, and nothing downstream would show it.
    """
    prior = prior_games(history, week)
    values: dict = {}
    for name, (numerator, denominator) in TEMPO_RATES.items():
        top, bottom = paired_sum(prior, numerator, denominator)
        values[name] = share(top, bottom)
        values[f"{name}_weeks"] = sum(
            1 for game in prior
            if game.get(numerator) is not None and game.get(denominator) is not None
        )
    return values


def opponent_of(game: dict, team_abbr: str) -> str:
    """The other side of a game."""
    return game["away_team"] if team_abbr == game["home_team"] else game["home_team"]


def environment_row(
    game: dict,
    team_abbr: str,
    market: list[dict],
    histories: dict[str, list[dict]],
    forecast: dict | None,
    updated_at: str,
) -> dict:
    """One team's environment for one game.

    The opponent's pace sits on the same row because game pace is set by both
    offences: a fast team facing a slow one sees fewer drives than its own
    number suggests, and feature 18 should not have to go looking for the
    other half.
    """
    week = game["week"]
    own = trailing_tempo(histories.get(team_abbr, []), week)
    opponent = trailing_tempo(histories.get(opponent_of(game, team_abbr), []), week)
    line = consensus(market)

    return {
        "game_id": game["game_id"],
        "team_abbr": team_abbr,
        "season": game["season"],
        "week": week,
        "spread": line["spread"],
        "game_total": line["game_total"],
        "implied_team_total": line["implied_team_total"],
        "books": line["books"],
        "market_captured_at": line["market_captured_at"],
        "pace": own["pace"],
        "pace_weeks": own["pace_weeks"],
        "proe": own["proe"],
        "proe_weeks": own["proe_weeks"],
        "opponent_pace": opponent["pace"],
        "opponent_proe": opponent["proe"],
        # Weather belongs to the game, so both of its rows carry the same
        # values. NULL for a dome, where weather does not apply, and for any
        # game with no forecast: past games can never have one, and games
        # beyond the provider's 16-day horizon do not have one yet.
        "wind_mph": (forecast or {}).get("wind_mph"),
        "temperature_f": (forecast or {}).get("temperature_f"),
        "precip_chance": (forecast or {}).get("precip_chance"),
        "updated_at": updated_at,
    }


def environment_rows(
    games: list[dict],
    market: dict[tuple[str, str], list[dict]],
    histories: dict[str, list[dict]],
    forecasts: dict[str, dict],
    updated_at: str,
) -> list[dict]:
    """Two rows per game, one per team.

    Driven by games rather than by the market, so a week with no captured line
    still gets its pace half. Past weeks can never have a line, because
    historical odds are a paid tier, and feature 23's backtest wants them.
    """
    rows = []
    for game in games:
        for team_abbr in (game["home_team"], game["away_team"]):
            rows.append(
                environment_row(
                    game, team_abbr,
                    market.get((game["game_id"], team_abbr), []),
                    histories, forecasts.get(game["game_id"]), updated_at,
                )
            )
    return rows


ENVIRONMENT_UPSERT = """
INSERT INTO game_environment_weekly (
  game_id, team_abbr, season, week,
  spread, game_total, implied_team_total, books, market_captured_at,
  pace, pace_weeks, proe, proe_weeks,
  opponent_pace, opponent_proe,
  wind_mph, temperature_f, precip_chance, updated_at
)
VALUES (
  :game_id, :team_abbr, :season, :week,
  :spread, :game_total, :implied_team_total, :books, :market_captured_at,
  :pace, :pace_weeks, :proe, :proe_weeks,
  :opponent_pace, :opponent_proe,
  :wind_mph, :temperature_f, :precip_chance, :updated_at
)
ON CONFLICT(game_id, team_abbr) DO UPDATE SET
  season = excluded.season,
  week = excluded.week,
  spread = excluded.spread,
  game_total = excluded.game_total,
  implied_team_total = excluded.implied_team_total,
  books = excluded.books,
  market_captured_at = excluded.market_captured_at,
  pace = excluded.pace,
  pace_weeks = excluded.pace_weeks,
  proe = excluded.proe,
  proe_weeks = excluded.proe_weeks,
  opponent_pace = excluded.opponent_pace,
  opponent_proe = excluded.opponent_proe,
  wind_mph = excluded.wind_mph,
  temperature_f = excluded.temperature_f,
  precip_chance = excluded.precip_chance,
  updated_at = excluded.updated_at
"""

GAMES_QUERY = """
SELECT game_id, season, week, home_team, away_team
FROM games WHERE season = ? ORDER BY week, game_id
"""

MARKET_QUERY = """
SELECT game_id, team_abbr, book, spread, game_total, captured_at
FROM team_market_data WHERE season = ?
"""

TEMPO_QUERY = """
SELECT team_abbr, week, plays, neutral_intervals, neutral_seconds_per_play, proe
FROM team_tempo_weekly WHERE season = ?
"""


# The latest forecast per game. Earlier captures are history feature 27 will
# want; the environment carries whichever was most recent.
FORECAST_QUERY = """
SELECT game_id, wind_mph, temperature_f, precip_chance
FROM game_forecast
WHERE (game_id, captured_at) IN (
  SELECT game_id, MAX(captured_at) FROM game_forecast
  WHERE season = ? GROUP BY game_id
)
"""


def load_environment(conn: sqlite3.Connection, season: int) -> tuple[int, int, int]:
    """Compute and upsert one season's environment.

    Returns (rows, rows_with_a_market_line, rows_with_trailing_pace). The two
    counts legitimately differ: a past week has pace and can never have a line,
    and week 1 has a line but no pace.
    """
    games = [dict(row) for row in conn.execute(GAMES_QUERY, (season,))]

    market: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in conn.execute(MARKET_QUERY, (season,)):
        entry = dict(row)
        market[(entry["game_id"], entry["team_abbr"])].append(entry)

    histories: dict[str, list[dict]] = defaultdict(list)
    for row in conn.execute(TEMPO_QUERY, (season,)):
        entry = dict(row)
        histories[entry["team_abbr"]].append(tempo_history_row(entry))

    forecasts = {
        row[0]: {"wind_mph": row[1], "temperature_f": row[2], "precip_chance": row[3]}
        for row in conn.execute(FORECAST_QUERY, (season,))
    }

    rows = environment_rows(games, market, histories, forecasts, utc_now())
    write(conn, ENVIRONMENT_UPSERT, rows)
    return (
        len(rows),
        sum(1 for row in rows if row["books"]),
        sum(1 for row in rows if row["pace"] is not None),
    )
