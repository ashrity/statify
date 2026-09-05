-- Wind and temperature per outdoor game, the environment input feature 14 turns
-- into a weather adjustment.
--
-- Only outdoor games get a row. Indoor games are absent rather than zeroed,
-- because weather does not apply rather than being calm. Outdoor games with no
-- upstream reading are also absent, so a present row always means measured.
-- Which games are outdoor comes from games.is_dome, set in feature 1; this
-- table never re-derives it.
--
-- observed_at is the game's kickoff time, and the reading is the settled
-- game-time condition. Despite what the column name suggests, it is a fact
-- recorded after the fact, never a pre-kickoff forecast. Feature 14 must not
-- treat it as forward-looking information.
--
-- TODO: precip_chance has no source. nflverse publishes no precipitation, and
-- filling it needs an outside provider (Open-Meteo is free and needs no key).
-- The column exists so adding one later is a loader change, not a migration.
CREATE TABLE weather (
  game_id       TEXT PRIMARY KEY REFERENCES games(game_id),
  wind_mph      REAL,
  precip_chance REAL,
  temperature_f REAL,
  observed_at   TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
