from statify.ingest.weather import has_reading, weather_row

KICKOFF = "2024-09-07T00:15:00+00:00"
UPDATED_AT = "2026-01-01T00:00:00+00:00"


def source(**overrides):
    base = {"game_id": "2024_01_BAL_KC", "temp": 67, "wind": 8}
    return {**base, **overrides}


def test_both_values_present_is_a_reading():
    assert has_reading(source()) is True


def test_neither_value_is_not_a_reading():
    assert has_reading(source(temp=None, wind=None)) is False


def test_temperature_alone_is_not_a_reading():
    """Does not occur in 2024, but the rule must not depend on check order."""
    assert has_reading(source(wind=None)) is False


def test_wind_alone_is_not_a_reading():
    assert has_reading(source(temp=None)) is False


def test_zero_wind_is_a_real_reading():
    """A calm game reads 0, which is a measurement, not a missing value."""
    assert has_reading(source(wind=0)) is True


def test_zero_temperature_is_a_real_reading():
    assert has_reading(source(temp=0)) is True


def test_row_coerces_to_float():
    """The feed ships ints; the columns are REAL."""
    row = weather_row(source(), KICKOFF, UPDATED_AT)
    assert row["temperature_f"] == 67.0
    assert row["wind_mph"] == 8.0
    assert isinstance(row["temperature_f"], float)


def test_observed_at_comes_from_the_game_not_the_clock():
    """It is the settled game-time condition, not when the pipeline ran."""
    row = weather_row(source(), KICKOFF, UPDATED_AT)
    assert row["observed_at"] == KICKOFF
    assert row["observed_at"] != row["updated_at"]


def test_row_never_carries_precipitation():
    """No source for it, so the loader must not invent one."""
    assert "precip_chance" not in weather_row(source(), KICKOFF, UPDATED_AT)
