# 🦆 What is left to do

The gun works. The four-corner homography solves, the axes are settled, the
beacons hold, the sights are corrected, and a round plays end to end — so the
whole measurement list that used to live in this file has been retired, and with
it the two firmware skeletons (the from-scratch PixArt gun and the bezel-finding
ESP32-S3-CAM plan B). Nothing is falling back to anything: the remote plays.

Stage 7, the leaderboard, is built and running — the server, the console board on
a screen of its own, and the game posting one row per round without drawing any of
it ([`docs/LEADERBOARD.md`](LEADERBOARD.md)). It is finished through M5, and the one
milestone still open is waiting on hardware rather than on anyone writing it. The
milestone numbers are `LEADERBOARD.md`'s, and they match it.

**The three jobs that used to sit below this are done**: the name search, the two
rounds, and the clear-out. What is left in this file is the two things blocked on a
box that does not exist, one rough edge in the smallest window, and M7 — the list of
things that only earn themselves once the game is played often enough to ask for
them. There is a test suite now: `.venv/bin/python -m pytest tests/ -q`, 87 tests
over the store's queries, the routes, the two rounds' arithmetic and the name screen
driven headlessly.

## Next up

- [x] **M1 — store + server.** `leaderboard/store.py`, `leaderboard/server.py`.
- [x] **M2 — the console board.** `leaderboard/display.py`.
- [x] **M3 — the name.** Asked AFTER the round instead of before it, and after
      every round rather than only a record one: a player who has just shot has a
      number they want on the board, which is when they will gladly type. The
      pixel frontend's `name` mode, the field left empty (Sept 2026: it used to
      remember the last name in `player.json`, which signs one player's round to
      the player before them), `--player` to skip the typing.
- [x] **M4 — the game talks to the board.** `duckhunt/net/leaderboard_client.py`,
      the `[leaderboard]` settings, the offline queue, and one line on the results
      screen about delivery and nothing else — the board's own content stays on
      the board's own screen. Checked both ways: with the server up the row is
      there in under a second, and three rounds played with it down arrive once
      each after it is back.
- [x] **M5 — seeding.** `leaderboard/seed.py` (`--from-scores`, `--demo N`), the
      ticker's record announcements, README and `LEADERBOARD.md` rewritten to what
      was actually built.
- [ ] **M6 — autostart. Blocked on the Pi existing, and not otherwise wanted.**
      `systemd` units for the Pi, a `launchd` plist for the Mac. Two things this
      is *not* for, both of which it used to claim: it is not two terminals down
      to one — `python3 -m leaderboard` already runs the server in a thread with
      the board in the foreground, one thing to start and `q` to quit both — and
      it is not a round saved, because a round posted with the server down goes
      to `pending_runs.jsonl` and arrives when it is back. What it is for is the
      box in a room with no keyboard on it, powered up by a wall switch, which is
      the Pi under the TV and does not exist yet. Written before that box is
      here, a unit is a guessed user, a guessed path and a guessed tty that
      nobody can run once to check.
- [ ] **The smallest window clips the keymap.** A results screen carrying both
      `STOPPED EARLY` (or `OUT OF AMMUNITION`) *and* a delivery line needs about
      510 px of panel, and the smallest windowed picture is 450 px tall, so the last
      row or two of the keymap goes off the bottom. Pre-existing — the old layout
      needed 482 px of the same 450 — and invisible in fullscreen, which is how the
      game is actually played. The real cause is that the fonts are fixed at 22/40 pt
      while the picture is not; the fix is font sizes measured off the picture, the
      way the keymap, the HUD and the name screen's own two lines already are.
- [ ] **M7 — if it earns it.** Shoot-the-letters name entry, `/api/events` so the
      board reacts instead of polling, per-day and per-week boards on a rotating
      panel.

The by-hand checks that say M4 is really finished are at the end of
`docs/LEADERBOARD.md`; the two that have caught things before are the same name in
two cases landing on one row, and the server killed mid-evening.

## After the leaderboard

All three are done, in the order 2, 1, 3: the name search first because it touched
nothing the other two needed, then the two rounds, then the clear-out once there was
something to clear out *of*. They are kept here rather than deleted because each one
records a decision that is not in the code — what was rejected, and why.

### 1. ~~Two modes: a scored round and a practice round~~ — done

Two settings files over the same game rather than two code paths, which is what
`--settings hard.toml` was always for.

**Scored** — `settings.toml`, the default: 40 ducks and **40 shots**. The round ends
when the ducks run out or the magazine does, whichever comes first; the shot that
empties it still counts, a duck already falling still lands, and no further ducks
are launched with nothing left to shoot them with. `+2` a duck, `−1` a miss, `−5`
the dog — the dog's penalty replaces the miss rather than stacking on it. The score
may go below zero and is shown below zero.

**Practice** — `practice.toml` laid over the settings: ten ducks, slow, **one in
the air at a time** (`[duck] max_alive = 1`, the only genuinely new mechanic — the
pace is a timer, so the held-back duck goes up the moment the sky clears rather
than waiting out another interval), unlimited ammunition, the crosshair on, and
nothing sent to the board.

**Chosen in the game, not at launch** (Sept 2026). The title screen cycles the
modes with **M**, or **A on the remote** — which is the binding that matters,
since handing the gun over and taking it back is exactly when the round changes
and the player is three metres from the keyboard. `--practice` / `--mode NAME`
now only say which round the evening opens on. What made it switchable is that
the rule was written down and enforced (`config.MODE_SECTIONS`): a mode owns
`[round]`, `[duck]`, `[score]` and `[gun] crosshair`, and nothing else — so the
window, the sight-in, the beacons, the sounds and the board never move, and a
switch costs a new `World` and a re-sized duck. Any other round is another file:
`modes/*.toml`, named by its own `[mode]` section, on the screen without being
registered anywhere.

**The dog crossed the line the honest way.** He is still drawn entirely by the
frontend, and `core` still has never heard of him — but `World.update` now takes
`dog_box` for the frames he is up, in the same 0..1 coordinates as the aim, so the
shot that hits him is decided where every other shot is decided and costs what the
settings say.

**A scored round is shot down the sights**, which needed a decision the old note
did not have: the crosshair was *on* by default, so the rule as written would have
meant no round ever counted. `[gun] crosshair` is now `"auto"` (off with a gun
plugged in, on for the mouse, which has no front sight to aim down), `"on"` or
`"off"`. `C` and A on the remote still flip it; `world.crosshair_used` is latched,
so flipping it back does not launder the round, and `leaderboard_client.refusal()`
is the one place that decides whether a round may be offered — both frontends ask
it, the results screen says which reason applies, and a refused round skips the
name screen altogether rather than asking for a name nobody will find.

**The latch starts with the first duck** (Sept 2026). The title screen and the
countdown used to latch it too, on the grounds that three seconds in the stance
with the crosshair up is exactly how you read the offset between the front sight
and where the shot lands. In practice it turned the one honest move — crosshair
on to check the gun is tracking, off to play — into a refusal, and the round that
followed really was shot down the sights. So the rule is now judged over the
round: `World.update` is the only thing that latches it, and the two screens
before the round are free.

**The board ranks by score**, done with the modes rather than after them: `score`,
`dog_hits` and `crosshair` in the schema, the payload and the validator, both
indexes and every `ORDER BY` changed to `score DESC, hits DESC, shots ASC`, a
migration that adds the columns to the database that already exists and backfills
old rows with `score = hits` (exactly right: they were played when a duck was worth
one point and nothing cost anything), and both boards showing the number they rank
by.

Tests: `tests/test_round_modes.py` (ammunition, the penalties, the dog's box, the
one-at-a-time pace, the crosshair latch), `tests/test_score_board.py` (ranking,
the migration) and `tests/test_name_screen.py` (the screen driven headlessly).

### 2. ~~Name entry that finds the name you already have~~ — done

Typing a name from scratch every evening is how `Женя`, `женя` and `Zhenya` end up
as three players. The name entry now searches as you type and offers what is
already there to pick instead.

- **`GET /api/players?q=`** — the sixth route. `store.search_players`: one row per
  player, the spelling they first used, their best run with its own round size, and
  the attempt count, so the screen shows `Женя — 31/40 (12 tries)`. Blind to case
  *and* to accents (`store.search_key` strips combining marks; the folding happens
  inside SQL through a `fold()` function registered on the connection, because
  SQLite's `LIKE` only knows ASCII case), matched with `instr()` so nothing in a
  typed name needs escaping, and across every round size — a name is a name
  whatever length of round it was first typed in. An empty `q` is the screen
  opening: the most recent players.
- **`PlayerLookup`** in `duckhunt/net/leaderboard_client.py` — the client's first
  GET. Its own worker thread, one request per pause in the typing rather than one
  per keystroke, a 1.5 s ceiling, and every failure an empty list: the name screen
  never waits on the board, and with the board off it is the screen it always was.
- **The list under the field**: `TAB` / `↓` / **the trigger** takes the next name,
  `↑` comes back off the list to what was typed, `ENTER` — or **A on the remote** —
  sends whatever is in the field. Trigger to pick and A to send is the point: a
  player three metres away with a gun in both hands no longer walks to the keyboard
  for a name that is already there, which is exactly how the fourth spelling of it
  used to arrive. A name the board has never seen still needs the keyboard — that
  is what M7's shoot-the-letters entry is left for.
- **Picking an existing name overwrites nothing**, and the screen says so in as
  many words: every attempt has always been its own row, the board is the best row
  per player, so a worse round moves `tries` and leaves the best where it was.
- The ASCII path got that line too, and then lost the whole prompt: a keyboard
  round is refused by the same rule (its `+` is the aiming), so asking who was
  shooting was asking for a row that would never exist. `main.py` prints the result
  and one line saying so. That is the second thing the rule cost, after the mouse,
  and both were the point of it rather than a surprise.
- Tests: `tests/` (new — `pytest`), covering the folding, prefix-before-substring,
  the first spelling, wildcards as literal characters, the route over a real
  server, and `PlayerLookup` against both a live server and a dead port.

### 3. ~~Clear out what is no longer used~~ — done, and three of the five were wrong

The instruction this list came with was "to be checked rather than trusted", and
that turned out to be the valuable half of it: two candidates were dead, three were
not, and saying which is which is the result.

**Deleted — the remote straight over Bluetooth.** `duckhunt/input/wiimote.py`,
`--wiimote`, and `hidapi` out of `requirements.txt` (nothing else imported it, in
the repo or in the venv). It was labelled "kept for reference" in its own docstring
and in the README, which is a job git already does better. `tools/wiimote_monitor.py`
stays — it watches the *bridge*, which is the live path.

**Deleted — the local high-score table.** `duckhunt/core/scores.py` is gone and
`scores.json` is no longer written. Ten rows on one machine, invisible to anyone not
sitting at it, still being written long after the last thing that read them back was
removed. Three things had to find a home first, which is why this was not a delete
but a move:

- `NAME_MAX` went to `duckhunt/core/player.py`, next to the name it limits.
- `pending_path()` was deriving the project root from `scores.default_path()`; it
  works it out from its own module now. (It leaned on `player.default_path()` for a
  while, until `player.json` went the same way as `scores.json` — see M3.) The
  offline queue never had anything to do with the score table.
- `--from-scores` **kept its reader**, moved into `leaderboard/seed.py` as
  `read_scores()`. An old `scores.json` in somebody's project root is a handful of
  real evenings, and the import exists to put them on the board rather than to throw
  them away for being in the old shape. It is the only thing left that understands
  that format, so it has tests of its own now (`tests/test_seed_import.py`),
  including a malformed row and a broken file.

**Not dead: the alignment and calibration screens.** The suspicion was that three
hardware evenings had left redundant controls behind. They had not. `--calibrate` is
literally F1 called at startup and `--align` is TAB's boolean pre-flipped — both
documented in the README as the way the procedure is run, so they are shortcuts, not
duplicates. F2 and `--no-calibration` look like the same switch and are not: F2
toggles a correction that was *loaded*, while `--no-calibration` means
`calibration.json` is never read at all, which is what you reach for when you
suspect the file itself. That distinction was in `--help` and nowhere else, so it is
in the README now. TAB (where to tape the beacons) and F1 (sight parallax) measure
two unrelated things. Nothing here was removed. Worth knowing before anyone tries
again: `tests/` covers none of it.

**Not dead: `tools/ir_view.py`.** 1321 lines, and the parts that look like finished
measurements are the parts that come back the first time the rig moves —
`--bezel` computes the `[gun] beacon_*` numbers that are baked into `settings.toml`
today, and `settings.toml` quotes the exact invocation that produced them. `--plan`
says where to stand, the axis checks matter after any reflash, and the README points
at the live view and `--summary` for ordinary debugging. All seven files in `tools/`
are referenced by the README or `docs/BUILD.md`. A hardware instrument is not dead
code just because the hardware currently works.

**`settings.toml` was not split, and the reason is worth recording.** 357 lines,
three quarters of them comments, and every key in it has a live reader — there is no
dead weight to remove, only an ordering problem. Splitting the hardware block into a
second file is now mechanically possible (`config.load()` grew `overlay=` for
`--practice`), but it would mean two files to keep in step, a second path to pass
around, and `--settings` meaning something different depending on which half you
meant. What the file actually needed was to say where things are: it now opens with
a map of its own sections, and the `[gun]` section is fenced in two — the *feel*
(spread, crosshair, lead) above the line, the *rig* (frame, beacons: the only part
about one particular room) below it. If the split is wanted anyway, it is a small
change on top of this and the fence is where it would cut.


