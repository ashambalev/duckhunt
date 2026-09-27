# Modes — another round, without another code path

Every TOML file in this directory is a **mode**: a short file laid *over*
`settings.toml`, which the pixel frontend's title screen offers alongside the
scored round and `practice.toml`. **M** on the keyboard, or **A on the remote**,
cycles them; `--mode NAME` says which one the evening opens on. Nothing has to be
registered anywhere — the file being here is what puts it on the screen.

A mode says who it is, and then says only what makes it a different round:

```toml
# modes/sudden.toml
[mode]
name = "SUDDEN DEATH"                       # what the title screen calls it
note = "one shot, one duck — miss and it is over"   # the line under the name

[round]
ducks = 1
ammo = 1
```

## What a mode may change, and why only that

| | |
|---|---|
| `[round]` `[duck]` `[score]` | the round: how many, how fast, how many at once, what a shot costs |
| `[gun] crosshair` | `"on"`, `"off"` or `"auto"` — the one key of `[gun]` that is the round |

**Everything else is refused**, out loud, and the value in `settings.toml`
stands. The rest of that file is the room and the machine: which monitor, where
the four beacons are taped, how far the gun shoots off them, how loud, which
board. Those were measured once for this house, they are the same whichever round
is being played, and — since the title screen switches modes between rounds —
several of them could not follow a mode anyway: a window does not change size,
and a sight-in does not get re-measured, between two pulls of the trigger.

It is also the old safety of `--practice`, written down rather than remembered: a
mode file that could replace the sight-in and the beacon rectangle would hand a
first-timer the one gun in the house that is not aimed at anything.

The rule lives in `duckhunt/core/config.py` (`MODE_SECTIONS`), the list of modes
in `duckhunt/core/modes.py`.
