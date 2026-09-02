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

import os
import random
import sys
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

FPS = 60
SCALE = 5          # one sprite pixel = SCALE screen pixels
DOG_SCALE = 6


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
DOG_TARGET_W = 150                 # desired on-screen width of the dog, px


def _load_sheet(pygame, assets_dir, duck_w):
    """The frame set from assets/sprites/, or None if it is not there.

    Integer scaling only — anything else makes the pixel art smear.
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
    k_dog = max(1, round(DOG_TARGET_W / raw["dog_walk_1"].get_width()))

    def up(name, k):
        img = raw[name]
        return pygame.transform.scale(img, (img.get_width() * k, img.get_height() * k))

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
        "dog_catch": up("dog_catch", k_dog),
    }


def _load_fallback(pygame, assets_dir):
    """The old path: individual PNGs under fixed names, or the built-in art."""
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
    walk = [load("dog_walk_a", _build(DOG_SNIFF_A, PALETTE, DOG_SCALE)),
            load("dog_walk_b", _build(DOG_SNIFF_B, PALETTE, DOG_SCALE))]
    one = {
        "right": right,
        "left": [pygame.transform.flip(s, True, False) for s in right],
        "hit": load("duck_hit", _build(DUCK_HIT, PALETTE, SCALE)),
    }
    return {
        "ducks": {c: one for c in DUCK_COLORS},
        "dog_walk": [walk[0], walk[1], walk[0], walk[1]],
        "dog_laugh": load("dog_laugh", _build(DOG_LAUGH, PALETTE, DOG_SCALE)),
        "dog_catch": load("dog_catch", _build(DOG_CATCH, PALETTE, DOG_SCALE)),
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
    def __init__(self, settings=None):
        self.world = World(settings=settings)

    def run(self, source=None) -> None:
        import pygame

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
        info = pygame.display.Info()
        bw, bh = backgrounds[bg_index]["image"].get_size() if backgrounds else (300, 225)
        if self.world.settings.scene.fullscreen:
            display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            sw, sh = display.get_size()
            k = max(1, min(sw // bw, sh // bh))
            W, H = bw * k, bh * k
            offset = ((sw - W) // 2, (sh - H) // 2)
            screen = pygame.Surface((W, H))
        else:
            k = max(2, min(4, (info.current_h - 120) // bh))
            W, H = bw * k, bh * k
            display = pygame.display.set_mode((W, H))
            sw, sh = W, H
            offset = (0, 0)
            screen = display
        pygame.mouse.set_visible(False)      # the game draws its own crosshair
        pygame.display.set_caption("🦆 Duck Hunt")

        def present():
            """Show the frame: centred in fullscreen, as-is in a window."""
            if screen is not display:
                display.fill((0, 0, 0))
                display.blit(screen, offset)
            pygame.display.flip()
        clock = pygame.time.Clock()
        font = pygame.font.SysFont("Menlo,monospace", 22, bold=True)
        big = pygame.font.SysFont("Menlo,monospace", 40, bold=True)
        # pre-render the sprites: first look for frames sliced out of the sprite
        # sheet (assets/sprites/), otherwise individual PNGs or the built-in pixel
        # art. The sprite is scaled to the duck size from the settings.
        duck_px_w = int(self.world.settings.duck.width * W)
        art = _load_sheet(pygame, assets_dir, duck_px_w) \
            or _load_fallback(pygame, assets_dir)
        dog_walk = art["dog_walk"]
        dog_catch = art["dog_catch"]
        dog_laugh = art["dog_laugh"]

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

        def draw_results(mode, name_buf, table):
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
            y += font.get_height() + int(H * 0.045)

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

            footer = ("ENTER — SAVE   ·   ESC — SKIP" if mode == "name"
                      else "SPACE — PLAY AGAIN   ·   Q — QUIT")
            draw_center(footer, font,
                        py + panel.get_height() - font.get_height() - int(H * 0.03),
                        (200, 200, 200))

        # scene state: intro -> play -> name (name entry) -> over (score table)
        mode = "intro"
        t_mode = 0.0
        dog_x = -60.0
        name_buf = ""
        # the dog's pop-up reaction: kind in (None,'catch','laugh'), phase 0..1
        pop_kind = None
        pop_t = 0.0
        last_landed = 0
        last_escaped = 0
        crosshair = [0.5, 0.5]
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
                elif e.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif e.key == pygame.K_b and backgrounds:
                    bg_index = (bg_index + 1) % len(backgrounds)
                    bg, GRASS_Y = use_background(bg_index)
                elif e.key == pygame.K_SPACE and mode == "over":
                    self.world = World(settings=settings)   # a new round
                    mode, t_mode, dog_x, name_buf = "intro", 0.0, -60.0, ""
                    last_landed = last_escaped = 0
                    pop_kind = None

            if source is not None:
                st = source.poll()
                if st.quit:
                    running = False
                # The gun aims at the PHYSICAL screen (its beacons sit at the screen
                # corners), so st.x/st.y are fractions of the display — while the
                # scene is a letterboxed rectangle inside it. Convert display
                # fraction -> scene fraction, the same trick the mouse branch does
                # with pygame.mouse.get_pos(). Without this the crosshair lags
                # behind the barrel by up to half the black bar at the edges.
                # (Windowed play cannot be corrected — we do not know where the
                # window sits on screen — so play fullscreen when using the gun.)
                crosshair[0] = min(1.0, max(0.0, (st.x * sw - offset[0]) / W))
                crosshair[1] = min(1.0, max(0.0, (st.y * sh - offset[1]) / H))
                fire = st.fire
            else:
                mx, my = pygame.mouse.get_pos()
                crosshair[0] = min(1.0, max(0.0, (mx - offset[0]) / W))
                crosshair[1] = min(1.0, max(0.0, (my - offset[1]) / H))
                md = pygame.mouse.get_pressed()[0]
                fire = md and not prev_mouse_down
                prev_mouse_down = md

            # ---- intro: the dog walks and sniffs ----
            if mode == "intro":
                draw_background()
                dog_x += 120 * dt
                frame = dog_walk[int(t_mode * 8) % len(dog_walk)]
                # the paws sit inside the grass band, not on its top edge
                feet = GRASS_Y + int((H - GRASS_Y) * 0.8)
                screen.blit(frame, (dog_x, feet - frame.get_height()))
                msg = big.render("DUCK HUNT", True, (255, 255, 255))
                screen.blit(msg, (W // 2 - msg.get_width() // 2, 120))
                hint = (f"{self.world.total} DUCKS IN A MINUTE  ·  B BACKGROUND  ·  Q QUIT"
                        if backgrounds else
                        f"{self.world.total} DUCKS IN A MINUTE  ·  Q QUIT")
                sub = font.render(hint, True, (255, 255, 240))
                screen.blit(sub, (W // 2 - sub.get_width() // 2, 180))
                if t_mode > 3.2:
                    mode = "play"
                    t_mode = 0.0
                present()
                continue

            # ---- round results and the high-score table ----
            if mode in ("name", "over"):
                draw_background()
                draw_results(mode, name_buf, table)
                present()
                continue

            # ---- gameplay ----
            self.world.update(dt, crosshair[0], crosshair[1], fire)
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
                if pop_t > 1.4:
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
                # an arc: rises out of the grass and drops back down (0->1->0)
                up = 1.0 - abs(pop_t / 0.7 - 1.0)
                up = max(0.0, min(1.0, up))
                dy = int(spr.get_height() * up)
                screen.blit(spr, (W // 2 - spr.get_width() // 2, GRASS_Y - dy))

            # crosshair
            cx, cy = int(crosshair[0] * W), int(crosshair[1] * H)
            pygame.draw.circle(screen, (255, 255, 255), (cx, cy), 14, 2)
            pygame.draw.line(screen, (255, 60, 60), (cx - 18, cy), (cx + 18, cy), 2)
            pygame.draw.line(screen, (255, 60, 60), (cx, cy - 18), (cx, cy + 18), 2)

            # HUD: hits, how many of the flock have been released, round time
            w = self.world
            hud = font.render(
                f"HIT {w.hits}   DUCK {w.released}/{w.total}   "
                f"{w.elapsed:.0f}s   ACC {w.accuracy:.0f}%",
                True, (255, 255, 255))
            screen.blit(hud, (16, 12))

            present()

        pygame.quit()
