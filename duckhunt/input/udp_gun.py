"""Input over UDP — the same `x,y,b` lines, off the network instead of a port.

This is how `tools/fake_gun.py` plays the game with no hardware at all: it sends
the lines a bridge would send, and the game cannot tell the difference. The
protocol is deliberately the same one `serial_gun.py` reads, because the point
of the split between the game and the gun is that anything able to say where it
is pointing can drive it.

    .venv/bin/python main.py --udp
    .venv/bin/python tools/fake_gun.py

Each datagram is one line: `x,y,b` with the coordinates 0..1000 and a button
mask. Only the newest datagram of a frame matters for the aim, but every one is
read, because the trigger is an edge and a quick pull must not be lost.
"""

from __future__ import annotations

import socket

from .base import AimState, GunStats, InputSource

DEFAULT_PORT = 4210


class UdpGunInput(InputSource):
    def __init__(self, port: int = DEFAULT_PORT):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("", port))       # listen on every interface
        self._sock.setblocking(False)     # poll must not block the game loop
        self._x = 0.5
        self._y = 0.5
        self._btn_prev = 0                # for edge-detecting the shot
        self.stats = GunStats()

    def poll(self) -> AimState:
        fire = False
        pressed = 0

        # Every datagram that has piled up gets looked at, not just the freshest:
        # the position only wants the newest value, but the trigger is an EDGE,
        # and a quick pull can start and finish inside one frame's worth of
        # packets. Keeping only the last packet threw those shots away. (Same
        # reasoning, same fix as in serial_gun.py.)
        while True:
            try:
                data, _addr = self._sock.recvfrom(64)
            except BlockingIOError:
                break
            except OSError:
                break
            if not data:
                continue
            parsed = self._parse(data.strip())
            if parsed is None:
                continue
            nx, ny, btn = parsed
            pressed |= btn & ~self._btn_prev        # every button's rising edge
            if nx >= 0:                    # dots visible — update the aim
                self._x, self._y = nx, ny
            if (btn & 1) and not (self._btn_prev & 1):  # trigger rising edge
                fire = True
            self._btn_prev = btn
            self.stats.report(blind=nx < 0)

        return AimState(x=self._x, y=self._y, fire=fire,
                        buttons=self._btn_prev, pressed=pressed)

    @staticmethod
    def _parse(line: bytes):
        try:
            parts = line.decode("ascii", "ignore").split(",")
            xi, yi, btn = int(parts[0]), int(parts[1]), int(parts[2])
        except (ValueError, IndexError):
            return None
        if xi < 0 or yi < 0:
            return -1.0, -1.0, btn
        nx = min(1.0, max(0.0, xi / 1000.0))
        ny = min(1.0, max(0.0, yi / 1000.0))
        return nx, ny, btn

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass
