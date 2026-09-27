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
  4× 940 nm IR LEDs on the ───────┘              │  x,y,b
  picture's corners (the "sensor bar")           ▼
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
pip install -r requirements-dev.txt        # only to run the tests

python3 main.py                                              # aim with the mouse (development)
python3 main.py --serial /dev/tty.usbserial-0001             # aim with the light gun
python3 main.py --serial /dev/tty.usbserial-0001 --mode practice   # ... starting on practice
```

The round is picked **in the game**, on the title screen — **M**, or **A on the
remote** — so handing the gun to a first-timer and taking it back is not a
restart. `--mode NAME` only says which round the evening opens on.

**Playing with the light gun**, start to finish:

```bash
ls /dev/tty.usbserial*                                       # find the bridge (usually -0001)
python3 main.py --serial /dev/tty.usbserial-0001             # play
#   Then press 1 and 2 together on the remote. If the gun was in use a moment
#   ago, not even that: the bridge pages it by address and it comes back on its
#   own. The red SYNC button under the battery cover is not needed any more.
```

**Connecting the remote** takes one press of **1+2**, at any point after the game
has started — there is no window to hit. Opening the serial port still reboots the
bridge (the macOS CH340 driver pulls the reset line whatever pyserial asks), so the
bridge comes up fresh every time; what changed is that it no longer sits deaf after
one 12.8 s scan, and it no longer needs the SYNC button to pair:

- it **pages the last remote it used** first, by address out of its flash — a remote
  that is merely awake (which it is for a while after the bridge reboots under it)
  answers that without any button at all;
- then it **scans** for a remote made discoverable by **1+2** (or by SYNC), in rounds,
  for as long as nothing is connected;
- then it **holds the radio quiet** for a few seconds, which is the window a remote
  needs to page the bridge itself — any button, on a remote that was paired
  SYNC-style and so remembers it.

**If the remote will not connect**, it is almost always one of these:

- **The remote went to sleep.** It only stays discoverable for ~20 s after 1+2;
  press it again and watch for `# new remote` on the port.
- **No `--serial` on the command line.** Without it the game runs on the mouse and
  ignores the gun completely, which looks exactly like a dead remote.
- **Tired batteries.** The remote pairs happily and then drops the link a few seconds
  later under continuous IR reporting.

The bridge says which of the three ways of pairing it is trying (`# new remote,
trying: ...`) and remembers the one that worked in flash, so the guessing happens
once. Two one-letter commands on the same serial port drive it by hand: **`p`**
pairs SYNC-style on the next connection — the only kind the *remote* stores, after
which any button on it reconnects — and **`f`** makes the bridge forget the remote
it knows. (**`?`** prints everything the bridge is set to: the axes, the remote
it remembers, the beacon rectangle it was flashed with.)

To see what the camera sees — and what the bridge is saying while it pairs — run `tools/ir_view.py`: it draws the blobs in the
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
.venv/bin/python tools/ir_view.py --plan --diagonal 27   # where to tape the beacons
.venv/bin/python tools/ir_view.py --bezel 5 5 10 5 --diagonal 27   # ... on the bezel
```

**Testing the aim without any hardware.** `tools/fake_gun.py` sends the same
`x,y,b` stream over UDP that the bridge does, so the whole Mac side of the aim —
the `[gun]` rectangle, the letterbox conversion, the crosshair, the hitbox — can
be tested with a known aim point instead of a shaking hand. Two terminals:

```bash
.venv/bin/python main.py --udp                    # the game, listening
.venv/bin/python tools/fake_gun.py --fire         # aim at each corner in turn, and shoot
.venv/bin/python tools/fake_gun.py --sweep        # a slow circle
```

With `[gun] frame = "picture"` the crosshair should reach the four corners of the
picture exactly and shoot there; `--blind` (no beacons in view) should freeze it
where it was rather than jump.

The remote re-pairs by itself if the link drops mid-round: the game keeps running and
the crosshair freezes at its last position until the stream comes back.

Every round starts the same way, the first of the session and every one after
it: the title screen waits for the trigger (or Space), and then `[round]
countdown` seconds tick down — 3 by default — before the first duck, so there is
time to get the gun up. Leaving the results screen takes you back to that title
screen rather than straight into a countdown, so a pull aimed at dismissing the
score table cannot start the next round by accident. A shot has a radius, `[gun]
spread`: the crosshair circle *is* the hit zone, and the nearest duck touching it
falls.

The controls are listed on the title screen and on the results screen — you are
standing three metres away with a gun in both hands, which is no place to be
looking things up. In game: **mouse / gun** aims, **left button / trigger**
fires, **Esc** stops the round early and takes you to the result with the score
so far still offered to the board, **B** cycles the background, **G** puts the
gun's own numbers on the HUD (report rate, how clumped the reports are, how often
the beacons are out of view, how old the aim is — "it feels laggy" has three
different causes and these tell them apart), **F1** sights the gun in on five
targets (from the title screen or the results screen) and **F2** turns that
correction on and off so it can be judged rather than assumed, **Space** or the
trigger leaves the results screen, **Q** quits.

### Bringing up the gun

1. Flash `firmware/esp32_wiimote_bridge/` onto an ESP32-WROOM-32U (Arduino, with
   `--libraries firmware/libs` so the patched `Wiimote` library is picked up).
2. Plug the ESP32 into the Mac over USB. **Start the game, then press 1+2 on the
   remote** — no rush, and no need to reach the SYNC button under the battery
   cover, which is the point: the remote lives inside the gun shell. The board
   prints its progress as `# ...` lines on the same serial port — the game's
   parser ignores them.
3. Stick the four IR LEDs down and say where they ended up, in `[gun]`:
   on the corners of the **game's picture** (`frame = "picture"` — nothing to
   measure, and it plays the same on any screen; the game prints the picture's
   exact rectangle at startup), or
   on the **bezel** around the screen (`frame = "display"` plus the four numbers
   `tools/ir_view.py --bezel` prints — nothing stuck to the glass, at the cost of
   a longer playing distance). Then run the game with `--serial`. See
   [`docs/BUILD.md`](docs/BUILD.md).

The bridge turns the four beacons into an aim point with a **4-corner homography**:
the dots the camera reports *are* the screen rectangle seen down the barrel, so the
aim point is where the centre of the camera image falls inside it — which handles
distance, angle and gun tilt without any calibration step. It needs all four dots
at once, and the camera's view is narrow (~33°), so there is a minimum playing
distance — about 2 m for a 27" monitor and 4.3 m for a 55" TV with the beacons on
the picture's corners, since aiming into one corner pushes the opposite one out of
frame ([`docs/BUILD.md`](docs/BUILD.md) has the table). The distance follows the
width of the beacon rectangle, so a TV wants a sofa further back than a monitor
does. On fewer than four dots it drops back to the old centroid guess: the
crosshair keeps moving, but it is no longer screen-referenced.

### Sighting the gun in

The homography puts the crosshair where the **camera** is looking. You aim down
the **sights**, and those are not the camera: they sit a couple of centimetres
above and behind it, the barrel is not exactly parallel to the lens, and the
beacon rectangle in `[gun]` is a tape measure's opinion rather than a law. What
comes out is a crosshair a steady distance from what the front sight is covering
— invisible while the crosshair is on screen, because you just aim with it, and
murder the moment you turn it off (**A** on the remote) and shoot down the barrel
the way the Zapper was meant to be shot.

So it gets measured. **F1**, or `--calibrate`:

```bash
cd /Users/evgenychernyak/projects/duckhunt
.venv/bin/python main.py --serial /dev/tty.usbserial-0001 --calibrate
```

Five round targets — the centre, then the four corners — shot one at a time
**with the crosshair off**. Put the front sight on the bull, pull, and the screen
records the gap between where the gun said it was pointing and where you actually
pointed it. One round is five shots; **the reading is not the position at the
moment the trigger was read** but the median of the aim over the quarter second
before it, stopping 40 ms short of the pull, which is the part where the gun was
being held still rather than jerked.

After every round it says how bad it was and what it can do about it:

| line | what it means |
|---|---|
| `BEFORE` | how far the gun was from where you pointed it — the error you came to fix |
| `AFTER` | what is left once the correction is applied. **This is the only honest answer to "is it good now"** |
| `YOUR HAND` | your own scatter while holding aim — the floor. A residual already below it cannot be improved by shooting more |
| `MODEL` | what the fit found: the sights' shift, a scale per axis, and the roll you hold the gun at |
| `ROUND TO ROUND` | from the second round on: how far the same target moved between rounds. Bigger than `AFTER` means the residual was luck |

The verdict is read against **the shot's own radius** (`[gun] spread`), not
against a round number — the same residual is excellent on a forgiving hit zone
and poor on a pinpoint one. From there: **trigger** or **Space** shoots another
round (five more shots into the same fit, and it gets better), **R** throws away
the round you just shot if you fumbled one, **S** (or **A** on the remote) saves
it to `calibration.json` and plays with it from then on, **Esc** leaves it alone.
**U** during a round takes back the last shot.

The correction is an **affine** map — shift, scale per axis, rotation and shear,
six numbers out of ten equations. A pure shift would fix the parallax and nothing
else, and the other two errors are not shifts: a beacon rectangle measured 3 %
too wide is a scale error that is zero in the middle and worst at the edges, and
a gun held with a little roll is a rotation. A full homography would be eight
numbers, but the two extra ones model the camera looking at the screen off-axis
— and the firmware has already dealt with that one. The fit is checked before it
is believed: a map that mirrors the picture, tilts it 25° or halves it is a
misaimed round rather than a sight error, and it falls back to scale+shift and
then to shift alone instead of shipping nonsense.

Shots that land with no beacons in view are **not** recorded — the last position
is a memory, not an aim, and baking one into the fit is how a calibration ends up
worse than none. `calibration.json` keeps the geometry it was measured on, and
the game says so at startup if the picture or the `[gun]` numbers have changed
since.

### The lag, and where it actually is

Nothing in the game is slow, and that is the point: the crosshair trails the
barrel because the aim it is drawing is *old*, not because anything is
struggling to draw it. Measured on this Mac, the frame costs 16.67 ms and under
1 ms of that is the drawing — `display.flip()` waits for vsync and paces the
loop at 59.8 fps whatever it is given, so raising the frame rate buys nothing.
The budget in good health:

| where | cost |
|---|---|
| the remote's report period (mode 0x33, ~96/s) | ~10 ms |
| the Bluetooth link, no interference | ~10-20 ms |
| USB-Serial and the CH340 driver | ~1-3 ms |
| the game reads the port once a frame | 0-17 ms |
| the frame is shown at the next vsync | ~17 ms |

Call it 40-55 ms, in which a barrel sweeping at 1.5 playfields a second travels
6-8 % of the screen. Two of those five rows can be argued with; the radio is the
one that turns into whole tenths of a second when the band is busy, and the
measurement that settled that is in [the run notes below](#to-check-on-the-next-run):
97 reports/s with no stalls at -42 dBm, against 40-60/s and stalls up to 1.7 s at
-51 dBm. **The single biggest thing you can do about the lag is put the bridge
where the player stands** — on a USB extension, not next to the screen — and use
the -32U's external antenna.

**Extrapolation was tried and taken back out.** The crosshair can be drawn
where the aim is *going* rather than where it was last heard from — advanced
along a velocity fitted over the last 100 ms of reports, by a `lead` of a few
tens of milliseconds. Two evenings of A/B with the gun said it works: 40 ducks
in 55 shots (73 %) at 35 ms against 46 % at 20 ms, with the overshoot that made
the first run look bad traced to a ceiling left above the lead, so that every
stall in the link briefly tripled it.

It still came out, and the reason is not in the hit rate. A crosshair thrown
ahead of the barrel leaves the barrel the moment you move, and a sight that does
not sit where the gun is pointed is not a sight — the hit rate was bought with a
crosshair that lies, and it lies most in exactly the movement you aim with. So
the game draws the aim the gun reported, and the ~45 ms is paid for where it is
actually spent: by standing the bridge next to the player. `git log` has the
code and the tables if the question ever comes back.

**In a hall full of other radios** — a conference, a fair — expect the link, not
the game, to be what gives. Bluetooth Classic hops 79 1-MHz channels 1600 times
a second, so other *Bluetooth* devices mostly cost collisions in proportion to
how many there are; the real damage comes from Wi-Fi, where every 20 MHz access
point covers ~22 of those 79 channels for as long as it is transmitting, and a
hall has them on channels 1, 6 and 11 at full power. Adaptive hopping then
crowds the link into what is left, a packet that collides is retransmitted, and
a retransmission is exactly the 20-100 ms hole that reads as lag. Bodies between
the gun and the bridge cost several dB each on top. What to do about it, in the
order it is worth doing:

- **Shorten the link.** The bridge on a USB extension at the player's position,
  a metre or two from the gun, not three metres away behind the screen. This is
  the one that was actually measured: halving that distance took the stalls from
  1.5 a second to 0.17 and the report rate from 83/s to 96 (see [the run
  notes](#to-check-on-the-next-run)). Nothing in software came close.
- **Use the antenna.** The WROOM-**32U** has a U.FL connector precisely so the
  antenna does not have to be where the board is; keep it vertical (the remote's
  own antenna is too) and clear of metal and of the laptop's lid.
- **Get the Mac off 2.4 GHz.** Its Wi-Fi on 5 GHz or on Ethernet, and no
  hotspot: the strongest 2.4 GHz transmitter in the room is otherwise sitting
  30 cm from the bridge.
- **Fresh cells in the remote.** A tired AA pair drops the transmit power, which
  is the same thing as more interference.
- **Measure, do not guess.** The bridge prints `# link: rssi -NN dBm` once a
  second and **G** puts the report rate, the stalls and the aim's age on the
  HUD. Above -45 dBm the stream is healthy; -50 and below is where the stalls
  start.
- **If the signal is good and the rate sags anyway**, the band is crowded rather
  than the link long — and the one lever software had for that is discussed
  below, along with why it is not in the sketch any more.

#### The channel map, and why it is not here

Where the interference is known in advance, a host can tell the controller which
channels not to bother hopping onto (`HCI_Set_AFH_Host_Channel_Classification`,
which the vendored library implements). The bridge had a table of Wi-Fi plans
behind an `a` command for exactly that, and it was measured: the ESP32's
controller takes the map (`status 0x00`), and a reboot forgets it.

Whether it *helps* needs a hall full of access points and an A/B on the report
rate, which is not a thing a desk can answer — and it only bites at all while
the bridge is the piconet's master, i.e. when it placed the call. A lever that
cannot be judged where the gun is used is a lever nobody pulls, so it is out of
the sketch; `git log` has it.

### To check on the next run

Some of what follows is in the code but has never been exercised against the
hardware — the board was unplugged when it was written. Worth a look the next time
the gun comes out:

- [x] **Does the remote stay paired across game launches? No — measured, it does
      not.** `input/serial_gun.py` sets DTR/RTS false before opening, and the bridge
      still reboots on every open: the port comes up printing the ESP32's ROM log
      and `rst:0x1 (POWERON_RESET)`, twice out of two attempts. The macOS CH340
      driver drives the lines during `open()` whatever pyserial asks for, so the
      EN pin gets pulled anyway. A hardware fix if the reboot itself ever matters:
      a 10 µF capacitor from EN to GND, or cut the auto-reset trace and flash with
      the BOOT button instead. What the reboot *cost* — the SYNC-after-launch
      dance — is dealt with in the firmware instead, in the item below.

- [x] **Does 1+2 connect the remote now, and does it come back by itself? Yes to
      both — measured.** A 1+2 press connected on the first attempt, by the first
      strategy the bridge tries (no authentication at all), 1.7 s after the press:
      `# new remote, trying: no authentication` -> `# Remote connected` ->
      `# stored for next time: remote 00:1B:7A:23:88:42`. Then the port was closed
      and reopened, which is exactly what starting the game does and which reboots
      the bridge: the gun was back **5.6 s later with nothing pressed**, and again
      on every launch after that. 70-98 reports/s either way, RSSI -39 to -50 dBm,
      quality 205-216/255, no drops in 130 s. A full round with the gun scored 81
      of 100 ducks at 75%, which is the whole chain working.

      *Which* of the three ways back it was, the logs do not yet say — and the
      honest reading is that it was not the bridge's own paging. Only an outgoing
      connection raises `WIIMOTE_EVENT_NEW`, and no reconnect printed the
      `# new remote` line that goes with it, so the remote was calling the bridge:
      it still remembers this ESP32 from the SYNC pairings of the old firmware,
      and page scan has always been on, so it comes home by itself. The bridge now
      prints which side placed the call (`Remote connected (the bridge called it)`
      against `(it called the bridge)`), so the next log settles it. It matters for
      a remote that has never been SYNC-paired to this bridge: that one has nothing
      to call back, and the direct page is what would have to carry it.
      So the SYNC button was never needed for anything: the remote is happy to be
      connected to without pairing, and the old firmware was insisting on a PIN
      built from the bridge's address — which is only what the SYNC button asks
      for. The three things that had to change, all in
      `firmware/esp32_wiimote_bridge/` and the vendored `Wiimote` library:

      - **The PIN.** The remote asks for a different one depending on which button
        opened its window — SYNC wants the *bridge's* bluetooth address, 1+2 wants
        the *remote's own* — and the library only ever answered with the bridge's.
        A 1+2 press therefore got all the way to authentication and was hung up
        on, which is exactly the reported symptom. The bridge now tries, in turn,
        no authentication at all (what a 1+2 connection normally wants), then the
        remote's address, then the bridge's, and keeps whichever worked in flash.
        A wrong guess costs one retry.
      - **The window.** The old sketch scanned exactly once, for the 12.8 s after
        boot, and then sat deaf: a press that came later did nothing at all. It
        now scans in rounds for as long as nothing is connected.
      - **The address.** A remote is only discoverable for ~20 s after a button
        press, but it stays *connectable* while it is awake. The address of the
        last remote that worked goes into flash and every round starts by paging
        it directly, so a game restarted promptly should find the gun with no
        press at all.

      The other two strategies have therefore never run against the hardware —
      they are the fallback for a remote that does want a PIN. `p` on the serial
      port forces the SYNC-style pairing (the only one the *remote* stores, after
      which any button on it reconnects); `f` makes the bridge forget what it
      knows, which is the way to replay the first connection from scratch.
- [x] **What took 6 dB off the link? The laptop was moved closer to the
      player — and that is the whole recipe.** Two runs half an hour apart, same
      room, same remote, same firmware: RSSI from -44…-49 dBm to -36…-46, the
      report rate from 83/s to 96, stalls longer than 50 ms from **1.5 a second
      to 0.17**, and the worst pause in a run from 1376 ms to 136. Nothing in
      software has ever moved these numbers that far. Six dB in free space is
      about half the distance, so the bridge went from roughly three metres from
      the gun to roughly one and a half.

      The lesson is not "play closer to the screen", though, and that matters at
      a venue where the screen's position is not yours to choose: the bridge was
      only closer because it is plugged into the laptop that carries the screen.
      **Put it on a USB extension instead** and the radio gets its 6 dB while the
      picture stays exactly where it was — which is the point, because the
      playing distance is set by the IR camera's field of view (all four beacons
      have to fit in ~33°), not by the radio. The two constraints pull in
      opposite directions, and a three-metre cable is what stops them fighting.

- [ ] **Do the beacons and the picture line up?** The picture is smaller than the
      display, because the pixel art is scaled by a whole number and centred
      (1280×915 inside 1470×956 on this Mac — bars of 6.5% down the sides, 2.1%
      top and bottom; the game prints the rectangle it chose at startup).
      `[gun] frame` says which rectangle the LEDs are actually on — `"picture"`
      for its corners (nothing to measure, and it plays the same on any display),
      `"display"` for the screen's, which the frontend then converts. An
      in-between rectangle goes in `beacon_w/h` and `beacon_cx/cy`
      ([`docs/BUILD.md`](docs/BUILD.md)).

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
| `python3 main.py --serial PORT` | **the gun**: Wiimote → ESP32-WROOM-32U → USB-Serial |
| `python3 main.py` | the mouse — no hardware, for development. Never a record: a mouse has no sights to aim down, so there the crosshair *is* the aiming |
| `python3 main.py --udp` | the same `x,y,b` off the network, which is how `tools/fake_gun.py` drives the game with no hardware at all |

Anything able to say where it is pointing can drive the game: an `InputSource`
is three methods, and the `World` has never heard of a gun.

## Roadmap

- [x] **Stage 0–1** — playable prototype, pure logic core (an ASCII frontend
      rode on it until Sept 2026, when the pixel one had long replaced it).
- [x] **Stage 2** — pygame pixel frontend: NES sprites, backgrounds, dog, scores.
- [x] **Stage 3** — ESP32-WROOM-32U ↔ Wii Remote bridge, IR camera enabled, `x,y,b`
      over USB-Serial.
- [ ] **Stage 4** — real aim: 4-point homography in the firmware + corner calibration.
- [ ] **Stage 5** — enclosure (3D-printed shell around the remote), recoil, going
      wireless (Wi-Fi/UDP or BLE, `x,y,b` unchanged).
- [ ] **Stage 6** — levels, NES sounds, more of that dog 🐕.
- [x] **Stage 7** — a leaderboard on a screen of its own: the game asks who was
      shooting *after* the round and posts the result to a separate server that
      keeps every attempt in SQLite; a console board shows the best run per player
      with a running line along the bottom, and the game itself draws none of it —
      [`docs/LEADERBOARD.md`](docs/LEADERBOARD.md). One command brings the whole
      thing up; autostart waits for the Pi it would run on.

## How a game goes

There are **two rounds**, and they are two settings files over the same game
rather than two code paths. **The title screen switches between them** — **M** on
the keyboard, or **A on the remote**, which is the one that matters: the player
choosing the round is three metres away with both hands on the gun. The name of
the round and a line saying what it is sit above the controls, and the next
trigger pull plays that one.

**The scored round** — `settings.toml`, what you get by default — is **40 ducks and
40 shots**, launched at a steady pace (a 0.9 s pause) and crossing the screen
quickly. It ends when the ducks run out *or* the magazine does, whichever comes
first: the shot that empties it still counts, and a duck already falling still
lands. Firing costs something, which is the whole point of counting shots:

| | |
|---|---|
| a duck downed | **+2** |
| a shot that hit nothing | **−1** |
| a shot that hit the dog | **−5** |

What is left of the magazine is on the belt in the **bottom-left corner**: one
shell per four shots, a quarter off the leading shell per shot, ten shells for the
forty. It is down there because the ducks are kept out of the bottom of the
picture (`[duck] sky`), so the one gauge you watch while aiming can never cover
the thing you are aiming at — and it is a belt rather than a number because
"nearly out" is something you should be able to see without reading.

The score can go below zero and is shown below zero — clamping it at nothing would
only hide that the round went badly. Counting the ducks alone made every shot free,
and the best strategy was to hold the trigger down.

**The practice round** — `practice.toml`, laid **over** `settings.toml` — is for
handing the gun to someone who has never held one: **ten ducks, slow, one in the
air at a time**, unlimited ammunition, the crosshair on, and nothing sent to the
board. One duck at a time is the only genuinely different mechanic in it (`[duck]
max_alive = 1`); everything else is a smaller number. `--mode practice` starts
on it; **M** on the title screen goes there and back.

**A mode is the round, never the rig.** A mode file may only set `[round]`,
`[duck]`, `[score]` and `[gun] crosshair`; anything else in it is refused out loud
and the base file's value stands. That rule is what makes a mode something you
switch rather than something you launch: the window, the background, the sounds,
the beacon rectangle, the sight-in and the board are the same in every round, so
changing mode between two rounds costs a new world and a re-sized duck — not a
restart. It is also the old safety, written down: the sight-in and the beacon
rectangle were measured on one gun, on one screen, over three evenings, and a mode
that could move them would hand the beginner the one gun in the house that is not
aimed at anything.

**Another round is another file.** Drop a TOML into `modes/` and it appears on the
title screen next time the game starts, named by its own `[mode]` section:

```toml
# modes/sudden.toml
[mode]
name = "SUDDEN DEATH"
note = "one shot, one duck — miss and it is over"

[round]
ducks = 1
ammo = 1
```

**A scored round is shot down the sights.** `[gun] crosshair` decides whether the
crosshair is drawn when the round starts — `"auto"` (the default) means off with a
gun plugged in and on for the mouse, which has no front sight to aim down. **C**
(or **A** on the remote) still flips it mid-round, and a round that had it up at
any point **of the round** is still played and still scored on screen, it is simply
never offered to the leaderboard, and the results screen says which of the two
reasons applies. Turning it back off before the last duck does not buy the record
back.

**The title screen and the countdown are not the round.** The crosshair is free
there and the rule starts with the first duck, so turning it on to check the gun
is tracking and putting it away before the round costs nothing. It used to count
on those two screens as well — three seconds of countdown is enough to read how
far the front sight sits from where the shot lands — but that made the one honest
move look like the cheat, and the round you then shot down the sights was refused
anyway.

The ducks fly in the top `[duck] sky` of the picture (90 % by default) and the
dog keeps to the bottom `[dog] band` (20 %), so neither gets in the other's way.

When the flock is gone you get the result: hits, shots, accuracy, time. **Esc**
during a round ends it there and gets you the same screen — the score so far
counts, and the result says how far the round actually got, so a short round does
not read as a bad one.

Then the game asks **WHO WAS SHOOTING?** — after every round, not only a record
one. **Enter** sends the round to the leaderboard, **Esc** skips it. A name can be
up to **50 characters**, so a name and a surname both fit; the field steps down a
size once it is long, and the boards cut what they show to the width they have.
**The field comes up empty** and Enter on it does nothing: it used to be
pre-filled with the last name typed on this machine, which in a room with a queue
of players is the wrong default — the next player finishes a round, somebody
else's name is already there, and one pull of **A** signs the round to them. An
evening with one shooter is what `--player NAME` is for; everyone else picks
their name off the list below. After that **Space** or the trigger goes back to
the title screen, where another pull starts the next round, and **Q** quits.

**Three kinds of round never reach this screen at all**: a practice round, a round
that had the crosshair up, and a round with not a single shot in it — the last
being what **Esc** on the countdown leaves behind, which used to go to the board
as an empty `0/40` row and one more attempt against somebody's name. The results
screen says which of the three applies.

**Under the field are the names already on the board**, searched as you type:
`ALREADY ON THE BOARD: ЖЕНЯ — 31/40 (12 tries)`. **Tab**, **↓** or **the trigger**
takes the next one, **↑** goes back up the list and off it to what you typed, and
**Enter** — or **A on the remote** — sends whatever is in the field, a name nobody
has used yet included. Trigger to pick, **A** to send: a player standing three
metres away with both hands on the gun signs their round without walking to the
keyboard, which is exactly how the fourth spelling of their name used to get on
the board. A name the board has never seen still needs the keyboard, and that is
what shoot-the-letters entry is for if it ever earns itself. The search
is blind to case and to accents, so `женя`, `ЖЕНЯ` and `Женя` all find the same
row, and it looks across every round size — a name is a name whatever length of
round it was first typed in, which is why the score next to it says `31/40` rather
than a bare number. **Taking a name off the list overwrites nothing**: every
attempt has always been its own row and the board shows the best one per player,
so signing a bad round under your own name moves the `tries` count and leaves your
best exactly where it was. The screen says so in as many words, because the list
looks like it does the opposite. With the board off or unreachable there is no
list and nothing waits for it: the screen is what it was before — type a name,
press Enter.

**The board itself is a screen of its own** and the game draws none of it — no
ranks, no other players, no table, just a line saying the round got there. It is
started on its own, one command for the whole scoreboard:

```bash
cd /Users/evgenychernyak/projects/duckhunt
.venv/bin/python -m leaderboard                                     # server + the tube-TV board
.venv/bin/python main.py --serial /dev/tty.usbserial-0001 \
                         --leaderboard http://localhost:8420
```

`python3 -m leaderboard` is the whole scoreboard in one command: the
server in a thread, and the board opened in the browser. Drag that window to the
second screen and press **F** for fullscreen. It is drawn as a television set: a **4:3** tube in a
plastic cabinet with a speaker grille, two knobs, a power lamp and feet — phosphor
glow, scanlines, an aperture grille, and the bright band rolling slowly down the
picture that a camera sees on a real CRT. Green by default, `--color amber` or
`--color white`, and `?cabinet=graphite` or `?cabinet=wood` for the case (`C` and
`B` cycle them in the page).

There was a second board for a while — the same table drawn in a terminal, for a
Pi with no desktop. Two boards on one set of rows is one board too many to keep
in step, and the Pi does not exist, so it is gone; the server can still be
started on its own (`python3 -m leaderboard.server`) with the page opened from
another machine, which is what you want when the board lives on a screen of its
own.

The server keeps **every** attempt in SQLite and the board shows the best run per
player (`55 PTS · 33 DUCKS · 12 TRIES`), with a running line of records and totals
scrolling along the bottom. A round played with the server down waits in
`pending_runs.jsonl` and lands on the board the next time the game starts. The
permanent switch is `[leaderboard] enabled = true` in `settings.toml`; the whole
thing is described in [`docs/LEADERBOARD.md`](docs/LEADERBOARD.md).

**`scores.json` is no longer written.** It was a top ten on one machine, invisible
to anyone not sitting at it, and it kept being written for a while after nothing
read it back — which is not a fallback, it is a file. A round played with the board
down is not lost either way: it goes to `pending_runs.jsonl` and arrives when the
board is back. An old `scores.json` in a project root is not wasted though —
`python3 -m leaderboard.seed --from-scores` puts those evenings on the board,
scored by the rule they were played under (this repo's own six are on it).

Every shot is heard: the bang of the gun, a quack where it connected, and the dog
laughing at whatever flew off unharmed ([Sound](#sound) below — `[sound] enabled =
false` if the room needs quiet).

The interface is English (as on the NES): `HIT 37  DUCK 64/100  41s  ACC 58%`,
`WHO WAS SHOOTING?`, `ON THE BOARD` — as are the comments in `settings.toml`, the
`--help` output and this documentation.

## Settings

Round length, duck size, their speed and the spawn rate live in `settings.toml` in
the project root — with comments there explaining what each value means:

```toml
[mode]
name = "SCORED"       # what the title screen calls this round
note = "the whole flock, shot down the sights — the one the board keeps"

[round]
ducks = 40            # how many ducks in a round
interval = 0.9        # pause between launches: round length ≈ ducks × interval
ammo = 40             # shots in the magazine; 0 = unlimited (what practice.toml uses)
scored = true         # false = never offered to the leaderboard
speedup = 1.0         # 1.0 — a steady pace; less — the round speeds up towards the end
countdown = 3.0       # seconds from the trigger pull on the title screen to the first duck

[score]
duck = 2              # a duck downed
miss = -1             # a shot that hit nothing
dog = -5              # a shot that hit the dog

[duck]
width = 0.13          # duck width, fraction of screen width (both hitbox and sprite)
height = 0.16
speed_min = 0.30      # speed: fraction of screen per second, random per duck
speed_max = 0.55
sky = 0.90            # ducks keep to the top 90 % — the grass below is the dog's
max_alive = 0         # 0 = as many as the pace launches; 1 = one duck at a time

[dog]
width = 0.12          # dog size, fraction of screen width
band = 0.20           # and the bottom strip it never rises above
```

Everything is in fractions of the screen rather than pixels, so the same numbers
work identically in a window and in fullscreen, on a monitor and on a TV. The game prints the
values in effect on a single line at startup, so you can see which file was picked
up:

```
Settings: 40 ducks, one every 0.9 s (≈36 s round) · 40 shots · size 0.13×0.16 ·
speed 0.3–0.65 · background meadow, fullscreen
```

A practice round says so on the same line: `unlimited ammunition, 1 at a time,
practice (not for the board)`. `[round] points` from before the score had parts is
still read, as `[score] duck`, with a note asking you to move it.

The scene is set there too:

```toml
[scene]
background = "meadow"   # sunset | mountains | clouds | random | none
fullscreen = true       # false — play in a window
display = -1            # which monitor, counting from 0; -1 — let SDL choose
```

Sound is three lines further down:

```toml
[sound]
enabled = true        # false — a silent game
volume = 0.7          # master; `shot`, `quack` and `laugh` are the balance under it
shot_on_hit = true    # false — a hit is the quack alone, the bang means "missed"
```

With more than one monitor, pin `display`: SDL lists them in its own order and
that order changes when one is plugged in or wakes from sleep, so left to chance
the game comes up on the laptop some days and on the TV others — and the IR
beacons are taped to one particular screen. The startup line says which one it
took and what else is connected, so you can read the number off it:

```
display auto of 2 connected [(1470, 956), (1920, 1080)] — using 1920x1080
```

**On macOS the fullscreen window is opened in two steps** — created plain first,
then put into fullscreen once Cocoa has actually shown it. macOS applies a
window's fullscreen state on the window's next *show*, and a window created with
the flag already set never gets one, so the state is quietly dropped and what you
get is an ordinary window the size of the desktop: title bar, menu bar and all.
(Minimising it and bringing it back fixes it by hand — that is the missing show.)
Measured over eight launches each: 0 of 8 came up fullscreen the one-step way, 8
of 8 this way. SDL's own `FULLSCREEN` flag is no help in telling the two apart —
it reads true in both — so the count came from asking the `NSWindow` for its
`styleMask`.

The game also sets `SDL_VIDEO_MAC_FULLSCREEN_SPACES=0`, which is a separate
matter: it makes the fullscreen borderless-and-raised instead of a native macOS
Space, so there is no half-second animation at launch and no extra desktop in
Mission Control. It does *not* fix the bug above on its own. Set the variable
yourself before launching to get Spaces back.

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
python3 main.py --settings hard.toml
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

## Sound

Three sounds, and they are the round's feedback loop: **the gun goes off** on every
trigger pull, **the duck quacks** when it takes the shot, and **the dog laughs**
when one gets away.

That split is deliberate. The bang says the trigger was *read* — with a light gun
three metres from the screen that is the one thing you cannot see for yourself, and
a pull that makes no noise is indistinguishable from a pull the bridge dropped. The
quack is the hit, arriving on the same frame the duck folds up. And the laugh is
timed to the dog coming up out of the grass rather than to the shot that missed: a
duck is only really missed once it leaves the picture, which is the moment the dog
reacts. If you would rather the bang *meant* "missed", `shot_on_hit = false` leaves
a hit with the quack alone.

The game plays whatever is in `assets/sounds/{shot,quack,dog_laugh}.wav`, and there
are two scripts that put files there.

**The originals** — the Zapper, the quack and the dog's laugh off the 1984
cartridge, which is what is in there now. Same provenance as the sprites, and the
same caveat: Nintendo's, fine in your living room, not something to ship.

```bash
python3 tools/import_nes_sounds.py     # assets/source/nes_sounds/ -> assets/sounds/
```

It only does housekeeping: the Zapper is cut to 300 ms and the quack to 115 ms (the
rip leaves the Zapper ringing for 1.6 s, which with rapid fire plays over its own
next shot, and pads the quack past the frame the duck folds up in), everything
is resampled 44.1 → 22.05 kHz to match the mixer, normalised to one peak so a
single `[sound] volume` governs all three, and faded at both ends. The dog's laugh
is left at its full 1.4 s, which is exactly how long the dog stays up out of the
grass — the sound and the sprite end together.

**Or synthesized from nothing**, if you would rather not keep a rip of someone's
cartridge in the folder:

```bash
python3 tools/make_sounds.py           # -> assets/sounds/*.wav, ~40 KB the three
```

That script needs nothing installed (the standard library's `wave` and `math` are
the whole toolbox). The shot is a burst of noise whose filter shuts from 8 kHz down
to 400 Hz in 25 ms — that sweep is the crack — over a low resonance that is the
boom. The two voices are a pulse train through three resonators, the pulses being
the pitch and the resonators the throat, and both move: the quack is one syllable
opening up (F2 sliding 2 kHz → 1.2 kHz while F1 climbs and the pitch falls,
soft-clipped for the rasp), the laugh five breathy chuckles on /i/. The pitches,
formants and decay times are named constants at the top of each function, so
retuning is an edit and a re-run.

Mixed at 22 kHz mono with a 256-frame buffer — about 12 ms of latency, because the
trigger is the one sound in the game you notice arriving late. Missing files, no
audio device, `enabled = false`: the game says so in one line (or nothing at all)
and plays on in silence, the mixer handed back.

## Layout

| Path | Purpose |
|---|---|
| `main.py` | entry point: frontend and input source (mouse / gun / keyboard) |
| `duckhunt/core/models.py` | data: `Duck`, `Facing`, `DuckState` (coordinates 0..1, no sprites) |
| `duckhunt/core/world.py` | **the pure logic core**: `World.update()`, spawning, physics, score |
| `duckhunt/core/config.py` | reading `settings.toml`: duck size and speed, spawn rate |
| `duckhunt/core/calibration.py` | the sight correction: fitting it, `calibration.json`, and applying it |
| `duckhunt/frontends/calibrate.py` | the five-target sighting-in screen (**F1**, `--calibrate`) |
| `settings.toml` | the settings themselves — edit these, no need to touch the code |
| `duckhunt/core/modes.py` | the list of rounds: `practice.toml` and `modes/*.toml`, and what a mode may change |
| `practice.toml` | the practice round, laid **over** `settings.toml` so the gun keeps its sight-in |
| `modes/` | any other round, same rule — it shows up on the title screen on its own |
| `tests/` | `pytest`: the board's queries and routes, the two rounds' arithmetic, the name screen driven headlessly |
| `duckhunt/frontends/pygame_app.py` | **the pixel frontend**: sprites, backgrounds, dog, crosshair |
| `duckhunt/sound.py` | the three sounds: loading them, the `[sound]` volumes, playing one |
| `duckhunt/input/base.py` | the input interface `InputSource` → `AimState(x, y, fire)` |
| `duckhunt/input/serial_gun.py` | input from the ESP32 over USB-Serial (the `x,y,b\n` protocol) |
| `duckhunt/input/udp_gun.py` | the same protocol over UDP — what `fake_gun.py` drives |
| `firmware/esp32_wiimote_bridge/` | **the current firmware**: ESP32-WROOM-32U ↔ Wii Remote → serial |
| `firmware/libs/Wiimote/` | the `Wiimote` library plus the Duck Hunt patch (`enable_ir`) |
| `tools/slice_spritesheet.py` | slicing the NES sprite sheet into `assets/sprites/` |
| `tools/slice_backgrounds.py` | slicing the NES background sheet into `assets/backgrounds/` |
| `tools/import_nes_sounds.py` | the cartridge's own Zapper, quack and dog laugh → `assets/sounds/` |
| `tools/make_sounds.py` | the same three sounds synthesized instead, if you would rather not use the rip |
| `tools/ir_view.py` | drawing what the camera sees (the four blobs, the quad, the aim), logging a test run to `logs/`, `--plan`: where to tape the beacons and how far back to stand, `--bezel`: the `[gun]` numbers for beacons on the bezel |
| `tools/fake_gun.py` | the gun's UDP stream without the gun — testing the aim, the crosshair and the hits from a known aim point |
| `docs/BUILD.md` | BOM, wiring and assembly of the hardware |
| `docs/TODO.md` | what is left to do on the gun and the game, most useful first |
| `leaderboard/server.py` | the leaderboard's HTTP server: six routes over one SQLite file |
| `leaderboard/store.py` | the SQL behind it — every attempt kept, best run per player queried |
| `leaderboard/board.html` | the browser board for the second screen — a tube TV, rolling band and all |
| `leaderboard/__main__.py` | `python3 -m leaderboard`: the server plus the board in a browser, one command |
| `leaderboard/seed.py` | putting an old `scores.json` on the board |
| `duckhunt/net/leaderboard_client.py` | the game's side: post the round, queue it when the board is off |
| `docs/LEADERBOARD.md` | the leaderboard server, its board and how they are run |

**The layers are independent:** `core` knows nothing about rendering or the
hardware — it is `World.update(dt, x, y, fire)` and nothing else — and every
input source speaks the same `x,y,b` gun protocol.

## Building the hardware

The bill of materials, the pinout and a step-by-step guide are in
[`docs/BUILD.md`](docs/BUILD.md) — including the IR beacons, which the current
Wiimote path needs just the same (the remote's camera looks for exactly those four
940 nm dots).

The Wiimote path is the only one now. The two firmware skeletons that used to sit
beside it — a gun around a bare PixArt camera, and an ESP32-S3-CAM finding the
monitor's bezel without IR LEDs at all — are gone: the remote plays, so there is
nothing left for a fallback to fall back from. Whatever replaces it later speaks
the same `x,y,b`, and the game will not notice.

## References

- **GUN4IR** — the reference IR light gun (schematics, firmware, enclosures).
- [ddean-blip/esp32-lightgun](https://github.com/ddean-blip/esp32-lightgun) — ESP32-S3 + camera.
- [henning2323/IR_LightGun](https://github.com/henning2323/IR_LightGun) — a DIY IR gun.
- [takeru/Wiimote](https://github.com/takeru/Wiimote) — Wii Remote over Bluetooth Classic on the ESP32 (vendored in `firmware/libs/`, plus our IR patch).
- IR camera: DFRobot "Positioning IR Camera" (SEN0158, PixArt PAJ7025 — as in the Wiimote).
- IR beacons: 4× **940 nm** LEDs at the screen corners, each a standalone module on its
  own 2×AAA (3 V, 100–120 Ω) — no wiring across the screen; frost the tips for a wide angle.
