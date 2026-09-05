from statify.ingest.depth import dedupe_depth_rows, depth_row

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def source(**overrides):
    base = {
        "season": 2024,
        "week": 1,
        "club_code": "PHI",
        "gsis_id": "00-0034844",
        "position": "RB",
        "depth_team": "1",
        "formation": "Offense",
    }
    return {**base, **overrides}


def row(player_id="00-0034844", week=1, depth_rank=1):
    return {
        "player_id": player_id,
        "season": 2024,
        "week": week,
        "team_abbr": "PHI",
        "position": "RB",
        "depth_rank": depth_rank,
        "updated_at": UPDATED_AT,
    }


def test_depth_rank_is_cast_to_int():
    """Stored as text, rank <= 2 would compare wrongly in feature 10."""
    built = depth_row(source(depth_team="3"), UPDATED_AT)
    assert built["depth_rank"] == 3
    assert isinstance(built["depth_rank"], int)


def test_team_is_normalized():
    assert depth_row(source(club_code="LAR"), UPDATED_AT)["team_abbr"] == "LA"


def test_identical_duplicates_collapse():
    assert len(dedupe_depth_rows([row(), row()])) == 1


def test_conflicting_ranks_keep_the_lower():
    kept = dedupe_depth_rows([row(depth_rank=3), row(depth_rank=1)])
    assert len(kept) == 1
    assert kept[0]["depth_rank"] == 1


def test_lower_rank_wins_regardless_of_order():
    kept = dedupe_depth_rows([row(depth_rank=1), row(depth_rank=3)])
    assert kept[0]["depth_rank"] == 1


def test_distinct_weeks_are_kept_separately():
    assert len(dedupe_depth_rows([row(week=1), row(week=2)])) == 2


def test_distinct_players_are_kept_separately():
    assert len(dedupe_depth_rows([row(player_id="a"), row(player_id="b")])) == 2


def test_empty_input():
    assert dedupe_depth_rows([]) == []
