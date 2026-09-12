"""Input abstraction.

Every input source (the keyboard for now, the light gun later) implements
`InputSource` and returns an `AimState` on each frame. The game talks to this
interface only and knows nothing about the hardware — which is why the move from
keyboard → USB gun → BLE gun never touches the game logic.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class AimState:
    """Aim state for the current frame.

    x, y   — normalized screen coordinates in the range [0.0, 1.0]
             (0,0 = top-left corner, 1,1 = bottom-right).
    fire   — edge-triggered: True exactly on the frame where the shot happened
             (the trigger pull), not for as long as the trigger is held.
    quit   — the player asked to quit the game.
    """

    x: float = 0.5
    y: float = 0.5
    fire: bool = False
    quit: bool = False
    # The rest of the gun's buttons, as the firmware's bitmask: bit0 trigger
    # (which is what `fire` is the edge of), bit1 A, bit2 HOME. `buttons` is
    # what is held right now, `pressed` is what went DOWN during this frame —
    # accumulated over every report read, so a quick tap between two frames is
    # not lost, the same way the trigger is not.
    buttons: int = 0
    pressed: int = 0


class GunStats:
    """A rolling window of when the gun's reports arrived.

    "It feels laggy" has three different causes that look the same on screen — a
    slow report rate, reports arriving in clumps, and beacons dropping out of
    view (the aim then holds its last position, which reads as sticking). They
    are told apart by numbers, not by feel, so the sources keep these and the
    pixel frontend can put them on the HUD (the G key).
    """

    WINDOW = 240        # ~4 s at the remote's 60-70 reports a second

    def __init__(self) -> None:
        self._t = deque(maxlen=self.WINDOW)       # when each report arrived
        self._blind = deque(maxlen=self.WINDOW)   # ... and whether it had no beacons
        self._t_aim = 0.0                         # the last report WITH beacons

    def report(self, blind: bool) -> None:
        now = time.monotonic()
        self._t.append(now)
        self._blind.append(blind)
        if not blind:
            self._t_aim = now

    HOLE = 0.05         # a gap this long is a stall, not clumping
    SPAN = 3.0          # seconds the numbers are averaged over

    def snapshot(self) -> dict | None:
        """What the stream looks like over the window, or None until there is one.

        rate   — reports a second. The remote sends ~96 in good health, so this
                 is the number that says whether the link is healthy.
        holes  — gaps longer than 50 ms, per second: each one is the crosshair
                 standing still that long. This is what "laggy" usually is.
        worst  — the longest such gap in the window, in seconds.
        blind  — share of reports that had no beacons in view.
        age    — how old the current aim is.

        Deliberately NOT a percentile of the gaps: these timestamps are taken
        when the game drains the port, once a frame, so every percentile below
        ~50 ms only measures the frame rate. Anything past a few frames is real.
        """
        if len(self._t) < 2:
            return None
        # Over a fixed TIME window, not a fixed number of reports: every line
        # drained in one poll gets nearly the same timestamp, so a window that
        # happens to sit inside a single poll has a span near zero — and
        # count/span then reports six hundred thousand reports a second, which
        # is exactly what one startup window in a real log did.
        now = time.monotonic()
        span = min(self.SPAN, now - self._t[0])
        if span < 0.25:
            return None
        ts = [t for t in self._t if t >= now - span]
        if len(ts) < 2:
            return None
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        big = [g for g in gaps if g > self.HOLE]
        return {"rate": len(ts) / span,
                "holes": len(big) / span,
                "worst": max(gaps),
                "blind": sum(self._blind) / len(self._blind),
                "span": round(span, 2),
                "age": time.monotonic() - self._t_aim if self._t_aim else None}


class InputSource:
    """Base interface for an input source."""

    def poll(self) -> AimState:
        """Return the current aim state. Must not block for long."""
        raise NotImplementedError

    def close(self) -> None:
        """Release resources (serial port, terminal, and so on)."""
