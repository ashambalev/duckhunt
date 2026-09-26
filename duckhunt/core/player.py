"""Who played last, in `player.json` next to scores.json.

The name is asked after every round now, and asking a repeat player to spell
themselves out again every time is the kind of friction that ends with everybody
being PLAYER. So the last name typed is remembered and offered pre-filled: Enter
accepts it, Backspace starts a different one.
"""

from __future__ import annotations

import json
import os

PLAYER_NAME = "player.json"


def default_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "..", PLAYER_NAME)


def load(path: str | None = None) -> str:
    """The last player's name, or "" if there is none to remember."""
    path = path or default_path()
    try:
        with open(path, encoding="utf-8") as f:
            return str(json.load(f).get("name", ""))
    except (OSError, ValueError, AttributeError):
        return ""


def save(name: str, path: str | None = None) -> None:
    path = path or default_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": name}, f, ensure_ascii=False)
    except OSError:
        pass          # remembering a name is a convenience, never a failure
