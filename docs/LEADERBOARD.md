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
                                        │   ║ 1. EUGENE  55 pts  33 ducks ║ │
                                        │   ╚════════════════════════════╝ │
                                        │  ◀ NEW RECORD: EUGENE 55 *** 412 │
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
    hits         INTEGER NOT NULL,          -- ducks downed
    shots        INTEGER NOT NULL,
    ducks        INTEGER NOT NULL,          -- round size: 100-duck and 40-duck runs do not compete
    score        INTEGER NOT NULL DEFAULT 0,-- what the board ranks by; may be negative
    dog_hits     INTEGER NOT NULL DEFAULT 0,-- shots that hit the dog, at -5 each
    crosshair    INTEGER NOT NULL DEFAULT 0,-- 1 = the crosshair was up: not a record
    accuracy     REAL    NOT NULL,          -- hits/shots*100, stored so the board sorts cheaply
    duration     REAL    NOT NULL,          -- world.elapsed, seconds
    started_at   TEXT    NOT NULL,          -- ISO-8601 UTC
    finished_at  TEXT    NOT NULL,
    client_id    TEXT    NOT NULL,          -- which cabinet sent it
    input_source TEXT,                      -- mouse | serial | udp | keyboard
    game_version TEXT,
    settings     TEXT                       -- JSON: pace, duck size, speeds, ammo, the score table
);
CREATE INDEX runs_board_v2  ON runs (ducks, score DESC, hits DESC, shots ASC, finished_at ASC);
CREATE INDEX runs_player_v2 ON runs (player_key, score DESC, hits DESC, shots ASC);
```

**The score is not the hit count any anymore**, which is the one thing to keep in
mind reading the rest of this file. A duck is worth `+2`, a miss `−1` and the dog
`−5`, out of a magazine of 40 (`[round] ammo`, `[score]` — see the README), so a
round can finish below zero and the ranking had to stop meaning "who downed more".
Everything now ranks by `score DESC, hits DESC, shots ASC, finished_at ASC`: hits
break a tie, because between two equal scores the round that caught more ducks was
the better one. `store.RANK` is that clause, once, interpolated everywhere, so the
five places that rank cannot drift apart.

**The migration, because the database already existed.** `CREATE TABLE IF NOT
EXISTS` cannot add a column, so `init()` calls `_migrate()`: `PRAGMA table_info` for
the three columns, `ALTER TABLE … ADD COLUMN` for whichever are missing, and — only
when `score` was the missing one — `UPDATE runs SET score = hits` over the rows that
were already there. That backfill is not a guess: those rounds were played when a
duck was worth one point and nothing cost anything, so their score *was* their hit
count. It cannot run twice, so a genuinely negative score is never overwritten. The
old `runs_board` / `runs_player` indexes are dropped by name — `CREATE INDEX IF NOT
EXISTS` over an existing index is a silent no-op, which is why the new ones are
named `_v2` and the old names are gone rather than redefined.

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

**The board query** — best run per player, ranked by score:

```sql
SELECT name, score, hits, shots, ducks, accuracy, finished_at, attempts
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY player_key
                              ORDER BY score DESC, hits DESC, shots ASC,
                                       finished_at ASC) AS rn,
           COUNT(*)     OVER (PARTITION BY player_key) AS attempts
    FROM runs WHERE ducks = :ducks
)
WHERE rn = 1
ORDER BY score DESC, hits DESC, shots ASC, finished_at ASC
LIMIT :limit;
```

`attempts` comes free from the same pass, and the board shows `55 PTS … 33 DUCKS …
12 TRIES` — which is the fun part of keeping every row. A personal best is a better
*score* now, not more ducks: `answer()` compares scores, so a round that caught
fewer ducks but wasted far fewer shots is the improvement it says it is.

## The HTTP API

Everything is JSON. Errors are `{"error": "..."}` with a 4xx/5xx code.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/runs` | submit a finished round; returns rank and personal best |
| `GET` | `/api/board?ducks=100&limit=10&window=all\|today\|week&order=best\|attempts` | the board: best run per player |
| `GET` | `/api/player/<name>?ducks=100&limit=20` | one player: best run, attempt count, recent history |
| `GET` | `/api/players?q=жен&limit=8` | the name entry's search: who is already on the board |
| `GET` | `/api/stats?ducks=100` | totals for the running line |
| `GET` | `/healthz` | `{"ok": true}` — the display's link indicator |

**`POST /api/runs`** — the game sends:

```json
{ "run_uuid": "3f2c…", "name": "Eugene", "hits": 24, "shots": 40, "ducks": 40,
  "score": 44, "dog_hits": 1, "crosshair": false,
  "duration": 61.4, "started_at": "2026-09-02T18:20:11Z",
  "finished_at": "2026-09-02T18:21:12Z", "client_id": "eugene-mac",
  "input_source": "serial", "game_version": "0.5.0",
  "settings": {"interval": 0.9, "width": 0.13, "speed_min": 0.3, "speed_max": 0.65,
               "spread": 0.02, "ammo": 40, "duck": 2, "miss": -1, "dog": -5,
               "max_alive": 0} }
```

and gets back where the round landed:

```json
{ "ok": true, "rank": 3, "of": 17, "score": 44, "hits": 24, "dog_hits": 1,
  "personal_best": 44, "previous_best": 37, "improved": true, "attempts": 12,
  "world_record": {"name": "Anna", "score": 58, "hits": 30} }
```

`score`, `dog_hits` and `crosshair` are **optional**, and a POST without them is
accepted with `score = hits`: a cabinet running an older copy of the game plays the
old rule, where a duck was worth a point and nothing cost anything, so that is its
real score rather than a zero that would park its whole evening at the bottom of the
board.

The game does not draw any of that — it is there for the log, for a future results
screen on the *board's* side, and because a POST that answers only "ok" is a POST
nobody can debug.

- **Idempotent on `run_uuid`.** A retried POST returns the same answer instead of a
  duplicate row (`INSERT … ON CONFLICT(run_uuid) DO NOTHING`, then read back), and
  the answer is computed from the stored row, so a retry says what the first call
  said.
- **Validation, because the port is open on the LAN**: body ≤ 8 KB; `name` non-empty
  and trimmed to 50; `0 ≤ hits ≤ shots`; `hits ≤ ducks`; `1 ≤ ducks ≤ 10000`;
  `0 ≤ duration < 24 h`; `0 ≤ dog_hits ≤ shots`; timestamps parseable. Anything else
  is a `400` and is not stored — a junk row on the board is forever. `score` is the
  one number that is **not** bounded: a round genuinely can finish at `−35`, and
  clamping it at zero would only hide the worst round of the evening, which is half
  the entertainment.
- **Optional shared secret**: `--token SECRET` on the server, `X-Duckhunt-Key` on
  the request, compared with `hmac.compare_digest`. Off by default (home LAN);
  `[leaderboard] token` on the game's side when it goes to a public event.

`GET /api/stats` feeds the running line: rounds played, distinct players, ducks
downed, today's best, the standing record, and the most recent run (with
`is_record`) so the ticker can shout about a fresh one.

**`GET /api/players?q=`** is the only route the *game* reads rather than writes,
and it exists to stop one player becoming three. Typing a name from scratch every
evening is how `Женя`, `женя` and `Zhenya` end up as three rows, so the name entry
searches as it types and offers what is already there:

```json
{ "ok": true, "q": "жен",
  "rows": [ { "name": "Женя", "hits": 31, "shots": 40, "ducks": 40,
              "accuracy": 77.5, "attempts": 12,
              "last_played": "2026-09-26T21:40:02+00:00",
              "finished_at": "2026-09-12T19:02:44+00:00" } ] }
```

Four decisions are worth knowing, because each of them is a thing the obvious
version gets wrong:

- **Blind to case *and* to accents.** `player_key` (whitespace-collapsed,
  casefolded) is what groups a player's attempts; the *search* folds harder —
  `store.search_key` also strips combining marks, so `José` is reachable by
  `jose` and a `Женя` typed with a Latin `e` still lands. The folding happens on
  both sides of the comparison, inside SQL, via a `fold()` function registered on
  the connection: SQLite's own `LIKE` only knows ASCII case. Matching is `instr()`
  rather than `LIKE '%q%'` — substring, and nothing in a typed name has to be
  escaped, `%` and `_` included.
- **Every round size at once.** The board keeps 40-duck and 100-duck rounds apart
  on purpose, but a name is a name whatever they played, and a search that hid a
  regular because tonight's round is a different length would recreate the very
  duplicate it exists to prevent. So the score comes back with its own `ducks` and
  the screen says `31/40`.
- **The spelling that comes back is the first one they used**, not the one on
  their best run. It is what they will recognise, and the key groups the attempts
  either way.
- **An empty `q` is not an error**, it is the screen opening: the most recent
  players, which after one evening is exactly the right guess.

`LIKE`-versus-FTS5 does not come up at a few hundred rows, and SQLite's FTS5 is
there if it ever does — it will not.

## The server

`leaderboard/server.py` — `ThreadingHTTPServer`, a router of six routes, and
`leaderboard/store.py` doing every bit of SQL. `build()` hands a ready server back
rather than serving it, which is what lets `python3 -m leaderboard` run one in a
thread beside the board.

- `PRAGMA journal_mode=WAL` so the display's reads never block a write, and
  `PRAGMA busy_timeout=5000` for the rare overlap.
- A connection per request; nothing shared between threads.
- `--host 0.0.0.0 --port 8420 --db leaderboard.db --token …`
- One line per accepted run on stdout, so the terminal it runs in *is* the audit
  trail, leading with the number the board ranks by:
  `18:21:12  eugene  44 pts  24/40  92%  61s  rank 3`.

**Autostart on the Pi** (once it lives on a box of its own): a `systemd` unit for
the server and a second one for the display on tty1, both `Restart=always`; on a
Mac, the same with a `launchd` plist. Sketches go here when it happens — and not
before, because until there is a box the unit is a guessed user, a guessed path
and a guessed tty that nobody can run once to check. On this Mac there is nothing
for it to fix: `python3 -m leaderboard` is already one command, and a round posted
while the server is down is not lost but queued.

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
╔══════════════════════════════════════════════════════════════════════╗
║                                TOP 10                                ║
╠══════════════════════════════════════════════════════════════════════╣
║  1. EUGENE .................   55 PTS  33 DUCKS  75%  12 TRIES 09-02 ║
║  2. MIKE ...................   46 PTS  29 DUCKS  78%   4 TRIES 09-01 ║
║  3. ALEXANDRA KONSTAN… .....  -35 PTS   3 DUCKS   8%   1 TRY   09-26 ║
╚══════════════════════════════════════════════════════════════════════╝
◀ *** NEW RECORD: EUGENE — 55 PTS ***  412 ROUNDS PLAYED  ***
```

The panel is 70 columns inside rather than the 58 it was: five numbers do not fit
beside an 18-character name without the date falling off the end, and 72 all told
still sits inside an 80-column terminal. Under 40 columns the compact row shows the
score instead of the ducks — that is the number the board ranks by, and if only one
fits it is that one.

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
- **Dot leaders and uppercase**: `EUGENE ....... 55 PTS`. Names are upper-cased
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

`scores.json` is **no longer written at all**, and `duckhunt/core/scores.py` is
gone. It was ten rows on one machine, and it went on being written long after
anything stopped reading it back out — a mirror nobody looks in. What actually
survives a board being down is `pending_runs.jsonl`, which is a different
mechanism and a working one. `leaderboard/seed.py` keeps its own reader for an old
`scores.json`, because those files are real evenings and `--from-scores` exists to
put them on the board rather than to throw them away for being in the old shape.

1. **`WHO WAS SHOOTING?` after every round that could be a record**, not only a
   winning one: the board keeps every attempt, and a round nobody signed is a row
   nobody can find. (A round that could not be a record does not ask — see 3.)
   Enter sends it, Esc skips it entirely. The buffer starts on the last name used
   (`player.json`, or `--player`), and the first character typed replaces it whole,
   so a new player does not have to backspace someone else's name out.
2. **The names already there are offered under the field** — `/api/players?q=`
   searched as you type, `TAB` / `↓` / the trigger to take one, `↑` to come back
   off the list to what you typed, `ENTER` — or **A on the remote** — to send
   whatever is in the field. Trigger to pick and A to send is the gun-only path:
   a returning player never touches the keyboard, and A has nothing else to do on
   this screen (there is no crosshair here to toggle). The
   lookup is `PlayerLookup` in the same client module: its own worker thread, one
   request per pause in the typing rather than one per keystroke, a 1.5 s ceiling,
   and every failure an empty list — the name screen must never wait on the board,
   and with the board off it is exactly the screen it was before.
3. **Not every round is offered.** `leaderboard_client.refusal(world, settings)` is
   the one place that decides, and both frontends ask it: a practice round
   (`[round] scored = false`) is not a record by definition, and a scored round that
   had the crosshair up at any point is not one either — a scored round is shot down
   the sights. A refused round skips the `WHO WAS SHOOTING?` screen altogether
   rather than asking for a name nobody will ever find, and the results screen says
   which of the two reasons applies. `crosshair` still rides along in the payload
   and is stored, so the server can turn such a row away itself if a cabinet ever
   sends one.
4. **The round has an identity**: `World` makes a `run_uuid` and stamps
   `started_at` when it is constructed, so a retried POST is recognised as the same
   round.
5. **`duckhunt/net/leaderboard_client.py`** posts on a worker thread — 3 tries,
   0.5/1/2 s apart — and on any failure appends the payload to
   `pending_runs.jsonl` in the project root. The queue is flushed oldest-first on
   the next launch and after every successful POST. A 4xx is *not* queued: the
   server refused the row itself, and retrying it forever on every launch would be
   a bug with a long memory.
6. **One line on the results screen**, about delivery and nothing else:
   `SENDING THE ROUND TO THE BOARD…` → `ON THE BOARD`, or `SAVED — WILL SYNC WHEN
   THE BOARD IS BACK`. Nothing when the board is off.
7. **`[leaderboard]` in `settings.toml`** (`enabled`, `url`, `client_id`,
   `timeout`, `token`), overridden by `DUCKHUNT_LEADERBOARD` and then by
   `--leaderboard URL` / `--no-leaderboard`.
8. **The ASCII frontend does not talk to the board at all**, and that is a
   decision rather than an omission. It draws a `+` at the aim point and the arrow
   keys move that mark, so the mark *is* the aiming, exactly as the crosshair is for
   the mouse; it passes `crosshair=True` to every `world.update` and `refusal()`
   turns the round away. A board where a keyboard round and a light-gun round sat in
   the same column would not be measuring anything.

   So the prompt is gone rather than unreachable: it used to ask who was shooting,
   remember the name and post the row, and all of that was dead the moment the rule
   applied to it. `main.py` prints the result and one line saying a keyboard round is
   not for the board, which is the whole of its business with the leaderboard now.
   The round is still played and still scored on screen. `--player` stays — it
   pre-fills the pixel frontend's question.

## Milestones

- [x] **M1 — store + server.** Schema, validation, the five routes.
- [x] **M2 — the console board.** The table, the running line, the poll thread, the
      link-down state.
- [x] **M3 — the name.** Asked after the round (not before, as this file first
      planned), remembered in `player.json`, `--player` to skip it.
- [x] **M4 — the game talks to the board.** The client, the `[leaderboard]`
      settings, the offline queue, the one delivery line on the results screen.
- [x] **M5 — seeding.** `leaderboard/seed.py`: import an old `scores.json`, `--demo N`.
- [ ] **M6 — autostart.** `systemd` units for the Pi / a `launchd` plist for the
      Mac, so the board comes up with the box. Blocked on the Pi existing: see
      the note under **The server** for why it buys nothing here.
- [ ] **M7 — if it earns it.** Shoot-the-letters name entry — now only for a name
      the board has never seen, since the trigger picks one it has and A sends it;
      `/api/events` as SSE so the display reacts instantly instead of polling.

## Files

| Path | What |
|---|---|
| `leaderboard/__main__.py` | `python3 -m leaderboard`: the server in a thread, the board in front |
| `leaderboard/store.py` | SQLite: schema, `insert_run`, `board`, `player`, `search_players`, `stats` |
| `leaderboard/server.py` | the HTTP server and its six routes |
| `leaderboard/display.py` | the blessed console board with the running line |
| `leaderboard/board.html` | the browser board: the same data as a tube TV |
| `leaderboard/seed.py` | import an old `scores.json`, generate and clear demo rows |
| `duckhunt/net/leaderboard_client.py` | POST + retries + `pending_runs.jsonl`, and `PlayerLookup` |
| `duckhunt/core/player.py` | who played last, in `player.json` |
| `duckhunt/frontends/pygame_app.py` | the `name` mode after the round, the names on offer, the delivery line |
| `duckhunt/core/config.py`, `settings.toml` | the `[leaderboard]` section |
| `main.py` | `--player`, `--practice`, `--leaderboard`, `--no-leaderboard` |
| `practice.toml` | the practice round: ten slow ducks, one at a time, nothing sent |
| `docs/LEADERBOARD.md` | this file |

## Tests

`.venv/bin/python -m pytest tests/ -q` — the store's queries, the routes over a
real `ThreadingHTTPServer` on a throwaway database, and `PlayerLookup` against
both a live server and a dead port. They never touch `leaderboard.db`, so they
run happily while an evening's board is up.

## Checks worth running by hand

- Two players, the same name in different case → **one** row on the board, the
  higher score, `attempts` counting both.
- A round shot with the crosshair on → no name screen, the results screen says the
  crosshair was up, and nothing arrives on the board.
- `--practice` → no name screen either, and the board is untouched by ten rounds of it.
- A round that ends on an empty magazine → the shot that emptied it counted, the last
  duck landed, and the row that arrives says the score, not the ducks.
- An old copy of the game posting without `score` → accepted, ranked as `score = hits`.
- Type three letters of a name that is on the board → it appears under the field;
  the trigger takes it without touching the keyboard; the round lands on that
  player's row and moves their `tries`, not their best.
- Play a round with the board stopped → the name screen has no list, waits for
  nothing, and Enter still sends (to `pending_runs.jsonl`).
- Twenty rounds by one player → the board shows their best,
  `/api/player/eugene` shows all twenty.
- Kill the server mid-evening, play three rounds, bring it back, relaunch the game
  → all three appear, none twice.
- A 50-duck round (`[round] ducks = 50`) does not mix into the 100-duck board.
- Pull the network cable from the display box → the board stays on screen, the
  ticker says the link is down, and it recovers on its own.
