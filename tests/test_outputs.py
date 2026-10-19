"""Picking the display and the audio output: `[sound] device` matching, and the
`--display` / `--audio` overrides laid over every mode's settings."""

from argparse import Namespace

from duckhunt.core.config import Settings
from duckhunt.sound import pick_output
from main import with_outputs

OUTPUTS = ["MacBook Pro Speakers", "LG TV (HDMI)", "LG TV SSCR2"]


def test_an_exact_name_wins_even_when_it_is_part_of_another():
    assert pick_output(["TV", "TV 2"], "tv") == "TV"


def test_part_of_a_name_picks_the_one_output_containing_it():
    assert pick_output(OUTPUTS, "macbook") == "MacBook Pro Speakers"
    assert pick_output(OUTPUTS, "hdmi") == "LG TV (HDMI)"


def test_two_matches_is_no_guess(capsys):
    assert pick_output(OUTPUTS, "lg tv") is None
    assert "matches several" in capsys.readouterr().out


def test_no_match_says_what_there_is(capsys):
    assert pick_output(OUTPUTS, "headphones") is None
    assert "MacBook Pro Speakers" in capsys.readouterr().out


def test_the_flags_override_the_settings():
    s = with_outputs(Settings(), Namespace(display=1, size=0.6, audio="tv"))
    assert s.scene.display == 1
    assert s.scene.size == 0.6
    assert s.sound.device == "tv"


def test_no_flags_leave_the_settings_alone():
    base = Settings()
    assert with_outputs(base, Namespace(display=None, size=None, audio=None)) == base
