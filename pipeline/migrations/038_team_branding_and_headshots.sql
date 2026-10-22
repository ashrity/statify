-- Logos, team colors and player headshots for the dashboard. Feature 22's
-- board and feature 29's accuracy page read these; nothing in the projection
-- pipeline does.
--
-- PULLED FROM THE FEED, NEVER HAND-TYPED, the same rule migration 026's
-- stadium map follows for place names: nflverse's load_teams() already
-- publishes team_logo_espn, team_color and team_color2, and load_rosters()
-- publishes headshot_url. Typing 32 hex colors and 32 URLs by hand would
-- invent a second source of truth that silently drifts from the feed.
--
-- headshot_url SITS OUTSIDE THE roster_season GUARD, like pfr_id. PLAYERS_UPSERT
-- refuses to let an older backfill rewrite a current team, which is right for
-- roster state and wrong for identity: a player's photo does not belong to a
-- season, so running it through that guard would leave it NULL on every row
-- already stamped with a newer season. reference.py's own comment above
-- PLAYER_PFR_ID_UPDATE sets this precedent.
--
-- Every column is nullable. A team or player the feed has no image for is a
-- real state the UI handles (initials in a colored badge instead), not a
-- reason to block the row.
ALTER TABLE teams ADD COLUMN logo_url TEXT;
ALTER TABLE teams ADD COLUMN color_primary TEXT;
ALTER TABLE teams ADD COLUMN color_secondary TEXT;

ALTER TABLE players ADD COLUMN headshot_url TEXT;
