"""High-score table: the best rounds, in `scores.json` next to settings.toml.

A round is `settings.round.ducks` ducks; what goes into the table is how many of
them were shot down. On a tie, whoever spent fewer shots ranks higher, and if
that ties too, whoever set the record earlier. The file is read and written whole:
ten rows.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date

TOP_N = 10
SCORES_NAME = "scores.json"
NAME_MAX = 12


@dataclass(frozen=True)
class Entry:
    name: str
    hits: int          # ducks shot down — the score, too
    shots: int         # how many shots it took
    ducks: int         # how many ducks there were in the round
    date: str          # YYYY-MM-DD

    @property
    def accuracy(self) -> float:
        return (self.hits / self.shots * 100.0) if self.shots else 0.0


def default_path() -> str:
    """`scores.json` in the project root — right next to settings.toml."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "..", SCORES_NAME)


def _rank(e: Entry) -> tuple:
    return (-e.hits, e.shots, e.date)


def load(path: str | None = None) -> list[Entry]:
    """Read the table. Missing or broken file gives an empty table."""
    path = path or default_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        entries = [Entry(name=str(r["name"]), hits=int(r["hits"]),
                         shots=int(r["shots"]), ducks=int(r["ducks"]),
                         date=str(r["date"]))
                   for r in raw]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"{SCORES_NAME}: could not be read ({exc}) — starting a fresh table",
              file=sys.stderr)
        return []
    return sorted(entries, key=_rank)[:TOP_N]


def save(entries: list[Entry], path: str | None = None) -> None:
    """Write the table via a temp file, so an interrupted write keeps the old one."""
    path = path or default_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in entries], f,
                      ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"{SCORES_NAME}: could not be written ({exc})", file=sys.stderr)


def qualifies(entries: list[Entry], hits: int, shots: int) -> bool:
    """Would such a result make the table? A zero score never does."""
    if hits <= 0:
        return False
    if len(entries) < TOP_N:
        return True
    worst = entries[-1]
    return (-hits, shots) < (-worst.hits, worst.shots)


def add(entry: Entry, path: str | None = None) -> list[Entry]:
    """Add a round to the table, trim it to ten rows and save."""
    entries = sorted(load(path) + [entry], key=_rank)[:TOP_N]
    save(entries, path)
    return entries


def from_world(world, name: str) -> Entry:
    """Round result -> a table row."""
    return Entry(name=(name.strip() or "PLAYER")[:NAME_MAX],
                 hits=world.hits, shots=world.shots,
                 ducks=world.total, date=date.today().isoformat())
