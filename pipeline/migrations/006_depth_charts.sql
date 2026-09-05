-- Offensive depth rank per player per week: the role signal feature 10 pairs
-- with snap share.
--
-- The primary key matches project-overview.md, but the feed does not satisfy it
-- on its own: a player appears once per formation and depth position, so an RB
-- listed RB3 on offense and PR1 and KOR1 on special teams is three rows. The
-- loader filters to the offensive formation and keeps the lowest rank, which is
-- what makes this key hold.
CREATE TABLE depth_charts (
  player_id   TEXT NOT NULL REFERENCES players(player_id),
  season      INTEGER NOT NULL,
  week        INTEGER NOT NULL,
  team_abbr   TEXT NOT NULL REFERENCES teams(team_abbr),
  position    TEXT NOT NULL,
  depth_rank  INTEGER NOT NULL,
  updated_at  TEXT NOT NULL,
  PRIMARY KEY (player_id, season, week)
);

CREATE INDEX idx_depth_charts_season_week ON depth_charts(season, week);
