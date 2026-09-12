#!/usr/bin/env python3
"""Live monitor for the Wiimote->ESP32 bridge (for debugging the hardware).

It opens the ESP32's serial port and shows, in real time:
  - the firmware's status lines ("# ..."): pairing, IR enabling;
  - whether an IR dot is visible and its coordinates (updated in place);
  - how many of the four corner beacons the camera has in view right now — four
    means the firmware is solving the real homography, fewer means it has fallen
    back to the coarse centroid aim;
  - whether the trigger (the B button) is pressed.

Running it:
    .venv/bin/python tools/wiimote_monitor.py                 # the default port
    .venv/bin/python tools/wiimote_monitor.py /dev/tty.usbserial-0001

How to use it:
  1. Start the monitor — the ESP32 will reboot (that is fine) and you will see
     "BT init".
  2. Press 1 and 2 together on the Wii Remote. Wait for "Remote connected" and
     "IR camera enabled". A remote the bridge has already used is paged by
     address first, so it may connect before you press anything.
  3. Point the remote at a TV remote control (and HOLD one of its buttons) — the
     IR line should show coordinates instead of "no dot". Pull the trigger and
     you will see FIRE.
  4. With the four corner beacons switched on, point the remote at the screen
     from where you would actually stand: "dots=4" is what the homography needs.
     If it keeps dropping to 3, a corner is outside the camera's narrow (~33°)
     view — step further back.
  Ctrl-C quits.
"""

import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbserial-0001"
BAUD = 115200


def main() -> None:
    s = serial.Serial(PORT, BAUD, timeout=0.2)
    s.setDTR(False)
    s.setRTS(False)
    print(f"Listening on {PORT} @ {BAUD}. Press 1+2 on the remote. Ctrl-C quits.\n")

    seen_point = False
    last_status = time.time()
    npts = 0
    dots = ""            # the firmware's twice-a-second beacon report
    try:
        while True:
            raw = s.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", "ignore").strip()
            if not line:
                continue

            if line.startswith("#") or (not line[0].isdigit() and line[0] != "-"):
                # a firmware status line, or bootloader noise
                if line.startswith("# dots"):
                    # folded into the live line below instead of scrolling past
                    dots = line[2:]
                elif line.startswith("#"):
                    print("  " + line, flush=True)
                continue

            # an x,y,b data line
            parts = line.split(",")
            if len(parts) != 3:
                continue
            try:
                x, y, b = int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                continue

            fire = "🔴FIRE" if (b & 1) else "     "
            if x < 0:
                msg = f"IR: no dot            {fire}  {dots}"
            else:
                npts += 1
                if not seen_point:
                    seen_point = True
                    print(f"\n✅ FIRST DOT ACQUIRED: x={x} y={y}\n", flush=True)
                msg = f"IR: x={x:4d} y={y:4d}   {fire}  {dots}"

            # refresh the line in place no more than ~10 times a second
            if time.time() - last_status > 0.1:
                last_status = time.time()
                print("\r" + msg + " " * 8, end="", flush=True)
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        s.close()


if __name__ == "__main__":
    main()
