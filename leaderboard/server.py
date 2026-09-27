"""The leaderboard server: five routes, one SQLite file, standard library only.

    python3 -m leaderboard.server --port 8420 --db leaderboard.db

One packet per ROUND, so this is HTTP and not the `x,y,b` UDP the gun speaks:
delivery matters far more than latency here, and a lost datagram would be a lost
record. HTTP also gives the game something back — though with the board on a
screen of its own the game only uses it to know the row arrived.

The terminal it runs in is the audit trail: one line per accepted run.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import store

MAX_BODY = 8192
# The widest a score may be, per duck in the round, in either direction. There is
# no honest exact bound — the points table lives in the game's settings, and the
# server is told what it was rather than deciding it — but there is an obvious
# insane one. `score DESC` leads every ranking and nothing ever rewrites a stored
# score, so one hand-made POST of 10^15 would own the board, the ticker and every
# record shout for good, on a port this file's own docstring calls open on the LAN.
# 100 a duck is roughly fifty times the real rate and still stops that dead.
MAX_POINTS_PER_DUCK = 100          # a round result is ~400 bytes; anything larger is junk
TOKEN_HEADER = "X-Duckhunt-Key"
PAGE_NAME = "board.html"  # the browser board, served at /

# Where the per-run lines go. None means the terminal, which is what you want
# when the server has a terminal of its own; `python3 -m leaderboard` points this
# at a file instead, because the board is drawing on that terminal and a log line
# landing in the middle of it is a hole in the board.
log_stream = None


def log(line: str, err: bool = False) -> None:
    if log_stream is not None:
        print(line, file=log_stream, flush=True)
    else:
        print(line, file=sys.stderr if err else sys.stdout, flush=True)


class Rejected(Exception):
    """A request that will not be stored, with the reason to send back."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def _iso(value: str, field: str) -> str:
    """A timestamp we can read back, or a 400. The board sorts on these."""
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise Rejected(f"{field}: not an ISO-8601 timestamp")
    return str(value)


def validate(body: dict) -> dict:
    """Everything that goes in the table, checked — the port is open on the LAN.

    A junk row on the board is forever, so a bad run is a 400 and is not stored.

    `score`, `dog_hits` and `crosshair` are optional, and that is deliberate: a
    game that has not been updated yet posts without them, and the day the board
    starts answering 400 to the cabinet in the other room is the day an evening
    of rounds is lost. Missing means the old rule — a duck was a point, nothing
    cost anything, and nobody counted the dog — so the score falls back to the
    hits. A score is NOT clamped at zero: a round that fired forty times for
    three ducks genuinely went below it, and hiding that would make the board
    lie about how hard aiming is.
    """
    if not isinstance(body, dict):
        raise Rejected("body must be a JSON object")
    run_uuid = str(body.get("run_uuid", "")).strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", run_uuid):
        raise Rejected("run_uuid: expected a hex uuid")
    name = " ".join(str(body.get("name", "")).split())[:store.NAME_MAX]
    if not name:
        raise Rejected("name: must not be empty")
    try:
        hits, shots, ducks = (int(body["hits"]), int(body["shots"]),
                              int(body["ducks"]))
        duration = float(body["duration"])
    except (KeyError, TypeError, ValueError):
        raise Rejected("hits, shots, ducks and duration are required numbers")
    if not 0 <= hits <= shots:
        raise Rejected("hits must be between 0 and shots")
    if not 1 <= ducks <= 10000:
        raise Rejected("ducks must be between 1 and 10000")
    if hits > ducks:
        raise Rejected("hits cannot exceed the ducks in the round")
    if not 0 <= duration < 24 * 3600:
        raise Rejected("duration must be a sane number of seconds")
    try:
        score = int(body.get("score", hits))
        dog_hits = int(body.get("dog_hits", 0))
    except (TypeError, ValueError):
        raise Rejected("score and dog_hits must be whole numbers")
    # a duck and the dog each cost a shot, so this is the real invariant: a
    # one-shot round cannot have hit both
    if not 0 <= dog_hits <= shots - hits:
        raise Rejected("dog_hits must be between 0 and the shots that missed")
    if abs(score) > MAX_POINTS_PER_DUCK * ducks:
        # deliberately not clamped at zero in the other direction: a round really
        # can finish at -35, and hiding the worst round of the evening would cost
        # the board half its entertainment
        raise Rejected("score is not a plausible number of points")
    settings = body.get("settings")
    return {"run_uuid": run_uuid.lower(), "name": name,
            "hits": hits, "shots": shots, "ducks": ducks, "duration": duration,
            "score": score, "dog_hits": dog_hits,
            "crosshair": bool(body.get("crosshair", False)),
            "started_at": _iso(body.get("started_at"), "started_at"),
            "finished_at": _iso(body.get("finished_at"), "finished_at"),
            "client_id": str(body.get("client_id", "unknown"))[:64],
            "input_source": str(body.get("input_source", ""))[:32] or None,
            "game_version": str(body.get("game_version", ""))[:32] or None,
            "settings": (json.dumps(settings, ensure_ascii=False)
                         if settings is not None else None)}


class Handler(BaseHTTPRequestHandler):
    server_version = "duckhunt-leaderboard/1.0"
    db_path: str = ""
    token: str = ""

    # ---- plumbing ----

    def log_message(self, fmt: str, *args) -> None:
        pass          # the accepted-run lines below are the log; HTTP noise is not

    def _send(self, payload: dict, code: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass      # the display walked away mid-answer; not our problem

    def _check_token(self, given: str = "") -> None:
        if not self.token:
            return
        # the header is how the game sends it; `?key=` is for the browser board,
        # which is a page and cannot set one on its own fetches
        given = given or self.headers.get(TOKEN_HEADER, "")
        if not hmac.compare_digest(given, self.token):
            raise Rejected("bad or missing key", 403)

    def _send_page(self) -> None:
        """The browser board — read from disk each time, so tuning how it looks
        is a reload rather than a restart."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), PAGE_NAME)
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            raise Rejected(f"the board page is missing ({exc})", 500)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise Rejected("empty body")
        if length > MAX_BODY:
            raise Rejected("body too large", 413)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Rejected(f"body is not JSON ({exc})")

    # ---- routes ----

    def do_GET(self) -> None:
        url = urlparse(self.path)
        q = parse_qs(url.query)

        def num(key, default, cast=int):
            try:
                return cast(q[key][0])
            except (KeyError, IndexError, ValueError):
                return default

        try:
            if url.path == "/healthz":
                self._send({"ok": True})
                return
            if url.path in ("/", "/index.html", "/" + PAGE_NAME):
                # the page carries no data of its own; the API calls it makes
                # are checked like any other
                self._send_page()
                return
            self._check_token(q.get("key", [""])[0])
            ducks = num("ducks", 100)
            with store.connect(self.db_path) as conn:
                if url.path == "/api/board":
                    self._send({"ok": True, "ducks": ducks,
                                "rows": store.board(conn, ducks,
                                                    num("limit", 10),
                                                    q.get("window", ["all"])[0],
                                                    q.get("order", ["best"])[0])})
                elif url.path == "/api/stats":
                    self._send({"ok": True, **store.stats(conn, ducks)})
                elif url.path == "/api/players":
                    # the name entry, asking who is already here. Not scoped to
                    # `ducks`: see store.search_players for why a name outlives
                    # the round size it was first typed in.
                    term = q.get("q", [""])[0][:store.NAME_MAX]
                    self._send({"ok": True, "q": term,
                                "rows": store.search_players(conn, term,
                                                             num("limit", 8))})
                elif url.path.startswith("/api/player/"):
                    name = unquote(url.path[len("/api/player/"):])
                    if not name:
                        raise Rejected("player: no name in the path", 404)
                    self._send({"ok": True,
                                **store.player(conn, name, ducks, num("limit", 20))})
                else:
                    raise Rejected("no such route", 404)
        except Rejected as exc:
            self._send({"error": str(exc)}, exc.code)
        except Exception as exc:                          # noqa: BLE001
            log(f"! {url.path}: {exc}", err=True)
            self._send({"error": "server error"}, 500)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        try:
            if url.path != "/api/runs":
                raise Rejected("no such route", 404)
            self._check_token()
            run = validate(self._body())
            with store.connect(self.db_path) as conn:
                result = store.insert_run(conn, run)
            when = run["finished_at"][11:19]
            acc = run["hits"] / run["shots"] * 100 if run["shots"] else 0
            log(f"{when}  {run['name']:<12} {run['score']:>4} pts  "
                f"{run['hits']:>3}/{run['ducks']:<4} "
                f"{acc:>3.0f}%  {run['duration']:>4.0f}s  "
                f"rank {result.get('rank')}"
                f"{'  (duplicate, not stored twice)' if result['duplicate'] else ''}")
            self._send(result)
        except Rejected as exc:
            log(f"! rejected: {exc}", err=True)
            self._send({"error": str(exc)}, exc.code)
        except Exception as exc:                          # noqa: BLE001
            log(f"! /api/runs: {exc}", err=True)
            self._send({"error": "server error"}, 500)


def build(host: str, port: int, db: str, token: str = "") -> ThreadingHTTPServer:
    """A server ready to be served — in this process or in a thread of its own."""
    store.init(db)
    Handler.db_path, Handler.token = db, token
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python3 -m leaderboard.server",
                                 description="Duck Hunt leaderboard server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--db", default=store.default_path(),
                    help="SQLite file (leaderboard.db in the project root)")
    ap.add_argument("--token", default="",
                    help="shared secret the game must send in "
                         f"{TOKEN_HEADER} — off by default (home LAN)")
    ap.add_argument("--log", metavar="FILE",
                    help="write the per-run lines to a file instead of here")
    args = ap.parse_args(argv)

    global log_stream
    if args.log:
        log_stream = open(args.log, "a", encoding="utf-8")
    httpd = build(args.host, args.port, args.db, args.token)
    print(f"leaderboard on http://{args.host}:{args.port}  db={args.db}"
          f"\nthe board in a browser: http://localhost:{args.port}/"
          f"{'  (token required)' if args.token else ''}\n"
          f"one line per accepted run follows; Ctrl-C stops it", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
