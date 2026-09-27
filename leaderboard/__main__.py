"""The whole scoreboard in one command: the server, and the board in a browser.

    python3 -m leaderboard
    python3 -m leaderboard --color amber --top 12

The server runs in a thread inside this process and serves the board itself
(`leaderboard/board.html`) at `/` — the tube-TV page, phosphor glow, scanlines
and the bright band rolling down the picture that a camera sees on a real tube.
This command opens it in the default browser and then holds the terminal:
Ctrl-C stops the server, F in the page goes fullscreen (drag it to the second
screen first).

The server's per-run lines go to a file — `leaderboard.log` next to the
database, `tail -f` away — because a terminal that is holding a server is not
the place to read them.

Two processes are still the right thing when the board is on one machine and
the server on another, or when either has to be restarted without the other:

    python3 -m leaderboard.server --port 8420 --db leaderboard.db
    # ... and http://raspberrypi.local:8420/ in a browser on the other one
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from urllib.parse import urlencode

from . import server, store

# What the page understands. Kept in step with board.html's own defaults — it
# validates every one of these again, because a URL anyone can type is not a
# thing to trust, and this parser is here so a typo is caught in the terminal
# rather than silently ignored by the page.
COLORS = ("green", "amber", "white")
CABINETS = ("beige", "graphite", "wood")


def default_ducks() -> int:
    """The round size to show: whatever the game on this machine is set to.

    The board and the game usually share a Mac, and `[round] ducks` is the one
    setting they must agree on — a board showing 100-duck rounds while the game
    plays 40 is empty for a reason nobody can see. On a box with no game there
    is no settings.toml and 100 is the default.
    """
    try:
        from duckhunt.core.config import load
        return load().round.ducks
    except Exception:                                   # noqa: BLE001
        return 100


def _already_serving(port: int) -> bool:
    """Is a scoreboard already answering on that port? Then do not fight it.

    Starting the board a second time is a thing that happens — a second screen, a
    terminal reopened — and "Address already in use" followed by a traceback is a
    poor answer when the right one is to show the board that is already there.
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz",
                                    timeout=1.0) as r:
            return bool(json.loads(r.read().decode("utf-8")).get("ok"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="python3 -m leaderboard",
        description="Duck Hunt scoreboard: the server, and the board in a browser.")
    ap.add_argument("--host", default="0.0.0.0",
                    help="what the server listens on (0.0.0.0: the game may be "
                         "on another machine on the LAN)")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--db", default=store.default_path())
    ap.add_argument("--log", metavar="FILE",
                    help="where the server's per-run lines go "
                         "(default: leaderboard.log next to the database; "
                         "`-` throws them away)")
    ap.add_argument("--ducks", type=int, default=default_ducks(),
                    help="round size the board shows (default: [round] ducks "
                         "from the game's settings.toml)")
    ap.add_argument("--top", type=int, default=10, help="rows on the board")
    ap.add_argument("--color", choices=COLORS, default="green",
                    help="the phosphor")
    ap.add_argument("--cabinet", choices=CABINETS, default="beige",
                    help="the plastic around the tube")
    ap.add_argument("--refresh", type=float, default=2.0,
                    help="seconds between polls")
    ap.add_argument("--speed", type=float, default=7.0,
                    help="how fast the line along the bottom runs, characters/s")
    ap.add_argument("--plain", action="store_true",
                    help="no glow, no scanlines, no rolling band — a flat board")
    args = ap.parse_args(argv)

    httpd = None
    if _already_serving(args.port):
        # somebody else's server is on that port — show its board rather than
        # refusing to start
        print(f"a scoreboard is already serving on :{args.port} — showing it",
              file=sys.stderr)
    else:
        log_path = args.log or os.path.splitext(args.db)[0] + ".log"
        server.log_stream = (open(os.devnull, "w") if args.log == "-"
                             else open(log_path, "a", encoding="utf-8"))
        try:
            httpd = server.build(args.host, args.port, args.db)
        except OSError as exc:
            ap.error(f"cannot listen on {args.host}:{args.port} ({exc})")
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        where = "" if args.log == "-" else f", runs logged to {log_path}"
        print(f"leaderboard on :{args.port}  db={args.db}{where}", file=sys.stderr)

    params = {"ducks": args.ducks, "top": args.top, "color": args.color,
              "cabinet": args.cabinet, "refresh": args.refresh,
              "speed": args.speed}
    if args.plain:
        params["plain"] = 1
    url = f"http://localhost:{args.port}/?{urlencode(params)}"
    print(f"the board: {url}\n"
          f"F in the page goes fullscreen — drag it to the second screen "
          f"first.\nCtrl-C here stops the server.", file=sys.stderr)
    webbrowser.open(url)
    try:
        if httpd is not None:
            httpd.serve_forever()
        else:
            # somebody else's server is serving it; nothing for us to hold
            print("that server is not ours to keep running — this command is "
                  "done", file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if server.log_stream is not None:
            server.log_stream.close()


if __name__ == "__main__":
    main()
