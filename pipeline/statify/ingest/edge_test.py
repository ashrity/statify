from statify.ingest.edge import edge_updates, latest_at_or_before, prop_lines_by_key


def projection(player, week, stat_type, projected_value, generated_at, pid=1):
    return {
        "id": pid,
        "player_id": player,
        "week": week,
        "stat_type": stat_type,
        "projected_value": projected_value,
        "generated_at": generated_at,
    }


def prop_line(player, week, stat_type, line, captured_at, lid):
    return {"id": lid, "player_id": player, "week": week, "stat_type": stat_type, "line": line, "captured_at": captured_at}


# --- the temporal match -----------------------------------------------------


def test_a_line_captured_after_generation_is_ignored():
    candidates = [prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-02T00:00:00+00:00", 1)]
    match = latest_at_or_before(candidates, "2026-01-01T00:00:00+00:00")
    assert match is None


def test_the_latest_at_or_before_line_wins_among_several():
    candidates = sorted(
        [
            prop_line("WR1", 3, "receiving_yards", 55.5, "2026-01-01T00:00:00+00:00", 1),
            prop_line("WR1", 3, "receiving_yards", 58.5, "2026-01-02T00:00:00+00:00", 2),
            prop_line("WR1", 3, "receiving_yards", 70.5, "2026-01-05T00:00:00+00:00", 3),
        ],
        key=lambda r: (r["captured_at"], r["id"]),
    )
    match = latest_at_or_before(candidates, "2026-01-03T00:00:00+00:00")
    assert match["line"] == 58.5


def test_a_capture_at_the_exact_same_instant_counts_as_available():
    candidates = [prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-01T00:00:00+00:00", 1)]
    match = latest_at_or_before(candidates, "2026-01-01T00:00:00+00:00")
    assert match is not None


def test_the_tie_break_is_deterministic_by_id():
    candidates = sorted(
        [
            prop_line("WR1", 3, "receiving_yards", 55.5, "2026-01-01T00:00:00+00:00", 2),
            prop_line("WR1", 3, "receiving_yards", 56.5, "2026-01-01T00:00:00+00:00", 1),
        ],
        key=lambda r: (r["captured_at"], r["id"]),
    )
    match = latest_at_or_before(candidates, "2026-01-01T00:00:00+00:00")
    assert match["id"] == 2


def test_no_candidates_is_no_match():
    assert latest_at_or_before([], "2026-01-01T00:00:00+00:00") is None


# --- the full update set ------------------------------------------------------


def test_a_matched_projection_gets_an_edge_update():
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-02T00:00:00+00:00")
    lines = [prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-01T00:00:00+00:00", 10)]
    updates = edge_updates([proj], lines)
    assert len(updates) == 1
    assert updates[0] == {"id": 1, "market_line": 60.5, "prop_line_id": 10, "edge": 65.0 - 60.5}


def test_touchdowns_edge_is_probability_minus_the_fixed_line():
    proj = projection("WR1", 3, "touchdowns", 0.42, "2026-01-02T00:00:00+00:00")
    lines = [prop_line("WR1", 3, "touchdowns", 0.5, "2026-01-01T00:00:00+00:00", 11)]
    updates = edge_updates([proj], lines)
    assert updates[0]["edge"] == 0.42 - 0.5


def test_no_matching_line_leaves_the_projection_untouched():
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-02T00:00:00+00:00")
    updates = edge_updates([proj], [])
    assert updates == []


def test_a_different_player_or_stat_type_is_not_matched():
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-02T00:00:00+00:00")
    lines = [
        prop_line("WR2", 3, "receiving_yards", 60.5, "2026-01-01T00:00:00+00:00", 1),
        prop_line("WR1", 3, "receptions", 4.5, "2026-01-01T00:00:00+00:00", 2),
    ]
    assert edge_updates([proj], lines) == []


def test_a_null_line_is_not_a_match():
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-02T00:00:00+00:00")
    lines = [prop_line("WR1", 3, "receiving_yards", None, "2026-01-01T00:00:00+00:00", 1)]
    assert edge_updates([proj], lines) == []


def test_prop_lines_by_key_sorts_each_group_by_captured_at_then_id():
    lines = [
        prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-02T00:00:00+00:00", 2),
        prop_line("WR1", 3, "receiving_yards", 55.5, "2026-01-01T00:00:00+00:00", 1),
    ]
    grouped = prop_lines_by_key(lines)
    key = ("WR1", 3, "receiving_yards")
    assert [row["id"] for row in grouped[key]] == [1, 2]
