"""Duck Hunt entry point.

    python3 main.py --pygame                                    # pixel art, aim with the mouse
    python3 main.py --pygame --serial /dev/tty.usbserial-0001   # pixel art + LIGHT GUN
    python3 main.py                                             # the old ASCII frontend, keyboard

The round is chosen IN THE GAME, on the title screen: M, or A on the remote,
cycles the modes — the scored round, practice.toml, and anything dropped into
modes/. `--mode NAME` (and its shortcut `--practice`) only say which one the
evening opens on, so handing the gun to a first-timer is not a restart. What a
mode may change is fenced in core/config.py, and that fence is what makes it
switchable: the window, the sight-in, the beacons and the board are the same
round to round.

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

from duckhunt.core import modes as modes_core
from duckhunt.core.config import LeaderboardSettings
from duckhunt.frontends.terminal import TerminalFrontend
from duckhunt.input.base import AimState, InputSource
from duckhunt.input.keyboard import KeyboardInput

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
    ap.add_argument("--mode", metavar="NAME",
                    help="which round to START on — the pixel frontend's title "
                         "screen switches them with M (or A on the remote), so "
                         "this is only where the evening begins. The names are "
                         "printed at startup; a mode is a short TOML file laid "
                         "over the settings (practice.toml, or modes/*.toml)")
    ap.add_argument("--practice", action="store_true",
                    help="start on the practice round — ten slow ducks, one in "
                         "the air at a time, the crosshair on and nothing sent "
                         "to the board, for handing the gun to someone who has "
                         "never held one. The same as --mode practice")
    ap.add_argument("--player", metavar="NAME",
                    help="who is shooting: pre-fills the question the pixel "
                         "frontend asks after the round, for an evening of "
                         "rounds without typing. Nothing else does — the field "
                         "comes up empty, so one player's round is never one "
                         "keypress away from being signed to the player before "
                         "them")
    ap.add_argument("--leaderboard", metavar="URL",
                    help="send every round to the scoreboard at URL (overrides "
                         "[leaderboard] in settings.toml, and DUCKHUNT_LEADERBOARD)")
    ap.add_argument("--no-leaderboard", dest="board", action="store_false",
                    help="do not send this session's rounds anywhere")
    args = ap.parse_args()

    # Every round there is to play, not just the one asked for: the title screen
    # switches between them, so they are all resolved before the window opens —
    # a mode is only allowed to change the round (see core/modes.py), which is
    # exactly what makes that safe to do mid-evening.
    all_modes = [modes_core.with_settings(m, with_leaderboard(m.settings, args))
                 for m in modes_core.load_all(args.settings)]
    start = starting_mode(all_modes, args)
    settings = all_modes[start].settings
    print(f"{all_modes[start].name}: {settings.summary()}"
          f"\n(change them in settings.toml)")
    if len(all_modes) > 1:
        how = ("M in game, or A on the remote from the title screen"
               if args.pygame else
               "--mode NAME picks one; the ASCII frontend has no title screen "
               "to switch on")
        print(f"Modes: {' · '.join(m.name for m in all_modes)} — {how}")

    # the gun input source (serial/udp), shared by both frontends
    gun = None
    if args.udp:
        from duckhunt.input.udp_gun import UdpGunInput
        gun = UdpGunInput(args.udp)
    elif args.serial:
        from duckhunt.input.serial_gun import SerialGunInput
        gun = SerialGunInput(args.serial, args.baud)

    source_name = ("udp" if args.udp else "serial" if args.serial else None)

    # ---- pixel frontend (pygame) ----
    if args.pygame:
        from duckhunt.frontends.pygame_app import PygameFrontend
        game = PygameFrontend(settings, align=args.align, log_gun=args.log_gun,
                              calibrate=args.calibrate,
                              use_calibration=args.calibration,
                              player_name=args.player or "",
                              source_name=source_name or "mouse",
                              modes=all_modes, mode=start)
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
    # A keyboard round is not a record and the board is never told about one: this
    # frontend draws a `+` at the aim point and the arrow keys move it, so the mark
    # IS the aiming, the way the crosshair is for the mouse. There is nothing to ask
    # a name for, so it is not asked — see leaderboard_client.refusal(). Said before
    # the result rather than after it, because the result ends with goodbye.
    print("\nA keyboard round does not go to the board: the `+` is the aiming, and\n"
          "the board measures one thing — the gun, shot down its sights. Play with\n"
          "--pygame --serial PORT for that.")
    print_result(game.world)


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


def starting_mode(all_modes, args) -> int:
    """Which mode the game opens on — and a refusal rather than a fallback.

    A `--mode` nobody has written is an error, not a shrug. `--practice` is the
    case that makes it one: falling back to the base settings would be the exact
    inverse of what the flag promises — forty ducks at full speed, a magazine to
    run out of, and the round posted as a record — handed to somebody who has
    never held the gun.
    """
    wanted = args.mode or ("practice" if args.practice else None)
    if not wanted:
        return 0
    found = modes_core.find(all_modes, wanted)
    if found < 0:
        have = ", ".join(m.name for m in all_modes)
        sys.exit(f"no mode called {wanted!r}, so there is nothing to play. "
                 f"There is: {have}. A mode is a TOML file laid over the "
                 f"settings — {modes_core.PRACTICE_NAME} in the project root, "
                 f"or {modes_core.MODES_DIR}/*.toml")
    return found


def print_result(w) -> None:
    """Print the round result. The board itself lives on its own screen."""
    ammo = "" if w.ammo < 0 else f", {w.ammo} left in the magazine"
    dog = "" if not w.dog_hits else f", and the dog {w.dog_hits}×"
    print(f"\nResult: {w.score} points — {w.hits} of {w.total} ducks "
          f"({w.accuracy:.0f}% accuracy, {w.shots} shots{ammo}{dog}). Bye! 🦆")


if __name__ == "__main__":
    main()
