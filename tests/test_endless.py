"""The endless round: no end, a clip to reload, a combo, and never the board."""

from __future__ import annotations

from dataclasses import replace

from duckhunt.core import modes
from duckhunt.core.config import Settings
from duckhunt.core.models import DuckState
from duckhunt.core.world import World
from duckhunt.net.leaderboard_client import NOT_ENDLESS, refusal

AWAY = (0.99, 0.01)


def make(clip=10, reload=1.0, endless=True, ducks=3, ammo=0):
    base = Settings()
    s = replace(base, round=replace(base.round, endless=endless, clip=clip,
                                    reload=reload, ducks=ducks, ammo=ammo,
                                    interval=0.5, speedup=1.0, scored=False))
    return World(seed=1, settings=s)


def put_duck(w, x=0.5, y=0.4):
    w.spawn()
    d = w.ducks[-1]
    d.x, d.y, d.vx, d.vy, d.state = x, y, 0.0, 0.0, DuckState.FLYING
    return d


def shoot(w, d=None):
    at = (d.x + d.w / 2, d.y + d.h / 2) if d else AWAY
    w.update(0.001, *at, True)


def test_endless_never_finishes_on_its_own():
    w = make(ducks=3)
    for _ in range(200):
        w.update(0.1, *AWAY, False)
    assert w.released > 3 and not w.finished
    w.stop()
    assert w.finished


def test_the_clip_empties_and_a_dry_pull_is_not_a_shot():
    w = make(clip=3)
    for _ in range(3):
        shoot(w)
    assert (w.clip, w.shots, w.loaded) == (0, 3, False)
    shoot(w)                                   # click: starts the reload
    assert w.shots == 3 and w.reloading > 0


def test_a_reload_takes_its_time_and_fills_the_clip():
    w = make(clip=2, reload=1.0)
    shoot(w)
    w.reload()
    shoot(w)                                   # mid-reload: nothing happens
    assert w.shots == 1
    w.update(0.6, *AWAY, False)
    assert not w.loaded
    w.update(0.6, *AWAY, False)
    assert (w.clip, w.loaded) == (2, True)


def test_a_full_clip_does_not_reload():
    w = make(clip=2)
    w.reload()
    assert w.reloading == 0


def test_no_clip_means_no_reloading():
    w = make(clip=0, endless=False)
    for _ in range(50):
        shoot(w)
    assert w.shots == 50 and w.clip == -1 and w.loaded


def test_the_combo_counts_hits_in_a_row_and_a_miss_breaks_it():
    w = make(clip=0)
    for _ in range(3):
        shoot(w, put_duck(w))
    assert (w.combo, w.best_combo) == (3, 3)
    shoot(w)
    assert (w.combo, w.best_combo) == (0, 3)
    shoot(w, put_duck(w))
    assert (w.combo, w.best_combo) == (1, 3)


def test_an_endless_round_is_never_for_the_board():
    w = make()
    shoot(w)
    assert refusal(w, w.settings) == NOT_ENDLESS
    s = replace(w.settings, round=replace(w.settings.round, scored=True))
    assert refusal(w, s) == NOT_ENDLESS


def test_the_endless_mode_file():
    found = {m.key: m for m in modes.load_all()}
    m = found["endless"]
    base = found["scored"].settings
    r = m.settings.round
    assert (r.endless, r.scored, r.clip, r.dog_laughs) == (True, False, 10, False)
    assert m.settings.gun.crosshair == "off"
    # the same ducks as the scored round
    assert m.settings.duck == base.duck
