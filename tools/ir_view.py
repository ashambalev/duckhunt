#!/usr/bin/env python3
"""What the gun's camera actually sees — live, and written to a log.

The bridge firmware reports its raw IR blobs on the same serial port as the aim
(`# dots n=4 (x,y) ...`). This tool asks for one report per camera frame, draws
them, and records everything to `logs/ir_view_<timestamp>.jsonl` so a test run
can be read back afterwards.

Two panels:
  * the CAMERA — the sensor's own 1024x768 space, the blobs it reports, and the
    quad the firmware builds from them. Swing the gun right and these dots go
    left: the camera is looking out of the barrel, so the picture slides against
    the movement. That is not the aim, and it is not inverted — the aim is the
    lower panel (green = a clean rectangle, so the
    homography is solving; amber = fewer than four dots or a rejected quad, so
    the firmware has fallen back to the coarse centroid aim);
  * the SCREEN — where the firmware says the gun is pointing, 0..1 in both axes,
    with a short trail. The four beacons span the whole display, so this panel is
    the display; the inner rectangle is the game's letterboxed picture, which is
    where the ducks actually are (the pixel art is scaled by a whole number, so
    black bars are left over — see docs/BUILD.md).

Running it (the game must NOT be running — the port takes one reader):

    .venv/bin/python tools/ir_view.py                        # the default port
    .venv/bin/python tools/ir_view.py /dev/tty.usbserial-0001
    .venv/bin/python tools/ir_view.py --no-window            # log only, no pygame
    .venv/bin/python tools/ir_view.py --summary logs/ir_view_*.jsonl   # read a log back

X and Y flip the firmware's axis flags on the spot, without reflashing: point at
the screen, sweep, and press the key for whichever axis runs backwards. The
firmware prints the new setting, so the log always says what it was recorded
under. Whatever it is when the crosshair tracks the barrel is the right answer;
copy it into CAM_MIRROR_X / CAM_MIRROR_Y so it survives the next flash.

Tagging: HOLD 1 2 3 4 while aiming at that corner of the PHYSICAL screen, where
the LEDs are, not the corner of the picture (5 = the centre). The tag lasts only
while the key is down, so a forgotten key cannot label a whole session. Three
seconds per corner is plenty. C clears the trail, Q/Esc quits.

The tags are what make a log worth reading: with them the summary can say whether
the firmware's axis flags (CAM_MIRROR_X / CAM_MIRROR_Y) are the right way round.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from collections import deque
from pathlib import Path

CAM_W, CAM_H = 1024, 768
DEFAULT_PORT = "/dev/tty.usbserial-0001"
BAUD = 115200
REPO = Path(__file__).resolve().parent.parent

# "# dots n=3 (512,384,5) (600,390,4)" — the third number is the blob's size,
# 0..15, and it is what tells a dim beacon from a dead one. Older logs have pairs
# without it, so it stays optional.
DOTS_RE = re.compile(r"^#\s*dots\s+n=(\d+)(.*)$")
PAIR_RE = re.compile(r"\((\d+),(\d+)(?:,(\d+))?\)")

# The four corners a sample can be tagged with, and where they should land on
# screen if the firmware's mapping is right.
TARGETS = {
    "TL": (0.0, 0.0), "TR": (1.0, 0.0),
    "BR": (1.0, 1.0), "BL": (0.0, 1.0),
    "C":  (0.5, 0.5),
}
TAG_KEYS = {"1": "TL", "2": "TR", "3": "BR", "4": "BL", "5": "C"}
# Kept in step with CAM_MIRROR_X / CAM_MIRROR_Y in the bridge firmware, so the
# summary can name the *physical* beacon that goes missing rather than a corner of
# the sensor image. Wrong here only mislabels that one sentence.
CAM_MIRROR_X, CAM_MIRROR_Y = False, True
# KEYUP does not carry a unicode character on every platform, so match key codes
# too: pygame.K_1 .. pygame.K_5 are 49..53.
TAG_KEY_CODES = set(range(49, 54))


# --------------------------------------------------------------------------
# the firmware's own dot sorting, mirrored here so the view shows its decision
# --------------------------------------------------------------------------
def desktop_size():
    """The display the game will go fullscreen on, as (w, h) — or None."""
    try:
        import pygame

        pygame.init()
        try:
            return list(pygame.display.get_desktop_sizes()[0])
        except Exception:
            info = pygame.display.Info()
            return [info.current_w, info.current_h]
    except Exception:
        return None


def scene_frac():
    """Where the game's picture sits inside the display, in display fractions:
    (x, y, w, h). The pygame frontend scales the 256x183 background by a whole
    number and centres it, so the ducks never reach the screen's edges — this is
    the same arithmetic, so the view can draw that inner rectangle."""
    try:
        import pygame

        # get_desktop_sizes() keeps answering about the DESKTOP; display.Info()
        # starts answering about our own window once one is open.
        try:
            sw, sh = pygame.display.get_desktop_sizes()[0]
        except Exception:
            info = pygame.display.Info()
            sw, sh = info.current_w, info.current_h
        bw, bh = pygame.image.load(
            str(REPO / "assets" / "backgrounds" / "meadow.png")).get_size()
        k = max(1, min(sw // bw, sh // bh))
        w, h = bw * k, bh * k
        return ((sw - w) // 2 / sw, (sh - h) // 2 / sh, w / sw, h / sh)
    except Exception:
        return None


def missing_corner(dots):
    """Three corners of a rectangle -> the fourth, plus how rectangular the three
    actually were. Of the three, the one whose two edges meet at a right angle is
    the corner opposite the missing one, so the fourth is a + c - b."""
    best, bi = 9e9, None
    for i in range(3):
        b = dots[i]
        a, c = dots[(i + 1) % 3], dots[(i + 2) % 3]
        v1 = (a[0] - b[0], a[1] - b[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 < 1 or n2 < 1:
            continue
        cos = abs((v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2))
        if cos < best:
            best, bi = cos, i
    if bi is None:
        return None, 1.0
    b = dots[bi]
    a, c = dots[(bi + 1) % 3], dots[(bi + 2) % 3]
    return (a[0] + c[0] - b[0], a[1] + c[1] - b[1]), best


def name_beacon(x, y, cx, cy):
    """An image position -> the beacon's place on the actual screen."""
    right = x > cx
    below = y > cy
    if CAM_MIRROR_X:
        right = not right
    if CAM_MIRROR_Y:
        below = not below
    return ("bottom" if below else "top") + "-" + ("right" if right else "left")


def sort_quad(dots):
    """Four dots -> [top-left, top-right, bottom-right, bottom-left] in image
    space, or None if two of them share a quadrant (not a clean rectangle)."""
    if len(dots) != 4:
        return None
    cx = sum(p[0] for p in dots) / 4.0
    cy = sum(p[1] for p in dots) / 4.0
    slots = [None] * 4
    for x, y in dots:
        i = (2 if x > cx else 3) if y > cy else (1 if x > cx else 0)
        if slots[i] is not None:
            return None
        slots[i] = (x, y)
    return slots


# --------------------------------------------------------------------------
# serial
# --------------------------------------------------------------------------
class Bridge:
    """Line-oriented reader for the bridge, pairing each aim line with the dot
    report that follows it (the firmware prints them in that order)."""

    def __init__(self, port: str):
        import serial  # pyserial

        # Same careful open as the game: no DTR/RTS pulse, so the ESP32 is not
        # reset and the remote stays paired.
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = BAUD
        self.ser.timeout = 0
        try:
            self.ser.dtr = False
            self.ser.rts = False
        except Exception:  # a driver that does not expose the lines
            pass
        self.ser.open()
        # Opening the port resets the ESP32 (the macOS CH340 driver drives the
        # lines whatever pyserial asks), so a request sent right now is read by a
        # bootloader and lost. Ask again, and keep asking, until the reports
        # arrive at full speed.
        self.buf = b""
        self._asked = 0.0
        self.full_rate = False      # set when the firmware answers that it heard
        self.axes = "?"             # what the firmware says its axis flags are
        self.ask_for_full_rate()
        self.aim = None       # (x, y) in 0..1, or None while no beacon is seen
        self.btn = 0

    def send(self, ch: str):
        try:
            self.ser.write(ch.encode())
        except Exception:
            pass

    def ask_for_full_rate(self):
        """Ask the firmware to dump the dots on every camera report, at most once
        a second (it is one byte, and the board may still be booting)."""
        if time.time() - self._asked < 1.0:
            return
        self._asked = time.time()
        try:
            self.ser.write(b"d")
        except Exception:
            pass

    def poll(self):
        """-> (samples, status_lines) since the last call."""
        samples, status = [], []
        try:
            n = self.ser.in_waiting
            if n:
                self.buf += self.ser.read(n)
        except Exception:
            pass
        while b"\n" in self.buf:
            raw, self.buf = self.buf.split(b"\n", 1)
            line = raw.decode("utf-8", "ignore").strip()
            if not line:
                continue
            m = DOTS_RE.match(line)
            if m:
                found = PAIR_RE.findall(m.group(2))
                dots = [(int(a), int(b)) for a, b, _ in found]
                sizes = [int(c) if c else -1 for _, _, c in found]
                samples.append({"n": int(m.group(1)), "dots": dots, "sizes": sizes,
                                "aim": self.aim, "b": self.btn})
            elif line.startswith("#"):
                if "every report" in line:
                    self.full_rate = True      # the request was heard, stop asking
                if "MIRROR_X=" in line:
                    self.axes = line.split("MIRROR_X=", 1)[1].strip()
                    self.axes = "MIRROR_X=" + self.axes
                status.append(line)
            else:
                parts = line.split(",")
                try:
                    x, y, b = int(parts[0]), int(parts[1]), int(parts[2])
                except (ValueError, IndexError):
                    continue
                self.btn = b
                self.aim = None if x < 0 else (x / 1000.0, y / 1000.0)
        return samples, status

    def close(self):
        try:
            self.ser.write(b"s")  # leave the firmware dumping at the gentle rate
            self.ser.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# the window
# --------------------------------------------------------------------------
class View:
    BG = (18, 18, 24)
    INK = (225, 225, 235)
    DIM = (120, 120, 140)
    GOOD = (90, 220, 120)
    WARN = (235, 175, 70)
    DOT = (90, 220, 255)
    AIM = (255, 90, 110)

    W, H = 560, 830
    CAM_RECT = (24, 46, 512, 384)      # x, y, w, h — the camera panel
    SCR_RECT = (24, 500, 512, 288)     # the screen panel (16:9)

    def __init__(self):
        import pygame

        self.pg = pygame
        pygame.init()
        self.scene = scene_frac()      # the picture inside the display, or None
        pygame.display.set_caption("Duck Hunt — what the gun sees")
        self.surf = pygame.display.set_mode((self.W, self.H))
        self.font = pygame.font.SysFont("Menlo,Monaco,monospace", 13)
        self.big = pygame.font.SysFont("Menlo,Monaco,monospace", 16, bold=True)
        self.trail = deque(maxlen=150)

    def cam_xy(self, x, y):
        rx, ry, rw, rh = self.CAM_RECT
        return rx + x * rw / CAM_W, ry + y * rh / CAM_H

    def scr_xy(self, x, y):
        rx, ry, rw, rh = self.SCR_RECT
        return rx + x * rw, ry + y * rh

    def text(self, s, x, y, color=None, font=None):
        img = (font or self.font).render(s, True, color or self.INK)
        self.surf.blit(img, (x, y))

    def draw(self, sample, tag, rate, elapsed, log_path, four_pct, axes="?"):
        pg, s = self.pg, self.surf
        s.fill(self.BG)
        dots = sample["dots"] if sample else []
        quad = sort_quad(dots)
        solving = quad is not None

        self.text("CAMERA  1024x768, as the sensor reports it — the dots slide "
                  "AGAINST the barrel, that is normal", 24, 24, self.DIM)
        pg.draw.rect(s, (46, 46, 58), self.CAM_RECT, 1)
        # the barrel axis: the centre of the camera image
        ccx, ccy = self.cam_xy(CAM_W / 2, CAM_H / 2)
        pg.draw.line(s, (70, 70, 88), (ccx - 9, ccy), (ccx + 9, ccy))
        pg.draw.line(s, (70, 70, 88), (ccx, ccy - 9), (ccx, ccy + 9))

        if quad:
            pts = [self.cam_xy(*p) for p in quad]
            pg.draw.polygon(s, self.GOOD, pts, 1)
            for label, p in zip(("TL", "TR", "BR", "BL"), pts):
                self.text(label, p[0] + 6, p[1] - 16, self.GOOD)
        sizes = sample.get("sizes") if sample else None
        for i, (x, y) in enumerate(dots):
            px, py = self.cam_xy(x, y)
            sz = sizes[i] if sizes and i < len(sizes) else -1
            # a dim beacon reads as a small blob: draw what the sensor reported
            pg.draw.circle(s, self.DOT, (int(px), int(py)),
                           6 if sz < 0 else max(3, 3 + sz), 2)
            if sz >= 0:
                self.text(str(sz), px + 10, py + 2, self.DOT)
        if dots and not quad:
            pts = [self.cam_xy(*p) for p in dots]
            if len(pts) > 1:
                pg.draw.lines(s, self.WARN, True, pts, 1)

        n = len(dots)
        state = ("homography — 4 corners solved" if solving
                 else f"FALLBACK — {n} dot{'' if n == 1 else 's'}, aim is only a guess")
        self.text(f"dots {n}/4   {state}", 24, 438, self.GOOD if solving else self.WARN)
        self.text(f"four-dot frames this run: {four_pct:5.1f}%", 24, 458, self.DIM)

        self.text("SCREEN  where the firmware says the gun points — judge the aim "
                  "here, not above", 24, 478, self.DIM)
        pg.draw.rect(s, (46, 46, 58), self.SCR_RECT, 1)
        # the letterboxed picture: outside it there is only black bar, and the
        # game clamps the crosshair to its edge
        if self.scene:
            fx, fy, fw, fh = self.scene
            px, py = self.scr_xy(fx, fy)
            qx, qy = self.scr_xy(fx + fw, fy + fh)
            pg.draw.rect(s, (78, 78, 96), (px, py, qx - px, qy - py), 1)
            self.text("ducks", px + 5, py + 3, (78, 78, 96))
        aim = sample["aim"] if sample else None
        if aim:
            self.trail.append(aim)
        for i, (tx, ty) in enumerate(self.trail):
            f = i / max(1, len(self.trail))          # older points fade out
            shade = (int(60 + 90 * f), int(30 + 40 * f), int(45 + 55 * f))
            px, py = self.scr_xy(tx, ty)
            pg.draw.circle(s, shade, (int(px), int(py)), 2)
        if aim:
            ax, ay = self.scr_xy(*aim)
            pg.draw.line(s, self.AIM, (ax - 11, ay), (ax + 11, ay), 2)
            pg.draw.line(s, self.AIM, (ax, ay - 11), (ax, ay + 11), 2)
            note = ""
            if self.scene:
                fx, fy, fw, fh = self.scene
                inside = fx <= aim[0] <= fx + fw and fy <= aim[1] <= fy + fh
                note = "" if inside else "  (in the black bar)"
            self.text(f"{aim[0]:.3f}, {aim[1]:.3f}{note}", ax + 14, ay + 6, self.AIM)

        fire = sample and (sample["b"] & 1)
        y0 = 800
        self.text(f"{rate:5.1f} rep/s   {elapsed:6.1f}s   "
                  f"{'TRIGGER' if fire else '       '}", 24, y0 - 4,
                  self.AIM if fire else self.INK, self.big)
        if tag:
            want = TARGETS[tag]
            self.text(f"aiming at {tag} of the SCREEN "
                      f"(expect {want[0]:.1f},{want[1]:.1f}) — hold the key",
                      24, y0 + 16, self.WARN)
            wx, wy = self.scr_xy(*want)
            pg.draw.circle(s, self.WARN, (int(wx), int(wy)), 10, 1)
        else:
            self.text("hold 1 TL  2 TR  3 BR  4 BL  5 centre    X/Y flip axes  C  Q",
                      24, y0 + 16, self.DIM)
        self.text(str(log_path.relative_to(REPO)), 24, 4, self.DIM)
        self.text(axes, self.W - 190, 4, self.WARN if axes == "?" else self.DIM)
        pg.display.flip()


# --------------------------------------------------------------------------
# the log and its summary
# --------------------------------------------------------------------------
def summarize(path: Path) -> str:
    samples, statuses, t_first, t_last = [], [], None, None
    with path.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "dots" in rec:
                samples.append(rec)
                t_first = rec["t"] if t_first is None else t_first
                t_last = rec["t"]
            elif "status" in rec:
                statuses.append(rec["status"])

    out = [f"log: {path}", f"samples: {len(samples)}"]
    for rec in (json.loads(l) for l in path.open()):
        if "meta" in rec and rec["meta"].get("scene"):
            d = rec["meta"].get("desktop")
            x, y, w, h = rec["meta"]["scene"]
            out.append(f"display {d[0]}x{d[1]}, the game's picture fills "
                       f"{100*w:.0f}% x {100*h:.0f}% of it — beacons on the screen's "
                       f"corners need {1/w:.2f}x the playing distance that beacons "
                       f"on the picture's corners would")
            break
    if not samples:
        out.append("nothing was recorded — did the remote pair? statuses seen:")
        out += [f"  {s}" for s in statuses[-8:]]
        return "\n".join(out)

    dur = (t_last - t_first) or 1e-9
    counts = {i: 0 for i in range(5)}
    for r in samples:
        counts[min(4, r["n"])] += 1
    quads = sum(1 for r in samples if sort_quad([tuple(d) for d in r["dots"]]))
    out.append(f"duration: {dur:.1f}s   rate: {len(samples)/dur:.1f} reports/s")
    out.append("dots per frame: " + "  ".join(
        f"{k}:{v} ({100*v/len(samples):.0f}%)" for k, v in sorted(counts.items())))
    out.append(f"frames the homography could solve: {quads} "
               f"({100*quads/len(samples):.1f}%)")

    # the longest stretch without all four beacons — the thing that ruins aim
    worst, run_start = 0.0, None
    for r in samples:
        if r["n"] < 4:
            run_start = r["t"] if run_start is None else run_start
            worst = max(worst, r["t"] - run_start)
        else:
            run_start = None
    out.append(f"longest stretch below four dots: {worst:.2f}s")

    # How big the beacon rectangle came out in the frame — that is the distance,
    # and how much room is left before a corner slides out of view.
    widths = []
    for r in samples:
        q = sort_quad([tuple(d) for d in r["dots"]])
        if q:
            widths.append((q[1][0] - q[0][0] + q[2][0] - q[3][0]) / 2)
    if widths:
        med = statistics.median(widths)
        out.append(f"beacon rectangle in the frame: {med:.0f} px wide of {CAM_W} "
                   f"({100*med/CAM_W:.0f}% of it, range {100*min(widths)/CAM_W:.0f}"
                   f"-{100*max(widths)/CAM_W:.0f}%) — a corner slides out of view "
                   f"once that passes 50%")
        if 100 * med / CAM_W > 50:
            out.append("  -> too close: aiming anywhere but the middle pushes a "
                       "beacon out of the frame. Step back until this reads ~40%.")

    # How bright each beacon looked, using only the frames where all four were
    # seen — there every dot can be named, and a lopsided table means one LED is
    # weaker than the others rather than the whole set being dim.
    per = {}
    for r in samples:
        q = sort_quad([tuple(d) for d in r["dots"]]) if r["n"] == 4 else None
        if not q:
            continue
        cx = statistics.fmean([d[0] for d in r["dots"]])
        cy = statistics.fmean([d[1] for d in r["dots"]])
        for (x, y), sz in zip(r["dots"], r.get("sizes", [])):
            if sz >= 0:
                per.setdefault(name_beacon(x, y, cx, cy), []).append(sz)
    if per:
        out.append("")
        out.append("blob size per beacon, frames with all four (0..15; bigger is "
                   "brighter):")
        for k, v in sorted(per.items(), key=lambda kv: statistics.fmean(kv[1])):
            out.append(f"  {k:13s} mean {statistics.fmean(v):.2f}   n={len(v)}")
        means = [statistics.fmean(v) for v in per.values()]
        if max(means) > 0 and min(means) < 0.4 * max(means):
            weak = min(per.items(), key=lambda kv: statistics.fmean(kv[1]))[0]
            out.append(f"  -> the {weak} beacon is much weaker than the rest: "
                       f"its battery, its resistor, or it is aimed away from you")

    allsz = [z for r in samples for z in r.get("sizes", []) if z >= 0]
    if allsz:
        hist = {}
        for z in allsz:
            hist[z] = hist.get(z, 0) + 1
        out.append("blob sizes the sensor reported: " + "  ".join(
            f"{k}:{v}" for k, v in sorted(hist.items())) +
            "   (a beacon that only ever reads 0-1 is dim, not dead)")

    # When exactly one beacon is missing, which one — and was it out of the
    # camera's view (stand further back) or simply not seen (a dim or dead LED)?
    three = [r for r in samples if r["n"] == 3]
    if len(three) >= 20:
        named, out_of_frame = {}, 0
        for r in three:
            d, cos = missing_corner([tuple(p) for p in r["dots"]])
            if d is None or cos > 0.35:      # the three were not a rectangle's corners
                continue
            cx = (sum(p[0] for p in r["dots"]) + d[0]) / 4
            cy = (sum(p[1] for p in r["dots"]) + d[1]) / 4
            if not (0 <= d[0] < CAM_W and 0 <= d[1] < CAM_H):
                out_of_frame += 1
            name = name_beacon(d[0], d[1], cx, cy)
            named[name] = named.get(name, 0) + 1
        if named:
            top, n = max(named.items(), key=lambda kv: kv[1])
            total = sum(named.values())
            out.append("")
            out.append(f"one beacon missing in {len(three)} frames — reconstructing "
                       f"where it should have been:")
            for k, v in sorted(named.items(), key=lambda kv: -kv[1]):
                out.append(f"  the {k} beacon: {v} frames ({100*v/total:.0f}%)")
            out.append(f"  {100*out_of_frame/total:.0f}% of those were outside the "
                       f"camera's frame (= stand further back); the rest were inside "
                       f"it and simply not seen (= that LED is dim, misaimed or dead)")
            if n / total > 0.6 and out_of_frame / total < 0.25:
                out.append(f"  -> suspect the {top} LED itself, not the distance")

    drops = sum(1 for s in statuses if "disconnect" in s.lower())
    if drops:
        out.append(f"the remote dropped the link {drops}x during the run "
                   f"(fresh AA cells are the usual cure)")

    # THE ONE-BEACON PASS: light a single corner, hold its key, repeat. Every dot
    # in view then belongs to a beacon whose place on the screen is known, which
    # settles both open questions at once — how bright each one is, and which way
    # the sensor's axes run against the screen's.
    solo, dark = {}, {}
    for r in samples:
        tag = r.get("tag")
        if not tag:
            continue
        if r["n"] == 1 and r["dots"]:
            sz = (r.get("sizes") or [-1])[0]
            solo.setdefault(tag, []).append((r["dots"][0], sz))
        elif r["n"] == 0:
            dark[tag] = dark.get(tag, 0) + 1
    # Only when it really was a one-beacon pass: a normal aiming run throws off
    # the odd single-dot frame too, and two of those prove nothing.
    steady = [t for t, v in solo.items() if len(v) >= 15]
    multi = sum(1 for r in samples if r["n"] >= 2)
    # ...and only when the run really was one beacon at a time. An ordinary
    # corner-aiming run also leaves single-dot frames behind (the others slide out
    # of view), and reading those as a beacon pass produced a confident, wrong
    # answer about the axes once already.
    if (len(steady) + len([t for t, n in dark.items() if n >= 15]) >= 2
            and multi < 0.05 * max(1, len(samples))):
        out.append("")
        out.append("one beacon at a time — each corner as the sensor saw it:")
        for tag in ("TL", "TR", "BR", "BL", "C"):
            pts = solo.get(tag)
            if not pts:
                if tag in dark:
                    out.append(f"  {tag}: nothing seen in {dark[tag]} frames — that "
                               f"beacon is dead, or it was not switched on")
                continue
            xs = [p[0][0] for p in pts]
            ys = [p[0][1] for p in pts]
            szs = [p[1] for p in pts if p[1] >= 0]
            blind = dark.get(tag, 0)
            out.append(f"  {tag}: n={len(pts):4d}  sensor "
                       f"({statistics.fmean(xs):4.0f},{statistics.fmean(ys):4.0f})"
                       + (f"  blob size {statistics.fmean(szs):.2f}" if szs else "")
                       + (f"   (plus {blind} frames where it vanished)" if blind else ""))
        per_tag = {t: statistics.fmean([q[1] for q in v if q[1] >= 0])
                   for t, v in solo.items() if any(q[1] >= 0 for q in v)}
        if len(per_tag) >= 2:
            weak = min(per_tag, key=per_tag.get)
            strong = max(per_tag, key=per_tag.get)
            if per_tag[weak] < 0.6 * per_tag[strong]:
                out.append(f"  -> {weak} is the weak one: blob size "
                           f"{per_tag[weak]:.2f} against {per_tag[strong]:.2f} "
                           f"for {strong}")

        # Which way do the axes run? Compare corners that differ along one axis.
        def axis(i, lo_tags, hi_tags, flag):
            lo = [statistics.fmean([q[0][i] for q in solo[t]])
                  for t in lo_tags if t in solo]
            hi = [statistics.fmean([q[0][i] for q in solo[t]])
                  for t in hi_tags if t in solo]
            if not lo or not hi:
                return f"  {flag}: needs both sides of that axis lit in turn"
            a, b = statistics.fmean(lo), statistics.fmean(hi)
            with_screen = b > a
            return (f"  {flag} should be {'false' if with_screen else 'true'} — "
                    f"the sensor's axis runs {'with' if with_screen else 'against'} "
                    f"the screen's ({a:.0f} vs {b:.0f})")

        out.append("")
        out.append("axis orientation, straight from the one-beacon pass:")
        out.append(axis(0, ("TL", "BL"), ("TR", "BR"), "CAM_MIRROR_X"))
        out.append(axis(1, ("TL", "TR"), ("BL", "BR"), "CAM_MIRROR_Y"))

    # Only the frames the homography actually solved can say anything about the
    # aim: on the fallback the numbers are a relative guess, and averaging them in
    # would quietly poison the axis check below.
    tagged, tagged_fallback = {}, 0
    for r in samples:
        if not (r.get("tag") and r.get("aim")):
            continue
        if r["n"] == 4 and sort_quad([tuple(d) for d in r["dots"]]):
            tagged.setdefault(r["tag"], []).append(r["aim"])
        else:
            tagged_fallback += 1
    if tagged:
        out.append("")
        out.append("tagged aim (solved frames only, while you aimed at a corner):")
        if tagged_fallback:
            out.append(f"  ({tagged_fallback} tagged samples ignored — fewer than "
                       f"four dots, so the aim was only the fallback guess)")
        for tag, pts in sorted(tagged.items()):
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ex, ey = TARGETS[tag]
            sx = statistics.pstdev(xs) if len(xs) > 1 else 0.0
            sy = statistics.pstdev(ys) if len(ys) > 1 else 0.0
            out.append(f"  {tag}: n={len(pts):4d}  reported "
                       f"({statistics.fmean(xs):.3f} ±{sx:.3f}, "
                       f"{statistics.fmean(ys):.3f} ±{sy:.3f})   expected ({ex:.1f}, {ey:.1f})")

        # Do the axes run the right way? Compare the tags that differ along each
        # axis; if aiming further right reported a smaller x, the flag is wrong.
        def verdict(axis: int, flag: str) -> str:
            lo = [statistics.fmean([p[axis] for p in pts])
                  for tag, pts in tagged.items() if TARGETS[tag][axis] < 0.5]
            hi = [statistics.fmean([p[axis] for p in pts])
                  for tag, pts in tagged.items() if TARGETS[tag][axis] > 0.5]
            if not lo or not hi:
                return f"  {flag}: not enough tags to tell (need both sides of the axis)"
            d = statistics.fmean(hi) - statistics.fmean(lo)
            if abs(d) < 0.15:
                return f"  {flag}: inconclusive — the two sides differ by only {d:+.3f}"
            return (f"  {flag}: correct as it is (separation {d:+.3f})" if d > 0 else
                    f"  {flag}: WRONG WAY ROUND — flip it in the firmware ({d:+.3f})")

        out.append("")
        out.append("axis check:")
        out.append(verdict(0, "CAM_MIRROR_X"))
        out.append(verdict(1, "CAM_MIRROR_Y"))

        # how far off the aim landed, once the axes are right
        errs = [max(abs(p[0] - TARGETS[t][0]), abs(p[1] - TARGETS[t][1]))
                for t, pts in tagged.items() for p in pts]
        out.append(f"  worst distance from the tagged corner: {max(errs):.3f} "
                   f"(median {statistics.median(errs):.3f}) — only meaningful "
                   f"once the two flags above are right")
    else:
        out.append("")
        out.append(f"no usable tagged samples ({tagged_fallback} were tagged but "
                   f"never had four dots) — hold 1..5 while aiming at a known "
                   f"corner, with all four beacons in view, and the axis check runs")
    if statuses:
        out.append("")
        out.append("firmware said:")
        seen = []
        for s in statuses:
            if s not in seen:
                seen.append(s)
        out += [f"  {s}" for s in seen[:10]]
    return "\n".join(out)


# --------------------------------------------------------------------------
def run(port: str, window: bool) -> Path:
    log_dir = REPO / "logs"
    log_dir.mkdir(exist_ok=True)
    path = log_dir / time.strftime("ir_view_%Y%m%d_%H%M%S.jsonl")
    log = path.open("w", buffering=1)
    # The scene rectangle goes into the log too: where the beacons should sit, and
    # how far back to stand, both follow from it.
    scene = scene_frac()
    log.write(json.dumps({"t": 0.0, "meta": {"port": port, "cam": [CAM_W, CAM_H],
                                             "desktop": desktop_size(),
                                             "scene": scene,
                                             "started": time.strftime("%F %T")}}) + "\n")

    bridge = Bridge(port)
    view = View() if window else None
    print(f"Logging to {path}")
    if not window:
        print("No window (--no-window): press Ctrl-C to stop.")

    t0 = time.time()
    tag = None
    last = None
    recent = deque(maxlen=120)
    four = total = 0
    try:
        while True:
            now = time.time() - t0
            samples, statuses = bridge.poll()
            for s in statuses:
                log.write(json.dumps({"t": round(now, 3), "status": s}) + "\n")
                print("  " + s, flush=True)
            for s in samples:
                total += 1
                four += (s["n"] == 4)
                recent.append(now)
                rec = {"t": round(now, 3), "n": s["n"], "dots": s["dots"],
                       "sizes": s["sizes"],
                       "aim": [round(v, 4) for v in s["aim"]] if s["aim"] else None,
                       "b": s["b"]}
                if tag:
                    rec["tag"] = tag
                log.write(json.dumps(rec) + "\n")
                last = s
            rate = (len(recent) / (recent[-1] - recent[0])
                    if len(recent) > 1 and recent[-1] > recent[0] else 0.0)
            if not bridge.full_rate:        # the reset ate the request — ask again
                bridge.ask_for_full_rate()

            if view:
                pg = view.pg
                for e in pg.event.get():
                    if e.type == pg.QUIT:
                        raise KeyboardInterrupt
                    if e.type == pg.KEYDOWN:
                        ch = e.unicode.lower()
                        if e.key in (pg.K_ESCAPE,) or ch == "q":
                            raise KeyboardInterrupt
                        if ch in TAG_KEYS:
                            tag = TAG_KEYS[ch]
                            log.write(json.dumps({"t": round(now, 3),
                                                  "marker": tag}) + "\n")
                        elif ch == "c":
                            view.trail.clear()
                        elif ch in ("x", "y"):
                            # flip that axis in the firmware, right now
                            bridge.send(ch)
                    if e.type == pg.KEYUP and tag:
                        # the tag only lasts while the key is held
                        if e.unicode.lower() in TAG_KEYS or e.key in TAG_KEY_CODES:
                            tag = None
                view.draw(last, tag, rate, now, path,
                          100.0 * four / total if total else 0.0, bridge.axes)
                pg.time.wait(8)
            else:
                if total and total % 50 == 0:
                    print(f"\r  {now:6.1f}s  {total} samples  "
                          f"{100*four/total:5.1f}% four-dot  {rate:5.1f}/s",
                          end="", flush=True)
                time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()
        if view:
            view.pg.quit()
        log.close()
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("port", nargs="?", default=DEFAULT_PORT)
    ap.add_argument("--no-window", action="store_true",
                    help="record the log without opening the pygame window")
    ap.add_argument("--summary", metavar="LOG",
                    help="print the summary of an existing log and exit")
    args = ap.parse_args()

    if args.summary:
        print(summarize(Path(args.summary)))
        return

    window = not args.no_window
    if window:
        try:
            import pygame  # noqa: F401
        except ImportError:
            print("pygame is not installed — running without the window.")
            window = False

    path = run(args.port, window)
    print("\n" + "=" * 72)
    text = summarize(path)
    print(text)
    with path.open("a") as fh:
        fh.write(json.dumps({"summary": text}) + "\n")
    print("=" * 72)
    print(f"\nThe log is {path} — hand it over and it can be read back with:\n"
          f"  .venv/bin/python tools/ir_view.py --summary {path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
