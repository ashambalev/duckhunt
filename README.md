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

python3 main.py --pygame                                     # aim with the mouse (development)
python3 main.py --pygame --serial /dev/tty.usbserial-0001    # aim with the light gun
```

**Playing with the light gun**, start to finish:

```bash
ls /dev/tty.usbserial*                                       # find the bridge (usually -0001)
python3 main.py --pygame --serial /dev/tty.usbserial-0001    # play
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
it knows. (**`?`** prints everything the bridge is set to, **`k`** toggles the
link keep-alive and **`a`** steps through the
[AFH channel plans](#telling-the-radio-which-channels-to-skip-a) — off unless
asked for.)

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
.venv/bin/python tools/ir_view.py --plan --diagonal 27   # where to tape the beacons
.venv/bin/python tools/ir_view.py --bezel 5 5 10 5 --diagonal 27   # ... on the bezel
```

**Testing the aim without any hardware.** `tools/fake_gun.py` sends the same
`x,y,b` stream over UDP that the bridge does, so the whole Mac side of the aim —
the `[gun]` rectangle, the letterbox conversion, the crosshair, the hitbox — can
be tested with a known aim point instead of a shaking hand. Two terminals:

```bash
.venv/bin/python main.py --pygame --udp           # the game, listening
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
so far still offered to the table, **B** cycles the background, **Tab** shows
where the IR beacons go, **G** puts the gun's own numbers on the HUD (report
rate, how clumped the reports are, how often the beacons are out of view, how old
the aim is — "it feels laggy" has three different causes and these tell them
apart), **L** steps the crosshair's lead through 0 / 20 / 35 / 50 ms live and
puts that HUD up while it does (the difference is a feel, and a feel does not
survive the minute it takes to restart the game and get the remote back),
**F1** sights the gun in on five targets (from the title screen or the score
table) and **F2** turns that correction on and off so it can be judged rather
than assumed, **Space** or the trigger leaves the results screen, **Q** quits.
`--align` starts with those
targets up, and what it draws follows `[gun] frame`: with `"picture"`, brackets in
the picture's four corners to tape a bundle into; with `"display"`, the letterbox
bars go pale grey so the screen's own edge is visible and the brackets sit in the
screen's corners, for beacons on the bezel — plus a thin blue set on the
picture's corners to aim at and check the numbers.

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
   measure, `--align` puts targets there, and it plays the same on any screen), or
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
width of the beacon rectangle, so `[scene] scale` shrinks the picture (and the
rectangle with it) to bring a TV within reach of a sofa. On fewer than four dots it drops back to the old centroid guess: the
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
.venv/bin/python main.py --pygame --serial /dev/tty.usbserial-0001 --calibrate
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
since. Sighting in belongs to `--pygame`: the ASCII frontend has no letterboxed
picture to measure against.

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

The rest is hidden rather than removed: `[gun] lead` draws the crosshair where
the aim is *going* instead of where it was last heard from, advancing it along
its own velocity by `lead` seconds plus however stale the last report already
is, capped at `[gun] lead_max`. The velocity is fitted over the last 100 ms of
reports rather than smoothed frame by frame (an exponential average lags by
~1.9 frames — 31 ms of the 40 it is meant to cancel), and a report that never
arrived is not a sample, so a stalled link leaves the crosshair coasting instead
of dragging it to a stop. Replayed against a 1.5-playfield/s sweep with 45 ms of
link delay, the crosshair sits 5.9 % of the screen behind the barrel with `lead
= 0` and 3.4 % at 0.02.

Then it was played with the gun, which changed the answer. Lead settings of
0.035 and 0.05 visibly **overshot** on a sweep that stops — and the culprit was
not mostly the lead but the gap between `lead` and `lead_max`. That run measured
~1.5 stalls longer than 50 ms per second, and each one lets the lead grow
towards the ceiling: at `lead = 0.02, lead_max = 0.06` a stall tripled it,
several times a second, right while the barrel was moving. Simulated against a
decelerating sweep with those stalls in it, how far the crosshair sails past the
point the barrel stopped at:

| `lead` / `lead_max` | past the stop | mean error |
|---|---|---|
| 0 / 0 | 0.4 % | 4.0 % |
| 0.02 / 0.02 | 1.8 % | 2.9 % |
| 0.02 / 0.035 | 3.2 % | 2.5 % |
| **0.035 / 0.035** | **3.2 %** | **2.2 %** |
| 0.035 / 0.06 | 5.5 % | 2.1 % |

Tying the two together is what settled it. With `lead_max` following `lead`,
and on a link that had stopped stalling — 0.2 stalls a second against the
earlier 1.5, after the receiver was moved — two full rounds back to back, every
duck downed in both, picked the value by themselves:

| `lead` | ducks | shots | hit rate |
|---|---|---|---|
| 0.02 | 118 | 254 | 46 % |
| **0.035** | 40 | 55 | **73 %** |
| 0.05 | 40 | 67 | 60 % |

The 0.05 round is the *later* one, so this is not practice talking. It ships at
`lead = lead_max = 0.035`. Raising `lead_max` above `lead` only pays on a link
clean enough that coasting through a stall is worth the occasional overshoot —
and even on this one it buys 0.1 % of mean error for 2.3 % more overshoot, so
no. A dropout longer than `lead_max` gives the guess back over 0.2 s, so a dead
link parks the crosshair on the last thing the gun actually said rather than
8 % of the screen away from it.

Two measured levers are left unused, for a session with the gun rather than the
day before one. Fitting the velocity over 60 ms instead of 100 takes the
overshoot from 1.8 % to 1.5 % for 8 % more jitter; fitting a *parabola* instead
of a straight line — the slope of a line over a window is the velocity in the
middle of that window, i.e. 50 ms stale, which is exactly wrong while the barrel
is slowing — takes it to 1.4 % with the mean error down to 2.7 %, at the cost of
roughly a third more noise in the velocity. Both are in `AimLead`.

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
  start. Try **HOME** on the remote (or **K**) as well — it turns on the
  bridge's keep-alive, which is there to stop a quiet link dropping into sniff
  mode.
- **If the signal is good and the rate sags anyway**, the band is crowded rather
  than the link long, and there is a lever for exactly that — below.

#### Telling the radio which channels to skip (`a`)

Adaptive hopping already drops channels the controller measures as bad, but it
has to collide with them first and re-test them afterwards, and every one of
those collisions is a retransmission — the hole in the stream that feels like
lag. Where the interference is known in advance and sits in the same place all
day, the host can say so up front:
`HCI_Set_AFH_Host_Channel_Classification` is in the vendored library, and **`a`
on the serial port steps through a table of plans** and sends the one it lands
on:

```
off, every channel back in play   79 of 79 channels
Wi-Fi 1                           57      (2402-2423 MHz dropped)
Wi-Fi 6                           56      (2426-2448)
Wi-Fi 11                          56      (2451-2473)
Wi-Fi 1 + 6                       34
Wi-Fi 6 + 11                      33
Wi-Fi 1 + 6 + 11, narrow          28      (the middle 17 MHz of each)
```

**It is off, and nothing sends it by itself.** Nothing runs at boot, on a
connection or on a timer; the game sends `o` and `k`, `tools/ir_view.py` sends
`d`, `s`, `x` and `y`, and none of them is `a`. Until it is typed, the radio
behaves exactly as it does today. `?` says which plan is selected and whether
anything was ever sent.

Three things to know before using it:

- **It only bites while the bridge is the master** of the piconet — that is, when
  the bridge placed the call (`Remote connected (the bridge called it)`). If the
  remote called in, it owns the hop sequence and the map goes no further than our
  own radio; the bridge says so when you apply a plan. Restarting the bridge and
  pressing nothing on the remote is what gets the call placed from this side.
- **Blocking is not boosting.** The traffic moves into whatever is left, so too
  wide a plan makes things worse. Start with the one Wi-Fi channel the hall is
  actually loudest on.
- **Fewer than 20 channels left is refused** by the radio itself (HCI status
  0x12) — and by the sketch before it gets that far, which is why blocking all of
  1, 6 and 11 is offered only in its narrow form. A refused map changes nothing.

**The ESP32's controller does implement it** — measured, with the firmware
flashed and the port watched: `a` produced `# afh: Wi-Fi 1 - 57 of 79 channels
left in play` followed by `# afh: the radio took the channel map (status 0x00)`,
and again for the next plan. Boot printed nothing about AFH at all, and a
reboot — which is what opening the serial port does — puts it back to plan 0
with nothing sent, so a plan cannot be left switched on by accident. What is
still unmeasured is whether it *helps*: that needs a crowded band and an A/B
against the report rate, which is a thing to do next to a busy access point
rather than at a desk.

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

- [ ] **Does the AFH channel map help in a crowded hall? The controller takes
      it — measured.** `a` on the serial port answered `# afh: the radio took
      the channel map (status 0x00)` for two plans in a row, boot said nothing
      about AFH, and a reboot returns it to plan 0 with nothing sent. So the
      command works and cannot be left on by accident. Whether it *helps* is the
      part still open, and it cannot be answered at a quiet desk: it wants a
      busy access point, an A/B on the report rate with the plan on and off, and
      a remote the bridge itself called (`the bridge called it`) — as a slave it
      owns no hop sequence and the map goes nowhere.

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

The ducks fly in the top `[duck] sky` of the picture (90 % by default) and the
dog keeps to the bottom `[dog] band` (20 %), so neither gets in the other's way.

When the flock is gone you get the result: hits, shots, accuracy, time. **Esc**
during a round ends it there and gets you the same screen — the score so far
counts, and the result says how far the round actually got, so a short round does
not read as a bad one. If the result made the top ten, the game asks for a name
(**Enter** saves, **Esc** skips), and the round goes into `scores.json` in the
project root. After that **Space** or the trigger goes back to the title screen,
where another pull starts the next round, and **Q** quits. The table is also
printed to the terminal on exit. On a tied score, whoever spent fewer shots ranks
higher.

That table is local to this Mac and keeps ten rounds. Moving it onto a screen of
its own — a separate server storing every attempt and showing the best result per
player, console style with a running line — is planned in
[`docs/LEADERBOARD.md`](docs/LEADERBOARD.md); nothing of it is built yet.

Every shot is heard: the bang of the gun, a quack where it connected, and the dog
laughing at whatever flew off unharmed ([Sound](#sound) below — `[sound] enabled =
false` if the room needs quiet).

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
countdown = 3.0       # seconds from the trigger pull on the title screen to the first duck

[duck]
width = 0.13          # duck width, fraction of screen width (both hitbox and sprite)
height = 0.16
speed_min = 0.30      # speed: fraction of screen per second, random per duck
speed_max = 0.55
sky = 0.90            # ducks keep to the top 90 % — the grass below is the dog's

[dog]
width = 0.12          # dog size, fraction of screen width
band = 0.20           # and the bottom strip it never rises above
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
| `duckhunt/core/scores.py` | the high-score table (`scores.json`) |
| `duckhunt/core/calibration.py` | the sight correction: fitting it, `calibration.json`, and applying it |
| `duckhunt/frontends/calibrate.py` | the five-target sighting-in screen (**F1**, `--calibrate`) |
| `settings.toml` | the settings themselves — edit these, no need to touch the code |
| `duckhunt/frontends/pygame_app.py` | **the pixel frontend**: sprites, backgrounds, dog, crosshair |
| `duckhunt/frontends/terminal.py` | the ASCII frontend (the original prototype) |
| `duckhunt/sound.py` | the three sounds: loading them, the `[sound]` volumes, playing one |
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
| `tools/import_nes_sounds.py` | the cartridge's own Zapper, quack and dog laugh → `assets/sounds/` |
| `tools/make_sounds.py` | the same three sounds synthesized instead, if you would rather not use the rip |
| `tools/wiimote_monitor.py` | watching the raw `x,y,b` stream while debugging the gun |
| `tools/ir_view.py` | drawing what the camera sees (the four blobs, the quad, the aim), logging a test run to `logs/`, `--plan`: where to tape the beacons and how far back to stand, `--bezel`: the `[gun]` numbers for beacons on the bezel |
| `tools/fake_gun.py` | the gun's UDP stream without the gun — testing the aim, the crosshair and the hits from a known aim point |
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
