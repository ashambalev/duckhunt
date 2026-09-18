"""The sight's own correction: where the gun says it points vs where it is aimed.

The beacon homography puts the crosshair where the CAMERA is looking. The player
looks down the iron sights, and those are not the camera: they sit a couple of
centimetres above and behind it, the barrel is not perfectly parallel to the
lens, and the beacon rectangle in settings.toml is a measurement of taped-up
LEDs rather than a law of nature. All of that adds up to a crosshair that is a
steady distance away from what the front sight is covering — which is invisible
while the crosshair is on screen (you just aim with it) and murder as soon as it
is off.

So it gets measured instead of guessed. The player shoots five round targets —
centre and four corners — aiming with the sights, and every shot gives one pair:
what the gun reported, and where the gun was actually pointed. `fit()` turns
those pairs into an affine map, `Calibration.apply()` is what the game then runs
every frame.

**Why affine and not just an offset.** A pure shift fixes the sights' own
parallax and nothing else. The other two errors on the list are not shifts: a
beacon rectangle measured 3 % too wide is a SCALE error that is zero in the
middle and worst at the edges, and a gun held with a little roll — which
everyone does — is a ROTATION. Affine is the smallest model that has all three
in it (shift, scale per axis, rotation and shear: six numbers), and five points
give ten equations for them, so it is fitted rather than solved and one shaky
shot cannot swing it far. A full homography has eight, which five points can
still take, but the two extra ones model the camera looking at the screen
off-axis — and that one the beacon homography in the firmware has already dealt
with. Fitting it here again out of five hand-held shots buys nothing and can
bend the corners badly.

The fit is checked before it is believed: a map that mirrors the screen, tilts it
25° or halves it is not a sight error, it is a misaimed round, and the fit falls
back to scale+shift and then to shift alone rather than shipping nonsense.

The file is `calibration.json` in the project root, next to scores.json. It is
written by the calibrator and read by the game; there is nothing in it worth
editing by hand, which is exactly why it is not a section in settings.toml.
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime

CALIBRATION_NAME = "calibration.json"
IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def default_path() -> str:
    """`calibration.json` in the project root (two levels above this file)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "..", CALIBRATION_NAME)


@dataclass(frozen=True)
class Calibration:
    """An affine map from what the gun reports to where it is pointed.

    `m` is the map itself, rows of a 2x3 matrix: x' = a*x + b*y + c and
    y' = d*x + e*y + f, in fractions of the picture. Everything else is the
    story of how it was measured — kept because a calibration whose geometry no
    longer matches the screen it was made on is worse than none, and because
    another round can be added to the same points later.
    """

    m: tuple = IDENTITY
    model: str = "none"        # affine | scale | offset | none
    made: str = ""             # when it was measured, ISO minutes
    rounds: int = 0            # how many passes over the five targets went in
    before: float = 0.0        # mean error before the correction, picture widths
    residual: float = 0.0      # ... and what is left after it (RMS)
    steady: float = 0.0        # the player's own scatter while holding aim
    picture: tuple = (0, 0)    # the picture it was measured on, px
    display: tuple = (0, 0)    # ... on that display, px
    frame: str = ""            # [gun] frame at the time
    beacons: tuple = (1.0, 1.0, 0.5, 0.5)   # ... and beacon_w/h/cx/cy
    points: tuple = ()         # every (reported x, y, aimed x, y) that went in
    dropped: int = 0           # ... of which this many were left out as fumbles
    limit: float = 0.0         # the residual past which a shot was called a fumble

    # ---- using it ----------------------------------------------------------

    def apply(self, x: float, y: float) -> tuple[float, float]:
        a, b, c, d, e, f = self.m
        return a * x + b * y + c, d * x + e * y + f

    @property
    def active(self) -> bool:
        return self.model != "none"

    # ---- reading it --------------------------------------------------------

    @property
    def shift(self) -> tuple[float, float]:
        """How far the correction moves the centre of the picture — the sights'
        parallax, which is the part a human can feel."""
        x, y = self.apply(0.5, 0.5)
        return x - 0.5, y - 0.5

    @property
    def scale_x(self) -> float:
        a, _, _, d, _, _ = self.m
        return math.hypot(a, d)

    @property
    def scale_y(self) -> float:
        _, b, _, _, e, _ = self.m
        return math.hypot(b, e)

    @property
    def tilt(self) -> float:
        """Degrees of roll the fit took out — a gun held a little sideways."""
        a, _, _, d, _, _ = self.m
        return math.degrees(math.atan2(d, a))

    def describe(self) -> str:
        """One line for the startup log and the results screen."""
        if not self.active:
            return "no sight calibration"
        dx, dy = self.shift
        drops = (f", {self.dropped} shot{'s' if self.dropped != 1 else ''} "
                 "left out of the fit" if self.dropped else "")
        return (f"{self.model}: shift {100 * dx:+.1f}% x {100 * dy:+.1f}%, "
                f"scale {self.scale_x:.3f} x {self.scale_y:.3f}, "
                f"tilt {self.tilt:+.1f}deg, "
                f"{self.rounds} round{'s' if self.rounds != 1 else ''} "
                f"({len(self.points)} shots), "
                f"{100 * self.before:.1f}% off -> {100 * self.residual:.1f}% left"
                f"{drops}{', ' + self.made if self.made else ''}")

    def mismatch(self, picture, display, gun) -> str | None:
        """What changed since this was measured, or None if nothing did.

        The correction is in fractions of the PICTURE, so the picture changing
        size is survivable — but the beacon settings changing is not: those
        decide what the gun's numbers mean in the first place, and a correction
        fitted on top of the old meaning is then measuring the wrong thing
        twice. Worth a warning either way; the player is the one who knows
        whether the gun also moved.
        """
        if not self.active:
            return None
        beacons = (gun.beacon_w, gun.beacon_h, gun.beacon_cx, gun.beacon_cy)
        if self.frame and (self.frame != gun.frame
                           or tuple(self.beacons) != beacons):
            return (f"measured with [gun] frame = \"{self.frame}\" and beacons "
                    f"{self.beacons[0]:g}x{self.beacons[1]:g} — settings.toml "
                    f"now says \"{gun.frame}\" and {gun.beacon_w:g}x"
                    f"{gun.beacon_h:g}; calibrate again")
        if tuple(self.picture) not in ((0, 0), tuple(picture)):
            return (f"measured on a {self.picture[0]}x{self.picture[1]} picture, "
                    f"this one is {picture[0]}x{picture[1]} — still roughly "
                    "right, but worth another round")
        return None

    # ---- the file ----------------------------------------------------------

    def to_dict(self) -> dict:
        return {"model": self.model, "matrix": list(self.m), "made": self.made,
                "dropped": self.dropped, "limit": round(self.limit, 5),
                "rounds": self.rounds, "before": round(self.before, 5),
                "residual": round(self.residual, 5), "steady": round(self.steady, 5),
                "picture": list(self.picture), "display": list(self.display),
                "frame": self.frame, "beacons": list(self.beacons),
                "points": [[round(v, 5) for v in p] for p in self.points]}

    @classmethod
    def from_dict(cls, raw: dict) -> "Calibration":
        m = tuple(float(v) for v in raw["matrix"])
        if len(m) != 6:
            raise ValueError("matrix must have six numbers")
        return cls(m=m, model=str(raw.get("model", "affine")),
                   made=str(raw.get("made", "")),
                   rounds=int(raw.get("rounds", 0)),
                   dropped=int(raw.get("dropped", 0)),
                   limit=float(raw.get("limit", 0.0)),
                   before=float(raw.get("before", 0.0)),
                   residual=float(raw.get("residual", 0.0)),
                   steady=float(raw.get("steady", 0.0)),
                   picture=tuple(raw.get("picture", (0, 0))),
                   display=tuple(raw.get("display", (0, 0))),
                   frame=str(raw.get("frame", "")),
                   beacons=tuple(raw.get("beacons", (1.0, 1.0, 0.5, 0.5))),
                   points=tuple(tuple(float(v) for v in p)
                                for p in raw.get("points", ())))


def load(path: str | None = None) -> Calibration:
    """Read the correction. Missing or broken file = none, and the game plays on."""
    path = path or default_path()
    if not os.path.exists(path):
        return Calibration()
    try:
        with open(path, encoding="utf-8") as f:
            return Calibration.from_dict(json.load(f))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"{CALIBRATION_NAME}: could not be read ({exc}) — playing "
              "without the sight correction", file=sys.stderr)
        return Calibration()


def save(calib: Calibration, path: str | None = None) -> bool:
    """Write it through a temp file, so an interrupted write keeps the old one."""
    path = path or default_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(calib.to_dict(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        print(f"{CALIBRATION_NAME}: could not be written ({exc})", file=sys.stderr)
        return False


# ---- the fit ---------------------------------------------------------------

def _solve3(S, b):
    """Gaussian elimination with partial pivoting on a 3x3 — None if singular."""
    a = [row[:] + [rhs] for row, rhs in zip(S, b)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            return None
        a[col], a[piv] = a[piv], a[col]
        for r in range(3):
            if r == col:
                continue
            k = a[r][col] / a[col][col]
            for c in range(col, 4):
                a[r][c] -= k * a[col][c]
    return [a[i][3] / a[i][i] for i in range(3)]


def _affine(points):
    """Least squares over all the shots: the six numbers, or None."""
    if len(points) < 4:
        return None
    S = [[0.0] * 3 for _ in range(3)]
    bx = [0.0] * 3
    by = [0.0] * 3
    for rx, ry, tx, ty in points:
        v = (rx, ry, 1.0)
        for i in range(3):
            for j in range(3):
                S[i][j] += v[i] * v[j]
            bx[i] += v[i] * tx
            by[i] += v[i] * ty
    row_x = _solve3(S, bx)
    row_y = _solve3(S, by)
    if row_x is None or row_y is None:
        return None
    return (row_x[0], row_x[1], row_x[2], row_y[0], row_y[1], row_y[2])


def _line(vals, targets):
    """t = s*r + k on one axis, least squares. None if the shots did not spread."""
    n = len(vals)
    mr = sum(vals) / n
    mt = sum(targets) / n
    den = sum((r - mr) ** 2 for r in vals)
    if den < 1e-6:            # every shot at the same place on this axis
        return None
    s = sum((r - mr) * (t - mt) for r, t in zip(vals, targets)) / den
    return s, mt - s * mr


def _scale(points):
    """Shift and a scale per axis — no rotation, no shear. The fallback when the
    affine fit comes out looking like something other than a sight error."""
    if len(points) < 3:
        return None
    x = _line([p[0] for p in points], [p[2] for p in points])
    y = _line([p[1] for p in points], [p[3] for p in points])
    if x is None or y is None:
        return None
    return (x[0], 0.0, x[1], 0.0, y[0], y[1])


def _offset(points):
    """Just the shift: the mean of how far every shot missed by."""
    if not points:
        return None
    n = len(points)
    dx = sum(p[2] - p[0] for p in points) / n
    dy = sum(p[3] - p[1] for p in points) / n
    return (1.0, 0.0, dx, 0.0, 1.0, dy)


def _sane(m) -> bool:
    """Is this a sight error, or a misaimed round?

    A correction is allowed to shift the picture by a third of it, scale it by
    half or double and roll it 25 degrees. Past that the numbers are not
    describing a gun any more — a mirrored or wildly sheared map is what you get
    when two of the five shots went to the wrong target, and it would make the
    game unplayable in a way that looks like the hardware broke.
    """
    a, b, c, d, e, f = m
    sx, sy = math.hypot(a, d), math.hypot(b, e)
    if not (0.5 <= sx <= 2.0 and 0.5 <= sy <= 2.0):
        return False
    if a * e - b * d <= 0:                      # mirrored
        return False
    if abs(math.degrees(math.atan2(d, a))) > 25:
        return False
    shear = (a * b + d * e) / (sx * sy)         # 0 when the axes stay square
    if abs(math.degrees(math.asin(max(-1.0, min(1.0, shear))))) > 20:
        return False
    dx, dy = a * 0.5 + b * 0.5 + c - 0.5, d * 0.5 + e * 0.5 + f - 0.5
    return math.hypot(dx, dy) <= 0.35


def errors(m, points, aspect: float = 1.0) -> list[dict]:
    """Per shot: how far off it was, before the correction and after it.

    Distances come out in fractions of the picture's WIDTH, with the vertical
    scaled by `aspect` (picture height / width) — otherwise 3 % across and 3 %
    down are added up as if they were the same distance, and on a 16:9 picture
    they differ by nearly a factor of two.
    """
    out = []
    for rx, ry, tx, ty in points:
        ax = m[0] * rx + m[1] * ry + m[2]
        ay = m[3] * rx + m[4] * ry + m[5]
        out.append({
            "target": (tx, ty), "aim": (rx, ry), "fixed": (ax, ay),
            "dx": rx - tx, "dy": ry - ty,
            "before": math.hypot(rx - tx, (ry - ty) * aspect),
            "after": math.hypot(ax - tx, (ay - ty) * aspect),
        })
    return out


def _best(points):
    """The richest model that both solves and looks like a gun."""
    for name, solve in (("affine", _affine), ("scale", _scale),
                        ("offset", _offset)):
        candidate = solve(points)
        if candidate is not None and _sane(candidate):
            return name, candidate
    return "none", IDENTITY


# How far out a shot has to be before the fit stops listening to it. Least
# squares has no defence of its own here: one shot put on the wrong target is a
# quarter of the screen away, its error is squared like everyone else's, and it
# drags the whole map — measured, a single fumble among ten shots took the
# residual from 0.5 % to 15 %, which is a calibration that makes the gun worse.
# So the fit is run once, and any shot this far past the middle of the pack is
# left out of a second one. The floor is what keeps an unusually steady round
# from throwing away its own worst shot: at four times a median of 0.7 % the
# limit would be under 3 %, and a shot 3 % out is a hand, not a fumble.
DROP_FACTOR = 4.0
DROP_FLOOR = 0.04


def fit(points, aspect: float = 1.0) -> Calibration:
    """Every (reported x, y, aimed x, y) there is -> the correction to apply.

    Tries the full affine first and walks down to shift-only, taking the first
    model that both solves and looks like a gun, then throws out the fumbles and
    does it again. Reports what it settled on and what it left behind, because
    "the calibration is saved" and "the calibration helps" are different claims
    and only the residual can tell them apart.

    Dropped shots stay in `points` — the file keeps everything that was ever
    shot, and the next round refits from all of it. They are dropped from the
    FIT, not from the record.
    """
    points = [tuple(p) for p in points]
    model, m = _best(points)
    rows = errors(m, points, aspect)
    res = sorted(r["after"] for r in rows)
    median = res[len(res) // 2] if res else 0.0
    limit = max(DROP_FACTOR * median, DROP_FLOOR)
    keep = [p for p, r in zip(points, rows) if r["after"] <= limit]
    dropped = 0
    if 4 <= len(keep) < len(points):
        model, m = _best(keep)
        rows = errors(m, keep, aspect)
        dropped = len(points) - len(keep)
    n = max(1, len(rows))
    before = sum(r["before"] for r in rows) / n
    residual = math.sqrt(sum(r["after"] ** 2 for r in rows) / n)
    return Calibration(m=m, model=model, before=before, residual=residual,
                       points=tuple(points), dropped=dropped, limit=limit,
                       made=datetime.now().strftime("%Y-%m-%d %H:%M"))


# Where the residual stops mattering: the shot has a radius ([gun] spread), and
# a correction whose leftover error is well inside it cannot cost a duck. So the
# grade is read against that rather than against a round number — the same
# residual is excellent on a forgiving hit zone and poor on a pinpoint one.
GRADES = (
    (0.25, "EXCELLENT", "well inside the shot's own radius"),
    (0.50, "GOOD", "comfortably inside the shot's radius"),
    (1.00, "USABLE", "about the size of the shot itself"),
    (1e9, "POOR", "bigger than the shot — shoot another round"),
)


def grade(residual: float, spread: float) -> tuple[str, str, float]:
    """(word, why, residual as a share of the shot's radius)."""
    ref = spread if spread > 0 else 0.02     # a pinpoint crosshair still needs a ruler
    share = residual / ref
    for limit, word, why in GRADES:
        if share <= limit:
            return word, why, share
    return GRADES[-1][1], GRADES[-1][2], share
