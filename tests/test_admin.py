"""The staff tool: rename, merge and delete — and that each one can be undone.

What matters at a booth is not only that a rude name can be taken off the board,
but that a slip of the hand while doing it costs nothing: every change is undone
row for row, and the rounds played in between stay where they are.
"""

from __future__ import annotations

import json
import os

import pytest

from leaderboard import admin as admin_mod, store
from leaderboard.admin import Admin, AdminError


@pytest.fixture()
def admin(db, add):
    a = Admin(db)
    yield a
    a.close()


def names(admin):
    return sorted(p["name"] for p in admin.players())


def test_a_missing_database_is_an_error_not_an_empty_board(tmp_path):
    with pytest.raises(AdminError):
        Admin(str(tmp_path / "nope.db"))


def test_players_fold_case_and_carry_their_best_per_round_size(admin, add):
    add("Женя", hits=30, ducks=40)
    add("женя", hits=50, ducks=100, uuid="b")
    add("Eugene", hits=10)
    [p] = admin.players("ЖЕН")
    assert p["name"] == "Женя" and p["rounds"] == 2
    assert p["best"] == {40: 30, 100: 50}


def test_rename_moves_every_round_and_the_key(admin, add):
    add("Zhneya", hits=12)
    add("Zhneya", hits=20, uuid="b")
    assert admin.rename("zhneya", "  Zhenya  ") == 2
    assert names(admin) == ["Zhenya"]
    assert store.board(admin.conn, ducks=40)[0]["attempts"] == 2


def test_rename_onto_a_taken_name_is_a_merge_under_one_spelling(admin, add):
    add("Zhenya", hits=12)
    add("Женя", hits=30, uuid="b")
    admin.rename("Zhenya", "Женя")
    [p] = admin.players()
    assert p["name"] == "Женя" and p["rounds"] == 2
    assert {r["name"] for r in admin.runs()} == {"Женя"}


def test_merge_keeps_the_target_spelling(admin, add):
    add("Женя", hits=30)
    add("Zhenya", hits=12, uuid="b")
    add("zhenia", hits=5, uuid="c")
    assert admin.merge(["zhenya", "ZHENIA"], into="женя") == 3
    [p] = admin.players()
    assert p["name"] == "Женя" and p["rounds"] == 3


def test_merge_refuses_names_that_are_not_there(admin, add):
    add("Женя")
    with pytest.raises(AdminError):
        admin.merge(["ghost"], into="Женя")
    with pytest.raises(AdminError):
        admin.merge(["женя"], into="Женя")      # one player already


def test_rename_refuses_an_empty_or_overlong_name(admin, add):
    add("Eugene")
    for bad in ("   ", "x" * (store.NAME_MAX + 1)):
        with pytest.raises(AdminError):
            admin.rename("Eugene", bad)


def test_delete_player_and_delete_run(admin, add):
    add("rude", hits=1)
    add("rude", hits=2, uuid="b")
    add("Eugene", hits=3)
    assert admin.delete_player("RUDE") == 2
    assert names(admin) == ["Eugene"]
    [r] = admin.runs()
    assert admin.delete_runs([r["id"]]) == 1
    assert admin.players() == []


def test_undo_puts_back_a_delete_and_keeps_rounds_played_since(admin, add):
    add("Eugene", hits=33)
    admin.delete_player("Eugene")
    add("Newcomer", hits=5)                  # the queue did not stop
    assert "delete" in admin.undo()
    assert names(admin) == ["Eugene", "Newcomer"]
    assert store.board(admin.conn, ducks=40)[0]["score"] == 33


def test_undo_reverses_a_merge_into_both_original_spellings(admin, add):
    add("Женя", hits=30)
    add("Zhenya", hits=12, uuid="b")
    admin.merge(["Zhenya"], into="Женя")
    admin.undo()
    assert names(admin) == ["Zhenya", "Женя"]


def test_undo_goes_back_one_change_at_a_time_and_then_stops(admin, add):
    add("a")
    admin.rename("a", "b")
    admin.rename("b", "c")
    admin.undo()
    assert names(admin) == ["b"]
    admin.undo()
    assert names(admin) == ["a"]
    with pytest.raises(AdminError):
        admin.undo()
    assert [e["undone"] for e in admin.history() if "rows" in e] == [True, True]


def test_every_change_leaves_a_backup_and_only_the_last_few_are_kept(
        admin, add, monkeypatch):
    monkeypatch.setattr(admin_mod, "BACKUPS_KEEP", 2)
    add("a")
    for new in ("b", "c", "d"):
        admin.rename(names(admin)[0], new)
    kept = os.listdir(admin.backups)
    assert len(kept) == 2


def test_queued_rounds_under_a_name_are_counted(admin, add):
    with open(admin.pending, "w", encoding="utf-8") as f:
        f.write(json.dumps({"name": "Rude "}) + "\n")
        f.write("not json\n")
        f.write(json.dumps({"name": "other"}) + "\n")
    assert admin.queued("rude") == 1


def test_the_cli_renames_and_lists(db, add, capsys):
    add("Zhneya", hits=7)
    assert admin_mod.main(["--db", db, "rename", "Zhneya", "Zhenya"]) == 0
    assert admin_mod.main(["--db", db, "players"]) == 0
    out = capsys.readouterr().out
    assert "Zhenya" in out and "7 (40)" in out


def test_the_cli_reports_an_unknown_player_without_a_traceback(db, capsys):
    assert admin_mod.main(["--db", db, "delete", "ghost", "-y"]) == 1
    assert "no player" in capsys.readouterr().err


def test_the_cli_asks_before_a_merge_and_no_means_no(db, add, monkeypatch, capsys):
    add("Женя", hits=30)
    add("Zhenya", hits=12, uuid="b")
    monkeypatch.setattr("builtins.input", lambda q: "n")
    assert admin_mod.main(["--db", db, "merge", "Zhenya", "--into", "Женя"]) == 1
    monkeypatch.setattr("builtins.input", lambda q: "y")
    assert admin_mod.main(["--db", db, "merge", "Zhenya", "--into", "Женя"]) == 0
    assert "1 player(s)" in (admin_mod.main(["--db", db, "players"]),
                             capsys.readouterr().out)[1]


def test_the_cli_asks_before_a_delete_and_no_means_no(db, add, monkeypatch):
    add("rude")
    monkeypatch.setattr("builtins.input", lambda q: "")
    assert admin_mod.main(["--db", db, "delete", "rude"]) == 1
    assert admin_mod.main(["--db", db, "delete-run", "1"]) == 1
    a = Admin(db)
    assert len(a.players()) == 1
    a.close()
