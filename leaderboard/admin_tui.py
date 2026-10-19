"""The interactive screen of `python3 -m leaderboard.admin`: curses, no extra deps.

Two lists, Tab between them: PLAYERS (who is on the board) and ROUNDS (newest
first — the one to open when a test shot has just landed on the board). Enter on
a player opens their rounds. Space marks rows; an action applies to the marked
rows, or to the highlighted one when nothing is marked. Every change can be taken
back with U, and the lists reload by themselves every two seconds, so a round
played while this is open shows up without touching anything.
"""

from __future__ import annotations

import codecs
import curses
import locale
import os

from .admin import Admin, AdminError, best_text, when

REFRESH_MS = 2000

HELP = {
    "players": "↑↓ move  SPACE mark  ENTER rounds  R rename  M merge marked "
               "into this  D delete  / filter  U undo  TAB rounds  Q quit",
    "runs": "↑↓ move  SPACE mark  D delete  U undo  ESC back  TAB players  "
            "Q quit",
}


class Screen:
    def __init__(self, scr, admin: Admin):
        self.scr, self.admin = scr, admin
        self.view = "players"
        self.filter = ""              # the players list's search text
        self.who: str | None = None   # the rounds list's player, None = everyone
        self.rows: list[dict] = []
        self.at = 0                   # the highlighted row
        self.top = 0                  # the first row on screen
        self.marked: set = set()
        self.msg = ""

    # ---- data ----

    def key_of(self, row: dict):
        return row["player_key"] if self.view == "players" else row["id"]

    def reload(self) -> None:
        """Fetch the list again, keeping the highlight on the same row."""
        current = self.key_of(self.rows[self.at]) if self.rows else None
        self.rows = (self.admin.players(self.filter) if self.view == "players"
                     else self.admin.runs(self.who))
        keys = [self.key_of(r) for r in self.rows]
        self.marked &= set(keys)
        self.at = keys.index(current) if current in keys else min(
            self.at, max(0, len(self.rows) - 1))

    def switch(self, view: str, who: str | None = None) -> None:
        self.view, self.who = view, who
        self.rows, self.at, self.top, self.marked = [], 0, 0, set()
        self.reload()

    def chosen(self) -> list[dict]:
        """The marked rows, or the highlighted one when nothing is marked."""
        if self.marked:
            return [r for r in self.rows if self.key_of(r) in self.marked]
        return [self.rows[self.at]] if self.rows else []

    # ---- drawing ----

    def put(self, y: int, x: int, text: str, attr: int = 0) -> None:
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and x < w:
            try:
                self.scr.addnstr(y, x, text, w - x - (y == h - 1), attr)
            except curses.error:
                pass

    def draw(self) -> None:
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        players = len(self.admin.players()) if self.view == "runs" else len(self.rows)
        title = (f" DUCK HUNT · BOARD ADMIN   {players} players   "
                 f"{self.admin.db}")
        self.put(0, 0, title.ljust(w), curses.A_REVERSE | curses.A_BOLD)

        if self.view == "players":
            sub = f" PLAYERS{f'   filter: {self.filter}' if self.filter else ''}"
            head = f"   {'NAME':<26}{'ROUNDS':>7}   {'LAST PLAYED':<13}BEST (ROUND SIZE)"
        else:
            sub = f" ROUNDS — {self.who if self.who else 'everyone, newest first'}"
            head = (f"   {'ID':>6}  {'WHEN':<12}{'NAME':<26}{'SCORE':>6}"
                    f"{'HITS/SHOTS':>12}{'DUCKS':>7}")
        self.put(1, 0, sub, curses.A_BOLD)
        self.put(2, 0, head, curses.A_UNDERLINE)

        body = max(1, h - 5)
        if self.at < self.top:
            self.top = self.at
        elif self.at >= self.top + body:
            self.top = self.at - body + 1
        for i, r in enumerate(self.rows[self.top:self.top + body]):
            n = self.top + i
            mark = "●" if self.key_of(r) in self.marked else " "
            if self.view == "players":
                line = (f" {mark} {r['name'][:25]:<26}{r['rounds']:>7}   "
                        f"{when(r['last_played']):<13}{best_text(r['best'])}")
            else:
                line = (f" {mark} {r['id']:>6}  {when(r['finished_at']):<12}"
                        f"{r['name'][:25]:<26}{r['score']:>6}"
                        f"{r['hits']:>7}/{r['shots']:<4}{r['ducks']:>7}")
            self.put(3 + i, 0, line.ljust(w),
                     curses.A_REVERSE if n == self.at else 0)
        if not self.rows:
            self.put(3, 3, "nothing here", curses.A_DIM)

        self.put(h - 2, 0, f" {self.msg}", curses.A_BOLD)
        self.put(h - 1, 0, f" {HELP[self.view]}", curses.A_DIM)
        self.scr.refresh()

    # ---- asking ----

    def ask(self, label: str, initial: str = "") -> str | None:
        """A line of text at the bottom, Unicode included. Esc gives None."""
        buf = list(initial)
        utf8 = codecs.getincrementaldecoder("utf-8")("ignore")
        self.scr.timeout(-1)
        curses.curs_set(1)
        try:
            while True:
                h, w = self.scr.getmaxyx()
                text = f" {label}: {''.join(buf)}"
                self.put(h - 2, 0, text.ljust(w), curses.A_BOLD)
                self.scr.move(h - 2, min(len(text), w - 1))
                # Bytes, decoded here: a curses built without wide-character
                # support hands Женя over one byte at a time, as Ð and friends.
                ch = self.scr.getch()
                if ch in (10, 13, curses.KEY_ENTER):
                    return "".join(buf)
                if ch == 27:
                    return None
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    if buf:
                        buf.pop()
                elif 0 <= ch < 256:
                    buf += [c for c in utf8.decode(bytes([ch])) if c.isprintable()]
        finally:
            curses.curs_set(0)
            self.scr.timeout(REFRESH_MS)

    def confirm(self, question: str) -> bool:
        answer = self.ask(f"{question} y/N")
        return answer is not None and answer.strip().lower() in ("y", "yes")

    def queued_note(self, names) -> str:
        n = sum(self.admin.queued(x) for x in names)
        return (f"   ({n} queued round(s) under the old name will still arrive)"
                if n else "")

    # ---- actions ----

    def rename(self) -> None:
        p = self.rows[self.at]
        new = self.ask(f"rename {p['name']!r} to", p["name"])
        if not new or new == p["name"]:
            self.msg = "rename cancelled"
            return
        taken = self.admin.find(new)
        if (taken and taken["player_key"] != p["player_key"]
                and not self.confirm(f"{taken['name']!r} is already on the board "
                                     f"— merge into it?")):
            self.msg = "rename cancelled"
            return
        n = self.admin.rename(p["name"], new)
        self.msg = (f"renamed {n} round(s) to {' '.join(new.split())!r}"
                    + self.queued_note([p["player_key"]]))

    def merge(self) -> None:
        into = self.rows[self.at]
        others = [r for r in self.rows if r["player_key"] in self.marked
                  and r["player_key"] != into["player_key"]]
        if not others:
            self.msg = ("mark the duplicates with SPACE, then press M on the "
                        "name to keep")
            return
        names = ", ".join(r["name"] for r in others)
        if not self.confirm(f"merge {names} into {into['name']!r}?"):
            self.msg = "merge cancelled"
            return
        n = self.admin.merge([r["name"] for r in others], into["name"])
        self.marked.clear()
        self.msg = (f"merged — {n} round(s) now under {into['name']!r}"
                    + self.queued_note(r["player_key"] for r in others))

    def delete(self) -> None:
        rows = self.chosen()
        if not rows:
            return
        if self.view == "players":
            rounds = sum(r["rounds"] for r in rows)
            names = ", ".join(r["name"] for r in rows)
            if not self.confirm(f"delete {names} ({rounds} round(s))?"):
                self.msg = "delete cancelled"
                return
            for r in rows:
                self.admin.delete_player(r["name"])
            self.msg = (f"deleted {names}, {rounds} round(s) — U to undo"
                        + self.queued_note(r["player_key"] for r in rows))
        else:
            ids = [r["id"] for r in rows]
            if not self.confirm(f"delete round(s) {', '.join(map(str, ids))}?"):
                self.msg = "delete cancelled"
                return
            self.admin.delete_runs(ids)
            self.msg = f"deleted {len(ids)} round(s) — U to undo"
        self.marked.clear()

    def undo(self) -> None:
        last = next((e for e in reversed(self.admin.history())
                     if "rows" in e and not e["undone"]), None)
        if last is None:
            self.msg = "nothing to undo"
        elif self.confirm(f"undo “{last['what']}”?"):
            self.msg = f"undone: {self.admin.undo()}"

    # ---- the loop ----

    def handle(self, ch) -> bool:
        """One key. False ends the program."""
        n = len(self.rows)
        body = max(1, self.scr.getmaxyx()[0] - 5)
        if ch in ("q", "Q"):
            return False
        elif ch in (curses.KEY_UP, "k"):
            self.at = max(0, self.at - 1)
        elif ch in (curses.KEY_DOWN, "j"):
            self.at = min(max(0, n - 1), self.at + 1)
        elif ch == curses.KEY_PPAGE:
            self.at = max(0, self.at - body)
        elif ch == curses.KEY_NPAGE:
            self.at = min(max(0, n - 1), self.at + body)
        elif ch == curses.KEY_HOME:
            self.at = 0
        elif ch == curses.KEY_END:
            self.at = max(0, n - 1)
        elif ch == " " and self.rows:
            self.marked ^= {self.key_of(self.rows[self.at])}
            self.at = min(n - 1, self.at + 1)
        elif ch == "\t":
            self.switch("runs" if self.view == "players" else "players")
        elif ch in ("u", "U"):
            self.undo()
        elif ch in ("d", "D") and self.rows:
            self.delete()
        elif self.view == "players":
            if ch in ("\n", "\r", curses.KEY_ENTER) and self.rows:
                self.switch("runs", self.rows[self.at]["name"])
            elif ch in ("r", "R") and self.rows:
                self.rename()
            elif ch in ("m", "M") and self.rows:
                self.merge()
            elif ch == "/":
                text = self.ask("filter (empty = everyone)", self.filter)
                if text is not None:
                    self.filter = text.strip()
                    self.at = self.top = 0
            elif ch == "\x1b" and self.filter:
                self.filter, self.at = "", 0
        elif ch in ("\x1b", curses.KEY_BACKSPACE, "\x7f"):
            self.switch("players")
        return True

    def loop(self) -> None:
        curses.curs_set(0)
        curses.use_default_colors()
        self.scr.keypad(True)
        self.scr.timeout(REFRESH_MS)
        self.reload()
        while True:
            self.draw()
            try:
                ch = self.scr.get_wch()
            except curses.error:          # the refresh timeout: just reload
                self.reload()
                continue
            if ch == curses.KEY_RESIZE:
                continue
            try:
                if not self.handle(ch):
                    return
            except AdminError as exc:
                self.msg = f"error: {exc}"
            self.reload()


def run(admin: Admin) -> None:
    locale.setlocale(locale.LC_ALL, "")      # so Женя draws as Женя
    os.environ.setdefault("ESCDELAY", "25")  # Esc should not take a second
    curses.wrapper(lambda scr: Screen(scr, admin).loop())

