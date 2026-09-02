"""Input straight from a Wii Remote over Bluetooth (Path A — no soldering).

We read the remote's IR camera and buttons over HID (hidapi), without taking the
Wiimote apart. This is a quick prototype; later the camera will be desoldered and
wired to the ESP32 (`serial_gun.py`), but both sources produce the same
`AimState`, so the game is unchanged.

Requirements on macOS (the HID stack is temperamental on Sonoma and newer):
  1) Pair the remote with the **WiimotePair** utility (dolphin-emu/WiimotePair) —
     once. (Direct pairing via System Settings on newer macOS asks for a PIN and
     often falls apart.)
  2) brew install hidapi;  pip install hidapi
  3) python3 main.py --wiimote

Wiimote protocol (in brief, see wiibrew.org/wiki/Wiimote):
  - output report 0x12 sets the reporting mode (0x33 = buttons+accel+12 IR bytes);
  - enabling the IR camera means a series of register writes (enable_ir below);
  - IR mode 3 (extended) -> 4 dots of 3 bytes each, X:0..1023, Y:0..767;
  - the B button (the Zapper trigger) = second button byte & 0x04.
"""

from __future__ import annotations

import time

from .base import AimState, InputSource

try:
    import hid  # the hidapi package
except ImportError:  # pragma: no cover
    hid = None

VENDOR_NINTENDO = 0x057E
PID_RVL003 = 0x0306   # Wii Remote (RVL-003)
PID_RVL036 = 0x0330   # Wii Remote Plus (RVL-036) — same camera

# The standard "level 3" IR sensitivity block (as used by the Wii itself).
_SENS_BLOCK1 = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x90, 0x00, 0xC0])
_SENS_BLOCK2 = bytes([0x40, 0x00])
IR_ABSENT = 0xFF  # the camera reports 0xFF for "dot not visible"


class WiimoteInput(InputSource):
    def __init__(self):
        if hid is None:
            raise RuntimeError("No hidapi: brew install hidapi && pip install hidapi")
        self._dev = self._open()
        self._x = 0.5
        self._y = 0.5
        self._btn_prev = False
        self._enable_ir()

    # ---- connection ------------------------------------------------------
    def _open(self):
        for pid in (PID_RVL003, PID_RVL036):
            try:
                d = hid.device()
                d.open(VENDOR_NINTENDO, pid)
                d.set_nonblocking(True)
                return d
            except (OSError, IOError):
                continue
        raise RuntimeError(
            "Wii Remote not found. Pair it first (WiimotePair) and check Bluetooth."
        )

    def _write(self, data: bytes) -> None:
        # On macOS the first buffer byte is the output report number. The low bit
        # of that first byte drives the rumble motor — keep it 0.
        self._dev.write(bytes(data))
        time.sleep(0.02)

    def _write_register(self, offset: int, payload: bytes) -> None:
        # Report 0x16: write to the control registers (address flag 0x04).
        buf = bytearray(22)
        buf[0] = 0x16
        buf[1] = 0x04
        buf[2] = (offset >> 16) & 0xFF
        buf[3] = (offset >> 8) & 0xFF
        buf[4] = offset & 0xFF
        buf[5] = len(payload)
        buf[6:6 + len(payload)] = payload
        self._write(bytes(buf))

    def _enable_ir(self) -> None:
        # The IR camera enable sequence (wiibrew).
        self._write(bytes([0x13, 0x04]))            # enable IR
        self._write(bytes([0x1A, 0x04]))            # enable IR (2)
        self._write_register(0xB00030, bytes([0x08]))
        self._write_register(0xB00000, _SENS_BLOCK1)
        self._write_register(0xB0001A, _SENS_BLOCK2)
        self._write_register(0xB00033, bytes([0x03]))  # IR mode 3 (extended)
        self._write_register(0xB00030, bytes([0x08]))
        self._write(bytes([0x12, 0x00, 0x33]))      # reporting mode 0x33
        # light LED1 so you can see the remote is connected
        self._write(bytes([0x11, 0x10]))

    # ---- reading ---------------------------------------------------------
    def poll(self) -> AimState:
        fire = False
        latest = None
        while True:
            rpt = self._dev.read(22)
            if not rpt:
                break
            if rpt[0] == 0x33:
                latest = rpt

        if latest is not None:
            b_pressed = bool(latest[2] & 0x04)  # the B button is the trigger
            if b_pressed and not self._btn_prev:
                fire = True
            self._btn_prev = b_pressed

            aim = self._aim_from_ir(latest[6:18])
            if aim is not None:
                self._x, self._y = aim

        return AimState(x=self._x, y=self._y, fire=fire)

    @staticmethod
    def _aim_from_ir(ir: bytes):
        """12 IR bytes (4 dots × 3) -> an averaged aim point in 0..1.

        A STUB, like the one in the ESP32 firmware: average the visible dots, map
        the camera's raw range onto 0..1, invert X. A proper four-corner
        homography ("aim at the corners" calibration) is a TODO, to land together
        with the IR beacons.
        """
        sx = sy = 0
        n = 0
        for i in range(4):
            b0, b1, b2 = ir[i * 3], ir[i * 3 + 1], ir[i * 3 + 2]
            if b0 == IR_ABSENT and b1 == IR_ABSENT:
                continue
            x = b0 | ((b2 & 0x30) << 4)
            y = b1 | ((b2 & 0xC0) << 2)
            sx += x
            sy += y
            n += 1
        if n == 0:
            return None
        nx = 1.0 - (sx / n) / 1023.0   # the camera mirrors the image — invert X
        ny = (sy / n) / 767.0
        return min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny))

    def close(self) -> None:
        try:
            self._dev.close()
        except Exception:
            pass
