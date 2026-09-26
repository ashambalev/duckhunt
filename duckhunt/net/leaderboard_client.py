"""Sending a finished round to the leaderboard — off the game's thread, always.

The round is over by the time this runs, and the board lives on a screen of its
own, so nothing on the game's side waits for the network: one worker thread takes
payloads off a queue, tries three times, and on any failure writes the payload to
`pending_runs.jsonl` next to `scores.json`. The queue is flushed oldest-first on
the next launch, and the `run_uuid` makes a double-send harmless — so an evening
played with the server off still lands on the board when it comes back.

`[leaderboard] enabled = false` (the default) makes every call here a no-op, and
the game behaves exactly as it did before the board existed.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .. import __version__
from ..core import scores

PENDING_NAME = "pending_runs.jsonl"
BACKOFF = (0.5, 1.0, 2.0)          # three tries, then the queue on disk
TOKEN_HEADER = "X-Duckhunt-Key"

# What the results screen may say. The board's own content — ranks, names, other
# people's scores — is deliberately not among it: that is on the other screen.
OFF, SENDING, SENT, QUEUED = "off", "sending", "sent", "queued"

MESSAGES = {
    SENDING: "SENDING THE ROUND TO THE BOARD…",
    SENT: "ON THE BOARD",
    QUEUED: "SAVED — WILL SYNC WHEN THE BOARD IS BACK",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def pending_path() -> str:
    """Next to scores.json, which is the game's other bit of local state."""
    return os.path.join(os.path.dirname(scores.default_path()), PENDING_NAME)


def payload(world, name: str, client_id: str, input_source: str | None = None,
            finished_at: str | None = None) -> dict:
    """A finished round as the server wants it."""
    s = world.settings
    return {"run_uuid": world.run_uuid,
            "name": (name.strip() or "PLAYER")[:scores.NAME_MAX],
            "hits": world.hits, "shots": world.shots, "ducks": world.total,
            "duration": round(world.elapsed, 2),
            "started_at": world.started_at,
            "finished_at": finished_at or utc_now(),
            "client_id": client_id,
            "input_source": input_source,
            "game_version": __version__,
            "settings": {"interval": s.round.interval, "width": s.duck.width,
                         "speed_min": s.duck.speed_min,
                         "speed_max": s.duck.speed_max,
                         "spread": s.gun.spread}}


class LeaderboardClient:
    """One worker thread, one queue, one file of unsent rounds."""

    def __init__(self, settings, queue_path: str | None = None):
        self.settings = settings
        self.enabled = bool(settings.enabled and settings.url)
        self.queue_path = queue_path or pending_path()
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._state = OFF
        self._detail = ""
        self._busy = False       # the worker is mid-round: not "finished" yet
        self._worker: threading.Thread | None = None
        if self.enabled:
            self._worker = threading.Thread(target=self._run, daemon=True)
            self._worker.start()
            self._q.put(("flush", None))

    # ---- what the game sees ----

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def line(self) -> str:
        """One line for the results screen, or "" when there is nothing to say."""
        with self._lock:
            return MESSAGES.get(self._state, "")

    def _set(self, state: str, detail: str = "") -> None:
        with self._lock:
            self._state, self._detail = state, detail

    def submit(self, run: dict) -> None:
        """Hand a round over. Returns at once; the sending happens elsewhere."""
        if not self.enabled:
            return
        self._set(SENDING)
        self._q.put(("run", run))

    def wait(self, timeout: float = 5.0) -> bool:
        """Block until what has been handed over is sent (or queued on disk).

        The worker is a daemon thread, so a process that exits the moment the
        player presses Enter would take an in-flight POST with it. Both frontends
        call this on the way out; in the game it costs nothing, because by then
        the round has been over for a while.
        """
        if not self.enabled:
            return True
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                idle = not self._busy and self._state != SENDING
            if idle and self._q.empty():
                return True
            time.sleep(0.05)
        return False

    def close(self, timeout: float = 5.0) -> None:
        if self._worker is not None:
            self.wait(timeout)
            self._q.put(("stop", None))

    # ---- the worker ----

    def _run(self) -> None:
        while True:
            kind, run = self._q.get()
            if kind == "stop":
                return
            # Taken off the queue but not dealt with yet — wait() has to count
            # this as work in flight, or a process on its way out can exit
            # between the queue going empty and the payload reaching the disk.
            with self._lock:
                self._busy = True
            try:
                if kind == "flush":
                    self._flush_pending()
                elif self._post_with_retries(run):
                    self._set(SENT)
                    self._flush_pending()   # a working link: drain what was stuck
                else:
                    self._append_pending(run)
                    self._set(QUEUED)
            finally:
                with self._lock:
                    self._busy = False

    def _post_with_retries(self, run: dict) -> bool:
        for attempt, pause in enumerate(BACKOFF, 1):
            try:
                self._post(run)
                return True
            except (urllib.error.HTTPError,) as exc:
                if 400 <= exc.code < 500:
                    # the server refused the row itself — retrying cannot help,
                    # and queueing it would retry it forever on every launch
                    print(f"[board] the server rejected the round ({exc.code}) — "
                          f"not queued", flush=True)
                    return True
                if attempt < len(BACKOFF):
                    time.sleep(pause)
            except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                if attempt < len(BACKOFF):
                    time.sleep(pause)
        return False

    def _post(self, run: dict) -> dict:
        data = json.dumps(run).encode("utf-8")
        req = urllib.request.Request(
            self.settings.url.rstrip("/") + "/api/runs", data=data,
            headers={"Content-Type": "application/json"})
        if self.settings.token:
            req.add_header(TOKEN_HEADER, self.settings.token)
        with urllib.request.urlopen(req, timeout=self.settings.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # ---- the queue on disk ----

    def _append_pending(self, run: dict) -> None:
        try:
            with open(self.queue_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(run, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"[board] could not queue the round ({exc})", flush=True)

    def _flush_pending(self) -> None:
        """Oldest first; what still fails is written back and waits for next time."""
        if not os.path.exists(self.queue_path):
            return
        try:
            with open(self.queue_path, encoding="utf-8") as f:
                lines = [ln for ln in (l.strip() for l in f) if ln]
        except OSError:
            return
        if not lines:
            return
        left: list[str] = []
        sent = 0
        for i, line in enumerate(lines):
            try:
                run = json.loads(line)
            except ValueError:
                continue               # a half-written line from a hard kill
            if left:                   # the link just failed — keep the order
                left.append(line)
                continue
            if self._post_with_retries(run):
                sent += 1
            else:
                left.append(line)
        try:
            if left:
                with open(self.queue_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(left) + "\n")
            else:
                os.remove(self.queue_path)
        except OSError:
            pass
        if sent:
            print(f"[board] {sent} round(s) that had been waiting are on the board",
                  flush=True)
