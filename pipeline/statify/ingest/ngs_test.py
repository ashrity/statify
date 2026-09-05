import pytest

from statify.ingest.common import normalize_team
from statify.ingest.ngs import align_postseason_weeks

# Real week lists pulled from nflreadpy while speccing this feature. The 2019 row
# is the 17-game era, the others the 18-game era; the Super Bowl is one higher in
# NGS in every case.
REAL_SEASONS = [
    ("2019", [18, 19, 20, 22], [18, 19, 20, 21], {18: 18, 19: 19, 20: 20, 22: 21}),
    ("2021", [19, 20, 21, 23], [19, 20, 21, 22], {19: 19, 20: 20, 21: 21, 23: 22}),
    ("2024", [19, 20, 21, 23], [19, 20, 21, 22], {19: 19, 20: 20, 21: 21, 23: 22}),
]


@pytest.mark.parametrize("label,ngs,schedule,expected", REAL_SEASONS)
def test_aligns_real_seasons(label, ngs, schedule, expected):
    assert align_postseason_weeks(ngs, schedule) == expected


def test_partial_postseason_passes_through():
    """Mid-playoffs the schedule knows all four weeks but NGS has only the first."""
    assert align_postseason_weeks([19], [19, 20, 21, 22]) == {19: 19}


def test_no_postseason_yet():
    assert align_postseason_weeks([], [19, 20, 21, 22]) == {}


def test_super_bowl_only():
    """A single-week filter must still resolve, since 23 is the max of its own list."""
    assert align_postseason_weeks([23], [19, 20, 21, 22]) == {23: 22}


def test_gap_in_the_middle_raises():
    """A missing round means the one-gap assumption broke; guessing would be wrong."""
    with pytest.raises(RuntimeError, match="expected at most one unrecognized"):
        align_postseason_weeks([19, 25, 23], [19, 20, 21, 22])


def test_unrecognized_week_below_the_max_raises():
    with pytest.raises(RuntimeError, match="expected at most one unrecognized"):
        align_postseason_weeks([19, 30, 40], [19, 20, 21, 22])


def test_schedule_without_postseason_raises():
    with pytest.raises(RuntimeError, match="no postseason weeks"):
        align_postseason_weeks([19], [])


@pytest.mark.parametrize(
    "given,expected",
    [("LAR", "LA"), ("LA", "LA"), ("KC", "KC"), ("LV", "LV"), (None, None)],
)
def test_normalize_team(given, expected):
    assert normalize_team(given) == expected
