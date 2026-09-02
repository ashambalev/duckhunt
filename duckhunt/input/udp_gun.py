"""Input from the ESP32 bridge over Wi-Fi (UDP) — Path B.

The chain: Wiimote → (Bluetooth Classic) → ESP32 → (Wi-Fi UDP) → Mac.
The ESP32 sends UDP (broadcast) packets carrying the same line as the Serial
version:

    x,y,b\\n
    x, y — the aim point 0..1000 (normalized to [0,1]);
           -1,-1 if the beacons/dots are not visible
    b    — button mask: bit0 (1) = trigger (the remote's B button)

On the Mac side we simply listen on a UDP port and pair nothing over Bluetooth
(which was the whole point: to move the link away from the temperamental macOS
Bluetooth stack). No external dependencies — a plain socket. Matches the parser in
`serial_gun.py`, so the game is unchanged.
"""

from __future__ import annotations

import socket

from .base import AimState, InputSource

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

    def poll(self) -> AimState:
        fire = False
        line = None

        # Take every datagram that has piled up, keep the freshest one.
        while True:
            try:
                data, _addr = self._sock.recvfrom(64)
            except BlockingIOError:
                break
            except OSError:
                break
            if data:
                line = data.strip()

        if line:
            parsed = self._parse(line)
            if parsed is not None:
                nx, ny, btn = parsed
                if nx >= 0:                    # dots visible — update the aim
                    self._x, self._y = nx, ny
                if (btn & 1) and not (self._btn_prev & 1):  # trigger rising edge
                    fire = True
                self._btn_prev = btn

        return AimState(x=self._x, y=self._y, fire=fire)

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
