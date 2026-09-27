"""The pixel (retro) Duck Hunt frontend, built on pygame.

Original pixel sprites in the Duck Hunt spirit (our own, not copies): a duck
flapping its wings, a downed duck, and the dog — sniffing around / retrieving the
catch / laughing at a miss. It runs on the same `World` core and the same
`InputSource` as the terminal version, so the hardware and its calibration do not
change.

Running it:
    pip install pygame
    python3 main.py                                    # aim with the mouse
    python3 main.py --serial /dev/tty.usbserial-0001   # light gun
"""

from __future__ import annotations

import math
import os
import random
import sys
import time
import tomllib

from ..core import calibration as calib_core
from ..core import modes as modes_core
from ..core import player
from ..core.models import DuckState, Facing
from ..core.world import World
from ..net.leaderboard_client import LeaderboardClient, PlayerLookup
from ..net.leaderboard_client import payload as board_payload
from ..net.leaderboard_client import refusal
from ..sound import Sounds
from .calibrate import Calibrator

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

# The row that names the rounds. It is filled in per session from the modes there
# actually are, and left out of the keymap altogether when there is only one
# round on the disk — a control that does nothing is worse than no control at
# all. Kept out here so `run()` can recognise it by identity.
MODE_ROW = ("M · A on the title", "which round — %s")

# The controls, in one place: shown on the title screen and on the result screen,
# because a player standing three metres away with a gun in both hands has no
# way to look them up. Remote buttons are named first where there is one — that is
# the control they actually have in their hands. The mode comes second because it
# is the other thing the title screen is for: which round, and then start it.
KEYMAP = [
    ("TRIGGER · SPACE", "start the round, and shoot in it"),
    MODE_ROW,
    ("ESC", "stop the round — the score still counts"),
    ("Q", "quit Duck Hunt"),
    ("C · A in a round", "show / hide the crosshair"),
    ("B", "next background"),
    ("G", "the gun's report rate and dropouts"),
    ("F1", "sight the gun in on five targets"),
    ("F2", "use that calibration on / off"),
]

# The two lines the name screen gains once the board has names to offer. They
# are set in a measured size rather than a chosen one, like the keymap and for
# the same reason: the second is half again as long as the line it replaces, and
# a windowed picture is about sixty characters wide.
NAME_NOTE = "PICKING A NAME KEEPS ITS BEST — THIS ROUND JUST ADDS A TRY"
NAME_HINT = "ENTER — SEND IT   ·   TRIGGER OR TAB — TAKE A NAME   ·   ESC — SKIP"

FPS = 60
SCALE = 5          # one sprite pixel = SCALE screen pixels
MARK_LIFE = 1.4    # seconds a shot's hole stays on screen before it fades out
RING_LIFE = 0.22   # ... and how long the ring that snaps out to the hit zone lives
MARKS_MAX = 24     # keep the last few; a fast round can put out a lot of lead
HUD_X = 16         # the left margin the HUD line and the shell belt share
# One shell on the belt is this many shots, and a shot takes a quarter off the
# leading one — four, so the default magazine of 40 is ten shells exactly. It is
# a picture of the magazine and not a scale of it: change [round] ammo and the
# belt grows or shrinks, it never puts more shots inside a shell to keep its own
# length.
SHELL_SHOTS = 4
SUG_MAX = 4        # names offered under the name field; more is a table, not a hint

def aim_to_picture(gun, gx, gy, geom, clamp=True):
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

    `clamp=False` hands back the number as it came out, outside the picture and
    all. The game wants it clamped — a crosshair does not leave the screen — but
    the calibrator is measuring exactly how far outside the gun lands, and a
    clamped reading there is a measurement of the clamp.
    """
    sw, sh, W, H, ox, oy = geom
    u = gun.beacon_cx + (gx - 0.5) * gun.beacon_w
    v = gun.beacon_cy + (gy - 0.5) * gun.beacon_h
    if gun.frame == "display":
        u = (u * sw - ox) / W
        v = (v * sh - oy) / H
    if not clamp:
        return u, v
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
    def __init__(self, settings=None, calibrate=False, player_name="",
                 source_name=None, modes=None, mode=0):
        # The rounds the title screen cycles between, and which of them this
        # session opens on. A mode may only change the round and never the rig
        # (core/modes.py), which is the whole reason this is a list here rather
        # than a flag back in main: the window, the sight-in, the beacons and the
        # board are the same in all of them, so switching costs a new World and
        # a re-sized duck instead of a restart.
        self.modes = list(modes) if modes else []
        self.mode_index = min(max(mode, 0), len(self.modes) - 1) if self.modes else 0
        if self.modes:
            settings = self.modes[self.mode_index].settings
        self.world = World(settings=settings)
        if not self.modes:
            # Called with plain settings (the tests, and anyone embedding this):
            # one unnamed round, nothing to switch to, and the title screen says
            # neither more nor less than it did before modes existed.
            self.modes = [modes_core.Mode(modes_core.BASE_NAME,
                                          modes_core.BASE_NOTE, None,
                                          self.world.settings)]
        # The name the round is sent to the board under. Empty unless --player
        # says who is shooting tonight: the field after a round starts blank.
        # It used to be pre-filled with the last name typed on this machine,
        # which is the wrong default in the only room this game is played in —
        # the next player finishes a round, the previous player's name is
        # already in the field, and one pull of A signs their round to somebody
        # else. What is offered instead is the list: type a letter, or pull the
        # trigger, and the names already on the board come up to be taken.
        self.player_name = player_name
        # which of the gun paths is in use — goes into the row, for reading the
        # board back later and asking "which cabinet was this"
        self.source_name = source_name
        # --calibrate: straight into the sighting-in screen, before the title
        self.calibrate = calibrate

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

        # The mixer's buffer size is taken when the subsystem comes up, so the
        # ask has to happen before init() — after it, the sounds play at SDL's
        # default latency, which is enough to hear your own trigger late.
        Sounds.pre_init(pygame)
        pygame.init()
        assets_dir = os.path.join(os.path.dirname(__file__), "..", "..", "assets")
        settings = self.world.settings
        # The board is a separate process on a screen of its own: the game posts
        # one row per round and draws nothing that comes back. Off unless
        # [leaderboard] enabled = true, and never on the game's own thread.
        board = LeaderboardClient(settings.leaderboard)
        # ... and the one thing the game does read back off it: who is already
        # there, so a returning player picks their own spelling off the name
        # screen instead of inventing a third one. Spawns nothing until that
        # screen asks, and answers nothing when the board is off or away.
        look = PlayerLookup(settings.leaderboard, limit=SUG_MAX)
        # the shot, the quack and the dog's laugh ([sound] in settings.toml).
        # Silent if the files or the audio device are missing — it says so once.
        sfx = Sounds(pygame, settings.sound, assets_dir)

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
        if self.world.settings.scene.fullscreen:
            display = _open_fullscreen(pygame, want_display, desktops)
            sw, sh = display.get_size()
            # Fill the screen's height, keep the aspect: the art pixels no
            # longer land on a whole number of display pixels, so some come out
            # a pixel bigger than their neighbours. transform.scale is
            # nearest-neighbour, so nothing smears — and the ducks are half
            # again as big as a whole-number letterboxed fit makes them, which
            # is the whole reason this is the only fit there is.
            H, W = sh, int(round(bw * sh / bh))
            if W > sw:                          # a screen narrower than the art
                W, H = sw, int(round(bh * sw / bw))
            k = max(1, round(H / bh))
            offset = ((sw - W) // 2, (sh - H) // 2)
            screen = pygame.Surface((W, H))
        else:
            dw, dh = desktops[max(0, want_display)]
            fits = max(1, min(dw // bw, (dh - 120) // bh))
            k = max(2, min(4, fits))
            W, H = bw * k, bh * k
            display = (pygame.display.set_mode((W, H)) if want_display < 0
                       else pygame.display.set_mode((W, H), display=want_display))
            sw, sh = W, H
            offset = (0, 0)
            screen = display
        # Where the picture came out: the rectangle the beacons are measured
        # against when [gun] frame = "picture", and the number to check after
        # changing the display or its resolution.
        print(f"display {want_display if want_display >= 0 else 'auto'} of "
              f"{len(desktops)} connected {desktops} — using {sw}x{sh}"
              f"{'' if self.world.settings.scene.fullscreen else ' (windowed)'}")
        print(f"picture {W}x{H} px at {offset[0]},{offset[1]} of {sw}x{sh} "
              f"({100*W/sw:.0f}% x {100*H/sh:.0f}% of the display, "
              f"{'fit to height' if W * bh != H * bw or H % bh else f'scale {k}x'}"
              f"{'' if H % bh == 0 else f', ~{H/bh:.2f}x'})")
        pygame.mouse.set_visible(False)      # the game draws its own crosshair
        pygame.display.set_caption("🦆 Duck Hunt")

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

        def draw_belt():
            """What is left in the magazine, as shells on a belt, not as a count.

            One shell is `SHELL_SHOTS` shots and every shot takes a quarter off
            the top of the leading one, so the default `[round] ammo = 40` is
            exactly ten shells — a row you read the way you read a fuel gauge,
            without reading a number at all. A magazine that is not a whole
            number of shells (ammo = 10, say) starts with its last shell part
            full, which is the honest picture of two and a half shells rather
            than a belt that quietly rounds the magazine up.

            It sits in the strip below `[duck] sky` — the part of the picture the
            ducks are kept out of — so it can never cover the thing being aimed
            at, and it is drawn before the crosshair so the crosshair is never
            covered either. The dog trots through it: he goes on first and the
            shells over him, because half a second of dog should not be able to
            take the gauge away.

            Rounds that do not count shots (practice) have no belt at all. A
            magazine that cannot run out is not a thing to watch.
            """
            cap = settings.round.ammo
            if cap <= 0:
                return
            left = max(0, self.world.ammo)
            shells = -(-cap // SHELL_SHOTS)     # ceil: a part-full last shell shows

            floor_y = H - max(6, int(H * 0.02))
            # nothing flies below this, so this is where the belt may start
            sky_y = int(H * settings.duck.sky)
            tall = max(int(H * 0.045), min(int(H * 0.075), floor_y - sky_y))
            wide = max(3, int(W * 0.016))
            gap = max(2, wide // 2)
            # A deep magazine makes the shells thinner rather than fewer: a
            # quarter is one shot wherever the belt is, and a belt that put two
            # shots in a quarter to keep its own proportions would be a gauge
            # that lies about the only thing it is for. Past about twenty shells
            # they are too thin to carry an outline or the quarter lines and the
            # belt becomes a row of red hairlines — still a gauge, just no longer
            # a picture of ammunition. That is a magazine three times the size of
            # any this game ships, and the alternative is drawing 200 shots as
            # something other than 200 shots.
            room = int(W * 0.40)
            if shells * (wide + gap) > room:
                span = max(3, room // shells)
                wide, gap = max(2, span * 2 // 3), max(1, span - span * 2 // 3)
            detail = wide >= 5           # room inside the shell for its own lines

            brass_h = max(2, int(tall * 0.28))
            body_h = tall - brass_h
            top = floor_y - tall
            for i in range(shells):
                x = HUD_X + i * (wide + gap)
                quarters = min(SHELL_SHOTS, max(0, left - i * SHELL_SHOTS))
                # the hull first, dark, so a spent loop is still a loop on the
                # belt — how much has gone is half of what a bandolier tells you
                pygame.draw.rect(screen, (46, 40, 38), (x, top, wide, body_h))
                pygame.draw.rect(screen, (196, 156, 68),
                                 (x, top + body_h, wide, brass_h))
                pygame.draw.line(screen, (138, 104, 40),
                                 (x, top + body_h + brass_h // 2),
                                 (x + wide - 1, top + body_h + brass_h // 2))
                if quarters:
                    # the load empties from the top, so what is left is the
                    # BOTTOM quarters — the shell shortens the way a shell does
                    fill = int(round(body_h * quarters / SHELL_SHOTS))
                    y = top + body_h - fill
                    pygame.draw.rect(screen, (198, 46, 38), (x, y, wide, fill))
                    pygame.draw.line(screen, (240, 96, 84),
                                     (x, y), (x + wide - 1, y))
                    # the quarters themselves, so the belt can be counted and not
                    # only glanced at
                    if detail:
                        for q in range(1, quarters):
                            qy = top + body_h - int(round(body_h * q / SHELL_SHOTS))
                            pygame.draw.line(screen, (126, 28, 22),
                                             (x + 1, qy), (x + wide - 2, qy))
                if detail:
                    pygame.draw.rect(screen, (24, 20, 18), (x, top, wide, tall), 1)

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

        def present():
            """Show the frame: centred in fullscreen, as-is in a window.

            """
            if screen is not display:
                display.fill((0, 0, 0))
                display.blit(screen, offset)
            pygame.display.flip()

        # the geometry aim_to_picture needs: display size, picture size, where
        # the picture sits in the display
        geom = (sw, sh, W, H, offset[0], offset[1])

        clock = pygame.time.Clock()
        font = pygame.font.SysFont("Menlo,monospace", 22, bold=True)
        big = pygame.font.SysFont("Menlo,monospace", 40, bold=True)
        # the countdown digit: as big as the picture can carry, so it reads from
        # across the room with a gun in your hands
        huge = pygame.font.SysFont("Menlo,monospace", max(60, H // 4), bold=True)
        # The keymap this session actually has. The mode row names the rounds
        # that were found on disk rather than a fixed pair, and goes away when
        # there is only one of them — a control that does nothing is worse than
        # no control at all.
        names = [m.name.lower() for m in self.modes]
        listed = " / ".join(names[:3]) + ("…" if len(names) > 3 else "")
        keymap = []
        for row in KEYMAP:
            if row is not MODE_ROW:
                keymap.append(row)
            elif len(self.modes) > 1:
                keymap.append((row[0], row[1] % listed))
        # the keymap is a dozen rows wide, so it is measured to fit rather than
        # set at a fixed size — and it has to fit inside the score panel too
        km_font = _fit_font(pygame, keymap, int(W * 0.80))
        # ... and the line under the mode's name on the title screen. Measured
        # across EVERY mode's note, not just the one showing, so the sentence
        # does not change size as the modes are cycled.
        note_font = _fit_font(pygame, [(m.note.upper(), "") for m in self.modes]
                              or [("", "")], int(W * 0.80), biggest=18)
        # ... and the name screen's own two lines, measured against the same
        # 0.80 W, which is exactly the width inside its panel
        sug_font = _fit_font(pygame, [(NAME_NOTE, ""), (NAME_HINT, "")],
                             int(W * 0.80))

        def hud_text(score, hits, released, ammo, secs, acc):
            """The HUD's one line, from the numbers it shows.

            The score leads it because the score is what the round is worth now —
            hits are no longer the same number, a miss costs and the dog costs
            more. The magazine follows the flock, and only while shots are
            counted at all: a magazine you cannot see is one you cannot plan
            around, and a magazine that does not exist is just a number in the
            way. A function rather than an f-string on the spot so the line can
            be measured before the round with the widest values it could reach.
            """
            parts = [f"SCORE {score}", f"HIT {hits}",
                     f"DUCK {released}/{settings.round.ducks}"]
            if ammo >= 0:
                parts.append(f"AMMO {ammo}")
            parts += [f"{secs:.0f}s", f"ACC {acc:.0f}%"]
            return "   ".join(parts)

        # The HUD gets its own measured size for the same reason the keymap does:
        # it carries two more fields than it used to, and at 22 pt the line runs
        # off the side of a windowed picture. Measured once against the widest it
        # can get — every count at its ceiling, the score deep in the red, the
        # minus sign included — and then left alone, so the numbers do not change
        # size as they change.
        hud_font = _fit_font(pygame, [(hud_text(
            -99 * settings.round.ducks, settings.round.ducks,
            settings.round.ducks, settings.round.ammo or -1,
            999.0, 100.0), "")], W - 32)
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
            keys = [km_font.render(k, True, key_ink) for k, _ in keymap]
            acts = [km_font.render(a, True, text_ink) for _, a in keymap]
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

        def dog_pop_sprite(kind, t):
            """The popping-up dog: his sprite and the corner it is blitted at.

            One sum with two callers — the blit below and the box the core decides
            shots against — because a second copy of this arc would eventually
            disagree by a pixel or by a frame, and then the dog would be hit
            where he is not drawn. None while he is down.
            """
            if kind is None:
                return None
            spr = dog_catch if kind == "catch" else dog_laugh
            # An arc inside the dog's band: he comes up from below the picture's
            # bottom edge and at the top of the arc his head just reaches
            # DOG_TOP — the band's ceiling — then he drops back out of sight
            # (0->1->0 over [dog] pop seconds).
            up = 1.0 - abs(t / (settings.dog.pop / 2) - 1.0)
            up = max(0.0, min(1.0, up))
            return spr, W // 2 - spr.get_width() // 2, H - int(up * (H - DOG_TOP))

        def dog_pop_box(kind, t):
            """The same dog as the core wants him: `(x0, y0, x1, y1)` of 0..1.

            Divided straight out of the blit rectangle, so the box can never
            describe a dog the screen is not showing. Part of him hangs below the
            picture on the way up and on the way down, which the box says
            honestly — the aim is clamped to the picture, so those rows are simply
            never hit.
            """
            placed = dog_pop_sprite(kind, t)
            if placed is None:
                return None
            spr, left, top = placed
            return (left / W, top / H,
                    (left + spr.get_width()) / W, (top + spr.get_height()) / H)

        def draw_results(mode, name_buf, aborted, status, sug=(), sug_i=-1):
            """The round result, and the name the row is sent to the board under.

            Nothing of the leaderboard is drawn here on purpose — no ranks, no
            other players, no table. The board is a screen of its own, and a game
            that also showed a top ten would be two scoreboards quietly
            disagreeing about which one you should be reading. What this screen
            does say is whether the row got there, which is about the player's own
            round rather than about the board.

            `sug` is not that table either. It is the spellings already on the
            board that match what is being typed, offered because typing a name
            from scratch every evening is how one player becomes three; `sug_i`
            is the one taken, or -1 while the typed text stands.
            """
            w = self.world
            shown = list(sug)[:SUG_MAX] if mode == "name" else []
            # The name screen is four lines and wants to sit in the middle of the
            # picture; the result screen carries the whole keymap under it. With
            # names on offer the name panel is instead as tall as what it carries
            # — 0.16 H of gaps, the score and the field (`big` twice), the ducks
            # and the shots, the question and the footer (`font` four times),
            # 20 px of fixed gaps between them, whichever of the dog and the
            # early stop are there, and the block of names — and never taller
            # than the picture, nor shorter than it has always been.
            tall = 0.84
            km_block = len(keymap) * (km_font.get_height() + 2)
            if mode == "name":
                block = (2 * sug_font.get_height() + 4 + int(H * 0.02)
                         + len(shown) * (font.get_height() + 2)) if shown else 0
                need = (int(H * 0.16) + 2 * big.get_height()
                        + 4 * font.get_height() + 20 + block
                        + (font.get_height()
                           if aborted or (w.dry and w.released < w.total)
                           else 0)
                        + (font.get_height() if w.dog_hits else 0))
                tall = min(0.94, max(0.62, need / H))
            else:
                # The result screen carries the whole keymap under the round, and
                # the round has grown a line — so the fixed 0.84 no longer holds
                # both on a small picture, and the keymap went out through the
                # bottom of the panel. Measured the same way the name panel is:
                # the gaps (0.05 + 0.04 + 0.03 of H), the headline, the three
                # lines under it, whichever of the dog, the early stop and the
                # delivery line are there, and the keymap with its own heading.
                # Never shorter than it has always been.
                need = (int(H * 0.12) + big.get_height()
                        + 3 * font.get_height() + 8 + km_block
                        + (font.get_height() if w.dog_hits else 0)
                        + (font.get_height()
                           if aborted or (w.dry and w.released < w.total)
                           else 0)
                        + (font.get_height() + int(H * 0.02) if status else 0)
                        + font.get_height() + 6)
                tall = min(0.96, max(0.84, need / H))
            panel = pygame.Surface((int(W * 0.86), int(H * tall)), pygame.SRCALPHA)
            panel.fill((0, 0, 0, 190))
            px, py = (W - panel.get_width()) // 2, (H - panel.get_height()) // 2
            screen.blit(panel, (px, py))

            y = py + int(H * 0.05)
            # The score is the headline, because the score is what the round is
            # worth: the ducks are still the story of it, but ten ducks bought
            # with forty shots is not the same round as ten with twelve, and only
            # one of those two numbers says so. It can be negative, which is the
            # point and reads as one.
            draw_center(f"SCORE {w.score}", big, y, (255, 225, 90))
            y += big.get_height() + 2
            draw_center(f"{w.hits} OF {w.total} DUCKS", font, y, (255, 255, 240))
            y += font.get_height() + 2
            draw_center(f"{w.shots} shots  ·  {w.accuracy:.0f}% accuracy  "
                        f"·  {w.elapsed:.0f}s", font, y)
            y += font.get_height() + 4
            if w.dog_hits:
                # He is on your side and he fetches your ducks, so what it cost
                # to shoot him is said out loud rather than left inside the
                # score to be worked out from the accuracy.
                draw_center(f"THE DOG: {w.dog_hits} × {settings.score.dog}",
                            font, y, (255, 170, 120))
                y += font.get_height()
            if aborted:
                # stopped with ESC: say so, because "12 of 100" otherwise reads
                # like a bad round rather than a short one
                draw_center(f"STOPPED EARLY — {w.released} of {w.total} ducks "
                            "were let out", font, y, (255, 170, 120))
                y += font.get_height()
            elif w.dry and w.released < w.total:
                # ... and the same for a round the magazine ended: with 40 shots
                # for 40 ducks "18 of 40" is what running out looks like, not what
                # shooting badly looks like, and only this line tells them apart.
                # `released < total` matters: a perfect round spends its last shot
                # on the last duck and is dry at the end without having been cut
                # short by it, and telling that player they ran out would be a lie.
                draw_center(f"OUT OF AMMUNITION — {w.released} of {w.total} ducks "
                            "were let out", font, y, (255, 170, 120))
                y += font.get_height()
            y += int(H * 0.04)

            if mode == "name":
                draw_center("WHO WAS SHOOTING?", font, y, (255, 225, 90))
                y += font.get_height() + 10
                cursor = "_" if int(t_mode * 2) % 2 else " "
                # A name may be 50 characters long, and 50 characters in the big
                # font run off both sides of the picture — so the field steps
                # down a size once it is long, and the line is clipped to the
                # panel rather than allowed to escape it.
                inner = panel.get_width() - int(W * 0.06)
                typed = (name_buf or "") + cursor
                face = big if len(typed) <= 14 else font
                while face.size(typed)[0] > inner and len(typed) > 1:
                    typed = typed[1:]          # keep the end: that is where the caret is
                draw_center(typed, face, y)
                y += face.get_height() + int(H * 0.03)

                if shown:
                    draw_center("ALREADY ON THE BOARD:", sug_font, y,
                                (200, 200, 200))
                    y += sug_font.get_height() + 4
                    for i, row in enumerate(shown):
                        tries = int(row.get("attempts", 0) or 0)
                        # the best round that name has, at whatever size it was
                        # played, which is why the ducks are there next to the hits
                        score = (f"{row.get('hits', 0)}/{row.get('ducks', 0)}  "
                                 f"({tries} {'try' if tries == 1 else 'tries'})")
                        who = str(row.get("name", ""))
                        line = f"{who} — {score}"
                        # a long name is cut rather than let out of the panel, the
                        # way the field cuts one — except that here the end of the
                        # line is the score, so it is the name that gives way
                        while font.size(line)[0] > inner and len(who) > 1:
                            who = who[:-1]
                            line = f"{who}… — {score}"
                        draw_center(line, font, y,
                                    (255, 225, 90) if i == sug_i else (200, 200, 200))
                        y += font.get_height() + 2
                    # Taking a name off this list looks exactly like overwriting
                    # whoever is on it, and a player who thinks that is what it
                    # does will type a new spelling to be safe — which is the one
                    # thing the list is here to stop.
                    draw_center(NAME_NOTE, sug_font, y, (170, 170, 170))
                    y += sug_font.get_height()

                hint = "ENTER — SEND IT   ·   ESC — SKIP"
                hint_face = font
                hint_y = (py + panel.get_height() - font.get_height()
                          - int(H * 0.04))
                if shown:
                    hint = NAME_HINT
                    if font.size(hint)[0] > inner:
                        hint_face = sug_font    # a narrow picture, a longer line
                    # ... and never over the last name: on a short picture the
                    # panel has hit its cap and the block is what had to grow
                    hint_y = max(y + 4, py + panel.get_height()
                                 - hint_face.get_height() - int(H * 0.04))
                draw_center(hint, hint_face, hint_y, (200, 200, 200))
                return

            if status:
                draw_center(status, font, y, (170, 220, 255))
                y += font.get_height() + int(H * 0.02)
            # The same keymap as the title screen, under the same rule: the
            # round ends where the player is standing, not where the keyboard is.
            # The trigger is listed first because it is what starts the next one.
            # The pair is kept together and never allowed above `y`, or on a short
            # picture the keymap's headline climbs over the line before it.
            head = max(y, py + panel.get_height() - int(H * 0.03) - km_block
                       - font.get_height() - 6)
            draw_center("TRIGGER OR SPACE — BACK TO THE TITLE SCREEN", font,
                        head, (255, 225, 90))
            draw_keymap(head + font.get_height() + 6)

        def finish_round(name):
            """Keep the round: remember the name, and send the row to the board.

            There used to be a third thing here, a local top ten in `scores.json`.
            It kept being written long after anything stopped reading it back —
            ten rows, on one machine, invisible to everyone not sitting at it,
            while the board next to the television kept every attempt by every
            player. A mirror nobody looks in is not a fallback, it is a file.
            """
            if refusal(self.world, settings):
                # Belt and braces: a refused round has no name screen to be
                # signed on any more, so nothing should reach this at all. The
                # rule lives in refusal() and this is the one call that could
                # break it, which is exactly why the check is here as well.
                return
            name = (name.strip() or "PLAYER")[:player.NAME_MAX]
            board.submit(board_payload(self.world, name,
                                       settings.leaderboard.client_id,
                                       self.source_name))

        # scene state: intro -> ready (countdown) -> play -> name (who was
        # shooting) -> over (the result) -> intro again. The name is asked AFTER
        # the round and after every round, not only a record one: the board keeps
        # every attempt, and a round nobody signed is a row nobody can find.
        # Every round starts from the title
        # screen and waits for a trigger there, whether it is the first of the
        # session or the fifth — "play again" must not be one pull away from a
        # countdown that has already started.
        mode = "intro"
        t_mode = 0.0
        DOG_START_X = -float(dog_walk[0].get_width())
        dog_x = DOG_START_X
        name_buf = self.player_name
        # A --player name is offered, not imposed: the first character typed
        # replaces it whole, so a new player does not have to backspace it out.
        # Without --player the field is simply empty, and "fresh" then costs
        # nothing — there is nothing in it to replace.
        name_fresh = True
        # What the board says about the name being typed: the rows on offer, which
        # of them is taken (-1 — none of them, the typed text stands), whether the
        # list is being cycled rather than typed into, and the text typed by hand,
        # kept so that cycling back off the list returns to it.
        sug = []
        sug_i = -1
        sug_frozen = False
        typed_buf = name_buf
        typed_fresh = name_fresh

        def send_name():
            """Sign the round with what is in the field — ENTER, or A on the gun.

            The trigger picks a name off the list and A sends it, which together
            are the whole point of the list: a player standing three metres away
            with both hands on the gun can sign their round without walking to the
            keyboard. Typing a name the board has never seen still needs one.
            """
            nonlocal mode, t_mode
            if not name_buf.strip():
                return                         # an empty line is not a name
            finish_round(name_buf)
            mode, t_mode = "over", 0.0

        def end_round():
            """Where a finished round goes: the name screen, or straight past it.

            A round that may not go to the board has no row to be signed for, and
            WHO WAS SHOOTING? is then a question with nowhere to put the answer —
            so a refused round goes to the result screen directly, which says why
            instead. Everything the name screen would have reset is reset either
            way, so the round after this one starts from the same place.
            """
            nonlocal mode, t_mode, sug, sug_i, sug_frozen
            nonlocal typed_buf, typed_fresh
            mode, t_mode = ("over" if refusal(self.world, settings)
                            else "name"), 0.0
            # nothing is on offer until the board has answered about this name
            sug, sug_i, sug_frozen = [], -1, False
            typed_buf, typed_fresh = name_buf, name_fresh

        def take_suggestion(step=1):
            """Put the next name on offer into the field — TAB, DOWN or trigger.

            The typed text is one step off the end of the list, so a player who
            cycles past their own name comes back to what they typed rather than
            to somebody else's spelling they then have to fix by hand.
            """
            nonlocal name_buf, name_fresh, sug_i, sug_frozen
            nonlocal typed_buf, typed_fresh
            if not sug:
                return
            if sug_i < 0:
                # ... which the list comes back to, and it comes back whole: a
                # remembered name that is still untouched must stay untouched, or a
                # glance at the list would quietly cost the next player four
                # backspaces
                typed_buf, typed_fresh = name_buf, name_fresh
                sug_i = 0 if step > 0 else len(sug) - 1
            elif (sug_i == 0 and step < 0) or (sug_i == len(sug) - 1 and step > 0):
                # The typed text sits one step off EITHER end of the list, because
                # the trigger only ever goes forward: a player three metres away who
                # cycles past their own name has to be able to keep going and arrive
                # back at what they typed, or the gun has put a stranger's spelling
                # in the field with no way to take it out again.
                name_buf, name_fresh = typed_buf, typed_fresh
                sug_i, sug_frozen = -1, False
                return
            else:
                sug_i = (sug_i + step) % len(sug)
            name_buf = str(sug[sug_i].get("name", ""))[:player.NAME_MAX]
            name_fresh = False
            # the field is no longer what anybody typed, so it must not become the
            # next question either — one TAB would otherwise narrow the list to
            # the name it just put there
            sug_frozen = True

        gun = settings.gun
        # The sights are not the camera: they sit above and behind it, the
        # barrel is not exactly parallel to the lens, and the beacon rectangle
        # in settings.toml is a tape measure's opinion. What that adds up to is
        # measured by the calibrator (F1) and kept in calibration.json — see
        # core/calibration.py. Applied after the beacon rectangle is taken out
        # before the crosshair is drawn, so a duck falls where the front
        # sight was.
        calib = [calib_core.load()]
        use_calib = [calib[0].active]
        if calib[0].active:
            print(f"calibration.json — {calib[0].describe()}")
            warn = calib[0].mismatch((W, H), (sw, sh), gun)
            if warn:
                print(f"calibration.json: {warn}")
        else:
            print("no sight calibration yet — F1 on the title screen sights the "
                  "gun in on five targets")

        def run_calibrator():
            """F1: five targets, shot down the sights, in place of the game."""
            mouse_down = [False]

            def poll_raw():
                """One frame of RAW aim for the calibrator: no correction and
                unclamped — the numbers it is there to measure."""
                if source is None:
                    mx, my = pygame.mouse.get_pos()
                    md = pygame.mouse.get_pressed()[0]
                    fired = md and not mouse_down[0]
                    mouse_down[0] = md
                    return ((mx - offset[0]) / W, (my - offset[1]) / H,
                            time.monotonic(), fired, 0, False)
                st = source.poll()
                ux, uy = aim_to_picture(gun, st.x, st.y, geom, clamp=False)
                stats = getattr(source, "stats", None)
                # the time the REPORT arrived, not now: a stale one is the last
                # thing the gun said, not where it is pointing, and the
                # calibrator refuses to record it
                t = stats.last_aim() if stats is not None else time.monotonic()
                return ux, uy, t, st.fire, st.pressed, st.quit

            fresh_calib = Calibrator(pygame, screen, present, poll_raw, W, H,
                                     settings.gun.spread, calib[0],
                                     display=(sw, sh), gun=gun).run()
            if fresh_calib is not None:
                calib[0] = fresh_calib
                use_calib[0] = fresh_calib.active
                print(f"calibration — {fresh_calib.describe()}")
            pygame.mouse.set_visible(False)
            clock.tick(FPS)       # swallow the time spent in there, or the first
                                  # frame back would advance the world by minutes
        show_gun = [False]                 # G: the gun's report rate and dropouts
        # Whether the crosshair starts up is [gun] crosshair, because it decides
        # whether the round can be a record at all. "auto" asks what is in the
        # player's hands: a light gun has sights of its own to aim down, a mouse
        # has none and would be unplayable blind. `source` rather than
        # `source_name` — the source is what the loop actually reads the aim
        # from, and it is the mouse path exactly when there is none. A on the
        # remote (or C) flips it from here either way.
        hide_cross = [gun.crosshair == "off"
                      or (gun.crosshair == "auto" and source is not None)]
        # the dog's pop-up reaction: kind in (None,'catch','laugh'), phase 0..1
        pop_kind = None
        pop_t = 0.0
        last_landed = 0
        last_escaped = 0
        crosshair = [0.5, 0.5]
        marks = []                 # where the shots went: {x, y, t, hit}
        prev_mouse_down = False

        def next_mode(step=1):
            """The next round in the list — the title screen's own control.

            Only from the title screen, and that is not a technical limit: the
            mode IS the round, so changing it builds the world the next round
            will be played in, and doing that anywhere else would either throw
            away a round in progress or rub out the result still being read.

            What follows the mode is re-derived right here, and it is a short
            list precisely because a mode may only change the round (see
            core/modes.py): the world, the ducks' size, the HUD measured against
            its own widest line, and whether the crosshair starts up. The
            window, the background, the sounds, the beacon rectangle and the
            sight-in belong to the room rather than to the round, and none of
            them move.
            """
            nonlocal settings, gun, art, dog_walk, dog_catch, dog_laugh, hud_font
            if len(self.modes) < 2:
                return
            self.mode_index = (self.mode_index + step) % len(self.modes)
            mode_now = self.modes[self.mode_index]
            settings = mode_now.settings
            # A fresh world, so the title screen shows the round that is about to
            # be played — its duck count, and a clean crosshair latch.
            self.world = World(settings=settings)
            gun = settings.gun
            hide_cross[0] = (gun.crosshair == "off"
                             or (gun.crosshair == "auto" and source is not None))
            art = _load_sheet(pygame, assets_dir,
                              int(settings.duck.width * W), dog_px_w,
                              settings.dog.catch_scale) \
                or _load_fallback(pygame, assets_dir, dog_px_w,
                                  settings.dog.catch_scale)
            dog_walk = art["dog_walk"]
            dog_catch = art["dog_catch"]
            dog_laugh = art["dog_laugh"]
            hud_font = _fit_font(pygame, [(hud_text(
                -99 * settings.round.ducks, settings.round.ducks,
                settings.round.ducks, settings.round.ammo or -1,
                999.0, 100.0), "")], W - 32)
            print(f"{mode_now.name}: {settings.summary()}")

        if self.calibrate:
            run_calibrator()

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
                        send_name()
                    elif e.key == pygame.K_BACKSPACE:
                        name_buf, name_fresh = name_buf[:-1], False
                        sug_i, sug_frozen = -1, False
                    elif e.key == pygame.K_ESCAPE:
                        # changed their mind — the round is not recorded anywhere
                        mode, t_mode = "over", 0.0
                    elif e.key in (pygame.K_TAB, pygame.K_DOWN):
                        take_suggestion(1)
                    elif e.key == pygame.K_UP:
                        take_suggestion(-1)
                    elif (e.unicode and e.unicode.isprintable()
                          and (e.unicode != " " or name_buf)):
                        # A space counts once there is something to separate —
                        # names have surnames. Leading spaces do not, and neither
                        # does anything unprintable that a key may deliver.
                        # Typing also hands the list back to the field: what is on
                        # offer follows what is typed, never the other way round.
                        sug_i, sug_frozen = -1, False
                        if name_fresh:
                            name_buf, name_fresh = "", False
                            if e.unicode == " ":
                                continue      # the space that cleared the old name
                        if len(name_buf) < player.NAME_MAX:
                            name_buf += e.unicode
                elif e.key == pygame.K_ESCAPE and mode in ("ready", "play"):
                    # Stop the round where it is and go to the result, with what
                    # has been shot so far still counted and, if the round was
                    # for the board at all, still signed for it — a hundred ducks
                    # is a long way to be stuck when the arm gets tired, and
                    # quitting the game outright would throw the score away.
                    self.world.stop()
                    end_round()
                elif e.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif e.key == pygame.K_c:
                    hide_cross[0] = not hide_cross[0]
                elif e.key == pygame.K_g:
                    show_gun[0] = not show_gun[0]
                elif e.key == pygame.K_F1 and mode in ("intro", "over"):
                    # From the title screen or the result screen only: sighting in
                    # is a thing you do between rounds, and stepping out of a
                    # live round would leave ducks hanging in the air.
                    run_calibrator()
                elif e.key == pygame.K_F2:
                    if not calib[0].active:
                        print("no sight calibration to turn on — F1 shoots one")
                    else:
                        use_calib[0] = not use_calib[0]
                        show_gun[0] = True
                        print(f"sight calibration "
                              f"{'ON' if use_calib[0] else 'off'} "
                              f"({calib[0].describe()})")
                elif e.key == pygame.K_b and backgrounds:
                    bg_index = (bg_index + 1) % len(backgrounds)
                    bg, GRASS_Y = use_background(bg_index)
                elif e.key == pygame.K_m and mode == "intro":
                    next_mode()
                elif e.key == pygame.K_SPACE and mode == "intro":
                    mode, t_mode = "ready", 0.0
                elif e.key == pygame.K_SPACE and mode == "over":
                    self.world = World(settings=settings)   # a new round
                    mode, t_mode, dog_x = "intro", 0.0, DOG_START_X
                    name_buf, name_fresh = self.player_name, True
                    last_landed = last_escaped = 0
                    pop_kind = None

            if source is not None:
                st = source.poll()
                if st.quit:
                    running = False
                ax, ay = aim_to_picture(gun, st.x, st.y, geom, clamp=False)
                if use_calib[0]:
                    ax, ay = calib[0].apply(ax, ay)
                crosshair[0] = min(1.0, max(0.0, ax))
                crosshair[1] = min(1.0, max(0.0, ay))
                fire = st.fire
                if st.pressed & 0x02:              # A on the remote
                    if mode == "intro" and len(self.modes) > 1:
                        # The title screen is where the round is chosen, and the
                        # player choosing it is three metres away with both
                        # hands on the gun — so A is the mode here and the
                        # crosshair everywhere else. There is no round yet to
                        # peek in, and C still flips the crosshair from the
                        # keyboard for anyone who wants to see it on this screen.
                        next_mode()
                    elif mode == "name":
                        # there is no crosshair to toggle on this screen, and
                        # there is one thing the gun cannot otherwise do: ENTER.
                        # The pull that may have come in the same frame is
                        # swallowed with it, or it would dismiss the result screen
                        # this one just brought up.
                        send_name()
                        fire = False
                    else:
                        hide_cross[0] = not hide_cross[0]
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
            elif fire and mode == "name" and sug:
                # The trigger does what TAB does here. It is the whole reason the
                # list is worth anything: the player is three metres away with a
                # gun in both hands, and walking to the keyboard to type a name
                # that is already on the board is exactly how the fourth spelling
                # of it gets there.
                take_suggestion(1)
            elif fire and mode == "over":
                # back to the title screen, not straight into the countdown: the
                # pull that dismisses the result screen is the one you make while
                # still looking at it, and it must not also be the pull that
                # starts the next round
                self.world = World(settings=settings)
                mode, t_mode, dog_x, fire = "intro", 0.0, DOG_START_X, False
                name_buf, name_fresh = self.player_name, True
                last_landed = last_escaped = 0
                pop_kind = None

            # ---- intro: the dog walks and sniffs ----
            if mode == "intro":
                # The crosshair is free on this screen and on the countdown: the
                # round is judged from the first duck, by `World.update`, and
                # nothing before it counts. These two screens used to latch it as
                # well — peeking there is how you learn where the front sight
                # sits against where the shot lands — but it made the one honest
                # move look like the cheat: turn the crosshair on to check the
                # gun is tracking, turn it off before the round, and the round
                # you then shot down the sights was refused anyway.
                draw_background()
                dog_x += settings.dog.speed * W * dt
                # the title screen waits for the trigger however long that takes,
                # so the dog walks the field on a loop instead of once
                if dog_x > W:
                    dog_x = DOG_START_X
                draw_dog_walking(dog_x, t_mode)
                mode_now = self.modes[self.mode_index]
                # The title screen is laid out measured rather than at fixed
                # gaps. Its two headlines are set in a fixed point size and the
                # picture is not, so on a small window the block below them ran
                # out through the bottom edge and took the last rows of the
                # keymap with it. What gives way, in order: the mode's one-line
                # note (the only line here that repeats what the name already
                # says), and then the gaps between the blocks.
                note_on = len(self.modes) > 1 and bool(mode_now.note)
                lines = (2 * big.get_height() + font.get_height() + 2
                         + len(keymap) * (km_font.get_height() + 2))
                gaps = [H * 0.08, H * 0.02, H * 0.02, H * 0.03]
                room = H - lines - int(H * 0.02)      # a little air at the foot
                if note_on and room - note_font.get_height() < sum(gaps) / 2:
                    note_on = False                   # too tight for both
                if note_on:
                    room -= note_font.get_height()
                gap = [int(v * min(1.0, max(0.0, room / sum(gaps)))) for v in gaps]

                y = gap[0]
                draw_center("DUCK HUNT", big, y)
                y += big.get_height() + gap[1]
                # blink it, so it reads as "waiting for you" rather than "stuck"
                if int(t_mode * 2) % 2:
                    draw_center("PULL THE TRIGGER TO START", big, y, (255, 225, 90))
                y += big.get_height() + gap[2]
                # Which round is about to be played, on the line that already
                # says how long it is: the mode is not a setting hidden in a
                # file any more, it is the thing the next trigger pull picks.
                head = (f"{mode_now.name}  ·  " if len(self.modes) > 1 else "")
                draw_center(f"{head}{self.world.total} DUCKS  ·  "
                            f"{settings.round.countdown:g}s COUNTDOWN", font, y,
                            (255, 255, 240))
                y += font.get_height() + 2
                if note_on:
                    # what the mode's own file says it is, in its own words —
                    # warm off-white rather than grey, because this line has no
                    # panel behind it and grey on a bright sky is not something
                    # you read from three metres away
                    draw_center(mode_now.note.upper(), note_font, y,
                                (252, 238, 195))
                    y += note_font.get_height()
                y += gap[3]
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

            # ---- round results and the name the row goes under ----
            if mode in ("name", "over"):
                if mode == "name":
                    if not sug_frozen:
                        # the offered names follow the field, except while they
                        # are being cycled: TAB putting one of them in the field
                        # is not a new question about who is on the board
                        look.ask(name_buf)
                        sug = look.rows()
                    if sug_i > len(sug) - 1:      # the list shrank under it
                        sug_i = len(sug) - 1
                # Why the round is not on its way, or else how it is getting
                # there — one line, never both: a round that was never for the
                # board has no delivery to report, and "SENT" under "PRACTICE"
                # would be two answers to one question.
                draw_background()
                draw_results(mode, name_buf, self.world.stopped,
                             refusal(self.world, settings) or board.line(),
                             sug, sug_i)
                present()
                continue

            # ---- gameplay ----
            # Every shot leaves a mark where it went. With the crosshair hidden
            # (A on the remote) this is the only thing that says where the barrel
            # actually pointed, and even with it visible it is the feedback a
            # light gun owes you: the ring is the hit zone the shot had, the hole
            # stays behind for a moment. Hit or miss is taken from the score,
            # which is what decided it.
            hits_before, shots_before = self.world.hits, self.world.shots
            # The dog's box is read HERE, before his phase is advanced a few
            # lines down — which is precisely the box that was drawn last frame,
            # because the blit at the bottom of the loop uses the phase after
            # that advance. So the shot is resolved against the dog the player
            # was looking at when they pulled, rather than against one who has
            # already moved on this frame's arc.
            self.world.update(dt, crosshair[0], crosshair[1], fire,
                              dog_box=dog_pop_box(pop_kind, pop_t),
                              crosshair=not hide_cross[0])
            if self.world.shots > shots_before:
                # Not simply `if fire`: a pull on an empty magazine is not a
                # shot, the core does not count it, and it must not leave a mark
                # on the sky or a bang in the speakers to say otherwise.
                hit = self.world.hits > hits_before
                marks.append({"x": crosshair[0], "y": crosshair[1], "t": 0.0,
                              "hit": hit})
                del marks[:-MARKS_MAX]
                # ... and the same thing in sound: the bang on every pull, the
                # quack on top of it when a duck takes it. The bang is the
                # feedback that the trigger was read at all — with a light gun
                # three metres from the screen that is worth hearing even on a
                # hit ([sound] shot_on_hit turns it off there).
                sfx.fired(hit)
            if self.world.finished:
                end_round()

            # the dog's reactions to core events
            if pop_kind is None:
                if self.world.landed > last_landed:
                    pop_kind, pop_t = "catch", 0.0
                elif self.world.escaped > last_escaped:
                    pop_kind, pop_t = "laugh", 0.0
                    # the laugh goes with the dog coming up out of the grass, not
                    # with the shot that missed: a duck is only really missed once
                    # it leaves the picture, and that is the moment the dog reacts
                    sfx.laugh()
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

            # the dog (pops up out of the grass), at the same place the box
            # handed to the core says he is
            placed = dog_pop_sprite(pop_kind, pop_t)
            if placed is not None:
                spr, left, top = placed
                screen.blit(spr, (left, top))

            for m in marks:
                m["t"] += dt
            while marks and marks[0]["t"] > MARK_LIFE:
                marks.pop(0)
            draw_marks()
            draw_belt()
            draw_crosshair()

            # HUD: the score, hits, how much of the flock is out, what is left in
            # the magazine, round time
            w = self.world
            hud = hud_font.render(
                hud_text(w.score, w.hits, w.released, w.ammo, w.elapsed,
                         w.accuracy),
                True, (255, 255, 255))
            screen.blit(hud, (HUD_X, 12))

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
                    parts.append(f"calib {'ON' if use_calib[0] else 'off'}")
                    text = " · ".join(parts)
                img = font.render(text, True, (255, 240, 140))
                screen.blit(img, (HUD_X, 12 + hud.get_height() + 6))

            present()

        board.close()
        look.close()
        pygame.quit()
