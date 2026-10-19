"""The staff's tool for the board: rename, merge and delete players and rounds.

    python3 -m leaderboard.admin                         # the TUI
    python3 -m leaderboard.admin players [TEXT]          # who is on the board
    python3 -m leaderboard.admin runs [NAME] [-n 50]     # the rounds, newest first
    python3 -m leaderboard.admin rename OLD NEW          # a typo, or a rude name
    python3 -m leaderboard.admin merge NAME... --into NAME
    python3 -m leaderboard.admin delete NAME             # a player and every round
    python3 -m leaderboard.admin delete-run ID...        # one round (a test shot)
    python3 -m leaderboard.admin history                 # what was changed, when
    python3 -m leaderboard.admin undo                    # take the last change back

A player is not a row anywhere: it is every round that shares a `player_key`
(the name with case and spacing folded, `store.player_key`). So a rename rewrites
the name and the key on those rounds, and a merge is a rename onto a key that is
already taken — `Zhenya` and `Женя` become one line on the board, with every
attempt of both counted under it.

Nothing here is a one-way door. Before every change the database is copied into
`leaderboard-backups/` (the last BACKUPS_KEEP of them are kept), and the rows the
change touched are written to `leaderboard-admin.jsonl` exactly as they were.
`undo` puts those rows back — and only those, so the rounds played since the
mistake stay on the board, which restoring a whole backup would not do.

Safe with the board up: SQLite in WAL mode lets the server keep reading and
writing, and the board shows the change on its next poll. With the server on
another box (a Pi), run this there — `--db` points at its file.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime

from . import store

BACKUPS_KEEP = 20
BACKUP_DIR = "leaderboard-backups"
PENDING_NAME = "pending_runs.jsonl"     # the game's queue of unsent rounds


class AdminError(Exception):
    """A change that cannot be made as asked — said to the operator, not raised."""


def clean_name(name: str) -> str:
    """The name the way the game would have sent it: spacing collapsed, capped."""
    name = " ".join(name.split())
    if not name:
        raise AdminError("an empty name is not a name")
    if len(name) > store.NAME_MAX:
        raise AdminError(f"names are at most {store.NAME_MAX} characters")
    return name


def when(iso: str) -> str:
    """`2026-10-14T18:01:00+00:00` as the local `10-14 20:01` it was played at."""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return str(iso)[:16]
    return t.astimezone().strftime("%m-%d %H:%M")


class Admin:
    """Every change the tool makes, on one database. The CLI and the TUI share it."""

    def __init__(self, db: str):
        if not os.path.exists(db):
            # init() would happily create an empty one, and an operator pointed at
            # the wrong path would then be told the board has nobody on it
            raise AdminError(f"no database at {db}")
        self.db = os.path.abspath(db)
        store.init(self.db)
        self.conn = store.connect(self.db)
        root = os.path.dirname(self.db)
        self.journal = os.path.splitext(self.db)[0] + "-admin.jsonl"
        self.backups = os.path.join(root, BACKUP_DIR)
        self.pending = os.path.join(root, PENDING_NAME)

    def close(self) -> None:
        self.conn.close()

    # ---- reading ----

    def players(self, q: str = "") -> list[dict]:
        """Every player, the most recently seen first; `q` narrows like the game's search.

        `name` is the spelling of their first round, the one the game's name
        list offers. `best` is per round size, because a 40-duck and a 100-duck
        score are on different boards: `{100: 55, 40: 30}`.
        """
        rows = self.conn.execute("""
            SELECT player_key,
                   (SELECT name FROM runs f WHERE f.player_key = g.player_key
                    ORDER BY id ASC LIMIT 1) AS name,
                   rounds, last_played
            FROM (SELECT player_key, COUNT(*) AS rounds,
                         MAX(finished_at) AS last_played, MAX(id) AS last_id
                  FROM runs GROUP BY player_key) g
            WHERE :q = '' OR instr(fold(player_key), :q) > 0
            ORDER BY last_played DESC, last_id DESC
        """, {"q": store.search_key(q)}).fetchall()
        best: dict[str, dict[int, int]] = {}
        for r in self.conn.execute("SELECT player_key, ducks, MAX(score) AS s "
                                   "FROM runs GROUP BY player_key, ducks"):
            best.setdefault(r["player_key"], {})[r["ducks"]] = r["s"]
        return [{**dict(r), "best": best.get(r["player_key"], {})} for r in rows]

    def find(self, name: str) -> dict | None:
        """The player a name means, by key — `женя` finds `Женя`."""
        key = store.player_key(name)
        return next((p for p in self.players() if p["player_key"] == key), None)

    def runs(self, name: str | None = None, limit: int = 200) -> list[dict]:
        """Rounds, newest first: everybody's, or one player's."""
        where, params = "", {"limit": max(1, limit)}
        if name is not None:
            where, params["key"] = "WHERE player_key = :key", store.player_key(name)
        return [dict(r) for r in self.conn.execute(f"""
            SELECT id, name, player_key, score, hits, shots, dog_hits, ducks,
                   finished_at
            FROM runs {where} ORDER BY id DESC LIMIT :limit""", params)]

    def queued(self, name: str) -> int:
        """Rounds under this name still in the game's offline queue.

        They reach the board the next time the game starts, under the name they
        were signed with — so a name deleted or renamed here can come back.
        """
        key, n = store.player_key(name), 0
        try:
            with open(self.pending, encoding="utf-8") as f:
                for line in f:
                    try:
                        n += store.player_key(json.loads(line).get("name", "")) == key
                    except (ValueError, AttributeError):
                        continue
        except OSError:
            pass
        return n

    # ---- changing ----

    def rename(self, old: str, new: str) -> int:
        """Every round of `old` signed `new` instead. Onto a taken name, a merge.

        Both players' rounds get the new spelling then, not only the moved ones:
        the board shows the spelling of a player's best round and the game's list
        the spelling of their first, and after a merge those must be one name.
        """
        new = clean_name(new)
        okey, nkey = store.player_key(old), store.player_key(new)
        if self.find(old) is None:
            raise AdminError(f"no player {old!r}")
        return self._change(
            f"rename {old!r} -> {new!r}", "player_key IN (?, ?)", (okey, nkey),
            "UPDATE runs SET name = ?, player_key = ? WHERE player_key IN (?, ?)",
            (new, nkey, okey, nkey))

    def merge(self, names: list[str], into: str) -> int:
        """`names` become `into`, under the spelling `into` already has."""
        target = self.find(into)
        if target is None:
            raise AdminError(f"no player {into!r}")
        keys = {target["player_key"]}
        for n in names:
            if self.find(n) is None:
                raise AdminError(f"no player {n!r}")
            keys.add(store.player_key(n))
        if len(keys) < 2:
            raise AdminError("nothing to merge: that is one player already")
        marks = ", ".join("?" * len(keys))
        return self._change(
            f"merge {', '.join(map(repr, names))} into {target['name']!r}",
            f"player_key IN ({marks})", tuple(keys),
            f"UPDATE runs SET name = ?, player_key = ? "
            f"WHERE player_key IN ({marks})",
            (target["name"], target["player_key"], *keys))

    def delete_player(self, name: str) -> int:
        if self.find(name) is None:
            raise AdminError(f"no player {name!r}")
        key = store.player_key(name)
        return self._change(f"delete player {name!r}", "player_key = ?", (key,),
                            "DELETE FROM runs WHERE player_key = ?", (key,))

    def delete_runs(self, ids: list[int]) -> int:
        ids = sorted({int(i) for i in ids})
        if not ids:
            raise AdminError("no rounds given")
        marks = ", ".join("?" * len(ids))
        return self._change(f"delete round{'s' * (len(ids) > 1)} "
                            f"{', '.join(map(str, ids))}",
                            f"id IN ({marks})", tuple(ids),
                            f"DELETE FROM runs WHERE id IN ({marks})", tuple(ids))

    def _change(self, what: str, where: str, where_args: tuple,
                sql: str, args: tuple) -> int:
        """Back up, remember the rows as they are, change them, write it down."""
        before = [dict(r) for r in self.conn.execute(
            f"SELECT * FROM runs WHERE {where}", where_args)]
        if not before:
            raise AdminError("no rounds match")
        self.backup()
        with self.conn:
            self.conn.execute(sql, args)
        self._log({"what": what, "rows": before})
        return len(before)

    # ---- the safety net ----

    def history(self) -> list[dict]:
        """The journal, oldest first, each entry marked `undone` once it is."""
        entries = []
        try:
            with open(self.journal, encoding="utf-8") as f:
                entries = [json.loads(line) for line in f if line.strip()]
        except (OSError, ValueError):
            return []
        undone = {e["undoes"] for e in entries if "undoes" in e}
        return [{**e, "undone": e["n"] in undone} for e in entries]

    def undo(self) -> str:
        """Put back the rows the last change touched, exactly as they were.

        Rows, not a backup file: a whole-file restore would also throw away
        every round played since, and at a booth that is the whole queue.
        """
        todo = [e for e in self.history() if "rows" in e and not e["undone"]]
        if not todo:
            raise AdminError("nothing to undo")
        last = todo[-1]
        self.backup()
        cols = list(last["rows"][0])
        with self.conn:
            self.conn.executemany(
                f"INSERT OR REPLACE INTO runs ({', '.join(cols)}) "
                f"VALUES ({', '.join(':' + c for c in cols)})", last["rows"])
        self._log({"what": f"undo: {last['what']}", "undoes": last["n"]})
        return last["what"]

    def backup(self) -> str:
        """A consistent copy of the live database, safe while the server writes."""
        os.makedirs(self.backups, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = os.path.join(self.backups, f"leaderboard-{stamp}.db")
        with closing(sqlite3.connect(path)) as dst:
            self.conn.backup(dst)
        for old in sorted(glob.glob(os.path.join(self.backups,
                                                 "leaderboard-*.db")))[:-BACKUPS_KEEP]:
            os.remove(old)
        return path

    def _log(self, entry: dict) -> None:
        entry = {"n": len(self.history()) + 1,
                 "at": datetime.now().isoformat(timespec="seconds"), **entry}
        with open(self.journal, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def best_text(best: dict) -> str:
    """`{100: 55, 40: 30}` as `55 (100) · 30 (40)`: the score, then the round size."""
    return " · ".join(f"{s} ({d})" for d, s in sorted(best.items(), reverse=True))


# ---- the command line ----

def _table(rows: list[list], heads: list[str]) -> None:
    rows = [[str(c) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h)
              for i, h in enumerate(heads)]
    print("  ".join(h.ljust(w) for h, w in zip(heads, widths)))
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))


def _confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _warn_queued(admin: Admin, *names: str) -> None:
    for n in names:
        if q := admin.queued(n):
            print(f"note: {q} round(s) for {n!r} are still in {PENDING_NAME} and "
                  f"will arrive under that name when the game next starts",
                  file=sys.stderr)


def cli(admin: Admin, args) -> int:
    if args.cmd == "players":
        ps = admin.players(" ".join(args.text))
        _table([[p["name"], p["rounds"], best_text(p["best"]),
                 when(p["last_played"])] for p in ps],
               ["NAME", "ROUNDS", "BEST (ROUND SIZE)", "LAST PLAYED"])
        print(f"\n{len(ps)} player(s)")
    elif args.cmd == "runs":
        rs = admin.runs(args.name, args.limit)
        _table([[r["id"], when(r["finished_at"]), r["name"], r["score"],
                 f"{r['hits']}/{r['shots']}", r["ducks"]] for r in rs],
               ["ID", "WHEN", "NAME", "SCORE", "HITS/SHOTS", "DUCKS"])
    elif args.cmd == "rename":
        taken = admin.find(args.new)
        if (taken and taken["player_key"] != store.player_key(args.old)
                and not _confirm(f"{taken['name']!r} is already on the board — "
                                 f"merge {args.old!r} into it?", args.yes)):
            return 1
        n = admin.rename(args.old, args.new)
        print(f"renamed {n} round(s) to {clean_name(args.new)!r}")
        _warn_queued(admin, args.old)
    elif args.cmd == "merge":
        target = admin.find(args.into)
        if target is None:
            raise AdminError(f"no player {args.into!r}")
        found = [admin.find(n) for n in args.names]
        if None in found:
            raise AdminError(f"no player {args.names[found.index(None)]!r}")
        moved = ", ".join(f"{p['name']!r} ({p['rounds']})" for p in found)
        if not _confirm(f"merge {moved} into {target['name']!r} "
                        f"({target['rounds']})?", args.yes):
            return 1
        n = admin.merge(args.names, args.into)
        print(f"merged — {n} round(s) now under {admin.find(args.into)['name']!r}")
        _warn_queued(admin, *args.names)
    elif args.cmd == "delete":
        p = admin.find(args.name)
        if p is None:
            raise AdminError(f"no player {args.name!r}")
        if not _confirm(f"delete {p['name']!r} and their {p['rounds']} "
                        f"round(s)?", args.yes):
            return 1
        print(f"deleted {admin.delete_player(args.name)} round(s)")
        _warn_queued(admin, args.name)
    elif args.cmd == "delete-run":
        if not _confirm(f"delete round(s) {', '.join(map(str, args.ids))}?",
                        args.yes):
            return 1
        print(f"deleted {admin.delete_runs(args.ids)} round(s)")
    elif args.cmd == "history":
        for e in admin.history():
            mark = "  (undone)" if e["undone"] else ""
            print(f"{e['n']:>4}  {e['at']}  {e['what']}{mark}")
    elif args.cmd == "undo":
        print(f"undone: {admin.undo()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m leaderboard.admin",
        description="Rename, merge and delete players and rounds on the board. "
                    "With no command: the interactive screen.")
    ap.add_argument("--db", default=store.default_path(),
                    help="the board's database (default: leaderboard.db in the "
                         "project root)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("players", help="list the players")
    p.add_argument("text", nargs="*", help="only names containing this")
    p = sub.add_parser("runs", help="list rounds, newest first")
    p.add_argument("name", nargs="?", help="only this player's")
    p.add_argument("-n", "--limit", type=int, default=50)
    p = sub.add_parser("rename", help="sign a player's rounds with another name")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("-y", "--yes", action="store_true",
                   help="merge without asking if the new name is taken")
    p = sub.add_parser("merge", help="make several players one")
    p.add_argument("names", nargs="+")
    p.add_argument("--into", required=True,
                   help="the player to keep; their spelling wins")
    p.add_argument("-y", "--yes", action="store_true")
    p = sub.add_parser("delete", help="delete a player and all their rounds")
    p.add_argument("name")
    p.add_argument("-y", "--yes", action="store_true")
    p = sub.add_parser("delete-run", help="delete rounds by id (see `runs`)")
    p.add_argument("ids", nargs="+", type=int)
    p.add_argument("-y", "--yes", action="store_true")
    sub.add_parser("history", help="every change made here, oldest first")
    sub.add_parser("undo", help="take the last change back")
    args = ap.parse_args(argv)

    try:
        admin = Admin(args.db)
    except AdminError as exc:
        ap.error(str(exc))
    try:
        if args.cmd is None:
            if not sys.stdin.isatty():
                ap.error("the interactive screen needs a terminal")
            from .admin_tui import run
            run(admin)
            return 0
        return cli(admin, args)
    except AdminError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        admin.close()


if __name__ == "__main__":
    sys.exit(main())
