#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **exception testers** (i.e., low-level callables introspecting
metadata associated with various types of exceptions).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................

# ....................{ TESTERS                            }....................
#FIXME: Unit test us up, please.
def is_exception_message_str(exception: Exception) -> bool:
    '''
    :data:`True` only if the message encapsulated by the passed exception is a
    simple string (as is typically but *not* necessarily the case).

    Parameters
    ----------
    exception : Exception
        Exception to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this exception's message is a simple string.
    '''
    assert isinstance(exception, Exception), f'{repr(exception)} not exception.'

    # Return true only if...
    return bool(
        # Exception arguments are a tuple (as is typically but not necessarily
        # the case) *AND*...
        isinstance(exception.args, tuple) and
        # This tuple is non-empty (as is typically but not necessarily the
        # case) *AND*...
        exception.args and
        # The first item of this tuple is a string providing this exception's
        # message (as is typically but *NOT* necessarily the case)...
        isinstance(exception.args[0], str)
    )
