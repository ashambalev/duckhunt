"""Turn the original Duck Hunt (NES, 1984) sound effects into the game's three files.

    python3 tools/import_nes_sounds.py            # assets/source/nes_sounds/ -> assets/sounds/

The counterpart of `slice_spritesheet.py`, for sound: that script cuts the sprites
out of the NES sheet, this one cuts the sounds out of the NES rip. Three of the
fifteen effects are the ones the game plays —

    zapper_gun.wav  -> shot.wav        the Zapper going off
    duck_quack.wav  -> quack.wav       the duck, when it takes the shot
    dog_miss.wav    -> dog_laugh.wav   the dog laughing at the one that got away

— and what happens to them on the way is only housekeeping: trimmed (the rip
leaves the Zapper ringing for 1.6 s, which would still be going when you fire
again), resampled 44.1 -> 22.05 kHz to match the mixer so nothing is converted at
load time, normalised so one `[sound] volume` governs all three, and faded at both
ends so no clip starts or stops with a click.

`tools/make_sounds.py` is the other path to the same three files: it synthesizes
them from nothing, which is what to run if you would rather not have a rip of
someone's cartridge in the folder. The game plays whatever is in `assets/sounds/`
and does not care which script wrote it.

Where the source came from: the Duck Hunt sound rip on The Sounds Resource
(https://www.sounds-resource.com/nes/duckhunt/). The effects are Nintendo's, like
the sprite sheet in `assets/source/` — fine for a light gun standing in someone's
living room, not something to ship.
"""

from __future__ import annotations

import math
import os
import struct
import sys
import wave
import zipfile

RATE = 22050      # the mixer's rate (duckhunt/sound.py); the rip is 44100, exactly 2x
PEAK = 0.89       # the same normalisation make_sounds.py uses, so the two are swappable

# source file -> (the game's file, seconds to keep, the fade-out on that cut, and
# the lowpass to soften it with — 0 leaves the sound exactly as ripped)
WANTED = {
    # The Zapper rings on for 1.6 s in the rip, and its body is flat for the first
    # 220 ms before rolling off. Cutting at 300 ms takes the whole percussive part
    # and lets the fade finish the roll-off — a shot you can fire again on top of,
    # where half a second still had its own tail playing under the next pull.
    # 2.8 kHz: the Zapper is white noise, and everything above that is fizz
    # rather than gun. Below ~2 kHz it stops sounding like a shot at all and
    # starts sounding like a door.
    "zapper_gun.wav": ("shot.wav", 0.30, 0.07, 2800.0),
    # The quack's own body ends at ~130 ms and the rip pads the rest. 115 ms with
    # a fade over the last quarter of it lands the sound inside the frame the duck
    # folds up in, instead of trailing after it.
    "duck_quack.wav": ("quack.wav", 0.115, 0.025, 0),
    # 1.4 s of laughing, which is exactly how long the dog stays up out of the
    # grass ([dog] pop in settings.toml) — the sound and the sprite end together.
    "dog_miss.wav": ("dog_laugh.wav", None, 0.02, 0),
}


def read_wav(path_or_bytes) -> tuple[list[float], int]:
    """A PCM wav -> samples in -1..1, mono (a stereo one is mixed down)."""
    with wave.open(path_or_bytes, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{w.getsampwidth() * 8}-bit wav — expected 16")
        n, ch = w.getnframes(), w.getnchannels()
        raw = struct.unpack(f"<{n * ch}h", w.readframes(n))
        rate = w.getframerate()
    if ch == 1:
        return [x / 32768 for x in raw], rate
    return [sum(raw[i:i + ch]) / (32768 * ch) for i in range(0, len(raw), ch)], rate


def resample_half(xs: list[float]) -> list[float]:
    """44.1 -> 22.05 kHz. The rate is exactly halved, so averaging each pair and
    keeping one of them is both the anti-alias filter and the decimation — the
    cheap trick that is actually correct here, rather than an approximation."""
    return [(xs[i] + xs[i + 1]) / 2 for i in range(0, len(xs) - 1, 2)]


def soften(xs: list[float], cutoff: float, poles: int = 2) -> list[float]:
    """Take the top off. The NES Zapper is the console's NOISE channel — white
    noise with an envelope on it — so what it is made of is hiss, and past a few
    kHz that hiss carries no information about the shot, only the fizz. Two
    one-pole lowpasses in series (-12 dB/octave) leave the crack and the body and
    quietly drop the rest; one pole is too gentle to hear, four makes it muffled.
    """
    a = 1.0 - math.exp(-2.0 * math.pi * cutoff / RATE)
    for _ in range(poles):
        y = 0.0
        out = []
        for x in xs:
            y += a * (x - y)
            out.append(y)
        xs = out
    return xs


def polish(xs: list[float], fade_in: float = 0.002, fade_out: float = 0.02) -> list[float]:
    top = max((abs(x) for x in xs), default=0.0) or 1.0
    xs = [x * PEAK / top for x in xs]
    for fade, at_end in ((fade_in, False), (fade_out, True)):
        k = min(int(fade * RATE), len(xs))
        for i in range(k):
            xs[-1 - i if at_end else i] *= i / k
    return xs


def write_wav(path: str, xs: list[float]) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, x)) * 32767))
                               for x in xs))


def sources(path: str):
    """The three files we want, out of a folder or straight out of the rip's zip."""
    if os.path.isdir(path):
        for name in WANTED:
            full = os.path.join(path, name)
            if os.path.exists(full):
                yield name, full
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for name in WANTED:
                match = next((m for m in z.namelist()
                              if os.path.basename(m) == name), None)
                if match:
                    with z.open(match) as f:
                        yield name, io_bytes(f.read())
    else:
        raise SystemExit(f"{path}: not a folder and not a zip")


def io_bytes(data: bytes):
    import io
    return io.BytesIO(data)


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "assets",
                                                             "source", "nes_sounds")
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "..", "assets",
                                                                 "sounds")
    os.makedirs(out_dir, exist_ok=True)
    print(f"{os.path.normpath(src)} -> {os.path.normpath(out_dir)}")
    found = 0
    for name, handle in sources(src):
        target, keep, fade_out, cutoff = WANTED[name]
        xs, rate = read_wav(handle)
        was = len(xs) / rate
        if rate == 2 * RATE:
            xs = resample_half(xs)
        elif rate != RATE:
            raise SystemExit(f"{name}: {rate} Hz — expected 44100 or {RATE}")
        if keep:
            xs = xs[:int(keep * RATE)]
        if cutoff:
            xs = soften(xs, cutoff)
        write_wav(os.path.join(out_dir, target), polish(xs, fade_out=fade_out))
        print(f"  {name:<16} -> {target:<14} {was * 1000:5.0f} ms -> "
              f"{len(xs) / RATE * 1000:5.0f} ms")
        found += 1
    if found < len(WANTED):
        print(f"  only {found} of {len(WANTED)} found — the rest keep whatever is "
              f"in {os.path.basename(out_dir)} already")


if __name__ == "__main__":
    main()
