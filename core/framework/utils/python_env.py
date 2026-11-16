"""The Python environment Hive's child processes inherit."""

from __future__ import annotations

from collections.abc import MutableMapping

# uv's Windows launcher (the python.exe of a uv-made virtualenv, from
# astral-sh/uv#17821 until #19199 stopped it) sets PYTHONHOME for the
# interpreter it starts and copies the value here, to tell its own PYTHONHOME
# from one the user set.
_UV_PYTHONHOME_MARKER = "UV_INTERNAL__PYTHONHOME"


def drop_launcher_pythonhome(environ: MutableMapping[str, str]) -> bool:
    """Remove the ``PYTHONHOME`` uv's launcher set for this interpreter.

    It served this interpreter's start-up and nothing after, but every
    process Hive starts inherits it: an MCP server that ``uvx`` runs on
    another Python version then loads this one's standard library and dies
    at import (``AssertionError: SRE module mismatch``). A ``PYTHONHOME``
    the user set is kept.

    Returns:
        Whether it was removed.
    """
    home = environ.get("PYTHONHOME")
    if home is None or environ.get(_UV_PYTHONHOME_MARKER) != home:
        return False
    del environ["PYTHONHOME"]
    del environ[_UV_PYTHONHOME_MARKER]
    return True
