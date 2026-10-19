# Make .venv with a Python pygame ships wheels for (3.13 down to 3.10), and
# install requirements.txt into it whenever that changes. Sourced by ./run and
# ./play from the project root; leaves $VENV set.
#
# Not 3.14: there pip builds pygame from source without SDL_ttf and SDL_mixer,
# and the game dies on its first text.

VENV=.venv
STAMP=$VENV/.requirements-installed

if [ ! -x "$VENV/bin/python" ]; then
    PY=
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        command -v "$candidate" >/dev/null || continue
        if "$candidate" -c 'import sys; sys.exit(not (3, 10) <= sys.version_info[:2] <= (3, 13))'; then
            PY=$candidate
            break
        fi
    done
    if [ -z "$PY" ]; then
        echo "run: needs Python 3.10–3.13 (pygame has no 3.14 wheels yet)." >&2
        echo "     e.g. 'mise install python@3.13' or 'brew install python@3.13'" >&2
        exit 1
    fi
    echo "run: making $VENV with $("$PY" --version)"
    "$PY" -m venv "$VENV"
fi

# Install on the first run, and again whenever requirements.txt changes.
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
    # pygame-ce replaced pygame and both own the pygame/ folder: drop the old
    # one first, or uninstalling it later would take the new one's files too.
    if "$VENV/bin/python" -m pip show -q pygame >/dev/null 2>&1; then
        "$VENV/bin/python" -m pip uninstall -q -y pygame pygame-ce
    fi
    "$VENV/bin/python" -m pip install -q --disable-pip-version-check -r requirements.txt
    touch "$STAMP"
fi
