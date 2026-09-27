"""Input from the ESP32 light gun over Serial (USB CDC).

Protocol (one text line per frame, terminated by `\\n`):

    x,y,b

    x, y — the aim point, integers 0..1000 (normalized to [0,1]);
           -1,-1 means the beacons are not visible
    b    — button bitmask: bit0 (1) = trigger pulled

Example line: ``742,318,1`` — aiming upper-right of centre, trigger pulled.

The same format will later go over BLE (same parser), with no change to the game.
The q key for quitting from the terminal is handled separately in main.py, so
that you can quit from the keyboard even while playing with the gun.
"""

from __future__ import annotations

from .base import AimState, GunStats, InputSource

try:
    import serial  # pyserial
except ImportError:  # pragma: no cover
    serial = None


class SerialGunInput(InputSource):
    def __init__(self, port: str, baud: int = 115200):
        if serial is None:
            raise RuntimeError("pyserial is not installed: pip install pyserial")
        # Open WITHOUT rebooting the ESP32. On these CH340 boards DTR/RTS drive the
        # reset/boot pins, and pyserial asserts them while opening — which rebooted
        # the bridge and dropped the paired Wii Remote every time the game started.
        # Configuring the port first and setting dtr/rts False *before* open() makes
        # pyserial apply them as it opens, so the reset pulse never happens and the
        # remote stays connected across game restarts.
        self._ser = serial.Serial()
        self._ser.port = port
        self._ser.baudrate = baud
        self._ser.timeout = 0
        try:
            self._ser.dtr = False
            self._ser.rts = False
        except Exception:      # a port/driver that does not expose the lines
            pass
        self._ser.open()
        self._buf = b""
        self._x = 0.5
        self._y = 0.5
        self._btn_prev = 0  # for edge-detecting the shot
        self.stats = GunStats()
        self._hushed = False   # have we asked the bridge to stop its dot dumps

    def poll(self) -> AimState:
        fire = False
        pressed = 0

        # Drain the port buffer completely (not just 4096 B) so that latency does
        # not build up: take exactly what has arrived, and read all of it below.
        try:
            n = self._ser.in_waiting
            if n:
                self._buf += self._ser.read(n)
        except Exception:
            pass

        # EVERY line gets looked at, not just the freshest one. The position
        # only needs the newest value, but the trigger is an EDGE: at 60-70
        # reports a second against 60 frames, a quick pull can begin and end
        # inside one frame's worth of lines, and keeping only the last line threw
        # that shot away — which is what made fast shooting drop hits. The aim
        # still ends up being the last line's, because each one overwrites it.
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            raw = raw.strip()
            # The bridge also reports its beacon count on this port; the '#'
            # lines are status, not aim.
            if raw.startswith(b"#"):
                continue
            parsed = self._parse(raw)
            if parsed is None:
                continue
            nx, ny, btn = parsed
            pressed |= btn & ~self._btn_prev        # every button's rising edge
            if nx >= 0:  # beacons visible — update the position
                self._x, self._y = nx, ny
            # fire on the rising edge of the trigger (0 -> 1)
            if (btn & 1) and not (self._btn_prev & 1):
                fire = True
            self._btn_prev = btn
            self.stats.report(blind=nx < 0)
            if not self._hushed:
                # The bridge also dumps its raw dots on this port, twice a second
                # by default and on EVERY report if a tool left it in 'd' mode.
                # At 115200 a dump line is ~5 ms of port time that the next aim
                # line waits behind, so hush it now that the aim is flowing ('o'
                # is the bridge's own command; it comes back at the next reset).
                self._hushed = True
                try:
                    self._ser.write(b"o")
                except Exception:
                    pass

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
            self._ser.close()
        except Exception:
            pass
