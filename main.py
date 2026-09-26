"""Duck Hunt entry point.

    python3 main.py --pygame                                    # pixel art, aim with the mouse
    python3 main.py --pygame --serial /dev/tty.usbserial-0001   # pixel art + LIGHT GUN
    python3 main.py                                             # the old ASCII frontend, keyboard

The scoreboard is not in here: it is two processes of its own, on a screen of its
own (docs/LEADERBOARD.md). The game asks who was shooting once the round is over
and posts the row; what the board makes of it is shown there, not here.

    python3 -m leaderboard.server                               # :8420 + leaderboard.db
    python3 -m leaderboard.display --url http://localhost:8420  # the board itself

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
import os
import sys
from dataclasses import replace

from blessed import Terminal

from duckhunt.core import player, scores
from duckhunt.core.config import LeaderboardSettings
from duckhunt.core.config import load as load_settings
from duckhunt.frontends.terminal import TerminalFrontend
from duckhunt.input.base import AimState, InputSource
from duckhunt.input.keyboard import KeyboardInput
from duckhunt.net.leaderboard_client import LeaderboardClient
from duckhunt.net.leaderboard_client import payload as board_payload

LEADERBOARD_ENV = "DUCKHUNT_LEADERBOARD"


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
    ap.add_argument("--player", metavar="NAME",
                    help="who is shooting: skips the question after the round, "
                         "for an evening of rounds without typing")
    ap.add_argument("--leaderboard", metavar="URL",
                    help="send every round to the scoreboard at URL (overrides "
                         "[leaderboard] in settings.toml, and DUCKHUNT_LEADERBOARD)")
    ap.add_argument("--no-leaderboard", dest="board", action="store_false",
                    help="do not send this session's rounds anywhere")
    args = ap.parse_args()

    settings = load_settings(args.settings)
    settings = with_leaderboard(settings, args)
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

    source_name = ("udp" if args.udp else "wiimote" if args.wiimote
                   else "serial" if args.serial else None)

    # ---- pixel frontend (pygame) ----
    if args.pygame:
        from duckhunt.frontends.pygame_app import PygameFrontend
        game = PygameFrontend(settings, align=args.align, log_gun=args.log_gun,
                              calibrate=args.calibrate,
                              use_calibration=args.calibration,
                              player_name=args.player or "",
                              source_name=source_name or "mouse")
        try:
            game.run(gun)          # gun=None -> aim with the mouse
        finally:
            if gun is not None:
                gun.close()
        # the name was asked on the results screen and the row was sent from
        # there — nothing left to do but say how the round went
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
    record_round(game.world, settings, args.player,
                 source_name or "keyboard")


def with_leaderboard(settings, args):
    """Where the board is, deciding between the three ways of saying it.

    In order: `--leaderboard URL` beats `DUCKHUNT_LEADERBOARD` in the environment,
    which beats `[leaderboard]` in settings.toml. `--no-leaderboard` turns it off
    for one session whatever the file says.
    """
    lb = settings.leaderboard
    url = args.leaderboard or os.environ.get(LEADERBOARD_ENV)
    if url:
        lb = LeaderboardSettings(**{**lb.__dict__, "url": url, "enabled": True})
    if not args.board:
        lb = LeaderboardSettings(**{**lb.__dict__, "enabled": False})
    return replace(settings, leaderboard=lb)


def record_round(w, settings, name: str | None, source_name: str) -> None:
    """Ask who was shooting, keep the round, send the row. The ASCII path's turn.

    The pixel frontend asks this on its own results screen; here the round ends
    with the terminal back to normal, so it is a plain prompt. Either way the name
    is asked AFTER the round and the row goes to the board — which is a process on
    a screen of its own, and nothing of it is printed here.
    """
    if w.shots == 0 and w.hits == 0 and not w.stopped:
        return                        # nothing happened; nothing to sign
    remembered = player.load()
    if not name:
        prompt = (f"Who was shooting? [{remembered}] " if remembered
                  else "Who was shooting? (Enter to skip) ")
        try:
            name = input(prompt).strip() or remembered
        except (EOFError, KeyboardInterrupt):
            name = ""
    if not name:
        print("not recorded.")
        return
    name = name[:scores.NAME_MAX]
    player.save(name)
    if scores.qualifies(scores.load(), w.hits, w.shots):
        scores.add(scores.from_world(w, name))
    board = LeaderboardClient(settings.leaderboard)
    if not board.enabled:
        return
    board.submit(board_payload(w, name, settings.leaderboard.client_id, source_name))
    board.close()
    print({"sent": f"{name}: on the board.",
           "queued": f"{name}: saved locally — it will reach the board on the "
                     f"next launch."}.get(board.state, ""))


def print_result(w) -> None:
    """Print the round result. The board itself lives on its own screen."""
    print(f"\nResult: {w.hits} of {w.total} ducks "
          f"({w.accuracy:.0f}% accuracy, {w.shots} shots). Bye! 🦆")


if __name__ == "__main__":
    main()
