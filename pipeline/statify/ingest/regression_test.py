import pytest

from statify.ingest.regression import build_features, fit_and_evaluate, mae, train_test_split

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def row(week, baseline, matchup=1.0, environment=1.0, actual=None, pid=1):
    return {
        "projection_id": pid,
        "week": week,
        "baseline_value": baseline,
        "matchup_multiplier_used": matchup,
        "environment_multiplier_used": environment,
        "actual_value": actual if actual is not None else baseline,
    }


# --- feature construction --------------------------------------------------------


def test_build_features_centers_the_interaction_terms_on_neutral():
    X, y = build_features([row(1, baseline=10.0, matchup=1.2, environment=0.9, actual=15.0)])
    assert X[0] == pytest.approx([10.0, 10.0 * 0.2, 10.0 * -0.1])
    assert y == [15.0]


def test_a_neutral_row_contributes_zero_to_both_interaction_terms():
    X, _ = build_features([row(1, baseline=10.0, matchup=1.0, environment=1.0)])
    assert X == [[10.0, 0.0, 0.0]]


# --- the temporal train/test split -----------------------------------------------


def test_a_test_weeks_row_never_appears_in_training():
    rows = [row(w, baseline=10.0) for w in range(1, 6)]
    train, test = train_test_split(rows, test_weeks={4, 5})
    assert {r["week"] for r in train} == {1, 2, 3}
    assert {r["week"] for r in test} == {4, 5}


def test_the_split_is_exhaustive():
    rows = [row(w, baseline=10.0) for w in range(1, 6)]
    train, test = train_test_split(rows, test_weeks={4, 5})
    assert len(train) + len(test) == len(rows)


# --- mae -------------------------------------------------------------------------


def test_mae_is_the_mean_absolute_error():
    assert mae([10.0, 20.0], [12.0, 15.0]) == (2.0 + 5.0) / 2


# --- model selection on a known case ----------------------------------------------


def test_the_better_of_two_models_is_selected():
    """A dataset with real signal in the interaction terms: a model that
    uses them should test better than pure noise, and fit_and_evaluate must
    report a real stat_type-shaped result either way."""
    train_rows = [
        row(w, baseline=10.0 + i, matchup=1.0 + 0.1 * (i % 3), environment=1.0, actual=10.0 + i + 2 * (i % 3))
        for i, w in enumerate(range(1, 15))
    ]
    test_rows = [
        row(w, baseline=10.0 + i, matchup=1.0 + 0.1 * (i % 3), environment=1.0, actual=10.0 + i + 2 * (i % 3))
        for i, w in enumerate(range(15, 19))
    ]
    result = fit_and_evaluate(train_rows, test_rows)
    assert result["model"] in ("ridge", "lasso")
    assert "candidates" in result
    assert set(result["candidates"].keys()) == {"ridge", "lasso"}
    assert result["test_mae"] == min(c["test_mae"] for c in result["candidates"].values())
