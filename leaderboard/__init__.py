"""The leaderboard: a server, a store and a page, all of them separate from
the game.

Separate processes, deliberately. The game must never freeze or crash because
the scoreboard is off, and the scoreboard must survive the game being restarted
twenty times an evening. They meet at one HTTP endpoint and one SQLite file —
see docs/LEADERBOARD.md.

    python3 -m leaderboard                     # the server + the board in a browser
    python3 -m leaderboard.server              # :8420, leaderboard.db, nothing opened
"""
