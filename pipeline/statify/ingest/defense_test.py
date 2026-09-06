from statify.ingest.defense import aggregate_defense, exclusion_reason, position_faced

POSITIONS = {"wr1": "WR", "rb1": "RB", "te1": "TE", "qb1": "QB"}


def play(**overrides):
    base = {
        "season": 2024,
        "week": 1,
        "season_type": "REG",
        "defteam": "BUF",
        "epa": 0.5,
        "pass": 0,
        "rush": 0,
        "sack": 0,
        "receiver_player_id": None,
        "rusher_player_id": None,
        "touchdown": 0,
        "two_point_attempt": 0,
    }
    return {**base, **overrides}


def test_rush_resolves_to_the_rushers_position():
    assert position_faced(play(rush=1, rusher_player_id="rb1"), POSITIONS) == "RB"


def test_pass_resolves_to_the_receivers_position():
    assert position_faced(play(**{"pass": 1, "receiver_player_id": "te1"}), POSITIONS) == "TE"


def test_a_sack_has_no_position():
    """A sack carries pass = 1 with no receiver, so it must not slip through."""
    sack = play(sack=1, **{"pass": 1})
    assert position_faced(sack, POSITIONS) is None
    assert exclusion_reason(sack, POSITIONS) == "sack"


def test_a_throwaway_has_no_position():
    thrown_away = play(**{"pass": 1})
    assert position_faced(thrown_away, POSITIONS) is None
    assert exclusion_reason(thrown_away, POSITIONS) == "no player credited"


def test_an_unknown_player_has_no_position():
    unknown = play(rush=1, rusher_player_id="fullback9")
    assert position_faced(unknown, POSITIONS) is None
    assert exclusion_reason(unknown, POSITIONS) == "player not in players table"


def test_two_point_attempts_are_excluded():
    two_pointer = play(two_point_attempt=1, rush=1, rusher_player_id="rb1")
    assert position_faced(two_pointer, POSITIONS) is None
    assert exclusion_reason(two_pointer, POSITIONS) == "two-point attempt"


def test_a_kick_is_not_a_scrimmage_play():
    assert position_faced(play(), POSITIONS) is None


def test_rate_is_a_ratio_of_sums_not_a_mean_of_means():
    """Averaging per-play EPA gives the same answer only when counts are equal.

    Two plays at +1.0 and one at -2.0 sum to 0.0 over three plays. A mean of the
    two groups' means would give a different, plausible-looking number.
    """
    plays = [
        play(rush=1, rusher_player_id="rb1", epa=1.0),
        play(rush=1, rusher_player_id="rb1", epa=1.0),
        play(rush=1, rusher_player_id="rb1", epa=-2.0),
    ]
    rows, _ = aggregate_defense(plays, POSITIONS)
    assert len(rows) == 1
    assert rows[0]["plays"] == 3
    assert rows[0]["epa_allowed"] == 0.0
    assert rows[0]["epa_allowed_per_play"] == 0.0


def test_positions_are_bucketed_separately():
    plays = [
        play(**{"pass": 1, "receiver_player_id": "wr1", "epa": 0.4}),
        play(**{"pass": 1, "receiver_player_id": "te1", "epa": 0.2}),
        play(rush=1, rusher_player_id="rb1", epa=-0.1),
    ]
    rows, _ = aggregate_defense(plays, POSITIONS)
    assert {r["position"]: r["epa_allowed"] for r in rows} == {"WR": 0.4, "TE": 0.2, "RB": -0.1}


def test_weeks_and_teams_are_bucketed_separately():
    plays = [
        play(rush=1, rusher_player_id="rb1"),
        play(rush=1, rusher_player_id="rb1", week=2),
        play(rush=1, rusher_player_id="rb1", defteam="KC"),
    ]
    rows, _ = aggregate_defense(plays, POSITIONS)
    assert len(rows) == 3


def test_touchdowns_land_in_the_right_bucket():
    plays = [
        play(**{"pass": 1, "receiver_player_id": "wr1", "touchdown": 1}),
        play(**{"pass": 1, "receiver_player_id": "wr1"}),
        play(rush=1, rusher_player_id="rb1", touchdown=1),
    ]
    rows, _ = aggregate_defense(plays, POSITIONS)
    counts = {r["position"]: r["touchdowns_allowed"] for r in rows}
    assert counts == {"WR": 1, "RB": 1}


def test_excluded_plays_are_counted_by_reason():
    plays = [
        play(sack=1, **{"pass": 1}),
        play(**{"pass": 1}),
        play(rush=1, rusher_player_id="nobody"),
    ]
    rows, excluded = aggregate_defense(plays, POSITIONS)
    assert rows == []
    assert excluded == {"sack": 1, "no player credited": 1, "player not in players table": 1}


def test_a_play_with_no_epa_is_excluded_not_counted_as_zero():
    """Treating a null EPA as 0.0 would drag the rate toward the mean."""
    plays = [play(rush=1, rusher_player_id="rb1", epa=None)]
    rows, excluded = aggregate_defense(plays, POSITIONS)
    assert rows == []
    assert excluded["no epa on the play"] == 1


def test_preseason_is_ignored():
    plays = [play(rush=1, rusher_player_id="rb1", season_type="PRE")]
    assert aggregate_defense(plays, POSITIONS)[0] == []


def test_a_play_with_no_defence_is_ignored():
    plays = [play(rush=1, rusher_player_id="rb1", defteam=None)]
    assert aggregate_defense(plays, POSITIONS)[0] == []


def test_empty_input_produces_no_rows():
    rows, excluded = aggregate_defense([], POSITIONS)
    assert rows == [] and excluded == {}
