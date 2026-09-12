# 🦆 What is left to do

Written after the first evenings of live shooting with the Wii Remote bridge. The
gun works: the four-corner homography is solving, the axes are settled, the
beacons hold. What is below is what came out of those runs, most useful first.

## 1. Measure how accurate the aim actually is

Everything else in this list assumes we know. We still do not: not one tagged
sample has ever landed on a frame with four dots, so the summary has never been
able to print the one number that matters — where the crosshair goes when you
aim at a known point.

**The run:** beacons on the corners of the game's picture and
`[gun] frame = "picture"`, which is also what makes this measurement mean
something simple — the tagged corner is then the corner of the playfield itself,
expected at exactly 0 or 1, with no letterbox arithmetic in between. Stand where
`--plan` says (about **2 m** for a 27"; the beacon rectangle should read ~35% of
the frame in the summary, 50% is where corners start sliding out of view). Wait
until `dots 4/4` holds while you sweep. Then aim at each corner of the picture in
turn and **hold** its key for three seconds — `1` top-left, `2` top-right, `3`
bottom-right, `4` bottom-left, `5` the centre.

```bash
.venv/bin/python tools/ir_view.py --plan --diagonal 27   # where to stand
.venv/bin/python tools/ir_view.py
.venv/bin/python tools/ir_view.py --summary logs/ir_view_<time>.jsonl
```

Before the gun comes out at all, `tools/fake_gun.py` proves the Mac side: it
sends the bridge's own stream over UDP, so a crosshair that misses the picture's
corner there is a `settings.toml` problem, not a hardware one.

The summary then prints, per corner, what the firmware reported against what it
should have been. Two things to read out of it: the offset (a constant one means
the beacon rectangle does not match what `[gun]` says it is — fix it there)
and the spread (that is the real precision, and the sensor's own contribution is
only 0.1-0.2% of the screen, so anything larger is the hardware or the hand).

## 2. A hit zone, not a pinpoint crosshair — done

A shot used to be a single point, which was harsher than the NES ever was and
the wrong feel for a light gun — a shotgun scatters. Now `[gun] spread` is the
shot's radius in fractions of the playfield width (0.04 by default):
`Duck.distance_to()` in `core/models.py` gives the point-to-hitbox distance,
`World.update` drops the **nearest** flying duck within the radius, and the pixel
frontend draws the crosshair circle at exactly that radius — so the circle on
screen is the hit zone. Being in `core`, the terminal frontend gets it too.

What is left of the idea, if it ever wants more:

- A brief flash of the zone on the trigger would sell it further.
- Scaling the radius with the duck's distance, or shrinking it as the round goes
  on, is the classic way to add difficulty.

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

Solved on paper, unmeasured in the room. Two knobs now do it, both on the Mac
side (`settings.toml`), neither needing a flash:

```toml
[scene]
scale = 6          # display px per px of the art; 0 = as big as fits
[gun]
frame = "picture"  # the beacons are on the picture's corners, not the screen's
```

Both knobs assume the beacons can go **on the picture**, i.e. on the glass. On
the bezel (`frame = "display"` + `tools/ir_view.py --bezel`) the rectangle is the
whole screen and the distance is the screen's own width x 4.8 — 5.8 m on a 55",
which no room has. So the TV is the one place where the LEDs have to come off the
bezel and onto the screen itself, or onto a bar standing in front of it.

`frame = "picture"` is the right wiring on any screen: the beacons go on the
corners of the letterboxed picture (printed at startup), the firmware's numbers
are then playfield coordinates already, and the same settings play on the 27" and
on the 55". `scale` is the distance knob — the picture, and the beacon rectangle
with it, shrink together:

| 55" 4K | picture | distance |
|---|---|---|
| beacons on the screen's corners | 122 cm | 5.8 m |
| `scale = 0` (11x, all that fits) | 89 cm | 4.3 m |
| `scale = 6` | 49 cm | 2.3 m |
| `scale = 4` | 32 cm | 1.6 m |

Shrinking the beacon rectangle *alone* does not work, which the old version of
this section got wrong: the firmware clamps the aim to its own rectangle
(`constrain(u*1000, 0, 1000)`), so aiming past a beacon sticks there and the
picture's outer band is unreachable. The picture has to come down with it.

What is left to check with the gun in hand:

- Whether ~12° of view is enough picture to enjoy. That angle is fixed by the
  camera's field of view, so a 55" at 2.3 m looks exactly as big as a 27" at
  2.0 m — the TV is worth it only if the room can give the distance back.
- Whether a beacon rectangle as small as 32-49 cm holds four dots as reliably as
  the 42 cm one on the 27" does (it should — same fraction of the frame), and how
  much of the tolerance a centimetre of misplaced LED eats at that size.
- The picture moves when the display's resolution changes, so the beacons have to
  be re-stuck; `ir_view.py` logs the geometry in its meta line, and the game
  prints it at startup, so a mismatch is visible.

A wider lens is still the only thing that makes the picture *bigger* rather than
nearer — the `firmware/esp32_lightgun` path with a bare PixArt module and an M12
lens. The Wii Remote's camera cannot be opened up.

## 5. Latency, now that there is something to measure

The `G` key puts the stream's own numbers on the HUD: report rate, how clumped
the reports are (p90 and worst interval), how often the beacons are out of view,
how old the aim is. The run of 12 Sep read 67 reports/s median, p90 gap 34 ms,
worst 1336 ms (a link drop), four dots in 61% of frames and 28% of reports with
no dots at all — so what felt like lag was mostly the beacons dropping out, not
the transport. Budget when the dots hold: ~15 ms of remote + bridge, up to 16 ms
of frame, plus whatever the display adds; nothing in the pixel frontend smooths
the aim, so there is no hidden filter to blame.

Worth doing when the dropouts are fixed and the number still annoys:

- **Raise the serial baud.** 115200 is ~1 ms per aim line; 921600 makes it 0.13.
  Both sides change (`Serial.begin` in the firmware, `--baud` in the game).
- **Keep the dot dump off while playing** (`o` in the bridge, or just do not leave
  `ir_view` in `d` mode): at 60-70 reports/s a 60-byte dump line per report is
  half the port's bandwidth, and the aim queues behind it.
- **Measure the display's own contribution** before blaming the gun — HDMI, not
  AirPlay, and no scaling.

## 6. Smaller things

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
