"""Make the game's three sounds: the shot, the duck's quack, the dog's laugh.

    python3 tools/make_sounds.py          # -> assets/sounds/*.wav

They are SYNTHESIZED here rather than sampled from anywhere — same spirit as the
pixel art being cut from a sheet we can point at: nothing to license, nothing to
download, and no new dependency (the standard library's `wave` and `math` are the
whole toolbox, so this runs without pygame, numpy or pillow).

Each sound is a recipe a few lines long, and the recipes are the same three
tricks:

  * NOISE through a filter — a gunshot is a burst of noise whose bright crack
    turns into a low boom as the filter closes.
  * A PULSE TRAIN through resonators — the classic way to fake a voice: the
    pulses are the vocal cords (their rate is the pitch), the resonators are the
    throat and mouth (their frequencies are the vowel). A duck's quack and a
    dog's cackle are both this, with different pitch curves.
  * An ENVELOPE — how loud it is over time. This is what makes a sound read as a
    snap, a squawk or a chuckle more than anything else in it.

So the knobs worth turning are at the top of each make_* function below: the
pitch it starts and ends on, the formants, and the decay times. Re-run the script
after changing them; the game just loads the files.
"""

from __future__ import annotations

import math
import os
import random
import struct
import sys
import wave

RATE = 22050      # the game's mixer rate too (duckhunt/sound.py) — no resampling
PEAK = 0.89       # every file is normalised to this, so one [sound] volume rules all


# ---- the toolbox ------------------------------------------------------------
def noise(n: int, rng: random.Random) -> list[float]:
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]


def lowpass(xs: list[float], cutoff) -> list[float]:
    """One-pole lowpass. `cutoff` in Hz — a number, or a function of the sample
    index, which is how the shot's crack closes down into a boom."""
    out, y = [], 0.0
    get = cutoff if callable(cutoff) else (lambda i: cutoff)
    for i, x in enumerate(xs):
        a = 1.0 - math.exp(-2.0 * math.pi * max(20.0, get(i)) / RATE)
        y += a * (x - y)
        out.append(y)
    return out


def resonate(xs: list[float], freq, bw) -> list[float]:
    """Two-pole resonator: rings at `freq`, `bw` Hz wide. A formant.

    Both may be functions of the sample index, and that is not a detail — a
    formant that MOVES is the difference between a vowel and a buzz. "Quack" is
    not one vowel held for a fifth of a second, it is a glide from a closed one
    into an open one; the coefficients are therefore recomputed per sample, which
    at a few thousand samples costs nothing worth saving.
    """
    get_f = freq if callable(freq) else (lambda i: freq)
    get_bw = bw if callable(bw) else (lambda i: bw)
    out, y1, y2 = [], 0.0, 0.0
    for i, x in enumerate(xs):
        r = math.exp(-math.pi * max(10.0, get_bw(i)) / RATE)
        theta = 2.0 * math.pi * min(max(20.0, get_f(i)), RATE * 0.45) / RATE
        b1, b2 = 2.0 * r * math.cos(theta), -r * r
        a0 = (1.0 - r * r) * math.sin(theta)
        y = a0 * x + b1 * y1 + b2 * y2
        y2, y1 = y1, y
        out.append(y)
    return out


def rasp(xs: list[float], drive: float) -> list[float]:
    """Soft clipping. A duck is a HARSH sound — its energy reaches well past the
    formants — and clipping is what puts those upper harmonics there. Gentle
    enough not to turn into fuzz: tanh rounds the peaks rather than shearing them.
    """
    return [math.tanh(drive * x) for x in xs]


def glide(n: int, start: float, end: float, over: float = 1.0, rate: float = RATE):
    """A value sliding from `start` to `end` over the first `over` of the sound,
    then held. Returned as a function of the sample index, for the two above."""
    span = max(1.0, n * over)
    return lambda i: start + (end - start) * min(1.0, i / span)


def pulses(n: int, pitch, jitter: float = 0.0,
           rng: random.Random | None = None) -> list[float]:
    """A pulse train at `pitch` Hz (a number or a function of the sample index) —
    one impulse per cycle. `jitter` roughens the period, which is what makes a
    quack rasp instead of buzzing like a synthesizer."""
    get = pitch if callable(pitch) else (lambda i: pitch)
    out = [0.0] * n
    phase = 0.0
    for i in range(n):
        f = max(20.0, get(i))
        if jitter and rng is not None:
            f *= 1.0 + rng.uniform(-jitter, jitter)
        phase += f / RATE
        if phase >= 1.0:
            phase -= 1.0
            out[i] = 1.0
    return out


def mix(*parts: tuple[float, list[float]]) -> list[float]:
    """Sum signals of any lengths, each with its own gain."""
    n = max((len(xs) for _, xs in parts), default=0)
    out = [0.0] * n
    for gain, xs in parts:
        for i, x in enumerate(xs):
            out[i] += gain * x
    return out


def attack_decay(n: int, attack: float, decay: float, hold: float = 0.0) -> list[float]:
    """Rise over `attack` s, hold, then die away with time constant `decay`."""
    env = []
    for i in range(n):
        t = i / RATE
        if t < attack:
            env.append(t / attack if attack else 1.0)
        else:
            env.append(math.exp(-(t - attack - min(t - attack, hold)) / decay))
    return env


def apply_env(xs: list[float], env: list[float]) -> list[float]:
    return [x * e for x, e in zip(xs, env)]


def polish(xs: list[float], fade: float = 0.004) -> list[float]:
    """Normalise to PEAK and fade both ends, so nothing starts or stops with a click."""
    top = max((abs(x) for x in xs), default=0.0) or 1.0
    xs = [x * PEAK / top for x in xs]
    k = max(1, int(fade * RATE))
    for i in range(min(k, len(xs))):
        xs[i] *= i / k
        xs[-1 - i] *= i / k
    return xs


def write_wav(path: str, xs: list[float]) -> None:
    frames = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, x)) * 32767))
                      for x in xs)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    print(f"  {os.path.basename(path):<14} {len(xs) / RATE * 1000:4.0f} ms  "
          f"{len(frames) + 44:6d} bytes")


# ---- the three sounds ------------------------------------------------------
def make_shot(rng: random.Random) -> list[float]:
    """A gun going off: a bright crack that closes into a low boom.

    One burst of noise used twice — once through a filter that shuts from 8 kHz
    down to 400 Hz in 25 ms (that sweep IS the crack), once through a resonator
    low enough to be felt rather than heard (the boom, and the reason it does not
    sound like a hiss). The boom outlives the crack by three times, which is the
    shape of a real muzzle blast and of the NES's own noise channel alike.
    """
    dur, n = 0.26, int(0.26 * RATE)
    src = noise(n, rng)
    crack = lowpass(src, lambda i: 8000.0 * math.exp(-(i / RATE) / 0.025) + 400.0)
    boom = resonate(src, 150.0, 130.0)
    # the click of the hammer: a handful of samples at full tilt, so the attack
    # has an edge to it at any playback volume
    click = [src[i] * math.exp(-(i / RATE) / 0.0015) for i in range(n)]
    return polish(mix(
        (1.0, apply_env(crack, attack_decay(n, 0.0008, 0.045))),
        (1.3, apply_env(boom, attack_decay(n, 0.002, 0.10))),
        (0.35, click),
    ), fade=0.0008)       # barely any fade: a shot is a click, do not round it off


def make_quack(rng: random.Random) -> list[float]:
    """A duck's quack — the sound of being hit. "Кря", not a buzz.

    Three things make it a quack rather than a held note, and the first version of
    this function had none of them:

      * THE GLIDE. A quack is one syllable that OPENS: it starts closed and nasal
        and finishes wide open, which in formant terms is F2 falling from 2 kHz to
        1.2 kHz while F1 climbs from 650 to 900. Hold the formants still and you
        get a kazoo, which is exactly what it sounded like.
      * THE PITCH FALL. Flat for the first quarter, then down from 420 Hz to 230 —
        a bird running out of breath, not a tone generator.
      * THE RASP. Soft clipping after the formants, because a real quack has
        energy far above them; without it the sound is too polite to cut through
        a gunshot that is playing at the same time.

    The 6 ms of filtered noise in front is the "k" the syllable starts on — it is
    what makes the sound land on one frame instead of fading in.
    """
    dur, n = 0.20, int(0.20 * RATE)
    # flat for the first quarter, then down: 420 -> 230 Hz
    def f0(i, n=n):
        t = i / n
        return 420.0 if t < 0.25 else 420.0 - 190.0 * (t - 0.25) / 0.75
    src = pulses(n, f0, jitter=0.05, rng=rng)
    breath = lowpass(noise(n, rng), 3500.0)
    voice = mix((1.0, src), (0.18, breath))
    # the vowel opening up over the first 60 % of the sound: F2 down, F1 up
    body = mix(
        (1.0, resonate(voice, glide(n, 650.0, 900.0, 0.6), 120.0)),
        (0.8, resonate(voice, glide(n, 2000.0, 1150.0, 0.6), 200.0)),
        (0.3, resonate(voice, 2800.0, 600.0)),
    )
    body = rasp(body, 2.2)
    click = apply_env(resonate(noise(n, rng), 1600.0, 1400.0),
                      attack_decay(n, 0.0005, 0.006))
    # short: the quack lands on the frame the duck folds up in, and anything
    # longer is still going while it falls
    env = attack_decay(n, 0.004, 0.055, hold=0.035)
    return polish(mix((1.0, apply_env(body, env)), (0.45, click)), fade=0.002)


def make_laugh(rng: random.Random) -> list[float]:
    """The dog at the one that got away — a GIGGLE. "Хи-хи-хи-хи-хи".

    Five quick chuckles instead of four slow ones, and the vowel is /i/ rather
    than /e/: F1 down at 320 Hz with F2 up at 2250 is what makes a voice sound
    high, thin and amused. (The first version put them at 650/1150, which is an
    open "heh" — a big dog barking a laugh rather than a small one sniggering at
    you, and it came out heavier than the joke.)

    Each chuckle is two sounds glued together: 14 ms of breathy noise — the "kh",
    aspiration is most of what a giggle IS — and then 50 ms of voice. The pitch
    lifts inside each one and drops from one to the next, so the whole thing
    falls away while every chuckle still turns up at its own end. They get
    quieter and a touch faster as they go, the way someone trying to stop
    laughing does.
    """
    pitches = [430.0, 412.0, 388.0, 362.0, 336.0]
    breath_t, gap = 0.014, 0.040
    out: list[float] = []
    for k, f in enumerate(pitches):
        last = k == len(pitches) - 1
        # the "kh": noise, wide band, gone almost at once
        nb = int(breath_t * RATE)
        huff = apply_env(resonate(noise(nb, rng), 2600.0, 1600.0),
                         attack_decay(nb, 0.001, 0.008))
        # the "i": pulses through a high, thin vowel, pitch lifting at the end
        nv = int((0.050 + (0.03 if last else 0.0)) * RATE)
        f0 = lambda i, f=f, nv=nv: f * (1.0 + 0.07 * (i / nv) ** 2)
        voice = mix((1.0, pulses(nv, f0, jitter=0.03, rng=rng)),
                    (0.22, lowpass(noise(nv, rng), 3000.0)))
        body = mix(
            (1.0, resonate(voice, 320.0, 90.0)),
            (0.9, resonate(voice, 2250.0, 200.0)),
            (0.35, resonate(voice, 3100.0, 500.0)),
        )
        env = attack_decay(nv, 0.005, 0.045 if last else 0.022)
        chuckle = mix((0.55, huff), (1.0, [0.0] * nb + apply_env(body, env)))
        # each one quieter than the last — a laugh runs out of air
        out += [x * (1.0 - 0.13 * k) for x in chuckle]
        if not last:
            out += [0.0] * int(gap * (1.0 - 0.08 * k) * RATE)
    return polish(out)


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..",
                                                                "assets", "sounds")
    os.makedirs(out_dir, exist_ok=True)
    # a fixed seed: the noise in the shot is random, but the file should not
    # change every time the script is run
    rng = random.Random(1984)
    print(f"{RATE} Hz mono 16-bit -> {os.path.normpath(out_dir)}")
    write_wav(os.path.join(out_dir, "shot.wav"), make_shot(rng))
    write_wav(os.path.join(out_dir, "quack.wav"), make_quack(rng))
    write_wav(os.path.join(out_dir, "dog_laugh.wav"), make_laugh(rng))


if __name__ == "__main__":
    main()
