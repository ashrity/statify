-- The market's view of a game: who is favoured, how many points it expects,
-- and how many each side is expected to score.
--
-- Feature 14 cannot be built without implied_team_total, and feature 21
-- compares our projections against the same market this table records.
--
-- Two rows per game per book, because an implied total belongs to a team while
-- the spread and the game total describe the matchup. Storing one row per game
-- would make feature 14 do the splitting on every read.
--
-- implied_team_total = game_total / 2 - spread / 2, with spread already signed
-- from that team's point of view. Measured against the live feed: San
-- Francisco at -7.5 on a 52.5 total gives 30.0 and Washington at +7.5 gives
-- 22.5. The pair always sums back to game_total, which is the property worth
-- checking, because a sign error produces two plausible numbers that sum to
-- the wrong thing.
--
-- It is stored rather than derived on read. The arithmetic is trivial, but it
-- depends on two numbers from the same book at the same capture, and a
-- consumer rejoining them later is a chance to pair the wrong ones.
--
-- captured_at is the run's clock, never the book's last_update. Feature 7a used
-- last_update and got 433 duplicate rows, because that field records when a
-- book last published rather than when it moved a price. The same field is in
-- this payload and is the same trap.
--
-- Several captures per game are intended history, which is why captured_at is
-- part of the key. Two rows for one book at one instant are a duplicate rather
-- than history, so the primary key refuses them.
--
-- season and week are additions to the column list in project-overview.md.
-- Every other weekly table carries them, and feature 14 wants market data by
-- week without joining through games to discover which week a row belongs to.
--
-- spread, game_total and implied_team_total are all nullable: books post the
-- two markets separately, so a game can legitimately have one and not yet the
-- other. A NULL says which is missing; a zero would be a line.
CREATE TABLE team_market_data (
  game_id            TEXT NOT NULL REFERENCES games(game_id),
  team_abbr          TEXT NOT NULL REFERENCES teams(team_abbr),
  season             INTEGER NOT NULL,
  week               INTEGER NOT NULL,
  book               TEXT NOT NULL,
  spread             REAL,
  game_total         REAL,
  implied_team_total REAL,
  captured_at        TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  PRIMARY KEY (game_id, team_abbr, book, captured_at)
);

CREATE INDEX idx_team_market_season_week ON team_market_data(season, week);
