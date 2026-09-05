-- Pro Football Reference id, the bridge to feeds that carry no GSIS id.
--
-- Snap counts key on pfr_player_id ('BrowSp00') and ship no GSIS column at all,
-- so nothing can join them to players without this. PFR advanced stats are keyed
-- the same way, which is where routes_run lives for feature 10.
--
-- Identity rather than roster state, so it is set outside the roster_season
-- guard on PLAYERS_UPSERT: a player's PFR id does not change when they change
-- teams, and gating it would leave rows NULL for no reason.
ALTER TABLE players ADD COLUMN pfr_id TEXT;

CREATE INDEX idx_players_pfr_id ON players(pfr_id);
