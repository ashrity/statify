from statify.ingest.snaps import should_insert_orphan, snap_row

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def source(**overrides):
    base = {
        "game_id": "2024_01_GB_PHI",
        "season": 2024,
        "week": 1,
        "pfr_player_id": "BarkSa00",
        "team": "PHI",
        "offense_snaps": 51.0,
        "offense_pct": 0.76,
    }
    return {**base, **overrides}


def test_maps_the_snap_columns():
    row = snap_row(source(), "00-0034844", UPDATED_AT)
    assert row["player_id"] == "00-0034844"
    assert row["game_id"] == "2024_01_GB_PHI"
    assert row["snaps"] == 51
    assert row["snap_share"] == 0.76


def test_snaps_coerced_to_int():
    """The feed ships floats; the column is INTEGER."""
    row = snap_row(source(offense_snaps=62.0), "00-0034844", UPDATED_AT)
    assert row["snaps"] == 62
    assert isinstance(row["snaps"], int)


def test_missing_snap_count_becomes_zero():
    row = snap_row(source(offense_snaps=None), "00-0034844", UPDATED_AT)
    assert row["snaps"] == 0


def test_share_is_not_rounded():
    """Rounding here would silently change feature 10's snap share."""
    row = snap_row(source(offense_pct=0.6666666666666666), "00-0034844", UPDATED_AT)
    assert row["snap_share"] == 0.6666666666666666


def test_share_may_be_null():
    """A null percentage is unknown, not zero, so it passes through."""
    row = snap_row(source(offense_pct=None), "00-0034844", UPDATED_AT)
    assert row["snap_share"] is None


def test_team_is_normalized():
    """This feed says LA, but the helper must still be applied for the ones that don't."""
    assert snap_row(source(team="LAR"), "x", UPDATED_AT)["team_abbr"] == "LA"
    assert snap_row(source(team="KC"), "x", UPDATED_AT)["team_abbr"] == "KC"


def test_orphan_with_offensive_snaps_is_inserted():
    assert should_insert_orphan(source(offense_snaps=40.0)) is True


def test_orphan_with_no_offensive_snaps_is_skipped():
    """Special-teams-only players have no usage to model."""
    assert should_insert_orphan(source(offense_snaps=0.0)) is False


def test_orphan_with_null_snaps_is_skipped():
    assert should_insert_orphan(source(offense_snaps=None)) is False


def test_a_single_offensive_snap_is_enough():
    """The boundary is > 0, not some minimum playing time."""
    assert should_insert_orphan(source(offense_snaps=1.0)) is True
