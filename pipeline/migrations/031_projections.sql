-- The model's output and its own track record, exactly as project-overview.md
-- locks it. Feature 19's raw projection gets a storage identity here, and
-- that is this table's whole job: "persists each projection with its model
-- version, so past runs stay comparable after the model changes" is that
-- document's own reason for the table.
--
-- A SURROGATE KEY, NOT A COMPOSITE ONE, ON PURPOSE. Every table since feature
-- 15a has been keyed by (player, season, week, ...) and upserted in place: the
-- current best estimate, overwritten as it improves. This table is the
-- opposite. It accumulates a history, so (player_id, season, week, stat_type,
-- model_version) can legitimately repeat across rows with different
-- generated_at, the same reason prop_lines allows an opening and a closing
-- capture to both exist. id is what makes a single row addressable.
--
-- CONTENT-BASED NOVELTY, NOT A SCHEDULE. A re-run of compute
-- generate-projections inserts a new row only when projected_value actually
-- changed since the latest stored row for that key. Without this, feature
-- 25's weekly refresh would duplicate the whole table on every run that found
-- nothing new, the exact mistake feature 7a made once already with 433 rows.
--
-- market_line, prop_line_id, edge AND confidence ARE ALWAYS NULL HERE. This
-- feature stops at projected_value and model_version. Matching a market line
-- and computing the edge is feature 21's job; confidence is feature 26's.
-- Filling any of them in this loader would cross a boundary the build plan
-- itself draws between features 20, 21 and 26.
CREATE TABLE projections (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  player_id        TEXT    NOT NULL REFERENCES players(player_id),
  season           INTEGER NOT NULL,
  week             INTEGER NOT NULL,
  stat_type        TEXT    NOT NULL CHECK (
    stat_type IN ('receiving_yards', 'receptions', 'rushing_yards', 'passing_yards', 'touchdowns')
  ),
  model_version    TEXT    NOT NULL,
  projected_value  REAL    NOT NULL,
  market_line      REAL,
  prop_line_id     INTEGER REFERENCES prop_lines(id),
  edge             REAL,
  confidence       REAL,
  generated_at     TEXT    NOT NULL
);

CREATE INDEX idx_projections_lookup
  ON projections(player_id, season, week, stat_type, model_version);

CREATE INDEX idx_projections_season_week ON projections(season, week);
