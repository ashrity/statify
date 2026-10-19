from statify.sources.nflverse import CACHE_VARIABLE, cache_mode_to_apply


def test_an_unset_variable_gets_the_disk_cache():
    assert cache_mode_to_apply({}) == "filesystem"


def test_an_explicit_choice_is_left_alone():
    """The documented way to force a fresh pull when injuries have moved."""
    assert cache_mode_to_apply({CACHE_VARIABLE: "off"}) is None


def test_an_explicit_filesystem_is_also_left_alone():
    """Same value, but setting it again would still be us overriding the user."""
    assert cache_mode_to_apply({CACHE_VARIABLE: "filesystem"}) is None


def test_an_empty_variable_is_not_a_choice():
    """Set-but-empty is how a shell says nothing, not how it says 'off'."""
    assert cache_mode_to_apply({CACHE_VARIABLE: ""}) == "filesystem"
    assert cache_mode_to_apply({CACHE_VARIABLE: "   "}) == "filesystem"


def test_other_variables_are_ignored():
    assert cache_mode_to_apply({"NFLREADPY_CACHE_DIR": "/tmp/x"}) == "filesystem"
