"""How much name a player may type.

There used to be a `player.json` here as well, remembering the last name typed
on this machine and offering it pre-filled after every round. In the one room
this game is played in that is the wrong default: the next player finishes a
round, the previous player's name is already in the field, and one pull of A
signs their round to somebody else. The field starts empty now, and what is
offered instead is the list of names already on the board — which the trigger
can walk without anyone reaching for a keyboard. `--player NAME` still fills it
in for an evening with one shooter.
"""

from __future__ import annotations

# How much name a player may type. Generous on purpose: a name, a surname, a
# nickname in Cyrillic, all of it. This is what is STORED — what is SHOWN is the
# boards' business, and both of them cut a long name down to the width they have
# (see NAME_W in leaderboard/display.py and .name in leaderboard/board.html). It
# lives here, next to the name itself, now that the local score table it used to
# belong to is gone; `leaderboard.store.NAME_MAX` is the same number on the
# server's side of the wire.
NAME_MAX = 50
