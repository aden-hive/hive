#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **exception handlers** (i.e., low-level callables manipulating
fatal exceptions in a human-readable, general-purpose manner).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import NoReturn
from beartype._data.error.dataerrmagic import EXCEPTION_PLACEHOLDER
from beartype._util.error.utilerrtest import is_exception_message_str
from beartype._util.text.utiltextmunge import uppercase_str_char_first

# ....................{ RAISERS                            }....................
def reraise_exception_placeholder(
    # Mandatory parameters.
    exception: Exception,
    target_str: str,

    # Optional parameters.
    source_str: str = EXCEPTION_PLACEHOLDER,
) -> NoReturn:
    '''
    Reraise the passed exception in a safe manner preserving both this exception
    object *and* the original traceback associated with this exception object,
    but globally replacing all instances of the passed source substring
    hard-coded into this exception's message with the passed target substring.

    Parameters
    ----------
    exception : Exception
        Exception to be reraised.
    target_str : str
        Target human-readable format substring to replace the passed source
        substring previously hard-coded into this exception's message.
    source_str : Optional[str]
        Source non-human-readable substring previously hard-coded into this
        exception's message to be replaced by the passed target substring.
        Defaults to :data:`.EXCEPTION_PLACEHOLDER`.

    Raises
    ------
    exception
        The passed exception, globally replacing all instances of this source
        substring in this exception's message with this target substring.

    See Also
    --------
    :data:`.EXCEPTION_PLACEHOLDER`
        Further commentary on usage and motivation.
    https://stackoverflow.com/a/62662138/2809027
        StackOverflow answer mildly inspiring this implementation.

    Examples
    --------
    .. code-block:: pycon

       >>> from beartype.roar import BeartypeDecorHintPepException
       >>> from beartype._util.cache.utilcachecall import callable_cached
       >>> from beartype._util.error.utilerrraise import (
       ...     reraise_exception_placeholder, EXCEPTION_PLACEHOLDER)
       >>> from random import getrandbits
       >>> @callable_cached
       ... def portend_low_level_winter(is_winter_coming: bool) -> str:
       ...     if is_winter_coming:
       ...         raise BeartypeDecorHintPepException(
       ...             '{} intimates that winter is coming.'.format(
       ...                 EXCEPTION_PLACEHOLDER))
       ...     else:
       ...         return 'PRAISE THE SUN'
       >>> def portend_high_level_winter() -> None:
       ...     try:
       ...         print(portend_low_level_winter(is_winter_coming=False))
       ...         print(portend_low_level_winter(is_winter_coming=True))
       ...     except BeartypeDecorHintPepException as exception:
       ...         reraise_exception_placeholder(
       ...             exception=exception,
       ...             target_str=(
       ...                 'Random "Song of Fire and Ice" spoiler' if getrandbits(1) else
       ...                 'Random "Dark Souls" plaintext meme'
       ...             ))
       >>> portend_high_level_winter()
       PRAISE THE SUN
       Traceback (most recent call last):
         File "<input>", line 30, in <module>
           portend_high_level_winter()
         File "<input>", line 27, in portend_high_level_winter
           'Random "Dark Souls" plaintext meme'
         File "/home/leycec/py/beartype/beartype._util.error.utilerrraise.py", line 225, in reraise_exception_placeholder
           raise exception.with_traceback(exception.__traceback__)
         File "<input>", line 20, in portend_high_level_winter
           print(portend_low_level_winter(is_winter_coming=True))
         File "/home/leycec/py/beartype/beartype/_util/cache/utilcachecall.py", line 296, in _callable_cached
           raise exception
         File "/home/leycec/py/beartype/beartype/_util/cache/utilcachecall.py", line 289, in _callable_cached
           *args, **kwargs)
         File "<input>", line 13, in portend_low_level_winter
           EXCEPTION_PLACEHOLDER))
       beartype.roar.BeartypeDecorHintPepException: Random "Song of Fire and Ice" spoiler intimates that winter is coming.
    '''
    assert isinstance(exception, Exception), (
        f'{repr(exception)} not exception.')
    assert isinstance(source_str, str), f'{repr(source_str)} not string.'
    assert isinstance(target_str, str), f'{repr(target_str)} not string.'

    # If this is a conventional exception...
    if is_exception_message_str(exception):
        # Munged exception message globally replacing all instances of this
        # source substring with this target substring.
        #
        # Note that we intentionally call the lower-level str.replace() method
        # rather than the higher-level
        # beartype._util.text.utiltextmunge.replace_str_substrs() function here,
        # as the latter unnecessarily requires this exception message to contain
        # one or more instances of this source substring.
        exception_message = exception.args[0].replace(source_str, target_str)

        # If doing so actually changed this message...
        if exception_message != exception.args[0]:
            # Uppercase the first character of this message if needed.
            exception_message = uppercase_str_char_first(exception_message)

            # Reconstitute this exception argument tuple from this message.
            #
            # Note that if this tuple contains only this message, this slice
            # "exception.args[1:]" safely yields the empty tuple. Go, Python!
            exception.args = (exception_message,) + exception.args[1:]
        # Else, this message remains preserved as is.
    # Else, this is an unconventional exception. In this case, preserve this
    # exception as is.

    # Re-raise this exception while preserving its original traceback.
    raise exception.with_traceback(exception.__traceback__)
