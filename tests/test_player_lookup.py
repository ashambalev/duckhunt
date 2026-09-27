"""`PlayerLookup` — the client side of the name search.

The one thing that must always hold: the name screen never waits. So every test
here calls `ask()` and `rows()` the way the draw loop does and checks that the
answer turns up on its own — including when there is no server at all.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import pytest

from duckhunt.net import leaderboard_client as lc
from leaderboard import server


@dataclass
class Board:
    """Stands in for `settings.leaderboard`."""
    url: str
    enabled: bool = True
    client_id: str = "test"
    timeout: float = 2.0
    token: str = ""


@pytest.fixture()
def url(db):
    httpd = server.build("127.0.0.1", 0, db)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def settle(lookup, want, timeout=3.0):
    """Poll `rows()` the way a draw loop would, up to `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if lookup.asked() == want:
            return lookup.rows()
        time.sleep(0.02)
    return None


def test_a_typed_name_comes_back_with_its_best_and_its_tries(url, add):
    add("Женя", hits=66, ducks=40, uuid="a")
    add("Женя", hits=30, ducks=40, uuid="b")
    look = lc.PlayerLookup(Board(url))
    look.ask("жен")
    rows = settle(look, "жен")
    look.close()
    assert rows is not None, "the lookup never answered"
    assert rows[0]["name"] == "Женя"
    assert rows[0]["hits"] == 66 and rows[0]["attempts"] == 2
    assert rows[0]["ducks"] == 40


def test_an_empty_buffer_asks_for_the_regulars(url, add):
    add("Anna")
    look = lc.PlayerLookup(Board(url))
    look.ask("")
    rows = settle(look, "")
    look.close()
    assert rows and rows[0]["name"] == "Anna"


def test_only_the_latest_question_is_answered(url, add):
    add("Anna")
    add("Boris")
    look = lc.PlayerLookup(Board(url))
    for text in ("a", "an", "b", "bo"):        # a fast typist, one frame apart
        look.ask(text)
        time.sleep(0.01)
    rows = settle(look, "bo")
    look.close()
    assert rows and rows[0]["name"] == "Boris"
    assert look.asked() == "bo"


def test_a_board_that_is_off_is_never_asked():
    look = lc.PlayerLookup(Board("http://127.0.0.1:1", enabled=False))
    look.ask("anything")
    assert look.rows() == [] and look.asked() is None
    assert look._thread is None                # nothing was even started


def test_a_dead_board_answers_nothing_and_does_not_raise():
    # port 1: refused at once, so this is the "server is down" path, fast
    look = lc.PlayerLookup(Board("http://127.0.0.1:1", timeout=0.3))
    look.ask("anna")
    rows = settle(look, "anna", timeout=3.0)
    look.close()
    assert rows == []


def test_asking_the_same_text_twice_does_not_re_ask(url, add):
    add("Anna")
    look = lc.PlayerLookup(Board(url))
    look.ask("anna")
    assert settle(look, "anna") is not None
    look.ask("anna")
    look.close()
    assert look._wanted is None
