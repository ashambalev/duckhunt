"""The game's sounds: the shot, the duck's quack, the dog's laugh.

Three WAV files in `assets/sounds/`, made by `tools/make_sounds.py` (they are
synthesized, not sampled — the recipes are in that script). This module is the
thin layer between them and the game: load them into pygame's mixer, keep the
volumes from `[sound]` in settings.toml, and play one by name.

It is deliberately unable to break a round. No audio device, a mixer that will
not start, a missing file, an unplugged USB headset — each of those prints one
line and leaves a Sounds object that plays nothing. The gun and the ducks do not
care, and a silent game is still a game.

Latency is the reason for the numbers below. A light gun round is the one place
where sound being a frame late is noticeable: you hear your own trigger. So the
mixer is asked for a 256-frame buffer (~12 ms at 22 kHz) instead of SDL's default
half-a-dozen times that, and the files are written at the mixer's own rate so
nothing has to be resampled on the way in.
"""

from __future__ import annotations

import os

RATE = 22050        # the rate tools/make_sounds.py writes, so no resampling
BUFFER = 256        # ~12 ms of latency; you hear your own trigger pull
CHANNELS = 16       # room for overlapping shots, a quack and a laugh at once

# the name the game uses -> the file it lives in
FILES = {
    "shot": "shot.wav",
    "quack": "quack.wav",
    "laugh": "dog_laugh.wav",
}


def sounds_dir(assets_dir: str | None = None) -> str:
    """`assets/sounds` — next to the sprites, by the same route they are found."""
    if assets_dir is None:
        here = os.path.dirname(os.path.abspath(__file__))
        assets_dir = os.path.join(here, "..", "assets")
    return os.path.join(assets_dir, "sounds")


class Sounds:
    """The loaded clips, and `play(name)`.

    `pre_init` has to be called BEFORE pygame.init(), because the mixer takes its
    buffer size when the subsystem comes up and ignores it afterwards — asking
    later gives you SDL's default latency and a trigger you hear late.
    """

    @staticmethod
    def pre_init(pygame) -> None:
        try:
            pygame.mixer.pre_init(RATE, -16, 1, BUFFER)
        except Exception as exc:                  # no mixer in this build at all
            print(f"sound: mixer unavailable ({exc}) — playing silently")

    def __init__(self, pygame, settings=None, assets_dir: str | None = None):
        self.clips: dict = {}
        self.master = 0.0
        self.gains: dict[str, float] = {}
        self.shot_on_hit = True
        if settings is not None and (not settings.enabled or settings.volume <= 0):
            # [sound] enabled = false (or the volume turned all the way down):
            # nothing is loaded, and the audio device is handed back — pygame.init()
            # brings the mixer up by itself, and a silent game has no business
            # holding a device another program might want.
            try:
                pygame.mixer.quit()
            except Exception:
                pass
            return
        self.master = 1.0 if settings is None else settings.volume
        self.gains = {
            "shot": 0.9 if settings is None else settings.shot,
            "quack": 1.0 if settings is None else settings.quack,
            "laugh": 1.0 if settings is None else settings.laugh,
        }
        self.shot_on_hit = True if settings is None else settings.shot_on_hit

        try:
            pygame.mixer.init(RATE, -16, 1, BUFFER)
            pygame.mixer.set_num_channels(CHANNELS)
        except Exception as exc:
            # no audio device (over ssh, or a Mac with everything muted at the
            # driver level) — not a reason to refuse to play the game
            print(f"sound: no audio device ({exc}) — playing silently")
            return

        folder = sounds_dir(assets_dir)
        missing = []
        for name, filename in FILES.items():
            path = os.path.join(folder, filename)
            try:
                clip = pygame.mixer.Sound(path)
            except Exception:
                missing.append(filename)
                continue
            clip.set_volume(max(0.0, min(1.0, self.master * self.gains[name])))
            self.clips[name] = clip
        if missing:
            print(f"sound: {', '.join(missing)} missing from "
                  f"{os.path.normpath(folder)} — run tools/make_sounds.py")

    # ---- what the game calls ----
    def play(self, name: str) -> None:
        clip = self.clips.get(name)
        if clip is not None:
            clip.play()

    def shot(self) -> None:
        """The gun going off. Played on every shot unless [sound] shot_on_hit is
        off, in which case a hit gets only the quack."""
        self.play("shot")

    def quack(self) -> None:
        """A duck taking the shot."""
        self.play("quack")

    def laugh(self) -> None:
        """The dog, when one gets away."""
        self.play("laugh")

    def fired(self, hit: bool) -> None:
        """One trigger pull, and whether it downed a duck — the only call the
        game's loop needs to make: it keeps the shot_on_hit rule in one place."""
        if hit:
            self.quack()
            if self.shot_on_hit:
                self.shot()
        else:
            self.shot()
