"""The pixel (retro) Duck Hunt frontend, built on pygame.

Original pixel sprites in the Duck Hunt spirit (our own, not copies): a duck
flapping its wings, a downed duck, and the dog — sniffing around / retrieving the
catch / laughing at a miss. It runs on the same `World` core and the same
`InputSource` as the terminal version, so the hardware and its calibration do not
change.

Running it:
    pip install pygame
    python3 main.py --pygame                      # aim with the mouse (for development)
    python3 main.py --pygame --serial /dev/tty.usbserial-XXXX   # light gun
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import time
import tomllib

from ..core import scores
from ..core.models import DuckState, Facing
from ..core.world import World

# ---- pixel-art palette -----------------------------------------------------
PALETTE = {
    ".": None,               # transparent
    "K": (24, 24, 28),       # outline / black
    "W": (245, 245, 245),    # white
    "Y": (240, 205, 55),     # yellow (duck)
    "O": (232, 140, 24),     # orange (beak / feet)
    "B": (60, 115, 225),     # blue (duck, alternate colour)
    "C": (150, 200, 255),    # light blue (belly)
    "H": (46, 140, 95),      # green head (mallard colouring)
    "M": (34, 34, 52),       # dark blue-black body
    "N": (140, 92, 52),      # brown (dog)
    "D": (88, 56, 30),       # dark brown (ears / spots / shadow)
    "T": (225, 200, 158),    # tan (muzzle / belly / paws)
    "R": (205, 60, 55),      # red (tongue)
}

# ---- sprites (lists of strings; the builder pads the width) ----------------
# The duck flies right (beak on the right, eye by the beak). The body occupies the
# same rows in both frames — only the wing moves, so the duck does not jump around.
DUCK_R_A = [                         # wing up
    ".....KWK.........",
    "....KWWWK........",
    "...KWWWWWK.......",
    "....KKKKKKKHHHK..",
    "..KMMMMMMMHHHHHKO",
    ".KMMMMMMMMHWKHHKO",
    ".KMMMMMMMMMHHHK..",
    ".KMMMMMMMMMMMHK..",
    ".KMMMMMMMMMMMK...",
    "..KWWWWWWMMMK....",
    "..KKWWWWMMK......",
    "...KOO.OOK.......",
    ".................",
    ".................",
    ".................",
]
DUCK_R_B = [                         # wing down
    ".................",
    ".................",
    ".................",
    "....KKKKKKKHHHK..",
    "..KMMMMMMMHHHHHKO",
    ".KMMMMMMMMHWKHHKO",
    ".KMMMMMMMMMHHHK..",
    ".KMMMMMMMMMMMHK..",
    ".KMMMMMMMMMMMK...",
    "..KWWWWWWMMMK....",
    "..KKWWWWMMK......",
    "...KOO.OOK.......",
    "...KWWWWWK.......",
    "....KWWWK........",
    ".....KWK.........",
]
DUCK_HIT = [                         # shot down — cross eyes, wings splayed
    "....KKKKKKKHHHK..",
    "..KMMMMMMMHHHHHK.",
    ".KMMMMMMMMHKHKHK.",
    ".KMMMMMMMMMHHHK..",
    ".KMMMMMMMMMMMMK..",
    "..KMMMMMMMMMK....",
    ".KWK.KWWWWK.KWK..",
    "KWWK.......KWWK..",
]

# The dog (side view) walks through the grass, searching — two "step" frames (the
# paws alternate). In detail: a floppy dark ear, muzzle with nose, eye, spots on
# the body, tan paws.
DOG_SNIFF_A = [
    "................KKKK...",
    "..............KKNNNNK..",
    ".....KKKK....KNNNNNNNK.",
    "....KDDDDK..KNNNWKNNNKO",
    "KKK.KDDDDDK.KNNNNTTTNKO",
    "KNNKKDDDDDKKKNNNNNTTNK.",
    "KNNNKDDDDDNNNNNNNNNTK..",
    "KNNNNNNNNNNNNNNNNNNK...",
    ".KNNDDNNNNNNNDDNNNNK...",
    ".KNNDDNNNNNNNDDNNNNK...",
    ".KTNNNNNNNNNNNNNNNTK...",
    ".KTTNNNNNNNNNNNNNTTK...",
    ".KNNK.KNNK..KNNK.KNNK..",
    ".KNNK.KNNK..KNNK.KNNK..",
    ".KTTK.KTTK..KTTK.KTTK..",
]
DOG_SNIFF_B = [
    "................KKKK...",
    "..............KKNNNNK..",
    ".....KKKK....KNNNNNNNK.",
    "....KDDDDK..KNNNWKNNNKO",
    "KKK.KDDDDDK.KNNNNTTTNKO",
    "KNNKKDDDDDKKKNNNNNTTNK.",
    "KNNNKDDDDDNNNNNNNNNTK..",
    "KNNNNNNNNNNNNNNNNNNK...",
    ".KNNDDNNNNNNNDDNNNNK...",
    ".KNNDDNNNNNNNDDNNNNK...",
    ".KTNNNNNNNNNNNNNNNTK...",
    ".KTTNNNNNNNNNNNNNTTK...",
    "..KNNK.KNNK.KNNK.KNNK..",
    "..KNNK.KNNK.KNNK.KNNK..",
    "..KTTK.KTTK.KTTK.KTTK..",
]
# The dog caught a duck — it jumps up holding the catch overhead, pleased.
DOG_CATCH = [
    ".......KKKKK.........",
    "......KBBBBBKO.......",
    "......KBCCCBK........",
    ".......KKKKK.........",
    "........KKK..........",
    ".......KKKKK.........",
    "......KNNNNNK........",
    ".....KNDDNDDNK.......",
    ".....KNNNNNNNK.......",
    ".....KNWKWKWNK.......",
    ".....KNNTOTNNK.......",
    ".....KNTTTTTNK.......",
    "......KNNNNNK........",
    ".....KNNNNNNNK.......",
    "....KNNNNNNNNNK......",
    "....KNNDDNDDNNK......",
    "....KTTNNNNNTTK......",
    ".....KNK...KNK.......",
    ".....KTK...KTK.......",
]
# The dog laughs at a miss — head thrown back, mouth wide open, tongue out.
DOG_LAUGH = [
    "........KKKKK.......",
    ".......KNNNNNK......",
    "......KNDDNDDNK.....",
    "......KNNNNNNNK.....",
    "......KNKKNKKNK.....",
    "......KNNNNNNNK.....",
    "......KWWWWWWWK.....",
    "......KWWWWWWWK.....",
    "......KNRRRRRNK.....",
    ".......KNRRRNK......",
    "......KNNNNNNNK.....",
    ".....KNNNNNNNNNK....",
    ".....KNNDDNDDNNK....",
    ".....KTTNNNNNTTK....",
    "......KNK...KNK.....",
    "......KTK...KTK.....",
]

# The controls, in one place: shown on the title screen and on the score table,
# because a player standing three metres away with a gun in both hands has no way
# to look them up. Remote buttons are named first where there is one — that is
# the control they actually have in their hands.
KEYMAP = [
    ("TRIGGER · SPACE", "start the round, and shoot in it"),
    ("ESC", "stop the round — the score still counts"),
    ("Q", "quit Duck Hunt"),
    ("A (remote) · C", "show / hide the crosshair"),
    ("B", "next background"),
    ("TAB", "corner targets for the IR beacons"),
    ("G", "the gun's report rate and dropouts"),
    ("HOME (remote) · K", "the bridge's link keep-alive"),
]

FPS = 60
SCALE = 5          # one sprite pixel = SCALE screen pixels
MARK_LIFE = 1.4    # seconds a shot's hole stays on screen before it fades out
RING_LIFE = 0.22   # ... and how long the ring that snaps out to the hit zone lives
MARKS_MAX = 24     # keep the last few; a fast round can put out a lot of lead


def aim_to_picture(gun, gx, gy, geom):
    """Gun coordinates -> a fraction of the picture the ducks fly in.

    The gun reports where the barrel points inside the BEACON RECTANGLE, 0..1
    along its own two axes (the firmware solves the homography and clamps to its
    own rectangle). `gun` — the [gun] section of settings.toml — says what that
    rectangle is: with `frame = "picture"` the LEDs are on the corners of the
    letterboxed picture, so the numbers are playfield fractions already and this
    is a no-op whatever the display; with `frame = "display"` they are on the
    physical screen's corners, and the black bars have to come out, or the
    crosshair lags behind the barrel by up to half a bar at the edges. (A window
    cannot be corrected — nothing tells us where it sits on screen — so with
    "display" beacons play fullscreen.)

    `geom` is (display w, display h, picture w, picture h, picture x, picture y).
    """
    sw, sh, W, H, ox, oy = geom
    u = gun.beacon_cx + (gx - 0.5) * gun.beacon_w
    v = gun.beacon_cy + (gy - 0.5) * gun.beacon_h
    if gun.frame == "display":
        u = (u * sw - ox) / W
        v = (v * sh - oy) / H
    return min(1.0, max(0.0, u)), min(1.0, max(0.0, v))


def _open_fullscreen(pygame, want_display, desktops):
    """Open the fullscreen window so that it is actually fullscreen.

    macOS applies a window's fullscreen state when the window is next SHOWN, and
    a window created with the flag already set never gets a next show — so the
    state is quietly never applied and what you get is an ordinary window the
    size of the desktop, title bar, menu bar and all. That is also why minimising
    it and bringing it back fixes the picture by hand: that IS the next show.

    So do it in two steps: create the window plain, let Cocoa put it on screen,
    and only then ask for fullscreen. Measured over eight launches each on a
    two-monitor Mac: 0 of 8 came up fullscreen the one-step way, 8 of 8 this way.
    Asking the NSWindow for its own styleMask is how that was counted — SDL's own
    FULLSCREEN flag reads true either way and cannot be trusted here.

    `want_display` is a monitor number or -1 for SDL's choice; with -1 the size
    stays (0, 0), which pygame reads as "the desktop", and the window lands on
    the same monitor it always did.
    """
    size = desktops[want_display] if want_display >= 0 else (0, 0)
    where = {"display": want_display} if want_display >= 0 else {}
    pygame.display.set_mode(size, pygame.NOFRAME, **where)
    for _ in range(3):                  # let the window get on screen first
        pygame.event.pump()
        time.sleep(0.05)
    return pygame.display.set_mode(size, pygame.FULLSCREEN, **where)


def _fit_font(pygame, rows, width, biggest=22):
    """The largest font the two-column keymap still fits into `width` with.

    The rest of the text is set in fixed point sizes, which is fine for a line or
    two but not for a block eight rows wide: the picture is 768 px across in a
    window and 2000 in fullscreen, and the same 22 pt runs off the edge of the
    first. So the keymap gets its own size, measured rather than guessed.
    """
    for size in range(biggest, 8, -1):
        f = pygame.font.SysFont("Menlo,monospace", size, bold=True)
        # the two columns are each as wide as their own widest row, and those
        # two rows are not the same row — so the block is the sum of the maxima
        if (max(f.size(k)[0] for k, _ in rows)
                + max(f.size(a)[0] for _, a in rows)) <= width:
            return f
    return pygame.font.SysFont("Menlo,monospace", 9, bold=True)


def _build(rows, palette, scale):
    """A list of strings -> pygame.Surface (transparent background, integer scale)."""
    import pygame

    w = max(len(r) for r in rows)
    surf = pygame.Surface((w * scale, len(rows) * scale), pygame.SRCALPHA)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            color = palette.get(ch)
            if color is not None:
                surf.fill(color, (x * scale, y * scale, scale, scale))
    return surf


# ---- sprites sliced out of the Duck Hunt sheet (assets/sprites/) -----------
SPRITE_DIR = "sprites"
DUCK_COLORS = ("black", "red")     # the duck colours available on the sheet
FLAP = (0, 1, 2, 1)                # flap frame order: down-middle-up


def _load_sheet(pygame, assets_dir, duck_w, dog_w, catch_scale):
    """The frame set from assets/sprites/, or None if it is not there.

    The ducks are scaled by a whole number of times — anything else makes the
    pixel art smear. The dog is scaled to exactly the width [dog] width asks for,
    whole number or not: it is a size you set deliberately, and a whole-number
    step is 54 art pixels wide, which at a typical fullscreen scale is a third of
    a dog — far too coarse a knob. transform.scale is nearest-neighbour, so the
    worst that happens is that some of its pixels come out a pixel bigger than
    others, exactly as they do for the whole picture under fit = "height".
    One factor for the dog, so its frames keep their proportions against each
    other — except the retrieving one, which [dog] catch_scale deliberately
    blows up a little past the rest.
    """
    d = os.path.join(assets_dir, SPRITE_DIR)
    names = [f"duck_{c}_{row}_{i}"
             for c in DUCK_COLORS for row in ("fly", "up") for i in (1, 2, 3)]
    names += [f"dog_walk_{i}" for i in (1, 2, 3, 4)] + ["dog_laugh_1", "dog_catch"]

    raw = {}
    for name in names:
        path = os.path.join(d, name + ".png")
        if not os.path.exists(path):
            return None
        raw[name] = pygame.image.load(path).convert_alpha()

    k_duck = max(1, round(duck_w / raw[f"duck_{DUCK_COLORS[0]}_fly_1"].get_width()))
    k_dog = max(1.0, dog_w / raw["dog_walk_1"].get_width())

    def up(name, k):
        img = raw[name]
        return pygame.transform.scale(img, (max(1, round(img.get_width() * k)),
                                            max(1, round(img.get_height() * k))))

    ducks = {}
    for c in DUCK_COLORS:
        right = [up(f"duck_{c}_fly_{i}", k_duck) for i in (1, 2, 3)]
        ducks[c] = {
            "right": right,
            "left": [pygame.transform.flip(s, True, False) for s in right],
            # the downed duck is the frame with the wings thrown upwards
            "hit": up(f"duck_{c}_up_3", k_duck),
        }
    return {
        "ducks": ducks,
        "dog_walk": [up(f"dog_walk_{i}", k_dog) for i in (1, 2, 3, 4)],
        "dog_laugh": up("dog_laugh_1", k_dog),
        "dog_catch": up("dog_catch", k_dog * catch_scale),
    }


def _load_fallback(pygame, assets_dir, dog_w, catch_scale):
    """The old path: individual PNGs under fixed names, or the built-in art."""
    # the built-in dog is drawn as characters, so its scale comes from how wide
    # those rows are — the same [dog] width in fractions of the picture. Whole
    # pixels here, because _build paints the art a block at a time.
    dog_scale = max(1, round(dog_w / max(len(r) for r in DOG_SNIFF_A)))
    catch_scale_px = max(1, round(dog_scale * catch_scale))

    def load(name, fallback):
        path = os.path.join(assets_dir, name + ".png")
        if os.path.exists(path):
            img = pygame.image.load(path).convert_alpha()
            tw = fallback.get_width()
            if img.get_width() != tw:
                th = max(1, round(img.get_height() * tw / img.get_width()))
                img = pygame.transform.scale(img, (tw, th))
            return img
        return fallback

    right = [load("duck_a", _build(DUCK_R_A, PALETTE, SCALE)),
             load("duck_b", _build(DUCK_R_B, PALETTE, SCALE))]
    right = [right[0], right[1], right[1]]          # three frames out of two
    walk = [load("dog_walk_a", _build(DOG_SNIFF_A, PALETTE, dog_scale)),
            load("dog_walk_b", _build(DOG_SNIFF_B, PALETTE, dog_scale))]
    one = {
        "right": right,
        "left": [pygame.transform.flip(s, True, False) for s in right],
        "hit": load("duck_hit", _build(DUCK_HIT, PALETTE, SCALE)),
    }
    return {
        "ducks": {c: one for c in DUCK_COLORS},
        "dog_walk": [walk[0], walk[1], walk[0], walk[1]],
        "dog_laugh": load("dog_laugh", _build(DOG_LAUGH, PALETTE, dog_scale)),
        "dog_catch": load("dog_catch", _build(DOG_CATCH, PALETTE, catch_scale_px)),
    }


# ---- backgrounds (assets/backgrounds/, sliced by tools/slice_backgrounds.py) -
BG_DIR = "backgrounds"


def _load_backgrounds(pygame, assets_dir):
    """The backgrounds from index.toml: name, image and grass line. None -> empty."""
    d = os.path.join(assets_dir, BG_DIR)
    index_path = os.path.join(d, "index.toml")
    if not os.path.exists(index_path):
        return []
    try:
        with open(index_path, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        print(f"{BG_DIR}/index.toml could not be read ({exc}) — drawing the landscape myself",
              file=sys.stderr)
        return []

    out = []
    for name, entry in data.items():
        path = os.path.join(d, entry.get("file", name + ".png"))
        if not os.path.exists(path):
            print(f"background {name!r}: no file {path} — skipped", file=sys.stderr)
            continue
        out.append({"name": name,
                    "image": pygame.image.load(path),
                    # the fraction of the height where the grass starts: the dog
                    # pops up along that line
                    "grass": float(entry.get("grass", 0.8))})
    return out


def _procedural_bg(pygame, W, H, grass_y):
    """A fallback landscape drawn in code: gradient sky, hill, bushes."""
    SKY_TOP, SKY_BOT = (60, 120, 245), (140, 195, 255)
    HILL, GRASS, GRASS_DK = (70, 175, 90), (58, 160, 72), (40, 120, 55)
    BUSH, CLOUD = (36, 110, 52), (245, 250, 255)

    bg = pygame.Surface((W, H))
    for i in range(grass_y):                       # gradient sky
        t = i / grass_y
        bg.fill((int(SKY_TOP[0] + (SKY_BOT[0] - SKY_TOP[0]) * t),
                 int(SKY_TOP[1] + (SKY_BOT[1] - SKY_TOP[1]) * t),
                 int(SKY_TOP[2] + (SKY_BOT[2] - SKY_TOP[2]) * t)),
                (0, i, W, 1))
    for cx, cy, r in ((160, 90, 26), (200, 100, 34), (680, 70, 30), (720, 82, 22)):
        pygame.draw.ellipse(bg, CLOUD, (cx, cy, r * 3, r * 2))
    pygame.draw.ellipse(bg, HILL, (-100, grass_y - 90, W + 200, 180))
    pygame.draw.rect(bg, GRASS, (0, grass_y, W, H - grass_y))
    pygame.draw.rect(bg, GRASS_DK, (0, grass_y, W, 6))
    for bx in (90, 300, 560, 780):
        pygame.draw.ellipse(bg, BUSH, (bx, grass_y - 34, 130, 60))
    return bg


def _pick_background(backgrounds, wanted):
    """Background index from the settings name: `random` picks one, unknown -> first."""
    names = [b["name"] for b in backgrounds]
    if wanted == "random":
        return random.randrange(len(names))
    if wanted in names:
        return names.index(wanted)
    print(f"background {wanted!r} not found, using {names[0]!r} "
          f"(available: {', '.join(names)})",
          file=sys.stderr)
    return 0


class PygameFrontend:
    def __init__(self, settings=None, align=False, log_gun=False):
        self.world = World(settings=settings)
        # --align: start with the beacon corner targets showing (TAB toggles)
        self.align = align
        # --log-gun: one line a second about the gun's stream, for reading the
        # trend back afterwards (ir_view cannot run at the same time as the game,
        # the serial port takes one reader)
        self.log_gun = log_gun

    def run(self, source=None) -> None:
        import pygame

        # Fullscreen without a Space of its own: SDL makes the window
        # borderless, puts it on the display and raises it over the menu bar,
        # instead of handing it to macOS's native fullscreen machinery. That
        # means no half-second Space animation at launch and no separate desktop
        # in Mission Control, which suits a game you start and stare at. It is
        # NOT what fixes the window-instead-of-fullscreen bug — see
        # _open_fullscreen below — it just makes the result instant. Has to be
        # set before the video subsystem comes up; setdefault leaves it yours to
        # override from the shell.
        os.environ.setdefault("SDL_VIDEO_MAC_FULLSCREEN_SPACES", "0")

        pygame.init()
        assets_dir = os.path.join(os.path.dirname(__file__), "..", "..", "assets")
        settings = self.world.settings
        table = scores.load()

        # background from settings.toml ([scene] background); "none" -> draw our own
        wanted_bg = self.world.settings.scene.background
        backgrounds = [] if wanted_bg == "none" else _load_backgrounds(pygame, assets_dir)
        bg_index = _pick_background(backgrounds, wanted_bg) if backgrounds else 0

        # The scene is always scaled by a WHOLE number — anything else smears the
        # pixel art. So in fullscreen it is letterboxed whole and black bars are
        # left at the edges: the scene is drawn into a separate `screen` surface,
        # which present() blits into the centre of the display.
        # Which monitor. The old code asked set_mode for "the desktop size" and
        # took whatever display SDL picked, while the windowed branch sized
        # itself from Info() — and on a two-monitor Mac those are not the same
        # display, so the two branches disagreed. [scene] display settles it.
        desktops = pygame.display.get_desktop_sizes()
        want_display = self.world.settings.scene.display
        if want_display >= len(desktops):
            print(f"[scene] display {want_display}: only {len(desktops)} "
                  f"connected — letting SDL choose")
            want_display = -1
        bw, bh = backgrounds[bg_index]["image"].get_size() if backgrounds else (300, 225)
        # [scene] scale asks for a picture smaller than fits — the light gun's
        # distance knob (a smaller beacon rectangle can be seen from closer up),
        # and nothing else changes because every size in the game is a fraction
        # of the picture. 0 = as big as fits.
        wanted = self.world.settings.scene.scale
        fit = self.world.settings.scene.fit
        if self.world.settings.scene.fullscreen:
            display = _open_fullscreen(pygame, want_display, desktops)
            sw, sh = display.get_size()
            fits = max(1, min(sw // bw, sh // bh))
            if fit == "height" and wanted <= 0:
                # fill the screen's height, keep the aspect: the art pixels no
                # longer land on a whole number of display pixels, so some come
                # out a pixel bigger than their neighbours. transform.scale is
                # nearest-neighbour, so nothing smears — and the ducks are half
                # again as big as the letterboxed fit makes them.
                H, W = sh, int(round(bw * sh / bh))
                if W > sw:                      # a screen narrower than the art
                    W, H = sw, int(round(bh * sw / bw))
                k = max(1, round(H / bh))
            else:
                k = min(wanted, fits) if wanted > 0 else fits
                W, H = bw * k, bh * k
            offset = ((sw - W) // 2, (sh - H) // 2)
            screen = pygame.Surface((W, H))
        else:
            dw, dh = desktops[max(0, want_display)]
            fits = max(1, min(dw // bw, (dh - 120) // bh))
            k = min(wanted, fits) if wanted > 0 else max(2, min(4, fits))
            W, H = bw * k, bh * k
            display = (pygame.display.set_mode((W, H)) if want_display < 0
                       else pygame.display.set_mode((W, H), display=want_display))
            sw, sh = W, H
            offset = (0, 0)
            screen = display
        if wanted > fits:
            print(f"[scene] scale {wanted}x does not fit this display — using {k}x")
        # Where the picture came out: the rectangle to tape the beacons to when
        # [gun] frame = "picture", and the number to check after changing the
        # display or its resolution (the pixel-art scale is a whole number, so the
        # picture changes size in steps and the beacons have to follow).
        print(f"display {want_display if want_display >= 0 else 'auto'} of "
              f"{len(desktops)} connected {desktops} — using {sw}x{sh}"
              f"{'' if self.world.settings.scene.fullscreen else ' (windowed)'}")
        print(f"picture {W}x{H} px at {offset[0]},{offset[1]} of {sw}x{sh} "
              f"({100*W/sw:.0f}% x {100*H/sh:.0f}% of the display, "
              f"{'fit to height' if W * bh != H * bw or H % bh else f'scale {k}x'}"
              f"{'' if H % bh == 0 else f', ~{H/bh:.2f}x'})")
        pygame.mouse.set_visible(False)      # the game draws its own crosshair
        pygame.display.set_caption("🦆 Duck Hunt")

        def draw_beacon_marks(surf, w, h, lines, inks, ink=(230, 40, 40), small=False):
            """Corner targets to tape the four IR beacons to (TAB toggles them).

            Brackets in the four corners of `surf` — so the caller decides which
            rectangle is being marked, because that is exactly what differs
            between the two ways of mounting the beacons: the picture's corners
            ([gun] frame = "picture", drawn into the picture surface) or the
            physical screen's ("display", drawn into the display, with the
            letterbox bars lit up so the screen's own edge is visible against the
            bezel). Red on white, because a mark has to read against sky, grass
            and a lit bar alike.
            """
            arm = max(24, w // (20 if small else 10))
            t = max(2, k) if small else max(4, 2 * k)   # thick enough to aim at
            for ax, ay in ((0, 0), (1, 0), (1, 1), (0, 1)):
                x0 = 0 if ax == 0 else w - arm    # the horizontal arm
                y0 = 0 if ay == 0 else h - t
                x1 = 0 if ax == 0 else w - t      # the vertical arm
                y1 = 0 if ay == 0 else h - arm
                for ink_, inset in (((255, 255, 255), 0), (ink, t // 4)):
                    d = inset
                    pygame.draw.rect(surf, ink_, (x0 + (d if ax == 0 else 0),
                                                  y0 + (d if ay == 0 else 0),
                                                  arm - d, t - d))
                    pygame.draw.rect(surf, ink_, (x1 + (d if ax == 0 else 0),
                                                  y1 + (d if ay == 0 else 0),
                                                  t - d, arm - d))
            y = h // 2 - 52
            for line, ink in zip(lines, inks):
                img = font.render(line, True, ink)
                if img.get_width() > w - 40:      # a small picture, a long line
                    img = pygame.transform.smoothscale(
                        img, ((w - 40), img.get_height() * (w - 40) // img.get_width()))
                shade = pygame.Surface((img.get_width() + 12, img.get_height() + 4),
                                       pygame.SRCALPHA)
                shade.fill((0, 0, 0, 150))
                surf.blit(shade, (w // 2 - shade.get_width() // 2, y - 2))
                surf.blit(img, (w // 2 - img.get_width() // 2, y))
                y += img.get_height() + 6

        def picture_marks():
            """The playfield's own corners — where beacons go with frame = "picture"."""
            draw_beacon_marks(screen, W, H, [
                "BEACONS GO IN THESE FOUR CORNERS",
                f"picture {W}x{H} at {offset[0]},{offset[1]} of {sw}x{sh}, scale {k}x",
                '[gun] frame = "picture" — right for these corners',
                "TAB hides this",
            ], [(255, 255, 255), (255, 255, 255), (140, 255, 140), (190, 190, 190)])

        def display_marks():
            """The screen's own corners, for beacons on the bezel.

            The bars are lit for this, so the display's edge is the line where the
            light stops — that is what a bundle on the bezel lines up with, and
            there is no other way to see it while the game is on.
            """
            draw_beacon_marks(display, sw, sh, [
                "RED: BEACONS GO ON THE BEZEL, LEVEL WITH THESE CORNERS",
                "line each bundle up with the corner where the light stops",
                "BLUE: aim there to check — the crosshair should sit in the angle",
                f'[gun] frame = "display", beacon rectangle {gun.beacon_w:g} x '
                f"{gun.beacon_h:g} of the screen",
                "TAB hides this",
            ], [(255, 255, 255), (255, 255, 255), (130, 210, 255),
                (140, 255, 140), (190, 190, 190)])

        # The crosshair IS the hit zone: [gun] spread is the shot's radius in
        # fractions of the playfield width, and the circle is drawn at exactly
        # that, so a duck touching the circle is a duck that falls. The cross
        # keeps the centre readable; with spread = 0 only the cross is left.
        shot_r = int(settings.gun.spread * W)

        def draw_marks():
            """The shot marks: a ring on every shot, and a hole only where one
            MISSED. A hit already announces itself — the duck folds up and falls
            — so a hole there is just litter over the thing you wanted to see;
            a miss otherwise leaves no trace at all, which is exactly when you
            want to know where the barrel was pointing. The ring stays green on
            a hit so the shot still reads as one."""
            for m in marks:
                age = m["t"]
                cx, cy = int(m["x"] * W), int(m["y"] * H)
                ink = (120, 255, 140) if m["hit"] else (255, 255, 255)
                if age < RING_LIFE and shot_r >= 4:
                    # the ring snaps out to the hit zone and thins as it goes, so
                    # the shot reads as a shot and not as a dot appearing
                    grow = age / RING_LIFE
                    r = max(2, int(shot_r * (0.3 + 0.9 * grow)))
                    width = max(1, int((1.0 - grow) * max(3, k)))
                    pygame.draw.circle(screen, ink, (cx, cy), r, width)
                if m["hit"]:
                    continue          # the falling duck is the feedback there
                # The hole itself: dark, with a bright rim so it reads against
                # both the sky and the grass, and big enough to see from across
                # the room — a third of the shot's own radius. It fades over its
                # life rather than vanishing, so a burst of shots leaves a
                # readable trail of where the barrel has been.
                left = 1.0 - age / MARK_LIFE
                if left > 0:
                    hole = max(3, shot_r // 3 if shot_r else 2 * k)
                    pad = hole + 2
                    shade = pygame.Surface((pad * 2, pad * 2), pygame.SRCALPHA)
                    pygame.draw.circle(shade, (20, 20, 26, int(235 * left)),
                                       (pad, pad), hole)
                    pygame.draw.circle(shade, (*ink, int(200 * left)),
                                       (pad, pad), hole, max(1, k // 2))
                    screen.blit(shade, (cx - pad, cy - pad))

        def draw_crosshair():
            # Hidden is a real way to play a light gun: you aim down the barrel,
            # and the only feedback is the duck falling. A on the remote toggles
            # it (C on the keyboard), because reaching for a keyboard with a gun
            # in both hands is not playing.
            if hide_cross[0]:
                return
            cx, cy = int(crosshair[0] * W), int(crosshair[1] * H)
            arm = max(10, shot_r + max(4, k))
            if shot_r >= 4:
                pygame.draw.circle(screen, (255, 255, 255), (cx, cy), shot_r, max(2, k // 2))
            pygame.draw.line(screen, (255, 60, 60), (cx - arm, cy), (cx + arm, cy), 2)
            pygame.draw.line(screen, (255, 60, 60), (cx, cy - arm), (cx, cy + arm), 2)

        def log_gun_line():
            """One line a second about the gun's stream, while --log-gun is on.

            Hung off present(), which every mode calls, rather than off the
            gameplay branch: the bridge's status lines — including the remote's
            battery level, which it sends on connect — arrive while the title
            screen is still up waiting for the trigger.
            """
            if gun_log is None:
                return
            now = time.monotonic() - t_start
            if now - t_logged[0] < 1.0:
                return
            t_logged[0] = now
            snap = getattr(source, "stats", None)
            snap = snap.snapshot() if snap is not None else None
            if snap is not None:
                snap["t"] = round(now, 2)
                snap["fps"] = round(clock.get_fps(), 1)
                snap["ducks"] = len(self.world.ducks)
                # shots in this second: the firmware kicks the remote's rumble
                # motor for 90 ms on every trigger pull, and that motor comes out
                # of the same AA cells as the radio — so if the stream sags
                # exactly where the shots are, that is the answer, and the log
                # has to carry both to show it
                snap["keepalive"] = 1 if keepalive[0] else 0
                snap["shots"] = max(0, self.world.shots - shots_logged[0])
                shots_logged[0] = self.world.shots
                gun_log.write(json.dumps(snap) + "\n")
            # whatever the bridge said since the last line: a re-pairing in the
            # middle of a round explains a hole that no rate number can
            said = getattr(source, "statuses", None)
            if said:
                for line in said:
                    gun_log.write(json.dumps(
                        {"t": round(now, 2), "status": line}) + "\n")
                said.clear()

        def present():
            """Show the frame: centred in fullscreen, as-is in a window.

            The beacon marks go on here rather than in the gameplay branch, so
            they are up on the intro and the score table too — taping beacons
            should not have to wait for the dog to finish sniffing.
            """
            if show_marks[0]:
                if gun_is_picture:
                    picture_marks()
                else:
                    # the playfield's corners: not where the beacons go in this
                    # wiring, but where to aim to see whether [gun] is right
                    draw_beacon_marks(screen, W, H, [], [],
                                      ink=(70, 150, 255), small=True)
            if screen is not display:
                # the bars go pale grey while the bezel marks are up: a lit
                # display shows where its own glass ends, black does not
                display.fill((170, 170, 178) if show_marks[0] and not gun_is_picture
                             else (0, 0, 0))
                display.blit(screen, offset)
            if show_marks[0] and not gun_is_picture:
                display_marks()
            log_gun_line()
            pygame.display.flip()

        # the geometry aim_to_picture needs: display size, picture size, where
        # the picture sits in the display
        geom = (sw, sh, W, H, offset[0], offset[1])

        gun_log = None
        if self.log_gun and source is not None:
            log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
            os.makedirs(log_dir, exist_ok=True)
            gun_log_path = os.path.normpath(os.path.join(
                log_dir, time.strftime("gun_%Y%m%d_%H%M%S.jsonl")))
            gun_log = open(gun_log_path, "w", buffering=1)
            print(f"Logging the gun stream to {gun_log_path}")
        t_start = time.monotonic()
        t_logged = [0.0]           # a list: present() writes to it from a closure
        shots_logged = [0]

        clock = pygame.time.Clock()
        font = pygame.font.SysFont("Menlo,monospace", 22, bold=True)
        big = pygame.font.SysFont("Menlo,monospace", 40, bold=True)
        # the countdown digit: as big as the picture can carry, so it reads from
        # across the room with a gun in your hands
        huge = pygame.font.SysFont("Menlo,monospace", max(60, H // 4), bold=True)
        # the keymap is eight rows wide, so it is measured to fit rather than set
        # at a fixed size — and it has to fit inside the score panel too (0.86 W)
        km_font = _fit_font(pygame, KEYMAP, int(W * 0.80))
        # pre-render the sprites: first look for frames sliced out of the sprite
        # sheet (assets/sprites/), otherwise individual PNGs or the built-in pixel
        # art. The sprite is scaled to the duck size from the settings.
        duck_px_w = int(self.world.settings.duck.width * W)
        # The dog is sized the same way as everything else — a fraction of the
        # picture ([dog] width) — so it is the same dog on a 27" monitor and on a
        # 55" TV, where it used to be a fixed 150 px that shrank as the picture
        # grew.
        dog_px_w = int(settings.dog.width * W)
        art = _load_sheet(pygame, assets_dir, duck_px_w, dog_px_w,
                          settings.dog.catch_scale) \
            or _load_fallback(pygame, assets_dir, dog_px_w, settings.dog.catch_scale)
        dog_walk = art["dog_walk"]
        dog_catch = art["dog_catch"]
        dog_laugh = art["dog_laugh"]

        # ---- the dog's band: the bottom [dog] band of the picture, and nothing
        # above it. DOG_TOP is the highest any dog pixel may reach (the pop-up
        # tops out exactly there), DOG_FEET is where it stands — a little above
        # the picture's bottom edge, so the paws sit in the grass rather than on
        # the very last row.
        DOG_TOP = int(H * (1.0 - settings.dog.band))
        DOG_FEET = H - max(1, int(H * settings.dog.band * 0.06))

        def use_background(i):
            """The background scaled to the window, plus the grass line the dog walks."""
            b = backgrounds[i]
            return (pygame.transform.scale(b["image"].convert(), (W, H)),
                    int(b["grass"] * H))

        if backgrounds:
            bg, GRASS_Y = use_background(bg_index)
        else:
            GRASS_Y = int(H * 0.80)
            bg = _procedural_bg(pygame, W, H, GRASS_Y)

        def draw_background():
            screen.blit(bg, (0, 0))

        def draw_center(text, glyphs, y, color=(255, 255, 255)):
            img = glyphs.render(text, True, color)
            screen.blit(img, (W // 2 - img.get_width() // 2, y))

        def draw_keymap(y, key_ink=(255, 225, 90), text_ink=(225, 225, 225),
                        shade=False):
            """The controls in two columns: the keys right-aligned in one, what
            they do left-aligned in the other, and the pair of columns centred as
            a block. (Not both columns hung off the picture's centre line — the
            wording is longer than the key names, so that throws the block to the
            right and runs the longest row off the edge.) Returns the y it
            finished at."""
            gap = max(4, W // 200)
            keys = [km_font.render(k, True, key_ink) for k, _ in KEYMAP]
            acts = [km_font.render(a, True, text_ink) for _, a in KEYMAP]
            kw = max(i.get_width() for i in keys)
            aw = max(i.get_width() for i in acts)
            x0 = (W - (kw + 2 * gap + aw)) // 2
            if shade:
                # the title screen has no panel under it, and grey-on-tree is
                # not something you read from across the room
                pad = max(6, W // 100)
                box = pygame.Surface(
                    (kw + 2 * gap + aw + 2 * pad,
                     len(keys) * (km_font.get_height() + 2) + 2 * pad - 2),
                    pygame.SRCALPHA)
                box.fill((0, 0, 0, 150))
                screen.blit(box, (x0 - pad, y - pad))
            for k, a in zip(keys, acts):
                screen.blit(k, (x0 + kw - k.get_width(), y))
                screen.blit(a, (x0 + kw + 2 * gap, y))
                y += km_font.get_height() + 2
            return y

        def draw_dog_walking(x, t):
            """The dog trotting along the grass, inside its band."""
            frame = dog_walk[int(t * 8) % len(dog_walk)]
            # its paws stand on DOG_FEET, but it never rises above the band
            screen.blit(frame, (x, max(DOG_TOP, DOG_FEET - frame.get_height())))

        def draw_results(mode, name_buf, table, aborted):
            """The round result, the high-score name entry and the best-scores table."""
            w = self.world
            panel = pygame.Surface((int(W * 0.86), int(H * 0.84)), pygame.SRCALPHA)
            panel.fill((0, 0, 0, 190))
            px, py = (W - panel.get_width()) // 2, (H - panel.get_height()) // 2
            screen.blit(panel, (px, py))

            y = py + int(H * 0.04)
            draw_center(f"{w.hits} OF {w.total} DUCKS", big, y, (255, 225, 90))
            y += big.get_height() + 6
            draw_center(f"{w.shots} shots  ·  {w.accuracy:.0f}% accuracy  "
                        f"·  {w.elapsed:.0f}s", font, y)
            y += font.get_height() + 4
            if aborted:
                # stopped with ESC: say so, because "12 of 100" otherwise reads
                # like a bad round rather than a short one
                draw_center(f"STOPPED EARLY — {w.released} of {w.total} ducks "
                            "were let out", font, y, (255, 170, 120))
                y += font.get_height()
            y += int(H * 0.035)

            if mode == "name":
                draw_center("NEW HIGH SCORE — TYPE YOUR NAME, THEN ENTER", font, y,
                            (255, 225, 90))
                y += font.get_height() + 8
                cursor = "_" if int(t_mode * 2) % 2 else " "
                draw_center((name_buf or "") + cursor, big, y)
                y += big.get_height() + int(H * 0.03)

            draw_center("HIGH SCORES", font, y, (170, 220, 255))
            y += font.get_height() + 8
            if not table:
                draw_center("empty so far — this round can be the first", font, y)
                y += font.get_height()
            for i, e in enumerate(table, 1):
                # highlight the player's own fresh result
                mine = (mode == "over" and e.hits == w.hits and e.shots == w.shots
                        and e.ducks == w.total)
                line = (f"{i:>2}. {e.name[:12]:<12} {e.hits:>3} ducks  "
                        f"{e.accuracy:>3.0f}%  {e.date[5:]}")
                draw_center(line, font, y, (255, 225, 90) if mine else (245, 245, 245))
                y += font.get_height() + 2

            if mode == "name":
                draw_center("ENTER — SAVE   ·   ESC — SKIP", font,
                            py + panel.get_height() - font.get_height() - int(H * 0.03),
                            (200, 200, 200))
                return
            # The same keymap as the title screen, under the same rule: the
            # round ends where the player is standing, not where the keyboard is.
            # The trigger is listed first because it is what starts the next one.
            y += int(H * 0.03)
            block = len(KEYMAP) * (km_font.get_height() + 2)
            bottom = py + panel.get_height() - int(H * 0.03) - block
            draw_center("TRIGGER OR SPACE — BACK TO THE TITLE SCREEN", font,
                        max(y, bottom) - font.get_height() - 6, (255, 225, 90))
            draw_keymap(max(y, bottom))

        # scene state: intro -> ready (countdown) -> play -> name (name entry)
        # -> over (score table) -> intro again. Every round starts from the title
        # screen and waits for a trigger there, whether it is the first of the
        # session or the fifth — "play again" must not be one pull away from a
        # countdown that has already started.
        mode = "intro"
        t_mode = 0.0
        DOG_START_X = -float(dog_walk[0].get_width())
        dog_x = DOG_START_X
        name_buf = ""
        gun = settings.gun
        gun_is_picture = gun.frame == "picture"
        show_marks = [self.align]          # --align starts the corner targets up
        show_gun = [False]                 # G: the gun's report rate and dropouts
        hide_cross = [False]               # A on the remote (or C): no crosshair
        keepalive = [False]                # K: the bridge's link keep-alive
        # the dog's pop-up reaction: kind in (None,'catch','laugh'), phase 0..1
        pop_kind = None
        pop_t = 0.0
        last_landed = 0
        last_escaped = 0
        crosshair = [0.5, 0.5]
        marks = []                 # where the shots went: {x, y, t, hit}
        aim_prev = [0.5, 0.5]      # last frame's raw aim, for the lead below
        aim_vel = [0.0, 0.0]       # its smoothed velocity, playfields per second
        prev_mouse_down = False

        running = True
        while running:
            dt = clock.tick(FPS) / 1000.0
            t_mode += dt

            # ---- input ----
            fire = False
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type != pygame.KEYDOWN:
                    continue
                elif mode == "name":
                    # while a name is being typed, keys go into the string, not the game
                    if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        table = scores.add(scores.from_world(self.world, name_buf))
                        mode = "over"
                    elif e.key == pygame.K_BACKSPACE:
                        name_buf = name_buf[:-1]
                    elif e.key == pygame.K_ESCAPE:
                        mode = "over"            # changed their mind — do not save
                    elif e.unicode.strip() and len(name_buf) < scores.NAME_MAX:
                        name_buf += e.unicode
                elif e.key == pygame.K_ESCAPE and mode in ("ready", "play"):
                    # Stop the round where it is and go to the result, with what
                    # has been shot so far offered to the table — a hundred ducks
                    # is a long way to be stuck when the arm gets tired, and
                    # quitting the game outright would throw the score away.
                    self.world.stop()
                    mode = ("name" if scores.qualifies(table, self.world.hits,
                                                       self.world.shots) else "over")
                    t_mode = 0.0
                elif e.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif e.key == pygame.K_k:
                    # the bridge's keep-alive: an output report every 250 ms, no
                    # motor. Recoil is gone, but the A/B run that cleared it left
                    # the question of whether a link that is being talked to
                    # stays faster — this is how to answer it inside one round.
                    cmd = getattr(source, "command", None)
                    if cmd is not None:
                        keepalive[0] = not keepalive[0]
                        cmd("k")
                elif e.key == pygame.K_c:
                    hide_cross[0] = not hide_cross[0]
                elif e.key == pygame.K_g:
                    show_gun[0] = not show_gun[0]
                elif e.key == pygame.K_TAB:
                    show_marks[0] = not show_marks[0]
                elif e.key == pygame.K_b and backgrounds:
                    bg_index = (bg_index + 1) % len(backgrounds)
                    bg, GRASS_Y = use_background(bg_index)
                elif e.key == pygame.K_SPACE and mode == "intro":
                    mode, t_mode = "ready", 0.0
                elif e.key == pygame.K_SPACE and mode == "over":
                    self.world = World(settings=settings)   # a new round
                    mode, t_mode, dog_x, name_buf = "intro", 0.0, DOG_START_X, ""
                    last_landed = last_escaped = 0
                    pop_kind = None

            if source is not None:
                st = source.poll()
                if st.quit:
                    running = False
                ax, ay = aim_to_picture(gun, st.x, st.y, geom)
                # [gun] lead: hide some of the link's delay by advancing the
                # crosshair along the direction it is already travelling. The
                # velocity is smoothed hard, because a raw frame-to-frame
                # difference at this sample rate is mostly noise, and noise
                # multiplied by the lead is jitter. lead = 0 leaves it alone.
                if gun.lead > 0 and dt > 0:
                    a = 0.35
                    aim_vel[0] += a * ((ax - aim_prev[0]) / dt - aim_vel[0])
                    aim_vel[1] += a * ((ay - aim_prev[1]) / dt - aim_vel[1])
                    crosshair[0] = min(1.0, max(0.0, ax + gun.lead * aim_vel[0]))
                    crosshair[1] = min(1.0, max(0.0, ay + gun.lead * aim_vel[1]))
                else:
                    crosshair[0], crosshair[1] = ax, ay
                aim_prev[0], aim_prev[1] = ax, ay
                fire = st.fire
                if st.pressed & 0x02:              # A on the remote
                    hide_cross[0] = not hide_cross[0]
                if st.pressed & 0x04:              # HOME on the remote
                    # the same toggle as the K key, but reachable from where you
                    # actually stand: the laptop is by the screen and the player
                    # is three metres away with both hands on the gun
                    cmd = getattr(source, "command", None)
                    if cmd is not None:
                        keepalive[0] = not keepalive[0]
                        cmd("k")
            else:
                mx, my = pygame.mouse.get_pos()
                crosshair[0] = min(1.0, max(0.0, (mx - offset[0]) / W))
                crosshair[1] = min(1.0, max(0.0, (my - offset[1]) / H))
                md = pygame.mouse.get_pressed()[0]
                fire = md and not prev_mouse_down
                prev_mouse_down = md

            # The round starts on the TRIGGER, not on a timer: a light gun player
            # needs both hands on the gun before the first duck, and pulling the
            # trigger is the one control they have. The pull is swallowed here so
            # it cannot also be the round's first shot.
            if fire and mode == "intro":
                mode, t_mode, fire = "ready", 0.0, False
            elif fire and mode == "over":
                # back to the title screen, not straight into the countdown: the
                # pull that dismisses the score table is the one you make while
                # still looking at it, and it must not also be the pull that
                # starts the next round
                self.world = World(settings=settings)
                mode, t_mode, dog_x, name_buf, fire = "intro", 0.0, DOG_START_X, "", False
                last_landed = last_escaped = 0
                pop_kind = None

            # ---- intro: the dog walks and sniffs ----
            if mode == "intro":
                draw_background()
                dog_x += settings.dog.speed * W * dt
                # the title screen waits for the trigger however long that takes,
                # so the dog walks the field on a loop instead of once
                if dog_x > W:
                    dog_x = DOG_START_X
                draw_dog_walking(dog_x, t_mode)
                y = int(H * 0.08)
                draw_center("DUCK HUNT", big, y)
                y += big.get_height() + int(H * 0.02)
                # blink it, so it reads as "waiting for you" rather than "stuck"
                if int(t_mode * 2) % 2:
                    draw_center("PULL THE TRIGGER TO START", big, y, (255, 225, 90))
                y += big.get_height() + int(H * 0.02)
                draw_center(f"{self.world.total} DUCKS  ·  "
                            f"{settings.round.countdown:g}s COUNTDOWN", font, y,
                            (255, 255, 240))
                y += font.get_height() + int(H * 0.03)
                draw_keymap(y, shade=True)
                draw_crosshair()
                present()
                continue

            # ---- ready: the countdown, gun already up ----
            if mode == "ready":
                draw_background()
                dog_x += settings.dog.speed * W * dt
                if dog_x > W:
                    dog_x = DOG_START_X
                draw_dog_walking(dog_x, t_mode)
                left = settings.round.countdown - t_mode
                if left <= 0:
                    mode, t_mode = "play", 0.0
                else:
                    # whole seconds, counting down: 5 shows while 4 < left <= 5
                    count = huge.render(str(math.ceil(left)), True, (255, 225, 90))
                    cy0 = int(H * 0.18)
                    screen.blit(count, (W // 2 - count.get_width() // 2, cy0))
                    sub = big.render("GET READY", True, (255, 255, 255))
                    screen.blit(sub, (W // 2 - sub.get_width() // 2,
                                      cy0 + count.get_height() + 4))
                    draw_crosshair()
                    present()
                    continue

            # ---- round results and the high-score table ----
            if mode in ("name", "over"):
                draw_background()
                draw_results(mode, name_buf, table, self.world.stopped)
                present()
                continue

            # ---- gameplay ----
            # Every shot leaves a mark where it went. With the crosshair hidden
            # (A on the remote) this is the only thing that says where the barrel
            # actually pointed, and even with it visible it is the feedback a
            # light gun owes you: the ring is the hit zone the shot had, the hole
            # stays behind for a moment. Hit or miss is taken from the score,
            # which is what decided it.
            hits_before = self.world.hits
            self.world.update(dt, crosshair[0], crosshair[1], fire)
            if fire:
                marks.append({"x": crosshair[0], "y": crosshair[1], "t": 0.0,
                              "hit": self.world.hits > hits_before})
                del marks[:-MARKS_MAX]
            if self.world.finished:
                mode = ("name" if scores.qualifies(table, self.world.hits,
                                                   self.world.shots) else "over")

            # the dog's reactions to core events
            if pop_kind is None:
                if self.world.landed > last_landed:
                    pop_kind, pop_t = "catch", 0.0
                elif self.world.escaped > last_escaped:
                    pop_kind, pop_t = "laugh", 0.0
            last_landed = self.world.landed
            last_escaped = self.world.escaped
            if pop_kind is not None:
                pop_t += dt
                if pop_t > settings.dog.pop:
                    pop_kind = None

            draw_background()

            # ducks — the sprite is centred on the hitbox, colour comes from d.variant
            for d in self.world.ducks:
                skin = art["ducks"][DUCK_COLORS[d.variant % len(DUCK_COLORS)]]
                if d.state is DuckState.FALLING:
                    spr = skin["hit"]
                else:
                    side = "right" if d.facing is Facing.RIGHT else "left"
                    spr = skin[side][FLAP[int(d.age * 10) % len(FLAP)]]
                screen.blit(spr, (int((d.x + d.w / 2) * W - spr.get_width() / 2),
                                  int((d.y + d.h / 2) * H - spr.get_height() / 2)))

            # the dog (pops up out of the grass)
            if pop_kind is not None:
                spr = dog_catch if pop_kind == "catch" else dog_laugh
                # An arc inside the dog's band: it comes up from below the
                # picture's bottom edge and at the top of the arc its head just
                # reaches DOG_TOP — the band's ceiling — then it drops back out
                # of sight (0->1->0 over [dog] pop seconds).
                up = 1.0 - abs(pop_t / (settings.dog.pop / 2) - 1.0)
                up = max(0.0, min(1.0, up))
                top = H - int(up * (H - DOG_TOP))
                screen.blit(spr, (W // 2 - spr.get_width() // 2, top))

            for m in marks:
                m["t"] += dt
            while marks and marks[0]["t"] > MARK_LIFE:
                marks.pop(0)
            draw_marks()
            draw_crosshair()

            # HUD: hits, how many of the flock have been released, round time
            w = self.world
            hud = font.render(
                f"HIT {w.hits}   DUCK {w.released}/{w.total}   "
                f"{w.elapsed:.0f}s   ACC {w.accuracy:.0f}%",
                True, (255, 255, 255))
            screen.blit(hud, (16, 12))

            # G: what the gun's stream actually looks like. "Laggy" has three
            # different causes that feel identical — a slow rate, reports
            # arriving in clumps, and beacons dropping out (the aim then holds
            # its last position, which reads as sticking) — and these numbers
            # tell them apart while playing, without stopping to run ir_view.
            if show_gun[0]:
                gs = getattr(source, "stats", None)
                snap = gs.snapshot() if gs is not None else None
                if snap is None:
                    text = f"gun: no reports · fps {clock.get_fps():.0f}"
                else:
                    # short labels: this has to fit across the picture
                    parts = [f"gun {snap['rate']:.0f}/s",
                             f"stalls {snap['holes']:.1f}/s",
                             f"worst {1000*snap['worst']:.0f}ms",
                             f"blind {100*snap['blind']:.0f}%"]
                    if snap["age"] is not None:
                        parts.append(f"age {1000*snap['age']:.0f}ms")
                    parts.append(f"fps {clock.get_fps():.0f}")
                    parts.append(f"keepalive {'ON' if keepalive[0] else 'off'}")
                    text = " · ".join(parts)
                img = font.render(text, True, (255, 240, 140))
                screen.blit(img, (16, 12 + hud.get_height() + 6))

            present()

        if gun_log is not None:
            gun_log.close()
        pygame.quit()
