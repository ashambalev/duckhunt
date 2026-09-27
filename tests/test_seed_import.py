"""`--from-scores`: an old `scores.json` becomes rows on the board.

The module that used to write that file is gone, so this reader is the only thing
left that understands the old shape — which is exactly why it is worth a test. The
files it reads are real evenings somebody played, and the point of the import is
that they are not thrown away for being in the old shape.
"""

from __future__ import annotations

import json

from leaderboard import seed, store


def write(tmp_path, rows):
    path = tmp_path / "scores.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return str(path)


OLD = [{"name": "eugene", "hits": 66, "shots": 100, "ducks": 100,
        "date": "2026-09-02"},
       {"name": "Женя", "hits": 58, "shots": 78, "ducks": 100,
        "date": "2026-09-12"}]


def test_an_old_table_lands_on_the_board(conn, tmp_path):
    assert seed.from_scores(conn, write(tmp_path, OLD)) == 2
    rows = store.board(conn, ducks=100, limit=10)
    assert [(r["name"], r["score"], r["hits"]) for r in rows] == [
        ("eugene", 66, 66), ("Женя", 58, 58)]


def test_the_score_is_the_hit_count_because_that_was_the_rule_then(conn, tmp_path):
    # played when a duck was worth one point and neither a miss nor the dog cost
    # anything — so the hit count IS the score of such a round, not a guess. The
    # dog and the crosshair were not recorded at all, and must not be invented.
    seed.from_scores(conn, write(tmp_path, OLD))
    row = conn.execute("SELECT score, hits, dog_hits, crosshair FROM runs "
                       "WHERE name = 'eugene'").fetchone()
    assert (row["score"], row["hits"]) == (66, 66)
    assert (row["dog_hits"], row["crosshair"]) == (0, 0)


def test_importing_twice_does_not_double_the_board(conn, tmp_path):
    path = write(tmp_path, OLD)
    assert seed.from_scores(conn, path) == 2
    assert seed.from_scores(conn, path) == 0
    assert len(store.board(conn, ducks=100, limit=10)) == 2


def test_a_missing_file_imports_nothing_and_does_not_raise(conn, tmp_path):
    assert seed.from_scores(conn, str(tmp_path / "nope.json")) == 0


def test_a_broken_file_imports_nothing_and_does_not_raise(conn, tmp_path):
    path = tmp_path / "scores.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert seed.from_scores(conn, str(path)) == 0


def test_a_bad_row_is_skipped_and_the_good_ones_still_arrive(conn, tmp_path):
    rows = [{"name": "Anna", "hits": 10, "shots": 20, "ducks": 40,
             "date": "2026-09-01"},
            {"name": "no hits here", "shots": 20, "ducks": 40,
             "date": "2026-09-01"},
            {"name": "Boris", "hits": "seven", "shots": 20, "ducks": 40,
             "date": "2026-09-01"}]
    assert seed.from_scores(conn, write(tmp_path, rows)) == 1
    assert store.board(conn, ducks=40)[0]["name"] == "Anna"
