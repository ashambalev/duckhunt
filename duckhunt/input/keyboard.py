"""Keyboard input — for developing and debugging the game without the gun.

Arrows / WASD move the crosshair, Space fires, q / Esc quits.
It implements the same `InputSource` interface as the light gun, so the game
logic does not depend on which source is in use.
"""

from __future__ import annotations

from .base import AimState, InputSource

STEP = 0.04  # how far one key press moves the crosshair (fraction of screen)


class KeyboardInput(InputSource):
    def __init__(self, term):
        self._term = term
        self._x = 0.5
        self._y = 0.5

    def poll(self) -> AimState:
        fire = False
        quit_ = False

        # Read every key that has piled up, without blocking (timeout=0).
        while True:
            key = self._term.inkey(timeout=0)
            if not key:
                break

            name = key.name  # for special keys, e.g. 'KEY_LEFT'
            ch = str(key).lower()

            if name == "KEY_LEFT" or ch == "a":
                self._x -= STEP
            elif name == "KEY_RIGHT" or ch == "d":
                self._x += STEP
            elif name == "KEY_UP" or ch == "w":
                self._y -= STEP
            elif name == "KEY_DOWN" or ch == "s":
                self._y += STEP
            elif ch == " ":
                fire = True
            elif ch == "q" or name == "KEY_ESCAPE":
                quit_ = True

        self._x = min(1.0, max(0.0, self._x))
        self._y = min(1.0, max(0.0, self._y))
        return AimState(x=self._x, y=self._y, fire=fire, quit=quit_)

    def close(self) -> None:  # the terminal is owned by the game
        pass
