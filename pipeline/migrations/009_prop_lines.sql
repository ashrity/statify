-- The market side of the edge. Feature 21 subtracts these lines from the
-- projection, and feature 20's projections point back at a specific row.
--
-- game_id is stored even though project-overview.md's column list has only
-- season and week: every other weekly table keys to a game, and event
-- resolution hands it to us for free. Without it, feature 21 would have to
-- re-derive which game a line belongs to.
--
-- The UNIQUE constraint is what makes a re-run idempotent. Several captures per
-- player per week are intended history, so captured_at is part of the key, but
-- two rows for the same book at the same instant are a duplicate rather than
-- history.
--
-- stat_type carries a CHECK so an unmapped market fails loudly instead of
-- writing a value nothing downstream matches. touchdowns is listed here but is
-- not written until feature 7b.
CREATE TABLE prop_lines (
  id          INTEGER PRIMARY KEY,
  player_id   TEXT NOT NULL REFERENCES players(player_id),
  game_id     TEXT NOT NULL REFERENCES games(game_id),
  season      INTEGER NOT NULL,
  week        INTEGER NOT NULL,
  stat_type   TEXT NOT NULL CHECK (stat_type IN (
                'passing_yards', 'rushing_yards', 'receiving_yards',
                'receptions', 'touchdowns')),
  book        TEXT NOT NULL,
  line        REAL,
  over_odds   INTEGER,
  under_odds  INTEGER,
  captured_at TEXT NOT NULL,
  is_closing  INTEGER NOT NULL DEFAULT 0 CHECK (is_closing IN (0, 1)),
  updated_at  TEXT NOT NULL,
  UNIQUE (player_id, game_id, stat_type, book, captured_at)
);

CREATE INDEX idx_prop_lines_season_week ON prop_lines(season, week);
CREATE INDEX idx_prop_lines_player ON prop_lines(player_id, stat_type);
