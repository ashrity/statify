-- Tracking-derived efficiency inputs. Sparse by nature: Next Gen Stats covers
-- roughly 39% of skill-player weeks, and it is position-siloed. The receiving
-- feed carries only WR and TE, rushing only RB, passing only QB, so an RB has no
-- separation and a QB has no RYOE. Every metric column is nullable because a
-- missing value means "not measured", never zero.

-- No game_id: NGS ships none, and resolving one through weekly_actuals would
-- fail for exactly the players missing from that table. Keyed by week instead,
-- with postseason weeks remapped on ingest to match games.week, because NGS
-- numbers the Super Bowl one higher than the schedule does.
CREATE TABLE next_gen_stats (
  player_id      TEXT NOT NULL REFERENCES players(player_id),
  season         INTEGER NOT NULL,
  week           INTEGER NOT NULL,
  team_abbr      TEXT REFERENCES teams(team_abbr),
  avg_separation REAL,
  yacoe          REAL,
  avg_cushion    REAL,
  cpoe           REAL,
  time_to_throw  REAL,
  ryoe           REAL,
  ryoe_per_att   REAL,
  updated_at     TEXT NOT NULL,
  PRIMARY KEY (player_id, season, week)
);

CREATE INDEX idx_next_gen_stats_season_week ON next_gen_stats(season, week);
