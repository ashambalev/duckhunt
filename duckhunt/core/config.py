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
    speed_min: float = 0.30    # horizontal speed, fraction of screen per second
    speed_max: float = 0.55
    bob: float = 0.12          # vertical drift, ± fraction of screen per second
    fall_speed: float = 0.7    # falling speed of a downed duck


@dataclass(frozen=True)
class RoundSettings:
    ducks: int = 100           # ducks per round (then the result and the score table)
    interval: float = 0.6      # pause between ducks, s: ducks × interval ≈ round length
    points: int = 1            # points per duck shot down
    speedup: float = 1.0       # factor the pause shrinks by after each duck
    min_interval: float = 0.5  # the pace stops growing once the pause hits this


@dataclass(frozen=True)
class SceneSettings:
    # A background name from assets/backgrounds/index.toml, or "random" (a new
    # one each launch), or "none" (a landscape drawn in code). In game the
    # background cycles with the B key — settings.toml sets where to start.
    background: str = "meadow"
    # Fullscreen (the scene is letterboxed whole, black bars at the edges) or windowed.
    fullscreen: bool = True


@dataclass(frozen=True)
class Settings:
    duck: DuckSettings = DuckSettings()
    round: RoundSettings = RoundSettings()
    scene: SceneSettings = SceneSettings()

    def summary(self) -> str:
        """One-line summary of the values in effect — printed at startup."""
        d, r = self.duck, self.round
        return (f"{r.ducks} ducks, one every {r.interval:g} s "
                f"(≈{r.ducks * r.interval:.0f} s round) · "
                f"size {d.width:g}×{d.height:g} · "
                f"speed {d.speed_min:g}–{d.speed_max:g} · "
                f"background {self.scene.background}"
                f"{', fullscreen' if self.scene.fullscreen else ', windowed'}")


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

    rnd, base = s.round, RoundSettings()
    fixes = {}
    if rnd.ducks < 1:
        _warn("[round] ducks must be at least 1 — using the default")
        fixes["ducks"] = base.ducks
    if rnd.interval <= 0 or rnd.min_interval <= 0:
        _warn("[round] the pauses must be greater than zero — using the defaults")
        fixes["interval"], fixes["min_interval"] = base.interval, base.min_interval
    if not 0 < rnd.speedup <= 1:
        _warn("[round] speedup must be in the range (0, 1] — using the default")
        fixes["speedup"] = base.speedup
    if fixes:
        rnd = RoundSettings(**{**rnd.__dict__, **fixes})

    # whether such a background exists is the frontend's business, not this module's
    return Settings(duck=duck, round=rnd, scene=s.scene)


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
        if key not in ("duck", "round", "scene", "spawn"):
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
        scene=_section(SceneSettings, data.get("scene", {}), "scene"),
    ))
