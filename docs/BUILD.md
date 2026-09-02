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
| 4 | IR LEDs (beacons) | **940 nm** IR LED, 5 mm, wide angle | 4 (min) / 8 (better) | Mounted at the 4 screen corners; sand tips flat to widen beam | $0.20 ea |
| 5 | Resistors for LEDs | 150–220 Ω, 1/4 W | 4–8 | One per IR LED (see wiring) | $0.05 ea |
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
| Common ground | `GND` | camera GND, switch, MOSFET, LED supply GND |

Notes:
- **I²C pull-ups:** the DFRobot SEN0158 module has them onboard. A bare/salvaged
  Wii camera needs 4.7 kΩ pull-ups from SDA and SCL to 3V3.
- **Solenoid current must NOT flow through the ESP32.** Power the solenoid from the
  separate 5 V supply; only the MOSFET gate touches the ESP32 GPIO; share GND.

### Screen IR beacons (the "sensor bar")

**Important:** the beacons are a *separate* device — they do **not** connect to the
gun or the Mac in any way. Like a Wii sensor bar, they just emit IR light toward the
player; the gun's camera *sees* them optically. Beacons need **power only (5 V)**.

Four 940 nm IR LEDs, one at each screen/TV corner, defining the aiming rectangle.

**Powering / wiring options:**
- **Wired frame (simplest, recommended to start):** run a thin 2-wire lead (5 V + GND)
  along the screen bezel to all 4 corners; each LED+resistor sits in parallel across
  it. Single USB plug into the **TV's USB port** or a power bank. Hide the wire under
  the bezel.
- **Wireless corners (no wires across the screen):** make each corner a tiny standalone
  module = IR LED + resistor + coin cell (CR2032) / AAA. Four independent clips, zero
  wiring between them; you just swap batteries occasionally.
- Minimum is 4 points (corners) for a clean 4-corner homography. Two LEDs (top bar
  only) works but calibrates less accurately.

```
  [LED]───────────────[LED]      each LED in series with a 150–220 Ω resistor
    │      SCREEN        │        all LEDs powered from one 5 V source
    │                    │        (TV USB port or a power bank)
  [LED]───────────────[LED]
```

- Per-LED resistor for 5 V supply: `R = (5V − 1.3V) / 0.02A ≈ 185 Ω` → use **180–220 Ω**
  for ~20 mA each. Wire each LED+resistor in parallel across the 5 V rail.
- **Sand the LED domes flat** — it diffuses the beam so the camera sees them across
  a wider angle (IR LEDs are very directional otherwise).
- Aim the LEDs toward the player's play zone.

---

## Assembly steps

1. **Bench test the camera.** Wire IR camera → ESP32 (3V3, GND, SDA/GPIO8, SCL/GPIO9)
   on a breadboard. Flash the firmware. Open the serial monitor at 115200 baud —
   you should see `x,y,b` lines. Point it at a TV remote's IR LED (hold a button):
   the coordinates should react. This proves the camera + I²C work.
2. **Wire the trigger.** Micro switch between `GPIO 4` and `GND`. Pressing it should
   flip the last field of the serial line to `1`.
3. **Build the beacons.** Solder the 4 IR LEDs + resistors, mount at the screen
   corners, power from 5 V. Confirm the camera now reports up to 4 points.
4. **First play (crosshair ON).** Run `python3 main.py --serial /dev/tty.usbmodemXXXX`.
   Keep the on-screen crosshair visible — it's your calibration debug tool. Aim and
   watch where the `+` lands vs. where the barrel points.
5. **Calibration (Stage 3).** Replace the placeholder `computeAim()` in the firmware
   with a 4-corner **homography**: capture the 4 beacon points, map camera space →
   screen `0..1000`. Add a "point at each corner" calibration routine.
6. **Add recoil (optional).** MOSFET module: gate→`GPIO 5`, drain→solenoid−,
   solenoid+→+5V supply, source→GND (shared). Fire a short **non-blocking** pulse
   (~50 ms) on trigger — do not use `delay()` in the main loop.
7. **Go wireless (optional).** Add LiPo + TP4056 + switch, flip firmware from USB
   CDC serial to BLE (same `x,y,b` payload — the game/`serial_gun.py` parser is
   reused).
8. **Enclosure.** Print the shell, mount camera (clear line of sight out the barrel),
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
you drop the 4 IR LEDs + their resistors** (item #4/#5), since there are no beacons.

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
