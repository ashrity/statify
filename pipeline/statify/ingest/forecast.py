"""Weather as it was expected, from a forecast provider.

The `weather` table already holds readings, and this feature could have used
them. Migration 008 explains why that would be wrong: those are settled
game-time conditions recorded after the fact, so projecting a game with them
leaks the result of the game being projected.

Coordinates are geocoded from place names rather than written down. Nothing in
nflverse publishes a latitude or longitude, and Open-Meteo resolves places but
not venues: "Lumen Field" returns nothing while "Seattle" returns a point about
a kilometre away, where the wind and temperature are the same numbers. The
point of the indirection is failure mode. A wrong place name returns nothing or
the wrong country and is visible; a hand-typed coordinate silently returns the
weather somewhere else.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from statify.ingest.common import utc_now, write
from statify.sources import nflverse, open_meteo

# stadium_id -> (place, country_code, admin1 or None)
#
# The state is not decoration. Measured against the live geocoder, taking the
# first result for "Santa Clara" returns Cuba and "Saint-Denis" returns
# Reunion, so two stadiums would have landed on the wrong continent. Where a
# name is unique within its country the state is None and the country alone
# decides.
#
# GER00 and MUN01 are two ids for the same Munich venue, so they resolve to the
# same coordinate on purpose.
STADIUM_PLACES: dict[str, tuple[str, str, str | None]] = {
    "ATL97": ("Atlanta", "US", "Georgia"),
    "BAL00": ("Baltimore", "US", "Maryland"),
    "BOS00": ("Foxborough", "US", "Massachusetts"),
    "BUF00": ("Orchard Park", "US", "New York"),
    "CAR00": ("Charlotte", "US", "North Carolina"),
    "CHI98": ("Chicago", "US", "Illinois"),
    "CIN00": ("Cincinnati", "US", "Ohio"),
    "CLE00": ("Cleveland", "US", "Ohio"),
    "DAL00": ("Arlington", "US", "Texas"),
    "DEN00": ("Denver", "US", "Colorado"),
    "DET00": ("Detroit", "US", "Michigan"),
    "GNB00": ("Green Bay", "US", "Wisconsin"),
    "HOU00": ("Houston", "US", "Texas"),
    "IND00": ("Indianapolis", "US", "Indiana"),
    "JAX00": ("Jacksonville", "US", "Florida"),
    "KAN00": ("Kansas City", "US", "Missouri"),
    "LAX01": ("Inglewood", "US", "California"),
    "MIA00": ("Miami Gardens", "US", "Florida"),
    "MIN01": ("Minneapolis", "US", "Minnesota"),
    "NAS00": ("Nashville", "US", "Tennessee"),
    "NOR00": ("New Orleans", "US", "Louisiana"),
    "NYC01": ("East Rutherford", "US", "New Jersey"),
    "PHI00": ("Philadelphia", "US", "Pennsylvania"),
    "PHO00": ("Glendale", "US", "Arizona"),
    "PIT00": ("Pittsburgh", "US", "Pennsylvania"),
    "SEA00": ("Seattle", "US", "Washington"),
    "SFO01": ("Santa Clara", "US", "California"),
    "TAM00": ("Tampa", "US", "Florida"),
    "VEG00": ("Las Vegas", "US", "Nevada"),
    "WAS00": ("Landover", "US", "Maryland"),
    "GER00": ("Munich", "DE", None),
    "MUN01": ("Munich", "DE", None),
    # Two different London stadiums about 10km apart. "London" resolves both to
    # the city centre; the district names land within a kilometre of each
    # ground, and both need the state filter because Wembley and Tottenham also
    # exist in Canada and Australia.
    "LON00": ("Wembley", "GB", "England"),
    "LON02": ("Tottenham", "GB", "England"),
    "MAD01": ("Madrid", "ES", None),
    "MEL00": ("Melbourne", "AU", None),
    "MEX00": ("Mexico City", "MX", None),
    "PAR00": ("Saint-Denis", "FR", None),
    "RIO00": ("Rio de Janeiro", "BR", None),
    "SAO00": ("Sao Paulo", "BR", None),
}

# Enough results to find the right one past a same-named place elsewhere.
GEOCODE_CANDIDATES = 10


def matches(result: dict, country_code: str, admin1: str | None) -> bool:
    """Whether a geocoder result is the place we meant."""
    if result.get("country_code") != country_code:
        return False
    return admin1 is None or result.get("admin1") == admin1


def pick_place(results: list[dict], country_code: str, admin1: str | None) -> dict | None:
    """The first result in the right country and state, or None.

    Never falls back to the first result. Falling back is what puts a stadium
    in Cuba.
    """
    for result in results:
        if matches(result, country_code, admin1):
            return result
    return None


def stadium_row(stadium_id: str, place: str, result: dict, now: str) -> dict:
    return {
        "stadium_id": stadium_id,
        "place": place,
        "country_code": result.get("country_code"),
        "latitude": result["latitude"],
        "longitude": result["longitude"],
        "resolved_at": now,
        "updated_at": now,
    }


STADIUM_UPSERT = """
INSERT INTO stadiums (
  stadium_id, place, country_code, latitude, longitude, resolved_at, updated_at
)
VALUES (
  :stadium_id, :place, :country_code, :latitude, :longitude, :resolved_at, :updated_at
)
ON CONFLICT(stadium_id) DO UPDATE SET
  place = excluded.place,
  country_code = excluded.country_code,
  latitude = excluded.latitude,
  longitude = excluded.longitude,
  resolved_at = excluded.resolved_at,
  updated_at = excluded.updated_at
"""


def load_stadiums(conn: sqlite3.Connection) -> tuple[int, list[str]]:
    """Geocode every known stadium once. Returns (stored, unresolved ids).

    One request per stadium, stored so it never has to be asked again.
    """
    now = utc_now()
    rows: list[dict] = []
    unresolved: list[str] = []

    for stadium_id, (place, country_code, admin1) in sorted(STADIUM_PLACES.items()):
        body = open_meteo.geocode_many(place, GEOCODE_CANDIDATES)
        result = pick_place(body, country_code, admin1)
        if result is None:
            unresolved.append(f"{stadium_id} ({place}, {country_code})")
            continue
        rows.append(stadium_row(stadium_id, place, result, now))

    write(conn, STADIUM_UPSERT, rows)
    return len(rows), unresolved


# Half the sampling interval. A kickoff further than this from every point is
# outside what the provider returned, and the nearest value would be hours or
# days wrong rather than slightly wrong.
HOUR_TOLERANCE = timedelta(minutes=30)


def parse_time(value: str) -> datetime:
    """Open-Meteo returns naive UTC timestamps; games store an offset."""
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def nearest_hour_index(times: list[str], kickoff: datetime) -> int | None:
    """Index of the hourly point closest to kickoff, or None if there is none.

    None rather than the closest edge value. A game outside the forecast window
    is days away from the nearest point, and returning it would look like a
    forecast instead of a gap.
    """
    if not times:
        return None
    best = min(range(len(times)), key=lambda i: abs(parse_time(times[i]) - kickoff))
    if abs(parse_time(times[best]) - kickoff) > HOUR_TOLERANCE:
        return None
    return best


def forecast_row(game: dict, hourly: dict, captured_at: str) -> dict | None:
    """One game's conditions at the hour nearest kickoff, or None if out of range.

    A 1pm and an 8pm kickoff in the same city are different games, which is why
    this reads the hourly series rather than a daily summary.
    """
    index = nearest_hour_index(hourly.get("time") or [], parse_time(game["kickoff_at"]))
    if index is None:
        return None
    return {
        "game_id": game["game_id"],
        "season": game["season"],
        "week": game["week"],
        "wind_mph": hourly["wind_speed_10m"][index],
        "temperature_f": hourly["temperature_2m"][index],
        "precip_chance": hourly["precipitation_probability"][index],
        "forecast_for": hourly["time"][index],
        "captured_at": captured_at,
        "updated_at": captured_at,
    }


FORECAST_UPSERT = """
INSERT INTO game_forecast (
  game_id, season, week, wind_mph, temperature_f, precip_chance,
  forecast_for, captured_at, updated_at
)
VALUES (
  :game_id, :season, :week, :wind_mph, :temperature_f, :precip_chance,
  :forecast_for, :captured_at, :updated_at
)
ON CONFLICT(game_id, captured_at) DO UPDATE SET
  season = excluded.season,
  week = excluded.week,
  wind_mph = excluded.wind_mph,
  temperature_f = excluded.temperature_f,
  precip_chance = excluded.precip_chance,
  forecast_for = excluded.forecast_for,
  updated_at = excluded.updated_at
"""


def latest_stored(conn: sqlite3.Connection, season: int) -> dict[str, tuple]:
    """The most recent forecast stored per game."""
    rows = conn.execute(
        """
        SELECT game_id, wind_mph, temperature_f, precip_chance
        FROM game_forecast
        WHERE (game_id, captured_at) IN (
          SELECT game_id, MAX(captured_at) FROM game_forecast
          WHERE season = ? GROUP BY game_id
        )
        """,
        (season,),
    )
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


def is_new_capture(row: dict, latest: dict[str, tuple]) -> bool:
    """Whether this forecast says anything the stored history does not.

    Content, never the clock. A forecast that has not moved is the same fact
    recorded twice, and `captured_at` differs on every run, so keying on it
    would store the whole slate again each time. Features 7a and 8 each made
    that mistake once.
    """
    previous = latest.get(row["game_id"])
    if previous is None:
        return True
    return (row["wind_mph"], row["temperature_f"], row["precip_chance"]) != previous


GAMES_QUERY = """
SELECT game_id, season, week, kickoff_at
FROM games WHERE season = ? AND is_dome = 0 ORDER BY week, game_id
"""


def load_forecasts(
    conn: sqlite3.Connection, season: int, week: int | None = None, dry_run: bool = False
) -> dict:
    """Fetch and store a forecast for every outdoor game inside the horizon.

    One request per stadium rather than per game, because two games a week
    apart at the same ground share one series.
    """
    coordinates = {
        row[0]: (row[1], row[2])
        for row in conn.execute("SELECT stadium_id, latitude, longitude FROM stadiums")
    }
    venues = {
        row[0]: row[1]
        for row in nflverse.schedules(season)
        .select(["game_id", "stadium_id"])
        .iter_rows()
    }

    # The window has two edges, not one. A game beyond the horizon has no
    # forecast yet; a game already played never will, because the provider's
    # forecast series starts today and its archive returns actuals, which is
    # what the weather table already holds.
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=open_meteo.FORECAST_DAYS)
    scheduled, beyond_horizon, already_played, unknown = [], 0, 0, []
    for row in conn.execute(GAMES_QUERY, (season,)):
        game = dict(row)
        if week is not None and game["week"] != week:
            continue
        kickoff = parse_time(game["kickoff_at"])
        if kickoff < now:
            already_played += 1
            continue
        if kickoff > horizon:
            beyond_horizon += 1
            continue
        stadium_id = venues.get(game["game_id"])
        if stadium_id not in coordinates:
            unknown.append(f"{game['game_id']} ({stadium_id})")
            continue
        game["stadium_id"] = stadium_id
        scheduled.append(game)

    result = {
        "games": len(scheduled),
        "beyond_horizon": beyond_horizon,
        "already_played": already_played,
        "unknown_stadium": unknown,
        "stadiums": len({g["stadium_id"] for g in scheduled}),
        "stored": 0,
        "unchanged": 0,
    }
    if dry_run:
        return result

    captured_at = utc_now()
    by_stadium: dict[str, list[dict]] = {}
    for game in scheduled:
        by_stadium.setdefault(game["stadium_id"], []).append(game)

    rows: list[dict] = []
    for stadium_id, games in sorted(by_stadium.items()):
        latitude, longitude = coordinates[stadium_id]
        hourly = open_meteo.hourly_forecast(latitude, longitude)
        for game in games:
            row = forecast_row(game, hourly, captured_at)
            if row is not None:
                rows.append(row)

    latest = latest_stored(conn, season)
    fresh = [row for row in rows if is_new_capture(row, latest)]
    write(conn, FORECAST_UPSERT, fresh)

    result["stored"] = len(fresh)
    result["unchanged"] = len(rows) - len(fresh)
    return result
