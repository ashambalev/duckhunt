"""Slice the Duck Hunt (1984) sprite sheet into separate PNGs for the game.

The source is a webp sheet on a blue background (including darker and lighter blue
"tiles" left by recompression). The script strips the background, cleans up the
lossy-compression artefacts by snapping colours to the NES palette, and saves each
frame as its own PNG with transparency.

    python3 tools/slice_spritesheet.py [sheet.webp]   # assets/source/ by default

Result: assets/sprites/*.png (the full set) and assets/*.png (the 7 names the
pygame frontend picks up automatically).
"""

from __future__ import annotations

import os
import sys

from PIL import Image

# ---- the NES palette (blurred pixels are snapped to it) --------------------
BLACK = (0, 0, 0)          # outline, feathers
WHITE = (252, 252, 252)    # white feathers, the dog's muzzle
GREEN = (0, 88, 0)         # the mallard's green head
SALMON = (252, 116, 96)    # beak and feet
RED = (168, 0, 16)         # the red duck
ORANGE = (200, 76, 12)     # the dog's ginger coat
BROWN = (124, 12, 4)       # the dark hatching on the dog

# Each frame set gets its own palette: if every colour is allowed at once, the
# blurred pixels along the dog's edges snap to green and leave a fringe.
PAL_DOG = [BLACK, WHITE, SALMON, ORANGE, BROWN]
PAL_DUCK_BLACK = [BLACK, WHITE, GREEN, SALMON]
PAL_DUCK_RED = [BLACK, WHITE, SALMON, RED]
PAL_ALL = [BLACK, WHITE, GREEN, SALMON, RED, ORANGE, BROWN]


def is_bg(r: int, g: int, b: int) -> bool:
    """The sheet background: light blue, pale cyan and dark blue "tiles"."""
    if g >= 170 and b >= 170 and r <= 200 and g - r >= 40:
        return True                       # a pale cyan tile
    return b - max(r, g) >= 30 and b >= 110   # blue / dark blue background


def snap(px, palette):
    return min(palette, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, px)))


def cut(sheet: Image.Image, box, palette, mirror_at: int | None = None) -> Image.Image:
    """A frame from the sheet -> an RGBA sprite: transparent background, palette colours.

    `mirror_at` is the X (in sheet coordinates) of the axis of symmetry: the right
    half is built by mirroring the left one (the "dog with ducks" frame is cut off
    by the edge of the sheet).
    """
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, sheet.width), min(y1, sheet.height)
    src = sheet.load()
    w, h = x1 - x0, y1 - y0
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dst = out.load()
    for y in range(y0, y1):
        for x in range(x0, x1):
            sx = x
            if mirror_at is not None and x > mirror_at:
                sx = 2 * mirror_at - x          # take the reflection from the left
            if not 0 <= sx < sheet.width:
                continue
            p = src[sx, y]
            if not is_bg(*p):
                dst[x - x0, y - y0] = snap(p, palette) + (255,)
    return despeckle(trim(out))


def trim(img: Image.Image) -> Image.Image:
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def despeckle(img: Image.Image, min_size: int = 3) -> Image.Image:
    """Remove the stray speckle pixels left behind by lossy compression."""
    w, h = img.size
    px = img.load()
    seen = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if seen[y][x] or px[x, y][3] == 0:
                continue
            stack, pts = [(x, y)], []
            seen[y][x] = True
            while stack:
                cx, cy = stack.pop()
                pts.append((cx, cy))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] \
                                and px[nx, ny][3]:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            if len(pts) < min_size:
                for p in pts:
                    px[p[0], p[1]] = (0, 0, 0, 0)
    return trim(img)


# ---- what sits where on the sheet (coordinates in source pixels) -----------
# The dog: 5 walking/sniffing frames (the black "ground" strip at the bottom is cut
# off), 3 frames of the jump into the grass, 2 laughing frames and the frame with
# the caught ducks. The black "ground" strip under the dog (y 40..44 and y 104..107)
# is not part of the sprite.
FRAMES: dict[str, tuple] = {
    "dog_walk_1": (4, 0, 60, 40),
    "dog_walk_2": (64, 0, 120, 40),
    "dog_walk_3": (124, 0, 180, 40),
    "dog_walk_4": (182, 0, 242, 40),
    "dog_walk_5": (242, 0, 300, 40),
    "dog_jump_1": (2, 56, 60, 104),
    "dog_jump_2": (72, 58, 112, 104),
    "dog_jump_3": (132, 63, 170, 104),
    "dog_laugh_1": (193, 60, 228, 104),
    "dog_laugh_2": (254, 59, 288, 104),
}
# Ducks: three poses (level flight, climbing, flying towards the viewer), three
# flap frames each. The blue duck is skipped: on this sheet its dark blue body is
# indistinguishable from the dark background tiles.
DUCKS = {
    "black": (128, 168, 208),   # starting X of the three frames
    "red": (258, 298, 339),
}
DUCK_ROWS = {"fly": (116, 149), "climb": (154, 189), "up": (195, 229)}

for color, xs in DUCKS.items():
    for row, (ry0, ry1) in DUCK_ROWS.items():
        for i, x in enumerate(xs, 1):
            FRAMES[f"duck_{color}_{row}_{i}"] = (x, ry0, x + 38, ry1)


def palette_for(name: str) -> list:
    if name.startswith("duck_black"):
        return PAL_DUCK_BLACK
    if name.startswith("duck_red"):
        return PAL_DUCK_RED
    return PAL_DOG

# The dog with its catch: the frame runs into the right edge of the sheet, so the
# right half is rebuilt by mirroring the left one (the pose is symmetrical).
CATCH = ((316, 59, 377, 104), 346)

# The 7 names the pygame frontend looks for in assets/ with no configuration.
LEGACY = {
    "duck_a": "duck_black_fly_1",
    "duck_b": "duck_black_fly_3",
    "duck_hit": "duck_black_up_3",
    "dog_walk_a": "dog_walk_1",
    "dog_walk_b": "dog_walk_3",
    "dog_catch": "dog_catch",
    "dog_laugh": "dog_laugh_1",
}


def main() -> None:
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        root, "source", "duckhunt_sheet.webp")
    sheet = Image.open(src).convert("RGB")
    out_dir = os.path.join(root, "sprites")
    os.makedirs(out_dir, exist_ok=True)

    made: dict[str, Image.Image] = {}
    for name, box in FRAMES.items():
        made[name] = cut(sheet, box, palette_for(name))
    # the dog is holding ducks — this frame needs both ginger and green at once
    made["dog_catch"] = cut(sheet, CATCH[0], PAL_ALL, mirror_at=CATCH[1])

    for name, img in made.items():
        img.save(os.path.join(out_dir, name + ".png"))
        print(f"{name:22} {img.size[0]:>3}x{img.size[1]:<3}")

    for legacy, src_name in LEGACY.items():
        made[src_name].save(os.path.join(root, legacy + ".png"))
    print(f"\n{len(made)} frames -> assets/sprites/, {len(LEGACY)} -> assets/")


if __name__ == "__main__":
    main()
