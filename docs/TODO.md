# 🦆 What is left to do

The gun works. The four-corner homography solves, the axes are settled, the
beacons hold, the sights are corrected, and a round plays end to end — so the
whole measurement list that used to live in this file has been retired, and with
it the two firmware skeletons (the from-scratch PixArt gun and the bezel-finding
ESP32-S3-CAM plan B). Nothing is falling back to anything: the remote plays.

Stage 7, the leaderboard, is built and running — the server, the console board on
a screen of its own, and the game posting one row per round without drawing any of
it ([`docs/LEADERBOARD.md`](LEADERBOARD.md)). It is finished through M5: one
command brings the whole thing up, and the one milestone still open is waiting on
hardware rather than on anyone writing it. So the real next work is the two ideas
below, which only matter once people play often enough to have names worth
finding. The milestone numbers are `LEADERBOARD.md`'s, and they match it.

## Next up

- [x] **M1 — store + server.** `leaderboard/store.py`, `leaderboard/server.py`.
- [x] **M2 — the console board.** `leaderboard/display.py`.
- [x] **M3 — the name.** Asked AFTER the round instead of before it, and after
      every round rather than only a record one: a player who has just shot has a
      number they want on the board, which is when they will gladly type. The
      pixel frontend's `name` mode, `player.json` remembering the last one,
      `--player` to skip it.
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
- [ ] **M7 — if it earns it.** Shoot-the-letters name entry, `/api/events` so the
      board reacts instead of polling, per-day and per-week boards on a rotating
      panel.

The by-hand checks that say M4 is really finished are at the end of
`docs/LEADERBOARD.md`; the two that have caught things before are the same name in
two cases landing on one row, and the server killed mid-evening.

## After the leaderboard

These three are the next real work — M6 is parked until there is a Pi to park it
on. All of them touch files another session is writing right now (`main.py`, `frontends/pygame_app.py`, `core/world.py`, `core/config.py`,
`leaderboard/store.py`), so starting early means merging for no reason.

### 1. Two modes: a scored round and a practice round

Today there is one round and it is always for the record. Split it in two.

**Scored** is what plays today — 40 ducks, shot down the sights — plus a cost for
firing:

- **40 rounds of ammunition.** The round ends when the ducks run out *or* the
  magazine does, whichever comes first (the shot that empties it still counts, and
  a duck already falling still lands). Today nothing counts ammunition at all:
  `World.finished` looks only at how many ducks have been launched.
- **+2 a duck, −1 a miss, −5 the dog.** The first two are cheap — `World` already
  keeps `shots` and `hits`, and `[round] points` is the +2 knob under a new name.
  The dog is not: it lives entirely in the pixel frontend, an animation driven by
  the `landed` and `escaped` counters, and `core` has never heard of it. Something
  has to cross that line — the honest version is the frontend handing the world
  the dog's box while it is up, so the hit is decided where every other hit is.
- **The crosshair stays toggleable, but a round that used it does not count.** `C`
  (and `A` on the remote) already flips it; what is missing is the round
  remembering that it was ever on, and that flag riding along in M4's payload so
  the server can turn the row away.

**Practice** is for handing the gun to someone who has never held one: **10 ducks,
slow, one in the air at a time**, crosshair on or off as they like, nothing sent
to the board. One duck at a time is the only genuinely new mechanic — the pace
today is a timer, so a `max_alive` cap is needed to make the next duck wait for
the last one.

**Every number a setting, and the modes as files.** `--settings hard.toml` already
works, so the two modes are two files over the same defaults rather than a second
code path:

```toml
[round]
ducks = 40         # 10 in practice.toml
ammo = 40          # shots per round; 0 = unlimited (practice)
scored = true      # false = never offered to the leaderboard

[score]
duck = 2           # a duck downed  (was [round] points = 1)
miss = -1          # a shot that hit nothing
dog = -5           # a shot that hit the dog

[duck]
max_alive = 0      # 0 = as many as the pace launches; 1 = one at a time
```

`main.py --practice` as a shortcut for `--settings practice.toml` keeps it one
keystroke at the title screen.

Two things to decide before writing it:

- **May the score go negative?** −1 a miss with 40 shots means it can. Letting it
  is the honest answer and the HUD can show it; clamping at zero only hides that
  the round went badly.
- **The board has to rank by score, not by hits.** `runs` has no `score` column
  and `board()` orders by `hits DESC, shots ASC` — which stops meaning anything
  once a miss costs a point and the dog costs five. So: `score` (and a `dog_hits`
  counter) into the schema and the payload, the two indexes and both order-by
  clauses changed, and `leaderboard/display.py` showing the number it ranks by.
  Do this *with* the mode work, not after it, or the first scored round on the
  board will be ranked by the old rule.

### 2. Name entry that finds the name you already have

Typing a name from scratch every evening is how `Женя`, `женя` and `Zhenya` end up
as three players. The name entry should search as you type and offer what is
already there to pick instead.

- **The server side is a route that does not exist yet**: the five are `/healthz`,
  `/api/board`, `/api/stats`, `/api/player/<name>` and the POST. Add
  `/api/players?q=` — prefix and substring, case- and accent-blind, returning the
  name as it was first spelled with its best score and attempt count, so the
  entry screen can show `Женя — 66 (12 tries)` rather than a bare list. SQLite's
  FTS5 is there if `LIKE '%q%'` over a few hundred rows ever stops being enough,
  which it will not.
- **The client side** is the `name` mode M3 built, which currently offers exactly
  one candidate — the last name used on this machine. What is missing is a list
  under the field: the trigger or `TAB` to take a suggestion, `ENTER` to keep what
  was typed as a new player.
- **Picking an existing name is not overwriting anything.** This is already how
  the store works and it is worth not breaking: every attempt is its own row, and
  the board is a query for the best row per player (`_BEST_PER_PLAYER`). So a
  worse round still gets stored — it moves `attempts` and nothing else — and the
  board keeps showing the best. Nothing to build here beyond making the screen say
  so, which stops it looking like the run was thrown away.

### 3. Clear out what is no longer used

Once the modes and the name entry are in, a pass over what nobody calls any more.
Known candidates, to be checked rather than trusted:

- `duckhunt/input/wiimote.py` — the remote straight over Bluetooth, which macOS
  never let work; kept as reference for a path that is now closed.
- `core/scores.py` and `scores.json` — the local high-score table, once the board
  is the real one. `leaderboard/seed.py` imports the file, so the import runs
  first and the table goes after.
- The alignment and calibration screens' overlap: `--align`, `--calibrate`, `F1`,
  `F2`, `TAB` accumulated over three hardware evenings and some of it was for
  beacons that are now stuck down for good.
- `settings.toml` is 15 kB of comments for keys that were tuned once and never
  touched again; splitting the hardware block out of the game block would make
  both readable.
- Dead ends in `tools/`: `ir_view.py` is 1300 lines, most of it written for
  measurements that are now finished.

Run it as its own pass with the game playable at the end of each step, not as a
tidy-up bolted onto a feature.
