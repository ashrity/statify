from statify.ingest.defense import aggregate_defense, bucket, exclusion_reason

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


# The four buckets, one test each. A single combined assertion would pass with
# two of the four wrong, and telling a back's carries from his catches is the
# whole reason this dimension exists.


def test_a_carry_by_a_back():
    assert bucket(play(rush=1, rusher_player_id="rb1"), POSITIONS) == ("RB", "rush")


def test_a_catch_by_the_same_back():
    assert bucket(play(**{"pass": 1, "receiver_player_id": "rb1"}), POSITIONS) == ("RB", "pass")


def test_a_scramble_is_a_rush_by_the_quarterback():
    """Arguably a failed dropback, but play-by-play calls it a rush and so do we."""
    scramble = play(rush=1, rusher_player_id="qb1")
    assert bucket(scramble, POSITIONS) == ("QB", "rush")


def test_a_sack_is_a_pass_against_the_quarterback():
    """No receiver exists, and dropping it understated every good pass rush."""
    sack = play(sack=1, **{"pass": 1})
    assert bucket(sack, POSITIONS) == ("QB", "pass")


def test_a_catch_by_a_tight_end():
    assert bucket(play(**{"pass": 1, "receiver_player_id": "te1"}), POSITIONS) == ("TE", "pass")


def test_a_sack_is_no_longer_an_exclusion():
    """It used to be reported as one; counting it and excluding it would double-count."""
    assert "sack" not in exclusion_reason(play(sack=1, **{"pass": 1}), POSITIONS)


def test_a_throwaway_has_no_bucket():
    thrown_away = play(**{"pass": 1})
    assert bucket(thrown_away, POSITIONS) is None
    assert exclusion_reason(thrown_away, POSITIONS) == "no player credited"


def test_an_unknown_player_has_no_bucket():
    unknown = play(rush=1, rusher_player_id="fullback9")
    assert bucket(unknown, POSITIONS) is None
    assert exclusion_reason(unknown, POSITIONS) == "player not in players table"


def test_two_point_attempts_are_excluded():
    two_pointer = play(two_point_attempt=1, rush=1, rusher_player_id="rb1")
    assert bucket(two_pointer, POSITIONS) is None
    assert exclusion_reason(two_pointer, POSITIONS) == "two-point attempt"


def test_a_two_point_sack_is_still_excluded():
    """The two-point check runs first, or the sack rule would swallow it."""
    assert bucket(play(two_point_attempt=1, sack=1, **{"pass": 1}), POSITIONS) is None


def test_a_kick_is_not_a_scrimmage_play():
    assert bucket(play(), POSITIONS) is None


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
        play(**{"pass": 1}),
        play(rush=1, rusher_player_id="nobody"),
    ]
    rows, excluded = aggregate_defense(plays, POSITIONS)
    assert rows == []
    assert excluded == {"no player credited": 1, "player not in players table": 1}


def test_a_sack_is_kept_rather_than_excluded():
    """It is now a row, so counting it as excluded too would report it twice."""
    rows, excluded = aggregate_defense([play(sack=1, **{"pass": 1})], POSITIONS)
    assert [(r["position"], r["play_type"], r["plays"]) for r in rows] == [("QB", "pass", 1)]
    assert excluded == {}


def test_a_backs_carries_and_catches_are_separate_rows():
    """The reason the play type exists: one row for these two used to be all there was."""
    plays = [
        play(rush=1, rusher_player_id="rb1", epa=-0.2),
        play(**{"pass": 1, "receiver_player_id": "rb1", "epa": 0.8}),
    ]
    rows, _ = aggregate_defense(plays, POSITIONS)
    by_type = {r["play_type"]: r["epa_allowed"] for r in rows}
    assert by_type == {"rush": -0.2, "pass": 0.8}


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
