"""Switching the round from inside the game: the title screen's own control.

Driven the same way `test_name_screen` drives the name screen — the real
`PygameFrontend.run()` loop, headless, with `pygame.event.get` scripted frame by
frame — because the loop keeps its mode in a local and hands out only two things
a test can read: `frontend.mode_index` and the world it built for that mode.

What matters here is that a switch really is a switch: the world the next round
will be played in is the new mode's (its flock, its magazine), the crosshair goes
back to what that mode asks for, and none of it is reachable from anywhere but
the title screen — a mode change mid-round would throw the round away, and one on
the result screen would rub out the result still being read.
"""

from __future__ import annotations

from dataclasses import replace

import pygame

from duckhunt.core.config import Settings
from duckhunt.core.modes import Mode
from duckhunt.frontends import pygame_app
from duckhunt.frontends.pygame_app import PygameFrontend
from duckhunt.input.base import AimState


def key(k, unicode="") -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=unicode)


M = key(pygame.K_m, "m")     # `.unicode` because the name screen types it
SPACE = key(pygame.K_SPACE)
ESC = key(pygame.K_ESCAPE)

A_BUTTON = 0x02          # the remote's A, as the firmware's bitmask reports it


def _settings(ducks=40, crosshair="off", ammo=0, countdown=3.0) -> Settings:
    """Real settings with no screen and no ears — see test_name_screen."""
    base = Settings()
    return replace(
        base,
        round=replace(base.round, ducks=ducks, ammo=ammo, countdown=countdown),
        gun=replace(base.gun, crosshair=crosshair),
        scene=replace(base.scene, fullscreen=False, background="none"),
        sound=replace(base.sound, enabled=False),
    )


SCORED = Mode("SCORED", "the whole flock", None, _settings(ducks=40))
PRACTICE = Mode("PRACTICE", "ten slow ducks", "practice.toml",
                _settings(ducks=10, crosshair="on"))
SUDDEN = Mode("SUDDEN DEATH", "one shot", "modes/sudden.toml",
              _settings(ducks=25, ammo=1))

# The same two with no countdown, for the tests that need the round to actually
# start inside a handful of frames: the crosshair is only judged from the first
# duck, so anything about it has to be watched in play rather than before it.
QUICK_SCORED = Mode("SCORED", "the whole flock", None,
                    _settings(ducks=40, countdown=0.0))
QUICK_PRACTICE = Mode("PRACTICE", "ten slow ducks", "practice.toml",
                      _settings(ducks=10, crosshair="on", countdown=0.0))


def run_scripted(monkeypatch, frames, events=None, gun_frames=None,
                 modes=(SCORED, PRACTICE), start=0, worlds=None):
    """Drive the loop for `frames` frames and hand back the frontend.

    `events` maps a frame index to that frame's events; `gun_frames` does the
    same for a fake gun's `poll()` — pass it to get the light gun path (which is
    the only one that can press A), leave it out for the mouse. `worlds` is
    appended with the world the frontend was built with, before the loop runs:
    the only way to tell "never switched" from "switched and came back round".
    """
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

    events = events or {}
    counter = [0]

    def fake_get():
        idx = counter[0]
        counter[0] += 1
        if idx >= frames:
            return [pygame.event.Event(pygame.QUIT)]
        return events.get(idx, [])

    monkeypatch.setattr(pygame.event, "get", fake_get)

    frontend = PygameFrontend(modes=list(modes), mode=start)
    if worlds is not None:
        worlds.append(frontend.world)

    source = None
    if gun_frames is not None:
        class _FakeGun:
            def poll(self):
                # the frame counter has already moved on by the time poll() is
                # reached, so the gun answers for the frame that just read events
                return gun_frames.get(counter[0] - 1, AimState())

            def close(self):
                pass

        source = _FakeGun()

    frontend.run(source)
    return frontend


# --- the switch itself ------------------------------------------------------

def test_m_on_the_title_screen_builds_the_next_mode_s_round(monkeypatch):
    game = run_scripted(monkeypatch, frames=3, events={0: [M]})
    assert game.mode_index == 1
    assert game.world.total == 10, "the world is still the scored round's"
    assert game.world.settings.round.ducks == 10


def test_the_list_comes_back_round_to_where_it_started(monkeypatch):
    built = []
    game = run_scripted(monkeypatch, frames=5,
                        events={0: [M], 1: [M], 2: [M]},
                        modes=(SCORED, PRACTICE, SUDDEN), worlds=built)
    assert game.mode_index == 0 and game.world.total == 40
    assert game.world is not built[0], "the same round, but a fresh world for it"


def test_a_started_round_is_the_mode_that_was_showing(monkeypatch):
    """Switch, then pull the trigger: the round played is the one on the screen.

    ESC ends it early, which is also the proof that the round really started on
    the new mode's world rather than on a leftover one.
    """
    game = run_scripted(monkeypatch, frames=5,
                        events={0: [M], 1: [SPACE], 2: [ESC]})
    assert game.mode_index == 1
    assert game.world.total == 10 and game.world.stopped


def test_the_mode_cannot_be_changed_out_from_under_a_round(monkeypatch):
    """M during the countdown or the round does nothing at all.

    A switch builds the world the next round is played in, so honouring one here
    would throw away the round in progress — along with whatever has been shot.
    """
    game = run_scripted(monkeypatch, frames=5, events={1: [SPACE], 2: [M], 3: [M]})
    assert game.mode_index == 0 and game.world.total == 40


def test_the_screens_after_the_round_keep_their_round(monkeypatch):
    """... and neither can it be changed on the way out of one.

    ESC from the countdown lands on the name screen, where M is a letter of
    somebody's name and nothing else; ESC again is the result screen, which is
    still being read. Only the title screen after it switches.
    """
    game = run_scripted(monkeypatch, frames=7,
                        events={0: [SPACE], 1: [ESC], 2: [M], 3: [ESC], 4: [M]})
    assert game.mode_index == 0 and game.world.total == 40
    assert game.world.stopped, "the round the result screen is showing"


# --- what follows the mode --------------------------------------------------

def test_the_crosshair_goes_back_to_what_the_new_mode_asks_for(monkeypatch):
    """Practice draws the crosshair, the scored round does not.

    Watched where it now counts — in the round itself, whose world latches
    having had one up. So: switch, start the round, stop it, and ask the world
    what it was shot with.
    """
    quick = (QUICK_SCORED, QUICK_PRACTICE)
    practice = run_scripted(monkeypatch, frames=6, modes=quick,
                            events={0: [M], 1: [SPACE], 3: [ESC]})
    assert practice.mode_index == 1
    assert practice.world.crosshair_used is True, "practice drew none"

    scored = run_scripted(monkeypatch, frames=6, modes=quick,
                          events={0: [M], 1: [M], 2: [SPACE], 4: [ESC]})
    assert scored.mode_index == 0
    assert scored.world.crosshair_used is False, "the scored round drew one"


def test_one_mode_alone_has_nothing_to_switch_to(monkeypatch):
    """A house with no mode files still plays. M is simply not a control there,
    and pressing it must not rebuild the world behind the player's back."""
    built = []
    game = run_scripted(monkeypatch, frames=3, events={0: [M], 1: [M]},
                        modes=(SCORED,), worlds=built)
    assert game.mode_index == 0
    assert game.world is built[0], "a world was rebuilt for a mode that is not there"


def test_settings_alone_still_makes_one_unnamed_round(monkeypatch):
    """The old way in — `PygameFrontend(settings)` — is still a game with a
    title screen, it just has nothing to cycle."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    game = PygameFrontend(_settings(ducks=7))
    assert len(game.modes) == 1
    assert game.modes[0].settings.round.ducks == 7
    assert game.world.total == 7


# --- the gun's own way to do it ---------------------------------------------

def test_a_on_the_remote_switches_the_mode_from_the_title_screen(monkeypatch):
    """The player choosing the round is three metres away with both hands on the
    gun, so A is the mode on this screen (and the crosshair on every other)."""
    game = run_scripted(monkeypatch, frames=3,
                        gun_frames={0: AimState(pressed=A_BUTTON)})
    assert game.mode_index == 1 and game.world.total == 10


def test_a_in_a_round_is_still_the_crosshair(monkeypatch):
    """A pressed once the round has started must not change the round. It
    toggles the crosshair instead — which, with the gun, costs the record: the
    world says so, and that is what tells the two bindings apart."""
    game = run_scripted(
        monkeypatch, frames=5, events={0: [SPACE]},
        modes=(QUICK_SCORED, QUICK_PRACTICE),
        gun_frames={1: AimState(pressed=A_BUTTON), 2: AimState()})
    assert game.mode_index == 0 and game.world.total == 40
    assert game.world.crosshair_used is True
