-- One row per skill-position player per game: the box-score base every later
-- feature reads. Adding a column here after seasons are ingested costs a
-- migration plus a full re-pull, so the shape is deliberate.

-- Touchdowns stay split by phase rather than summed. A QB's passing TDs and
-- rushing TDs are priced as separate prop markets, and a sum cannot be un-mixed.
--
-- Counting stats are NOT NULL DEFAULT 0 because a WR with no carries genuinely
-- had zero. EPA is nullable because a player with no targets has undefined
-- receiving EPA, and averaging a fake 0.0 would drag efficiency numbers down.
--
-- snaps, snap_share (feature 4), routes_run (source undecided), and
-- red_zone_touches (the play-by-play pass) are written by later passes over rows
-- this loader creates, so each loader updates only the columns it owns.
CREATE TABLE weekly_actuals (
  player_id        TEXT NOT NULL REFERENCES players(player_id),
  game_id          TEXT NOT NULL REFERENCES games(game_id),
  season           INTEGER NOT NULL,
  week             INTEGER NOT NULL,
  team_abbr        TEXT NOT NULL REFERENCES teams(team_abbr),
  snaps            INTEGER,
  snap_share       REAL,
  routes_run       INTEGER,
  targets          INTEGER NOT NULL DEFAULT 0,
  receptions       INTEGER NOT NULL DEFAULT 0,
  receiving_yards  INTEGER NOT NULL DEFAULT 0,
  air_yards        INTEGER NOT NULL DEFAULT 0,
  yac              INTEGER NOT NULL DEFAULT 0,
  receiving_tds    INTEGER NOT NULL DEFAULT 0,
  receiving_epa    REAL,
  carries          INTEGER NOT NULL DEFAULT 0,
  rushing_yards    INTEGER NOT NULL DEFAULT 0,
  rushing_tds      INTEGER NOT NULL DEFAULT 0,
  rushing_epa      REAL,
  attempts         INTEGER NOT NULL DEFAULT 0,
  completions      INTEGER NOT NULL DEFAULT 0,
  passing_yards    INTEGER NOT NULL DEFAULT 0,
  passing_tds      INTEGER NOT NULL DEFAULT 0,
  passing_epa      REAL,
  red_zone_touches INTEGER,
  updated_at       TEXT NOT NULL,
  PRIMARY KEY (player_id, game_id)
);

CREATE INDEX idx_weekly_actuals_season_week ON weekly_actuals(season, week);
