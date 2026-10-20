import math

from statify.ingest.accuracy import accuracy_rows, beat_line_rate, mae, rmse

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def backtest(season=2024, week=3, stat_type="receiving_yards", model_version="v1", error=0.0, beat_line=None):
    return {
        "season": season,
        "week": week,
        "stat_type": stat_type,
        "model_version": model_version,
        "error": error,
        "beat_line": beat_line,
    }


# --- the arithmetic -----------------------------------------------------------


def test_mae_is_the_mean_of_absolute_errors():
    assert mae([3.0, -4.0, 5.0]) == (3.0 + 4.0 + 5.0) / 3


def test_rmse_is_the_root_mean_square():
    errors = [3.0, -4.0]
    assert rmse(errors) == math.sqrt((9.0 + 16.0) / 2)


def test_beat_line_rate_is_the_mean_of_non_null_values():
    assert beat_line_rate([1, 0, 1, 1]) == 0.75


def test_beat_line_rate_is_none_with_no_non_null_rows():
    assert beat_line_rate([]) is None


# --- grouping and the full row -------------------------------------------------


def test_one_row_per_season_week_stat_type_model_version():
    rows = accuracy_rows(
        [
            backtest(week=3, stat_type="receiving_yards", error=2.0),
            backtest(week=3, stat_type="receiving_yards", error=-4.0),
            backtest(week=4, stat_type="receiving_yards", error=1.0),
        ],
        updated_at=UPDATED_AT,
    )
    assert len(rows) == 2
    week3 = next(r for r in rows if r["week"] == 3)
    assert week3["n"] == 2
    assert week3["mae"] == 3.0


def test_beat_line_denominator_is_beat_line_n_not_n():
    """A push (beat_line None) must not silently count as a 0 against n."""
    rows = accuracy_rows(
        [
            backtest(beat_line=1),
            backtest(beat_line=None),  # a push, excluded from both sides
            backtest(beat_line=None),
        ],
        updated_at=UPDATED_AT,
    )
    row = rows[0]
    assert row["n"] == 3
    assert row["beat_line_n"] == 1
    assert row["beat_line_rate"] == 1.0


def test_a_group_with_no_beat_line_data_gets_a_null_rate_not_a_crash():
    rows = accuracy_rows([backtest(beat_line=None), backtest(beat_line=None)], updated_at=UPDATED_AT)
    row = rows[0]
    assert row["beat_line_n"] == 0
    assert row["beat_line_rate"] is None


def test_different_model_versions_get_separate_rows():
    rows = accuracy_rows(
        [backtest(model_version="v1", error=1.0), backtest(model_version="v2", error=100.0)],
        updated_at=UPDATED_AT,
    )
    assert len(rows) == 2
    versions = {r["model_version"]: r["mae"] for r in rows}
    assert versions["v1"] == 1.0
    assert versions["v2"] == 100.0
