# 🏆 Leaderboard — a separate server with a scoreboard of its own

The game used to keep its top ten in `scores.json` next to `settings.toml`: local
to one Mac, invisible to anyone not sitting at it, and it only remembered the ten
best rounds — every other attempt was thrown away.

That is now a **separate leaderboard**, on a screen of its own: the game asks who
was shooting *after* the round, posts one row, and the server keeps **every
attempt** in SQLite while the board shows **the best result per player**, with a
running line scrolling along the bottom.

Two rules decide everything below:

- **The name is asked after the round.** A player walks up, is handed a gun and
  shoots; being asked to type first is a form to fill in before a game. Afterwards
  they have a number they want on the board, which is the moment they will happily
  spell their name. The field starts **empty** — nothing is remembered between
  rounds, because the next player is not the last one — and the names already on
  the board are offered under it to be taken with the trigger. `--player NAME` is
  the evening with one shooter, where it is Enter, Enter, Enter.
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
                                        │  leaderboard/board.html (a tube TV)│
                                        │   ╔════ DUCK HUNT — TOP 10 ════╗ │
                                        │   ║ 1. EUGENE  55 pts  33 ducks ║ │
                                        │   ╚════════════════════════════╝ │
                                        │  ◀ NEW RECORD: EUGENE 55 *** 412 │
                                        └──────────────────────────────────┘
```

Separate processes, deliberately: the game must never freeze or crash because the
scoreboard is off, and the scoreboard must survive the game being restarted twenty
times an evening. They meet at one HTTP endpoint and one SQLite file.

**Why HTTP and not the `x,y,b`-style UDP the gun uses.** One packet per *round* —
delivery matters far more than latency, and a lost UDP datagram is a lost record.

**Why SQLite.** One writer, a handful of rows per minute, and the query we need
("best run per player") is a three-line window function. No server to run and no
dependency to install: `sqlite3` and `http.server` are standard library, and the
board is one HTML file the same server hands out. `requirements.txt` did not
change.

## Running it

Two commands, one for the scoreboard and one for the game:

```bash
cd /Users/evgenychernyak/projects/duckhunt

# the scoreboard: the server, and the tube-TV board in a browser window
.venv/bin/python -m leaderboard

# and the game, told where to send its rounds
.venv/bin/python main.py --serial /dev/tty.usbserial-0001 \
                         --leaderboard http://localhost:8420
```

Drag the browser window to the second screen and press **F** — it goes fullscreen
and stays there all evening.

`python3 -m leaderboard` runs the server in a thread of this process, opens the
page and holds the terminal until Ctrl-C: one thing to start, one thing to quit.
The flags that shape the page are turned into its query string, so
`--color amber --top 12 --ducks 50` work here. The server's per-run lines would
scroll past unread, so they go to `leaderboard.log` next to the database
(`--log FILE` moves it, `--log -` throws it away). Started a second time on a
port that already answers, it shows that board instead of failing on "address
already in use".

Two processes are still the right thing when the board is on one screen's machine
and the game on another, or when either has to be restarted without the other:

```bash
.venv/bin/python -m leaderboard.server --port 8420 --db leaderboard.db
# ... and http://raspberrypi.local:8420/ in a browser over there
```

`--leaderboard URL` is the one-off; the permanent way is `[leaderboard] enabled =
true` in `settings.toml`. `--no-leaderboard` turns it off for one session,
`--player NAME` skips the question after every round.

Rounds the board never saw — an old `scores.json` from before it existed:

```bash
.venv/bin/python -m leaderboard.seed --from-scores  # import the local scores.json
```

It is idempotent (the row's own id is derived from the row), so running it twice
does not double the board. There used to be a demo generator next to it that invented
players with names, surnames and form, to see the board full before anyone had
played; the board has real rounds on it now, and invented ones next to them are
just a thing to remember to delete.

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
12 TRIES` (the row's `accuracy` and `finished_at` are still served, just not drawn) — which is the fun part of keeping every row. A personal best is a better
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
- **No authentication.** The board is on the house LAN, and a shared secret was
  one more thing to keep in step between the server, the game and a page that
  cannot set a header on its own fetches. If this ever goes to a public event,
  the place for it is a reverse proxy in front, not four files here.

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
- `--host 0.0.0.0 --port 8420 --db leaderboard.db`
- One line per accepted run on stdout, so the terminal it runs in *is* the audit
  trail, leading with the number the board ranks by:
  `18:21:12  eugene  44 pts  24/40  92%  61s  rank 3`.

**Autostart on the Pi** (once it lives on a box of its own): a `systemd` unit
for the server, `Restart=always`, with a browser started on the display; on a
Mac, the same with a `launchd` plist. Sketches go here when it happens — and not
before, because until there is a box the unit is a guessed user, a guessed path
and a guessed tty that nobody can run once to check. On this Mac there is nothing
for it to fix: `python3 -m leaderboard` is already one command, and a round posted
while the server is down is not lost but queued.

## The board

`leaderboard/board.html`, served by the same server at `/`. One file, no build, no
dependency; the server reads it from disk on every request, so tuning how it looks
is a reload rather than a restart.

There was a second one for a while, `leaderboard/display.py`: the same rows drawn
in a terminal with `blessed`, box drawing and dot leaders, for a Pi on a tty with
no desktop. It was good, and it is gone — two boards over one set of rows is two
things to keep in step every time a column moves, and the Pi it was for does not
exist. `git log` has it if a keyboard-less box ever turns up.

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
  tiling window manager).
- **Keys**: `F` fullscreen, `C` next colour, `B` next cabinet, `E` effects on and
  off.
- Polls `/api/board` and `/api/stats` every `refresh` seconds while the ticker
  scrolls every frame; a fresh run flashes its row and the ticker leads with
  `*** NEW RECORD ***`; with the link down the last board stays on screen, dimmed.

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
   Enter sends it, Esc skips it entirely. The buffer starts **empty**, and Enter
   on an empty buffer does nothing: a pre-filled field plus the remote's A is how
   one player's round gets signed with the name of the one before them. `--player
   NAME` fills it for a one-shooter evening, and there the first character typed
   replaces it whole rather than having to be backspaced out.
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
   had the crosshair up at any point **of the round** is not one either — a scored
   round is shot down the sights. The title screen and the countdown are not the
   round: the crosshair is free there, and the latch starts with the first duck.
   The third reason is a round with **no shot in it** — what Esc on the countdown
   leaves behind — which used to arrive as an empty `0/40` row. A refused round skips the `WHO WAS SHOOTING?` screen altogether
   rather than asking for a name nobody will ever find, and the results screen says
   which of the three reasons applies. `crosshair` still rides along in the payload
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
   `timeout`), overridden by `--leaderboard URL` / `--no-leaderboard`.
8. **A mouse round is never a record**, and that is a decision rather than an
   omission: a mouse has no sights to aim down, so there the crosshair *is* the
   aiming. `refusal()` turns those rounds away and the results screen says why.
   A board where a mouse round and a light-gun round sat in the same column
   would not be measuring anything. The same rule retired the ASCII frontend's
   whole conversation with the board, and then the frontend itself.

## Milestones

- [x] **M1 — store + server.** Schema, validation, the five routes.
- [x] **M2 — the board.** The table, the running line, the poll thread, the
      link-down state.
- [x] **M3 — the name.** Asked after the round (not before, as this file first
      planned), the field empty and the board's own names offered under it,
      `--player` to skip the typing altogether.
- [x] **M4 — the game talks to the board.** The client, the `[leaderboard]`
      settings, the offline queue, the one delivery line on the results screen.
- [x] **M5 — seeding.** `leaderboard/seed.py`: import an old `scores.json`.
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
| `leaderboard/board.html` | the browser board: the same data as a tube TV |
| `leaderboard/seed.py` | import an old `scores.json` |
| `duckhunt/net/leaderboard_client.py` | POST + retries + `pending_runs.jsonl`, and `PlayerLookup` |
| `duckhunt/core/player.py` | how much name a player may type (`NAME_MAX`) |
| `duckhunt/frontends/pygame_app.py` | the `name` mode after the round, the names on offer, the delivery line |
| `duckhunt/core/config.py`, `settings.toml` | the `[leaderboard]` section |
| `main.py` | `--player`, `--mode`, `--leaderboard`, `--no-leaderboard` |
| `practice.toml` | the practice round: ten slow ducks, one at a time, nothing sent |
| `duckhunt/core/modes.py` | the rounds the title screen cycles — a mode may not touch `[leaderboard]` |
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
- The practice round → no name screen either, and the board is untouched by ten
  rounds of it. Worth doing by switching to it with **M** on the title screen
  rather than with `--mode practice`, since that is how it is reached in an
  evening:
  the round that follows the switch must be the practice one, and the scored
  round switched back to must still reach the name screen.
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
