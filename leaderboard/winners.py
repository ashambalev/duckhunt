"""The prize-giving page: three slides in the game's own colours, from the board.

    python3 -m leaderboard.winners                        # -> winners.html
    python3 -m leaderboard.winners --skip 1 --skip P      # leave test names off
    python3 -m leaderboard.winners --ducks 40 --since 2026-10-15 -o party.html
    python3 -m leaderboard.winners --event "TDS TechConf 2026"   # instead of the dates

Title, the evening in numbers, everybody from #4 down, and then the podium on a
slide of its own, big enough for a hall: → shows #3, then #2, then #1. One self-contained file —
the results and the sprites are baked in — so it can be generated on the scoreboard
host right before the speech and opened on whatever drives the projector.

`--skip` takes a name off the ranking only. Those rounds still count in the
numbers slide: they were fired, the ducks fell, and the totals would otherwise
disagree with the board everyone watched all evening.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime

from . import store

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")
TEMPLATE = os.path.join(HERE, "winners.html")
SPRITES = ["dog_laugh_1", "dog_laugh_2"] + [
    f"duck_{c}_fly_{i}" for c in ("red", "black") for i in (1, 2, 3)]


def _png(path: str) -> str:
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def sprites() -> dict:
    out = {name: _png(os.path.join(ASSETS, "sprites", name + ".png")) for name in SPRITES}
    out["meadow"] = _png(os.path.join(ASSETS, "backgrounds", "meadow.png"))
    return out


def results(conn, ducks: int, skip: list[str], since: str | None) -> dict:
    """The ranking without the skipped names, and the numbers with everything."""
    skipped = {store.player_key(n) for n in skip}
    extra = " AND finished_at >= :since" if since else ""
    p = {"ducks": ducks, "since": since}
    board = [r for r in store.board(conn, ducks, 100)
             if store.player_key(r["name"]) not in skipped]
    if since:
        board = [r for r in board if r["finished_at"] >= since]

    def one(sql):
        return conn.execute(sql.format(where=f"ducks = :ducks{extra}"), p).fetchone()

    t = one("SELECT COUNT(*) rounds, COUNT(DISTINCT player_key) players, "
            "COALESCE(SUM(hits),0) ducks_down, COALESCE(SUM(shots),0) shots, "
            "COALESCE(SUM(dog_hits),0) dog_hits, MIN(finished_at) first, "
            "MAX(finished_at) last FROM runs WHERE {where}")
    stats = {"rounds": t["rounds"], "players": t["players"],
             "ducks_down": t["ducks_down"], "shots": t["shots"],
             "dog_hits": t["dog_hits"],
             "hit_rate": round(100 * t["ducks_down"] / t["shots"]) if t["shots"] else 0}
    return {"board": board, "stats": stats, "when": _when(t["first"], t["last"])}


def _when(first: str | None, last: str | None) -> str:
    if not first:
        return ""
    a, b = (datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone()
            for x in (first, last))
    if a.date() == b.date():
        return a.strftime("%-d %b %Y").upper()
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.strftime('%-d %b %Y')}".upper()
    return f"{a.strftime('%-d %b')} – {b.strftime('%-d %b %Y')}".upper()


def _js(value) -> str:
    # inside a <script>: no "</script>" can come out of a player's name
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def render(data: dict) -> str:
    with open(TEMPLATE, encoding="utf-8") as f:
        page = f.read()
    for marker, value in (("DATA", data), ("SPRITES", sprites())):
        head, rest = page.split(f"/*{marker}*/", 1)
        _, tail = rest.split("/*END*/", 1)
        page = head + _js(value) + tail
    return page


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python3 -m leaderboard.winners",
                                 description="Write the prize-giving slides")
    ap.add_argument("--db", default=store.default_path())
    ap.add_argument("--ducks", type=int, default=40, help="the round size (40)")
    ap.add_argument("--skip", action="append", default=[], metavar="NAME",
                    help="leave a name off the ranking (still counted in the numbers)")
    ap.add_argument("--since", metavar="DATE",
                    help="only rounds finished on or after this ISO date")
    ap.add_argument("--event", metavar="NAME",
                    help="the line under the title (default: the dates played)")
    ap.add_argument("-o", "--out", default=os.path.join(HERE, "..", "winners.html"))
    args = ap.parse_args(argv)

    with store.session(args.db) as conn:
        data = results(conn, args.ducks, args.skip, args.since)
    if args.event:
        data["when"] = args.event
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render(data))
    b = data["board"]
    print(f"{os.path.relpath(args.out)}: {len(b)} on the ranking, "
          f"{data['stats']['rounds']} rounds in the numbers")
    for i, r in enumerate(b[:3], 1):
        print(f"  #{i}  {r['name']:<14} {r['score']:>4} pts  {r['hits']}/{r['ducks']}")


if __name__ == "__main__":
    main()
