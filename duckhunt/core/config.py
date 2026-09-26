"""Balance settings: duck size and speed, spawn rate.

The values live in `settings.toml` in the project root. The file may be absent —
then the defaults from this module are used (they are spelled out in
settings.toml as well, so editing them there is the convenient way). Another
file: `--settings path.toml` or the `DUCKHUNT_SETTINGS` environment variable.

All sizes and speeds are IN FRACTIONS OF THE SCREEN, like the rest of the
geometry in `models`: a width of 0.09 = 9 % of the playfield width, a speed of
0.2 = a fifth of the screen per second. That is why the settings work the same in
the terminal and in the pixel window.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, fields

SETTINGS_ENV = "DUCKHUNT_SETTINGS"
SETTINGS_NAME = "settings.toml"


@dataclass(frozen=True)
class DuckSettings:
    width: float = 0.13        # duck width (and its hitbox), fraction of screen width
    height: float = 0.16       # duck height, fraction of screen height
    speed_min: float = 0.30    # slowest horizontal speed, fraction of screen per second
    speed_max: float = 0.55    # and the fastest; each duck gets a random one between
    bob: float = 0.12          # vertical drift, ± fraction of screen per second
    fall_speed: float = 0.7    # falling speed of a downed duck
    # The strip the ducks are allowed to fly in, measured from the TOP of the
    # picture: 0.90 keeps them in the top 90 %, so the bottom tenth (the grass,
    # where the dog is) stays clear. A duck is spawned inside this strip and
    # bounces off its lower edge the same way it bounces off the top.
    sky: float = 0.90


@dataclass(frozen=True)
class RoundSettings:
    ducks: int = 100           # ducks per round (then the result and the score table)
    interval: float = 0.6      # pause between ducks, s: ducks × interval ≈ round length
    points: int = 1            # points per duck shot down
    speedup: float = 1.0       # factor the pause shrinks by after each duck
    min_interval: float = 0.5  # the pace stops growing once the pause hits this
    # Seconds between "start" and the first duck. The round does not begin on its
    # own any more: the intro waits for the trigger, and then this counts down, so
    # a light gun player has time to get the gun up and settled.
    countdown: float = 3.0


@dataclass(frozen=True)
class DogSettings:
    """The dog: how big it is and how much of the picture it may use.

    Like everything else here the size is a FRACTION OF THE PICTURE, so the dog
    keeps its proportions on a 27" monitor and on a 55" TV alike. (It used to be
    a fixed 150 px, which meant a dog that shrank as the picture grew.) Unlike
    the ducks it is scaled to exactly this width rather than by a whole number of
    times — a whole-number step would be a third of a dog at a typical fullscreen
    scale, which is not a knob anyone can aim with.
    """
    width: float = 0.12        # dog width, fraction of the picture's width
    # The bottom strip of the picture the dog lives in: it walks inside it during
    # the intro and pops up out of the grass no higher than its top edge. 0.20 =
    # the bottom fifth. Together with [duck] sky this keeps the ducks and the dog
    # out of each other's way.
    band: float = 0.20
    speed: float = 0.12        # walking speed in the intro, fraction of screen per second
    pop: float = 1.4           # how long one pop-up reaction lasts, seconds
    # The dog that comes up holding the ducks you shot, relative to `width`: it
    # is the reward for hitting something and reads better a little larger than
    # the dog that walks the grass. The one that laughs at a miss is left at
    # `width` — that one does not need help being noticed.
    catch_scale: float = 1.2


@dataclass(frozen=True)
class SoundSettings:
    """The three sounds: your shot, the duck's quack when it is hit, and the dog
    laughing at the one that got away.

    The files are `assets/sounds/*.wav`, made by `tools/make_sounds.py`. The
    volumes are all 0..1 and multiply: a clip plays at `volume` x its own knob, so
    `volume` is the one to turn down for the room and the rest are the balance
    between them (a gunshot three metres from your ear wants to be quieter than a
    quack needs to be heard). Missing files or no audio device is not an error —
    the game says so once and plays on in silence.
    """
    enabled: bool = True       # false = a silent game, nothing is even loaded
    volume: float = 0.7        # master volume, 0..1
    # Below the other two on purpose: the files share a peak, but the shot has
    # ~5.7 dB more energy than the quack where it is loudest, and it plays on
    # every trigger pull rather than only on a hit.
    shot: float = 0.4          # the gun, relative to master
    quack: float = 1.0         # the duck being hit
    laugh: float = 1.0         # the dog at a miss
    # Whether the gun is heard when you DO hit. On: every trigger pull goes bang
    # and a hit adds the quack on top — the shot is the feedback that the trigger
    # was read at all, which matters with a light gun. Off: a hit is the quack
    # alone, and the bang means "missed".
    shot_on_hit: bool = True


@dataclass(frozen=True)
class SceneSettings:
    # A background name from assets/backgrounds/index.toml, or "random" (a new
    # one each launch), or "none" (a landscape drawn in code). In game the
    # background cycles with the B key — settings.toml sets where to start.
    background: str = "meadow"
    # Fullscreen (the scene is letterboxed whole, black bars at the edges) or windowed.
    fullscreen: bool = True
    # Which monitor to open on, counting from 0. SDL enumerates displays in its
    # own order, and that order changes when one is plugged in or wakes from
    # sleep — so "whichever one it opened on last time" is luck, not a setting.
    # -1 leaves the choice to SDL, which is what it always did; the display
    # actually used is printed at startup, so you can read the number off and
    # pin it here.
    display: int = -1
    # How the picture is fitted to the screen:
    #   "height"  — as tall as the screen, aspect kept, bars left and right only.
    #               The art pixels then land on a non-whole number of display
    #               pixels, so some come out a pixel bigger than others — the
    #               scaling stays nearest-neighbour, nothing is blurred, and the
    #               picture is as big as it can be. This is what plays best.
    #   "integer" — the pixel-purist fit: a whole-number scale, letterboxed on
    #               all four sides, every art pixel exactly the same size.
    fit: str = "height"
    # How many display pixels one pixel of the art becomes, for fit = "integer"
    # (and the closest whole number is reported for "height"). 0 = as big as fits.
    # A smaller number deliberately shrinks the picture, which is the light gun's
    # distance knob: the camera has to hold all four beacons in frame, so the
    # playing distance is about 4.8x the width of the beacon rectangle. Half the
    # scale, half the distance — it is how a 55" TV becomes playable from a sofa.
    scale: int = 0


@dataclass(frozen=True)
class GunSettings:
    """Where the four IR beacons sit, so the gun's coordinates can be turned into
    playfield coordinates.

    The firmware solves the homography and reports where the barrel points inside
    the BEACON RECTANGLE, 0..1 along its own two axes. What that rectangle is
    against the game is a property of how the LEDs were taped up, so it lives
    here rather than in the firmware — one file to edit when moving between a
    monitor and a TV, instead of a reflash. Leave the firmware's own
    `BEACON_CX/CY/W/H` at 0.5/0.5/1.0/1.0 and do the whole correction here.

    `frame` says what the numbers below are fractions OF:

      "picture" — the game's letterboxed picture (the ducks' rectangle). With the
                  LEDs stuck to the corners of the picture itself, the defaults
                  are already right and nothing depends on the display: the same
                  settings play on a 27" monitor and on a 55" TV.
      "display" — the whole physical screen, the original wiring. The game then
                  works the letterbox out itself, so the crosshair still reaches
                  the picture's corner; aiming into a black bar parks it at the
                  edge.
    """
    # The shot's radius, as a fraction of the playfield width: a hit when the
    # duck's rectangle comes within this of the aim point, not only when it
    # swallows it. A shotgun scatters, and a single-pixel crosshair is harsher
    # than the NES ever was. The crosshair is drawn at exactly this size, so what
    # you see is what you hit. 0 = the old pinpoint.
    spread: float = 0.04
    # Seconds of aim to extrapolate ahead, to hide the link's own delay. The
    # chain costs ~40-55 ms (remote -> radio -> bridge -> one frame -> vsync,
    # the last two measured at 16.7 ms on this Mac), and this advances the
    # crosshair along its current velocity by that much. 0 = off; 0.02-0.045 is
    # the useful range, and too much makes it overshoot and jitter.
    lead: float = 0.0
    # The ceiling on that, in seconds. When the link stalls the last report goes
    # stale, and the crosshair is advanced by `lead` PLUS however stale it is —
    # which is the right thing to do while the barrel keeps moving and the wrong
    # thing to do forever, so it stops here. The crosshair then holds a bounded
    # distance ahead of the last thing the gun said instead of sailing off.
    lead_max: float = 0.06
    frame: str = "display"     # "picture" (LEDs on the picture) or "display" (on the screen)
    beacon_w: float = 1.0      # rectangle width, in widths of that frame
    beacon_h: float = 1.0      # rectangle height, in heights of that frame
    beacon_cx: float = 0.5     # its centre across, as a fraction of that frame
    beacon_cy: float = 0.5     # its centre down, as a fraction of that frame


@dataclass(frozen=True)
class LeaderboardSettings:
    """Where the scoreboard is, if there is one.

    The board is a separate process on a screen of its own (see
    docs/LEADERBOARD.md): the game posts one row per round and draws nothing of
    what comes back. Off by default — with `enabled = false` the game never
    touches the network and behaves exactly as it did before the board existed.
    """
    enabled: bool = False
    url: str = "http://localhost:8420"
    client_id: str = "duckhunt"      # which cabinet this is, in the server's log
    timeout: float = 2.0             # seconds per attempt; three attempts, then the queue
    token: str = ""                  # only if the server was started with --token


@dataclass(frozen=True)
class Settings:
    duck: DuckSettings = DuckSettings()
    round: RoundSettings = RoundSettings()
    dog: DogSettings = DogSettings()
    scene: SceneSettings = SceneSettings()
    gun: GunSettings = GunSettings()
    sound: SoundSettings = SoundSettings()
    leaderboard: LeaderboardSettings = LeaderboardSettings()

    def summary(self) -> str:
        """One-line summary of the values in effect — printed at startup."""
        d, r = self.duck, self.round
        return (f"{r.ducks} ducks, one every {r.interval:g} s "
                f"(≈{r.ducks * r.interval:.0f} s round) · "
                f"size {d.width:g}×{d.height:g} · "
                f"speed {d.speed_min:g}–{d.speed_max:g} · "
                f"background {self.scene.background}"
                f"{', fullscreen' if self.scene.fullscreen else ', windowed'}"
                f"{f' at {self.scene.scale}x' if self.scene.scale else ''}"
                f"{f' · board {self.leaderboard.url}' if self.leaderboard.enabled else ''}")


def _warn(msg: str) -> None:
    print(f"{SETTINGS_NAME}: {msg}", file=sys.stderr)


def _section(cls, data: dict, name: str):
    """A TOML section -> dataclass. Unknown keys and wrong types get a warning."""
    # take the key's type from the default value: the annotations here are
    # strings (`from __future__ import annotations`), comparing against them is
    # fragile
    known = {f.name: type(f.default) for f in fields(cls)}
    values = {}
    for key, value in data.items():
        if key not in known:
            _warn(f"[{name}] unknown key {key!r} — skipped")
        elif known[key] is str:
            if isinstance(value, str):
                values[key] = value
            else:
                _warn(f"[{name}] {key} must be a string, not {value!r} — "
                      "using the default")
        elif known[key] is bool:
            # check bool before numbers: in Python True is a number too
            if isinstance(value, bool):
                values[key] = value
            else:
                _warn(f"[{name}] {key} must be true or false, not {value!r} — "
                      "using the default")
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            _warn(f"[{name}] {key} must be a number, not {value!r} — using the default")
        elif known[key] is int:
            values[key] = int(value)
        else:
            values[key] = float(value)
    return cls(**values)


def _validated(s: Settings) -> Settings:
    """Fix values that would break the game (zero and negative ones)."""
    duck = s.duck
    fixes: dict[str, float] = {}
    for name in ("width", "height", "speed_min", "speed_max", "fall_speed"):
        if getattr(duck, name) <= 0:
            _warn(f"[duck] {name} must be greater than zero — using the default")
            fixes[name] = getattr(DuckSettings(), name)
    if fixes:
        duck = DuckSettings(**{**duck.__dict__, **fixes})
    if duck.speed_min > duck.speed_max:
        _warn("[duck] speed_min is greater than speed_max — swapped them")
        duck = DuckSettings(**{**duck.__dict__,
                               "speed_min": duck.speed_max,
                               "speed_max": duck.speed_min})
    if duck.bob < 0:
        duck = DuckSettings(**{**duck.__dict__, "bob": abs(duck.bob)})
    # The ducks need a strip taller than a duck to fly in, or spawning has
    # nowhere to put them and the bounce has nothing to bounce off.
    if not 0 < duck.sky <= 1:
        _warn("[duck] sky must be in the range (0, 1] — using the default")
        duck = DuckSettings(**{**duck.__dict__, "sky": DuckSettings().sky})
    if duck.sky <= duck.height:
        _warn(f"[duck] sky ({duck.sky:g}) is not taller than a duck "
              f"({duck.height:g}) — flying them in the whole picture instead")
        duck = DuckSettings(**{**duck.__dict__, "sky": 1.0})

    rnd, base = s.round, RoundSettings()
    fixes = {}
    if rnd.ducks < 1:
        _warn("[round] ducks must be at least 1 — using the default")
        fixes["ducks"] = base.ducks
    if rnd.interval <= 0 or rnd.min_interval <= 0:
        _warn("[round] the pauses must be greater than zero — using the defaults")
        fixes["interval"], fixes["min_interval"] = base.interval, base.min_interval
    if rnd.countdown < 0:
        _warn("[round] countdown cannot be negative — using 0 (start at once)")
        fixes["countdown"] = 0.0
    if not 0 < rnd.speedup <= 1:
        _warn("[round] speedup must be in the range (0, 1] — using the default")
        fixes["speedup"] = base.speedup
    if fixes:
        rnd = RoundSettings(**{**rnd.__dict__, **fixes})

    dog, dbase = s.dog, DogSettings()
    fixes = {}
    for name in ("width", "pop", "catch_scale"):
        if getattr(dog, name) <= 0:
            _warn(f"[dog] {name} must be greater than zero — using the default")
            fixes[name] = getattr(dbase, name)
    if not 0 < dog.band <= 1:
        _warn("[dog] band must be in the range (0, 1] — using the default")
        fixes["band"] = dbase.band
    if dog.speed < 0:
        _warn("[dog] speed cannot be negative — using 0 (a dog standing still)")
        fixes["speed"] = 0.0
    if fixes:
        dog = DogSettings(**{**dog.__dict__, **fixes})

    scene = s.scene
    if scene.fit not in ("height", "integer"):
        _warn(f'[scene] fit must be "height" or "integer", not {scene.fit!r} — '
              'using "height"')
        scene = SceneSettings(**{**scene.__dict__, "fit": "height"})
    if scene.scale < 0:
        _warn("[scene] scale cannot be negative — using 0 (as big as fits)")
        scene = SceneSettings(**{**scene.__dict__, "scale": 0})
    if scene.display < -1:
        _warn("[scene] display is a monitor number from 0, or -1 for SDL's "
              "choice — using -1")
        scene = SceneSettings(**{**scene.__dict__, "display": -1})

    gun, gbase = s.gun, GunSettings()
    fixes = {}
    if gun.frame not in ("display", "picture"):
        _warn(f'[gun] frame must be "display" or "picture", not {gun.frame!r} — '
              "using the default")
        fixes["frame"] = gbase.frame
    for name in ("spread", "lead", "lead_max"):
        if getattr(gun, name) < 0:
            _warn(f"[gun] {name} cannot be negative — using 0")
            fixes[name] = 0.0
    if fixes.get("lead_max", gun.lead_max) < fixes.get("lead", gun.lead):
        _warn("[gun] lead_max is below lead — raising it to lead, which is the "
              "least it can usefully be")
        fixes["lead_max"] = fixes.get("lead", gun.lead)
    if gun.spread > 0.5:
        _warn("[gun] spread is half the screen wide — capping it at 0.5")
        fixes["spread"] = 0.5
    for name in ("beacon_w", "beacon_h"):
        if getattr(gun, name) <= 0:
            _warn(f"[gun] {name} must be greater than zero — using the default")
            fixes[name] = getattr(gbase, name)
    if fixes:
        gun = GunSettings(**{**gun.__dict__, **fixes})
    # A beacon rectangle SMALLER than the picture cannot work: the firmware
    # clamps the aim to its own rectangle (0..1000), so aiming past a beacon
    # sticks there and the picture's outer band is unreachable. Shrinking the
    # picture with [scene] scale is the way to play closer, not this.
    if gun.frame == "picture" and (gun.beacon_w < 1 or gun.beacon_h < 1):
        _warn("[gun] beacons inside the picture — the crosshair will not reach "
              "its edge; shrink the picture with [scene] scale instead")

    snd, sbase = s.sound, SoundSettings()
    fixes = {}
    for name in ("volume", "shot", "quack", "laugh"):
        value = getattr(snd, name)
        if value < 0:
            _warn(f"[sound] {name} cannot be negative — using 0 (silent)")
            fixes[name] = 0.0
        elif value > 1:
            # louder than the file is not a thing the mixer can do, and asking
            # for it would only clip; the files are normalised, so 1 is the top
            _warn(f"[sound] {name} is a volume from 0 to 1 — capping it at 1")
            fixes[name] = 1.0
    if fixes:
        snd = SoundSettings(**{**snd.__dict__, **fixes})

    lb = s.leaderboard
    if lb.enabled and not lb.url.startswith(("http://", "https://")):
        _warn(f"[leaderboard] url must start with http:// or https://, not "
              f"{lb.url!r} — the board is off for this run")
        lb = LeaderboardSettings(**{**lb.__dict__, "enabled": False})
    if lb.timeout <= 0:
        _warn("[leaderboard] timeout must be greater than zero — using the default")
        lb = LeaderboardSettings(**{**lb.__dict__,
                                    "timeout": LeaderboardSettings().timeout})

    # whether such a background exists is the frontend's business, not this module's
    return Settings(duck=duck, round=rnd, dog=dog, scene=scene, gun=gun, sound=snd,
                    leaderboard=lb)


def default_path() -> str:
    """`settings.toml` in the project root (two levels above this file)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "..", SETTINGS_NAME)


def load(path: str | None = None) -> Settings:
    """Read the settings. Missing or broken file gives the defaults."""
    path = path or os.environ.get(SETTINGS_ENV) or default_path()
    if not os.path.exists(path):
        return Settings()
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        _warn(f"could not be read ({exc}) — playing with the default values")
        return Settings()

    for key in data:
        if key not in ("duck", "round", "dog", "scene", "gun", "sound",
                       "leaderboard", "spawn"):
            _warn(f"unknown section [{key}] — skipped")

    # the spawn rate used to live in [spawn]; old files still work, but ask to move
    rnd = dict(data.get("round", {}))
    if "spawn" in data:
        _warn("the [spawn] section moved to [round] — move interval/speedup/"
              "min_interval there")
        for key in ("interval", "speedup", "min_interval"):
            rnd.setdefault(key, data["spawn"].get(key, RoundSettings().__dict__[key]))

    return _validated(Settings(
        duck=_section(DuckSettings, data.get("duck", {}), "duck"),
        round=_section(RoundSettings, rnd, "round"),
        dog=_section(DogSettings, data.get("dog", {}), "dog"),
        scene=_section(SceneSettings, data.get("scene", {}), "scene"),
        gun=_section(GunSettings, data.get("gun", {}), "gun"),
        sound=_section(SoundSettings, data.get("sound", {}), "sound"),
        leaderboard=_section(LeaderboardSettings, data.get("leaderboard", {}),
                             "leaderboard"),
    ))
