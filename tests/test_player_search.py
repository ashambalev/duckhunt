"""`store.search_players` and `GET /api/players` — the name entry's lookup.

The point of the whole feature is that `Женя`, `женя` and `Zhenya` do not become
three players, so most of what is checked here is folding.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request

import pytest

from leaderboard import server, store


# --- the store ------------------------------------------------------------

def test_search_key_folds_case_and_accents():
    assert store.search_key("Женя") == store.search_key("ЖЕНЯ")
    assert store.search_key("José") == store.search_key("jose")
    assert store.search_key("  Anna   Lee ") == "anna lee"


def test_empty_query_offers_the_most_recent_players(conn, add):
    add("Anna", finished_at="2026-09-26T18:01:00+00:00")
    add("Boris", finished_at="2026-09-26T19:01:00+00:00")
    names = [r["name"] for r in store.search_players(conn)]
    assert names == ["Boris", "Anna"]


def test_prefix_matches_come_before_substring_matches(conn, add):
    add("Ann", hits=5)
    add("Joanna", hits=40)
    rows = store.search_players(conn, "ann")
    assert [r["name"] for r in rows] == ["Ann", "Joanna"]


def test_case_and_accent_blind_matching(conn, add):
    add("Женя")
    add("José")
    assert [r["name"] for r in store.search_players(conn, "ЖЕН")] == ["Женя"]
    assert [r["name"] for r in store.search_players(conn, "jos")] == ["José"]


def test_one_player_one_row_with_their_best_and_every_attempt(conn, add):
    add("Женя", hits=20, uuid="a")
    add("женя", hits=35, uuid="b")
    add("ЖЕНЯ", hits=30, uuid="c")
    rows = store.search_players(conn, "жен")
    assert len(rows) == 1
    assert rows[0]["attempts"] == 3
    assert rows[0]["hits"] == 35


def test_the_name_comes_back_in_its_first_spelling(conn, add):
    add("Женя", hits=20, uuid="a")            # first typed
    add("ЖЕНЯ", hits=90, uuid="b")            # their best, shouted
    assert store.search_players(conn, "жен")[0]["name"] == "Женя"


def test_every_round_size_is_searched_and_the_score_says_which(conn, add):
    add("Anna", hits=30, ducks=40)
    rows = store.search_players(conn, "anna")
    assert rows[0]["ducks"] == 40 and rows[0]["hits"] == 30


def test_wildcards_in_the_query_are_literal_characters(conn, add):
    add("Anna")
    assert store.search_players(conn, "%") == []
    assert store.search_players(conn, "_nn") == []
    assert store.search_players(conn, "a%a") == []


def test_no_match_is_an_empty_list_not_an_error(conn, add):
    add("Anna")
    assert store.search_players(conn, "zzz") == []


def test_limit_is_clamped(conn, add):
    for i in range(5):
        add(f"P{i}")
    assert len(store.search_players(conn, "", limit=2)) == 2
    assert len(store.search_players(conn, "", limit=0)) == 1
    assert len(store.search_players(conn, "", limit=999)) == 5


# --- the route ------------------------------------------------------------

@pytest.fixture()
def url(db):
    httpd = server.build("127.0.0.1", 0, db)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def get(url, path, **params):
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}{path}?{query}", timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def test_route_answers_with_rows_and_the_query_it_ran(url, add):
    add("Женя", hits=66, ducks=40)
    body = get(url, "/api/players", q="жен")
    assert body["ok"] is True and body["q"] == "жен"
    assert body["rows"][0]["name"] == "Женя"
    assert body["rows"][0]["hits"] == 66


def test_route_with_no_query_lists_the_regulars(url, add):
    add("Anna")
    assert get(url, "/api/players")["rows"][0]["name"] == "Anna"


def test_route_respects_limit(url, add):
    for i in range(4):
        add(f"P{i}")
    assert len(get(url, "/api/players", limit=2)["rows"]) == 2


def test_players_route_does_not_shadow_the_single_player_route(url, add):
    add("Anna", hits=7, ducks=40)
    body = get(url, "/api/player/anna", ducks=40)
    assert body["name"] == "Anna" and body["best"]["hits"] == 7


def test_the_best_round_means_the_same_thing_at_every_size(conn, add):
    # 40/40 is a better round than 45/100, and the name screen must not disagree
    # with `/api/board?ducks=40` about which one is this player's best
    add("Anna", hits=40, shots=40, ducks=40, uuid="perfect")
    add("Anna", hits=45, shots=90, ducks=100, uuid="mediocre")
    row = store.search_players(conn, "anna")[0]
    assert (row["hits"], row["ducks"]) == (40, 40)
    assert store.board(conn, ducks=40)[0]["hits"] == 40
