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

The aim mapping in the bridge is still a stub (it averages the visible IR dots);
the 4-point homography and corner calibration are the next step.

### To check on the next run

Two changes are in the code but have never been exercised against the hardware —
the board was unplugged when they were written. Worth a look the next time the gun
comes out:

- [ ] **Does the remote stay paired across game launches?** `input/serial_gun.py`
      now opens the port without pulsing DTR/RTS, which on these CH340 boards is what
      rebooted the bridge and dropped the remote. Start the game with the remote
      already connected: if the crosshair moves without touching SYNC, it works. If
      the bridge still reboots (it reprints `# Duck Hunt Wiimote bridge...`), the
      adapter resets some other way and the SYNC-after-launch dance comes back.
- [ ] **Does the crosshair reach the screen edges in fullscreen?** `pygame_app.py`
      now converts gun coordinates from display fractions to scene fractions, so the
      crosshair should track the barrel all the way into the corners instead of
      lagging by up to half a black bar. Only meaningful once the beacons give real
      screen-referenced aim — with one IR dot the aim is relative anyway.
- [ ] **Does the link drop under load?** One capture lost the remote after 16 s and
      re-paired itself 0.8 s later; a later 60 s run held fine. If it recurs, put
      fresh AA cells in the remote before blaming the firmware.

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

## How a game goes

A round is **100 ducks in about a minute**. The ducks launch at a steady pace (a
0.6 s pause) and cross the screen quickly; ammunition is not counted. However many
you down is your score.

When the flock is gone you get the result: hits, shots, accuracy, time. If the
result made the top ten, the game asks for a name (**Enter** saves, **Esc**
skips), and the round goes into `scores.json` in the project root. After that
**Space** starts another round and **Q** quits. The table is also printed to the
terminal on exit. On a tied score, whoever spent fewer shots ranks higher.

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
| `docs/BUILD.md` | BOM, wiring and assembly of the hardware |

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
