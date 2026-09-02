# Pixel art (assets)

The NES sprites and backgrounds the pygame frontend draws — the game's main look.
Cut out of the original sheets in `source/` by the scripts in `tools/`; nothing
here is needed by the ASCII frontend.

## Where they came from

`source/duckhunt_sheet.webp` — the Duck Hunt sprite sheet (NES, 1984). Slicing:

```bash
pip install pillow
python3 tools/slice_spritesheet.py          # the default sheet is in assets/source/
```

The script strips the blue background (including the dark and pale cyan "tiles"
left by webp recompression), snaps colours to the NES palette — otherwise a dirty
fringe is left along the edges — and lays the frames out in `sprites/`.

## What you get

`sprites/` — the set the pygame frontend uses:

| Frames | What |
|-------|-----|
| `duck_{black,red}_fly_{1..3}`   | level flight (the duck faces RIGHT; the game mirrors it for leftwards) |
| `duck_{black,red}_climb_{1..3}` | climbing diagonally |
| `duck_{black,red}_up_{1..3}`    | flying towards the viewer; `up_3` (wings up) doubles as the downed duck |
| `dog_walk_{1..5}`               | the dog walking and sniffing |
| `dog_jump_{1..3}`               | jumping into the grass |
| `dog_laugh_{1..2}`              | laughing at a miss |
| `dog_catch`                     | popping up with the catch (the right edge is cut off on the sheet — rebuilt by mirroring) |

There is no blue duck: on this sheet its dark blue body is indistinguishable from
the dark background tiles, so it cannot be cut out cleanly.

## Backgrounds

`source/backgrounds.png` — the Duck Hunt background sheet (a 3×2 grid of NES
screens). Slicing:

```bash
python3 tools/slice_backgrounds.py
```

The script takes only the scene from each screen (the top 183 rows) — the game
does not use the SHOT/HIT/SCORE panel or the strip of font, it draws the score
itself. That gives four backgrounds in `backgrounds/`: `meadow`, `sunset`,
`mountains`, `clouds` (two of the screens on the sheet are the same scenes with a
two-player panel, and are skipped).

Next to them sits `backgrounds/index.toml` — that is how the game learns at what
height the grass starts in a background (the line the dog pops up along). Your own
background is added with a file in the folder and a line in the index:

```toml
[my_swamp]
file = "my_swamp.png"
grass = 0.8
```

Which background to start with is set in `settings.toml`, section `[scene]`; in
game they cycle with the **B** key. The scene is scaled up by a whole number of
times, so the pixels stay square (see the root [`README.md`](../README.md)).

## Fallback path

If `sprites/` is missing, the frontend picks up the individual PNGs in this folder
under fixed names (`duck_a`, `duck_b`, `duck_hit`, `dog_walk_a`, `dog_walk_b`,
`dog_catch`, `dog_laugh` — the slicer writes those too), and if those are missing
as well it draws the built-in pixel art from `pygame_app.py`. Format: PNG, RGBA,
small. The game scales them up by whole numbers so that the pixels stay square.
