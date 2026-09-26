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
    accuracy     REAL    NOT NULL,
    duration     REAL    NOT NULL,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT    NOT NULL,
    client_id    TEXT    NOT NULL,
    input_source TEXT,
    game_version TEXT,
    settings     TEXT
);
CREATE INDEX IF NOT EXISTS runs_board  ON runs (ducks, hits DESC, shots ASC, finished_at ASC);
CREATE INDEX IF NOT EXISTS runs_player ON runs (player_key, hits DESC, shots ASC);
"""

# Best run per player, ranked the way the game's own table ranks: more hits
# first, then fewer shots, then whoever got there first. `attempts` falls out of
# the same pass.
_BEST_PER_PLAYER = """
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY player_key
                              ORDER BY hits DESC, shots ASC, finished_at ASC) AS rn,
           COUNT(*)     OVER (PARTITION BY player_key) AS attempts
    FROM runs
    WHERE ducks = :ducks {extra}
"""


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


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or default_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init(path: str | None = None) -> None:
    """Create the table and its indexes if they are not there yet."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)


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
    with conn:
        cur = conn.execute(
            """INSERT INTO runs (run_uuid, player_key, name, hits, shots, ducks,
                                 accuracy, duration, started_at, finished_at,
                                 client_id, input_source, game_version, settings)
               VALUES (:run_uuid, :player_key, :name, :hits, :shots, :ducks,
                       :accuracy, :duration, :started_at, :finished_at,
                       :client_id, :input_source, :game_version, :settings)
               ON CONFLICT(run_uuid) DO NOTHING""",
            {**run, "player_key": key, "accuracy": accuracy})
        fresh = cur.rowcount == 1
    return {**answer(conn, run["run_uuid"]), "duplicate": not fresh}


def answer(conn: sqlite3.Connection, run_uuid: str) -> dict:
    """What the game is told about a stored run: its rank, and its own best."""
    row = conn.execute("SELECT * FROM runs WHERE run_uuid = ?", (run_uuid,)).fetchone()
    if row is None:
        return {"ok": False, "error": "no such run"}
    ducks, key = row["ducks"], row["player_key"]

    rank = conn.execute(f"""
        WITH ranked AS (
            SELECT player_key, hits,
                   ROW_NUMBER() OVER (ORDER BY hits DESC, shots ASC, finished_at ASC) AS rn,
                   COUNT(*)     OVER () AS total
            FROM ({_BEST_PER_PLAYER.format(extra='')}) WHERE rn = 1
        )
        SELECT rn, total FROM ranked WHERE player_key = :key
    """, {"ducks": ducks, "key": key}).fetchone()

    best = conn.execute(
        "SELECT MAX(hits) AS h FROM runs WHERE player_key = ? AND ducks = ?",
        (key, ducks)).fetchone()["h"]
    # the best BEFORE this round — so "new personal best" means what it says
    previous = conn.execute(
        """SELECT MAX(hits) AS h FROM runs
           WHERE player_key = ? AND ducks = ? AND run_uuid != ?""",
        (key, ducks, run_uuid)).fetchone()["h"]
    attempts = conn.execute(
        "SELECT COUNT(*) AS n FROM runs WHERE player_key = ? AND ducks = ?",
        (key, ducks)).fetchone()["n"]
    record = conn.execute(
        """SELECT name, hits FROM runs WHERE ducks = ?
           ORDER BY hits DESC, shots ASC, finished_at ASC LIMIT 1""",
        (ducks,)).fetchone()

    return {"ok": True,
            "rank": rank["rn"] if rank else None,
            "of": rank["total"] if rank else 0,
            "personal_best": best,
            "previous_best": previous,
            "improved": previous is None or row["hits"] > previous,
            "attempts": attempts,
            "world_record": ({"name": record["name"], "hits": record["hits"]}
                             if record else None)}


def board(conn: sqlite3.Connection, ducks: int = 100, limit: int = 10,
          window: str = "all", order: str = "best") -> list[dict]:
    """The board: one row per player, their best run.

    `order = "attempts"` ranks by who has played most instead — the third panel
    of the display's attract mode, and the same query either way.
    """
    by = ("attempts DESC, hits DESC, shots ASC" if order == "attempts"
          else "hits DESC, shots ASC, finished_at ASC")
    rows = conn.execute(f"""
        SELECT name, hits, shots, ducks, accuracy, duration, finished_at, attempts
        FROM ({_BEST_PER_PLAYER.format(extra=_window(window))})
        WHERE rn = 1 ORDER BY {by} LIMIT :limit
    """, {"ducks": ducks, "limit": max(1, min(100, limit))}).fetchall()
    return [dict(r) for r in rows]


def player(conn: sqlite3.Connection, name: str, ducks: int = 100,
           limit: int = 20) -> dict:
    """One player: their best run, how many times they tried, and the recent ones."""
    key = player_key(name)
    best = conn.execute("""
        SELECT name, hits, shots, ducks, accuracy, duration, finished_at
        FROM runs WHERE player_key = :key AND ducks = :ducks
        ORDER BY hits DESC, shots ASC, finished_at ASC LIMIT 1
    """, {"key": key, "ducks": ducks}).fetchone()
    history = conn.execute("""
        SELECT hits, shots, accuracy, duration, finished_at
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


def stats(conn: sqlite3.Connection, ducks: int = 100) -> dict:
    """The numbers the running line is built from, in one call."""
    row = conn.execute("""
        SELECT COUNT(*) AS rounds, COUNT(DISTINCT player_key) AS players,
               COALESCE(SUM(hits), 0) AS ducks_down,
               COALESCE(SUM(shots), 0) AS shots
        FROM runs WHERE ducks = :ducks
    """, {"ducks": ducks}).fetchone()
    today = conn.execute(f"""
        SELECT name, hits FROM runs
        WHERE ducks = :ducks {_window('today')}
        ORDER BY hits DESC, shots ASC, finished_at ASC LIMIT 1
    """, {"ducks": ducks}).fetchone()
    record = conn.execute("""
        SELECT name, hits FROM runs WHERE ducks = :ducks
        ORDER BY hits DESC, shots ASC, finished_at ASC LIMIT 1
    """, {"ducks": ducks}).fetchone()
    last = conn.execute("""
        SELECT id, name, hits, shots, accuracy, finished_at FROM runs
        WHERE ducks = :ducks ORDER BY id DESC LIMIT 1
    """, {"ducks": ducks}).fetchone()
    latest = dict(last) if last else None
    if latest is not None and record is not None:
        # "is_record" as the ticker means it: this run IS the standing record
        latest["is_record"] = (latest["hits"] == record["hits"]
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
