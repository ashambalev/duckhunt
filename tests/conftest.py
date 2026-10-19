"""Shared fixtures: a throwaway leaderboard database with rows in it.

The tests never touch the real `leaderboard.db` — every one of them gets an
empty file in a tmp dir, which is also why they can run while an evening's
board is up.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leaderboard import store                             # noqa: E402


@pytest.fixture()
def db(tmp_path):
    """Path to an initialised, empty database."""
    path = str(tmp_path / "test.db")
    store.init(path)
    return path


@pytest.fixture()
def conn(db):
    with store.session(db) as c:
        yield c


def run_row(name, hits=10, shots=20, ducks=40, uuid=None, finished_at=None):
    """A payload the way `server.validate` would have handed it over."""
    run_id = uuid or f"{name}-{hits}-{shots}-{ducks}-{finished_at or ''}"
    return {"run_uuid": run_id, "name": name, "hits": hits, "shots": shots,
            "ducks": ducks, "duration": 60.0,
            "started_at": "2026-09-26T18:00:00+00:00",
            "finished_at": finished_at or "2026-09-26T18:01:00+00:00",
            "client_id": "test", "input_source": "keyboard",
            "game_version": "test", "settings": None}


@pytest.fixture()
def add(conn):
    """`add("Женя", hits=30)` — one stored round, returning the server's answer."""
    def _add(name, **kw):
        return store.insert_run(conn, run_row(name, **kw))
    return _add
