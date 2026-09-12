# 🦆 Duck Hunt Light Gun — Build & Assembly Guide

Hardware build for the terminal Duck Hunt game. The gun tracks 4 infrared (IR)
beacons around the screen with a PixArt IR camera, computes where the barrel is
aimed, and streams `x,y,b` to the Mac over USB (later BLE). Matches the firmware
in [`firmware/esp32_lightgun/esp32_lightgun.ino`](../firmware/esp32_lightgun/esp32_lightgun.ino).

Works on any display — monitor **or** big TV (it tracks the IR beacons, not the
screen). Use **HDMI**, not AirPlay, to avoid input lag.

---

## Bill of Materials (BOM)

### Core — required (minimum viable gun)

| # | Component | Spec / Suggested model | Qty | Notes | ~Price (USD) |
|---|-----------|------------------------|-----|-------|--------------|
| 1 | MCU board | **ESP32-S3** dev board (native USB, e.g. ESP32-S3-DevKitC-1 / Seeed XIAO ESP32-S3) | 1 | Native USB = shows up as `/dev/tty.usbmodem*` on Mac | you have it |
| 2 | IR position camera | **PixArt IR camera** — DFRobot "Positioning IR Camera" (SEN0158) or a salvaged Wii Remote camera (PAJ7025R2) | 1 | Outputs up to 4 IR blob coordinates over I²C (addr `0x58`) | $25–40 |
| 3 | Trigger switch | Momentary **micro switch** (SPDT lever, e.g. Omron D2F / "arcade microswitch") | 1 | Wired to a GPIO with internal pull-up | $1 |
| 4 | IR LEDs (beacons) | **940 nm** IR LED, 5 mm (IR333C / TSAL6100 / SFH 4544) | **12** | **Three per corner**, taped into one bundle; sand tips flat to widen the beam and help them merge | $0.20 ea |
| 5 | Resistors for LEDs | **100 Ω**, 1/4 W | **12** | One per LED — **never one shared resistor per bundle** (see wiring) | $0.05 ea |
| 5a | Battery holder for beacons | **2×AAA with a switch** | 4 | One per corner: each beacon is standalone, no wiring between them | $1.75 ea |
| 5b | AAA batteries | alkaline | 8 | ~15 h of play per set (56 mA per corner) | $0.50 ea |
| 6 | USB-C data cable | Good quality **data** cable (not charge-only) | 1 | Gun → Mac; also powers the ESP32 | $5 |
| 7 | Hook-up wire | 24–26 AWG stranded, a few colors | small roll | Internal wiring | $5 |

### Recoil feedback — optional (Stage 4, big immersion boost)

| # | Component | Spec / Suggested model | Qty | Notes | ~Price (USD) |
|---|-----------|------------------------|-----|-------|--------------|
| 8 | Solenoid | 5 V push-pull solenoid (e.g. 5 V ~1 A pull) | 1 | Kicks on trigger for recoil "thump" | $6–10 |
| 9 | MOSFET driver | Logic-level N-MOSFET module (e.g. IRLZ44N breakout) | 1 | ESP32 GPIO can't drive a solenoid directly | $2 |
| 10 | Flyback diode | 1N4007 (if not on the MOSFET module) | 1 | Protects against inductive kickback | $0.10 |
| 11 | Separate 5 V supply | 5 V ≥2 A (USB power bank / BEC) | 1 | Solenoid current should NOT come from the ESP32's 3V3 rail | $6 |

### Wireless — optional (Stage 4, cut the cable → BLE)

| # | Component | Spec / Suggested model | Qty | Notes | ~Price (USD) |
|---|-----------|------------------------|-----|-------|--------------|
| 12 | LiPo battery | 3.7 V 1000–2000 mAh, JST-PH | 1 | Powers the gun untethered | $8 |
| 13 | Charger / protection | TP4056 module **with protection** | 1 | Safe LiPo charging over USB-C | $2 |
| 14 | Power switch | SPST slide switch | 1 | On/off | $1 |

### Enclosure & tools

| Item | Notes |
|------|-------|
| 3D-printed gun shell | Grab a printable light-gun shell (GUN4IR / SAMCO community designs) or design your own around the camera + trigger |
| M12 lens + holder (optional) | A wider M12 lens on the camera widens the usable aiming cone |
| Soldering iron + solder | Assembly |
| Multimeter | Debugging continuity / voltages |
| Heat-shrink / Kapton tape | Insulation |
| Small screws / standoffs | Mounting boards in the shell |

**Rough budget:** core build ≈ **$40–60** (you already own the ESP32); full build with
recoil + wireless ≈ **$80–100**.

---

## Wiring & pinout

Pins below match the firmware constants — change both together if you re-route.

| Signal | ESP32-S3 pin (firmware) | Connects to |
|--------|--------------------------|-------------|
| I²C SDA | `GPIO 8` (`PIN_SDA`) | IR camera SDA |
| I²C SCL | `GPIO 9` (`PIN_SCL`) | IR camera SCL |
| Trigger | `GPIO 4` (`PIN_TRIGGER`) | micro switch → other leg to **GND** (uses `INPUT_PULLUP`) |
| Solenoid (opt.) | `GPIO 5` (`PIN_SOLENOID`) | MOSFET gate (via module) |
| Camera power | `3V3` | IR camera VCC (PixArt logic is 3.3 V) |
| Common ground | `GND` | camera GND, trigger switch, MOSFET (the beacons share no ground — they are a separate, battery-powered device) |

Notes:
- **I²C pull-ups:** the DFRobot SEN0158 module has them onboard. A bare/salvaged
  Wii camera needs 4.7 kΩ pull-ups from SDA and SCL to 3V3.
- **Solenoid current must NOT flow through the ESP32.** Power the solenoid from the
  separate 5 V supply; only the MOSFET gate touches the ESP32 GPIO; share GND.

### Screen IR beacons (the "sensor bar")

**Important:** the beacons are a *separate* device — they do **not** connect to the
gun or the Mac in any way. Like a Wii sensor bar, they just emit IR light toward the
player; the gun's camera *sees* them optically. Beacons need **power only**.

Four IR beacons, one at each screen/TV corner, define the aiming rectangle. The
homography needs all four dots at once, so four is a hard minimum — there is no
useful three-beacon mode.

**Each beacon is a bundle of three LEDs, not one.** A single 940 nm LED at its rated
20 mA is too dim for this camera: the first builds here measured blob sizes of
0.17 / 0.50 / 0.99 / 1.84 out of 15, and beacons that faint drop out of the frame
constantly. Overdriving one LED is the wrong fix — an LED's efficiency droops as the
current climbs, so 35 mA buys perhaps 65% more light than 20 mA while running 75%
over the datasheet rating. Three LEDs at 20 mA each give **~1.9× the light of one
overdriven LED**, with every part inside spec:

| Per corner | Current | Light | Within the 20 mA rating? |
|---|---|---|---|
| 1 LED, 100 Ω | 20 mA | 0.67× | yes |
| 2 LEDs, 82 Ω | 2 × 21 mA | 1.37× | yes |
| **3 LEDs, 100 Ω** | **3 × 19 mA** | **1.90×** | **yes** |

(Light is relative to one LED at 35 mA, and is modelled from the droop figure above,
not measured. The ratios are the right order; trust `ir_view.py`'s blob sizes for the
real answer.) Two LEDs at 82 Ω is the fallback if you are short on parts — but it is
only ~40% brighter than one, where three nearly doubles it.

**Chosen scheme: four independent 3 V corners.** Each corner is its own tiny module —
3 LEDs + 3 resistors + **2×AAA holder with a switch** — clipped to the bezel. No wires
run across or around the screen, nothing plugs into the TV, and each corner is
switched off separately when you are done playing.

```
  [***]               [***]      each corner is standalone:
    │      SCREEN        │
    │                    │            ┌── 100 Ω ──▶|──┐
  [***]               [***]    bat(+)─┼── 100 Ω ──▶|──┼── bat(−)
                               2×AAA  └── 100 Ω ──▶|──┘
   each [***] = 3 LEDs         +switch  three separate   cathodes
   taped into one bundle                  resistors      twisted together
```

- **One resistor per LED — this is the part that bites.** The temptation with a taped
  bundle is to twist all three anodes into one node and feed them through a single
  resistor. Do not: a shared resistor limits the *total*, and nothing balances the
  branches against each other. At the datasheet spread of Vf = 1.2–1.5 V the current
  divides like this:

  | Shared resistor, 3 V | Current per LED |
  |---|---|
  | 100 Ω | 16.7 / 1.7 / **0.0** mA |
  | 47 Ω | 26.0 / 11.0 / **0.0** mA |
  | 27 Ω | **35.3** / 20.3 / 5.3 mA |

  One LED cooks at 75% over its rating while another does not light at all — and it
  self-worsens, because the hot LED's Vf falls and it takes even more of the current.
  Solder each resistor straight onto its own anode leg *before* taping the bundle;
  then there is physically no room inside for the anodes to touch.
- **Resistor value: 100 Ω per LED.** On fresh cells (3.2 V) that is 20.0 mA for the
  lowest-Vf LED of the batch and 17.3 mA for the highest — the whole spread lands
  inside the rating. After three hours of play (~2.9 V) it is 17.3 / 14.5 mA.
  Do **not** reuse the 180 Ω value from the 5 V variant below — at 3 V that starves
  the LED and the camera may not see the dot.
- **The 16% spread between LEDs in a bundle does not matter.** The camera merges the
  three into a single blob whose brightness is their *sum*, and the sum is the same
  however it divides: 20 + 18.5 + 17.3 equals three at 18.6. Mismatch would only
  matter corner-to-corner, and with one resistor per LED every corner sums to the
  same ~56 mA. A shared resistor is bad for the overdriving, not the unevenness.
- **Runtime:** 56 mA per corner on 2×AAA (~900 mAh) is about **15 hours** — a whole
  evening of play costs a fifth of a set, and the current only sags 20 → 17 mA across
  it. CR2032 coin cells were considered and rejected: same 3 V, but they cannot hold
  56 mA at all.
- **Keep the bundle tight — under ~6 mm between LED centres.** The camera reports at
  most 4 blobs and `computeAim()` wants exactly the four corners, so three LEDs that
  resolve as three separate dots do not make a brighter beacon, they break the
  homography outright. Three 5 mm domes taped body-to-body sit ~5 mm apart, which is
  what you want:

  | Playing distance | 5 mm bundle spans |
  |---|---|
  | 1.4 m | 6.2 px |
  | 1.7 m | 5.1 px |
  | 2.9 m | 3.0 px |

  A blob at full IR sensitivity is already wider than that, so they merge. The short
  end of the range is the risky one — check `n=4` at your *minimum* playing distance,
  not a comfortable one.
- **Sand the LED domes flat** — it diffuses the beam so the camera sees the beacon
  across a wider angle (IR LEDs are very directional otherwise), and with a bundle it
  does double duty: three blurred sources overlap into one clean blob far more
  readily than three sharp ones.
- **All three LEDs parallel, pointing the same way** — domes flush, aimed at the zone
  where the player stands. Fanning them out for a wider angle is exactly what breaks
  the merge; get the angle from sanding instead.
- Electrical tape unwinds and goes sticky as it warms; a short piece of heat-shrink
  holds the bundle better. Nothing here gets hot, though — 80 mW for the whole bundle.
- **Check with a phone camera:** a powered 940 nm LED shows up as a pale violet dot on
  the phone's screen (the naked eye sees nothing). A finished bundle should read as
  **one** dot there, not three.
- **Check the corners against each other too.** The camera reports each blob's size,
  and `tools/ir_view.py` prints the average per corner: four similar numbers mean four
  similar beacons, and one that sits well below the others has a tired battery, a
  resistor on the wrong leg, an LED in backwards, or is pointing somewhere other than
  the play zone.

#### Where exactly to stick them — on the picture, not on the screen

The game's pixel art is scaled by a **whole** number and centred, so in fullscreen
it never fills the display: the 256×183 background is 1.4:1 and the screen is
16:9, and the scale can only go up in steps. On a 1440p 27" it comes out ×7 =
**1792×1281**, which is 70% of the width and 89% of the height; on a 4K 55" ×11 =
**2816×2013**, 73% × 93%. The game prints the rectangle it chose at startup:

```
picture 1792x1281 px at 384,80 of 2560x1440 (70% x 89% of the display, scale 7x)
```

**Stick the beacons on the corners of that picture** — the rectangle the ducks
actually fly in — and tell the game so, once, in `settings.toml`:

```toml
[gun]
frame = "picture"
```

Turn the game on and put each bundle where the picture's corner really is; no
tape measure is involved. Three things come out of this for free:

- **The aim needs no calibration per screen.** The firmware reports where the
  barrel points inside the beacon rectangle, and with the beacons on the picture
  those numbers *are* playfield coordinates. The same `settings.toml` plays on a
  27" monitor and on a 55" TV — the beacons move with you, and nothing in the
  firmware has to be reflashed.
- **You stand ~30% closer**, because the beacon rectangle is 70% of the display
  width and the distance follows the beacon width (next section).
- **Every bit of the sensor's resolution lands on the playfield** instead of on
  the black bars.

The other wiring, `frame = "display"`, is the original one: beacons on the
corners of the physical screen, and the game takes the black bars out itself
(`frontends/pygame_app.py`, `aim_to_picture`). It still works, and aiming into a
bar parks the crosshair at the picture's edge — but it wants fullscreen (a window
cannot be corrected, since nothing tells the game where the window sits) and the
longer playing distance.

Leave the firmware's own `BEACON_CX/CY/W/H` at `0.5/0.5/1.0/1.0` either way: the
same correction lives in `[gun]` on the Mac side, where changing it does not mean
a flash.

#### Beacons on the bezel — the other half of the answer

Nothing says the LEDs *can* go on the glass. A bundle of three sanded 5 mm LEDs
with a battery box behind it wants somewhere to be stuck, and the honest place is
usually the **bezel**. That is a rectangle slightly *bigger* than the screen, and
slightly off-centre when the chin is deeper than the top edge — so it is
`frame = "display"` plus four numbers, and the calculator prints them:

```bash
.venv/bin/python tools/ir_view.py --bezel 5 5 10 5 --diagonal 27
#                           top right bottom left, in mm, run on THAT screen
```

The millimetres are how far outside the screen's own edge each LED bundle's
centre ends up: a 1 cm bezel above the picture and 2 cm below means ~5 mm and
~10 mm if the bundles sit in the middle of the bezel. Out comes the block to
paste:

```toml
[gun]
frame = "display"
beacon_w = 1.017     # 1.7% wider than the screen
beacon_h = 1.045     # 4.5% taller
beacon_cx = 0.5
beacon_cy = 0.507    # the rectangle sits 0.7% of the height low
```

**Where on the bezel, exactly?** Run `main.py --pygame --align`. In this wiring
it lights the letterbox bars pale grey and puts **red** brackets in the four
corners of the *screen* — so the screen's own edge is the line where the light
stops, which is the thing to line a bundle up with (there is no other way to see
it while the game is on). Horizontally level with the side edge of the lit area,
vertically in the middle of the bezel, and that is the position those four
numbers describe.

What actually matters, in order:

- **A rectangle, not a trapezoid.** The left pair on one vertical, the right pair
  on another, the top pair on one horizontal, the bottom pair on another. Four
  numbers can describe any rectangle around the screen; they cannot describe a
  skew, and a skew goes straight into the aim.
- **Left/right symmetry** — otherwise the rectangle's centre moves and
  `beacon_cx` has to say so. Top and bottom may differ freely (1 cm of bezel
  above and 2 below is exactly what `beacon_cy` is for).
- **Not the exact size.** Whatever you measure is what `--bezel` turns into
  fractions, and 1 mm out of 600 is 0.17% of the screen — three pixels.
- All four in the plane of the screen, domes sanded, pointing into the play zone.

Getting the numbers wrong does not break the aim, it skews it by a constant — the
crosshair reaches the edge early, or never quite gets there. The same `--align`
screen also draws thin **blue** brackets on the picture's corners: aim there, and
the crosshair should sit in the angle of the bracket. Consistently high or low is
`beacon_cy`; short of the corners in both axes is `beacon_w`/`beacon_h`.

**What the bezel costs is distance,** and this is the trade to understand before
sticking anything down. The playing distance follows the size of the beacon
rectangle, and on the bezel that rectangle is the whole screen — so it is the
2.9 m column below on a 27", not the 2.0 m one, and `[scene] scale` cannot
shorten it any more (the beacons no longer move with the picture). Beacons on the
glass at the picture's corners buy the shorter distance; beacons on the bezel buy
a monitor with nothing stuck to its screen. Both aim exactly as well.

If the bezel is the only option and 2.9 m is too far, the horizontal pair can be
moved *inwards* along the top and bottom bezel: a narrower rectangle is seen from
closer up, down to the floor set by its height (the screen's own height is fixed,
and ~7 x that is where the vertical field of view runs out — about 2.5 m for a
27"). Then `[scene] scale` has to come down until the picture fits inside that
narrower rectangle, which `--bezel` works out and tells you. Negative
millimetres describe those inward positions.

One direction is not allowed: a beacon rectangle **smaller** than the picture.
The firmware clamps the aim to its own rectangle (0..1000), so aiming past a
beacon sticks there and the picture's outer band can never be reached. `--bezel`
checks for this and says which `[scene] scale` fixes it.

`tools/ir_view.py` reads `[gun] frame` too, so its SCREEN panel says what it is
showing you: the display with the ducks' rectangle inside it, or the picture
itself.

#### How far back the four corners can be seen from

The camera has to hold **all four** beacons in frame at once for the firmware to
solve the homography, and its field of view is narrow (~33° across, ~23° up and
down). That sets a floor under the playing distance, and the rule below is
calibrated against real runs rather than the datasheet — `tools/ir_view.py`
reports what fraction of the frame the beacon rectangle fills, and the runs said:
34% held four dots 67% of the time, 50% started dropping corners as soon as the
aim left the middle, 70% spent 45% of its frames down to a single dot.

**Distance = the width of the beacon rectangle × 4.8** for a comfortable 35% of
the frame; × 3.4 is the bare minimum, and it will drop dots whenever you aim into
a corner.

The frame is narrower vertically (~23° against ~33°), so the same 35% of the
*height* asks for **× 7.0** — which for any rectangle wider than about 1.5:1 is
the slacker of the two constraints and can be ignored. It only starts deciding
the distance once the rectangle has been made narrow on purpose (beacons moved
inwards along a bezel, say). `tools/ir_view.py --bezel` applies both and names
the axis that won.

| Screen (16:9) | Beacons on the screen | Comfortable | On the **picture** (~70%) | Comfortable |
|---|---|---|---|---|
| 13.6" MacBook (29 cm wide) | 29 cm | 1.4 m | 25 cm | 1.2 m |
| 24" (53 cm) | 53 cm | 2.5 m | 37 cm | 1.8 m |
| 27" (60 cm) | 60 cm | 2.9 m | 42 cm | 2.0 m |
| 43" (95 cm) | 95 cm | 4.6 m | 67 cm | 3.2 m |
| 55" (122 cm) | 122 cm | 5.8 m | 89 cm | 4.3 m |

(× 3.4 instead of × 4.8 for the bare minimum in either column.)

A monitor is comfortable; a big TV is not, and that is the camera's fault — a
55" wants most of a room. Below the minimum the gun still works, because the
firmware falls back to a coarse centroid aim on 1-3 dots, but the aim stops being
screen-referenced: only the direction of movement survives, not the position.

**Precision is not the limit here.** Measured on a steady gun, the aim wobbles by
0.1-0.2% of the screen — a hundredth of a duck. Shrinking the beacon rectangle to
buy distance costs almost nothing in noise; what it costs is tolerance, since a
centimetre of misplaced beacon counts for three times as much on a 40 cm
rectangle as on a 120 cm one.

**If the room cannot give you that distance, make the picture smaller.** Not the
beacon rectangle on its own — the firmware's clamp makes an undersized rectangle
unreachable at the edges (above) — but both together, which is one line:

```toml
[scene]
scale = 6        # display pixels per pixel of the art; 0 = as big as fits
```

Then re-stick the beacons on the smaller picture's corners. Distance scales
straight down with it: a 4K 55" at `scale = 11` (all it will fit) is an 89 cm
picture at 4.3 m, at `scale = 6` a 49 cm picture at 2.3 m, at `scale = 4` a 32 cm
picture at 1.6 m. Nothing else in the game changes — every size and speed is a
fraction of the picture, so the ducks stay exactly as big and as fast relative to
it.

What you cannot cheat is the angle. The distance rule says the beacon rectangle
fills ~35% of a 33° field of view, so the picture always ends up subtending about
**12°** — the same apparent size on a 27" at 2 m as on a 55" at 4.3 m. With this
camera a bigger TV buys you nothing unless the room can give back the distance;
what buys a genuinely bigger picture is a **wider lens** (the PixArt + M12 path in
`firmware/esp32_lightgun`), not a bigger screen.

*Alternative, if you would rather not have batteries:* run a thin 2-wire lead (5 V +
GND) along the bezel to all four corners, all 12 LEDs each with its own
**180 Ω** resistor (`(5V − 1.35V)/0.02A ≈ 182 Ω`), the whole frame fed from one USB
plug (TV USB port or a power bank) — 240 mA total. The one-resistor-per-LED rule is
the same here; 5 V only makes the corners match each other more closely, because the
Vf spread is a smaller share of the headroom.

---

## Assembly steps

1. **Bench test the camera.** Wire IR camera → ESP32 (3V3, GND, SDA/GPIO8, SCL/GPIO9)
   on a breadboard. Flash the firmware. Open the serial monitor at 115200 baud —
   you should see `x,y,b` lines. Point it at a TV remote's IR LED (hold a button):
   the coordinates should react. This proves the camera + I²C work.
2. **Wire the trigger.** Micro switch between `GPIO 4` and `GND`. Pressing it should
   flip the last field of the serial line to `1`.
3. **Build the beacons.** Solder 4 standalone modules: 3 LEDs, each with its **own**
   100 Ω resistor on its anode leg, cathodes twisted to one node, plus a 2×AAA holder
   with a switch. Tape each trio into a tight bundle (≤6 mm between centres), sand the
   domes, and check with a phone camera that it reads as **one** dot, not three. Clip
   them to the corners of the game's picture: run `main.py --pygame --align` and
   tape each bundle into the angle of its bracket — that is the whole calibration,
   and `tools/ir_view.py --plan --diagonal 27` says beforehand how far back that
   rectangle puts you. Then run `tools/ir_view.py`: it draws the blobs the
   camera reports and the quad built from them, so you can see all four corners appear
   — and it logs the run to `logs/` for later reading. Walk to your *closest* intended
   playing distance and confirm it still says `n=4`: that is where a loose bundle
   splits into extra dots.
4. **Test the aim without the gun first.** `tools/fake_gun.py` sends the bridge's
   own `x,y,b` stream over UDP, so the Mac side can be checked before any beacon is
   stuck to anything: `main.py --pygame --udp` in one terminal,
   `tools/fake_gun.py --fire` in another. With `[gun] frame = "picture"` the
   crosshair should land exactly on the four corners of the picture and shoot
   there. Whatever is wrong at this point is in `settings.toml`, not in the
   hardware.
5. **First play (crosshair ON).** Run `python3 main.py --serial /dev/tty.usbmodemXXXX`.
   Keep the on-screen crosshair visible — it's your calibration debug tool. Aim and
   watch where the `+` lands vs. where the barrel points.
6. **Check the aim mapping.** `computeAim()` in the bridge firmware already solves
   the 4-corner homography — no calibration routine is needed, the four beacons
   *are* the calibration. What does need confirming once on real hardware is the
   two axis flags at the top of the file (`CAM_MIRROR_X`, `CAM_MIRROR_Y`): if the
   crosshair runs the wrong way when you sweep the gun, flip the matching flag.
7. **Add recoil (optional).** MOSFET module: gate→`GPIO 5`, drain→solenoid−,
   solenoid+→+5V supply, source→GND (shared). Fire a short **non-blocking** pulse
   (~50 ms) on trigger — do not use `delay()` in the main loop.
8. **Go wireless (optional).** Add LiPo + TP4056 + switch, flip firmware from USB
   CDC serial to BLE (same `x,y,b` payload — the game/`serial_gun.py` parser is
   reused).
9. **Enclosure.** Print the shell, mount camera (clear line of sight out the barrel),
   trigger, and boards. Keep the camera lens unobstructed.

---

## Alternative camera path (Plan B): ESP32-S3-CAM / OV2640

Use this if the PixArt IR camera (SEN0158 / Wii camera) is out of stock — while you
keep hunting for a used Wiimote. It swaps the scarce IR-position camera for a cheap,
everywhere-available **ESP32-S3-CAM** board with an **OV2640** sensor, and detects the
**monitor's physical frame (bezel)** by edge detection instead of IR beacons — the
approach used by [ddean-blip/esp32-lightgun](https://github.com/ddean-blip/esp32-lightgun).

**What changes vs. the IR build:**

| | IR path (primary) | ESP32-S3-CAM / OV2640 (Plan B) |
|---|---|---|
| Camera | PixArt SEN0158 / Wii cam | **ESP32-S3-CAM + OV2640**, €8–12, widely stocked |
| Screen IR LEDs (beacons) | required | **not needed** (tracks the monitor edges) |
| Extra MCU | separate ESP32-S3 | camera board **is** the MCU (all-in-one) |
| Firmware | simple (camera returns 4 points) | heavier — frame capture + edge detection on-device |
| Precision / latency | best (~4 ms) | medium (~20–30 FPS at QVGA) |
| Room lighting | irrelevant | matters (needs contrast between screen and bezel) |
| Output protocol | `x,y,b\n` | **same** `x,y,b\n` — the game/`serial_gun.py` is unchanged |

**Plan-B BOM delta** (replaces core items #1 + #2):

| Component | Spec | Qty | Notes |
|---|---|---|---|
| ESP32-S3-CAM board | ESP32-S3 + **OV2640**, PSRAM recommended | 1 | e.g. Freenove ESP32-S3-CAM, XIAO ESP32-S3 Sense |
| (optional) M12 wide lens | ~120° cropped to ~85° | 1 | wider aiming cone |

Everything else (trigger, wiring, recoil, wireless, enclosure) stays the same — **but
you drop the whole beacon kit** (items #4, #5, #5a, #5b), since there are no beacons.

**Firmware:** use [`firmware/esp32cam_bezel/esp32cam_bezel.ino`](../firmware/esp32cam_bezel/esp32cam_bezel.ino)
(skeleton) instead of `esp32_lightgun.ino`. It captures a grayscale QVGA frame,
finds the monitor rectangle, maps the aim point, and emits the same `x,y,b` lines.

**Trade-off to accept:** lower precision and sensitivity to lighting. For a low-res
ASCII game that's fine; if you later want pixel-perfect aiming, switch to the IR path
once you get a Wii camera — the game and protocol don't change either way.

## Safety

- **LiPo:** only charge through a protection-equipped module (TP4056 w/ protection);
  never short or puncture; don't leave charging unattended.
- **Solenoid:** always include the flyback diode; keep its current off the ESP32
  rails; it can get warm — don't hold it energized.
- **IR is invisible but real light** — don't stare into beacon LEDs at close range.

---

## Reference builds

- **GUN4IR** — the gold-standard DIY IR light gun (schematics, firmware, shells).
- [ddean-blip/esp32-lightgun](https://github.com/ddean-blip/esp32-lightgun) — ESP32-S3 + camera.
- [henning2323/IR_LightGun](https://github.com/henning2323/IR_LightGun) — DIY IR light gun.
- **SAMCO** — camera + LED light gun system.
