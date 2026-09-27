"""The name screen in the pixel frontend: who a round gets signed to.

`PygameFrontend.run()` is one big loop with no state of its own to poke at, so
these tests drive the real loop headlessly (dummy video/audio drivers) and read
what it did off the one thing it actually hands out: the payload the board
would have received. `pygame.event.get` is scripted frame by frame, the board
and the name lookup are swapped for fakes that only ever live in this process,
and `player.json` is stubbed at the point the frontend calls it, never touched
on disk.

Getting from the title screen to the name screen without playing a round out:
ESC from "ready" ends the round early (`World.stop()`) exactly the way a player
walking away mid-flock does, which is the least magical way there is to reach
it. The one path with no ESC of its own is the gun's — A only sends a name once
it IS the name screen, and the trigger's only way in is a round that already
finished — so the gun-only test swaps in a world that reports itself finished
from the first frame, the way the loop is told to swap it: as `frontend.world`,
never by patching `World` itself.
"""

from __future__ import annotations

from dataclasses import replace

import pygame

from duckhunt.core.config import Settings
from duckhunt.core.world import World
from duckhunt.frontends import pygame_app
from duckhunt.frontends.pygame_app import PygameFrontend
from duckhunt.input.base import AimState

# Rows `PlayerLookup.rows()` would hand back for a board with two names on it:
# one Cyrillic (this screen exists for exactly that alphabet), one played once.
ROWS = [
    {"name": "Дуся", "hits": 66, "shots": 90, "ducks": 40, "accuracy": 73.3,
     "attempts": 2, "last_played": "2026-09-20",
     "finished_at": "2026-09-20T18:00:00+00:00"},
    {"name": "Alex", "hits": 10, "shots": 20, "ducks": 40, "accuracy": 50.0,
     "attempts": 1, "last_played": "2026-09-10",
     "finished_at": "2026-09-10T18:00:00+00:00"},
]


def key(k, unicode="") -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=unicode)


SPACE = key(pygame.K_SPACE, " ")           # title screen -> countdown
ESC = key(pygame.K_ESCAPE)                 # countdown/round -> name screen
ENTER = key(pygame.K_RETURN)
TAB = key(pygame.K_TAB)
UP = key(pygame.K_UP)


def char(c: str) -> pygame.event.Event:
    """One printable keystroke — the physical key does not matter, `.unicode`
    does, and that is all the name screen ever looks at for typed text."""
    return key(pygame.K_a, c)


class _FinishedWorld(World):
    """A round that is over the instant it exists.

    Only the gun-only test needs this: every other route into the name screen
    is ESC, which the remote has no button for. Swapped in as `frontend.world`
    after construction — nothing here subclasses or patches `World` itself.
    """

    @property
    def finished(self) -> bool:
        return True


def _settings(*, countdown: float = 3.0, scored: bool = True,
              crosshair: str = "off") -> Settings:
    """Real settings, minus the parts that need a real screen or ears.

    `background = "none"` skips the asset-backed backgrounds entirely (the
    code draws its own landscape), and `[sound] enabled = false` hands the
    mixer back before anything tries to load a wav. Windowed rather than
    fullscreen, so there is no macOS fullscreen dance to run headlessly.

    `scored` is the one game rule these tests care about: the name screen only
    exists for a round that could become a record, so a practice round is how
    the skipped-name-screen case is set up.

    `[gun] crosshair = "off"` for the same reason. These tests drive the mouse
    path, where `"auto"` means the crosshair is drawn — and a round that had it
    up is not a record either, so it would skip the very screen under test. Down
    the sights is the only round that reaches the name screen at all.
    """
    base = Settings()
    return replace(
        base,
        round=replace(base.round, countdown=countdown, scored=scored),
        gun=replace(base.gun, crosshair=crosshair),
        scene=replace(base.scene, fullscreen=False, background="none"),
        sound=replace(base.sound, enabled=False),
    )


def _fake_board(sink: list) -> type:
    """`LeaderboardClient` stand-in: records every submitted payload, sends
    nothing anywhere."""

    class FakeBoard:
        def __init__(self, settings):
            pass

        def submit(self, payload):
            sink.append(payload)

        def line(self):
            return ""

        def close(self):
            pass

    return FakeBoard


def _fake_lookup(rows: list, asks: list | None = None) -> type:
    """`PlayerLookup` stand-in: always answers with the same fixed rows,
    which is enough — the screen only ever reads the latest answer.

    `asks` collects what it was asked about, which is how a test tells the name
    screen from the result screen: only the name screen ever asks.
    """

    class FakeLookup:
        def __init__(self, settings, limit=None):
            self._rows = rows

        def ask(self, text):
            if asks is not None:
                asks.append(text)

        def rows(self):
            return self._rows

        def asked(self):
            return None

        def close(self):
            pass

    return FakeLookup


def run_scripted(monkeypatch, frames, events=None, gun_frames=None, rows=ROWS,
                  player_name="ЖЕНЯ", countdown=3.0, world_factory=None,
                  scored=True, asks=None, crosshair="off"):
    """Drive `PygameFrontend.run()` for exactly `frames` frames and report
    what got submitted to the board.

    `events` maps a frame index to the `pygame.event.Event` list that frame's
    single `pygame.event.get()` call hands back (default: none that frame).
    `gun_frames` does the same for a fake `InputSource.poll()`, keyed off the
    same frame counter — pass it to get a gun (source is not None); leave it
    out for the mouse path (source is None), which is what most of these
    tests want, since the mouse cannot press A. Frame `frames` and beyond get
    a QUIT event, which is what ends the loop — nothing here reaches into any
    of `run()`'s locals.
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

    submitted: list[dict] = []
    monkeypatch.setattr(pygame_app, "LeaderboardClient", _fake_board(submitted))
    monkeypatch.setattr(pygame_app, "PlayerLookup", _fake_lookup(rows, asks))
    # the one file finish_round() would otherwise write next to settings.toml
    monkeypatch.setattr(pygame_app.player, "save", lambda *a, **k: None)
    monkeypatch.setattr(pygame_app.player, "load", lambda *a, **k: "")

    frontend = PygameFrontend(
        settings=_settings(countdown=countdown, scored=scored,
                           crosshair=crosshair),
        player_name=player_name)
    if world_factory is not None:
        frontend.world = world_factory(frontend.world.settings)

    source = None
    if gun_frames is not None:
        gf = gun_frames

        class _FakeGun:
            def poll(self):
                # fake_get() already advanced the counter past this frame
                return gf.get(counter[0] - 1, AimState())

        source = _FakeGun()

    frontend.run(source)
    return submitted


# ---- the tests --------------------------------------------------------------

def test_enter_on_the_remembered_name_submits_it_once(monkeypatch):
    submitted = run_scripted(
        monkeypatch, frames=3,
        events={0: [SPACE], 1: [ESC], 2: [ENTER]},
        player_name="Стрелок")
    assert len(submitted) == 1
    assert submitted[0]["name"] == "Стрелок"


def test_esc_on_the_name_screen_submits_nothing(monkeypatch):
    submitted = run_scripted(
        monkeypatch, frames=3,
        events={0: [SPACE], 1: [ESC], 2: [ESC]})
    assert submitted == []


def test_tab_then_enter_submits_the_first_offered_name(monkeypatch):
    submitted = run_scripted(
        monkeypatch, frames=4,
        events={0: [SPACE], 1: [ESC], 2: [TAB], 3: [ENTER]})
    assert len(submitted) == 1
    assert submitted[0]["name"] == ROWS[0]["name"]


def test_trigger_then_a_submits_the_first_offered_name_gun_only(monkeypatch):
    """The gun-only path: no keyboard event anywhere in the script."""
    submitted = run_scripted(
        monkeypatch, frames=4, countdown=0.0,
        world_factory=lambda s: _FinishedWorld(settings=s),
        gun_frames={
            0: AimState(fire=True),          # intro -> ready -> play -> name
            2: AimState(fire=True),          # trigger: take the offered name
            3: AimState(pressed=0x02),       # A: send it
        })
    assert len(submitted) == 1
    assert submitted[0]["name"] == ROWS[0]["name"]


def test_tab_up_then_one_key_submits_just_that_character(monkeypatch):
    """The regression this file exists for: cycling off the suggestion list
    with UP used to restore the typed text but not whether the next keystroke
    replaces it or appends to it — so the round went in as "ЖЕНЯA" instead of
    the single character actually typed."""
    submitted = run_scripted(
        monkeypatch, frames=6,
        events={0: [SPACE], 1: [ESC], 2: [TAB], 3: [UP], 4: [char("A")],
                5: [ENTER]},
        player_name="ЖЕНЯ")
    assert len(submitted) == 1
    assert submitted[0]["name"] == "A"


def test_emptied_field_cannot_be_sent_but_the_screen_still_works(monkeypatch):
    """A space typed into the fresh, pre-filled field clears it (the same
    "first keystroke replaces" rule the regression above is about) rather than
    being added to it — so one keystroke is enough to get to a whitespace-only
    field. ENTER there must do nothing, and the screen has to still be live
    afterwards: proved by TAB and a second ENTER going on to work normally."""
    submitted = run_scripted(
        monkeypatch, frames=6,
        events={0: [SPACE], 1: [ESC], 2: [key(pygame.K_SPACE, " ")],
                3: [ENTER], 4: [TAB], 5: [ENTER]},
        player_name="Стрелок")
    assert len(submitted) == 1, "the empty-field ENTER must not have sent anything"
    assert submitted[0]["name"] == ROWS[0]["name"]


def test_a_practice_round_never_reaches_the_name_screen(monkeypatch):
    """A round that cannot be a record is not asked who shot it.

    `[round] scored = false` is refused by `refusal()`, so ESC goes straight
    from the round to the result screen. Nothing is submitted — and the part
    that says this really is the result screen rather than a name screen with a
    broken ENTER: the board is never asked which names are already on it, which
    only the name screen does.
    """
    asks: list[str] = []
    submitted = run_scripted(
        monkeypatch, frames=3, scored=False, asks=asks,
        events={0: [SPACE], 1: [ESC], 2: [ENTER]},
        player_name="Стрелок")
    assert submitted == []
    assert asks == []


def test_empty_board_makes_tab_and_trigger_no_ops_enter_still_sends(monkeypatch):
    """The board off (or answering nothing): the list a player would take a
    name off of is simply empty, so TAB and the trigger have nothing to do —
    and typing one's own name and pressing ENTER must still work exactly as it
    does with a board up."""
    submitted = run_scripted(
        monkeypatch, frames=5, rows=[],
        events={0: [SPACE], 1: [ESC], 2: [TAB], 4: [ENTER]},
        gun_frames={3: AimState(fire=True)},
        player_name="Solo")
    assert len(submitted) == 1
    assert submitted[0]["name"] == "Solo"


def test_the_countdown_cannot_be_used_to_peek_and_still_claim_a_record(monkeypatch):
    """The crosshair up during the countdown already costs the record.

    The countdown draws the crosshair but calls no `world.update()`, so the
    latch that `update()` keeps would never have seen it — and three seconds of
    watching where the barrel actually points is exactly the help the rule is
    there to take away. With `crosshair = "on"` this round is refused before it
    starts: no name screen, nothing asked of the board, nothing submitted.
    """
    asks: list[str] = []
    submitted = run_scripted(
        monkeypatch, frames=4, crosshair="on", asks=asks,
        events={0: [SPACE], 2: [ESC], 3: [ENTER]},
        player_name="Стрелок")
    assert submitted == []
    assert asks == []
