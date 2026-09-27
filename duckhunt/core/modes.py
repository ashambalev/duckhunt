"""The rounds there are to choose between, and where the list comes from.

A mode is one TOML file laid OVER settings.toml — `config.load(path, overlay)` —
and it may only change the round: how many ducks, how fast, what a shot costs,
and whether the crosshair is up. Never the rig. `config.MODE_SECTIONS` is where
that rule is written down and enforced; this module is only the list.

That restriction is what makes a mode something you can *switch* rather than
something you launch with. The window, the beacon rectangle, the sight-in, the
sound and the board are the same in every mode, so changing mode between two
rounds costs a new `World` and a re-sized duck — not a restart. The pixel
frontend's title screen cycles this list (M, or A on the remote); `--mode NAME`
on the command line only says which one to start on.

Where the files are:

    practice.toml       in the project root, where it has always been
    modes/*.toml        anything else, added by dropping a file in

A mode file says who it is in its own `[mode]` section:

    [mode]
    name = "PRACTICE"
    note = "ten slow ducks, one at a time — nothing goes to the board"

— and if it does not, the file name becomes the name and the line is blank.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, replace

from .config import Settings, default_path, load, read_toml

MODES_DIR = "modes"                  # drop another mode file in here
PRACTICE_NAME = "practice.toml"      # ... except this one, which predates the dir

# What the round in settings.toml itself is called. It is not a mode file, so it
# has no [mode] section to be named by — though settings.toml may add one and
# rename it, the same way any mode file does.
BASE_NAME = "SCORED"
BASE_NOTE = "the whole flock, shot down the sights — the one the board keeps"

NAME_MAX = 20                        # a title-screen word, not a sentence


@dataclass(frozen=True)
class Mode:
    """One playable round: what it is called, and the settings it plays on."""

    name: str
    note: str
    path: str | None                 # the overlay file; None for settings.toml itself
    settings: Settings

    @property
    def key(self) -> str:
        """What `--mode` matches against — the name, case and space forgiven."""
        return self.name.strip().lower()


def root() -> str:
    """The project root: two levels above this file."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))


def overlay_paths(where: str | None = None) -> list[str]:
    """Every mode file there is, in the order the title screen will show them.

    `practice.toml` first because it is the one that was always there and the one
    a first-timer is handed; the rest sorted, so the list does not reshuffle
    itself between launches on whatever order the filesystem feels like.
    """
    where = where or root()
    paths = []
    practice = os.path.join(where, PRACTICE_NAME)
    if os.path.exists(practice):
        paths.append(practice)
    paths += sorted(p for p in glob.glob(os.path.join(where, MODES_DIR, "*.toml"))
                    if os.path.basename(p) != PRACTICE_NAME)
    return paths


def describe(path: str | None, name: str, note: str = "") -> tuple[str, str]:
    """A file's `[mode]` name and one-line note, falling back to what is given."""
    data = (read_toml(path) or {}) if path and os.path.exists(path) else {}
    section = data.get("mode")
    if isinstance(section, dict):
        if isinstance(section.get("name"), str) and section["name"].strip():
            name = section["name"]
        if isinstance(section.get("note"), str):
            note = section["note"]
    return name.strip().upper()[:NAME_MAX], note.strip()


def load_all(settings_path: str | None = None,
             where: str | None = None) -> list[Mode]:
    """Every mode, settings resolved, the base round first.

    The base round is always there — a house with no mode files still has a game
    to play, it simply has nothing to switch to.
    """
    base_path = settings_path or default_path()
    name, note = describe(base_path, BASE_NAME, BASE_NOTE)
    modes = [Mode(name, note, None, load(settings_path))]
    for path in overlay_paths(where):
        stem = os.path.splitext(os.path.basename(path))[0]
        modes.append(Mode(*describe(path, stem), path,
                          load(settings_path, path)))
    return modes


def find(modes: list[Mode], wanted: str) -> int:
    """The index of the mode called `wanted`, or -1. Case and spacing forgiven."""
    key = wanted.strip().lower()
    for i, mode in enumerate(modes):
        if mode.key == key:
            return i
    return -1


def with_settings(mode: Mode, settings: Settings) -> Mode:
    """The same mode playing on different settings — what `--leaderboard` does."""
    return replace(mode, settings=settings)
