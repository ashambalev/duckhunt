"""The scoreboard on a screen of its own: a console board with a running line.

    python3 -m leaderboard.display --url http://raspberrypi.local:8420

    ╔══════════════════════════════════════════════════════╗
    ║             D U C K   H U N T   —   T O P  10         ║
    ╠══════════════════════════════════════════════════════╣
    ║   1. EUGENE ......... 66 DUCKS   66%   12 TRIES 09-02 ║
    ╚══════════════════════════════════════════════════════╝
    ◀ *** NEW RECORD: EUGENE — 66 DUCKS *** 412 ROUNDS PLAYED ***

Two clocks, on purpose: the running line scrolls every frame (~20 FPS) while the
API is polled on a background thread every couple of seconds. A slow or dead
server slows nothing down on screen — the board goes dim and the line says the
link is down, which is a great deal better than a scoreboard that goes blank
because one Wi-Fi packet was lost.

The game never draws any of this. It asks for a name and sends the row; the board
lives here.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from blessed import Terminal

# Names are stored long (scores.NAME_MAX is 50) and shown short: a board is a
# column of numbers people read from across the room, and one 50-character name
# would leave no room for what it scored.
NAME_W = 18

FPS = 20
FLASH_SECONDS = 5.0        # how long a freshly arrived row stays lit
SHOUT_SECONDS = 30.0       # how long the ticker leads with a new record

# Phosphor palettes: the bright colour for the top of the board, the dim one for
# the rows below it, so the list fades down the way a real tube does.
def default_ducks() -> int:
    """The round size to show: whatever the game on this machine is set to.

    The board and the game usually share a Mac, and `[round] ducks` is the one
    setting they must agree on — a board showing 100-duck rounds while the game
    plays 40 is empty for a reason nobody can see. On a box with no game (a Pi
    running only the board) there is no settings.toml and 100 is the default.
    """
    try:
        from duckhunt.core.config import load
        return load().round.ducks
    except Exception:                                   # noqa: BLE001
        return 100


PALETTES = {"green": ("bright_green", "green"),
            "amber": ("bright_yellow", "yellow"),
            "white": ("bright_white", "white")}

# One board, and only one: the best round per player, best first. The server
# still answers `window=today|week` and `order=attempts`, and a panel rotating
# through those was here and came back out — a screen people glance at from
# across the room should be showing the same thing every time they glance.

BOX = {"tl": "╔", "tr": "╗", "bl": "╚", "br": "╝", "h": "═", "v": "║",
       "ml": "╠", "mr": "╣"}
BOX_ASCII = {"tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-", "v": "|",
             "ml": "+", "mr": "+"}

# A 5-row block font, just the letters "DUCK HUNT" needs — no figlet dependency
# for nine characters.
BANNER = {
    "D": ["████ ", "█   █", "█   █", "█   █", "████ "],
    "U": ["█   █", "█   █", "█   █", "█   █", " ███ "],
    "C": [" ████", "█    ", "█    ", "█    ", " ████"],
    "K": ["█   █", "█  █ ", "███  ", "█  █ ", "█   █"],
    "H": ["█   █", "█   █", "█████", "█   █", "█   █"],
    "N": ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
    "T": ["█████", "  █  ", "  █  ", "  █  ", "  █  "],
    " ": ["  ", "  ", "  ", "  ", "  "],
}


class Board:
    """What the server last said, and whether it is still answering.

    Written by the poll thread, read by the drawing loop; a lock around the swap
    is all the synchronisation two threads sharing one dict need here.
    """

    def __init__(self, url: str, ducks: int, top: int, refresh: float,
                 token: str = ""):
        self.url = url.rstrip("/")
        self.ducks, self.top, self.refresh, self.token = ducks, top, refresh, token
        self._lock = threading.Lock()
        self.rows: list[dict] = []
        self.stats: dict = {}
        self.up = False
        self.last_ok = 0.0
        self.error = "connecting"
        self._wake = threading.Event()

    # ---- the network side ----

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(self.url + path)
        if self.token:
            req.add_header("X-Duckhunt-Key", self.token)
        with urllib.request.urlopen(req, timeout=2.0) as r:
            return json.loads(r.read().decode("utf-8"))

    def poll_once(self) -> None:
        try:
            rows = self._get(f"/api/board?ducks={self.ducks}&limit={self.top}"
                             ).get("rows", [])
            stats = self._get(f"/api/stats?ducks={self.ducks}")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            with self._lock:
                self.up, self.error = False, str(getattr(exc, "reason", exc))[:40]
            return
        with self._lock:
            self.rows, self.stats = rows, stats
            self.up, self.last_ok, self.error = True, time.monotonic(), ""

    def run_forever(self) -> None:
        while True:
            self.poll_once()
            # a dead server is retried on the same clock — no backoff, because the
            # moment it comes back is the moment the board should be right again
            self._wake.wait(self.refresh)
            self._wake.clear()

    def start(self) -> None:
        threading.Thread(target=self.run_forever, daemon=True).start()

    # ---- the drawing side reads through here ----

    def snapshot(self) -> tuple[list[dict], dict, bool, str]:
        with self._lock:
            return list(self.rows), dict(self.stats), self.up, self.error


def ticker_text(stats: dict, up: bool, error: str, shout: str) -> str:
    """The running line: one string, rebuilt whenever the numbers change."""
    parts: list[str] = []
    if shout:
        parts.append(shout)
    if not up:
        parts.append(f"LINK DOWN — RETRYING ({error})" if error else
                     "LINK DOWN — RETRYING")
    record = stats.get("record")
    if record:
        parts.append(f"RECORD: {record['name'].upper()} {record['hits']} DUCKS")
    if stats.get("rounds"):
        def many(n, one, more):
            return f"{n} {one if n == 1 else more}"
        parts.append(many(stats["rounds"], "ROUND PLAYED", "ROUNDS PLAYED"))
        parts.append(many(stats["players"], "SHOOTER", "SHOOTERS"))
        parts.append(many(stats["ducks_down"], "DUCK DOWNED", "DUCKS DOWNED"))
    if not parts:
        parts.append("NO ROUNDS YET — BE THE FIRST")
    parts.append("PULL THE TRIGGER")
    return "  ***  ".join(parts) + "  ***  "


def row_text(i: int, row: dict, width: int, compact: bool, ascii_only: bool = False) -> str:
    """One board line, dot leaders and all, fitted to the panel's width."""
    name = row["name"].upper()
    cut = "~" if ascii_only else "…"
    name = name if len(name) <= NAME_W else name[:NAME_W - 1] + cut
    if compact:
        return f"{i}.{name} {row['hits']}"[:width]
    # padded, so one player's single try does not shift the dot leaders
    tries = ("TRY" if row["attempts"] == 1 else "TRIES").ljust(5)
    right = (f"{row['hits']:>3} DUCKS {row['accuracy']:>3.0f}% "
             f"{row['attempts']:>3} {tries} {row['finished_at'][5:10]}")
    left = f"{i:>2}. {name} "
    dots = max(1, width - len(left) - len(right) - 1)
    return f"{left}{'.' * dots} {right}"[:width]


def banner_lines(ascii_only: bool) -> list[str]:
    glyphs = [BANNER[c] for c in "DUCK HUNT"]
    rows = ["".join(g[r] + " " for g in glyphs).rstrip() for r in range(5)]
    return [r.replace("█", "#") for r in rows] if ascii_only else rows


def boot_sequence(term: Terminal, url: str, bright, plain: bool) -> None:
    """A machine waking up. About 1.5 s, and any key skips it."""
    if plain:
        return
    lines = ["DUCK HUNT SCOREBOARD v1.0",
             "MEMORY OK ....... 64K",
             f"LINK {url} ... OK",
             "LOADING BOARD ..."]
    print(term.home + term.clear, end="", flush=True)
    for y, line in enumerate(lines):
        for x in range(len(line)):
            print(term.move_yx(y + 1, 2) + bright(line[:x + 1]), end="", flush=True)
            if term.inkey(timeout=0.006):
                return
        if term.inkey(timeout=0.12):
            return


def build_parser() -> argparse.ArgumentParser:
    """The board's flags, shared with `python3 -m leaderboard` — which hands the
    same ones to the terminal board or turns them into the browser board's query
    string, so `--color amber --top 12` means one thing however the board is drawn."""
    ap = argparse.ArgumentParser(prog="python3 -m leaderboard.display",
                                 description="Duck Hunt console scoreboard")
    ap.add_argument("--url", default="http://localhost:8420")
    ap.add_argument("--token", default="", help="if the server wants one")
    ap.add_argument("--ducks", type=int, default=default_ducks(),
                    help="round size this board is for: 100-duck and 40-duck "
                         "rounds do not compete (default: [round] ducks from "
                         "the game's settings.toml)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--refresh", type=float, default=2.0, help="seconds between polls")
    ap.add_argument("--speed", type=float, default=12.0,
                    help="running line speed, characters per second")
    ap.add_argument("--color", choices=sorted(PALETTES), default="green")
    ap.add_argument("--ascii", action="store_true",
                    help="+---+ instead of box drawing, for fonts that mangle it")
    ap.add_argument("--plain", action="store_true",
                    help="no banner, no boot sequence, no blinking cursor — for a "
                         "corner of a tiling window manager rather than a screen")
    ap.add_argument("--bell", action="store_true", help="beep on a new record")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    term = Terminal()
    box = BOX_ASCII if args.ascii else BOX
    bright_name, dim_name = PALETTES[args.color]
    bright = getattr(term, bright_name)
    dim = getattr(term, dim_name)

    board = Board(args.url, args.ducks, args.top, args.refresh, args.token)
    board.start()

    offset = 0.0
    shout, shout_t = "", 0.0
    flash_key, flash_t = None, 0.0
    last_id = None
    last_size = (0, 0)

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        boot_sequence(term, args.url, bright, args.plain)
        print(term.home + term.clear, end="")
        last = time.monotonic()
        while True:
            now = time.monotonic()
            dt = now - last
            last = now

            key = term.inkey(timeout=0)
            if key and (str(key).lower() == "q" or key.name == "KEY_ESCAPE"):
                break
            rows, stats, up, error = board.snapshot()

            # a run we have not seen before: light its row, and let the ticker
            # shout about it if it is the new record
            latest = stats.get("latest")
            if latest and latest.get("id") != last_id:
                if last_id is not None:
                    flash_key, flash_t = (latest["name"].casefold(), 0.0)
                    if latest.get("is_record"):
                        shout = (f"*** NEW RECORD: {latest['name'].upper()} — "
                                 f"{latest['hits']} DUCKS ***")
                        if args.bell:
                            print("\a", end="", flush=True)
                    else:
                        shout = (f"{latest['name'].upper()} SHOT "
                                 f"{latest['hits']} OF {stats.get('ducks', '')}")
                    shout_t = 0.0
                last_id = latest.get("id")
            if flash_key is not None:
                flash_t += dt
                if flash_t > FLASH_SECONDS:
                    flash_key = None
            if shout:
                shout_t += dt
                if shout_t > SHOUT_SECONDS:
                    shout = ""

            h, w = term.height, term.width
            if (h, w) != last_size:
                print(term.home + term.clear, end="")
                last_size = (h, w)
            compact = w < 40
            lines: list[tuple[str, object]] = []

            # ---- the banner, when there is room for it ----
            with_banner = not args.plain and h >= 20 and w >= 60
            if with_banner:
                for line in banner_lines(args.ascii):
                    lines.append((line.center(w), bright))
                lines.append(("", bright))

            # ---- the panel ----
            title = f"TOP {args.top}"
            inner = min(w - 2, 58 if not compact else w - 2)
            pad = max(0, (w - inner - 2) // 2)
            head = " " * pad + box["tl"] + box["h"] * inner + box["tr"]
            lines.append((head, bright if up else dim))
            head_text = title if with_banner or compact else f"DUCK HUNT — {title}"
            lines.append((" " * pad + box["v"] + head_text.center(inner)[:inner]
                          + box["v"], bright if up else dim))
            lines.append((" " * pad + box["ml"] + box["h"] * inner + box["mr"],
                          bright if up else dim))
            if not rows:
                empty = ("NO ROUNDS YET" if up else "WAITING FOR THE SERVER")
                lines.append((" " * pad + box["v"] + empty.center(inner)[:inner]
                              + box["v"], dim))
                for other in stats.get("sizes", []):
                    if other["ducks"] == args.ducks:
                        continue
                    note = (f"{other['runs']} ROUND(S) OF {other['ducks']} DUCKS "
                            f"— RESTART WITH --ducks {other['ducks']}")
                    lines.append((" " * pad + box["v"] + note.center(inner)[:inner]
                                  + box["v"], bright))
            for i, row in enumerate(rows[:args.top], 1):
                text = row_text(i, row, inner - 2, compact, args.ascii)
                body = " " * pad + box["v"] + " " + text.ljust(inner - 2) + " " + box["v"]
                lit = (flash_key is not None
                       and row["name"].casefold() == flash_key
                       and int(flash_t * 3) % 2 == 0)
                if not up:
                    style = dim
                elif lit:
                    style = term.reverse
                else:
                    style = bright if i <= 3 else dim
                lines.append((body, style))
            lines.append((" " * pad + box["bl"] + box["h"] * inner + box["br"],
                          bright if up else dim))

            # ---- the running line, pinned to the bottom row ----
            text = ticker_text(stats, up, error, shout)
            offset = (offset + args.speed * dt) % max(1, len(text))
            cursor = "" if args.plain else ("█" if int(now * 1) % 2 else " ")
            room = max(1, w - 3 - len(cursor))
            start = int(offset)
            window = (text * 3)[start:start + room]
            ticker = "◀ " if not args.ascii else "< "
            bottom = (ticker + window + cursor)[:w]

            above = max(0, (h - 1 - len(lines)) // 2)
            lines = [("", bright)] * above + lines
            while len(lines) < h - 1:
                lines.append(("", bright))
            del lines[h - 1:]
            lines.append((bottom, bright if up else dim))

            # One write per frame, never a clear in between: that is the whole
            # trick behind a board that glides instead of flickering.
            out = []
            for y, (text_line, style) in enumerate(lines):
                padded = text_line.ljust(w)[:w if y < h - 1 else w - 1]
                out.append(term.move_yx(y, 0) + style(padded))
            print("".join(out), end="", flush=True)

            time.sleep(max(0.0, 1.0 / FPS - (time.monotonic() - now)))


if __name__ == "__main__":
    main()
