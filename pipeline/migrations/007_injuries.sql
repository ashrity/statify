-- Availability by player and week: the largest week-to-week driver of
-- opportunity change.
--
-- Both status columns are nullable. A player can sit on the practice report
-- midweek with no game designation yet, and NULL there means "not designated",
-- which is not the same as available.
--
-- The CHECK constraints are deliberate. The feed ships sentences like "Limited
-- Participation in Practice" plus occasional junk, and the loader normalizes
-- them; the constraint is what turns an upstream vocabulary change into a loud
-- failure rather than a new value nothing downstream handles. NULL passes a
-- CHECK in SQLite, which is what keeps "not designated" legal.
--
-- report_at sits in the primary key so a later pull with a newer timestamp adds
-- a row rather than overwriting one. Consumers must take the latest report_at
-- per player week; the feed is close to one snapshot per week, but not
-- guaranteed to be.
CREATE TABLE injuries (
  player_id       TEXT NOT NULL REFERENCES players(player_id),
  season          INTEGER NOT NULL,
  week            INTEGER NOT NULL,
  team_abbr       TEXT REFERENCES teams(team_abbr),
  designation     TEXT CHECK (designation IN ('Out', 'Doubtful', 'Questionable')),
  practice_status TEXT CHECK (practice_status IN ('DNP', 'Limited', 'Full')),
  report_at       TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  PRIMARY KEY (player_id, season, week, report_at)
);

CREATE INDEX idx_injuries_season_week ON injuries(season, week);
