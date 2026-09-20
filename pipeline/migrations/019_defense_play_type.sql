-- Split what a defense allowed by play type, not just by the position it faced.
--
-- Migration 010 keyed this table on the ball carrier's position alone, which
-- answers the question for a receiver and fails for everyone else. An RB row
-- mixed his carries with his catches across 15,479 plays in 2024 with no way to
-- separate them, and the QB rows held 1,046 scramble and designed-run plays,
-- about 1.5 per team-week, because a pass is attributed to whoever caught it.
-- Feature 18 has to price rushing yards and passing yards, and neither question
-- could be asked of the old shape.
--
-- THIS MIGRATION EMPTIES THE TABLE. There is no honest play_type to give an
-- existing row: the value was never recorded and cannot be recovered from what
-- was stored. Every row here is derived from play-by-play, so one command puts
-- them all back:
--
--   uv run statify compute defense --season <year>
--
-- Until that runs, the table is empty and compute matchup will refuse rather
-- than build factors out of nothing.
--
-- SACKS NOW COUNT, as (QB, pass). Migration 010 dropped them as "no player
-- credited", which is true and unhelpful: a sack is the most valuable thing a
-- pass defense does, and excluding it understated exactly the defenses this
-- table exists to identify. The quarterback is the only honest attribution when
-- no receiver exists. A useful consequence: summing every play_type = 'pass'
-- row for a team-week now accounts for a whole dropback, sacks included.
--
-- A scramble stays a rush, following play-by-play's own rush flag. It is
-- arguably a failed dropback, but deciding that here would put this table out
-- of step with pass and rush everywhere else in the project.
DROP TABLE IF EXISTS team_defense_weekly;

CREATE TABLE team_defense_weekly (
  team_abbr            TEXT NOT NULL REFERENCES teams(team_abbr),
  season               INTEGER NOT NULL,
  week                 INTEGER NOT NULL,
  position             TEXT NOT NULL CHECK (position IN ('QB', 'RB', 'WR', 'TE')),
  play_type            TEXT NOT NULL CHECK (play_type IN ('pass', 'rush')),
  plays                INTEGER NOT NULL,
  epa_allowed          REAL NOT NULL,
  epa_allowed_per_play REAL NOT NULL,
  touchdowns_allowed   INTEGER NOT NULL,
  updated_at           TEXT NOT NULL,
  PRIMARY KEY (team_abbr, season, week, position, play_type)
);

CREATE INDEX idx_team_defense_season_week ON team_defense_weekly(season, week);
