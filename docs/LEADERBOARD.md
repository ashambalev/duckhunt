# 🏆 Leaderboard — a separate server with a console scoreboard

The game used to keep its top ten in `scores.json` next to `settings.toml`: local
to one Mac, invisible to anyone not sitting at it, and it only remembered the ten
best rounds — every other attempt was thrown away.

That is now a **separate leaderboard**, on a screen of its own: the game asks who
was shooting *after* the round, posts one row, and the server keeps **every
attempt** in SQLite while a console board shows **the best result per player**,
with a running line scrolling along the bottom.

Two rules decide everything below:

- **The name is asked after the round.** A player walks up, is handed a gun and
  shoots; being asked to type first is a form to fill in before a game. Afterwards
  they have a number they want on the board, which is the moment they will happily
  spell their name. The last name typed is remembered (`player.json`) and offered
  pre-filled, so an evening of rounds is Enter, Enter, Enter.
- **The game draws nothing of the board.** No ranks, no other players, no table —
  the results screen shows your round and the line you signed it with, and that is
  all. Two scoreboards disagreeing about which one you should be reading is worse
  than one; the board is on the other screen, and it is the one everybody watches.

## The shape of it

```
MAC (the game)                          SERVER BOX (a Pi, or the same Mac)
                                        ┌──────────────────────────────────┐
  round ─▶ "WHO WAS SHOOTING?" ─▶ row   │  leaderboard/server.py           │
                          │             │    HTTP :8420  ThreadingHTTP     │
                          │  POST /api/runs                                │
                          └────────────▶│    validate ─▶ SQLite (WAL)      │
                                        │              leaderboard.db      │
  offline? → pending_runs.jsonl         └─────────────┬────────────────────┘
             flushed on next launch                   │ GET /api/board
                                                      │ GET /api/stats
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

**Why SQLite.** One writer, a handful of rows per minute, and the query we need
("best run per player") is a three-line window function. No server to run, no
dependency to install — `sqlite3` and `http.server` are standard library, and
`blessed` was already here for the terminal frontend. `requirements.txt` did not
change.

## Running it

Two commands, one for the scoreboard and one for the game:

```bash
cd /Users/evgenychernyak/projects/duckhunt

# the scoreboard: the server, and the tube-TV board in a browser window
.venv/bin/python -m leaderboard --browser

# and the game, told where to send its rounds
.venv/bin/python main.py --pygame --serial /dev/tty.usbserial-0001 \
                         --leaderboard http://localhost:8420
```

Drag the browser window to the second screen and press **F** — it goes fullscreen
and stays there all evening. Drop `--browser` and the console board is drawn in
that terminal instead; both read the same server, so you can have one of each.

`python3 -m leaderboard` runs the server in a thread of this process: with
`--browser` it opens the page and holds the terminal until Ctrl-C, and without it
draws the console board in front — one thing to start, one thing to quit (`q`
stops the board and takes the server with it). Every flag that is not the server's goes to
the board, so `--color amber --top 12 --ducks 50` work here too. The server's
per-run lines cannot share a terminal with a board being drawn on it, so they go
to `leaderboard.log` next to the database (`--log FILE` moves it, `--log -` throws
it away). Started a second time on a port that already answers, it shows that
board instead of failing on "address already in use".

Two processes are still the right thing when the board lives on a Pi and the game
on the Mac, or when either has to be restarted without the other:

```bash
.venv/bin/python -m leaderboard.server --port 8420 --db leaderboard.db
.venv/bin/python -m leaderboard.display --url http://raspberrypi.local:8420
```

`--leaderboard URL` is the one-off; the permanent way is `[leaderboard] enabled =
true` in `settings.toml`. `--no-leaderboard` turns it off for one session,
`--player NAME` skips the question after every round, and `DUCKHUNT_LEADERBOARD`
in the environment sits between the flag and the file.

Something to look at before anyone has played:

```bash
.venv/bin/python -m leaderboard.seed --demo 75      # 75 invented rounds, 15 players
.venv/bin/python -m leaderboard.seed --clear-demo   # and take them back out again
.venv/bin/python -m leaderboard.seed --from-scores  # import the local scores.json
```

The invented players have names, surnames and form: each one has a share of the
flock they usually down and an aim of their own, so their attempts cluster around
their own number, a good player has one unusually good night, and the board ends
up the shape a real one will be — a few close at the top, a long tail, and
somebody who has played thirteen times to get there. Every demo row is
`client_id = 'demo'`, which is all `--clear-demo` needs to take them out again
without touching a round anybody actually shot.

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

**How long a name may be.** `scores.NAME_MAX` is **50** — a name, a surname and a
nickname in Cyrillic if that is what somebody types. That is what is *stored*;
what is *shown* is each board's own business, because one 50-character name on a
scoreboard leaves nowhere for what it scored: the terminal board cuts at 18
characters and the browser board at 20, both with an ellipsis, and the game's name
field drops to the smaller face and scrolls once what is typed no longer fits the
panel.

**Who counts as the same player.** `player_key = " ".join(name.split()).casefold()` —
so `Eugene`, `eugene` and `  Eugene ` are one person; the board shows the spelling
from their best run. No accounts, no passwords: this is a party scoreboard.

**The board query** — best run per player, ranked exactly like the game's own
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

`attempts` comes free from the same pass, and the board shows `66 DUCKS … 12
TRIES` — which is the fun part of keeping every row.

## The HTTP API

Everything is JSON. Errors are `{"error": "..."}` with a 4xx/5xx code.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/runs` | submit a finished round; returns rank and personal best |
| `GET` | `/api/board?ducks=100&limit=10&window=all\|today\|week&order=best\|attempts` | the board: best run per player |
| `GET` | `/api/player/<name>?ducks=100&limit=20` | one player: best run, attempt count, recent history |
| `GET` | `/api/stats?ducks=100` | totals for the running line |
| `GET` | `/healthz` | `{"ok": true}` — the display's link indicator |

**`POST /api/runs`** — the game sends:

```json
{ "run_uuid": "3f2c…", "name": "Eugene", "hits": 66, "shots": 100, "ducks": 100,
  "duration": 61.4, "started_at": "2026-09-02T18:20:11Z",
  "finished_at": "2026-09-02T18:21:12Z", "client_id": "eugene-mac",
  "input_source": "serial", "game_version": "0.5.0",
  "settings": {"interval": 0.6, "width": 0.13, "speed_min": 0.3, "speed_max": 0.55} }
```

and gets back where the round landed:

```json
{ "ok": true, "rank": 3, "of": 17, "personal_best": 66, "previous_best": 57,
  "improved": true, "attempts": 12, "world_record": {"name": "Anna", "hits": 71} }
```

The game does not draw any of that — it is there for the log, for a future results
screen on the *board's* side, and because a POST that answers only "ok" is a POST
nobody can debug.

- **Idempotent on `run_uuid`.** A retried POST returns the same answer instead of a
  duplicate row (`INSERT … ON CONFLICT(run_uuid) DO NOTHING`, then read back), and
  the answer is computed from the stored row, so a retry says what the first call
  said.
- **Validation, because the port is open on the LAN**: body ≤ 8 KB; `name` non-empty
  and trimmed to 50; `0 ≤ hits ≤ shots`; `hits ≤ ducks`; `1 ≤ ducks ≤ 10000`;
  `0 ≤ duration < 24 h`; timestamps parseable. Anything else is a `400` and is not
  stored — a junk row on the board is forever.
- **Optional shared secret**: `--token SECRET` on the server, `X-Duckhunt-Key` on
  the request, compared with `hmac.compare_digest`. Off by default (home LAN);
  `[leaderboard] token` on the game's side when it goes to a public event.

`GET /api/stats` feeds the running line: rounds played, distinct players, ducks
downed, today's best, the standing record, and the most recent run (with
`is_record`) so the ticker can shout about a fresh one.

## The server

`leaderboard/server.py` — `ThreadingHTTPServer`, a router of five routes, and
`leaderboard/store.py` doing every bit of SQL. `build()` hands a ready server back
rather than serving it, which is what lets `python3 -m leaderboard` run one in a
thread beside the board.

- `PRAGMA journal_mode=WAL` so the display's reads never block a write, and
  `PRAGMA busy_timeout=5000` for the rare overlap.
- A connection per request; nothing shared between threads.
- `--host 0.0.0.0 --port 8420 --db leaderboard.db --token …`
- One line per accepted run on stdout, so the terminal it runs in *is* the audit
  trail: `18:21:12  eugene  66/100  66%  61s  rank 3`.

**Autostart on the Pi** (once it lives on a box of its own): a `systemd` unit for
the server and a second one for the display on tty1, both `Restart=always`; on a
Mac, the same with a `launchd` plist. Sketches go here when it happens.

## Two boards

The same data, drawn two ways, because they are good at different things.

| | `board.html` (browser) | `display.py` (terminal) |
|---|---|---|
| Looks | a 4:3 television in a plastic cabinet: glow, scanlines, aperture grille, vignette, the roll band | text: box drawing, dot leaders, dim rows |
| Shows | the same one board: best round per player, best first | the same |
| Needs | a browser and a desktop | a terminal, any terminal |
| Where it wins | the screen people stand around | a Pi on a tty, SSH, no desktop at all |

**The browser one is the one to put on the second screen.** A terminal can draw
text and change its colour; it cannot do phosphor bloom, a curved bezel, or a
bright band drifting down the picture — the beat you see when a camera films a
CRT, because the tube's refresh and the shutter never quite agree. Those are three
CSS overlays here, and they are most of what makes a scoreboard read as *1983*
rather than as *a terminal with green text*.

## The browser board

`leaderboard/board.html`, served by the same server at `/`. One file, no build, no
dependency; the server reads it from disk on every request, so tuning how it looks
is a reload rather than a restart.

- **The set**: a **4:3** tube — the shape television was until 1998 — sunk into a
  cabinet with a speaker grille, a volume and a tuning knob, a red power lamp, a
  DUCKTRON DH-84 badge and two feet. The whole thing is sized off one custom
  property, `--H` (the tube's height), so cabinet, knobs and type scale together
  and the picture keeps its proportion at any window size.
- **The picture**: the title, `TOP 10` under it, up to `top` rows with dot
  leaders, and the running line pinned to the bottom. The top three rows burn
  brighter than the rest, and the row type is set from JS to whatever makes all
  `top` rows fit — both between the heading and the ticker, and across the
  picture: ten names get smaller letters than two do, no row is clipped by the
  bottom, and no name is squeezed into an ellipsis by a type size that was only
  ever checked against the height.
- **The tube**: `#scanlines` (a dark line every other row), `#grille` (a very faint
  RGB stripe — the aperture grille, and what stops it looking like a text editor),
  `#roll` (**the band**, one `translateY` keyframe over 7.5 s), `#vignette` (the
  glass's dark corners and one diagonal reflection), plus a slow `flicker` on the
  whole picture and a `warmup` line that opens out into a picture on load.
- **The round size** is the one setting the board and the game must agree on:
  40-duck and 100-duck rounds are separate boards, so `--ducks` (and `?ducks=`)
  defaults to `[round] ducks` from the game's `settings.toml`. A board with no
  rows says which sizes *do* have rounds, rather than leaving an empty screen to
  be read as "the game is not saving anything".
- **Query parameters**: `color=green|amber|white`,
  `cabinet=beige|graphite|wood`, `ducks`, `top`, `refresh`, `speed`,
  `plain=1` (no cabinet and no effects — the data alone, for a screenshot or a
  tiling window manager), `key=` (when the server was started with `--token` — a
  page cannot set a header on its own fetches).
- **Keys**: `F` fullscreen, `C` next colour, `B` next cabinet, `E` effects on and
  off.
- Polls `/api/board` and `/api/stats` every `refresh` seconds while the ticker
  scrolls every frame; a fresh run flashes its row and the ticker leads with
  `*** NEW RECORD ***`; with the link down the last board stays on screen, dimmed.

## The console display

`leaderboard/display.py` — `blessed`, full screen, hidden cursor, phosphor on
black.

```
╔══════════════════════════════════════════════════════════╗
║                          TOP 10                          ║
╠══════════════════════════════════════════════════════════╣
║  1. EUGENE ..............  66 DUCKS  66%  12 TRIES 09-02 ║
║  2. MIKE ................  57 DUCKS  66%   4 TRIES 09-01 ║
╚══════════════════════════════════════════════════════════╝
◀ *** NEW RECORD: EUGENE — 66 DUCKS ***  412 ROUNDS PLAYED  ***
```

- **The running line.** One string built from `/api/stats`, `***`-separated,
  scrolled right-to-left: render `(text * 3)[off : off + width]` and advance `off`
  by `speed × dt`, at 20 FPS.
- **Two clocks.** The scroll runs every frame; the API is polled on a background
  thread every `--refresh` seconds. A slow or dead server slows nothing on screen.
- **A fresh run arrives** (the newest `id` changed): its row flashes for five
  seconds and the ticker leads with `*** NEW RECORD: … ***` (or `EUGENE SHOT 66 OF
  100`) for thirty.
- **Link down**: the last board stays on screen, dimmed, and the running line says
  `LINK DOWN — RETRYING` with the reason. A scoreboard that goes blank because a
  Wi-Fi packet was lost is worse than a stale one.
- **One board, and only one**: the best round per player, best first. A panel
  rotating through TODAY and MOST ROUNDS PLAYED was built here and came back out —
  a screen people glance at from across the room should be showing the same thing
  every time they glance at it. The server still answers `window=today|week` and
  `order=attempts`, so another panel is a query away if it ever earns its place.
- **Resize** is picked up per frame; below 40 columns it drops to a compact
  `1.EUGENE 66` layout.
- Flags: `--url --token --ducks --top --refresh --speed --color green|amber|white
  --ascii --plain --bell`. `q` or Esc quits. All of them work through
  `python3 -m leaderboard` as well, which adds `--host --port --db --ducks --log`.

### The retro treatment

- **Phosphor palette.** `--color green` (the P1 look), `amber` (a VT220), `white`.
  Rows below the top three render dim, so the board fades down the list.
- **A boot sequence** typed out a character at a time, then the screen clears to
  the board — about 1.5 s, skipped by any key:
  ```
  DUCK HUNT SCOREBOARD v1.0
  MEMORY OK ....... 64K
  LINK http://localhost:8420 ... OK
  LOADING BOARD ...
  ```
- **A blinking block cursor** `█` parked at the end of the running line.
- **Dot leaders and uppercase**: `EUGENE ....... 66 DUCKS`. Names are upper-cased
  for display only; the database keeps what was typed.
- **Double-line box drawing**, with `--ascii` falling back to `+---+`.
- **A block-letter `DUCK HUNT` banner** from a five-row font built into the module
  (no `figlet` dependency), drawn when the terminal is tall enough.
- **`--bell`** beeps on a new record. A `\a` on a high score is exactly the right
  amount of 1983.
- **No flicker**: the whole frame is composed into one string and written once.

`--plain` turns all of it off, for when the board is a corner of a tiling window
manager rather than a screen.

## What changed in the game

`scores.json` is still written exactly as before — the per-machine mirror, and the
thing that works with no server anywhere. It is simply never shown any more.

1. **`WHO WAS SHOOTING?` after every round**, not only a record one: the board
   keeps every attempt, and a round nobody signed is a row nobody can find. Enter
   sends it, Esc skips it entirely. The buffer starts on the last name used
   (`player.json`, or `--player`), and the first character typed replaces it whole,
   so a new player does not have to backspace someone else's name out.
2. **The round has an identity**: `World` makes a `run_uuid` and stamps
   `started_at` when it is constructed, so a retried POST is recognised as the same
   round.
3. **`duckhunt/net/leaderboard_client.py`** posts on a worker thread — 3 tries,
   0.5/1/2 s apart — and on any failure appends the payload to
   `pending_runs.jsonl` next to `scores.json`. The queue is flushed oldest-first on
   the next launch and after every successful POST. A 4xx is *not* queued: the
   server refused the row itself, and retrying it forever on every launch would be
   a bug with a long memory.
4. **One line on the results screen**, about delivery and nothing else:
   `SENDING THE ROUND TO THE BOARD…` → `ON THE BOARD`, or `SAVED — WILL SYNC WHEN
   THE BOARD IS BACK`. Nothing when the board is off.
5. **`[leaderboard]` in `settings.toml`** (`enabled`, `url`, `client_id`,
   `timeout`, `token`), overridden by `DUCKHUNT_LEADERBOARD` and then by
   `--leaderboard URL` / `--no-leaderboard`.
6. **The ASCII frontend does the same** from `main.py`: a one-line prompt after the
   round, `--player NAME` to skip it, and no table printed on exit.

## Milestones

- [x] **M1 — store + server.** Schema, validation, the five routes.
- [x] **M2 — the console board.** The table, the running line, the poll thread, the
      link-down state.
- [x] **M3 — the name.** Asked after the round (not before, as this file first
      planned), remembered in `player.json`, `--player` to skip it.
- [x] **M4 — the game talks to the board.** The client, the `[leaderboard]`
      settings, the offline queue, the one delivery line on the results screen.
- [x] **M5 — seeding.** `leaderboard/seed.py`: import `scores.json`, `--demo N`.
- [ ] **M6 — autostart.** `systemd` units for the Pi / a `launchd` plist for the
      Mac, so the board comes up with the box.
- [ ] **M7 — optional.** Shoot-the-letters name entry (the only thing the keyboard
      is still needed for); `/api/events` as SSE so the display reacts instantly
      instead of polling.

## Files

| Path | What |
|---|---|
| `leaderboard/__main__.py` | `python3 -m leaderboard`: the server in a thread, the board in front |
| `leaderboard/store.py` | SQLite: schema, `insert_run`, `board`, `player`, `stats` |
| `leaderboard/server.py` | the HTTP server and its five routes |
| `leaderboard/display.py` | the blessed console board with the running line |
| `leaderboard/board.html` | the browser board: the same data as a tube TV |
| `leaderboard/seed.py` | import `scores.json`, generate and clear demo rows |
| `duckhunt/net/leaderboard_client.py` | POST + retries + `pending_runs.jsonl` |
| `duckhunt/core/player.py` | who played last, in `player.json` |
| `duckhunt/frontends/pygame_app.py` | the `name` mode after the round, the delivery line |
| `duckhunt/core/config.py`, `settings.toml` | the `[leaderboard]` section |
| `main.py` | `--player`, `--leaderboard`, `--no-leaderboard`, the ASCII prompt |
| `docs/LEADERBOARD.md` | this file |

## Checks worth running by hand

- Two players, the same name in different case → **one** row on the board, the
  higher score, `attempts` counting both.
- Twenty rounds by one player → the board shows their best,
  `/api/player/eugene` shows all twenty.
- Kill the server mid-evening, play three rounds, bring it back, relaunch the game
  → all three appear, none twice.
- A 50-duck round (`[round] ducks = 50`) does not mix into the 100-duck board.
- Pull the network cable from the display box → the board stays on screen, the
  ticker says the link is down, and it recovers on its own.
