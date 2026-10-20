from statify.ingest.projections import latest_values, new_rows

UPDATED_AT = "2026-01-01T00:00:00+00:00"
MODEL_VERSION = "v1"


def candidate(player, week, stat_type, value, season=2024):
    return {"player_id": player, "season": season, "week": week, "stat_type": stat_type, "raw_projection": value}


def stored(player, week, stat_type, value, generated_at="2025-01-01T00:00:00+00:00", season=2024):
    return {
        "player_id": player,
        "season": season,
        "week": week,
        "stat_type": stat_type,
        "projected_value": value,
        "generated_at": generated_at,
    }


# --- latest_values ----------------------------------------------------------


def test_latest_values_keys_by_player_week_stat_type():
    values = latest_values([stored("WR1", 3, "receiving_yards", 42.0)])
    assert values[("WR1", 2024, 3, "receiving_yards")] == 42.0


def test_latest_values_is_empty_with_no_stored_rows():
    assert latest_values([]) == {}


# --- the novelty decision ----------------------------------------------------


def test_a_brand_new_key_always_produces_a_row():
    rows = new_rows([candidate("WR1", 3, "receiving_yards", 50.0)], {}, MODEL_VERSION, updated_at=UPDATED_AT)
    assert len(rows) == 1
    assert rows[0]["projected_value"] == 50.0
    assert rows[0]["model_version"] == MODEL_VERSION


def test_an_unchanged_value_produces_no_row():
    latest = {("WR1", 2024, 3, "receiving_yards"): 50.0}
    rows = new_rows([candidate("WR1", 3, "receiving_yards", 50.0)], latest, MODEL_VERSION, updated_at=UPDATED_AT)
    assert rows == []


def test_a_changed_value_produces_a_new_row():
    latest = {("WR1", 2024, 3, "receiving_yards"): 50.0}
    rows = new_rows([candidate("WR1", 3, "receiving_yards", 55.0)], latest, MODEL_VERSION, updated_at=UPDATED_AT)
    assert len(rows) == 1
    assert rows[0]["projected_value"] == 55.0


def test_each_stat_type_is_judged_independently():
    latest = {("WR1", 2024, 3, "receiving_yards"): 50.0}
    rows = new_rows(
        [candidate("WR1", 3, "receiving_yards", 50.0), candidate("WR1", 3, "receptions", 4.0)],
        latest,
        MODEL_VERSION,
        updated_at=UPDATED_AT,
    )
    assert len(rows) == 1
    assert rows[0]["stat_type"] == "receptions"


def test_every_new_row_carries_the_stamp_and_no_market_fields():
    rows = new_rows([candidate("WR1", 3, "receiving_yards", 50.0)], {}, MODEL_VERSION, updated_at=UPDATED_AT)
    assert rows[0]["generated_at"] == UPDATED_AT
    assert set(rows[0].keys()) == {
        "player_id", "season", "week", "stat_type", "model_version", "projected_value", "generated_at"
    }
