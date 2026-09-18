"""Sighting in the gun: five round targets, shot with the sights, not the crosshair.

The whole point of the exercise is that the CROSSHAIR IS OFF while you shoot it.
A crosshair on screen makes this test circular — you would move the barrel until
the crosshair covers the bull, and the only thing measured would be your ability
to follow a dot. So the crosshair is hidden, you put the front sight on the bull
the way you would on a real gun, and what gets recorded is the gap between where
the gun says it is looking and where you actually pointed it.

One round is five shots: the centre first, then the four corners. Between the
trigger and the shot going off there is a jerk — the hand pulls, the barrel
dips — so the reading is NOT the position at the moment the trigger was read.
It is the median of the aim over the quarter second BEFORE that, stopping 40 ms
short of the pull: the part where the gun was being held still. The scatter of
those samples is kept too, because it is the floor this whole procedure can
reach. If your hand wanders 1 % of the screen while holding aim, no correction
fitted from it is going to be better than 1 %, and the results screen says so
rather than letting you shoot round after round chasing it.

Rounds accumulate: every round adds five more pairs to the same fit, and the
results screen after each one says what the fit looks like now — how far off the
gun was, what is left after the correction, and whether that is inside the shot's
own radius. From there you can shoot another round, redo the one you just shot
(if you fumbled one), save, or walk away.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import replace

from ..core import calibration as calib_core
from ..core.calibration import Calibration

# Where the five targets sit in the picture. The corners are inset rather than in
# the actual corners for two reasons: the firmware clamps its own output to the
# beacon rectangle, so a gun that reads a couple of per cent low would have its
# corner shots flattened against the edge and the fit would read that as a scale
# error; and a target whose rings run off the picture has no bull to aim at.
INSET = 0.12
TARGETS = [
    ("CENTRE", 0.5, 0.5),
    ("TOP LEFT", INSET, INSET),
    ("TOP RIGHT", 1.0 - INSET, INSET),
    ("BOTTOM RIGHT", 1.0 - INSET, 1.0 - INSET),
    ("BOTTOM LEFT", INSET, 1.0 - INSET),
]

HOLD = 0.25        # seconds of held aim that make one reading
SKIP = 0.04        # ... ending this long before the trigger, to miss the jerk
STALE = 0.25       # a report older than this is not a reading, it is a memory
SHOW = 0.7         # how long a shot stays on screen before the next target
WILD = 0.25        # a shot this far off is flagged: probably the wrong target

BG = (22, 24, 32)
INK = (240, 240, 245)
DIM = (120, 122, 132)
GOLD = (255, 225, 90)
SHOT_INK = (120, 210, 255)
GRADE_INK = {"EXCELLENT": (120, 255, 150), "GOOD": (170, 240, 130),
             "USABLE": (255, 210, 110), "POOR": (255, 120, 110)}


def _fit_font(pygame, sample: str, width: int, biggest: int = 22):
    """The biggest monospace that still fits `sample` across `width`."""
    for size in range(biggest, 7, -1):
        f = pygame.font.SysFont("Menlo,monospace", size, bold=True)
        if f.size(sample)[0] <= width:
            return f
    return pygame.font.SysFont("Menlo,monospace", 8, bold=True)


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


class Calibrator:
    """The calibration screen. Owns its own loop until the player leaves it.

    It is handed `poll` rather than the input source itself: the coordinates it
    has to record are the UNCORRECTED ones — where the gun reports, before any
    calibration and before the crosshair's extrapolation — and knowing how to
    get those is the frontend's business, not this screen's. `poll` returns
    (x, y, t, fire, pressed, quit): the raw aim in picture fractions, the time
    the report arrived, and the trigger.
    """

    def __init__(self, pygame, screen, present, poll, W, H, spread=0.02,
                 existing: Calibration | None = None, display=(0, 0), gun=None):
        self.pygame = pygame
        self.screen = screen
        self.present = present
        self.poll = poll
        self.W, self.H = W, H
        self.aspect = H / W if W else 1.0
        self.spread = spread
        self.existing = existing or Calibration()
        # What this was measured against, kept in the file: a correction fitted
        # for one beacon rectangle is not a correction for another, and the only
        # way the game can warn about that later is if the numbers travel with it.
        self.display = tuple(display)
        self.gun = gun
        self.font = pygame.font.SysFont("Menlo,monospace", 22, bold=True)
        self.big = pygame.font.SysFont("Menlo,monospace", 40, bold=True)
        self.row = _fit_font(
            pygame, "BOTTOM RIGHT   9.9% R  9.9% D    9.9%  999px    9.9%",
            int(W * 0.82))
        self.r = max(14, int(W * 0.045))          # target radius, px
        self._fonts = {}                          # monospace by width, cached
        self.phase, self.idx = "aim", 0           # where the round is up to

    def _mono(self, chars: int):
        """The biggest monospace in which `chars` characters still fit across.

        Fitted to the longest line the screen is ABOUT to draw rather than to a
        sample written here: the numbers decide the width (a tilt of -1.6 is
        wider than one of 1.6), and a font picked from a guess is how the model
        line ended up running off the edge of the picture.
        """
        if chars not in self._fonts:
            self._fonts[chars] = _fit_font(self.pygame, "M" * chars,
                                           int(self.W * 0.88))
        return self._fonts[chars]

    # ---- drawing -----------------------------------------------------------

    def _centre(self, text, font, y, ink=INK):
        img = font.render(text, True, ink)
        self.screen.blit(img, (self.W // 2 - img.get_width() // 2, y))
        return y + font.get_height()

    def _block(self, lines, y, font=None, inks=None, shade=True):
        """A centred stack of lines on a dark pad, so it reads over a target."""
        pygame = self.pygame
        font = font or self.font
        inks = inks or [INK] * len(lines)
        imgs = [font.render(t, True, k) for t, k in zip(lines, inks)]
        if shade:
            w = max(i.get_width() for i in imgs) + 24
            h = sum(i.get_height() + 4 for i in imgs) + 8
            pad = pygame.Surface((w, h), pygame.SRCALPHA)
            pad.fill((0, 0, 0, 170))
            self.screen.blit(pad, (self.W // 2 - w // 2, y - 6))
        for img in imgs:
            self.screen.blit(img, (self.W // 2 - img.get_width() // 2, y))
            y += img.get_height() + 4
        return y

    def _target(self, cx, cy, r, state, t=0.0):
        """One round target. `state` is "active", "pending" or "done"."""
        pygame = self.pygame
        if state == "active":
            rings = [((250, 250, 250), 1.00), ((225, 45, 45), 0.78),
                     ((250, 250, 250), 0.56), ((225, 45, 45), 0.34)]
        else:
            rings = [((150, 150, 158), 1.00), ((120, 62, 62), 0.78),
                     ((150, 150, 158), 0.56), ((120, 62, 62), 0.34)]
        pygame.draw.circle(self.screen, (10, 10, 14), (cx, cy), r + 2)
        for ink, k in rings:
            pygame.draw.circle(self.screen, ink, (cx, cy), max(1, int(r * k)))
        # the bull: a dark dot the front sight can be centred on, small enough
        # that covering it means something
        pygame.draw.circle(self.screen, (18, 18, 24), (cx, cy), max(2, int(r * 0.12)))
        if state == "active":
            # a ring that breathes, so the target you are on is obvious from
            # across the room and with the crosshair off
            grow = 1.22 + 0.06 * math.sin(t * 5.0)
            pygame.draw.circle(self.screen, GOLD, (cx, cy), int(r * grow),
                               max(2, self.W // 400))

    def _shot(self, sample):
        """Where the gun said it was, against the target it was aimed at."""
        pygame = self.pygame
        tx, ty, rx, ry = sample["target"] + sample["aim"]
        x0, y0 = int(tx * self.W), int(ty * self.H)
        x1, y1 = int(rx * self.W), int(ry * self.H)
        ink = (255, 140, 120) if sample["wild"] else SHOT_INK
        pygame.draw.line(self.screen, ink, (x0, y0), (x1, y1), max(1, self.W // 500))
        d = max(3, self.W // 220)
        pygame.draw.circle(self.screen, (255, 255, 255), (x1, y1), d + 2)
        pygame.draw.circle(self.screen, ink, (x1, y1), d)

    # ---- one reading -------------------------------------------------------

    def _reading(self, buf, now):
        """The held aim just before the trigger: (x, y, scatter) or None.

        The median, not the mean: one report with a beacon momentarily out of
        view can be a quarter of the screen away, and it would drag a mean with
        it. The scatter is the mean distance of the samples from that median —
        how still the gun was, in the same units as everything else here.
        """
        lo, hi = now - SKIP - HOLD, now - SKIP
        window = [(x, y) for t, x, y in buf if lo <= t <= hi]
        if len(window) < 3:
            window = [(x, y) for t, x, y in buf][-5:]      # a slow link, or the mouse
        if not window:
            return None
        mx = _median([p[0] for p in window])
        my = _median([p[1] for p in window])
        scatter = sum(math.hypot(x - mx, (y - my) * self.aspect)
                      for x, y in window) / len(window)
        return mx, my, scatter

    # ---- the numbers -------------------------------------------------------

    def _points(self, rounds):
        return [(s["aim"][0], s["aim"][1], s["target"][0], s["target"][1])
                for rnd in rounds for s in rnd]

    def _repeat(self, rounds, fit=None):
        """How far the same target moved between rounds — the honest ceiling.

        Two rounds that disagree by more than the correction's own residual mean
        the residual is luck: the fit is describing one particular way the gun
        was held, and the next time it is picked up it will be held differently.
        Shots the fit threw out are left out of this too, or one fumble would be
        reported as the gun being unrepeatable.
        """
        if len(rounds) < 2:
            return None
        spread = []
        for i in range(len(TARGETS)):
            pts = [rnd[i]["aim"] for rnd in rounds
                   if len(rnd) > i and not self._ignored(rnd[i], fit)]
            if len(pts) < 2:
                continue
            mx = sum(p[0] for p in pts) / len(pts)
            my = sum(p[1] for p in pts) / len(pts)
            spread += [math.hypot(x - mx, (y - my) * self.aspect) for x, y in pts]
        return sum(spread) / len(spread) if spread else None

    def _ignored(self, shot, fit) -> bool:
        """Was this shot one the fit refused to listen to? (see core: DROP_FLOOR)"""
        if fit is None or fit.limit <= 0:
            return False
        ax, ay = fit.apply(*shot["aim"])
        tx, ty = shot["target"]
        return math.hypot(ax - tx, (ay - ty) * self.aspect) > fit.limit

    def _px(self, d: float) -> float:
        """A distance in picture widths -> pixels on this screen."""
        return d * self.W

    # ---- the loop ----------------------------------------------------------

    def run(self) -> Calibration | None:
        """Shoot rounds until the player saves or leaves. Returns what to use
        from now on, or None if nothing was changed."""
        pygame = self.pygame
        clock = pygame.time.Clock()
        rounds: list[list[dict]] = []
        shots: list[dict] = []
        buf = deque(maxlen=240)
        phase = "aim"
        idx = 0
        t_phase = 0.0
        t_now = 0.0
        message = ("", 0.0)
        saved = None
        last_t = 0.0
        fit = None

        while True:
            dt = clock.tick(60) / 1000.0
            t_phase += dt
            t_now += dt

            # ---- keys ----
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return saved
                if e.type != pygame.KEYDOWN:
                    continue
                if e.key in (pygame.K_ESCAPE, pygame.K_q):
                    return saved
                if phase == "results":
                    if e.key == pygame.K_s:
                        saved = fit if calib_core.save(fit) else saved
                    elif e.key == pygame.K_r and rounds:
                        rounds.pop()                     # the round just shot
                        shots, idx, phase, t_phase = [], 0, "aim", 0.0
                    elif e.key == pygame.K_SPACE:
                        shots, idx, phase, t_phase = [], 0, "aim", 0.0
                elif e.key == pygame.K_u and shots:
                    shots.pop()                          # fumbled one — take it back
                    idx = len(shots)
                    phase, t_phase = "aim", 0.0

            # ---- input ----
            x, y, t, fire, pressed, quit_now = self.poll()
            if quit_now:
                return saved
            if t > last_t:                    # a report that is actually new
                buf.append((t, x, y))
                last_t = t
            fresh = t and (time.monotonic() - t) < STALE
            if pressed & 0x04:                # HOME on the remote — leave
                return saved
            if phase == "results" and pressed & 0x02:     # A on the remote — save
                saved = fit if calib_core.save(fit) else saved
            if phase == "results" and fire and t_phase > 0.8:
                # ... but not in the first moment of it: the pull that comes
                # right as the results appear is the one already on its way, and
                # it would throw the reading away before it could be read
                shots, idx, phase, t_phase = [], 0, "aim", 0.0
                fire = False

            # ---- the shot ----
            if phase == "shot" and t_phase > SHOW:
                phase, t_phase = "aim", 0.0
                if idx >= len(TARGETS):
                    rounds.append(shots)
                    fit = replace(
                        calib_core.fit(self._points(rounds), self.aspect),
                        rounds=len(rounds), steady=self._steady(rounds),
                        picture=(self.W, self.H), display=self.display,
                        frame=self.gun.frame if self.gun else "",
                        beacons=((self.gun.beacon_w, self.gun.beacon_h,
                                  self.gun.beacon_cx, self.gun.beacon_cy)
                                 if self.gun else (1.0, 1.0, 0.5, 0.5)))
                    phase = "results"
            elif phase == "aim" and fire:
                name, tx, ty = TARGETS[idx]
                reading = self._reading(buf, time.monotonic())
                if not fresh or reading is None:
                    # No beacons in view: the last position is a memory, not an
                    # aim, and recording it would bake a lie into the fit.
                    message = ("NO BEACONS IN VIEW — that shot was not recorded", 2.0)
                else:
                    rx, ry, scatter = reading
                    off = math.hypot(rx - tx, (ry - ty) * self.aspect)
                    shots.append({"name": name, "target": (tx, ty), "aim": (rx, ry),
                                  "scatter": scatter, "off": off,
                                  "wild": off > WILD})
                    idx += 1
                    phase, t_phase = "shot", 0.0

            # Which target it is asking for, readable from outside: a rig that
            # drives this with a simulated gun has to aim where the screen says,
            # and there is no other way for it to know.
            self.phase, self.idx = phase, idx

            # ---- drawing ----
            self.screen.fill(BG)
            if phase == "results":
                self._draw_results(rounds, fit, saved)
            else:
                self._draw_range(rounds, shots, idx, phase, fresh, t_now)
            if message[1] > 0:
                message = (message[0], message[1] - dt)
                self._block([message[0]], int(self.H * 0.78), self.font,
                            [GOLD])
            self.present()

    def _steady(self, rounds):
        vals = [s["scatter"] for rnd in rounds for s in rnd]
        return sum(vals) / len(vals) if vals else 0.0

    # ---- the two screens ---------------------------------------------------

    def _draw_range(self, rounds, shots, idx, phase, fresh, t):
        """The five targets, the one you are on, and the shots already taken."""
        for i, (name, tx, ty) in enumerate(TARGETS):
            state = "active" if (i == idx and phase == "aim") else (
                "done" if i < len(shots) else "pending")
            self._target(int(tx * self.W), int(ty * self.H), self.r, state, t)
        for s in shots:
            self._shot(s)

        y = int(self.H * 0.035)
        y = self._centre(f"SIGHTING IN — ROUND {len(rounds) + 1}", self.big, y, GOLD)
        y += 4
        shot_no = min(idx + 1, len(TARGETS))
        self._centre(f"SHOT {shot_no} OF {len(TARGETS)}"
                     + (f"  ·  {len(rounds)} round"
                        f"{'s' if len(rounds) != 1 else ''} already in the fit"
                        if rounds else ""), self.font, y, INK)

        # The instructions live in the middle of the picture, which is where the
        # centre target is — so they step out of its way while it is the one
        # being shot, rather than being drawn over the bull you are aiming at.
        mid = int(self.H * (0.70 if idx == 0 else 0.44))
        if phase == "aim":
            lines = ["PUT THE FRONT SIGHT ON THE BULL — NOT THE CROSSHAIR",
                     f"then pull.  Target: {TARGETS[idx][0]}"]
            inks = [INK, GOLD]
            if not fresh:
                lines.append("the camera cannot see the beacons right now")
                inks.append((255, 120, 110))
            self._block(lines, mid, self.font, inks)
        else:
            s = shots[-1]
            dx, dy = s["aim"][0] - s["target"][0], s["aim"][1] - s["target"][1]
            self._block([
                f"{s['name']}: the gun said "
                f"{abs(dx) * 100:.1f}% {'RIGHT' if dx > 0 else 'LEFT'}, "
                f"{abs(dy) * 100:.1f}% {'DOWN' if dy > 0 else 'UP'}",
                f"{self._px(s['off']):.0f} px off"
                + ("  ·  that is a long way — was it the right target?"
                   if s["wild"] else ""),
            ], mid, self.font,
                [INK, (255, 140, 120) if s["wild"] else DIM])

        self._centre("U — TAKE BACK THE LAST SHOT      ESC — LEAVE",
                     self.font, int(self.H * 0.93), DIM)

    def _draw_results(self, rounds, fit, saved):
        """What the round bought: the five misses, and what is left after the fit.

        Two numbers carry the whole screen. BEFORE is how far the gun was from
        where it was pointed — the thing you came here to fix. AFTER is what the
        correction leaves behind, and that one is the only honest answer to "is
        it any good now": a calibration that is saved and a calibration that
        helps are different claims. The player's own scatter is printed next to
        them because it is the floor — a residual already below it is not going
        to be improved by shooting more rounds, it is going to be chased.
        """
        pygame = self.pygame
        W, H = self.W, self.H
        last = rounds[-1]
        rows = calib_core.errors(fit.m, self._points([last]), self.aspect)
        word, why, share = calib_core.grade(fit.residual, self.spread)

        # ---- every line first, then a font that fits the longest of them ----
        head = f"{'TARGET':<14}{'GUN SAID':<18}{'OFF BY':<16}AFTER THE FIT"
        table = [(head, (150, 200, 255))]
        ignored = [self._ignored(s_, fit) for s_ in last]
        for s_, r, out in zip(last, rows, ignored):
            dx, dy = r["dx"], r["dy"]
            table.append((
                f"{s_['name']:<14}"
                f"{abs(dx) * 100:4.1f}% {'R' if dx > 0 else 'L'} "
                f"{abs(dy) * 100:4.1f}% {'D' if dy > 0 else 'U'}    "
                f"{r['before'] * 100:4.1f}% {self._px(r['before']):4.0f}px   "
                f"{r['after'] * 100:5.1f}% {self._px(r['after']):4.0f}px",
                (255, 140, 120) if out or s_["wild"] else INK))

        # the worst of the shots the fit actually used: quoting the fumble it
        # threw out would contradict the BEFORE/AFTER means on the same screen
        kept = [r for r, out in zip(rows, ignored) if not out] or rows
        worst_b = max(r["before"] for r in kept)
        worst_a = max(r["after"] for r in kept)
        dxs, dys = fit.shift
        facts = [
            ("BEFORE", f"the gun was {fit.before * 100:.1f}% of the picture out "
                       f"({self._px(fit.before):.0f} px), worst "
                       f"{worst_b * 100:.1f}%"),
            ("AFTER", f"{fit.residual * 100:.1f}% of that is left "
                      f"({self._px(fit.residual):.0f} px), worst "
                      f"{worst_a * 100:.1f}%"),
            ("YOUR HAND", f"scatter while holding aim {fit.steady * 100:.1f}% "
                          f"({self._px(fit.steady):.0f} px) — the floor for this"),
            ("MODEL", f"{fit.model} · shift {abs(dxs) * 100:.1f}% "
                      f"{'R' if dxs > 0 else 'L'} {abs(dys) * 100:.1f}% "
                      f"{'D' if dys > 0 else 'U'} · scale {fit.scale_x:.3f} x "
                      f"{fit.scale_y:.3f} · tilt {fit.tilt:+.1f} deg"),
        ]
        if fit.dropped:
            facts.append(("IGNORED",
                          f"{fit.dropped} shot"
                          f"{'s' if fit.dropped != 1 else ''} too far out to be "
                          f"a hand — left out of the fit, kept in the file"))
        repeat = self._repeat(rounds, fit)
        if repeat is not None:
            facts.append(("ROUND TO ROUND",
                          f"the same target moved {repeat * 100:.1f}% "
                          f"({self._px(repeat):.0f} px) between rounds"))
        fact_lines = [f"{label:<16}{text}" for label, text in facts]

        was = (f"replaces the one from {self.existing.made}"
               if self.existing.active and self.existing.made
               else "there is none saved yet")
        keys = [
            ("TRIGGER · SPACE", "another round — five more shots into the same fit"),
            ("S · A (remote)", f"save it and play with it ({was})"),
            ("R", "throw this round away and shoot it again"),
            ("ESC · HOME (remote)", "leave without saving"),
        ]
        kw = max(len(k) for k, _ in keys)
        key_lines = [f"{k:>{kw}}  {a}" for k, a in keys]

        widest = max(len(t) for t, _ in table)
        widest = max([widest] + [len(t) for t in fact_lines + key_lines])
        row = self._mono(widest)
        line = row.get_height() + 2
        x0 = W // 2 - row.size("M" * widest)[0] // 2

        # ---- the panel, sized to what is going on it ----
        block = (len(table) + len(fact_lines) + len(key_lines)) * line
        panel_h = min(int(H * 0.94), block + self.big.get_height()
                      + 4 * self.font.get_height() + int(H * 0.16))
        panel = pygame.Surface((int(W * 0.94), panel_h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 210))
        px, py = (W - panel.get_width()) // 2, (H - panel_h) // 2
        self.screen.blit(panel, (px, py))

        y = py + int(H * 0.025)
        y = self._centre(f"ROUND {len(rounds)} — {len(fit.points)} SHOTS IN THE FIT",
                         self.big, y, GOLD)
        y += int(H * 0.02)
        for text, ink in table:
            self.screen.blit(row.render(text, True, ink), (x0, y))
            y += line
        y += int(H * 0.02)
        for text in fact_lines:
            self.screen.blit(row.render(text, True, INK), (x0, y))
            y += line
        y += int(H * 0.025)

        y = self._centre(f"{word} — {why} "
                         f"({self.spread * 100:.1f}% of the picture)", self.font, y,
                         GRADE_INK.get(word, INK))
        if fit.steady > 0 and fit.residual < fit.steady * 0.8:
            y = self._centre("that is already tighter than your own hold — "
                             "another round will not improve it", self.font, y, DIM)
        elif word == "POOR":
            y = self._centre("shoot another round: the fit gets better with "
                             "every five shots", self.font, y, DIM)
        y += int(H * 0.025)

        for text in key_lines:
            k, _, rest = text.partition("  ")
            self.screen.blit(row.render(k, True, GOLD), (x0, y))
            self.screen.blit(row.render(rest, True, (225, 225, 225)),
                             (x0 + row.size(k + "  ")[0], y))
            y += line
        if saved is not None:
            self._centre("SAVED to calibration.json"
                         + ("" if saved is fit else " — this round is not in it yet"),
                         self.font, y + 6, (120, 255, 150))
