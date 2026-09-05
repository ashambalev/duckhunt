# 🦆 What is left to do

Written after the first evenings of live shooting with the Wii Remote bridge. The
gun works: the four-corner homography is solving, the axes are settled, the
beacons hold. What is below is what came out of those runs, most useful first.

## 1. Measure how accurate the aim actually is

Everything else in this list assumes we know. We still do not: not one tagged
sample has ever landed on a frame with four dots, so the summary has never been
able to print the one number that matters — where the crosshair goes when you
aim at a known point.

**The run:** on a 27" monitor stand about **3 m** back (the beacon rectangle
should read ~35% of the frame in the summary; 50% is the point where corners
start sliding out of view). Wait until `dots 4/4` holds while you sweep. Then aim
at each corner of the screen in turn and **hold** its key for three seconds — `1`
top-left, `2` top-right, `3` bottom-right, `4` bottom-left, `5` the centre.

```bash
.venv/bin/python tools/ir_view.py
.venv/bin/python tools/ir_view.py --summary logs/ir_view_<time>.jsonl
```

The summary then prints, per corner, what the firmware reported against what it
should have been. Two things to read out of it: the offset (a constant one means
the beacon rectangle does not match the screen — fix it with `BEACON_CX/CY/W/H`)
and the spread (that is the real precision, and the sensor's own contribution is
only 0.1-0.2% of the screen, so anything larger is the hardware or the hand).

## 2. A hit zone, not a pinpoint crosshair

Right now a shot is a single point: `Duck.contains(aim_x, aim_y)` in
`core/models.py` asks whether the aim point is inside the duck's rectangle, and
the frontend draws a 14 px circle that has nothing to do with it. That is harsher
than the NES ever was, and it is the wrong feel for a light gun — a shotgun
scatters.

- Give the shot a **radius**, in fractions of the screen, from `settings.toml`
  (`[gun] spread = 0.04`, say) — a hit when the duck's rectangle comes within
  that radius of the aim point, not only when it swallows it.
- **Draw what it means.** The crosshair circle should *be* the hit zone, at the
  same size, so the player can see what they are aiming with. A brief flash of
  the zone on the trigger would sell it further.
- Keep it in `core` so both frontends and the tests get it for free; the terminal
  frontend has the same problem at a much coarser resolution.
- Worth a thought while doing it: scaling the radius with the duck's distance, or
  shrinking it as the round goes on, is the classic way to add difficulty.

## 3. Brightness, if dots still drop out

The four beacons now read blob sizes 1-2 out of 15 with the camera at its most
sensitive setting. It works, but there is no margin: a beacon at size 0 is a
beacon that vanishes.

- 100 Ω at 3 V is about 17 mA. **47 Ω gives ~35 mA** — twice the current, a third
  of what the LED is rated for, and still ~27 h per set of cells. Expect 60-70%
  more light rather than double: efficiency droops as the current climbs. Below
  33 Ω the runtime halves and the light does not follow.
- **Or add a third cell.** 3×AAA with 100–120 Ω draws the same current, lasts
  longer, and evens the corners out: at 3 V a 0.2 V spread in forward voltage puts
  two LEDs 11% apart in current, at 4.5 V only 6%. See `docs/BUILD.md` for the
  full table.
- Aim matters as much as current: they are directional, so point each one at
  where you actually stand and sand the dome flat.
- Watch it in the summary's per-beacon table — four similar numbers is what a
  good set looks like.

## 4. Playing on the TV

A 55" wants **5.9 m** with the beacons on its corners, which no living room has.
The way down is a smaller beacon rectangle, and the firmware already takes it:

| beacons on | 27" | 55" |
|---|---|---|
| the screen's corners | 2.9 m | 5.9 m |
| the picture's corners | 2.1 m | 4.5 m |
| a smaller rectangle | width × 4.8 | width × 4.8 |

Set `BEACON_CX/CY/W/H` in the firmware to the rectangle's centre and size as
fractions of the display, and the game's letterbox conversion keeps working
untouched. Two catches: the LEDs end up on the screen's glass rather than its
bezel, and the display resolution has to stay put, because the pixel-art scale is
an integer and the picture changes size with it. `tools/ir_view.py` records the
display and picture geometry in every log, so a mismatch is visible.

The real fix for a TV is a wider lens, which the Wii Remote's camera does not
have — that is the `firmware/esp32_lightgun` path with a bare PixArt module and
an M12 lens.

## 5. Smaller things

- **The remote drops the link** every minute or two under continuous IR
  reporting, re-pairing itself in under a second. Fresh AA cells first; the
  summary counts the drops.
- **Opening the serial port reboots the bridge** — the macOS CH340 driver drives
  the reset line whatever pyserial asks, so the SYNC-after-launch dance stays. A
  10 µF capacitor from EN to GND would end it.
- **The camera is at its most sensitive setting.** If a bright room starts
  inventing dots, the gentler register block is one commented line below it in
  the firmware.
- **Redo the one-beacon pass** some quiet evening. It is the only measurement
  whose answer came out wrong once (mislabelled top and bottom), and it would be
  nice to have it agree with the other three.
