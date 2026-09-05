# 🏆 Leaderboard — a separate server with a console scoreboard

The game currently keeps its top ten in `scores.json` next to `settings.toml`: local
to one Mac, invisible to anyone who is not sitting at it, and it only remembers the
ten best rounds — every other attempt is thrown away.

This plan replaces that with a **separate leaderboard server**: the game asks for a
player's name *before* the round, sends the result *after* it, and the server keeps
**every attempt** in SQLite while showing **the best result per player** on a
dedicated screen — an old-computer console board with a running line scrolling along
the bottom.

Nothing here is written yet. This is the plan; the checkboxes are the work.

## The shape of it

```
MAC (the game)                          SERVER BOX (a Pi, or the same Mac)
                                        ┌──────────────────────────────────┐
  name entry ─▶ round ─▶ result         │  leaderboard/server.py           │
                          │             │    HTTP :8420  ThreadingHTTP     │
                          │  POST /api/runs                                │
                          └────────────▶│    validate ─▶ SQLite (WAL)      │
                          ◀─────────────│    ◀─ rank, personal best        │
        "#3 · NEW PERSONAL BEST"        │              leaderboard.db      │
                                        └─────────────┬────────────────────┘
  offline? → pending_runs.jsonl                       │ GET /api/board
             flushed on next launch                   │ GET /api/stats
                                                      ▼
                                        ┌──────────────────────────────────┐
                                        │  leaderboard/display.py (blessed)│
                                        │   ╔════ DUCK HUNT — TOP 10 ════╗ │
                                        │   ║ 1. EUGENE   66 ducks  66%  ║ │
                                        │   ╚════════════════════════════╝ │
                                        │  ◀ NEW RECORD: EUGENE 66 *** 412 │
                                        └──────────────────────────────────┘
```

Three processes, deliberately: the game must never freeze or crash because the
scoreboard is off, and the scoreboard must survive the game being restarted twenty
times an evening. They meet at one HTTP endpoint and one SQLite file.

**Why HTTP and not the `x,y,b`-style UDP the gun uses.** One packet per *round* —
delivery matters far more than latency, and a lost UDP datagram is a lost record.
HTTP also gives the game something back: the rank it just earned, which is what the
results screen wants to show.

**Why SQLite.** One writer, a handful of rows per minute, and the query we need
("best run per player") is a three-line window function. No server to run, no
dependency to install — `sqlite3` is in the standard library, as is `http.server`.
`requirements.txt` does not change; `blessed` for the console display is already
there for the terminal frontend.

## The data

One table. Every attempt is a row — the "top ten" is only ever a query.

```sql
CREATE TABLE runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid     TEXT    NOT NULL UNIQUE,   -- idempotency: the game may retry a POST
    player_key   TEXT    NOT NULL,          -- name, normalized — this is "the same player"
    name         TEXT    NOT NULL,          -- name as typed, for display
    hits         INTEGER NOT NULL,          -- ducks downed = the score
    shots        INTEGER NOT NULL,
    ducks        INTEGER NOT NULL,          -- round size: 100-duck and 50-duck runs do not compete
    accuracy     REAL    NOT NULL,          -- hits/shots*100, stored so the board sorts cheaply
    duration     REAL    NOT NULL,          -- world.elapsed, seconds
    started_at   TEXT    NOT NULL,          -- ISO-8601 UTC
    finished_at  TEXT    NOT NULL,
    client_id    TEXT    NOT NULL,          -- which cabinet sent it
    input_source TEXT,                      -- mouse | serial | udp | wiimote | keyboard
    game_version TEXT,
    settings     TEXT                       -- JSON: interval, duck size, speeds — for context
);
CREATE INDEX runs_board  ON runs (ducks, hits DESC, shots ASC, finished_at ASC);
CREATE INDEX runs_player ON runs (player_key, hits DESC, shots ASC);
```

**Who counts as the same player.** `player_key = " ".join(name.split()).casefold()` —
so `Eugene`, `eugene` and `  Eugene ` are one person; the board shows the spelling
from their most recent run. No accounts, no passwords: this is a party scoreboard.

**The board query** — best run per player, ranked exactly like the current
`scores._rank` (more hits first, then fewer shots, then whoever got there first):

```sql
SELECT name, hits, shots, ducks, accuracy, finished_at, attempts
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY player_key
                              ORDER BY hits DESC, shots ASC, finished_at ASC) AS rn,
           COUNT(*)     OVER (PARTITION BY player_key) AS attempts
    FROM runs WHERE ducks = :ducks
)
WHERE rn = 1
ORDER BY hits DESC, shots ASC, finished_at ASC
LIMIT :limit;
```

`attempts` comes free from the same pass, and the board can show `66 ducks (12 tries)`
— which is the fun part of keeping every row.

## The HTTP API

Everything is JSON. Errors are `{"error": "..."}` with a 4xx/5xx code.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/runs` | submit a finished round; returns rank and personal best |
| `GET` | `/api/board?ducks=100&limit=10` | the board: best run per player |
| `GET` | `/api/player/<name>?limit=20` | one player: best run, attempt count, recent history |
| `GET` | `/api/stats?ducks=100` | totals for the running line |
| `GET` | `/healthz` | `{"ok": true}` — for the display's link indicator |

**`POST /api/runs`** — the game sends:

```json
{ "run_uuid": "3f2c…", "name": "Eugene", "hits": 66, "shots": 100, "ducks": 100,
  "duration": 61.4, "started_at": "2026-09-02T18:20:11Z",
  "finished_at": "2026-09-02T18:21:12Z", "client_id": "eugene-mac",
  "input_source": "serial", "game_version": "0.4.0",
  "settings": {"interval": 0.6, "width": 0.13, "speed_min": 0.3, "speed_max": 0.55} }
```

and gets back everything the results screen wants to say:

```json
{ "ok": true, "rank": 3, "of": 17, "personal_best": 66, "previous_best": 57,
  "improved": true, "attempts": 12, "world_record": {"name": "Anna", "hits": 71} }
```

- **Idempotent on `run_uuid`.** A retried POST returns the same answer instead of a
  duplicate row (`INSERT … ON CONFLICT(run_uuid) DO NOTHING`, then read back).
- **Validation, because the port is open on the LAN**: body ≤ 8 KB; `name` non-empty
  and trimmed to `scores.NAME_MAX` (12); `0 ≤ hits ≤ shots`; `hits ≤ ducks`;
  `1 ≤ ducks ≤ 10000`; `0 < duration < 24 h`; timestamps parseable. Anything else is a
  `400` and is not stored — a junk row on the board is forever.
- **Optional shared secret**: `--token SECRET` on the server, `X-Duckhunt-Key` on the
  request, checked with `hmac.compare_digest`. Off by default (home LAN); one flag when
  the game goes to a public event.

**`GET /api/stats`** feeds the running line: total rounds, distinct players, ducks
downed all-time, today's best, and the most recent run (`{"name": …, "hits": …,
"is_record": true}`) so the ticker can shout about a fresh record.

## The server

`leaderboard/server.py` — `ThreadingHTTPServer` with a `BaseHTTPRequestHandler`, a
router of five routes, `leaderboard/store.py` doing every bit of SQL.

- `PRAGMA journal_mode=WAL` at startup so the display's reads never block a write, and
  `PRAGMA busy_timeout=5000` for the rare overlap.
- A connection per request (`sqlite3.connect` is cheap; nothing shared between threads,
  no `check_same_thread` games).
- `--host 0.0.0.0 --port 8420 --db leaderboard.db --token … --log runs.log`.
- Logs one line per accepted run to stdout so the terminal it runs in *is* the audit
  trail: `18:21:12  eugene  66/100  66%  61s  rank 3`.

```bash
python3 -m leaderboard.server --port 8420 --db leaderboard.db
```

**Autostart on the Pi** (later, once it lives on a box of its own): a `systemd` unit
running the server and a second one running the display on tty1, both `Restart=always`.
On a Mac, the same with a `launchd` plist. Sketches go in this file when it happens.

## The console display

`leaderboard/display.py` — `blessed`, full screen, hidden cursor, green on black.

```
╔══════════════════════════════════════════════════════╗
║             D U C K   H U N T   —   T O P  10        ║
╠══════════════════════════════════════════════════════╣
║   1. EUGENE          66 ducks   66%   12 tries  09-02║
║   2. MIKE            57 ducks   66%    4 tries  09-01║
║   3. ANNA            51 ducks   72%    9 tries  08-30║
╚══════════════════════════════════════════════════════╝
◀ *** NEW RECORD: EUGENE — 66 DUCKS *** 412 ROUNDS PLAYED *** 17 SHOOTERS *** 
```

- **The running line.** One string built from `/api/stats`, padded with `***`
  separators, scrolled right-to-left: render `(text * 2)[off : off + width]` and
  advance `off` by `speed × dt`. Redraw at ~20 FPS so it glides; that is the whole
  trick, and it is why the display is a loop rather than a `watch` command.
- **Two clocks.** The scroll runs every frame; the API is polled every 2 s on a
  background thread. A slow or dead server slows nothing down on screen.
- **A fresh run arrives** (the newest `id` changed): flash that row for a few seconds
  and push `NEW RECORD: …` / `EUGENE BEATS THEIR BEST — 66` to the front of the ticker
  for 30 s.
- **Link down**: keep the last board on screen, dim it, and put `LINK DOWN —
  RETRYING` in the running line. A scoreboard that goes blank because a Wi-Fi packet
  was lost is worse than a stale one.
- **Resize** on `term.on_resize`; below ~40 columns drop to a compact `1.EUGENE 66`
  layout.
- Flags: `--url http://localhost:8420 --top 10 --ducks 100 --refresh 2 --speed 12
  --color green|amber`. `q` quits.

```bash
python3 -m leaderboard.display --url http://raspberrypi.local:8420
```

### The retro treatment

The running line is the centrepiece, but on its own it is just scrolling text. What
makes a screen read as *old computer* is a handful of cheap tricks, all of them
plain `blessed`:

- **Phosphor palette.** `--color green` (`bright_green` on black, the P1 look),
  `amber` (`bright_yellow`, a VT220), `white`. Rows below the top three render in the
  dim variant, so the board fades down the list the way a real tube does.
- **A boot sequence** on launch, typed out a character at a time, then the screen
  clears to the board — about 1.5 s, skipped by any key:
  ```
  DUCK HUNT SCOREBOARD v0.1
  MEMORY OK ....... 64K
  LINK 192.168.1.20:8420 ... OK
  LOADING BOARD ...
  ```
- **A blinking block cursor** `█` parked at the end of the running line, 1 Hz — the
  single detail that sells "this machine is alive and waiting".
- **Dot leaders and uppercase** everywhere: `EUGENE ............ 66 DUCKS`. Names are
  upper-cased for display only; the database keeps what was typed.
- **Double-line box drawing** as in the sketch above, with `--ascii` falling back to
  `+---+` for terminals whose font mangles `╔`.
- **A block-letter banner** for `DUCK HUNT`, from a small 5-row font built into the
  module (no `figlet` dependency), drawn only when the terminal is tall enough.
- **A new record takes the screen**: the row inverts (`term.reverse`) three times over
  a second, the ticker jumps to `*** NEW RECORD ***`, and — behind `--bell` — the
  terminal beeps. A `\a` on a new high score is exactly the right amount of 1983.
- **Attract mode.** With no new run for a few minutes, the panel rotates every 20 s:
  TOP 10 → TODAY → MOST ROUNDS PLAYED, with a line-by-line wipe between them.
- **No flicker.** Compose the whole frame into one string with `term.move_yx` and emit
  it in a single write per tick; never clear the screen between frames.

`--plain` turns all of it off (no banner, no boot, no blink) for when the display is
being run in a corner of a tiling window manager rather than on a screen of its own.

## What changes in the game

The game keeps working with no server: `scores.json` stays exactly as it is, as the
local mirror and the offline fallback. Everything below is additive.

### 1. Ask for the name *before* the round

`duckhunt/frontends/pygame_app.py` gains a mode ahead of the intro:

```
enter_name → intro → play → over
```

- Reuse the existing name-entry drawing (`mode == "name"` in `draw_results`) — same
  keys: printable characters, Backspace, Enter, Esc.
- **Pre-fill with the last player**: `player.json` next to `scores.json` holds
  `{"name": "Eugene"}`, so a repeat player just presses Enter. Esc plays as `PLAYER`.
- Enter with an empty buffer is not a name — keep the prompt up.
- The old *end-of-round* name entry goes away: the name is known before the first duck.
  `mode` after `play` is always `over`; `scores.qualifies` still decides whether the
  local file gets the row, but it no longer gates a prompt.
- **Optional, and the right thing eventually**: an NES-style alphabet grid you enter
  your initials by *shooting* the letters — the only part of the game the keyboard is
  still needed for. Stretch goal, after the rest works.

### 2. Identify the round

At round start (`World` construction, or a tiny `RunMeta` next to it): `run_uuid =
uuid.uuid4().hex`, `started_at = datetime.now(timezone.utc)`. At the end,
`finished_at` and `world.elapsed` complete the payload.

### 3. Send the result

New `duckhunt/net/leaderboard_client.py` (`urllib.request`, no new dependency):

- `submit(payload) -> Result` posts with a 2 s timeout, retries 3× with backoff
  (0.5 s, 1 s, 2 s), **on a background thread** — the results screen must never stall
  on a network write, and the round is over anyway.
- On every failure path, append the payload to `pending_runs.jsonl` next to
  `scores.json`. On the next launch (and after each successful POST) flush the queue
  oldest-first; the `run_uuid` makes a double-send harmless.
- `enabled = false` or no URL configured → the client is a no-op and the game behaves
  exactly as it does today.

### 4. Show what came back

The results screen gains one line under the score, driven by the client's state:

| State | Line |
|---|---|
| in flight | `SENDING TO LEADERBOARD…` |
| ok, improved | `#3 ON THE BOARD · NEW PERSONAL BEST (was 57)` |
| ok, not improved | `#5 ON THE BOARD · YOUR BEST IS 66` |
| queued offline | `SAVED — WILL SYNC WHEN THE BOARD IS BACK` |
| disabled | nothing at all |

The local top-ten table stays underneath it, unchanged.

### 5. Configuration

New section in `settings.toml`, defaults in `duckhunt/core/config.py`:

```toml
[leaderboard]
enabled = false                       # true once the server is up
url = "http://localhost:8420"
client_id = "eugene-mac"              # which cabinet this is
timeout = 2.0                         # seconds per attempt
token = ""                            # only if the server was started with --token
```

- Add `LeaderboardSettings` as a fourth dataclass on `Settings`; `_section` already
  handles `str`/`bool`/`float` fields and warns on the rest.
- **Do not forget** `duckhunt/core/config.py`'s known-section list — the loop over
  `data` warns about `[leaderboard]` as an unknown section until `"leaderboard"` is
  added to `("duck", "round", "scene", "spawn")`.
- Overrides, in order: `--leaderboard URL` on the command line → `DUCKHUNT_LEADERBOARD`
  in the environment → `settings.toml`. `--no-leaderboard` turns it off for one run.
- `Settings.summary()` gets a `· board on` / nothing suffix so the startup line still
  says what is in effect.

### 6. The terminal frontend and `main.py`

- `TerminalFrontend` submits the same payload; the name comes from `--player NAME` or a
  one-line prompt before the round, so the ASCII path does not fall behind.
- `main.py --player NAME` also pre-fills the pixel frontend's name field and skips
  straight to the intro — the way to start an evening of rounds without typing.
- `print_result()` prints the server's top ten under the local one when the board
  answered.

## Milestones

Each one is usable on its own; stop after any of them and nothing is broken.

- [ ] **M1 — store + server.** `leaderboard/store.py`, `leaderboard/server.py`, the
      schema, validation, the five routes. *Done when:* `curl -X POST` puts a run in and
      `curl /api/board` ranks it; a duplicate `run_uuid` does not duplicate the row; a
      run with `hits > shots` is rejected with 400.
- [ ] **M2 — the console board.** `leaderboard/display.py` with the table, the running
      line, the poll thread, the link-down state. *Done when:* it runs against M1's
      server, scrolls smoothly, and survives the server being killed and restarted
      under it.
- [ ] **M3 — name first.** The `enter_name` mode in the pixel frontend, `player.json`,
      `--player`. *Done when:* the name is asked once at launch, pre-filled the next
      time, and the end-of-round prompt is gone.
- [ ] **M4 — the game talks to the board.** `duckhunt/net/leaderboard_client.py`, the
      `[leaderboard]` settings, the offline queue, the results-screen line. *Done when:*
      a round with the server up appears on the console board within two seconds, and a
      round with the server *down* appears there after the server comes back and the game
      is relaunched.
- [ ] **M5 — polish.** `leaderboard/seed.py` to import the existing `scores.json` (and a
      `--demo` filler for testing the display with a full board); the ticker's record
      announcements; `systemd`/`launchd` autostart; README and this file updated with what
      was actually built.
- [ ] **M6 — optional.** Shoot-the-letters name entry; a `/api/events` SSE stream so the
      display reacts instantly instead of polling; per-day and per-week boards on a
      rotating panel.

## Files

| Path | What |
|---|---|
| `leaderboard/store.py` | SQLite: schema, `insert_run`, `board`, `player`, `stats` |
| `leaderboard/server.py` | the HTTP server and its five routes |
| `leaderboard/display.py` | the blessed console board with the running line |
| `leaderboard/seed.py` | import `scores.json`, generate demo rows |
| `duckhunt/net/leaderboard_client.py` | POST + retries + `pending_runs.jsonl` |
| `duckhunt/frontends/pygame_app.py` | the `enter_name` mode, the result line |
| `duckhunt/frontends/terminal.py` | the same submission from the ASCII frontend |
| `duckhunt/core/config.py`, `settings.toml` | the `[leaderboard]` section |
| `main.py` | `--player`, `--leaderboard`, `--no-leaderboard` |
| `docs/LEADERBOARD.md` | this plan |

`requirements.txt` is unchanged: `sqlite3`, `http.server`, `urllib`, `uuid` and `json`
are standard library, and `blessed` is already a dependency.

## Checks worth running by hand

- Two players, the same name in different case → **one** row on the board, the higher
  score, `attempts` counting both.
- Twenty rounds by one player → the board shows their best, `/api/player/eugene`
  shows all twenty.
- Kill the server mid-evening, play three rounds, bring it back, relaunch the game →
  all three appear, none twice.
- A 50-duck round (`--settings hard.toml`) does not mix into the 100-duck board.
- Pull the network cable from the display box → the board stays on screen, the ticker
  says the link is down, and it recovers on its own.
