import sqlite3

import pytest

from statify import migrate as migrations
from statify.ingest.reference import PLAYER_HEADSHOT_UPDATE, PLAYERS_UPSERT


@pytest.fixture
def conn():
    """A real schema, built by the real migrations, so the DDL is under test too."""
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    migrations.migrate(connection)
    yield connection
    connection.close()


def upsert(conn, player_id, team, season, name="Test Player", position="WR"):
    conn.execute(
        PLAYERS_UPSERT,
        {
            "player_id": player_id,
            "name": name,
            "position": position,
            "team_abbr": team,
            "roster_season": season,
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    )


def team_of(conn, player_id):
    row = conn.execute(
        "SELECT team_abbr, roster_season FROM players WHERE player_id = ?", (player_id,)
    ).fetchone()
    return None if row is None else (row["team_abbr"], row["roster_season"])


def test_older_backfill_does_not_overwrite_current_team(conn):
    """The bug this fixes: ingesting 2024 after 2025 used to rewrite the team."""
    upsert(conn, "00-0034844", "PHI", 2025)
    upsert(conn, "00-0034844", "NYG", 2024)
    assert team_of(conn, "00-0034844") == ("PHI", 2025)


def test_newer_pull_wins(conn):
    upsert(conn, "00-0034844", "PHI", 2025)
    upsert(conn, "00-0034844", "DAL", 2026)
    assert team_of(conn, "00-0034844") == ("DAL", 2026)


def test_same_season_repull_applies(conn):
    """A midseason trade arrives as a re-pull of the season already stored."""
    upsert(conn, "00-0034844", "PHI", 2025)
    upsert(conn, "00-0034844", "LA", 2025)
    assert team_of(conn, "00-0034844") == ("LA", 2025)


def test_backfill_still_inserts_unseen_players(conn):
    """Retired players only exist in old rosters, and weekly_actuals needs them."""
    upsert(conn, "00-0030564", "TEN", 2024)
    assert team_of(conn, "00-0030564") == ("TEN", 2024)


def test_null_roster_season_row_is_claimed_by_any_pull(conn):
    """Rows written before migration 004 carry NULL and must not be frozen."""
    conn.execute(
        "INSERT INTO players (player_id, name, position, team_abbr, updated_at) "
        "VALUES ('00-0035216', 'Legacy Row', 'WR', 'PIT', '2026-01-01T00:00:00+00:00')"
    )
    assert team_of(conn, "00-0035216") == ("PIT", None)

    upsert(conn, "00-0035216", "CLE", 2024)
    assert team_of(conn, "00-0035216") == ("CLE", 2024)


def test_ingest_order_does_not_matter(conn):
    """Whichever order the two seasons are pulled in, the table ends up the same."""
    upsert(conn, "00-0034837", "TEN", 2025)
    upsert(conn, "00-0034837", "JAX", 2024)
    forwards = team_of(conn, "00-0034837")

    conn.execute("DELETE FROM players")
    upsert(conn, "00-0034837", "JAX", 2024)
    upsert(conn, "00-0034837", "TEN", 2025)
    backwards = team_of(conn, "00-0034837")

    assert forwards == backwards == ("TEN", 2025)


def test_guard_skips_are_not_counted_as_writes(conn):
    """total_changes must not count rows the WHERE clause refused."""
    upsert(conn, "00-0034844", "PHI", 2025)

    before = conn.total_changes
    upsert(conn, "00-0034844", "NYG", 2024)
    assert conn.total_changes - before == 0

    before = conn.total_changes
    upsert(conn, "00-0034844", "DAL", 2026)
    assert conn.total_changes - before == 1


# --- headshots: identity, not roster state -----------------------------------


def set_headshot(conn, player_id, url):
    conn.execute(
        PLAYER_HEADSHOT_UPDATE,
        {"player_id": player_id, "headshot_url": url, "updated_at": "2026-01-01T00:00:00+00:00"},
    )


def headshot_of(conn, player_id):
    row = conn.execute(
        "SELECT headshot_url FROM players WHERE player_id = ?", (player_id,)
    ).fetchone()
    return None if row is None else row["headshot_url"]


def test_an_older_pull_still_sets_a_headshot(conn):
    """The reason this sits outside the roster_season guard, like pfr_id: a photo
    is identity, so a 2024 pull must still fill a player stamped 2026."""
    upsert(conn, "00-0034844", "PHI", 2026)
    set_headshot(conn, "00-0034844", "https://example.test/a.png")
    assert headshot_of(conn, "00-0034844") == "https://example.test/a.png"


def test_a_changed_headshot_is_rewritten(conn):
    """Guard-free means a new photo replaces an old one."""
    upsert(conn, "00-0034844", "PHI", 2026)
    set_headshot(conn, "00-0034844", "https://example.test/old.png")
    set_headshot(conn, "00-0034844", "https://example.test/new.png")
    assert headshot_of(conn, "00-0034844") == "https://example.test/new.png"


def test_an_unchanged_headshot_is_not_a_write(conn):
    """A re-run must not report every player as changed."""
    upsert(conn, "00-0034844", "PHI", 2026)
    set_headshot(conn, "00-0034844", "https://example.test/a.png")

    before = conn.total_changes
    set_headshot(conn, "00-0034844", "https://example.test/a.png")
    assert conn.total_changes - before == 0


def test_a_headshot_for_an_unknown_player_writes_nothing(conn):
    """The UPDATE touches existing rows only; it never invents a player."""
    set_headshot(conn, "00-0000000", "https://example.test/a.png")
    assert headshot_of(conn, "00-0000000") is None
