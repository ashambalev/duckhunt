"""What there is to play on — screens, audio outputs, gun ports — and the picks
./play remembers between evenings (launch.json).

A screen is remembered by WHAT it is, not by SDL's number for it: that number
changes when a monitor is plugged in, unplugged or wakes up, which is the whole
reason `[scene] display = -1` came up on the wrong screen. The number is worked
out again at every start from the monitor's own vendor/model/serial; the name
and the old number are only the fallbacks.
"""

from __future__ import annotations

import ctypes
import glob
import json
import os
import subprocess
from dataclasses import asdict, dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICKS_FILE = os.path.join(ROOT, "launch.json")


@dataclass(frozen=True)
class Screen:
    index: int                  # SDL's number for it today: --display N
    name: str                   # "LG HDR 4K", "Built-in Retina Display"
    x: int                      # where it sits on the desktop, in points —
    y: int                      # what a browser's --window-position means
    w: int
    h: int
    key: str = ""               # vendor:model:serial, stable across replugs

    @property
    def label(self) -> str:
        return f"{self.name} — {self.w}x{self.h}"


def screens(pygame) -> list[Screen]:
    """Every connected screen, by SDL's numbering. pygame's display must be up.

    SDL gives the sizes and positions; macOS gives what each one is called
    (SDL's own names come out as "0", "1"). The two are matched by position,
    which is the one thing both of them agree on.
    """
    sizes = pygame.display.get_desktop_sizes()
    bounds = _sdl_bounds(pygame, len(sizes))
    mac = _mac_screens()
    out = []
    for i, (w, h) in enumerate(sizes):
        x, y = bounds[i] if i < len(bounds) else (0, 0)
        name, key = mac.get((x, y), (f"Screen {i}", ""))
        out.append(Screen(i, name, x, y, w, h, key))
    return out


def _sdl_bounds(pygame, n: int) -> list[tuple[int, int]]:
    """Each display's top-left, from the SDL pygame itself is running on."""
    class Rect(ctypes.Structure):
        _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int),
                    ("w", ctypes.c_int), ("h", ctypes.c_int)]
    try:
        here = os.path.join(os.path.dirname(pygame.__file__), ".dylibs")
        sdl = ctypes.CDLL(glob.glob(os.path.join(here, "libSDL2-2*"))[0])
        out = []
        for i in range(n):
            r = Rect()
            sdl.SDL_GetDisplayBounds(i, ctypes.byref(r))
            out.append((r.x, r.y))
        return out
    except Exception:                                   # noqa: BLE001
        return []


def _mac_screens() -> dict[tuple[int, int], tuple[str, str]]:
    """(x, y) of each screen -> (its name, vendor:model:serial). {} off a Mac."""
    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    class Size(ctypes.Structure):
        _fields_ = [("w", ctypes.c_double), ("h", ctypes.c_double)]

    class CGRect(ctypes.Structure):
        _fields_ = [("origin", Point), ("size", Size)]

    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/"
                         "CoreGraphics")
        cg.CGDisplayBounds.restype = CGRect
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        ids, n = (ctypes.c_uint32 * 16)(), ctypes.c_uint32()
        cg.CGGetActiveDisplayList(16, ids, ctypes.byref(n))
    except Exception:                                   # noqa: BLE001
        return {}
    names = _profiler_names()
    out = {}
    for d in ids[:n.value]:
        r = cg.CGDisplayBounds(d)
        key = (f"{cg.CGDisplayVendorNumber(d)}:{cg.CGDisplayModelNumber(d)}:"
               f"{cg.CGDisplaySerialNumber(d)}")
        name = names.get(d) or ("Built-in display" if cg.CGDisplayIsBuiltin(d)
                                else "External display")
        out[(int(r.origin.x), int(r.origin.y))] = (name, key)
    return out


def _profiler_names() -> dict[int, str]:
    """CGDirectDisplayID -> the monitor's own name, as System Settings shows it."""
    try:
        raw = subprocess.run(["system_profiler", "SPDisplaysDataType", "-json"],
                             capture_output=True, text=True, timeout=10).stdout
        out = {}
        for gpu in json.loads(raw).get("SPDisplaysDataType", []):
            for d in gpu.get("spdisplays_ndrvs", []):
                if str(d.get("_spdisplays_displayID", "")).isdigit():
                    out[int(d["_spdisplays_displayID"])] = d["_name"]
        return out
    except Exception:                                   # noqa: BLE001
        return {}


def find_screen(saved: dict | None, available: list[Screen]) -> Screen | None:
    """The screen a remembered pick means today: the same monitor if it is
    connected (vendor/model/serial), else one by that name, else the same
    number. None when there is nothing to go on."""
    if not saved:
        return None
    for test in ("key", "name", "index"):
        want = saved.get(test)
        if want in (None, ""):
            continue
        hits = [s for s in available if getattr(s, test) == want]
        if len(hits) == 1:
            return hits[0]
    return None


def gun_ports() -> list[str]:
    """Serial ports the ESP32 bridge could be on — the CP210x boards show up as
    usbserial, the native-USB ones as usbmodem."""
    return sorted(glob.glob("/dev/tty.usbserial*") +
                  glob.glob("/dev/tty.usbmodem*"))


def load_picks(path: str = PICKS_FILE) -> dict:
    """What was picked last time; {} the first time, or if the file is broken."""
    try:
        with open(path, encoding="utf-8") as f:
            picks = json.load(f)
        return picks if isinstance(picks, dict) else {}
    except (OSError, ValueError):
        return {}


def save_picks(picks: dict, path: str = PICKS_FILE) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(picks, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def remember(screen: Screen | None) -> dict | None:
    """A screen as launch.json keeps it."""
    if screen is None:
        return None
    s = asdict(screen)
    return {k: s[k] for k in ("key", "name", "index")}
