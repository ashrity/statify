-- Weather as it was EXPECTED, which is a different fact from the weather in
-- the `weather` table.
--
-- Migration 008 records that `weather.observed_at` is the game's kickoff time
-- and the reading is the settled game-time condition: a fact recorded after
-- the fact, never a pre-kickoff forecast, and it warns feature 14 against
-- treating it as forward-looking. Projecting a game with its own game-time
-- wind is the leakage features 11a, 13a and 14a all carry direct tests
-- against.
--
-- So this is a second table rather than more columns on the first. `weather`
-- stays what happened; `game_forecast` is what was expected and when. Feature
-- 27's walk-forward backtest needs to tell the two apart, and it can only do
-- that if nothing overwrote one with the other.
--
-- Several forecasts per game are intended history. One taken three days out
-- differs from one taken an hour before kickoff, and feature 27 wants whichever
-- was current at projection time, so captured_at is part of the key. Novelty is
-- decided by content in the loader: a forecast that has not moved is the same
-- fact recorded twice, which is the mistake features 7a and 8 each made once.
--
-- forecast_for is the hourly timestamp actually used, stored so the match
-- against kickoff can be audited rather than trusted.
--
-- Stadium coordinates are geocoded from place names rather than written down.
-- Nothing in nflverse publishes a latitude or longitude, and Open-Meteo's
-- geocoder resolves places but not venues: Lumen Field returns nothing while
-- Seattle returns a point about a kilometre away, where the wind and
-- temperature are the same numbers. A wrong place name fails visibly; a
-- hand-typed coordinate would quietly return the weather somewhere else. The
-- resolved values live here so they can be read back and checked.
--
-- Forty stadiums appear across 2024 to 2026 and they are not all American.
-- GER00 and MUN01 are two ids for the same Munich venue, so a duplicate
-- coordinate between exactly those two is expected.
CREATE TABLE stadiums (
  stadium_id   TEXT PRIMARY KEY,
  place        TEXT NOT NULL,
  country_code TEXT,
  latitude     REAL NOT NULL,
  longitude    REAL NOT NULL,
  resolved_at  TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE game_forecast (
  game_id       TEXT NOT NULL REFERENCES games(game_id),
  season        INTEGER NOT NULL,
  week          INTEGER NOT NULL,
  wind_mph      REAL,
  temperature_f REAL,
  precip_chance REAL,
  forecast_for  TEXT NOT NULL,
  captured_at   TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  PRIMARY KEY (game_id, captured_at)
);

CREATE INDEX idx_game_forecast_season_week ON game_forecast(season, week);

-- Filled by compute environment from each game's latest forecast, so feature
-- 18 reads one table for environment instead of joining a second for weather.
-- NULL for a dome, where weather does not apply, and for any game with no
-- forecast yet.
ALTER TABLE game_environment_weekly ADD COLUMN wind_mph REAL;
ALTER TABLE game_environment_weekly ADD COLUMN temperature_f REAL;
ALTER TABLE game_environment_weekly ADD COLUMN precip_chance REAL;
