from statify.ingest.forecast import (
    STADIUM_PLACES,
    forecast_row,
    is_new_capture,
    matches,
    pick_place,
    stadium_row,
)

NOW = "2026-10-20T00:00:00+00:00"


def place(name="Santa Clara", country="US", admin1="California", lat=37.35, lon=-121.95):
    return {"name": name, "country_code": country, "admin1": admin1,
            "latitude": lat, "longitude": lon}


# --- choosing the right place -----------------------------------------------


def test_the_right_country_and_state_matches():
    assert matches(place(), "US", "California") is True


def test_the_wrong_country_does_not():
    assert matches(place(country="CU", admin1="Villa Clara Province"), "US", "California") is False


def test_the_wrong_state_does_not():
    """Glendale exists in Arizona and California; only one has a stadium."""
    assert matches(place(name="Glendale", admin1="California"), "US", "Arizona") is False


def test_no_state_required_means_country_alone_decides():
    assert matches(place(name="Munich", country="DE", admin1="Bavaria"), "DE", None) is True


def test_the_cuba_case():
    """Measured: the geocoder leads with Cuba for Santa Clara."""
    results = [place(country="CU", admin1="Villa Clara Province", lat=22.4, lon=-79.9),
               place()]
    assert pick_place(results, "US", "California")["latitude"] == 37.35


def test_the_reunion_case():
    """Measured: the geocoder leads with Reunion for Saint-Denis."""
    results = [place(name="Saint-Denis", country="RE", admin1="Reunion", lat=-20.9, lon=55.5),
               place(name="Saint-Denis", country="FR", admin1="Ile-de-France", lat=48.9, lon=2.4)]
    assert pick_place(results, "FR", None)["latitude"] == 48.9


def test_no_match_returns_none_rather_than_the_first_result():
    """Falling back to the first result is what puts a stadium in Cuba."""
    assert pick_place([place(country="CU")], "US", "California") is None


def test_an_empty_result_list_returns_none():
    assert pick_place([], "US", "California") is None


# --- the map ----------------------------------------------------------------


def test_every_stadium_has_a_place_and_a_country():
    for stadium_id, (name, country, _admin1) in STADIUM_PLACES.items():
        assert name and country, stadium_id
        assert len(country) == 2, stadium_id


def test_every_us_stadium_names_its_state():
    """Without it, Glendale, Arlington and Santa Clara are all ambiguous."""
    for stadium_id, (_name, country, admin1) in STADIUM_PLACES.items():
        if country == "US":
            assert admin1 is not None, stadium_id


def test_the_two_munich_ids_share_a_place():
    """GER00 and MUN01 are the same venue, so an identical coordinate is correct."""
    assert STADIUM_PLACES["GER00"] == STADIUM_PLACES["MUN01"]


def test_a_row_carries_the_resolved_coordinate():
    row = stadium_row("SFO01", "Santa Clara", place(), NOW)
    assert row["stadium_id"] == "SFO01"
    assert (row["latitude"], row["longitude"]) == (37.35, -121.95)
    assert row["country_code"] == "US"
    assert row["resolved_at"] == NOW


# --- matching an hour to a kickoff ------------------------------------------

HOURS = {
    "time": ["2026-10-23T00:00", "2026-10-23T01:00", "2026-10-23T02:00"],
    "temperature_2m": [50.0, 52.0, 54.0],
    "wind_speed_10m": [5.0, 7.0, 9.0],
    "precipitation_probability": [10, 20, 30],
}


def game(kickoff="2026-10-23T01:00:00+00:00"):
    return {"game_id": "2026_07_CIN_BAL", "season": 2026, "week": 7, "kickoff_at": kickoff}


def test_a_kickoff_on_the_hour_takes_that_hour():
    row = forecast_row(game("2026-10-23T01:00:00+00:00"), HOURS, NOW)
    assert row["forecast_for"] == "2026-10-23T01:00"
    assert row["temperature_f"] == 52.0 and row["wind_mph"] == 7.0


def test_twenty_nine_minutes_past_rounds_down():
    """Truncation and round-to-nearest differ by a full hour and both look right."""
    row = forecast_row(game("2026-10-23T01:29:00+00:00"), HOURS, NOW)
    assert row["forecast_for"] == "2026-10-23T01:00"


def test_thirty_one_minutes_past_rounds_up():
    row = forecast_row(game("2026-10-23T01:31:00+00:00"), HOURS, NOW)
    assert row["forecast_for"] == "2026-10-23T02:00"


def test_a_kickoff_after_the_window_has_no_forecast():
    """None rather than the last value, which would be days wrong."""
    assert forecast_row(game("2026-11-20T18:00:00+00:00"), HOURS, NOW) is None


def test_a_kickoff_before_the_window_has_no_forecast():
    assert forecast_row(game("2026-09-01T18:00:00+00:00"), HOURS, NOW) is None


def test_an_empty_series_has_no_forecast():
    assert forecast_row(game(), {"time": []}, NOW) is None
    assert forecast_row(game(), {}, NOW) is None


def test_the_row_carries_the_game_identity_and_the_hour_used():
    row = forecast_row(game(), HOURS, NOW)
    assert row["game_id"] == "2026_07_CIN_BAL"
    assert row["season"] == 2026 and row["week"] == 7
    assert row["captured_at"] == NOW
    assert row["forecast_for"] == "2026-10-23T01:00"


def test_a_naive_provider_timestamp_compares_against_an_aware_kickoff():
    """Open-Meteo omits the offset; games store one. Mixing them would raise."""
    assert forecast_row(game("2026-10-23T02:00:00+00:00"), HOURS, NOW)["wind_mph"] == 9.0


# --- novelty is content, not the clock --------------------------------------


def stored(wind=7.0, temp=52.0, precip=20, game_id="2026_07_CIN_BAL"):
    return {"game_id": game_id, "wind_mph": wind, "temperature_f": temp,
            "precip_chance": precip}


def test_an_unseen_game_is_new():
    assert is_new_capture(stored(), {}) is True


def test_an_unchanged_forecast_is_not_new():
    """Two runs an hour apart carry different clocks and the same weather."""
    assert is_new_capture(stored(), {"2026_07_CIN_BAL": (7.0, 52.0, 20)}) is False


def test_a_moved_wind_is_new():
    assert is_new_capture(stored(wind=12.0), {"2026_07_CIN_BAL": (7.0, 52.0, 20)}) is True


def test_a_moved_temperature_is_new():
    assert is_new_capture(stored(temp=40.0), {"2026_07_CIN_BAL": (7.0, 52.0, 20)}) is True


def test_a_moved_precipitation_chance_is_new():
    assert is_new_capture(stored(precip=80), {"2026_07_CIN_BAL": (7.0, 52.0, 20)}) is True


def test_games_are_judged_separately():
    """One game's forecast moving must not suppress another's."""
    assert is_new_capture(stored(game_id="other"), {"2026_07_CIN_BAL": (7.0, 52.0, 20)}) is True
