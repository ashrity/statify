import pytest

from statify.ingest.injuries import normalize_designation, normalize_practice_status


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
