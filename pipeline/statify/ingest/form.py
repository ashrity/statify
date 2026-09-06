"""Compute what a player's usage looked like going into each week.

The window boundary is the whole point of this module. A week N row must be
built from games strictly before week N. If a week's own game leaks into its own
average, feature 19 projects a game using that game's result and feature 27's
backtest measures nothing, while every number here still looks reasonable. That
failure has no downstream symptom, so `prior_games` is tested directly rather
than inferred from an aggregate.
"""

from __future__ import annotations

from statify.ingest.common import utc_now, write
from statify.ingest.usage import share, weighted_opportunity

# Suffix and window size. None means every prior game of the season.
WINDOWS: tuple[tuple[str, int | None], ...] = (("l3", 3), ("l5", 5), ("std", None))

# Numerator and denominator for each volume-weighted rate.
WEIGHTED_RATES = {
    "target_share": ("targets", "team_targets"),
    "air_yards_share": ("air_yards", "team_air_yards"),
    "adot": ("air_yards", "targets"),
    "rz_touch_share": ("red_zone_touches", "team_red_zone_touches"),
    "route_participation": ("routes", "team_dropbacks"),
    "targets_per_route": ("targets", "routes"),
}

PER_GAME = {"targets_pg": "targets", "carries_pg": "carries", "routes_pg": "routes"}

VALUE_COLUMNS = tuple(PER_GAME) + tuple(WEIGHTED_RATES) + ("wopr", "snap_share")


def prior_games(history: list[dict], week: int) -> list[dict]:
    """Games before `week`, oldest first.

    Strictly before. `<=` here would leak the week's own result into its own
    form and quietly invalidate every projection built on it.
    """
    return sorted((game for game in history if game["week"] < week), key=lambda g: g["week"])


def window_slice(prior: list[dict], size: int | None) -> list[dict]:
    """The most recent `size` games played, or all of them.

    Counted in games, not weeks. A player who missed a month has a last-3 window
    of his last three appearances; counting weeks would fold the absences in as
    zeros.
    """
    if size is None:
        return prior
    return prior[-size:]


def _paired_sum(games: list[dict], numerator: str, denominator: str) -> tuple[float, float]:
    """Sum a numerator and denominator over games where both are present."""
    top = bottom = 0.0
    for game in games:
        if game.get(numerator) is None or game.get(denominator) is None:
            continue
        top += game[numerator]
        bottom += game[denominator]
    return top, bottom


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def window_values(games: list[dict]) -> dict:
    """Every metric for one window. All None when the window is empty."""
    if not games:
        return dict.fromkeys(VALUE_COLUMNS)

    values: dict = {}
    for column, field in PER_GAME.items():
        present = [g[field] for g in games if g.get(field) is not None]
        values[column] = _mean(present)

    for column, (numerator, denominator) in WEIGHTED_RATES.items():
        top, bottom = _paired_sum(games, numerator, denominator)
        values[column] = share(top, bottom)

    # From the windowed shares, not an average of weekly WOPR: the shares are
    # volume-weighted and averaging the composite would discard that.
    values["wopr"] = weighted_opportunity(values["target_share"], values["air_yards_share"])

    # The one metric that cannot be volume-weighted. Feature 4a stored the
    # percentage without the team snap count, so a mean is all there is.
    values["snap_share"] = _mean([g["snap_share"] for g in games if g.get("snap_share") is not None])
    return values


def form_row(player_id: str, season: int, week: int, history: list[dict], updated_at: str) -> dict:
    """One player's form entering one week."""
    row = {"player_id": player_id, "season": season, "week": week, "updated_at": updated_at}
    prior = prior_games(history, week)

    for suffix, size in WINDOWS:
        games = window_slice(prior, size)
        row[f"games_{suffix}"] = len(games)
        for column, value in window_values(games).items():
            row[f"{column}_{suffix}"] = value

    # Recorded even when there is no history, so the parameter is visible on
    # every row rather than only on rows that happened to have data.
    row["ewma_half_life"] = EWMA_HALF_LIFE
    for column, value in ewma_values(prior).items():
        row[f"{column}_ewma"] = value
    return row


def form_rows(player_id: str, season: int, history: list[dict], updated_at: str) -> list[dict]:
    """A row per week the player appeared, each built only from earlier weeks."""
    return [
        form_row(player_id, season, game["week"], history, updated_at)
        for game in sorted(history, key=lambda g: g["week"])
    ]


def form_columns() -> list[str]:
    """Every column of player_form_weekly, in a fixed order."""
    columns = ["player_id", "season", "week"]
    for suffix, _ in WINDOWS:
        columns.append(f"games_{suffix}")
        columns.extend(f"{value}_{suffix}" for value in VALUE_COLUMNS)
    columns.append("ewma_half_life")
    columns.extend(f"{value}_ewma" for value in VALUE_COLUMNS)
    columns.append("updated_at")
    return columns


def _upsert_sql() -> str:
    """Built from the same constants as the rows.

    The other loaders spell their SQL out, which is the better default: the
    statement reads as a data contract. Thirty columns is where that stops being
    true, and where a column present in the row dict but missing from the
    statement would be dropped in silence.
    """
    columns = form_columns()
    keys = {"player_id", "season", "week"}
    assignments = ",\n  ".join(
        f"{column} = excluded.{column}" for column in columns if column not in keys
    )
    return (
        f"INSERT INTO player_form_weekly ({', '.join(columns)})\n"
        f"VALUES ({', '.join(':' + column for column in columns)})\n"
        "ON CONFLICT(player_id, season, week) DO UPDATE SET\n"
        f"  {assignments}\n"
    )


FORM_UPSERT = _upsert_sql()

# player_usage_weekly holds the shares and their denominators; weekly_actuals
# holds carries and snap_share, which never became usage metrics.
HISTORY_QUERY = """
SELECT u.player_id, u.week, u.targets, u.team_targets,
       u.air_yards, u.team_air_yards,
       u.red_zone_touches, u.team_red_zone_touches,
       u.routes, u.team_dropbacks,
       w.carries, w.snap_share
FROM player_usage_weekly u
JOIN weekly_actuals w ON w.player_id = u.player_id AND w.game_id = u.game_id
WHERE u.season = ?
ORDER BY u.player_id, u.week
"""


def load_form(conn, season: int) -> tuple[int, int]:
    """Compute and upsert one season's form. Returns (rows, rows_with_no_history).

    Takes no week filter: a week's form depends on every earlier week, so the
    season is the natural unit.
    """
    histories: dict[str, list[dict]] = {}
    for row in conn.execute(HISTORY_QUERY, (season,)):
        game = dict(row)
        histories.setdefault(game.pop("player_id"), []).append(game)

    updated_at = utc_now()
    rows: list[dict] = []
    for player_id, history in histories.items():
        rows.extend(form_rows(player_id, season, history, updated_at))

    write(conn, FORM_UPSERT, rows)
    return len(rows), sum(1 for row in rows if row["games_std"] == 0)


# A game three appearances back carries half the weight of the most recent one.
# A judgement rather than a fitted value: the overview asks for a window of
# three to five games, and three sits at the responsive end, beside the l3
# window. Feature 31 is where weights get learned.
EWMA_HALF_LIFE = 3.0


def decay_weights(count: int, half_life: float) -> list[float]:
    """One weight per game, oldest first, with the most recent at 1.0.

    Anchoring the newest game at 1.0 rather than normalising keeps the numbers
    readable: a weight of 0.5 is visibly one half-life old.
    """
    return [0.5 ** ((count - 1 - index) / half_life) for index in range(count)]


def _weighted_pair(
    games: list[dict], weights: list[float], numerator: str, denominator: str | None
) -> tuple[float, float]:
    """Weighted sums of a numerator and its denominator.

    With no denominator field the weights themselves are the denominator, which
    turns the result into a weighted mean.
    """
    top = bottom = 0.0
    for weight, game in zip(weights, games):
        value = game.get(numerator)
        if value is None:
            continue
        if denominator is None:
            top += weight * value
            bottom += weight
            continue
        divisor = game.get(denominator)
        if divisor is None:
            continue
        top += weight * value
        bottom += weight * divisor
    return top, bottom


def ewma_values(games: list[dict], half_life: float = EWMA_HALF_LIFE) -> dict:
    """The same metrics as `window_values`, weighted toward recent games.

    Every rate weights its numerator and denominator separately. Weighting the
    already-computed share instead is the obvious implementation and it throws
    away volume, the same error a mean of ratios would make: measured across 506
    players it moves target share by up to 0.0202.

    `games` must be oldest first, which is what `prior_games` returns.
    """
    if not games:
        return dict.fromkeys(VALUE_COLUMNS)

    weights = decay_weights(len(games), half_life)
    values: dict = {}

    for column, field in PER_GAME.items():
        values[column] = share(*_weighted_pair(games, weights, field, None))

    for column, (numerator, denominator) in WEIGHTED_RATES.items():
        values[column] = share(*_weighted_pair(games, weights, numerator, denominator))

    values["wopr"] = weighted_opportunity(values["target_share"], values["air_yards_share"])
    values["snap_share"] = share(*_weighted_pair(games, weights, "snap_share", None))
    return values
