"""Cyclopts CLI implementation."""

import cyclopts

# Create the main CLI app
app = cyclopts.App(name="cyclopts")
app.register_install_completion_command(
    help="""\
    Register shell-completion for the cyclopts CLI itself.
    """
)


# Explicitly import command modules
from cyclopts.cli import (
    _complete,  # noqa: F401
    docs,  # noqa: F401
    run,  # noqa: F401
)

__all__ = ["app"]
