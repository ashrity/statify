from statify.refresh import StepResult, run_refresh, step_list


# --- the step list's shape ---------------------------------------------------


def test_every_ingest_and_compute_step_is_present():
    labels = [label for label, _ in step_list(2024)]
    expected = [
        "ingest games",
        "ingest players",
        "ingest weekly",
        "ingest ngs",
        "ingest snaps",
        "ingest redzone",
        "ingest depth",
        "ingest injuries",
        "ingest routes",
        "ingest weather",
        "ingest forecast",
        "ingest market",
        "compute defense",
        "compute matchup",
        "compute tendencies",
        "compute tempo",
        "compute usage",
        "compute efficiency",
        "compute form",
        "compute volume",
        "compute environment",
        "compute opportunity",
        "compute expected-efficiency",
        "compute touchdowns",
        "compute matchup-adjustment",
        "compute projection",
        "compute generate-projections",
        "compute edge",
        "compute confidence",
        "compute backtest",
        "compute accuracy",
    ]
    assert labels == expected


def test_props_teams_and_stadiums_are_never_included():
    labels = [label for label, _ in step_list(2024)]
    assert "ingest props" not in labels
    assert "ingest teams" not in labels
    assert "ingest stadiums" not in labels


def test_redzone_runs_after_snaps():
    labels = [label for label, _ in step_list(2024)]
    assert labels.index("ingest snaps") < labels.index("ingest redzone")


def test_matchup_depends_on_defense_running_first():
    labels = [label for label, _ in step_list(2024)]
    assert labels.index("compute defense") < labels.index("compute matchup")


def test_opportunity_runs_after_volume():
    labels = [label for label, _ in step_list(2024)]
    assert labels.index("compute volume") < labels.index("compute opportunity")


def test_projection_runs_after_its_four_inputs():
    labels = [label for label, _ in step_list(2024)]
    projection = labels.index("compute projection")
    for dependency in (
        "compute opportunity",
        "compute expected-efficiency",
        "compute touchdowns",
        "compute matchup-adjustment",
    ):
        assert labels.index(dependency) < projection


# --- week-less steps keep the --week flag out of their own argv ----------------


def test_season_only_steps_never_receive_a_week_flag():
    steps = dict(step_list(2024, week=7))
    for label in ("compute matchup", "compute tendencies", "compute form", "compute environment", "ingest weather"):
        assert "--week" not in steps[label]


def test_weekly_steps_receive_the_week_flag_when_given():
    steps = dict(step_list(2024, week=7))
    assert "--week" in steps["ingest weekly"]
    assert steps["ingest weekly"][steps["ingest weekly"].index("--week") + 1] == "7"


def test_no_week_flag_at_all_when_week_is_omitted():
    steps = dict(step_list(2024))
    assert "--week" not in steps["ingest weekly"]


# --- resilience: a failing step does not abort the run -------------------------


def test_a_failing_step_is_recorded_not_raised():
    def flaky_dispatch(argv):
        if argv[1] == "depth":
            raise RuntimeError("no depth chart data for 2026")
        return 0

    results = run_refresh(2026, dispatch=flaky_dispatch)
    by_label = {r.label: r for r in results}
    assert by_label["ingest depth"] == StepResult("ingest depth", False, "no depth chart data for 2026")
    # every step after the failure still ran
    assert by_label["ingest injuries"].ok is True
    assert by_label["compute accuracy"].ok is True


def test_every_step_succeeding_reports_all_ok():
    results = run_refresh(2024, dispatch=lambda argv: 0)
    assert all(r.ok for r in results)
    assert len(results) == len(step_list(2024))
