from statify.ingest.routes import count_routes, dropback_keys, parse_players

POSITIONS = {
    "wr1": "WR",
    "te1": "TE",
    "rb1": "RB",
    "qb1": "QB",
    "lt1": "T",
}


def play(play_id=1, game_id="G", dropback=1, special=0, season_type="REG", week=1):
    return {
        "game_id": game_id,
        "play_id": play_id,
        "week": week,
        "season_type": season_type,
        "qb_dropback": dropback,
        "special_teams_play": special,
    }


def participation_row(play_id=1, game_id="G", players="wr1;te1;rb1;qb1;lt1"):
    return {"nflverse_game_id": game_id, "play_id": play_id, "offense_players": players}


def test_a_dropback_is_a_route_opportunity():
    assert dropback_keys([play()]) == {("G", 1)}


def test_a_run_is_not():
    assert dropback_keys([play(dropback=0)]) == set()


def test_a_special_teams_play_is_not():
    """Participation covers punts, where 'offense_players' is a return unit."""
    assert dropback_keys([play(special=1)]) == set()


def test_preseason_is_not():
    assert dropback_keys([play(season_type="PRE")]) == set()


def test_players_split_on_semicolons():
    assert parse_players("a;b;c") == ["a", "b", "c"]


def test_a_single_player_parses():
    assert parse_players("a") == ["a"]


def test_an_empty_player_list_parses_to_nothing():
    assert parse_players("") == []
    assert parse_players(None) == []


def test_receivers_backs_and_tight_ends_get_routes():
    routes = count_routes([participation_row()], {("G", 1)}, POSITIONS)
    assert routes[("wr1", "G")] == 1
    assert routes[("te1", "G")] == 1
    assert routes[("rb1", "G")] == 1


def test_a_quarterback_never_gets_a_route():
    """He is on the field for every dropback; counting him puts him top of the league."""
    routes = count_routes([participation_row()], {("G", 1)}, POSITIONS)
    assert ("qb1", "G") not in routes


def test_a_lineman_never_gets_a_route():
    routes = count_routes([participation_row()], {("G", 1)}, POSITIONS)
    assert ("lt1", "G") not in routes


def test_a_player_we_do_not_store_is_ignored():
    routes = count_routes([participation_row(players="nobody")], {("G", 1)}, POSITIONS)
    assert routes == {}


def test_a_play_that_is_not_a_dropback_contributes_nothing():
    routes = count_routes([participation_row(play_id=2)], {("G", 1)}, POSITIONS)
    assert routes == {}


def test_routes_accumulate_across_plays():
    rows = [participation_row(play_id=n, players="wr1") for n in (1, 2, 3)]
    routes = count_routes(rows, {("G", 1), ("G", 2), ("G", 3)}, POSITIONS)
    assert routes[("wr1", "G")] == 3


def test_games_are_counted_separately():
    rows = [
        participation_row(game_id="G1", players="wr1"),
        participation_row(game_id="G2", players="wr1"),
    ]
    routes = count_routes(rows, {("G1", 1), ("G2", 1)}, POSITIONS)
    assert routes[("wr1", "G1")] == 1
    assert routes[("wr1", "G2")] == 1


def test_no_participation_yields_no_routes():
    assert count_routes([], {("G", 1)}, POSITIONS) == {}
