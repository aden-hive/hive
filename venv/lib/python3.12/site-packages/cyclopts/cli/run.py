"""Run Cyclopts applications from Python scripts."""

from pathlib import Path
from typing import Annotated

from cyclopts.cli import app
from cyclopts.loader import load_app_from_script
from cyclopts.parameter import Parameter


@app.command(help_flags="")
def run(
    script: Annotated[
        Path,
        Parameter(allow_leading_hyphen=True),
    ],
    /,
    *args: Annotated[str, Parameter(allow_leading_hyphen=True)],
):
    """Run a Cyclopts application from a Python script with dynamic shell completion.

    All arguments after the script path are passed to the loaded application.

    Shell completion is available. Run once to install (persistent):
    ``cyclopts --install-completion``

    Parameters
    ----------
    script : str
        Python script path with optional ':app_object' notation.
    args : str
        Arguments to pass to the loaded application.

    Examples
    --------
    Run a script:
        cyclopts run myapp.py --verbose foo bar

    Specify app object:
        cyclopts run myapp.py:app --help
    """
    if str(script) in app.help_flags:
        app.help_print()
        return
    app_obj, _ = load_app_from_script(script)
    return app_obj(args)
