"""The whole scoreboard in one command: the server and a board, one window.

    python3 -m leaderboard --browser             # the tube-TV board in a browser
    python3 -m leaderboard                       # the same board in this terminal
    python3 -m leaderboard --browser --color amber --top 12

Two boards, one server, the same flags for either: `--browser` opens the CRT page
(`leaderboard/board.html`) in the default browser and leaves the server holding
this terminal; without it the console board (`leaderboard/display.py`) is drawn
here. The browser one is the better-looking of the two — phosphor glow, scanlines,
and the bright band rolling down the picture that a camera sees on a real tube —
and the terminal one is the one that works on a Pi with no desktop.

The server runs in a thread inside this process and the board draws in the
foreground, so there is one thing to start and one thing to quit: `q` stops the
board and takes the server down with it. Every flag that is not the server's is
handed to `leaderboard.display`, so `--color`, `--top`, `--ducks`, `--speed`,
`--ascii`, `--plain` and `--bell` all work here too.

The server's per-run lines cannot share a terminal with a board being drawn on it,
so they go to a file — `leaderboard.log` next to the database, `tail -f` away.

Two processes are still the right thing when the board lives on a Pi and the
server somewhere else, or when either has to be restarted without the other:

    python3 -m leaderboard.server --port 8420 --db leaderboard.db
    python3 -m leaderboard.display --url http://raspberrypi.local:8420
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

from . import display, server, store


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
        description="Duck Hunt scoreboard: the server and the console board, "
                    "in one window. Flags not listed here go to the board — "
                    "see `python3 -m leaderboard.display --help`.")
    ap.add_argument("--host", default="0.0.0.0",
                    help="what the server listens on (0.0.0.0: the game may be "
                         "on another machine on the LAN)")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--db", default=store.default_path())
    ap.add_argument("--ducks", type=int, default=None,
                    help="round size the board shows (default: [round] ducks "
                         "from the game's settings.toml)")
    ap.add_argument("--token", default="",
                    help="shared secret; the game sends it in X-Duckhunt-Key")
    ap.add_argument("--browser", action="store_true",
                    help="open the tube-TV board in a browser instead of drawing "
                         "the console one here; the server then holds this terminal")
    ap.add_argument("--log", metavar="FILE",
                    help="where the server's per-run lines go "
                         "(default: leaderboard.log next to the database; "
                         "`-` throws them away)")
    args, rest = ap.parse_known_args(argv)

    if "--url" in rest:
        ap.error("--url is for `python3 -m leaderboard.display`: this command "
                 "runs the server itself, and the board reads it on 127.0.0.1")

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
            httpd = server.build(args.host, args.port, args.db, args.token)
        except OSError as exc:
            ap.error(f"cannot listen on {args.host}:{args.port} ({exc})")
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        where = "" if args.log == "-" else f", runs logged to {log_path}"
        print(f"leaderboard on :{args.port}  db={args.db}{where}", file=sys.stderr)

    try:
        if args.browser:
            # the same flags the console board takes, turned into the page's
            # query string — checked by the board's own parser, so a typo is
            # caught here rather than silently ignored by a URL
            d = display.build_parser().parse_args(rest)
            if args.ducks is not None:
                d.ducks = args.ducks
            params = {"ducks": d.ducks, "top": d.top, "color": d.color,
                      "refresh": d.refresh, "speed": d.speed}
            if d.plain:
                params["plain"] = 1
            if args.token:
                params["key"] = args.token
            url = f"http://localhost:{args.port}/?{urlencode(params)}"
            print(f"the board: {url}\n"
                  f"F in the page goes fullscreen — drag it to the second screen "
                  f"first.\nCtrl-C here stops the server.", file=sys.stderr)
            webbrowser.open(url)
            if httpd is not None:
                httpd.serve_forever()
            else:
                # somebody else's server is serving it; nothing for us to hold
                print("that server is not ours to keep running — this command is "
                      "done", file=sys.stderr)
        else:
            forward = list(rest) + ["--url", f"http://127.0.0.1:{args.port}"]
            if args.ducks is not None:
                forward += ["--ducks", str(args.ducks)]
            if args.token:
                forward += ["--token", args.token]
            display.main(forward)
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
