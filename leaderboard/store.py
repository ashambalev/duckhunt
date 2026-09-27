"""SQLite behind the leaderboard: one table, and every query the board needs.

Every attempt is a row. The "top ten" is never stored — it is a query over the
best run per player, which is why keeping every row costs nothing and buys the
fun part: `66 ducks (12 tries)`.

One writer and a handful of rows per minute, so there is nothing to tune beyond
WAL (the display's reads must not block a write) and a busy timeout for the rare
overlap. A connection per request; nothing shared between threads.
"""

from __future__ import annotations

import os
import sqlite3
import unicodedata
from datetime import datetime, timezone

DB_NAME = "leaderboard.db"
NAME_MAX = 50          # the same limit the game's name entry uses

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid     TEXT    NOT NULL UNIQUE,
    player_key   TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    hits         INTEGER NOT NULL,
    shots        INTEGER NOT NULL,
    ducks        INTEGER NOT NULL,
    score        INTEGER NOT NULL DEFAULT 0,
    dog_hits     INTEGER NOT NULL DEFAULT 0,
    crosshair    INTEGER NOT NULL DEFAULT 0,
    accuracy     REAL    NOT NULL,
    duration     REAL    NOT NULL,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT    NOT NULL,
    client_id    TEXT    NOT NULL,
    input_source TEXT,
    game_version TEXT,
    settings     TEXT
);
"""

# The indexes are applied after the migration rather than with the table,
# because they name `score` and a database written before the score existed has
# no such column until `_migrate` has run. New names, not new definitions under
# the old ones: `CREATE INDEX IF NOT EXISTS runs_board` over an index that is
# already there is a silent no-op, so the ones that rank by hits are dropped by
# name in `_migrate` and these take over.
INDEXES = """
CREATE INDEX IF NOT EXISTS runs_board_v2
    ON runs (ducks, score DESC, hits DESC, shots ASC, finished_at ASC);
CREATE INDEX IF NOT EXISTS runs_player_v2
    ON runs (player_key, score DESC, hits DESC, shots ASC);
"""

# How a round is ranked, here and in every ORDER BY below. The score leads,
# because it is the number the game plays for now and the one both boards show:
# a duck is worth `[score] duck`, a miss and the dog cost their own amount, so
# hits stopped being the score the moment firing started costing something. Hits
# are the first tiebreaker all the same — between two rounds that scored the
# same, the one that downed more ducks is the better round — then fewer shots,
# then whoever got there first.
RANK = "score DESC, hits DESC, shots ASC, finished_at ASC"

# Best run per player, ranked the way the game's own table ranks. `attempts`
# falls out of the same pass.
_BEST_PER_PLAYER = f"""
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY player_key
                              ORDER BY {RANK}) AS rn,
           COUNT(*)     OVER (PARTITION BY player_key) AS attempts
    FROM runs
    WHERE ducks = :ducks {{extra}}
"""

# What the score brought with it, and how each column is added to a table that
# already has rounds in it. `leaderboard.db` exists and is not empty, and CREATE
# TABLE IF NOT EXISTS adds nothing to a table that is already there, so these
# arrive by ALTER TABLE instead. `crosshair` is stored and handed back and
# nothing here reads it: whether a round shot with the crosshair on belongs on
# the same board is a decision for whoever makes it, and the board cannot make
# it later from rows that never recorded it.
_ADDED_COLUMNS = (
    ("score",     "score INTEGER NOT NULL DEFAULT 0"),
    ("dog_hits",  "dog_hits INTEGER NOT NULL DEFAULT 0"),
    ("crosshair", "crosshair INTEGER NOT NULL DEFAULT 0"),
)


def default_path() -> str:
    """`leaderboard.db` in the project root, next to settings.toml."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", DB_NAME)


def player_key(name: str) -> str:
    """Who counts as the same player: `Eugene`, `eugene` and `  Eugene ` are one.

    No accounts, no passwords — this is a party scoreboard. The board shows the
    spelling from their best run; the key is what groups the attempts.
    """
    return " ".join(name.split()).casefold()


def search_key(name: str) -> str:
    """The key the name *search* matches on: blind to case and to accents.

    `player_key` already folds case, which is what groups the attempts. The search
    folds one step harder, because nobody reaches for an accent while typing into a
    name box: it also strips combining marks (NFKD, combining characters dropped),
    so `José` is reachable by `jose`, on both sides of the comparison. It is never
    stored and never shown — the name goes back out spelled the way it was first
    typed.

    What this does NOT fix is homoglyphs: a `Женя` typed with a Latin `e` is a
    different string after every fold there is, and finding it would take a
    confusable table rather than a normal form. Substring matching hides most of
    that in practice — `жен` still finds it — and a party scoreboard is not the
    place for Unicode security work.
    """
    folded = unicodedata.normalize("NFKD", player_key(name))
    return "".join(c for c in folded if not unicodedata.combining(c))


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or default_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    # `search_players` needs Python's Unicode folding inside SQL; SQLite's own
    # LIKE only knows ASCII case. Deterministic, so SQLite may cache it.
    conn.create_function("fold", 1, search_key, deterministic=True)
    return conn


def init(path: str | None = None) -> None:
    """Create the table, bring an older one up to date, then the indexes.

    In that order and in three steps rather than one script, because the indexes
    rank by `score` and a database from before the score has to grow the column
    first. Safe to call on every start: each step does nothing when there is
    nothing left to do.
    """
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(INDEXES)


def _migrate(conn: sqlite3.Connection) -> None:
    """Grow a database written before the score into the shape above.

    Idempotent, because `init()` runs it every time: a column is added only when
    PRAGMA table_info says it is missing, and dropping an index that is already
    gone is not an error.
    """
    have = {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}
    for column, ddl in _ADDED_COLUMNS:
        if column not in have:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {ddl}")
    if "score" not in have:
        # The rows already in the table were played when a duck was worth one
        # point and neither a miss nor the dog cost anything, so the score of
        # such a round was its hit count exactly. That is arithmetic on the rule
        # those rounds were played under, not a guess at what they would have
        # scored under this one — which is unknowable, because nobody counted
        # the dog then. It happens once: the column exists afterwards, so no
        # later `init()` can walk over a score somebody really shot.
        conn.execute("UPDATE runs SET score = hits")
    # The old indexes lead with hits, which stopped ordering the board the
    # moment a miss cost a point. Dropped by name, since the replacements above
    # are IF NOT EXISTS under names of their own and would otherwise simply be
    # built beside two indexes nothing uses any more.
    conn.execute("DROP INDEX IF EXISTS runs_board")
    conn.execute("DROP INDEX IF EXISTS runs_player")


def _window(window: str) -> str:
    """The extra WHERE for a time-limited board. Unknown windows mean all time."""
    if window == "today":
        # local day, not UTC: an evening's rounds belong to that evening
        return "AND date(finished_at) = date('now', 'localtime')"
    if window == "week":
        return "AND finished_at >= datetime('now', '-7 days')"
    return ""


def insert_run(conn: sqlite3.Connection, run: dict) -> dict:
    """Store one finished round and answer with everything about where it lands.

    Idempotent on `run_uuid`: the game retries a failed POST, and a retry must
    not add a second row or a second entry in the attempt count. The answer is
    computed from the stored row afterwards, so a retry says the same thing the
    first call did.
    """
    key = player_key(run["name"])
    accuracy = (run["hits"] / run["shots"] * 100.0) if run["shots"] else 0.0
    # A round that arrives without a score was shot by a game that predates it,
    # under the rule where a duck was one point and nothing cost anything — so
    # its hit count is its score, which is the same arithmetic the migration
    # does for the rows that were already in the table.
    row = {**run, "player_key": key, "accuracy": accuracy,
           "score": int(run.get("score", run["hits"])),
           "dog_hits": int(run.get("dog_hits", 0)),
           "crosshair": int(bool(run.get("crosshair", False)))}
    with conn:
        cur = conn.execute(
            """INSERT INTO runs (run_uuid, player_key, name, hits, shots, ducks,
                                 score, dog_hits, crosshair,
                                 accuracy, duration, started_at, finished_at,
                                 client_id, input_source, game_version, settings)
               VALUES (:run_uuid, :player_key, :name, :hits, :shots, :ducks,
                       :score, :dog_hits, :crosshair,
                       :accuracy, :duration, :started_at, :finished_at,
                       :client_id, :input_source, :game_version, :settings)
               ON CONFLICT(run_uuid) DO NOTHING""",
            row)
        fresh = cur.rowcount == 1
    return {**answer(conn, run["run_uuid"]), "duplicate": not fresh}


def answer(conn: sqlite3.Connection, run_uuid: str) -> dict:
    """What the game is told about a stored run: its rank, and its own best.

    A personal best is a better *score* now, not more ducks: a round that downed
    fewer and wasted nothing can be the better round, and telling a player they
    have not improved when the number on the board went up would be a lie.
    """
    row = conn.execute("SELECT * FROM runs WHERE run_uuid = ?", (run_uuid,)).fetchone()
    if row is None:
        return {"ok": False, "error": "no such run"}
    ducks, key = row["ducks"], row["player_key"]

    rank = conn.execute(f"""
        WITH ranked AS (
            SELECT player_key, score, hits,
                   ROW_NUMBER() OVER (ORDER BY {RANK}) AS rn,
                   COUNT(*)     OVER () AS total
            FROM ({_BEST_PER_PLAYER.format(extra='')}) WHERE rn = 1
        )
        SELECT rn, total FROM ranked WHERE player_key = :key
    """, {"ducks": ducks, "key": key}).fetchone()

    best = conn.execute(
        "SELECT MAX(score) AS s FROM runs WHERE player_key = ? AND ducks = ?",
        (key, ducks)).fetchone()["s"]
    # the best BEFORE this round — so "new personal best" means what it says
    previous = conn.execute(
        """SELECT MAX(score) AS s FROM runs
           WHERE player_key = ? AND ducks = ? AND run_uuid != ?""",
        (key, ducks, run_uuid)).fetchone()["s"]
    attempts = conn.execute(
        "SELECT COUNT(*) AS n FROM runs WHERE player_key = ? AND ducks = ?",
        (key, ducks)).fetchone()["n"]
    record = conn.execute(
        f"""SELECT name, score, hits FROM runs WHERE ducks = ?
           ORDER BY {RANK} LIMIT 1""",
        (ducks,)).fetchone()

    return {"ok": True,
            "rank": rank["rn"] if rank else None,
            "of": rank["total"] if rank else 0,
            "score": row["score"],
            "hits": row["hits"],
            "dog_hits": row["dog_hits"],
            "personal_best": best,
            "previous_best": previous,
            "improved": previous is None or row["score"] > previous,
            "attempts": attempts,
            "world_record": ({"name": record["name"], "score": record["score"],
                              "hits": record["hits"]} if record else None)}


def board(conn: sqlite3.Connection, ducks: int = 100, limit: int = 10,
          window: str = "all", order: str = "best") -> list[dict]:
    """The board: one row per player, their best run.

    `order = "attempts"` ranks by who has played most instead — the third panel
    of the display's attract mode, and the same query either way.
    """
    by = (f"attempts DESC, {RANK}" if order == "attempts" else RANK)
    rows = conn.execute(f"""
        SELECT name, score, hits, dog_hits, crosshair, shots, ducks, accuracy,
               duration, finished_at, attempts
        FROM ({_BEST_PER_PLAYER.format(extra=_window(window))})
        WHERE rn = 1 ORDER BY {by} LIMIT :limit
    """, {"ducks": ducks, "limit": max(1, min(100, limit))}).fetchall()
    return [dict(r) for r in rows]


def player(conn: sqlite3.Connection, name: str, ducks: int = 100,
           limit: int = 20) -> dict:
    """One player: their best run, how many times they tried, and the recent ones."""
    key = player_key(name)
    best = conn.execute(f"""
        SELECT name, score, hits, dog_hits, crosshair, shots, ducks, accuracy,
               duration, finished_at
        FROM runs WHERE player_key = :key AND ducks = :ducks
        ORDER BY {RANK} LIMIT 1
    """, {"key": key, "ducks": ducks}).fetchone()
    history = conn.execute("""
        SELECT score, hits, dog_hits, shots, accuracy, duration, finished_at
        FROM runs WHERE player_key = :key AND ducks = :ducks
        ORDER BY finished_at DESC LIMIT :limit
    """, {"key": key, "ducks": ducks, "limit": max(1, min(200, limit))}).fetchall()
    attempts = conn.execute(
        "SELECT COUNT(*) AS n FROM runs WHERE player_key = ? AND ducks = ?",
        (key, ducks)).fetchone()["n"]
    return {"name": best["name"] if best else name,
            "attempts": attempts,
            "best": dict(best) if best else None,
            "history": [dict(r) for r in history]}


def search_players(conn: sqlite3.Connection, q: str = "",
                   limit: int = 8) -> list[dict]:
    """The names already on the board that look like what is being typed.

    This is what stops `Женя`, `женя` and `Zhenya` becoming three players: the
    name entry asks as you type and offers what is there to pick instead. Three
    decisions worth knowing about:

    - **Every round size at once.** The board keeps 40-duck and 100-duck rounds
      apart on purpose, but a name is a name whatever they played, and a search
      that hid a regular because tonight's round is a different length would
      recreate the very duplicate it exists to prevent. So the score that comes
      back carries its own `ducks` and says `40/40`. Which round is "their best"
      is then a question the board never has to ask, and a raw total answers it
      wrongly: `45/100` is a worse round than `40/40` and would have outranked
      it. The score is no better at this than hits were — a 100-duck round can
      out-point a flawless 40-duck one simply by being longer — so the pick here
      is by score PER DUCK, with the score and then the hits to break a tie: the
      board's ranking, divided by the only thing that differs between the
      boards. The share of the flock downed no longer leads it, because the
      rounds this has to compare are now told apart by what the shooting cost as
      well as by what it caught.
    - **The spelling that comes back is the first one they used**, not the one on
      their best run: it is the name they will recognise, and picking it keeps
      every later round under the same key regardless.
    - **Empty `q` is not an error**, it is the screen opening: the most recent
      players, which after one evening is exactly the right guess.
    """
    pattern = search_key(q)
    # Between two matching players, the same measure their own best row was picked
    # by — the share of the flock downed. Raw score here would have reintroduced,
    # one level up, exactly the round-size unfairness the row-picking avoids: a
    # 100-duck regular would sit above a 40-duck one for having played longer.
    order = ("b.score * 1.0 / b.ducks DESC, b.score DESC, b.hits DESC, "
             "g.attempts DESC" if pattern else
             "g.last_played DESC, g.attempts DESC")
    rows = conn.execute(f"""
        SELECT (SELECT name FROM runs f
                WHERE f.player_key = g.player_key
                ORDER BY id ASC LIMIT 1) AS name,
               g.attempts, g.last_played,
               b.score, b.hits, b.shots, b.ducks, b.accuracy, b.finished_at
        FROM (SELECT player_key, COUNT(*) AS attempts,
                     MAX(finished_at) AS last_played
              FROM runs GROUP BY player_key) g
        JOIN runs b ON b.id = (SELECT id FROM runs r
                               WHERE r.player_key = g.player_key
                               ORDER BY score * 1.0 / ducks DESC, score DESC,
                                        hits DESC, shots ASC, finished_at ASC
                               LIMIT 1)
        WHERE :pattern = '' OR instr(fold(g.player_key), :pattern) > 0
        ORDER BY CASE WHEN instr(fold(g.player_key), :pattern) = 1
                      THEN 0 ELSE 1 END, {order}
        LIMIT :limit
    """, {"pattern": pattern,
          "limit": max(1, min(50, limit))}).fetchall()
    return [dict(r) for r in rows]


def stats(conn: sqlite3.Connection, ducks: int = 100) -> dict:
    """The numbers the running line is built from, in one call."""
    row = conn.execute("""
        SELECT COUNT(*) AS rounds, COUNT(DISTINCT player_key) AS players,
               COALESCE(SUM(hits), 0) AS ducks_down,
               COALESCE(SUM(shots), 0) AS shots
        FROM runs WHERE ducks = :ducks
    """, {"ducks": ducks}).fetchone()
    today = conn.execute(f"""
        SELECT name, score, hits FROM runs
        WHERE ducks = :ducks {_window('today')}
        ORDER BY {RANK} LIMIT 1
    """, {"ducks": ducks}).fetchone()
    record = conn.execute(f"""
        SELECT name, score, hits FROM runs WHERE ducks = :ducks
        ORDER BY {RANK} LIMIT 1
    """, {"ducks": ducks}).fetchone()
    last = conn.execute("""
        SELECT id, name, score, hits, dog_hits, shots, accuracy, finished_at
        FROM runs WHERE ducks = :ducks ORDER BY id DESC LIMIT 1
    """, {"ducks": ducks}).fetchone()
    latest = dict(last) if last else None
    if latest is not None and record is not None:
        # "is_record" as the ticker means it: this run IS the standing record —
        # on the score, which is what the board is ranked by
        latest["is_record"] = (latest["score"] == record["score"]
                               and latest["name"] == record["name"])
    # Which round sizes exist at all. A 40-duck round and a 100-duck round do
    # not compete, so they are separate boards — and a board that is empty
    # because every round was a different size has to be able to say so, or it
    # reads as "the game is not saving anything".
    sizes = conn.execute(
        "SELECT ducks, COUNT(*) AS runs FROM runs GROUP BY ducks "
        "ORDER BY runs DESC").fetchall()
    return {"ducks": ducks,
            "sizes": [dict(r) for r in sizes],
            "rounds": row["rounds"], "players": row["players"],
            "ducks_down": row["ducks_down"], "shots": row["shots"],
            "today_best": dict(today) if today else None,
            "record": dict(record) if record else None,
            "latest": latest,
            "server_time": datetime.now(timezone.utc).isoformat(
                timespec="seconds").replace("+00:00", "Z")}
