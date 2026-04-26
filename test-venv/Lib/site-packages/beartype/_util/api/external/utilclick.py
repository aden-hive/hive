#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **Click utilities** (i.e., low-level callables handling the
third-party :mod:`click` package).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: The top-level of this module should avoid importing from third-party
# optional libraries, both because those libraries cannot be guaranteed to be
# either installed or importable here *AND* because those imports are likely to
# be computationally expensive, particularly for imports transitively importing
# C extensions (e.g., anything from NumPy or SciPy).
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
from beartype.roar import BeartypeDecorWrappeeException
from beartype._data.typing.datatyping import BeartypeableT

# ....................{ DECORATORS                         }....................
def beartype_click_command(
    click_command: BeartypeableT, **kwargs) -> BeartypeableT:
    '''
    Decorate the passed **Click command** (i.e., object produced by the
    :func:`click.command` decorator decorating an arbitrary callable) with
    dynamically generated type-checking.

    Design
    ------
    Note that the :func:`click.command` decorator does *not* support standard
    decorator chaining "out of the box." Click commands thus require manual
    detection and intervention from the :func:`beartype.beartype` decorator.
    Previously, we attempted to generically decorate Click commands using
    standard decorator chaining; that is to say, we preferred to ignore the
    existence of Click commands. Sadly, doing so caused Click to raise
    unreadable exceptions resembling the following -- indicative of low-level
    unresolved issues within Click itself:

    .. code-block:: python

       >>> from beartype import beartype
       >>> from click import command
       >>> from click.testing import CliRunner

       >>> @beartype
       ... @command()
       ... def main() -> None: pass

       >>> runner = CliRunner()
       >>> result = runner.invoke(cli=main)
       Traceback (most recent call last):
         File "/usr/lib/python3.13/site-packages/click/testing.py", line 403, in invoke
           prog_name = extra.pop("prog_name")
       KeyError: 'prog_name'

       During handling of the above exception, another exception occurred:

       Traceback (most recent call last):
         File "/home/leycec/tmp/mopy.py", line 19, in <module>
           result = runner.invoke(cli=main)
         File "/usr/lib/python3.13/site-packages/click/testing.py", line 405, in invoke
           prog_name = self.get_default_prog_name(cli)
         File "/usr/lib/python3.13/site-packages/click/testing.py", line 195, in get_default_prog_name
           return cli.name or "root"
                  ^^^^^^^^
       AttributeError: 'NoneType' object has no attribute 'name'

    Parameters
    ----------
    func : BeartypeableT
        Click command to be decorated by :func:`beartype.beartype`.

    All remaining keyword parameters are passed as is to the lower-level
    :func:`._beartype_func` decorator internally called by this higher-level
    decorator on the pure-Python function encapsulated in this Click command.

    Returns
    -------
    BeartypeableT
        New pure-Python callable wrapping this Click command with type-checking.
    '''

    # Avoid circular and third-party import dependencies.
    from beartype._decor._nontype.decornontype import beartype_func
    from click.core import Command  # pyright: ignore

    # If this Click command is *NOT* actually a @click.command()-decorated
    # callable, raise an exception.
    if not isinstance(click_command, Command):
        raise BeartypeDecorWrappeeException(  # pragma: no cover
            f'Click command {repr(click_command)} not  '
            f'decorated by @click.command().'
        )
    # Else, this Click command is a @click.command()-decorated callable.

    # Old pure-Python callable decorated by the @click.command() decorator.
    func = click_command.callback  # pyright: ignore

    # New pure-Python callable decorating that callable with type-checking.
    func_checked = beartype_func(func=func, **kwargs)  # type: ignore[type-var]

    # Replace the old with new pure-Python callable in the Click command created
    # and returned by the @click.command() decorator.
    click_command.callback = func_checked  # pyright: ignore

    # Return the same Click command.
    return click_command  # type: ignore[return-value]
