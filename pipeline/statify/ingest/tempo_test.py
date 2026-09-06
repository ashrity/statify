from statify.ingest.tempo import aggregate_tempo, is_neutral, play_intervals


def play(play_id=1, clock=3600, drive=1, **overrides):
    base = {
        "game_id": "2024_01_NE_SEA",
        "season": 2024,
        "week": 1,
        "season_type": "REG",
        "posteam": "SEA",
        "play_id": play_id,
        "fixed_drive": drive,
        "game_seconds_remaining": clock,
        "pass": 0,
        "rush": 1,
        "pass_oe": 0.0,
        "qtr": 1,
        "score_differential": 0,
        "incomplete_pass": 0,
    }
    return {**base, **overrides}


def test_consecutive_plays_in_a_drive_make_an_interval():
    intervals = play_intervals([play(1, 3600), play(2, 3570)])
    assert len(intervals) == 1
    assert intervals[0]["seconds"] == 30


def test_a_drive_change_breaks_the_chain():
    """The gap between drives includes the other team's possession."""
    assert play_intervals([play(1, 3600, drive=1), play(2, 3570, drive=2)]) == []


def test_a_gap_over_the_cap_is_dropped():
    """A timeout, injury or replay review is a stoppage, not tempo."""
    assert play_intervals([play(1, 3600), play(2, 3500)]) == []


def test_a_zero_gap_is_dropped():
    assert play_intervals([play(1, 3600), play(2, 3600)]) == []


def test_a_missing_clock_is_dropped():
    assert play_intervals([play(1, 3600), play(2, None)]) == []


def test_intervals_are_sorted_before_pairing():
    """Unordered input must not silently yield a number from fewer plays."""
    shuffled = [play(3, 3540), play(1, 3600), play(2, 3570)]
    assert [i["seconds"] for i in play_intervals(shuffled)] == [30, 30]


def test_plays_from_different_games_never_pair():
    other = play(1, 3600, game_id="2024_01_GB_PHI")
    assert play_intervals([play(1, 3600), other]) == []


def test_neutral_requires_the_first_three_quarters():
    assert is_neutral(play(), play(qtr=4)) is False
    assert is_neutral(play(), play(qtr=3)) is True


def test_neutral_requires_a_one_score_game():
    assert is_neutral(play(), play(score_differential=8)) is False
    assert is_neutral(play(), play(score_differential=-7)) is True


def test_neutral_requires_the_clock_to_have_been_running():
    """An incompletion stops the clock, so the next snap looks instant."""
    assert is_neutral(play(incomplete_pass=1), play()) is False
    assert is_neutral(play(incomplete_pass=0), play()) is True


def test_neutral_handles_a_missing_score():
    assert is_neutral(play(), play(score_differential=None)) is False


def test_pace_is_the_mean_of_intervals():
    rows = aggregate_tempo([play(1, 3600), play(2, 3570), play(3, 3530)])
    assert rows[0]["pace_intervals"] == 2
    assert rows[0]["seconds_per_play"] == 35.0


def test_proe_is_the_mean_of_pass_oe():
    rows = aggregate_tempo([play(1, 3600, pass_oe=10.0), play(2, 3570, pass_oe=-4.0)])
    assert rows[0]["proe"] == 3.0


def test_a_week_with_no_neutral_intervals_is_kept_with_null():
    """Dropping the row or storing 0.0 would both read as a real measurement."""
    rows = aggregate_tempo([play(1, 3600, qtr=4), play(2, 3570, qtr=4)])
    assert len(rows) == 1
    assert rows[0]["neutral_intervals"] == 0
    assert rows[0]["neutral_seconds_per_play"] is None
    assert rows[0]["seconds_per_play"] == 30.0


def test_teams_and_weeks_bucket_separately():
    rows = aggregate_tempo([play(1, 3600), play(1, 3600, week=2), play(1, 3600, posteam="NE")])
    assert len(rows) == 3


def test_non_scrimmage_plays_are_ignored():
    rows = aggregate_tempo([play(1, 3600, **{"pass": 0, "rush": 0})])
    assert rows == []


def test_preseason_is_ignored():
    assert aggregate_tempo([play(1, 3600, season_type="PRE")]) == []


def test_a_play_without_possession_is_ignored():
    assert aggregate_tempo([play(1, 3600, posteam=None)]) == []


def test_empty_input():
    assert aggregate_tempo([]) == []
