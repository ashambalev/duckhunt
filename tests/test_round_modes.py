"""The scored round and the practice round: ammunition, penalties, the dog, pace.

Aiming in these tests is exact rather than realistic — a duck is put where the
test wants it and the crosshair is placed on it — because what is under test is
what a shot *costs*, not whether the hit detection works (`Duck.distance_to`
covers that itself).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from duckhunt.core.config import Settings
from duckhunt.core.models import DuckState
from duckhunt.core.world import World

AWAY = (0.99, 0.01)        # a corner no duck of these tests is ever in


def make(ducks=40, ammo=0, max_alive=0, duck=2, miss=-1, dog=-5, interval=0.5,
         scored=True, **duck_kw):
    """A world with the settings a test cares about and defaults for the rest."""
    base = Settings()
    s = replace(
        base,
        round=replace(base.round, ducks=ducks, ammo=ammo, interval=interval,
                      speedup=1.0, scored=scored),
        score=replace(base.score, duck=duck, miss=miss, dog=dog),
        duck=replace(base.duck, max_alive=max_alive, **duck_kw),
    )
    return World(seed=1, settings=s)


def aim_at(d):
    """The middle of a duck's hitbox."""
    return d.x + d.w / 2, d.y + d.h / 2


def put_duck(w, x=0.5, y=0.4):
    """One duck, exactly where the test wants it, flying."""
    w.spawn()
    d = w.ducks[-1]
    d.x, d.y, d.vx, d.vy, d.state = x, y, 0.0, 0.0, DuckState.FLYING
    return d


# --- what a shot is worth --------------------------------------------------

def test_a_duck_is_worth_what_the_settings_say():
    w = make(duck=2)
    d = put_duck(w)
    w.update(0.016, *aim_at(d), True)
    assert (w.hits, w.score, w.dog_hits) == (1, 2, 0)


def test_a_miss_costs_a_point():
    w = make(miss=-1)
    put_duck(w)
    w.update(0.016, *AWAY, True)
    assert (w.shots, w.hits, w.score) == (1, 0, -1)


def test_the_score_may_go_negative_and_is_not_clamped():
    w = make(miss=-1)
    for _ in range(5):
        w.update(0.016, *AWAY, True)
    assert w.score == -5


def test_the_dog_costs_five_and_is_counted_apart():
    w = make(dog=-5)
    box = (0.4, 0.8, 0.6, 1.0)
    w.update(0.016, 0.5, 0.9, True, box)
    assert (w.dog_hits, w.score, w.hits) == (1, -5, 0)


def test_hitting_the_dog_is_not_also_a_miss():
    # the dog's own penalty replaces the miss, it does not stack on top of it
    w = make(miss=-1, dog=-5)
    w.update(0.016, 0.5, 0.9, True, (0.4, 0.8, 0.6, 1.0))
    assert w.score == -5


def test_a_duck_in_range_beats_the_dog_behind_it():
    w = make(duck=2, dog=-5)
    d = put_duck(w, x=0.45, y=0.85)
    w.update(0.016, *aim_at(d), True, (0.0, 0.8, 1.0, 1.0))
    assert (w.hits, w.dog_hits, w.score) == (1, 0, 2)


def test_the_dog_is_only_there_on_the_frames_he_is_up():
    w = make(miss=-1, dog=-5)
    w.update(0.016, 0.5, 0.9, True, None)      # he is off screen: a plain miss
    assert (w.dog_hits, w.score) == (0, -1)


# --- the magazine ----------------------------------------------------------

def test_ammunition_is_not_counted_when_it_is_zero():
    w = make(ammo=0)
    assert w.ammo == -1 and w.dry is False
    for _ in range(50):
        w.update(0.016, *AWAY, True)
    assert w.shots == 50 and w.dry is False


def test_the_magazine_empties_and_further_shots_do_not_count():
    w = make(ammo=3, miss=-1)
    for _ in range(5):
        w.update(0.016, *AWAY, True)
    assert (w.shots, w.ammo, w.score) == (3, 0, -3)
    assert w.dry is True


def test_the_shot_that_empties_the_magazine_still_counts():
    w = make(ammo=1, duck=2)
    d = put_duck(w)
    w.update(0.016, *aim_at(d), True)
    assert (w.hits, w.score, w.dry) == (1, 2, True)


def test_a_dry_round_is_not_over_while_a_duck_is_still_falling():
    w = make(ducks=40, ammo=1, duck=2)
    d = put_duck(w)
    w.update(0.016, *aim_at(d), True)
    assert d.state is DuckState.FALLING
    assert w.finished is False, "the duck it just downed has not landed yet"
    for _ in range(400):                        # let it fall out of the picture
        w.update(0.016, *AWAY, False)
        if w.finished:
            break
    assert w.finished is True and w.landed == 1


def test_a_dry_magazine_launches_no_more_ducks():
    w = make(ducks=40, ammo=1, interval=0.1)
    w.update(0.016, *AWAY, True)                # one shot, one empty magazine
    released = w.released
    for _ in range(60):
        w.update(0.016, *AWAY, False)
    assert w.released == released, "ducks kept coming with nothing to shoot them with"


def test_the_flock_still_ends_a_round_before_the_magazine_does():
    w = make(ducks=2, ammo=99, interval=0.05)
    for _ in range(600):
        w.update(0.016, *AWAY, False)
        if w.finished:
            break
    assert w.finished and w.released == 2 and not w.dry


# --- one duck at a time ----------------------------------------------------

def test_max_alive_holds_the_next_duck_back():
    w = make(ducks=10, max_alive=1, interval=0.1)
    for _ in range(120):                        # two seconds, twenty intervals
        w.update(0.016, *AWAY, False)
        assert len(w.ducks) <= 1, "two ducks in the air in a one-at-a-time round"


def test_the_held_back_duck_goes_up_as_soon_as_there_is_room():
    # the pace is a timer, so a duck held back must not then owe a whole interval
    # once the sky clears — it has already waited, out there, for its turn
    w = make(ducks=10, max_alive=1, interval=0.4)
    while not w.ducks:
        w.update(0.016, *AWAY, False)
    released = w.released
    for _ in range(40):                         # the next one's turn comes and goes
        w.update(0.016, *AWAY, False)
    assert w.released == released, "the cap let a second duck up"
    w.ducks.clear()                             # as if it had left the picture
    w.update(0.016, *AWAY, False)
    assert w.released == released + 1


def test_no_cap_means_as_many_as_the_pace_launches():
    w = make(ducks=10, max_alive=0, interval=0.1)
    for _ in range(120):
        w.update(0.016, *AWAY, False)
    assert len(w.ducks) > 1


def test_crowded_counts_a_falling_duck_too():
    w = make(max_alive=1)
    d = put_duck(w)
    d.state = DuckState.FALLING
    assert w.crowded is True


# --- a record is shot down the sights ---------------------------------------

def test_a_round_starts_out_having_used_no_crosshair():
    assert make().crosshair_used is False


def test_the_crosshair_is_latched_not_sampled():
    # turning it off before the last duck must not launder the round
    w = make()
    w.update(0.016, *AWAY, False, None, True)
    for _ in range(10):
        w.update(0.016, *AWAY, False, None, False)
    assert w.crosshair_used is True


# --- a mode is a file laid over the settings, not instead of them -----------

def test_practice_inherits_the_hardware_it_does_not_name():
    """The one thing `--practice` must never do is un-aim the gun.

    `config.load()` reads a single file and fills every unnamed key from the
    dataclass defaults, so a mode file used *instead of* settings.toml would quietly
    revert the sight-in, the beacon rectangle and the lead — measured on one gun,
    on one screen, over three evenings — and hand a first-timer the one gun in the
    house that is not pointed at anything. It is an overlay for that reason.
    """
    from duckhunt.core.config import load

    base = load()
    practice = load(overlay="practice.toml")
    # the round is a different round
    assert (practice.round.ducks, practice.round.scored) == (10, False)
    assert practice.duck.max_alive == 1
    # ... and the gun is the same gun, crosshair aside
    changed = {k for k in base.gun.__dict__
               if getattr(base.gun, k) != getattr(practice.gun, k)}
    assert changed == {"crosshair"}
    assert practice.sound == base.sound and practice.score == base.score


def test_an_overlay_that_is_missing_leaves_the_settings_alone():
    from duckhunt.core.config import load

    assert load(overlay="no-such-mode.toml").round == load().round


# --- running out is not the same as shooting badly -------------------------

def test_a_perfect_round_is_dry_without_having_been_cut_short():
    # One shot per duck, every shot a hit: the last one empties the magazine on the
    # last duck, so `dry` is true and yet nothing was taken away — the results
    # screen must not tell that player they ran out
    w = make(ducks=3, ammo=3, interval=0.2, duck=2)
    for _ in range(400):
        flying = [d for d in w.ducks if d.state is DuckState.FLYING]
        if flying:
            w.update(0.016, *aim_at(flying[0]), True)
        else:
            w.update(0.016, *AWAY, False)
        if w.finished:
            break
    assert (w.hits, w.shots, w.score) == (3, 3, 6)
    assert w.dry is True
    assert w.released == w.total, "the flock was fully let out"


def test_a_round_the_magazine_really_cut_short_says_so():
    w = make(ducks=40, ammo=2, interval=0.5)
    for _ in range(200):
        w.update(0.016, *AWAY, True)
        if w.finished:
            break
    assert w.dry and w.released < w.total


def test_practice_with_no_file_refuses_rather_than_playing_the_hard_round():
    """`--practice` must never quietly become the scored round.

    Falling back to the base settings would be the inverse of what the flag
    promises — forty ducks at full speed, a magazine to run out of, and the row
    posted as a record — handed to somebody who has never held the gun.
    """
    import main
    import pytest as _pytest

    class Args:
        settings = None
        practice = True

    real, main.PRACTICE_NAME = main.PRACTICE_NAME, "no-such-practice-file.toml"
    try:
        with _pytest.raises(SystemExit) as exit_info:
            main.practice_overlay(Args())
    finally:
        main.PRACTICE_NAME = real
    assert "no-such-practice-file.toml" in str(exit_info.value)
