-- What a defense allowed, per week, broken down by the position it faced. The
-- raw material for feature 13's matchup adjustment.
--
-- Nothing upstream publishes this. It is computed from play-by-play, so unlike
-- every table before it there is no external number to check a row against. The
-- guard is the shape of the result: EPA allowed on passes to receivers must come
-- out clearly positive and on runs to backs slightly negative, because that is
-- the most firmly established result in football analytics. An inversion means
-- the attribution broke, whatever the row count says.
--
-- plays and epa_allowed sit alongside the per-play rate on purpose. A rate
-- cannot be re-aggregated: feature 11 averages several weeks together, and
-- averaging four weekly rates would weight a 12-play week the same as a 40-play
-- one. Keeping the numerator and denominator makes the correct calculation
-- possible later.
--
-- touchdowns_allowed rather than the overview's points_allowed. Points are not
-- positional; field goals, safeties and defensive scores belong to no position,
-- so a points column here would silently mean "six times the touchdowns" and
-- carry a name that lies. The count lets feature 13 decide.
CREATE TABLE team_defense_weekly (
  team_abbr            TEXT NOT NULL REFERENCES teams(team_abbr),
  season               INTEGER NOT NULL,
  week                 INTEGER NOT NULL,
  position             TEXT NOT NULL CHECK (position IN ('QB', 'RB', 'WR', 'TE')),
  plays                INTEGER NOT NULL,
  epa_allowed          REAL NOT NULL,
  epa_allowed_per_play REAL NOT NULL,
  touchdowns_allowed   INTEGER NOT NULL,
  updated_at           TEXT NOT NULL,
  PRIMARY KEY (team_abbr, season, week, position)
);

CREATE INDEX idx_team_defense_season_week ON team_defense_weekly(season, week);
