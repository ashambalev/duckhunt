"""Input abstraction.

Every input source (the keyboard for now, the light gun later) implements
`InputSource` and returns an `AimState` on each frame. The game talks to this
interface only and knows nothing about the hardware — which is why the move from
keyboard → USB gun → BLE gun never touches the game logic.
"""

from __future__ import annotations

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


class InputSource:
    """Base interface for an input source."""

    def poll(self) -> AimState:
        """Return the current aim state. Must not block for long."""
        raise NotImplementedError

    def close(self) -> None:
        """Release resources (serial port, terminal, and so on)."""
