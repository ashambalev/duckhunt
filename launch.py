"""The whole evening from two commands: ./setup once, then ./play.

    ./setup                      # the picker, the gun's view, the calibration
    ./play                       # the board and the game, with what ./setup saved
    ./play --mode practice       # any other argument goes on to main.py

./setup (launch.py --setup) opens a small window that asks four things — which
screen the game goes on, which output its sound goes to, which screen the
scoreboard goes on, and what aims (the gun's port, or the mouse). What was
picked last time is already selected. Enter saves the picks, then:

  - the gun's debug view (tools/ir_view.py): the four beacons as the camera
    sees them and where the gun says it points. Enter goes on, Esc goes back
    to the picker;
  - the calibration (main.py --calibrate) on the game's screen, and after it
    the game — off the record, the board is not involved.

Quitting the game brings the picker back; Esc ends the setup. With the mouse
picked there is no gun to look at or sight in, so it goes straight to the game.

./play asks nothing: it takes the picks ./setup saved and starts

  - the scoreboard server, unless one already answers at [leaderboard] url
    (it may be on a Pi; then it is only shown, not started);
  - the board in a browser of its own, fullscreen on its screen — a Chromium
    (Chrome, Edge, Brave) in kiosk mode with a profile of its own, so it
    neither touches your own browser windows nor asks anything on start;
  - the game, fullscreen on its screen, which stays up when you click away.

Quitting the game (Q) ends the evening, board and server with it. The picks are
kept in launch.json (not in git: they describe one room's cables, like
calibration.json describes one gun).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from duckhunt import outputs                                  # noqa: E402
from duckhunt.core.config import load                         # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
BOARD_PROFILE = os.path.join(ROOT, ".board-browser")
BROWSERS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]

NO_BOARD = "don't open the board"
DEFAULT_AUDIO = "system default"
MOUSE = "mouse"


@dataclass
class Row:
    """One question in the picker: what it is, the answers, the one picked."""
    title: str
    options: list = field(default_factory=list)   # [(label, value)]
    at: int = 0

    @property
    def value(self):
        return self.options[self.at][1]

    def select(self, value, by=lambda v: v) -> None:
        for i, (_, v) in enumerate(self.options):
            if v is not None and value is not None and by(v) == by(value):
                self.at = i
                return

    def step(self, d: int) -> None:
        self.at = (self.at + d) % len(self.options)


def main() -> int:
    extra = sys.argv[1:]
    if shutil.which("caffeinate"):      # no display sleep while the evening runs
        subprocess.Popen(["caffeinate", "-di", "-w", str(os.getpid())])
    if extra[:1] == ["--setup"]:
        return setup(extra[1:])
    return evening(extra)


def setup(extra: list[str]) -> int:
    """./setup: the picker, then the gun's view, then the calibration — round
    and round until Esc in the picker."""
    board_on = load().leaderboard.enabled
    status = ""
    while True:
        chosen = choose(outputs.load_picks(), board_on, status)
        if chosen is None:
            return 0
        picks, game_screen, _ = chosen
        outputs.save_picks(picks)
        if picks["gun"] != MOUSE and not gun_view(picks["gun"]):
            status = "the gun's view was closed — Enter opens it again"
            continue
        calibrate = [] if picks["gun"] == MOUSE else ["--calibrate"]
        code = play(picks, game_screen, calibrate + ["--no-leaderboard"] + extra)
        status = ("saved — ./play starts the evening, Esc closes this"
                  if code == 0 else
                  f"the game stopped with an error ({code}) — see the terminal")


def evening(extra: list[str]) -> int:
    """./play: the board and the game with what ./setup saved, no questions."""
    picks = outputs.load_picks()
    if not picks:
        print("nothing set up yet — run ./setup first", flush=True)
        return 1
    picks, game_screen, board_screen = resolve(picks)
    lb = load().leaderboard
    board = Board(lb.url) if lb.enabled else None
    try:
        if board is not None:
            board.show(board_screen)
        return play(picks, game_screen, extra)
    finally:
        if board is not None:
            board.close()


def resolve(saved: dict):
    """The saved picks as they stand today, without asking: (picks, the game's
    screen, the board's screen or None). What has gone missing since ./setup
    falls back — and says so — rather than stopping the evening."""
    import pygame
    pygame.display.init()
    try:
        screens = outputs.screens(pygame)
    finally:
        pygame.quit()
    game = outputs.find_screen(saved.get("game_screen"), screens)
    if game is None:
        game = screens[-1]
        print(f"the game's screen from ./setup is not connected — "
              f"playing on {game.label}", flush=True)
    board = outputs.find_screen(saved.get("board_screen"), screens)
    if board is None and saved.get("board_screen"):
        print("the board's screen from ./setup is not connected — "
              "no board tonight", flush=True)
    picks = {"audio": "", "gun": MOUSE, **saved}
    if picks["gun"] != MOUSE and picks["gun"] not in outputs.gun_ports():
        print(f"no gun on {picks['gun']} — aiming with the mouse "
              f"(plug it in, or run ./setup)", flush=True)
        picks["gun"] = MOUSE
    return picks, game, board


def gun_view(port: str) -> bool:
    """tools/ir_view.py on the gun's port: True when it was left with Enter."""
    cmd = [sys.executable, os.path.join(ROOT, "tools", "ir_view.py"), port,
           "--next"]
    print("\n$ " + " ".join(cmd[1:]), flush=True)
    try:
        return subprocess.call(cmd, cwd=ROOT) == 0
    except KeyboardInterrupt:
        return False


# ---------------------------------------------------------------------------
# the picker

def choose(saved: dict, board_on: bool, status: str):
    """Show the picker. (the picks as launch.json keeps them, the game's
    screen, the board's screen or None) — or None for Esc."""
    import pygame
    pygame.display.init()
    pygame.font.init()
    screens = outputs.screens(pygame)
    audio = _audio_outputs(pygame)
    ports = outputs.gun_ports()

    rows = [Row("Game screen"), Row("Game sound"), Row("Board screen"),
            Row("Aim with")]
    game, sound, board_row, gun = rows
    game.options = [(s.label, s) for s in screens]
    found = outputs.find_screen(saved.get("game_screen"), screens)
    game.at = screens.index(found) if found else len(screens) - 1

    sound.options = [(DEFAULT_AUDIO, "")] + [(a, a) for a in audio]
    sound.select(saved.get("audio"))

    if not board_on:
        board_row.options = [("off in settings.toml ([leaderboard])", None)]
    else:
        board_row.options = [(s.label, s) for s in screens] + [(NO_BOARD, None)]
        found = outputs.find_screen(saved.get("board_screen"), screens)
        if found:
            board_row.at = screens.index(found)
        elif saved.get("board_screen") is None and "board_screen" in saved:
            board_row.at = len(screens)
        else:                     # a fresh start: not the game's own screen
            board_row.at = 0 if game.at != 0 else min(1, len(screens) - 1)

    gun.options = [(p, p) for p in ports] + [("mouse", MOUSE)]
    gun.select(saved.get("gun"))

    try:
        if not _picker(pygame, rows, status):
            return None
    finally:
        pygame.quit()
    picks = {"game_screen": outputs.remember(game.value),
             "audio": sound.value,
             "board_screen": outputs.remember(board_row.value),
             "gun": gun.value}
    return picks, game.value, board_row.value


def _audio_outputs(pygame) -> list[str]:
    from duckhunt.sound import output_names
    try:
        pygame.mixer.init()          # SDL lists the outputs only with audio up
        names = output_names(pygame)
        pygame.mixer.quit()
        return names
    except Exception:                                   # noqa: BLE001
        return []


BG, FG, DIM, HI, WARN = (12, 14, 24), (230, 230, 230), (120, 125, 140), \
                        (255, 196, 0), (255, 110, 90)


def _picker(pygame, rows: list[Row], status: str) -> bool:
    """The window: ↑↓ a question, ←→ the answer, Enter goes on, Esc quits.
    A click on the left or right half of an answer steps it back or on."""
    W, H = 900, 470
    win = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Duck Hunt — tonight's setup")
    font = pygame.font.SysFont("Menlo,monospace", 20, bold=True)
    small = pygame.font.SysFont("Menlo,monospace", 15)
    big = pygame.font.SysFont("Menlo,monospace", 34, bold=True)
    sel = 0
    clock = pygame.time.Clock()
    row_y = lambda i: 110 + i * 62                      # noqa: E731
    start_rect = pygame.Rect(W // 2 - 110, row_y(len(rows)) + 6, 220, 46)

    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return False
            if e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_ESCAPE, pygame.K_q):
                    return False
                if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    return True
                if e.key in (pygame.K_UP, pygame.K_w):
                    sel = (sel - 1) % len(rows)
                elif e.key in (pygame.K_DOWN, pygame.K_s, pygame.K_TAB):
                    sel = (sel + 1) % len(rows)
                elif e.key in (pygame.K_LEFT, pygame.K_a):
                    rows[sel].step(-1)
                elif e.key in (pygame.K_RIGHT, pygame.K_d):
                    rows[sel].step(+1)
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if start_rect.collidepoint(e.pos):
                    return True
                for i in range(len(rows)):
                    if row_y(i) - 8 <= e.pos[1] < row_y(i) + 46:
                        sel = i
                        if e.pos[0] >= 260:
                            rows[i].step(-1 if e.pos[0] < 260 + (W - 300) // 2
                                         else +1)

        win.fill(BG)
        win.blit(big.render("DUCK HUNT", True, HI), (40, 28))
        win.blit(small.render("tonight's setup — saved for ./play",
                              True, DIM), (42, 72))
        for i, r in enumerate(rows):
            y = row_y(i)
            on = i == sel
            if on:
                pygame.draw.rect(win, (32, 36, 56), (24, y - 8, W - 48, 50),
                                 border_radius=8)
            win.blit(font.render(r.title, True, HI if on else FG), (40, y + 4))
            n = len(r.options)
            arrows = ("◀ ", " ▶") if n > 1 else ("  ", "  ")
            label = _clip(r.options[r.at][0], 50)
            text = font.render(f"{arrows[0]}{label}{arrows[1]}", True,
                               FG if on else DIM)
            win.blit(text, (260, y + 4))
            if n > 1:
                win.blit(small.render(f"{r.at + 1}/{n}", True, DIM),
                         (W - 70, y + 8))
        warn = _warning(rows)
        pygame.draw.rect(win, HI, start_rect, border_radius=8)
        t = font.render("START  ⏎", True, BG)
        win.blit(t, t.get_rect(center=start_rect.center))
        line = warn or status or "↑↓ question   ←→ answer   Enter gun check   Esc quit"
        t = small.render(line, True, WARN if warn else DIM)
        win.blit(t, t.get_rect(center=(W // 2, H - 22)))
        pygame.display.flip()
        clock.tick(30)


def _warning(rows: list[Row]) -> str:
    game, _, board, gun = rows
    if board.value is not None and game.value is not None \
            and board.value.index == game.value.index:
        return "the board and the game are on the same screen"
    if gun.value == MOUSE and outputs.gun_ports():
        return "the gun's port is there, but the mouse is picked to aim"
    return ""


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


# ---------------------------------------------------------------------------
# the game

def play(picks: dict, screen, extra: list[str]) -> int:
    """Run main.py with the picks, until it quits; its exit code."""
    cmd = [sys.executable, os.path.join(ROOT, "main.py"),
           f"--display={screen.index}", f"--audio={picks['audio']}"]
    if picks["gun"] != MOUSE:
        cmd.append(f"--serial={picks['gun']}")
    cmd += extra
    print("\n$ " + " ".join(cmd[1:]), flush=True)
    try:
        return subprocess.call(cmd, cwd=ROOT)
    except KeyboardInterrupt:
        return 130


# ---------------------------------------------------------------------------
# the board

class Board:
    """The scoreboard server (if it is ours to run) and its kiosk browser."""

    def __init__(self, url: str):
        from leaderboard.__main__ import _already_serving, default_ducks
        self.base = url.rstrip("/")
        parts = urllib.parse.urlsplit(self.base)
        self.port = parts.port or 80
        self.server = None
        self.browser = None
        self.shown_on = "unset"
        self.page = f"{self.base}/?ducks={default_ducks()}"
        local = parts.hostname in ("localhost", "127.0.0.1", "::1")
        if local and not _already_serving(self.port):
            self.server = subprocess.Popen(
                [sys.executable, "-m", "leaderboard.server",
                 "--port", str(self.port), "--log",
                 os.path.join(ROOT, "leaderboard.log")],
                cwd=ROOT, stdout=subprocess.DEVNULL)
            for _ in range(30):
                if _already_serving(self.port):
                    break
                time.sleep(0.1)
            print(f"scoreboard server on :{self.port} "
                  f"(runs logged to leaderboard.log)", flush=True)
        elif local:
            print(f"a scoreboard already answers on :{self.port} — using it",
                  flush=True)

    def show(self, screen) -> None:
        """The board fullscreen on `screen` (an outputs.Screen), or nowhere
        for None. Already there: left alone, so it does not blink between
        rounds."""
        key = None if screen is None else (screen.x, screen.y, screen.w, screen.h)
        if key == self.shown_on and self._browser_alive():
            return
        self._close_browser()
        self.shown_on = key
        if screen is None:
            return
        exe = next((b for b in BROWSERS if os.path.exists(b)), None)
        if exe is None:
            print("no Chrome/Edge/Brave to put the board fullscreen with — "
                  "opened in the default browser: drag it to the screen and "
                  "press F", flush=True)
            webbrowser.open(self.page)
            return
        self.browser = subprocess.Popen(
            [exe, f"--user-data-dir={BOARD_PROFILE}",
             "--no-first-run", "--no-default-browser-check",
             "--disable-features=Translate",
             f"--window-position={screen.x},{screen.y}",
             f"--window-size={screen.w},{screen.h}",
             "--kiosk", f"--app={self.page}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"the board: {self.page} on {screen.name}", flush=True)

    def _browser_alive(self) -> bool:
        return self.browser is None or self.browser.poll() is None

    def _close_browser(self) -> None:
        if self.browser is not None and self.browser.poll() is None:
            self.browser.terminate()
            try:
                self.browser.wait(5)
            except subprocess.TimeoutExpired:
                self.browser.kill()
        self.browser = None

    def close(self) -> None:
        self._close_browser()
        if self.server is not None:
            self.server.terminate()
            self.server.wait(5)
            print("scoreboard server stopped", flush=True)


if __name__ == "__main__":
    sys.exit(main())
