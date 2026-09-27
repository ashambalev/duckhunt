"""The name screen in the pixel frontend: who a round gets signed to.

`PygameFrontend.run()` is one big loop with no state of its own to poke at, so
these tests drive the real loop headlessly (dummy video/audio drivers) and read
what it did off the one thing it actually hands out: the payload the board
would have received. `pygame.event.get` is scripted frame by frame, the board
and the name lookup are swapped for fakes that only ever live in this process,
and nothing is written next to `settings.toml` — the round's name goes to the
fake board and nowhere else.

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


class _SteadyClock:
    """`pygame.time.Clock` with the wall clock taken out of it.

    Two of these tests turn on the crosshair and then put it away *inside the
    countdown*, which only works if a frame is a known length. The real Clock
    measures one, so a loaded machine could run the countdown out before the key
    that has to land in it — pinned at 16 ms, the frame count is the timeline.
    """

    def tick(self, fps=0):
        return 16

    def get_fps(self):
        return 60.0


def run_scripted(monkeypatch, frames, events=None, gun_frames=None, rows=ROWS,
                  player_name="ЖЕНЯ", countdown=3.0, world_factory=None,
                  scored=True, asks=None, crosshair="off", shots=1):
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

    `shots` is the round's shot counter before the loop starts, and it is 1
    because these tests reach the name screen by ESC rather than by playing a
    flock out — so the round they stop has nothing in it, and a round nobody
    fired a shot in is refused by `refusal()` and never gets a name screen at
    all. That is a rule about the board, not about this screen; `shots=0` is for
    the one test that is about the rule itself.
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
    frontend = PygameFrontend(
        settings=_settings(countdown=countdown, scored=scored,
                           crosshair=crosshair),
        player_name=player_name)
    if world_factory is not None:
        frontend.world = world_factory(frontend.world.settings)
    frontend.world.shots = shots        # see the docstring: a round with a shot in it

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

def test_enter_on_a_player_name_submits_it_once(monkeypatch):
    """`--player` is the one thing that puts a name in the field before anyone
    types — one shooter, a whole evening, Enter after every round."""
    submitted = run_scripted(
        monkeypatch, frames=3,
        events={0: [SPACE], 1: [ESC], 2: [ENTER]},
        player_name="Стрелок")
    assert len(submitted) == 1
    assert submitted[0]["name"] == "Стрелок"


def test_the_field_is_empty_without_player_and_enter_sends_nothing(monkeypatch):
    """The round after somebody else's is not signed with their name.

    Nothing is pre-filled any more — the field comes up blank and Enter on it
    does nothing at all, so the pull of A that used to sign the round to
    whoever played last now waits for a name to be chosen. The list is how it is
    chosen: Tab (or the trigger) takes one off the board, and that is what gets
    sent.
    """
    submitted = run_scripted(
        monkeypatch, frames=6, player_name="",
        events={0: [SPACE], 1: [ESC], 2: [ENTER], 3: [TAB], 4: [ENTER]})
    assert len(submitted) == 1, "the empty-field Enter must not have sent anything"
    assert submitted[0]["name"] == ROWS[0]["name"]


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


def test_the_crosshair_in_the_round_costs_the_record(monkeypatch):
    """A record is shot down the sights, and the round is what is judged.

    `crosshair = "on"` with no countdown to wait out: the first duck is up with
    the crosshair over it, `world.update()` latches that, and the round is
    refused. No name screen, nothing asked of the board, nothing submitted.
    """
    monkeypatch.setattr(pygame.time, "Clock", _SteadyClock)
    asks: list[str] = []
    submitted = run_scripted(
        monkeypatch, frames=5, crosshair="on", countdown=0.0, asks=asks,
        events={0: [SPACE], 2: [ESC], 3: [ENTER]},
        player_name="Стрелок")
    assert submitted == []
    assert asks == []


def test_a_round_with_no_shot_in_it_is_not_offered(monkeypatch):
    """ESC on the countdown leaves no round, and no round is not a record.

    It used to go to the board as `0/40`: an empty row, and one more attempt
    against somebody's name. Nothing is asked and nothing is sent — the result
    screen says why, the same way it does for practice and for the crosshair.
    """
    asks: list[str] = []
    submitted = run_scripted(
        monkeypatch, frames=4, shots=0, asks=asks,
        events={0: [SPACE], 1: [ESC], 2: [ENTER]},
        player_name="Стрелок")
    assert submitted == []
    assert asks == []


def test_the_crosshair_switched_off_before_the_first_duck_leaves_a_record(monkeypatch):
    """... and the countdown before it is not the round.

    The crosshair is up while the countdown runs and **C** puts it away before
    the first duck: what follows is a round shot down the sights, so it reaches
    the name screen and goes to the board like any other. These two screens used
    to latch it too, which meant the one honest move — turn the crosshair on to
    see the gun is tracking, turn it off to play — read as the cheat.

    `Clock.tick` is pinned so the frames are a known 16 ms and the 50 ms
    countdown really does still have three of them left to press C in.
    """
    monkeypatch.setattr(pygame.time, "Clock", _SteadyClock)
    submitted = run_scripted(
        monkeypatch, frames=9, crosshair="on", countdown=0.05,
        events={0: [SPACE], 1: [key(pygame.K_c, "c")], 6: [ESC], 7: [ENTER]},
        player_name="Стрелок")
    assert len(submitted) == 1, "the round was shot down the sights"
    assert submitted[0]["name"] == "Стрелок"
