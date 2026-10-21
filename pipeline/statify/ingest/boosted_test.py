from statify.ingest.boosted import FEATURE_NAMES, build_raw_features, fit_boosted_model
from statify.ingest.regression import train_test_split

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def row(week, baseline, matchup=1.0, environment=1.0, actual=None):
    return {
        "week": week,
        "baseline_value": baseline,
        "matchup_multiplier_used": matchup,
        "environment_multiplier_used": environment,
        "actual_value": actual if actual is not None else baseline,
    }


# --- the raw feature matrix, no interaction terms -------------------------------


def test_build_raw_features_is_exactly_the_three_raw_columns():
    X, y = build_raw_features([row(1, baseline=10.0, matchup=1.2, environment=0.9, actual=15.0)])
    assert X == [[10.0, 1.2, 0.9]]
    assert y == [15.0]
    assert len(FEATURE_NAMES) == 3


def test_no_interaction_terms_are_built():
    """Unlike feature 31, the matchup/environment values pass through raw."""
    X, _ = build_raw_features([row(1, baseline=10.0, matchup=1.5, environment=0.5)])
    assert X[0] == [10.0, 1.5, 0.5]


# --- reuses feature 31's split, not a second implementation --------------------


def test_reuses_feature_31s_train_test_split():
    rows = [row(w, baseline=10.0) for w in range(1, 6)]
    train, test = train_test_split(rows, test_weeks={4, 5})
    assert {r["week"] for r in train} == {1, 2, 3}
    assert {r["week"] for r in test} == {4, 5}


# --- the fit, importance and SHAP output -----------------------------------------


def test_fit_boosted_model_returns_three_importances_and_three_shap_values():
    train_rows = [
        row(w, baseline=10.0 + i, matchup=1.0 + 0.1 * (i % 3), environment=1.0, actual=10.0 + i + 2 * (i % 3))
        for i, w in enumerate(range(1, 15))
    ]
    test_rows = [
        row(w, baseline=10.0 + i, matchup=1.0 + 0.1 * (i % 3), environment=1.0, actual=10.0 + i + 2 * (i % 3))
        for i, w in enumerate(range(15, 19))
    ]
    result = fit_boosted_model(train_rows, test_rows)
    assert set(result["importance"].keys()) == set(FEATURE_NAMES)
    assert set(result["shap_importance"].keys()) == set(FEATURE_NAMES)
    assert all(v >= 0 for v in result["importance"].values())
    assert all(v >= 0 for v in result["shap_importance"].values())  # mean absolute SHAP, never negative
    assert result["test_mae"] >= 0
    assert result["train_mae"] >= 0
