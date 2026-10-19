"""Put the rounds the board never saw on it.

    python3 -m leaderboard.seed --from-scores      # import scores.json

The game used to keep a top ten of its own in `scores.json`, and those were real
evenings. This is the only thing left that reads that shape. The import is
idempotent: the run_uuid is derived from the row itself, so running it twice does
not double the board.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

from . import store


def _uuid_for(*parts) -> str:
    """A stable id for a row that never had one — so an import cannot duplicate."""
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


SCORES_NAME = "scores.json"


def scores_path() -> str:
    """`scores.json` in the project root, where the game used to keep its ten."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", SCORES_NAME)


def read_scores(path: str | None = None) -> list[dict]:
    """The old local table, straight off disk.

    The module that wrote this file is gone — a top ten on one machine that
    nothing read back out, once the board next door was keeping every attempt by
    everybody. The *reader* outlives it on purpose: an old `scores.json` in
    somebody's project root is a handful of real evenings, and the whole point of
    `--from-scores` is that they are not thrown away for being in the old shape.
    Anything malformed is skipped rather than fatal — half an import beats none.
    """
    path = path or scores_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"{SCORES_NAME}: could not be read ({exc}) — nothing imported",
              file=sys.stderr)
        return []
    rows = []
    for r in raw if isinstance(raw, list) else []:
        try:
            rows.append({"name": str(r["name"]), "hits": int(r["hits"]),
                         "shots": int(r["shots"]), "ducks": int(r["ducks"]),
                         "date": str(r["date"])})
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def from_scores(conn, path: str | None = None) -> int:
    """The local top ten becomes the first rows of the board.

    `scores.json` has no score in it, because those rounds were played when a
    duck was worth one point and neither a miss nor the dog cost anything — so
    the hit count IS the score of such a round, the same arithmetic the migration
    in `store._migrate` does for the rows already in the database. Not a guess:
    it is the old rule applied to rows played under it. `dog_hits` stays 0 for
    the same reason — nothing counted the dog then — and so does `crosshair`,
    which those rounds never recorded either way.
    """
    added = 0
    for e in read_scores(path):
        when = f"{e['date']}T20:00:00+00:00"
        run = {"run_uuid": _uuid_for("scores", e["name"], e["hits"], e["shots"],
                                     e["ducks"], e["date"]),
               "name": e["name"], "hits": e["hits"], "shots": e["shots"],
               "ducks": e["ducks"],
               "score": e["hits"], "dog_hits": 0, "crosshair": 0,
               "duration": 0.0, "started_at": when, "finished_at": when,
               "client_id": "scores.json", "input_source": None,
               "game_version": None, "settings": None}
        result = store.insert_run(conn, run)
        added += 0 if result["duplicate"] else 1
    return added


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python3 -m leaderboard.seed",
                                 description="Seed the leaderboard database")
    ap.add_argument("--db", default=store.default_path())
    ap.add_argument("--from-scores", action="store_true",
                    help="import the game's local scores.json")
    ap.add_argument("--scores", metavar="FILE", help="a scores.json somewhere else")
    args = ap.parse_args(argv)

    store.init(args.db)
    with store.session(args.db) as conn:
        if args.from_scores or args.scores:
            print(f"imported {from_scores(conn, args.scores)} rounds from scores.json")
        if not (args.from_scores or args.scores):
            print("nothing to do: pass --from-scores")
        rows = store.board(conn, 100, 10)
    for i, r in enumerate(rows, 1):
        tries = "try" if r["attempts"] == 1 else "tries"
        print(f"  {i:>2}. {r['name'][:20]:<20} {r['score']:>5} pts  "
              f"{r['hits']:>3} ducks  {r['accuracy']:>3.0f}%  "
              f"{r['attempts']:>3} {tries}")


if __name__ == "__main__":
    main()
