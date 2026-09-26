"""The leaderboard: a server, a store and a console board, all of them separate
processes from the game.

Three processes, deliberately. The game must never freeze or crash because the
scoreboard is off, and the scoreboard must survive the game being restarted
twenty times an evening. They meet at one HTTP endpoint and one SQLite file —
see docs/LEADERBOARD.md.

    python3 -m leaderboard.server              # :8420, leaderboard.db
    python3 -m leaderboard.display             # the board, on a screen of its own
"""
