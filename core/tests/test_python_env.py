"""The PYTHONHOME uv's Windows launcher leaks to Hive's child processes."""

from __future__ import annotations

import os
import sys

import pytest

from framework.utils.python_env import drop_launcher_pythonhome

_HOME = r"C:\Python\cpython-3.11"


@pytest.mark.parametrize(
    ("environ", "dropped", "left"),
    [
        ({"PYTHONHOME": _HOME, "UV_INTERNAL__PYTHONHOME": _HOME, "PATH": "p"}, True, {"PATH": "p"}),
        # Set by the user: no marker, or a marker for some other value.
        ({"PYTHONHOME": _HOME}, False, {"PYTHONHOME": _HOME}),
        (
            {"PYTHONHOME": _HOME, "UV_INTERNAL__PYTHONHOME": r"C:\other"},
            False,
            {"PYTHONHOME": _HOME, "UV_INTERNAL__PYTHONHOME": r"C:\other"},
        ),
        ({"PATH": "p"}, False, {"PATH": "p"}),
    ],
)
def test_only_the_launchers_pythonhome_is_dropped(environ, dropped, left):
    assert drop_launcher_pythonhome(environ) is dropped
    assert environ == left


def test_hive_drops_it_before_running_a_command(monkeypatch):
    from framework.cli import main

    monkeypatch.setenv("PYTHONHOME", _HOME)
    monkeypatch.setenv("UV_INTERNAL__PYTHONHOME", _HOME)
    monkeypatch.setattr(sys, "argv", ["hive", "--version"])

    with pytest.raises(SystemExit):
        main()

    assert "PYTHONHOME" not in os.environ
    assert "UV_INTERNAL__PYTHONHOME" not in os.environ
