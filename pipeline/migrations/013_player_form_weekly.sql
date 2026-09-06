-- What a player's usage looked like GOING INTO each week: the last 3 games, the
-- last 5, and the season so far.
--
-- Every value in a week N row comes from games strictly before week N. That
-- boundary is the point of the table. If a week's own game leaked into its own
-- average, feature 19 would project a game using that game's result and feature
-- 27's walk-forward backtest would measure nothing, while every number here
-- still looked entirely reasonable: shares in range, trends plausible, no error
-- anywhere. Nothing downstream can detect it, so it is tested directly.
--
-- Windows count games played, not calendar weeks. A player who missed four weeks
-- injured has a last-3 window of his last three appearances; counting weeks
-- would fold the missed ones in as zeros.
--
-- Rates are volume-weighted, sum of numerators over sum of denominators, which
-- is why feature 10a stored both. A mean of weekly shares would weight a
-- 14-target game the same as a 29-target one.
--
-- snap_share is the one exception: feature 4a stored the percentage without the
-- team snap count, so a mean is all that is available. That is a known
-- limitation of the stored data, not an inconsistency to repair here.
--
-- games_* columns are NOT NULL and count real prior games. Value columns are
-- nullable and mean "not enough history", which is why a player's first game of
-- the season is entirely NULL rather than zero.
CREATE TABLE player_form_weekly (
  player_id            TEXT NOT NULL REFERENCES players(player_id),
  season               INTEGER NOT NULL,
  week                 INTEGER NOT NULL,

  -- last 3 games
  games_l3                  INTEGER NOT NULL,
  targets_pg_l3             REAL,
  carries_pg_l3             REAL,
  target_share_l3           REAL,
  air_yards_share_l3        REAL,
  wopr_l3                   REAL,
  adot_l3                   REAL,
  rz_touch_share_l3         REAL,
  snap_share_l3             REAL,

  -- last 5 games
  games_l5                  INTEGER NOT NULL,
  targets_pg_l5             REAL,
  carries_pg_l5             REAL,
  target_share_l5           REAL,
  air_yards_share_l5        REAL,
  wopr_l5                   REAL,
  adot_l5                   REAL,
  rz_touch_share_l5         REAL,
  snap_share_l5             REAL,

  -- the season so far
  games_std                 INTEGER NOT NULL,
  targets_pg_std            REAL,
  carries_pg_std            REAL,
  target_share_std          REAL,
  air_yards_share_std       REAL,
  wopr_std                  REAL,
  adot_std                  REAL,
  rz_touch_share_std        REAL,
  snap_share_std            REAL,

  updated_at           TEXT NOT NULL,
  PRIMARY KEY (player_id, season, week)
);

CREATE INDEX idx_player_form_season_week ON player_form_weekly(season, week);
