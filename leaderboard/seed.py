"""Fill the board from what is already there, or with something to look at.

    python3 -m leaderboard.seed --from-scores      # import scores.json
    python3 -m leaderboard.seed --demo 40          # 40 invented rounds

The import is idempotent: the run_uuid is derived from the row itself, so running
it twice does not double the board.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone

from duckhunt.core.config import ScoreSettings

from . import store

# What a shot is worth, for working out what a demo round scored. The dataclass
# defaults rather than a loaded settings.toml on purpose: seeding a board on a
# box with no game on it must not depend on a file that is not there, and the
# demo rows only have to be coherent with each other.
POINTS = ScoreSettings()

# Invented players for --demo, each with the share of the flock they usually
# down and roughly how straight they shoot. Names and surnames, because a board
# of bare first names does not show what the column really looks like on a night
# when three Annas have played. All within store.NAME_MAX.
DEMO_PLAYERS = [
    # name,               skill, accuracy, how often they play
    ("EVGENY CHERNYAK",   0.82, 0.74, 9),
    ("ANNA PETROVA",      0.71, 0.80, 6),
    ("MIKE SOKOLOV",      0.66, 0.61, 5),
    ("MARIA NOVIKOVA",    0.63, 0.77, 4),
    ("KOSTYA MOROZOV",    0.58, 0.55, 7),
    ("LENA IVANOVA",      0.54, 0.69, 3),
    ("IGOR LEBEDEV",      0.49, 0.58, 5),
    ("SVETA ORLOVA",      0.46, 0.72, 2),
    ("PETYA SMIRNOV",     0.41, 0.49, 6),
    ("DASHA VOLKOVA",     0.37, 0.64, 3),
    ("TIMUR KARIMOV",     0.33, 0.52, 4),
    ("ALEX MILLER",       0.28, 0.45, 2),
    # one deliberately absurd one: the name entry takes 50 characters, and this
    # is what a board does with somebody who uses them
    ("ALEXANDRA KONSTANTINOPOLSKAYA", 0.60, 0.76, 2),
    ("KATE BROWN",        0.24, 0.58, 2),
    ("OLYA FEDOROVA",     0.19, 0.41, 3),
]


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


def demo(conn, count: int, ducks: int) -> int:
    """Invented rounds — the way to see a board full before anyone has played.

    Not uniform noise: each player has a skill and an aim of their own, so their
    attempts cluster around their own number the way real ones do, a good player
    has an unusually good night once, and the board ends up with the shape it
    will really have — a few close at the top, a long tail, and somebody who has
    played eleven times to get there.

    The score is not invented beside the shooting but worked out from it, with
    the game's own arithmetic over the hits, the misses and the dog: a demo row
    claiming 140 points next to 20 ducks would make a board that is being tested
    look broken. It also means a sloppy demo player goes negative here exactly
    the way a sloppy real one does, which is the case both boards have to be
    looked at with.
    """
    rng = random.Random(20260926)
    now = datetime.now(timezone.utc)
    weights = [p[3] for p in DEMO_PLAYERS]
    # everybody plays at least once, then the rest of the evening goes to
    # whoever keeps queueing up — otherwise the dice leave somebody off the
    # board entirely and the demo shows fewer names than it has
    order = list(DEMO_PLAYERS)[:count]
    for i in range(count):
        if i < len(order):
            name, skill, aim, _ = order[i]
        else:
            name, skill, aim, _ = rng.choices(DEMO_PLAYERS, weights=weights)[0]
        # the night's form: mostly themselves, sometimes a round that surprises
        form = rng.gauss(skill, 0.07) + (0.12 if rng.random() < 0.08 else 0)
        hits = max(1, min(ducks, round(ducks * max(0.05, min(0.99, form)))))
        accuracy = max(0.18, min(0.97, rng.gauss(aim, 0.06)))
        shots = max(hits, round(hits / accuracy))
        # the dog walks in front of the grass and gets shot occasionally — never
        # more times than there were shots left over after the ducks
        dog_hits = min(shots - hits, rng.choices([0, 1, 2], [7, 2, 1])[0])
        score = (POINTS.duck * hits + POINTS.dog * dog_hits
                 + POINTS.miss * (shots - hits - dog_hits))
        # spread over the last fortnight, evenings, with some of it tonight
        when = now - timedelta(days=rng.triangular(0, 14, 1),
                               minutes=rng.randint(0, 240))
        store.insert_run(conn, {
            "run_uuid": _uuid_for("demo", i, name, hits, shots),
            "name": name, "hits": hits, "shots": shots, "ducks": ducks,
            "score": score, "dog_hits": dog_hits,
            # some of the evening was shot with the crosshair on and some without,
            # because the column exists for telling those apart one day
            "crosshair": rng.random() < 0.4,
            "duration": round(rng.uniform(52, 78), 1),
            "started_at": (when - timedelta(seconds=65)).isoformat(),
            "finished_at": when.isoformat(),
            "client_id": "demo", "input_source": rng.choice(["serial", "udp", "mouse"]),
            "game_version": "demo", "settings": None})
    return count


def clear_demo(conn) -> int:
    """Take the invented rounds back out — they are all `client_id = 'demo'`.

    So the board can be filled up to look at and emptied before the real evening
    starts, without touching a row anybody actually shot.
    """
    with conn:
        cur = conn.execute("DELETE FROM runs WHERE client_id = 'demo'")
    return cur.rowcount


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python3 -m leaderboard.seed",
                                 description="Seed the leaderboard database")
    ap.add_argument("--db", default=store.default_path())
    ap.add_argument("--from-scores", action="store_true",
                    help="import the game's local scores.json")
    ap.add_argument("--scores", metavar="FILE", help="a scores.json somewhere else")
    ap.add_argument("--demo", type=int, metavar="N", default=0,
                    help="add N invented rounds, by invented players")
    ap.add_argument("--clear-demo", action="store_true",
                    help="delete every invented round again (client_id = demo), "
                         "leaving the real ones where they are")
    ap.add_argument("--ducks", type=int, default=100, help="round size for --demo")
    args = ap.parse_args(argv)

    store.init(args.db)
    with store.connect(args.db) as conn:
        if args.from_scores or args.scores:
            print(f"imported {from_scores(conn, args.scores)} rounds from scores.json")
        if args.clear_demo:
            print(f"removed {clear_demo(conn)} demo rounds")
        if args.demo:
            print(f"added {demo(conn, args.demo, args.ducks)} demo rounds")
        if not (args.from_scores or args.scores or args.demo or args.clear_demo):
            print("nothing to do: pass --from-scores, --demo N or --clear-demo")
        rows = store.board(conn, args.ducks, 10)
    for i, r in enumerate(rows, 1):
        tries = "try" if r["attempts"] == 1 else "tries"
        print(f"  {i:>2}. {r['name'][:20]:<20} {r['score']:>5} pts  "
              f"{r['hits']:>3} ducks  {r['accuracy']:>3.0f}%  "
              f"{r['attempts']:>3} {tries}")


if __name__ == "__main__":
    main()
