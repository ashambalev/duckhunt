"""Game data models — pure, with no ties to how anything is drawn.

All coordinates and sizes are NORMALIZED to the range [0.0, 1.0] relative to the
playfield: (0,0) is the top-left corner, (1,1) the bottom-right. Speeds are in
fractions of the screen per second. Thanks to that, the same logic works
identically in the terminal (cells) and in the pixel window (pixels) — the
frontend does the scaling itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Facing(str, Enum):
    LEFT = "left"
    RIGHT = "right"


class DuckState(str, Enum):
    FLYING = "flying"
    FALLING = "falling"  # shot down, falling


@dataclass
class Duck:
    x: float          # top-left corner of the hitbox, fraction of screen [0..1]
    y: float
    vx: float         # X velocity, fraction of screen per second
    vy: float
    w: float          # hitbox width, fraction of screen
    h: float          # hitbox height
    facing: Facing
    state: DuckState = DuckState.FLYING
    age: float = 0.0      # lifetime (drives the wing-flap animation in the frontend)
    fall_t: float = 0.0   # how long it has been falling
    variant: int = 0      # duck colour: the frontend picks a sprite set by it

    def contains(self, px: float, py: float) -> bool:
        """Is the aim point (px, py) inside the duck's hitbox?"""
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h
