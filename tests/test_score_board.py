"""The score on the board: the ranking, the migration, and what a POST may omit.

The score is no longer the hit count — a duck is worth `[score] duck`, a miss and
the dog cost their own amount — so a round can score less than a round that
downed fewer ducks, and a bad round can score below zero. Everything here is one
of the two things that can go wrong with that: the board ranking by a number that
no longer decides anything, and the rows that were already in `leaderboard.db`
losing their place because they were played under the old rule.

`conftest.run_row` builds a payload without a score (the shape a client that has
not been updated still posts), which is exactly what some of these tests need —
so the scored payload is a local helper here rather than a change to the fixture
every other test file shares.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest

from leaderboard import server, store

# The table as it was before the score: what `leaderboard.db` on this Mac looks
# like, down to the two indexes that rank by hits. A migration cannot be tested
# against the schema it produces.
OLD_SCHEMA = """
CREATE TABLE runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid     TEXT    NOT NULL UNIQUE,
    player_key   TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    hits         INTEGER NOT NULL,
    shots        INTEGER NOT NULL,
    ducks        INTEGER NOT NULL,
    accuracy     REAL    NOT NULL,
    duration     REAL    NOT NULL,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT    NOT NULL,
    client_id    TEXT    NOT NULL,
    input_source TEXT,
    game_version TEXT,
    settings     TEXT
);
CREATE INDEX runs_board  ON runs (ducks, hits DESC, shots ASC, finished_at ASC);
CREATE INDEX runs_player ON runs (player_key, hits DESC, shots ASC);
"""


def scored_row(name, score=0, hits=0, shots=0, ducks=40, dog_hits=0,
               crosshair=False, uuid=None, finished_at=None) -> dict:
    """A payload the way `server.validate` hands it over now, score included."""
    run_id = uuid or f"{name}-{score}-{hits}-{shots}-{ducks}-{finished_at or ''}"
    return {"run_uuid": run_id, "name": name, "hits": hits, "shots": shots,
            "ducks": ducks, "score": score, "dog_hits": dog_hits,
            "crosshair": crosshair, "duration": 60.0,
            "started_at": "2026-09-26T18:00:00+00:00",
            "finished_at": finished_at or "2026-09-26T18:01:00+00:00",
            "client_id": "test", "input_source": "keyboard",
            "game_version": "test", "settings": None}


def put(conn, name, **kw) -> dict:
    """`put(conn, "Ann", score=40, hits=20, shots=30)` — one stored round."""
    return store.insert_run(conn, scored_row(name, **kw))


# --- the ranking ----------------------------------------------------------

def test_the_board_ranks_by_score(conn):
    # Bob downed ten ducks to Ann's twenty and still wins: he wasted nothing
    put(conn, "Ann", score=32, hits=20, shots=36)
    put(conn, "Bob", score=44, hits=24, shots=26)
    put(conn, "Cid", score=38, hits=21, shots=30)
    assert [r["name"] for r in store.board(conn, ducks=40)] == ["Bob", "Cid", "Ann"]


def test_hits_break_a_tie_on_the_score(conn):
    # the same number of points, and the round that downed more ducks is better
    put(conn, "Ann", score=40, hits=24, shots=32)
    put(conn, "Bob", score=40, hits=22, shots=28)
    assert [r["name"] for r in store.board(conn, ducks=40)] == ["Ann", "Bob"]


def test_a_negative_score_sorts_below_a_positive_one(conn):
    # forty shots for three ducks: it happens, it is not clamped, and it is last
    put(conn, "Ann", score=-28, hits=3, shots=40)
    put(conn, "Bob", score=2, hits=1, shots=1)
    rows = store.board(conn, ducks=40)
    assert [r["name"] for r in rows] == ["Bob", "Ann"]
    assert rows[1]["score"] == -28


def test_the_board_hands_the_score_and_the_dog_back(conn):
    put(conn, "Ann", score=30, hits=20, shots=34, dog_hits=2, crosshair=True)
    row = store.board(conn, ducks=40)[0]
    assert (row["score"], row["hits"], row["dog_hits"]) == (30, 20, 2)
    # stored and handed back, and nothing here ranks on it yet
    assert row["crosshair"] == 1


def test_the_record_and_the_players_own_board_agree(conn):
    put(conn, "Ann", score=32, hits=20, shots=36, uuid="ann")
    put(conn, "Bob", score=44, hits=24, shots=26, uuid="bob")
    assert store.stats(conn, ducks=40)["record"]["name"] == "Bob"
    assert store.player(conn, "Bob", ducks=40)["best"]["score"] == 44


# --- a personal best is a better score -----------------------------------

def test_a_better_score_with_fewer_ducks_is_an_improvement(conn):
    put(conn, "Ann", score=30, hits=25, shots=45, uuid="sprayed")
    answer = put(conn, "Ann", score=38, hits=20, shots=21, uuid="aimed")
    assert answer["previous_best"] == 30
    assert answer["personal_best"] == 38
    assert answer["improved"] is True


def test_more_ducks_for_a_worse_score_is_not_an_improvement(conn):
    put(conn, "Ann", score=38, hits=20, shots=21, uuid="aimed")
    answer = put(conn, "Ann", score=30, hits=25, shots=45, uuid="sprayed")
    assert answer["improved"] is False
    assert answer["personal_best"] == 38


def test_the_world_record_is_the_best_score(conn):
    put(conn, "Ann", score=32, hits=30, shots=40, uuid="ann")
    answer = put(conn, "Bob", score=44, hits=24, shots=26, uuid="bob")
    assert answer["world_record"] == {"name": "Bob", "score": 44, "hits": 24}


# --- the migration --------------------------------------------------------

def old_database(path: str) -> None:
    """A database as it was before the score, with one round already in it."""
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        """INSERT INTO runs (run_uuid, player_key, name, hits, shots, ducks,
                             accuracy, duration, started_at, finished_at,
                             client_id)
           VALUES ('old-round-1', 'eugene', 'Eugene', 31, 40, 40, 77.5, 61.0,
                   '2026-09-12T19:01:00+00:00', '2026-09-12T19:02:44+00:00',
                   'eugene-mac')""")
    conn.commit()
    conn.close()


def columns(path: str) -> set[str]:
    with store.session(path) as conn:
        return {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}


def indexes(path: str) -> dict[str, str]:
    with store.session(path) as conn:
        return {r["name"]: r["sql"] or "" for r in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index'")}


def test_the_migration_adds_the_columns_to_a_table_that_has_rows(tmp_path):
    path = str(tmp_path / "old.db")
    old_database(path)
    assert "score" not in columns(path)
    store.init(path)
    assert {"score", "dog_hits", "crosshair"} <= columns(path)


def test_an_old_row_keeps_its_place_because_its_score_was_its_hits(tmp_path):
    # It was shot when a duck was one point and nothing cost anything, so 31
    # ducks was 31 points. Not a guess: the old rule, applied to an old row.
    path = str(tmp_path / "old.db")
    old_database(path)
    store.init(path)
    with store.session(path) as conn:
        row = conn.execute("SELECT hits, score, dog_hits, crosshair "
                           "FROM runs").fetchone()
        assert (row["hits"], row["score"]) == (31, 31)
        assert (row["dog_hits"], row["crosshair"]) == (0, 0)
        assert store.board(conn, ducks=40)[0]["score"] == 31


def test_the_indexes_that_rank_by_hits_are_gone(tmp_path):
    path = str(tmp_path / "old.db")
    old_database(path)
    assert "runs_board" in indexes(path)
    store.init(path)
    after = indexes(path)
    assert "runs_board" not in after and "runs_player" not in after
    assert "score DESC" in after["runs_board_v2"]
    assert "score DESC" in after["runs_player_v2"]


def test_a_real_score_survives_a_later_init(tmp_path):
    # the backfill runs once, when the column appears — a round somebody
    # actually shot for -12 points must not be quietly turned into its hit count
    path = str(tmp_path / "old.db")
    old_database(path)
    store.init(path)
    with store.session(path) as conn:
        put(conn, "Ann", score=-12, hits=4, shots=40)
    store.init(path)
    with store.session(path) as conn:
        assert conn.execute("SELECT score FROM runs WHERE player_key = 'ann'"
                            ).fetchone()["score"] == -12


def test_init_twice_changes_nothing(tmp_path):
    path = str(tmp_path / "fresh.db")
    store.init(path)
    with store.session(path) as conn:
        put(conn, "Ann", score=30, hits=20, shots=34)
    before = (indexes(path), columns(path))
    store.init(path)
    assert (indexes(path), columns(path)) == before
    with store.session(path) as conn:
        assert store.board(conn, ducks=40)[0]["score"] == 30


def test_the_migration_is_idempotent_on_an_old_database(tmp_path):
    path = str(tmp_path / "old.db")
    old_database(path)
    store.init(path)
    before = (indexes(path), columns(path))
    store.init(path)
    store.init(path)
    assert (indexes(path), columns(path)) == before


# --- validation, and the client that has not been updated yet -------------

def test_validate_fills_the_score_in_for_an_old_client():
    body = {"run_uuid": "3f2c4d5e", "name": "Eugene", "hits": 31, "shots": 40,
            "ducks": 40, "duration": 61.0,
            "started_at": "2026-09-12T19:01:00Z",
            "finished_at": "2026-09-12T19:02:44Z"}
    run = server.validate(body)
    # the old rule again: no score posted means a duck was a point
    assert run["score"] == 31
    assert run["dog_hits"] == 0 and run["crosshair"] is False


def test_validate_keeps_a_negative_score_as_sent():
    body = {"run_uuid": "3f2c4d5e", "name": "Eugene", "hits": 3, "shots": 40,
            "ducks": 40, "score": -28, "dog_hits": 1, "crosshair": True,
            "duration": 61.0, "started_at": "2026-09-12T19:01:00Z",
            "finished_at": "2026-09-12T19:02:44Z"}
    run = server.validate(body)
    assert run["score"] == -28
    assert run["dog_hits"] == 1 and run["crosshair"] is True


def test_validate_refuses_more_dog_hits_than_shots():
    body = {"run_uuid": "3f2c4d5e", "name": "Eugene", "hits": 3, "shots": 4,
            "ducks": 40, "score": -8, "dog_hits": 5, "duration": 61.0,
            "started_at": "2026-09-12T19:01:00Z",
            "finished_at": "2026-09-12T19:02:44Z"}
    with pytest.raises(server.Rejected):
        server.validate(body)


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


def post(url, body: dict) -> tuple[int, dict]:
    """The POST the game makes, and whatever came back — a 4xx included."""
    req = urllib.request.Request(
        f"{url}/api/runs", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get(url, path) -> dict:
    with urllib.request.urlopen(f"{url}{path}", timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def round_body(**kw) -> dict:
    body = {"run_uuid": "3f2c4d5e6f", "name": "Eugene", "hits": 31, "shots": 40,
            "ducks": 40, "duration": 61.0,
            "started_at": "2026-09-12T19:01:00Z",
            "finished_at": "2026-09-12T19:02:44Z", "client_id": "test"}
    body.update(kw)
    return body


def test_a_post_without_the_score_is_still_accepted(url):
    # the cabinet in the other room has not been updated; a 400 here would lose
    # an evening of rounds for a field it does not know about yet
    code, body = post(url, round_body())
    assert code == 200 and body["ok"] is True
    assert get(url, "/api/board?ducks=40")["rows"][0]["score"] == 31


def test_a_negative_score_is_stored_as_it_was_sent(url):
    code, body = post(url, round_body(hits=3, score=-28, dog_hits=1,
                                      crosshair=True))
    assert code == 200
    row = get(url, "/api/board?ducks=40")["rows"][0]
    assert (row["score"], row["hits"], row["dog_hits"]) == (-28, 3, 1)
    assert row["crosshair"] == 1


def test_more_dog_hits_than_shots_is_a_400(url):
    code, body = post(url, round_body(shots=4, hits=3, dog_hits=5))
    assert code == 400 and "dog_hits" in body["error"]
    assert get(url, "/api/board?ducks=40")["rows"] == []


def test_the_route_ranks_what_it_stored_by_score(url):
    post(url, round_body(run_uuid="aaaaaaaa", name="Ann", hits=20, shots=36,
                         score=32))
    post(url, round_body(run_uuid="bbbbbbbb", name="Bob", hits=24, shots=26,
                         score=44))
    rows = get(url, "/api/board?ducks=40")["rows"]
    assert [r["name"] for r in rows] == ["Bob", "Ann"]


# --- the port is open on the LAN, so the numbers have to be plausible --------

def test_an_absurd_score_is_refused(url):
    """`score DESC` leads every ranking and nothing rewrites a stored score.

    One hand-made POST of 10^15 would otherwise own the board, the ticker and
    every record shout for good. There is no exact bound to be had — the points
    table lives in the game's settings — but there is an obvious insane one.
    """
    body = dict(scored_row("Vandal", hits=1, shots=1, ducks=40, uuid="a" * 32), score=10 ** 15)
    code, answer = post(url, body)
    assert code == 400 and "plausible" in answer["error"]


def test_a_negative_score_is_still_fine(url):
    body = dict(scored_row("Unlucky", hits=0, shots=40, ducks=40, uuid="b" * 32), score=-40)
    code, answer = post(url, body)
    assert code == 200 and answer["score"] == -40


def test_a_round_cannot_have_hit_a_duck_and_the_dog_with_one_shot(url):
    # both cost a shot, so the real invariant is hits + dog_hits <= shots
    body = dict(scored_row("Impossible", hits=1, shots=1, ducks=40, uuid="c" * 32), dog_hits=1)
    code, answer = post(url, body)
    assert code == 400 and "dog_hits" in answer["error"]


def test_a_session_closes_its_connection(db):
    # sqlite3's own `with` leaves the file open; the board polling every few
    # seconds ran the server out of file descriptors that way
    with store.session(db) as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
