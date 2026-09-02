# 🦆 Duck Hunt — a terminal duck hunt with a home-made light gun

A console (ASCII/TUI) "Duck Hunt" for macOS, driven by an external light gun built
on an **ESP32-S3 + a PixArt IR camera**. The gun works out where the barrel is
pointing (from 4 IR beacons around the screen) and sends the aim coordinates plus
the shot signal to the Mac over USB-Serial (BLE later).

## How it works

```
GUN (ESP32-S3)                              MAC (terminal)
  PixArt IR camera (I²C) ── 4 IR dots ──┐
  trigger (microswitch) ────────────────┤   USB    ┌ InputSource (kbd / serial)
  [later] solenoid, BLE, LiPo           ├─Serial──▶│ 30 FPS game loop
                                        │  x,y,b   └ ducks, crosshair, score, dog
  4 940 nm IR LEDs at the screen corners ┘
```

The game does not emulate a mouse: the gun sends `x,y,b` (coordinates 0..1000 plus
a button mask) and the game draws the crosshair itself — simpler and more precise.

## Roadmap

- [x] **Stage 0–1** — a playable keyboard prototype in the terminal (this code).
- [ ] **Stage 2** — the ESP32 sends `FIRE` on a trigger pull → `input/serial_gun.py`.
- [ ] **Stage 3** — IR camera + 4 LEDs, aim computation, corner calibration.
- [ ] **Stage 4** — recoil (solenoid+MOSFET), enclosure (3D printed), move to BLE+LiPo.
- [ ] **Stage 5** — levels, NES sounds, that dog 🐕.

## Running it (keyboard prototype)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 main.py                 # controls: arrows/WASD aim, Space fires, q quits
```

Path B (CURRENT) — Wiimote → ESP32 → Mac over Wi-Fi, no soldering and no USB:

```bash
# 1) flash firmware/esp32_wiimote_bridge/ onto an ORIGINAL ESP32 (not an S3!),
#    filling in your WiFi SSID/password; press 1+2 on the remote to pair with the ESP32
# 2) on the Mac, start receiving over UDP:
python3 main.py --udp            # port 4210 by default
```

Why this way: pairing a Wiimote directly with macOS does not come up (the Apple
Silicon wall). An ESP32 (the original one, with Bluetooth Classic) pairs with the
remote itself and sends the aim point to the Mac over Wi-Fi/UDP — macOS Bluetooth
is not involved. The remote stays intact and everything is wireless.

Path A — a Wii Remote straight over Bluetooth (does NOT work on recent macOS, kept
for reference):

```bash
brew install hidapi && pip install hidapi
# pair the remote once with the WiimotePair utility (direct pairing is finicky on recent macOS)
python3 main.py --wiimote
```

Path C — once the camera is desoldered and wired to the ESP32:

```bash
python3 main.py --serial /dev/tty.usbmodemXXXX --baud 115200
```

## How a game goes

A round is **100 ducks in about a minute**. The ducks launch at a steady pace (a
0.6 s pause) and cross the screen quickly; ammunition is not counted. However many
you down is your score.

When the flock is gone you get the result: hits, shots, accuracy, time. If the
result made the top ten, the game asks for a name (**Enter** saves, **Esc**
skips), and the round goes into `scores.json` in the project root. After that
**Space** starts another round and **Q** quits. The table is also printed to the
terminal on exit.

The game's interface is English (as on the NES): `HIT 37  DUCK 64/100  41s
ACC 58%`, `NEW HIGH SCORE`, `HIGH SCORES` — as are the comments in
`settings.toml`, the `--help` output and this documentation.

Round length and the value of a duck are set in `settings.toml`:

```toml
[round]
ducks = 100           # how many ducks in a round
interval = 0.6        # pause between launches: round length ≈ ducks × interval
points = 1            # points per duck
speedup = 1.0         # 1.0 — a steady pace; less — the round speeds up towards the end
```

On a tied score, whoever spent fewer shots ranks higher.

## Settings

Duck size, their speed and the spawn rate live in `settings.toml` in the project
root — with comments there explaining what each value means:

```toml
[round]
ducks = 100           # ducks per round
interval = 0.6        # pause between launches, seconds

[duck]
width = 0.13          # duck width, fraction of screen width (both hitbox and sprite)
height = 0.16
speed_min = 0.30      # speed: fraction of screen per second, random per duck
speed_max = 0.55
```

The game prints the values in effect on a single line at startup, so you can see
which file was picked up:

```
Settings: 100 ducks, one every 0.6 s (≈60 s round) · size 0.13×0.16 ·
speed 0.3–0.55 · background meadow, fullscreen
```

The background is chosen there too (for `--pygame` only):

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

Everything is in fractions of the screen rather than pixels, so the same numbers
work identically in the terminal and in the pixel window. The file can be deleted —
the game will use the same values as defaults; you can also keep several sets:

```bash
python3 main.py --pygame --settings hard.toml
```

Broken values do not crash the game: an unrecognized key or a zero width gets a
warning on stderr and the default value.

## Layout

| Path | Purpose |
|---|---|
| `main.py` | entry point, choice of input source (keyboard / gun) |
| `duckhunt/core/models.py` | data: `Duck`, `Facing`, `DuckState` (coordinates 0..1, no sprites) |
| `duckhunt/core/world.py` | **the pure logic core**: `World.update()`, spawning, physics, score |
| `duckhunt/core/config.py` | reading `settings.toml`: duck size and speed, spawn rate |
| `settings.toml` | the settings themselves — edit these, no need to touch the code |
| `duckhunt/frontends/terminal.py` | ASCII rendering + game loop (duck sprites) |
| `tools/slice_spritesheet.py` | slicing the NES sprite sheet into `assets/sprites/` (see `assets/README.md`) |
| `tools/slice_backgrounds.py` | slicing the NES background sheet into `assets/backgrounds/` |
| `duckhunt/frontends/pygame_app.py` | the pixel frontend (the same `World`) |
| `duckhunt/input/base.py` | the input interface `InputSource` → `AimState(x, y, fire)` |
| `duckhunt/input/keyboard.py` | keyboard input (for development without hardware) |
| `duckhunt/input/serial_gun.py` | input from the ESP32 over Serial (the `x,y,b\n` protocol) |
| `firmware/esp32_lightgun/` | ESP32-S3 firmware (Arduino/PlatformIO), skeleton |

**The layers are independent:** `core` knows nothing about rendering or the
terminal (coordinates are normalized to `0..1`), so both the ASCII and the pixel
frontend hook onto it; both use the same `InputSource` and the same `x,y,b` gun
protocol.

## Building the hardware

The full bill of materials (BOM), the pinout and a step-by-step guide are in
[`docs/BUILD.md`](docs/BUILD.md).

**Camera:** the main path is a PixArt IR camera (SEN0158 / from a Wii remote),
firmware [`firmware/esp32_lightgun/`](firmware/esp32_lightgun/). If you cannot get
one — **plan B** uses the widely available **ESP32-S3-CAM (OV2640)** with monitor
bezel detection and no IR LEDs: firmware
[`firmware/esp32cam_bezel/`](firmware/esp32cam_bezel/), details in `docs/BUILD.md`
→ "Alternative camera path". The `x,y,b` protocol is the same either way — the
game needs no changes in either variant.

## References (to study before Stage 3)

- **GUN4IR** — the reference IR light gun (schematics, firmware, enclosures).
- [ddean-blip/esp32-lightgun](https://github.com/ddean-blip/esp32-lightgun) — ESP32-S3 + camera.
- [henning2323/IR_LightGun](https://github.com/henning2323/IR_LightGun) — a DIY IR gun.
- IR camera: DFRobot "Positioning IR Camera" (SEN0158, PixArt PAJ7025 chip — as in the Wiimote).
- IR beacons: 4× **940 nm** LEDs at the screen corners (frost the tips for a wide angle).
