"""Slice the Duck Hunt (NES) background sheet into separate PNGs for the game.

The sheet is a 3x2 grid of 256x256 screens: each holds a scene (sky + grass), the
SHOT/HIT/SCORE panel and a strip of font at the bottom. The game only needs the
scene — it draws the panel itself — so we take the top 183 rows of each screen.
Two of the six screens are the same scenes with a two-player panel; we skip those.

    python3 tools/slice_backgrounds.py [sheet.png]   # assets/source/ by default

Result: assets/backgrounds/*.png plus index.toml, which tells the game at what
height the grass starts in each background (that is where the dog pops up).
"""

from __future__ import annotations

import os
import sys

from PIL import Image

CELL = 256          # one NES screen on the sheet
PLAYFIELD_H = 183   # below this the score panel starts — the game does not need it

# name: (screen x, y on the sheet, row where the grass starts, caption)
SCENES = {
    "meadow": (0, 0, 146, "a tree and a bush, blue sky"),
    "sunset": (CELL, 0, 146, "the same against a pink sunset sky"),
    "mountains": (2 * CELL, 0, 150, "mountains and a fir wood"),
    "clouds": (2 * CELL, CELL, 147, "clouds above tall grass"),
}


def main() -> None:
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        root, "source", "backgrounds.png")
    sheet = Image.open(src).convert("RGB")

    out_dir = os.path.join(root, "backgrounds")
    os.makedirs(out_dir, exist_ok=True)

    index = ["# Backgrounds sliced out of assets/source/backgrounds.png by",
             "# tools/slice_backgrounds.py. Pick one in settings.toml, [scene].",
             "#",
             "# grass — the fraction of the height where the grass starts: the dog",
             "# pops up along that line. Your own background can just be appended here.",
             ""]
    for name, (x, y, grass_row, note) in SCENES.items():
        img = sheet.crop((x, y, x + CELL, y + PLAYFIELD_H))
        img.info.pop("icc_profile", None)   # a broken profile in the source -> pygame warning
        img.save(os.path.join(out_dir, name + ".png"))
        index += [f"[{name}]",
                  f'file = "{name}.png"',
                  f"grass = {grass_row / PLAYFIELD_H:.3f}   # {note}",
                  ""]
        print(f"{name:12} {img.size[0]}x{img.size[1]}  grass from {grass_row}")

    with open(os.path.join(out_dir, "index.toml"), "w") as f:
        f.write("\n".join(index))
    print(f"\n{len(SCENES)} backgrounds -> assets/backgrounds/ (+ index.toml)")


if __name__ == "__main__":
    main()
