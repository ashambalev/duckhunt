#!/usr/bin/env python3
"""A gun that does not exist — the UDP aim stream, without any hardware.

`input/udp_gun.py` listens for the same `x,y,b` lines the bridge sends, so
sending them from here drives the crosshair exactly as the real gun does. That is
enough to test everything on the Mac side of the aim: the `[gun]` rectangle, the
letterbox conversion, the crosshair, the hitbox — with no remote paired, no LEDs
taped up, and a known aim point instead of a shaking hand.

Two terminals. The game:

    .venv/bin/python main.py --pygame --udp

and then the gun:

    .venv/bin/python tools/fake_gun.py            # walk TL TR BR BL C, 2 s each
    .venv/bin/python tools/fake_gun.py --fire     # ... and shoot at each
    .venv/bin/python tools/fake_gun.py --sweep --fire   # a slow circle, shooting
    .venv/bin/python tools/fake_gun.py --point 0.15 0.06    # one fixed aim point
    .venv/bin/python tools/fake_gun.py --blind    # no beacons in view (-1,-1)

What to expect, per `[gun] frame` in settings.toml — the numbers this sends are
fractions of the BEACON RECTANGLE, so the two settings differ in where the
rectangle is, not in what arrives:

  frame = "picture"   0,0 lands on the corner of the PICTURE (the grass/sky
                      rectangle), because that is where the beacons are. Every
                      corner should be reachable and nothing should clamp.
  frame = "display"   0,0 lands on the corner of the DISPLAY, which is inside a
                      black bar, so the crosshair clamps to the picture's corner
                      and stops. To hit the picture's corner exactly, aim at the
                      bar's width instead: the game prints the offset at startup
                      (`picture 1792x1281 px at 384,80 of 2560x1440` -> aim at
                      384/2560 = 0.15, 80/1440 = 0.06).

That difference is the test: the same `--point 0.15 0.06` should sit in the
picture's corner with "display" and 15% inside the picture with "picture".
"""

from __future__ import annotations

import argparse
import math
import socket
import time

DEFAULT_PORT = 4210
CORNERS = [("TL", 0.0, 0.0), ("TR", 1.0, 0.0), ("BR", 1.0, 1.0),
           ("BL", 0.0, 1.0), ("C", 0.5, 0.5)]
RATE = 100.0        # reports per second, near enough to the bridge's own


def send(sock, addr, x, y, fire=False):
    """One report, in the bridge's format: 0..1000 per axis, -1,-1 = no beacons."""
    xi = -1 if x < 0 else round(1000 * min(1.0, max(0.0, x)))
    yi = -1 if y < 0 else round(1000 * min(1.0, max(0.0, y)))
    sock.sendto(f"{xi},{yi},{1 if fire else 0}\n".encode(), addr)


def hold(sock, addr, x, y, seconds, fire_at=None):
    """Aim at one point for `seconds`, optionally pulling the trigger once.

    The trigger is a rising edge to the game, so it has to go down and come back
    up — holding it down for the whole stretch would fire exactly one shot and
    then look stuck.
    """
    frames = max(1, int(seconds * RATE))
    fire_frame = None if fire_at is None else int(fire_at * RATE)
    for i in range(frames):
        send(sock, addr, x, y, fire=(i == fire_frame))
        time.sleep(1.0 / RATE)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1", help="where the game listens")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--point", nargs=2, type=float, metavar=("X", "Y"),
                    help="hold one aim point, 0..1 of the beacon rectangle")
    ap.add_argument("--sweep", action="store_true",
                    help="a slow circle instead of the five points")
    ap.add_argument("--blind", action="store_true",
                    help="report no beacons in view (-1,-1) — the game should "
                         "freeze the crosshair where it was, not jump")
    ap.add_argument("--fire", action="store_true",
                    help="pull the trigger once at each point")
    ap.add_argument("--hold", type=float, default=2.0, metavar="S",
                    help="seconds per point (default 2)")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    addr = (args.host, args.port)
    print(f"aiming at {args.host}:{args.port} — Ctrl-C to stop")

    try:
        if args.blind:
            print("  no beacons in view (-1,-1)")
            while True:
                hold(sock, addr, -1, -1, 1.0)
        elif args.point:
            x, y = args.point
            print(f"  holding {x:.3f},{y:.3f}")
            while True:
                hold(sock, addr, x, y, 1.0, fire_at=0.5 if args.fire else None)
        elif args.sweep:
            print("  sweeping a circle around the centre"
                  + (", shooting every 1.5 s" if args.fire else ""))
            t, i = 0.0, 0
            while True:
                x = 0.5 + 0.45 * math.cos(t)
                y = 0.5 + 0.45 * math.sin(t)
                # --fire has to work here too: the title screen waits for a
                # trigger pull, so a sweep that never pulls one never gets into
                # the round at all.
                shot = args.fire and i % int(1.5 * RATE) == 0
                send(sock, addr, x, y, fire=shot)
                t += 2 * math.pi / (6.0 * RATE)      # one lap every 6 s
                i += 1
                time.sleep(1.0 / RATE)
        else:
            while True:
                for name, x, y in CORNERS:
                    print(f"  {name}: {x:.1f},{y:.1f}")
                    hold(sock, addr, x, y, args.hold,
                         fire_at=args.hold / 2 if args.fire else None)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
