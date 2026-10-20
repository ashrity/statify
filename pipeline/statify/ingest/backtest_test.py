from statify.ingest.backtest import actual_value, backtest_row, beat_line


def row(
    stat_type,
    projected_value=50.0,
    market_line=45.0,
    edge=5.0,
    receiving_yards=0,
    receptions=0,
    rushing_yards=0,
    passing_yards=0,
    receiving_tds=0,
    rushing_tds=0,
    pid=1,
):
    return {
        "id": pid,
        "stat_type": stat_type,
        "projected_value": projected_value,
        "market_line": market_line,
        "edge": edge,
        "receiving_yards": receiving_yards,
        "receptions": receptions,
        "rushing_yards": rushing_yards,
        "passing_yards": passing_yards,
        "receiving_tds": receiving_tds,
        "rushing_tds": rushing_tds,
    }


# --- actual value extraction -----------------------------------------------


def test_actual_value_reads_the_matching_column_per_stat_type():
    assert actual_value(row("receiving_yards", receiving_yards=73)) == 73.0
    assert actual_value(row("receptions", receptions=6)) == 6.0
    assert actual_value(row("rushing_yards", rushing_yards=88)) == 88.0
    assert actual_value(row("passing_yards", passing_yards=241)) == 241.0


def test_touchdowns_actual_is_one_if_either_phase_scored():
    assert actual_value(row("touchdowns", receiving_tds=1, rushing_tds=0)) == 1.0
    assert actual_value(row("touchdowns", receiving_tds=0, rushing_tds=1)) == 1.0
    assert actual_value(row("touchdowns", receiving_tds=1, rushing_tds=1)) == 1.0


def test_touchdowns_actual_is_zero_when_neither_phase_scored():
    assert actual_value(row("touchdowns", receiving_tds=0, rushing_tds=0)) == 0.0


# --- beat_line -----------------------------------------------------------------


def test_beat_line_is_one_when_sides_agree():
    # projected over (edge=5 > 0), actual also over the line (60 > 45)
    assert beat_line(actual=60.0, projected_value=50.0, market_line=45.0, edge=5.0) == 1


def test_beat_line_is_zero_when_sides_disagree():
    # projected over (edge=5 > 0), actual came in under the line (40 < 45)
    assert beat_line(actual=40.0, projected_value=50.0, market_line=45.0, edge=5.0) == 0


def test_beat_line_is_none_with_no_market_line():
    assert beat_line(actual=60.0, projected_value=50.0, market_line=None, edge=None) is None


def test_beat_line_is_none_on_an_edge_push():
    """The projection landed exactly on the line: no side was taken."""
    assert beat_line(actual=60.0, projected_value=45.0, market_line=45.0, edge=0.0) is None


def test_beat_line_is_none_on_an_actual_push():
    """The actual result landed exactly on the line: no side happened."""
    assert beat_line(actual=45.0, projected_value=50.0, market_line=45.0, edge=5.0) is None


def test_touchdowns_beat_line_uses_the_same_rule_at_a_smaller_scale():
    # projected under (edge negative, e.g. 0.1 prob vs 0.5 line), he did not score
    assert beat_line(actual=0.0, projected_value=0.1, market_line=0.5, edge=-0.4) == 1
    # he did score despite a low projection: the "under" side lost
    assert beat_line(actual=1.0, projected_value=0.1, market_line=0.5, edge=-0.4) == 0


# --- the full row ----------------------------------------------------------------


def test_backtest_row_computes_error_and_beat_line_together():
    result = backtest_row(row("receiving_yards", projected_value=50.0, market_line=45.0, edge=5.0, receiving_yards=60))
    assert result == {"projection_id": 1, "actual_value": 60.0, "error": 10.0, "beat_line": 1}


def test_backtest_row_with_no_market_line_still_computes_error():
    result = backtest_row(row("rushing_yards", projected_value=50.0, market_line=None, edge=None, rushing_yards=40))
    assert result["actual_value"] == 40.0
    assert result["error"] == -10.0
    assert result["beat_line"] is None
