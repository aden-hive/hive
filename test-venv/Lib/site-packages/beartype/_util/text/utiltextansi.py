# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **ANSI utilities** (i.e., low-level callables handling ANSI escape
sequences colouring arbitrary strings).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.typing.datatyping import BoolTristate
from re import compile as re_compile

# ....................{ CONSTANTS                          }....................
ANSI_RESET = '\033[0m'
'''
ANSI escape sequence resetting the effect of all prior ANSI sequence sequences,
effectively "undoing" all colors and styles applied by those sequences.
'''

# ....................{ CONSTANTS ~ color                  }....................
COLOR_BLUE = '\033[34m'
'''
ANSI escape sequence colouring all subsequent characters as blue.
'''


COLOR_CYAN = '\033[36m'
'''
ANSI escape sequence colouring all subsequent characters as **cyan** (i.e.,
light blue).
'''


COLOR_GREEN = '\033[32m'
'''
ANSI escape sequence colouring all subsequent characters as **green**.
'''


COLOR_MAGENTA = '\033[35m'
'''
ANSI escape sequence colouring all subsequent characters as **magenta** (i.e.,
purple, dark blue).
'''


COLOR_RED = '\033[31m'
'''
ANSI escape sequence colouring all subsequent characters as **red**.
'''


COLOR_YELLOW = '\033[33m'
'''
ANSI escape sequence colouring all subsequent characters as **yellow**.
'''

# ....................{ CONSTANTS ~ style                  }....................
STYLE_BOLD = '\033[1m'
'''
ANSI escape sequence stylizing all subsequent characters as bold.
'''

# ....................{ TESTERS                            }....................
def is_str_ansi(text: str) -> bool:
    '''
    :data:`True` only if the passed text contains one or more ANSI escape
    sequences.

    Parameters
    ----------
    text : str
        Text to be tested.

    Returns
    -------
    bool
        :data:`True` only if this text contains one or more ANSI escape
        sequences.
    '''
    assert isinstance(text, str), f'{repr(text)} not string.'

    # Return true only this compiled regex matching ANSI escape sequences
    # returns a non-"None" match object when passed this text.
    return _ANSI_REGEX.search(text) is not None

# ....................{ COLOURIZERS                        }....................
def color_hint(
    # Mandatory parameters.
    text: str,

    # Optional parameters.
    is_color: BoolTristate = True,
) -> str:
    '''
    Colour the passed substring as a type hint if the passed tri-state colouring
    boolean instructs this function to do so.

    Parameters
    ----------
    text : str
        Text to be coloured as a type hint.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`True`.

    Returns
    -------
    str
        This text conditionally coloured as a type hint.
    '''
    assert isinstance(text, str), f'{repr(text)} not string.'

    # Return either...
    return (
        # If this tri-state boolean instructs this function to colour this
        # string, this string coloured with ANSI;
        f'{STYLE_BOLD}{COLOR_GREEN}{text}{ANSI_RESET}'
        if _is_color(is_color) else
        # Else, this string uncoloured.
        text
    )


def color_pith(
    # Mandatory parameters.
    text: str,

    # Optional parameters.
    is_color: BoolTristate = True,
) -> str:
    '''
    Colour the passed substring as a **pith representation** (i.e.,
    machine-readable string describing the value of the object currently being
    type-checked, typically created by the
    :func:`beartype._util.text.utiltextrepr.represent_object` function) if the
    passed tri-state colouring boolean instructs this function to do so.

    Parameters
    ----------
    text : str
        Text to be coloured as a representation.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`True`.

    Returns
    -------
    str
        This text conditionally coloured as a representation.
    '''
    assert isinstance(text, str), f'{repr(text)} not string.'

    # Return either...
    return (
        # If this tri-state boolean instructs this function to colour this
        # string, this string coloured with ANSI;
        f'{STYLE_BOLD}{COLOR_RED}{text}{ANSI_RESET}'
        if _is_color(is_color) else
        # Else, this string uncoloured.
        text
    )


def color_type(
    # Mandatory parameters.
    text: str,

    # Optional parameters.
    is_color: BoolTristate = True,
) -> str:
    '''
    Colour the passed substring as a simple class if the passed tri-state
    colouring boolean instructs this function to do so.

    Parameters
    ----------
    text : str
        Text to be coloured as a simple class.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`True`.

    Returns
    -------
    str
        This text conditionally coloured as a simple class.
    '''
    assert isinstance(text, str), f'{repr(text)} not string.'

    # Return either...
    return (
        # If this tri-state boolean instructs this function to colour this
        # string, this string coloured with ANSI;
        f'{STYLE_BOLD}{COLOR_YELLOW}{text}{ANSI_RESET}'
        if _is_color(is_color) else
        # Else, this string uncoloured.
        text
    )

# ....................{ COLOURIZERS ~ name                 }....................
def color_attr_name(
    # Mandatory parameters.
    text: str,

    # Optional parameters.
    is_color: BoolTristate = True,
) -> str:
    '''
    Colour the passed substring as a **Python identifier** (e.g., possibly
    fully-qualified name of a module, class, callable, or variable name) if the
    passed tri-state colouring boolean instructs this function to do so.

    Parameters
    ----------
    text : str
        Text to be coloured as a Python identifier.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`True`.

    Returns
    -------
    str
        This text conditionally coloured as a Python identifier.
    '''
    assert isinstance(text, str), f'{repr(text)} not string.'

    # Return either...
    return (
        # If this tri-state boolean instructs this function to colour this
        # string, this string coloured with ANSI;
        f'{STYLE_BOLD}{COLOR_MAGENTA}{text}{ANSI_RESET}'
        if _is_color(is_color) else
        # Else, this string uncoloured.
        text
    )


def color_arg_name(
    # Mandatory parameters.
    text: str,

    # Optional parameters.
    is_color: BoolTristate = True,
) -> str:
    '''
    Colour the passed substring as an **argument name** (i.e., of the parameter
    of a :func:`beartype.beartype`-decorated callable currently being
    type-checked) if the passed tri-state colouring boolean instructs this
    function to do so.

    Parameters
    ----------
    text : str
        Text to be coloured as an argument name.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`True`.

    Returns
    -------
    str
        This text coloured as an argument name.
    '''
    assert isinstance(text, str), f'{repr(text)} not string.'

    # Return either...
    return (
        # If this tri-state boolean instructs this function to colour this
        # string, this string coloured with ANSI;
        f'{STYLE_BOLD}{COLOR_BLUE}{text}{ANSI_RESET}'
        if _is_color(is_color) else
        # Else, this string uncoloured.
        text
    )

# ....................{ STRIPPERS                          }....................
#FIXME: Unit test up the "is_color" parameter.
def strip_str_ansi(
    # Mandatory parameters.
    text: str,

    # Optional parameters.
    is_color: BoolTristate = False,
) -> str:
    '''
    Strip *all* ANSI escape sequences from the passed string if the passed
    tri-state colouring boolean instructs this function to do so.

    Specifically:

    * If ``is_color is True``, this function silently reduces to a noop.
    * If ``is_color is False``, this function unconditionally strips all ANSI
      escape sequences from this string.
    * If ``is_color is None``, this function conditionally strips all ANSI
      escape sequences from this string only if standard output is currently
      attached to an interactive terminal.

    Parameters
    ----------
    text : str
        Text to be stripped.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.

    Returns
    -------
    str
        This text conditionally stripped of ANSI.
    '''
    assert isinstance(text, str), f'{repr(text)} not string.'

    # Return either...
    return (
        # If this tri-state boolean instructs this function to preserve all ANSI
        # in this string, this string unmodified;
        text
        if _is_color(is_color) else
        # Else, this string stripped of all ANSI.
        _ANSI_REGEX.sub('', text)
    )

# ....................{ PRIVATE ~ constants                }....................
_ANSI_REGEX = re_compile(r'\033\[[0-9;?]*[A-Za-z]')
'''
Compiled regular expression matching a single ANSI escape sequence.
'''

# ....................{ PRIVATE ~ testers                  }....................
def _is_color(is_color: BoolTristate) -> bool:
    '''
    Reduce the passed tri-state colouring boolean governing ANSI usage to a
    simple boolean.

    Specifically, this tester returns either:

    * :data:`True` only if the passed ``is_color`` parameter is either:

      * :data:`True`.
      * :data:`None` and standard output is currently attached to an interactive
        POSIX-compliant terminal. Note that this is the common case, as the
        :attr:`beartype.BeartypeConf.is_color` attribute underlying this
        parameter typically defaults to :data:`None`.

    * :data:`False` otherwise.

    Parameters
    ----------
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
    '''
    assert isinstance(is_color, bool) or is_color is None, (  # <-- "NoneTypeOr" is unavailable here
        f'{repr(is_color)} not tri-state boolean.')

    # Avoid circular import dependencies.
    from beartype._util.os.utilostty import is_stdout_terminal

    # Return true only if the passed tri-state boolean is either...
    return (
        # True *OR*...
        is_color is True or
        # "None" and standard output is currently attached to an interactive
        # POSIX-compliant terminal.
        (is_color is None and is_stdout_terminal())
    )
