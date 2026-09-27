"""Game core: the world state and how it is updated. No rendering, no terminal.

Every frame the frontend calls `world.update(dt, aim_x, aim_y, fire)` and then
reads `world.ducks`, `world.score` and so on to draw the scene however it likes
(ASCII, sprites, 3D — makes no difference). The core is deterministic for a given
seed, which is handy for tests.

Firing costs something now, which is what the score is about: a duck is worth
`[score] duck`, a shot that hits nothing `[score] miss`, and the dog `[score]
dog`. The magazine (`[round] ammo`) is the other half of it — with free shots the
best strategy was to hold the trigger down. The dog is the one thing the core
cannot see for itself: he is drawn by the frontend, so the frontend hands his box
to `update()` while he is up, and the shot is then decided where every other shot
is decided.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from .config import Settings, load
from .models import Duck, DuckState, Facing

# A round is finite: we release `settings.round.ducks` ducks and that is it —
# the result goes into the high-score table. Duck size, speed and spawn rate live
# in settings.toml, see duckhunt/core/config.py.


def _inside(box: tuple[float, float, float, float], x: float, y: float) -> bool:
    """Is the aim point inside `(x0, y0, x1, y1)`? Edges count as inside."""
    x0, y0, x1, y1 = box
    return x0 <= x <= x1 and y0 <= y <= y1


class World:
    def __init__(self, seed: int | None = None, settings: Settings | None = None):
        self.settings = settings if settings is not None else load()
        self.rng = random.Random(seed)
        self.ducks: list[Duck] = []
        self.score = 0
        self.shots = 0
        self.hits = 0
        self.dog_hits = 0        # shots that hit the dog. He is on your side.
        # Whether the crosshair was drawn at any point in this round. A scored
        # round is shot down the sights; one that had the crosshair up is still a
        # round, and still scored on screen, it is simply never a record. Latched
        # rather than sampled at the end, so flipping it off before the last duck
        # does not launder the round.
        self.crosshair_used = False
        self.spawn_timer = 0.0
        self.spawn_interval = self.settings.round.interval
        self.released = 0        # how many ducks have been released this round
        self.elapsed = 0.0       # how long the round has been running, seconds
        self.stopped = False     # the player ended the round early — see stop()
        # events driving the dog's reactions (monotonic counters; the frontend
        # watches them for increments)
        self.landed = 0    # a downed duck hit the ground (the dog retrieves it)
        self.escaped = 0   # a live duck flew off screen (the dog laughs)
        # Who this round IS, for the leaderboard. The id is made here rather than
        # when the result is sent, so a retried POST is recognised as the same
        # round; `started_at` is the wall clock, because `elapsed` cannot say
        # which evening a row belongs to.
        self.run_uuid = uuid.uuid4().hex
        self.started_at = datetime.now(timezone.utc).isoformat(
            timespec="milliseconds")

    @property
    def accuracy(self) -> float:
        return (self.hits / self.shots * 100.0) if self.shots else 0.0

    @property
    def total(self) -> int:
        """How many ducks there are in a round."""
        return self.settings.round.ducks

    @property
    def ammo(self) -> int:
        """Shots left in the magazine, or -1 when it is not counted at all."""
        cap = self.settings.round.ammo
        return -1 if cap <= 0 else max(0, cap - self.shots)

    @property
    def dry(self) -> bool:
        """Out of ammunition. Never true in a round that does not count shots."""
        return self.ammo == 0

    @property
    def crowded(self) -> bool:
        """The sky is as full as `[duck] max_alive` allows. 0 means never.

        A duck that has been shot and is still falling counts: in a practice round
        (`max_alive = 1`) the next duck waits until the dog has picked the last one
        up, which is the pace a first-timer needs and reads on screen as one duck
        at a time rather than as a gap.
        """
        cap = self.settings.duck.max_alive
        return cap > 0 and len(self.ducks) >= cap

    @property
    def finished(self) -> bool:
        """Round over: stopped, or the flock is gone, or the magazine is.

        Either way the sky has to be empty first: the shot that empties the
        magazine still counts, and a duck already falling still lands — ending the
        round on the pull would take away the duck it just downed.
        """
        if self.stopped:
            return True
        if self.ducks:
            return False
        return self.released >= self.total or self.dry

    def stop(self) -> None:
        """End the round where it stands — what has been shot so far still counts.

        A hundred ducks is a long way to be committed to, so the frontend offers
        a way out (ESC) that keeps the score rather than throwing it away. The
        counters are left exactly as they are: `released` says how far the round
        actually got, and `stopped` says why it ended, so the result screen can
        tell a short round from a bad one.
        """
        self.stopped = True
        self.ducks.clear()

    @property
    def floor(self) -> float:
        """The lowest a duck's top-left corner may go.

        The ducks keep to the top `[duck] sky` of the picture (0.90 = the top
        90 %), so the grass band at the bottom stays the dog's. This is that
        limit expressed the way the ducks are stored — as the corner they are
        positioned by, hence minus their own height.
        """
        return max(0.0, self.settings.duck.sky - self.settings.duck.height)

    def spawn(self) -> None:
        duck = self.settings.duck
        from_left = self.rng.random() < 0.5
        facing = Facing.RIGHT if from_left else Facing.LEFT
        x = -duck.width if from_left else 1.0
        speed = self.rng.uniform(duck.speed_min, duck.speed_max)
        vx = speed if from_left else -speed
        self.ducks.append(Duck(
            x=x,
            y=self.rng.uniform(min(0.03, self.floor), self.floor),
            vx=vx,
            vy=self.rng.uniform(-duck.bob, duck.bob),
            w=duck.width,
            h=duck.height,
            facing=facing,
            variant=self.rng.randrange(2),
        ))
        self.released += 1

    def update(self, dt: float, aim_x: float, aim_y: float, fire: bool,
               dog_box: tuple[float, float, float, float] | None = None,
               crosshair: bool = False) -> None:
        """One frame. `dog_box` is the dog's `(x0, y0, x1, y1)` while he is up.

        The dog is drawn by the frontend and the core has never heard of him, but
        a shot that hits him has to cost what every other shot costs, decided in
        the same place — so the frontend hands his box over for the frames he is
        on screen, in the same 0..1 picture coordinates as the aim, and None the
        rest of the time. `crosshair` is the same arrangement for the crosshair:
        the frontend draws it, the round remembers it was up.
        """
        if self.finished:
            return
        if crosshair:
            self.crosshair_used = True
        self.elapsed += dt

        # Spawn new ducks until the whole flock has been released — and no further
        # than the magazine reaches, because launching a duck at a player with
        # nothing to shoot it with is not a round, it is a taunt.
        self.spawn_timer += dt
        if self.released < self.total and not self.dry \
                and self.spawn_timer >= self.spawn_interval:
            if self.crowded:
                # The pace is a timer, so a duck held back would otherwise owe a
                # whole interval once the sky clears. Hold the timer at the mark
                # instead: the next duck goes up as soon as there is room.
                self.spawn_timer = self.spawn_interval
            else:
                self.spawn_timer = 0.0
                self.spawn()
                rnd = self.settings.round
                self.spawn_interval = max(rnd.min_interval,
                                          self.spawn_interval * rnd.speedup)

        # A shot downs the flying duck NEAREST the crosshair, if any is within the
        # shot's radius ([gun] spread) — the frontend draws the crosshair at that
        # same radius, so the circle on screen is the hit zone. Nearest rather
        # than first in the list, because with a radius two ducks can be in range
        # at once and the one you were aiming at is the closer one.
        if fire and not self.dry:
            self.shots += 1
            points = self.settings.score
            radius = self.settings.gun.spread
            best, best_d = None, None
            for d in self.ducks:
                if d.state is not DuckState.FLYING:
                    continue
                dist = d.distance_to(aim_x, aim_y)
                if dist <= radius and (best_d is None or dist < best_d):
                    best, best_d = d, dist
            if best is not None:
                best.state = DuckState.FALLING
                best.vx = 0.0
                self.hits += 1
                self.score += points.duck
            elif dog_box is not None and _inside(dog_box, aim_x, aim_y):
                # The dog is in front of everything while he is up, so he is
                # checked after the ducks only because a duck in range was what
                # the shot was for; hitting him instead is its own mistake and
                # costs its own amount rather than a miss on top.
                self.dog_hits += 1
                self.score += points.dog
            else:
                self.score += points.miss

        # physics
        for d in self.ducks:
            d.age += dt
            if d.state is DuckState.FALLING:
                d.fall_t += dt
                d.y += self.settings.duck.fall_speed * dt
            else:
                d.x += d.vx * dt
                d.y += d.vy * dt
                # bounce off the top of the picture and off the bottom of the
                # sky strip ([duck] sky) — never down into the dog's grass
                if d.y < 0.0 or d.y > self.floor:
                    d.vy = -d.vy

        # drop ducks that left the playfield, counting the events for the dog
        kept = []
        for d in self.ducks:
            gone = not (-0.2 < d.x < 1.2 and d.y < 1.2)
            if gone:
                if d.state is DuckState.FALLING:
                    self.landed += 1      # shot down and fallen -> the dog retrieves it
                else:
                    self.escaped += 1     # got away alive -> the dog laughs
            else:
                kept.append(d)
        self.ducks = kept
