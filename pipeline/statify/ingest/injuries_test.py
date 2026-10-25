import pytest

from statify.ingest.injuries import (
    is_unchanged,
    normalize_designation,
    normalize_practice_status,
)


@pytest.mark.parametrize(
    "given,expected",
    [
        ("Did Not Participate In Practice", "DNP"),
        ("Limited Participation in Practice", "Limited"),
        ("Full Participation in Practice", "Full"),
    ],
)
def test_practice_sentences_map_to_short_forms(given, expected):
    assert normalize_practice_status(given) == expected


@pytest.mark.parametrize("given", [None, "", "   ", "\n    ", "Note"])
def test_practice_blanks_and_annotations_become_null(given):
    assert normalize_practice_status(given) is None


def test_unknown_practice_status_raises():
    """A new upstream wording must not quietly read as 'no practice report'."""
    with pytest.raises(RuntimeError, match="unrecognized practice status"):
        normalize_practice_status("Rested - Coach's Decision")


@pytest.mark.parametrize("given", ["Out", "Doubtful", "Questionable"])
def test_real_designations_pass_through(given):
    assert normalize_designation(given) == given


@pytest.mark.parametrize("given", [None, "", "   ", "Note"])
def test_designation_blanks_and_annotations_become_null(given):
    assert normalize_designation(given) is None


def test_unknown_designation_raises():
    """Silently nulling an unknown designation would mark an injured player available."""
    with pytest.raises(RuntimeError, match="unrecognized injury designation"):
        normalize_designation("Probable")


def test_surrounding_whitespace_is_tolerated():
    assert normalize_designation("  Out  ") == "Out"
    assert normalize_practice_status(" Full Participation in Practice ") == "Full"


# --- a feed with no timestamp of its own --------------------------------------
#
# 2024 carries date_modified; 2026 does not, while every other column matches.
# report_at is part of this table's key, so those rows are stamped with the
# ingest time and novelty is decided by content instead.


def report(designation="Out", practice="DNP"):
    return {
        "player_id": "P1",
        "season": 2026,
        "week": 7,
        "designation": designation,
        "practice_status": practice,
    }


def test_a_player_with_no_stored_report_is_always_new():
    assert is_unchanged(report(), {}) is False


def test_an_identical_report_is_unchanged():
    latest = {("P1", 7): ("Out", "DNP")}
    assert is_unchanged(report(), latest) is True


def test_an_upgraded_designation_is_a_change():
    """Questionable to Out is the whole point of re-pulling mid-week."""
    latest = {("P1", 7): ("Questionable", "DNP")}
    assert is_unchanged(report(designation="Out"), latest) is False


def test_a_practice_status_change_alone_is_a_change():
    latest = {("P1", 7): ("Out", "Limited")}
    assert is_unchanged(report(practice="DNP"), latest) is False


def test_clearing_a_designation_is_a_change():
    """A player coming off the report must not read as unchanged."""
    latest = {("P1", 7): ("Questionable", "Full")}
    assert is_unchanged(report(designation=None, practice="Full"), latest) is False


def test_the_same_player_in_a_different_week_is_not_compared():
    latest = {("P1", 6): ("Out", "DNP")}
    assert is_unchanged(report(), latest) is False
