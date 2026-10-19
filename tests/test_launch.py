"""./play's memory: a screen picked last time is found again after SDL has
renumbered the screens, and the picks survive the trip through launch.json."""

from dataclasses import replace

from duckhunt.outputs import (Screen, find_screen, load_picks, remember,
                              save_picks)
from launch import Row

LAPTOP = Screen(0, "Built-in Retina Display", 0, 0, 1470, 956, "1552:41216:0")
MONITOR = Screen(1, "LG HDR 4K", 1470, 0, 2560, 1440, "7789:30471:197701")
TV = Screen(2, "SAMSUNG", -1920, 0, 1920, 1080, "19501:3955:16777217")


def test_the_same_monitor_is_found_under_its_new_number():
    saved = remember(MONITOR)
    today = [replace(MONITOR, index=0), replace(LAPTOP, index=1)]
    assert find_screen(saved, today).index == 0


def test_by_name_when_the_serial_is_unknown():
    saved = {"key": "", "name": "SAMSUNG", "index": 5}
    assert find_screen(saved, [LAPTOP, TV]) is TV


def test_two_of_the_same_model_fall_back_to_the_number():
    twin = Screen(1, TV.name, 0, 0, 1920, 1080, "")
    saved = {"key": "gone", "name": TV.name, "index": 2}
    assert find_screen(saved, [LAPTOP, twin, TV]) is TV


def test_nothing_to_go_on_is_none():
    assert find_screen(None, [LAPTOP]) is None
    assert find_screen({"key": "x", "name": "y", "index": 9}, [LAPTOP]) is None


def test_picks_round_trip(tmp_path):
    path = str(tmp_path / "launch.json")
    picks = {"game_screen": remember(MONITOR), "audio": "LG TV (HDMI)",
             "board_screen": None, "gun": "/dev/tty.usbserial-0001"}
    save_picks(picks, path)
    assert load_picks(path) == picks


def test_a_missing_or_broken_file_is_a_first_evening(tmp_path):
    assert load_picks(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_picks(str(bad)) == {}


def test_a_row_selects_what_was_saved_and_wraps():
    r = Row("Game sound", [("system default", ""), ("TV", "TV"), ("Mac", "Mac")])
    r.select("Mac")
    assert r.value == "Mac"
    r.step(+1)
    assert r.value == ""
    r.select("unplugged since")
    assert r.value == ""


def test_play_takes_the_saved_screens_without_asking(monkeypatch):
    import launch
    monkeypatch.setattr(launch.outputs, "screens", lambda pg: [LAPTOP, MONITOR])
    monkeypatch.setattr(launch.outputs, "gun_ports",
                        lambda: ["/dev/tty.usbserial-0001"])
    saved = {"game_screen": remember(MONITOR), "audio": "TV",
             "board_screen": remember(LAPTOP), "gun": "/dev/tty.usbserial-0001"}
    picks, game, board = launch.resolve(saved)
    assert (game, board) == (MONITOR, LAPTOP)
    assert picks["gun"] == "/dev/tty.usbserial-0001"


def test_play_falls_back_when_the_room_changed(monkeypatch):
    import launch
    monkeypatch.setattr(launch.outputs, "screens", lambda pg: [LAPTOP])
    monkeypatch.setattr(launch.outputs, "gun_ports", lambda: [])
    saved = {"game_screen": remember(TV), "audio": "",
             "board_screen": remember(MONITOR), "gun": "/dev/tty.usbserial-0001"}
    picks, game, board = launch.resolve(saved)
    assert game == LAPTOP and board is None
    assert picks["gun"] == launch.MOUSE
