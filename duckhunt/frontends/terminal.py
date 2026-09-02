"""The terminal (ASCII/TUI) frontend on top of the `World` core.

It holds the visuals only: the duck sprites and the translation of the core's
normalized [0..1] coordinates into terminal cells. All game logic lives in
`duckhunt.core`.
"""

from __future__ import annotations

import time

from ..core.models import DuckState, Facing
from ..core.world import World

FPS = 30
FRAME = 1.0 / FPS
FLAP_HZ = 7  # wing flaps per second

# Sprites. The body always sits on the middle row, so the duck does not jitter
# vertically — only the wing moves up and down around it.
DUCK_RIGHT = [                       # flying right (beak on the right), eye by the beak
    [r" /\ ", r"(__o)>", r"    "],   # wing up
    [r"    ", r"(__o)>", r" \/ "],   # wing down
]
DUCK_LEFT = [                        # flying left (beak on the left)
    [r"  /\ ", r"<(o__)", r"     "],
    [r"     ", r"<(o__)", r"  \/ "],
]
DUCK_HIT = [r"(x__x)", r" vvv "]     # shot down — crosses for eyes


# Crosshair smoothing (exponential filter): 1.0 = no smoothing (maximum
# responsiveness, but jittery), lower = smoother but a little more sluggish.
# Tune it to taste.
SMOOTH_ALPHA = 0.45


class TerminalFrontend:
    def __init__(self, term, settings=None):
        self.term = term
        self.world = World(settings=settings)
        self._sx = 0.5   # smoothed crosshair coordinates
        self._sy = 0.5

    def _sprite(self, d) -> list:
        if d.state is DuckState.FALLING:
            return DUCK_HIT
        frames = DUCK_RIGHT if d.facing is Facing.RIGHT else DUCK_LEFT
        return frames[int(d.age * FLAP_HZ) % len(frames)]

    def render(self, aim) -> str:
        t = self.term
        width = self.term.width
        play_h = self.term.height - 1  # the bottom row is the HUD
        grid = [[" "] * width for _ in range(play_h)]

        for d in self.world.ducks:
            col0 = int(d.x * width)
            row0 = int(d.y * play_h)
            for ry, row in enumerate(self._sprite(d)):
                gy = row0 + ry
                if not (0 <= gy < play_h):
                    continue
                for rx, ch in enumerate(row):
                    gx = col0 + rx
                    if ch != " " and 0 <= gx < width:
                        grid[gy][gx] = ch

        # crosshair
        cx = int(aim.x * (width - 1))
        cy = int(aim.y * (play_h - 1))
        if 0 <= cy < play_h and 0 <= cx < width:
            grid[cy][cx] = "+"
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = cx + dx, cy + dy
                if 0 <= ny < play_h and 0 <= nx < width and grid[ny][nx] == " ":
                    grid[ny][nx] = "-" if dy == 0 else "|"

        lines = ["".join(row) for row in grid]
        w = self.world
        hud = (f" 🦆 HIT {w.hits}   DUCK {w.released}/{w.total}   "
               f"{w.accuracy:3.0f}% ACC   [arrows/WASD aim · SPACE fire · Q quit] ")
        hud = hud[:width].ljust(width)
        return t.home + "\n".join(lines) + "\n" + t.reverse(hud)

    def run(self, source) -> None:
        t = self.term
        with t.cbreak(), t.hidden_cursor(), t.fullscreen():
            print(t.home + t.clear, end="")
            last = time.monotonic()
            while True:
                now = time.monotonic()
                dt = now - last
                last = now

                state = source.poll()
                if state.quit:
                    break

                # smooth the crosshair position (the trigger/shot is left alone)
                self._sx += SMOOTH_ALPHA * (state.x - self._sx)
                self._sy += SMOOTH_ALPHA * (state.y - self._sy)
                state.x, state.y = self._sx, self._sy

                self.world.update(dt, state.x, state.y, state.fire)
                print(self.render(state), end="", flush=True)
                if self.world.finished:      # the flock is gone — round over
                    break

                sleep = FRAME - (time.monotonic() - now)
                if sleep > 0:
                    time.sleep(sleep)
