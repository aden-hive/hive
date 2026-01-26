#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **warning handlers** (i.e., low-level callables manipulating
non-fatal warnings -- which, technically, are also exceptions -- in a
human-readable, general-purpose manner).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Any,
    Iterable,
    Iterator,
)
from beartype._data.error.dataerrmagic import EXCEPTION_PLACEHOLDER
from beartype._data.typing.datatyping import TypeWarning
from beartype._util.error.utilerrtest import is_exception_message_str
from beartype._util.py.utilpyversion import (
    IS_PYTHON_AT_LEAST_3_11,
    IS_PYTHON_AT_LEAST_3_12,
)
from beartype._util.text.utiltextmunge import uppercase_str_char_first
from collections.abc import Iterable as IterableABC
from contextlib import contextmanager
from warnings import (
    WarningMessage,
    catch_warnings,
    simplefilter,
    warn,
    warn_explicit,
)

# ....................{ CONTEXTS                           }....................
#FIXME: Unit test us up, please.
@contextmanager
def warnings_ignored() -> Iterator[None]:
    '''
    Context manager temporarily ignoring *all* warnings transitively emitted
    within the body of this context.

    Yields
    ------
    None
        This context manager yields *no* objects.

    See Also
    --------
    https://stackoverflow.com/a/14463362/2809027
        StackOverflow answer strongly inspiring this implementation.
    '''

    # If the active Python interpreter targets Python > 3.11, prefer an
    # efficient one-liner yielding the desired outcome. Get it? Yielding? ...heh
    if IS_PYTHON_AT_LEAST_3_11:
        with catch_warnings(action='ignore'):  # type: ignore[call-overload]
            yield
    # Else, the active Python interpreter targets Python <= 3.10. In this case,
    # fallback to an inefficient generator yielding the same outcome.
    else:
        with catch_warnings():
            simplefilter('ignore')
            yield

# ....................{ WARNERS                            }....................
# If the active Python interpreter targets Python >= 3.12, the standard
# warnings.warn() function supports the optional "skip_file_prefixes" parameter
# critical for emitting more useful warnings. In this case, define the
# issue_warning() warner to pass that parameter.
if IS_PYTHON_AT_LEAST_3_12:
    # ....................{ IMPORTS                        }....................
    # Defer version-specific imports.
    import beartype
    from os.path import dirname

    # ....................{ WARNERS                        }....................
    def issue_warning(cls: TypeWarning, message: str) -> None:
        # The warning you gave us is surely our last!
        warn(message, cls, skip_file_prefixes=_ISSUE_WARNING_IGNORE_DIRNAMES)  # type: ignore[call-overload]
        # warn(message, cls)  # type: ignore[call-overload]

    # ....................{ PRIVATE ~ globals              }....................
    _ISSUE_WARNING_IGNORE_DIRNAMES = (dirname(beartype.__file__),)
    '''
    Tuple of one or more **ignorable warning dirnames** (i.e., absolute
    directory names of all Python modules to be ignored by the
    :func:`.issue_warning` warner when deciding which source module to associate
    with the issued warning, enabling this warner to associate this warning with
    the original externally defined module to which this warning applies).

    This tuple includes the dirname of the top-level directory providing the
    :mod:`beartype` package, enabling this warner to ignore all stack frames
    produced by internal calls to submodules of this package. Doing so emits
    substantially more useful and readable warnings for external callers.
    '''
# Else, the active Python interpreter targets Python < 3.12. In this case,
# define the issue_warning() warner to avoid passing that parameter.
else:
    def issue_warning(cls: TypeWarning, message: str) -> None:
        # Time to cry your tears! Now cry!
        warn(message, cls)


issue_warning.__doc__ = (
    '''
    Issue (i.e., emit) a non-fatal warning of the passed type with the passed
    message.

    Caveats
    -------
    **This high-level warner should always be called in lieu of the low-level**
    :func:`warnings.warn` **warner.** Whereas the latter issues warnings that
    obfuscate the external user-defined modules to which those warnings apply,
    this warner associates this warning with the applicable user-defined module
    when the active Python interpreter targets Python >= 3.12.

    Parameters
    ----------
    cls: Type[Warning]
        Type of warning to be issued.
    message: str
        Human-readable warning message to be issued.
    '''
)

# ....................{ REWARNERS                          }....................
def reissue_warnings_placeholder(
    # Mandatory parameters.
    warnings: Iterable[WarningMessage],
    target_str: str,

    # Optional parameters.
    source_str: str = EXCEPTION_PLACEHOLDER,
) -> None:
    '''
    Reissue (i.e., re-emit) the passed warning in a safe manner preserving both
    this warning object *and* **associated context** (e.g., filename, line
    number) associated with this warning object, but globally replacing all
    instances of the passed source substring hard-coded into this warning's
    message with the passed target substring.

    Parameters
    ----------
    warnings : Iterable[WarningMessage]
        Iterable of zero or more warnings to be reissued, typically produced by
        an external call to the standard
        ``warnings.catch_warnings(record=True)`` context manager.
    target_str : str
        Target human-readable format substring to replace the passed source
        substring previously hard-coded into this warning's message.
    source_str : Optional[str]
        Source non-human-readable substring previously hard-coded into this
        warning's message to be replaced by the passed target substring.
        Defaults to :data:`.EXCEPTION_PLACEHOLDER`.

    Warns
    -----
    warning
        The passed warning, globally replacing all instances of this source
        substring in this warning's message with this target substring.

    See Also
    --------
    :data:`.EXCEPTION_PLACEHOLDER`
        Further commentary on usage and motivation.
    https://stackoverflow.com/a/77516994/2809027
        StackOverflow answer strongly inspiring this implementation.
    '''
    assert isinstance(warnings, IterableABC), (
        f'{repr(warnings)} not iterable.')
    assert isinstance(source_str, str), f'{repr(source_str)} not string.'
    assert isinstance(target_str, str), f'{repr(target_str)} not string.'

    # For each warning descriptor in this iterable of zero or more warning
    # descriptors...
    for warning_info in warnings:
        assert isinstance(warning_info, WarningMessage), (  # <-- terrible name!
           f'{repr(warning_info)} not "WarningMessage" instance.')

        # Original warning wrapped by this warning descriptor, localized both
        # for readability *AND* negligible speed. *sigh*
        warning = warning_info.message

        # Munged warning message to be issued below.
        warning_message_new: Any = None

        # If either...
        if (
            # This warning is... *ALREADY A STRING!?* What is going on here?
            # Look. Not even we know. But mypy claims that warnings recorded by
            # calls to the standard "warnings.catch_warnings(record=True)"
            # function satisfy the union "Warning | str". Technically, that
            # makes no sense. Pragmatically, that makes no sense. But mypy says
            # it's true. We are too tired to argue with static type-checkers at
            # 4:11AM in the morning.
            isinstance(warning, str) or
            # This warning is conventional...
            is_exception_message_str(warning)
        # Then this warning is or has a standard message. In this case...
        ):
            # Original warning message, coerced from the original warning.
            #
            # Note that the poorly named "message" attribute is the original
            # warning rather warning message. Just as with exceptions, coercing
            # this warning into a string reliably retrieves its message.
            warning_message_old = str(warning)

            # Munged warning message globally replacing all instances of this
            # source substring with this target substring.
            #
            # Note that we intentionally call the lower-level str.replace()
            # method rather than the higher-level
            # beartype._util.text.utiltextmunge.replace_str_substrs() function
            # here, as the latter unnecessarily requires this warning message to
            # contain one or more instances of this source substring.
            warning_message_new = warning_message_old.replace(
                source_str, target_str)

            # If doing so actually changed this message...
            if warning_message_new != warning_message_old:
                # Uppercase the first character of this message if needed.
                warning_message_new = uppercase_str_char_first(
                    warning_message_new)
            # Else, this message remains preserved as is.
        # Else, this is an unconventional warning. In this case...
        else:
            # Tuple of the zero or more arguments with which this warning was
            # originally issued.
            warning_args = warning.args

            # Assert that this warning was issued with exactly one argument.
            # Since the warnings.warn() signature accepts only a single
            # "message" parameter, this assertion *SHOULD* always hold. *sigh*
            assert len(warning_args) == 1

            # Preserve this warning as is.
            warning_message_new = warning_args[0]

        # Reissue this warning with a possibly modified message.
        warn_explicit(
            message=warning_message_new,
            category=warning_info.category,
            filename=warning_info.filename,
            lineno=warning_info.lineno,
            source=warning_info.source,
        )
