# 🦆 Duck Hunt — NES pixel art in pygame, played with a home-made light gun

A pixel-art "Duck Hunt" for macOS: the NES sprites and backgrounds rendered by a
**pygame** frontend, aimed with an **external light gun**. The gun is a Wii Remote
(its PixArt IR camera does the aiming) bridged to the Mac by an **ESP32-WROOM-32U**,
which pairs with the remote over Bluetooth Classic and streams the aim point over
USB-Serial.

Two things are deliberately kept apart: the *game* (pure logic + pixel rendering,
coordinates normalized to `0..1`) and the *gun* (any device that can send `x,y,b`).
Everything below is one or the other.

## How it works

```
GUN                                          MAC (pygame window)
  Wii Remote — PixArt IR camera ──┐
  4 IR dots + trigger (B button)  │  BT Classic
                                  ├──────────▶ ESP32-WROOM-32U
                                  │              │  USB-Serial, 115200
  4× 940 nm IR LEDs at the ───────┘              │  x,y,b
  screen corners (the "sensor bar")              ▼
                                        InputSource ─▶ World (30 FPS)
                                                     ─▶ pixel frontend:
                                                        ducks, dog, crosshair,
                                                        NES backgrounds, score
```

The gun does not emulate a mouse. It sends `x,y,b` — coordinates `0..1000` plus a
button mask — and the game draws its own crosshair. Simpler, and more precise.

**Why an ESP32 in the middle:** pairing a Wii Remote straight to Apple Silicon
macOS does not work. The ESP32-WROOM-32U (the *original* ESP32 — the S3/C3 have no
Bluetooth Classic) pairs with the remote itself and hands the Mac a plain serial
line, so the macOS Bluetooth stack is never involved. The remote stays intact.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 main.py --pygame                                     # aim with the mouse (development)
python3 main.py --pygame --serial /dev/tty.usbserial-0001    # aim with the light gun
```

**Playing with the light gun**, start to finish:

```bash
ls /dev/tty.usbserial*                                       # find the bridge (usually -0001)
python3 main.py --pygame --serial /dev/tty.usbserial-0001    # play
#   Remote already paired? It just works — the game opens the port without
#   rebooting the bridge. Otherwise press the red SYNC button on the remote.
```

**If the remote will not connect**, it is almost always one of these:

- **SYNC pressed too early.** The board only hears it after it prints `# BT init...`;
  a press during boot goes nowhere and burns the remote's ~20 s pairing window.
- **No `--serial` on the command line.** Without it the game runs on the mouse and
  ignores the gun completely, which looks exactly like a dead remote.
- **Tired batteries.** The remote pairs happily and then drops the link a few seconds
  later under continuous IR reporting.

Watch what the bridge itself is saying with `tools/wiimote_monitor.py` — it prints the
firmware's `# ...` status lines, so you can see whether the remote is pairing at all
and whether the camera is picking up IR dots.

To *see* what the camera sees, run `tools/ir_view.py`: it draws the blobs in the
sensor's own 1024×768 space, the quad the firmware builds out of them, and where the
aim lands on screen — and it writes the whole run to `logs/ir_view_<time>.jsonl`.
While aiming at a known corner hold **1**–**4** (**5** for the centre): those tags
are what let the log answer, afterwards, whether the axis flags are the right way
round. The summary also reconstructs *which* beacon is missing when only three are
seen, and whether it fell outside the camera's frame (stand further back) or was
simply not seen (that LED is dim, misaimed or dead).

```bash
.venv/bin/python tools/ir_view.py                  # live view + log (quit with Q)
.venv/bin/python tools/ir_view.py --summary logs/ir_view_<time>.jsonl
```

The remote re-pairs by itself if the link drops mid-round: the game keeps running and
the crosshair freezes at its last position until the stream comes back.

In game: **mouse / gun** aims, **left button / trigger** fires, **B** cycles the
background, **Space** starts another round on the results screen, **Q** or **Esc**
quits.

### Bringing up the gun

1. Flash `firmware/esp32_wiimote_bridge/` onto an ESP32-WROOM-32U (Arduino, with
   `--libraries firmware/libs` so the patched `Wiimote` library is picked up).
2. Plug the ESP32 into the Mac over USB. **Start the game first, wait ~3 seconds,
   and only then press the red SYNC button** under the remote's battery cover:
   opening the serial port reboots the ESP32, and a SYNC pressed while it is still
   booting is simply not heard (it prints `# BT init...` when it is ready to listen).
   Pairing then takes well under a second. The board prints its progress as `# ...`
   lines on the same serial port — the game's parser ignores them.
3. Put the four IR LEDs at the corners of the screen (see
   [`docs/BUILD.md`](docs/BUILD.md)) and run the game with `--serial`.

The bridge turns the four beacons into an aim point with a **4-corner homography**:
the dots the camera reports *are* the screen rectangle seen down the barrel, so the
aim point is where the centre of the camera image falls inside it — which handles
distance, angle and gun tilt without any calibration step. It needs all four dots
at once, and the camera's view is narrow (~33°), so there is a minimum playing
distance — about 2 m for a 27" monitor, 4 m for a 55" TV, since aiming into one
corner pushes the opposite one out of frame ([`docs/BUILD.md`](docs/BUILD.md) has
the table). On fewer than four dots it drops back to the old centroid guess: the
crosshair keeps moving, but it is no longer screen-referenced.

### To check on the next run

Two changes are in the code but have never been exercised against the hardware —
the board was unplugged when they were written. Worth a look the next time the gun
comes out:

- [x] **Does the remote stay paired across game launches? No — measured, it does
      not.** `input/serial_gun.py` sets DTR/RTS false before opening, and the bridge
      still reboots on every open: the port comes up printing the ESP32's ROM log
      and `rst:0x1 (POWERON_RESET)`, twice out of two attempts. The macOS CH340
      driver drives the lines during `open()` whatever pyserial asks for, so the
      EN pin gets pulled anyway. **The SYNC-after-launch dance stays**: start the
      game (or a tool), wait for `# BT init...`, and only then press SYNC or A/1+2.
      A hardware fix if it becomes annoying: a 10 µF capacitor from EN to GND, or
      cut the auto-reset trace and flash with the BOOT button instead.
- [ ] **Do the beacons and the picture line up?** The LEDs go on the corners of
      the *physical screen*; the picture inside it is smaller, because the pixel
      art is scaled by a whole number and centred (1280×915 inside 1470×956 on
      this Mac — bars of 6.5% down the sides, 2.1% top and bottom), and the
      frontend converts display coordinates to picture coordinates itself. If the
      LEDs had to go on some other rectangle, describe it to the firmware with
      `BEACON_CX/CY/W/H` ([`docs/BUILD.md`](docs/BUILD.md)).

- [ ] **Does the crosshair reach the screen edges in fullscreen?** `pygame_app.py`
      now converts gun coordinates from display fractions to scene fractions, so the
      crosshair should track the barrel all the way into the corners instead of
      lagging by up to half a black bar. Only meaningful once the beacons give real
      screen-referenced aim — with one IR dot the aim is relative anyway.

- [x] **Do the four beacons map the right way round? Settled:**
      `CAM_MIRROR_X = false`, `CAM_MIRROR_Y = true` — the sensor's X runs with the
      screen's, its Y against it. The test that finally closed it has nothing to
      mislabel: cover the two top beacons by hand and watch the CAMERA panel in
      `tools/ir_view.py`. The dots that went dark were the ones *low* in the sensor
      frame, so a beacon at the top of the screen reports a large sensor y. A
      one-beacon-at-a-time pass said the same (left pair at sensor x≈386 against
      x≈930 for the right pair, top pair at y≈644 against y≈346).

      Two of the "it is inverted" reports along the way had nothing to do with the
      flags at all: they were read off the CAMERA panel, where the dots slide
      against the barrel by construction — the aim lives in the SCREEN panel
      below it. Both panels now say so on screen. The rest were one bug: the fallback
      aim followed the dot centroid, which slides the opposite way to the barrel,
      so it needs the opposite axis convention from the homography — and the two
      shared one pair of flags. Replaying the logs, a beacon dropping out moved
      the crosshair a median 0.45 of the screen and flipped it across the screen
      more than half the time (now 0.24, never past 0.4). Each flag flip then got
      judged against whichever build happened to be running, which is why the
      bridge now prints `# build ... | MIRROR_X=0 MIRROR_Y=1 | beacon ...` at boot,
      into every log.

- [ ] **Is the camera sensitive enough now?** Three beacon runs came back with
      every blob at size 0-2 out of 15, and dots dropping in and out constantly, so
      the IR sensitivity registers went from the gentle "inio" values to the Wii's
      own level 5 (thresholds `0x20`/`0x1F`). Untested. What to watch in the next
      `tools/ir_view.py` summary: the per-beacon blob sizes should climb, and if a
      bright room starts inventing dots that are not there, the gentler block is
      one commented line below in the firmware.

      First reading after the change: the weakest beacon went from a blob size of
      0.17 to 1.1, and no phantom dots appeared — better, but the whole set still
      reads 1-2 out of 15, which is dim. The next lever is current: 100 Ω at 3 V
      is about 17 mA, and 68 Ω (~25 mA) is still far inside a 5 mm IR LED's
      rating. The right-bottom beacon is the one to fix first — in the one-beacon
      pass it vanished in 263 of 331 frames while the other three held steady.

- [ ] **Does the link drop under load?** It does, and often: the first beacon run
      lost the remote twice in 132 s (at 15.6 s and 38.3 s), each time re-pairing
      by itself after 7–13 s. An earlier capture dropped it once at 16 s. Fresh AA
      cells in the remote are the thing to try before blaming the firmware —
      `tools/ir_view.py` counts the drops in its summary.

### Other input paths

| Command | Path |
|---|---|
| `python3 main.py --pygame` | mouse — no hardware, for development |
| `python3 main.py --pygame --serial PORT` | **the current gun**: Wiimote → ESP32-WROOM-32U → USB-Serial |
| `python3 main.py --pygame --udp` | the same bridge over Wi-Fi/UDP (port 4210) — the Mac side (`input/udp_gun.py`) is ready, the firmware sends serial today |
| `python3 main.py --pygame --wiimote` | remote straight over Bluetooth (`hidapi`) — does *not* work on recent macOS, kept for reference |
| `python3 main.py` | the ASCII/terminal frontend — the original prototype, same core, handy without a window |

The last one is a leftover from the first prototype rather than the goal; every
input source works with either frontend, since both sit on the same `World` and
the same `InputSource`.

## Roadmap

- [x] **Stage 0–1** — playable prototype, pure logic core, terminal frontend.
- [x] **Stage 2** — pygame pixel frontend: NES sprites, backgrounds, dog, scores.
- [x] **Stage 3** — ESP32-WROOM-32U ↔ Wii Remote bridge, IR camera enabled, `x,y,b`
      over USB-Serial.
- [ ] **Stage 4** — real aim: 4-point homography in the firmware + corner calibration.
- [ ] **Stage 5** — enclosure (3D-printed shell around the remote), recoil, going
      wireless (Wi-Fi/UDP or BLE, `x,y,b` unchanged).
- [ ] **Stage 6** — levels, NES sounds, more of that dog 🐕.
- [ ] **Stage 7** — a leaderboard on a screen of its own: the name is asked before
      the round, the result goes to a separate server that keeps every attempt in
      SQLite and shows the best run per player on an old-computer console board
      with a running line — planned in [`docs/LEADERBOARD.md`](docs/LEADERBOARD.md).

## How a game goes

A round is **100 ducks in about a minute**. The ducks launch at a steady pace (a
0.6 s pause) and cross the screen quickly; ammunition is not counted. However many
you down is your score.

When the flock is gone you get the result: hits, shots, accuracy, time. If the
result made the top ten, the game asks for a name (**Enter** saves, **Esc**
skips), and the round goes into `scores.json` in the project root. After that
**Space** starts another round and **Q** quits. The table is also printed to the
terminal on exit. On a tied score, whoever spent fewer shots ranks higher.

That table is local to this Mac and keeps ten rounds. Moving it onto a screen of
its own — a separate server storing every attempt and showing the best result per
player, console style with a running line — is planned in
[`docs/LEADERBOARD.md`](docs/LEADERBOARD.md); nothing of it is built yet.

The interface is English (as on the NES): `HIT 37  DUCK 64/100  41s  ACC 58%`,
`NEW HIGH SCORE`, `HIGH SCORES` — as are the comments in `settings.toml`, the
`--help` output and this documentation.

## Settings

Round length, duck size, their speed and the spawn rate live in `settings.toml` in
the project root — with comments there explaining what each value means:

```toml
[round]
ducks = 100           # how many ducks in a round
interval = 0.6        # pause between launches: round length ≈ ducks × interval
points = 1            # points per duck
speedup = 1.0         # 1.0 — a steady pace; less — the round speeds up towards the end

[duck]
width = 0.13          # duck width, fraction of screen width (both hitbox and sprite)
height = 0.16
speed_min = 0.30      # speed: fraction of screen per second, random per duck
speed_max = 0.55
```

Everything is in fractions of the screen rather than pixels, so the same numbers
work identically in the pixel window and in the terminal. The game prints the
values in effect on a single line at startup, so you can see which file was picked
up:

```
Settings: 100 ducks, one every 0.6 s (≈60 s round) · size 0.13×0.16 ·
speed 0.3–0.55 · background meadow, fullscreen
```

The scene is set there too:

```toml
[scene]
background = "meadow"   # sunset | mountains | clouds | random | none
fullscreen = true       # false — play in a window
```

Four backgrounds are sliced out of the NES sheet into `assets/backgrounds/`,
`random` picks one per launch, and `none` uses the landscape drawn in code. In
game the background cycles with the **B** key, so you can pick one by eye and then
write its name into `settings.toml`.

The scene is always scaled up by a whole number of times — otherwise the pixel art
smears. So in fullscreen it is letterboxed whole and black bars are left at the
edges: an NES picture (256×183) cannot be stretched across a wide monitor without
warping the pixels anyway. In windowed mode the window size is fitted to the
background instead.

The file can be deleted — the game will use the same values as defaults; you can
also keep several sets:

```bash
python3 main.py --pygame --settings hard.toml
```

Broken values do not crash the game: an unrecognized key or a zero width gets a
warning on stderr and the default value.

## Pixel art

The sprites and backgrounds are cut out of the original NES sheets by the scripts
in `tools/` — what comes out, what the frames are called and how to add your own
background is described in [`assets/README.md`](assets/README.md):

```bash
python3 tools/slice_spritesheet.py     # assets/source/duckhunt_sheet.webp -> assets/sprites/
python3 tools/slice_backgrounds.py     # assets/source/backgrounds.png     -> assets/backgrounds/
```

If `assets/sprites/` is missing, the frontend falls back to the loose PNGs in
`assets/`, and failing those to the pixel art drawn in `pygame_app.py` itself — so
the game always runs.

## Layout

| Path | Purpose |
|---|---|
| `main.py` | entry point: frontend and input source (mouse / gun / keyboard) |
| `duckhunt/core/models.py` | data: `Duck`, `Facing`, `DuckState` (coordinates 0..1, no sprites) |
| `duckhunt/core/world.py` | **the pure logic core**: `World.update()`, spawning, physics, score |
| `duckhunt/core/config.py` | reading `settings.toml`: duck size and speed, spawn rate |
| `duckhunt/core/scores.py` | the high-score table (`scores.json`) |
| `settings.toml` | the settings themselves — edit these, no need to touch the code |
| `duckhunt/frontends/pygame_app.py` | **the pixel frontend**: sprites, backgrounds, dog, crosshair |
| `duckhunt/frontends/terminal.py` | the ASCII frontend (the original prototype) |
| `duckhunt/input/base.py` | the input interface `InputSource` → `AimState(x, y, fire)` |
| `duckhunt/input/serial_gun.py` | input from the ESP32 over USB-Serial (the `x,y,b\n` protocol) |
| `duckhunt/input/udp_gun.py` | the same protocol over Wi-Fi/UDP |
| `duckhunt/input/wiimote.py` | the remote straight over Bluetooth (reference, macOS-broken) |
| `duckhunt/input/keyboard.py` | keyboard input (for development without hardware) |
| `firmware/esp32_wiimote_bridge/` | **the current firmware**: ESP32-WROOM-32U ↔ Wii Remote → serial |
| `firmware/esp32_lightgun/` | a gun built from scratch: ESP32-S3 + a bare PixArt camera (skeleton) |
| `firmware/esp32cam_bezel/` | plan B: ESP32-S3-CAM (OV2640) with bezel detection, no IR LEDs (skeleton) |
| `firmware/libs/Wiimote/` | the `Wiimote` library plus the Duck Hunt patch (`enable_ir`) |
| `tools/slice_spritesheet.py` | slicing the NES sprite sheet into `assets/sprites/` |
| `tools/slice_backgrounds.py` | slicing the NES background sheet into `assets/backgrounds/` |
| `tools/wiimote_monitor.py` | watching the raw `x,y,b` stream while debugging the gun |
| `tools/ir_view.py` | drawing what the camera sees (the four blobs, the quad, the aim) and logging a test run to `logs/` |
| `docs/BUILD.md` | BOM, wiring and assembly of the hardware |
| `docs/TODO.md` | what is left to do on the gun and the game, most useful first |
| `docs/LEADERBOARD.md` | the plan for the leaderboard server and its console board |

**The layers are independent:** `core` knows nothing about rendering or the
hardware, so both frontends hook onto it, and every input source speaks the same
`x,y,b` gun protocol.

## Building the hardware

The bill of materials, the pinout and a step-by-step guide are in
[`docs/BUILD.md`](docs/BUILD.md) — including the IR beacons, which the current
Wiimote path needs just the same (the remote's camera looks for exactly those four
940 nm dots).

Two alternatives to the Wiimote are kept alive as firmware skeletons: a gun built
around a bare **PixArt IR camera** (SEN0158 / a desoldered Wii camera) on an
ESP32-S3 — `firmware/esp32_lightgun/`; and an **ESP32-S3-CAM (OV2640)** that finds
the monitor's bezel and needs no IR LEDs at all — `firmware/esp32cam_bezel/`,
described in `docs/BUILD.md` → "Alternative camera path". The `x,y,b` protocol is
the same either way, so the game needs no changes.

## References

- **GUN4IR** — the reference IR light gun (schematics, firmware, enclosures).
- [ddean-blip/esp32-lightgun](https://github.com/ddean-blip/esp32-lightgun) — ESP32-S3 + camera.
- [henning2323/IR_LightGun](https://github.com/henning2323/IR_LightGun) — a DIY IR gun.
- [takeru/Wiimote](https://github.com/takeru/Wiimote) — Wii Remote over Bluetooth Classic on the ESP32 (vendored in `firmware/libs/`, plus our IR patch).
- IR camera: DFRobot "Positioning IR Camera" (SEN0158, PixArt PAJ7025 — as in the Wiimote).
- IR beacons: 4× **940 nm** LEDs at the screen corners, each a standalone module on its
  own 2×AAA (3 V, 100–120 Ω) — no wiring across the screen; frost the tips for a wide angle.
