"""Duck Hunt entry point.

    python3 main.py --pygame                                    # pixel art, aim with the mouse
    python3 main.py --pygame --serial /dev/tty.usbserial-0001   # pixel art + LIGHT GUN
    python3 main.py                                             # the old ASCII frontend, keyboard

Playing with the light gun: if the remote is already paired with the bridge it just
works — opening the port no longer reboots the ESP32 (see input/serial_gun.py). If it
is not paired, press the red SYNC button on the Wii Remote once the board is up (it
prints "# BT init..."); pairing takes well under a second. A SYNC pressed while the
board is still booting is not heard — that is what "the remote won't connect" looks
like.

To list the ESP32 ports on a Mac:  ls /dev/tty.usbserial*  or  ls /dev/tty.usbmodem*
"""

from __future__ import annotations

import argparse
import sys

from blessed import Terminal

from duckhunt.core import scores
from duckhunt.core.config import load as load_settings
from duckhunt.frontends.terminal import TerminalFrontend
from duckhunt.input.base import AimState, InputSource
from duckhunt.input.keyboard import KeyboardInput


class GunWithKeyboardQuit(InputSource):
    """The gun supplies aim/fire; quitting with 'q' stays on the keyboard."""

    def __init__(self, gun: InputSource, term: Terminal):
        self._gun = gun
        self._term = term

    def poll(self) -> AimState:
        state = self._gun.poll()
        key = self._term.inkey(timeout=0)
        if key and (str(key).lower() == "q" or key.name == "KEY_ESCAPE"):
            state.quit = True
        return state

    def close(self) -> None:
        self._gun.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Duck Hunt — NES pixel art + light gun")
    ap.add_argument("--serial", metavar="PORT",
                    help="light gun on the ESP32 bridge, e.g. /dev/tty.usbserial-0001 "
                         "(press SYNC on the remote if it is not paired yet)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--wiimote", action="store_true",
                    help="read the Wii Remote directly over Bluetooth (needs hidapi + WiimotePair)")
    ap.add_argument("--udp", nargs="?", const=4210, type=int, metavar="PORT",
                    help="receive data from the ESP32 bridge over Wi-Fi/UDP (Path B, port 4210)")
    ap.add_argument("--pygame", action="store_true",
                    help="graphical pixel mode (ducks + dog) instead of ASCII")
    ap.add_argument("--log-gun", action="store_true",
                    help="write the gun stream's own numbers to logs/gun_<time>."
                         "jsonl once a second (rate, clumping, dropouts, fps) — "
                         "read it back with tools/ir_view.py --trend")
    ap.add_argument("--calibrate", action="store_true",
                    help="sight the gun in first: five round targets, aimed "
                         "down the sights with the crosshair off, and the miss "
                         "is corrected from then on (F1 in game does the same). "
                         "Saved in calibration.json")
    ap.add_argument("--no-calibration", dest="calibration", action="store_false",
                    help="play on the gun's raw numbers, ignoring "
                         "calibration.json (F2 toggles it in game)")
    ap.add_argument("--align", action="store_true",
                    help="start with targets in the picture's corners, to tape the "
                         "four IR beacons to (TAB toggles them in game)")
    ap.add_argument("--settings", metavar="FILE",
                    help="settings file (settings.toml in the project root by default)")
    args = ap.parse_args()

    settings = load_settings(args.settings)
    print(f"Settings: {settings.summary()}\n(change them in settings.toml)")

    # the gun input source (serial/udp), shared by both frontends
    gun = None
    if args.udp:
        from duckhunt.input.udp_gun import UdpGunInput
        gun = UdpGunInput(args.udp)
    elif args.wiimote:
        from duckhunt.input.wiimote import WiimoteInput
        gun = WiimoteInput()
    elif args.serial:
        from duckhunt.input.serial_gun import SerialGunInput
        gun = SerialGunInput(args.serial, args.baud)

    # ---- pixel frontend (pygame) ----
    if args.pygame:
        from duckhunt.frontends.pygame_app import PygameFrontend
        game = PygameFrontend(settings, align=args.align, log_gun=args.log_gun,
                              calibrate=args.calibrate,
                              use_calibration=args.calibration)
        try:
            game.run(gun)          # gun=None -> aim with the mouse
        finally:
            if gun is not None:
                gun.close()
        print_result(game.world)
        return

    # ---- terminal (ASCII) frontend ----
    term = Terminal()
    if args.calibrate:
        # The correction is measured in fractions of the PIXEL frontend's
        # letterboxed picture, and the ASCII one has no such picture to measure
        # against — so sighting in belongs to --pygame. Said out loud rather
        # than silently ignored.
        print("--calibrate needs --pygame: the sighting-in screen draws its "
              "targets in the pixel picture", file=sys.stderr)
    if gun is not None:
        source: InputSource = GunWithKeyboardQuit(gun, term)
    else:
        source = KeyboardInput(term)

    game = TerminalFrontend(term, settings)
    try:
        game.run(source)
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
    print_result(game.world)


def print_result(w) -> None:
    """Print the round result and the high-score table to the terminal."""
    print(f"\nResult: {w.hits} of {w.total} ducks "
          f"({w.accuracy:.0f}% accuracy, {w.shots} shots). Bye! 🦆")
    table = scores.load()
    if table:
        print("\nHigh scores:")
        for i, e in enumerate(table, 1):
            print(f"  {i:>2}. {e.name[:12]:<12} {e.hits:>3} ducks  "
                  f"{e.accuracy:>3.0f}%  {e.date}")


if __name__ == "__main__":
    main()
