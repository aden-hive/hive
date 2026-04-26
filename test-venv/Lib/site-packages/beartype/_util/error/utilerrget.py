#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **exception getters** (i.e., low-level callables retrieving
metadata associated with various types of exceptions).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilExceptionException
from beartype._util.text.utiltextlabel import label_exception

# ....................{ GETTERS                            }....................
def get_name_error_attr_name(name_error: NameError) -> str:
    '''
    Unqualified basename of the non-existent attribute referenced by the passed
    :class:`NameError` exception.

    Parameters
    ----------
    name_error : NameError
        :class:`NameError` exception to be inspected.

    Returns
    -------
    str
        Unqualified basename of this non-existent attribute.

    Raises
    ------
    _BeartypeUtilExceptionException
        If this is *not* a well-known :class:`NameError` exception raised by the
        standard Python interpreter.

    Examples
    --------
    .. code-block:: pycon

       >>> from beartype._util.error.utilerrget import (
       ...     get_name_error_attr_name)
       >>> try:
       ...     undefined_attr
       ... except NameError as name_error:
       ...     print(get_name_error_attr_name(name_error))
       ...     print(name_error)
       undefined_attr
       name 'undefined_attr' is not defined
    '''
    assert isinstance(name_error, NameError), (
        f'{repr(name_error)} not "NameError" exception.')

    # Message associated with this name error.
    error_message = str(name_error)

    # Unqualified basename of the non-existent attribute referenced by this
    # message, initialized to the empty string.
    attr_name = ''

    # 0-based index of the first single quote in this message if this message
    # contains a single quote or "-1" otherwise.
    #
    # Note that:
    # * *ALL* well-recognized name errors contain one or more single-quoted
    #   substrings of the form "'{attr_name}'". The first such single-quoted
    #   substring in each name error provides the desired unqualified basename
    #   of the undefined attribute described by this name error.
    # * There exist at least three such kinds of name errors, including:
    #   * Most "NameError" exception messages assume the common form:
    #         NameError: name '{attr_name}' is not defined
    #   * Some "NameError" exception messages assume the less common form:
    #         UnboundLocalError: cannot access local variable '{attr_name}'
    #         where it is not associated with a value
    #   * A few "NameError" exception messages assume the uncommon form:
    #         UnboundLocalError: cannot access free variable '{attr_name}' where
    #         it is not associated with a value in enclosing scope.
    # * The str.find()-based approach performed below is more efficient than:
    #   * A brute-force iterative approach attempting to manually match this
    #     message against an iterable of well-known message prefixes.
    #   * A Python-compatible regular expression (PCRE)-based approach. In
    #     general, PCRE-based matching is only faster than str.find()-based
    #     matching as the number of str.find() calls increases past a certain
    #     threshold. Certainly, two str.find() calls is below that threshold.
    ERROR_MESSAGE_QUOTE_FIRST_INDEX = error_message.find("'")

    # If this name error contains at least one single quote...
    if ERROR_MESSAGE_QUOTE_FIRST_INDEX != -1:
        # Truncate the prefix of this message preceding this first single quote
        # (e.g., from "name '{attr_name}' is not defined" to "{attr_name}' is
        # not defined").
        error_message = error_message[ERROR_MESSAGE_QUOTE_FIRST_INDEX + 1:]
        # print(f'error_message truncated: {error_message}')

        # 0-based index of the next single quote in this message if this message
        # contains a second single quote or "-1" otherwise.
        ERROR_MESSAGE_QUOTE_NEXT_INDEX = error_message.find("'")

        # If this name error contains at least two single quotes...
        if ERROR_MESSAGE_QUOTE_NEXT_INDEX != -1:
            # Define the unqualified basename of the non-existent attribute
            # referenced by this message as the substring of this message
            # bounded by the first and second single quotes in this message
            # (e.g., from "{attr_name}' is not defined" to "{attr_name}").
            attr_name = error_message[:ERROR_MESSAGE_QUOTE_NEXT_INDEX]
        # Else, this name error contains only one single quote.
    # Else, this name error contains *NO* single quotes.

    # If this name error is unrecognized, raise an exception.
    #
    # Note that this should *NEVER* occur. Of course, this will occur.
    if not attr_name:
        raise _BeartypeUtilExceptionException(  # pragma: no cover
            f'Non-standard "{label_exception(name_error)}" unrecognized '
            f"(i.e., single-quoted substring '{{attr_name}}' not found)."
        ) from name_error
    # Else, this name error is recognized.
    #
    # If this basename is *NOT* a Python identifier, raise an exception.
    #
    # Note that this should *NEVER* occur. Of course, this will occur.
    elif not attr_name.isidentifier():
        raise _BeartypeUtilExceptionException(  # pragma: no cover
            f'Non-standard "{label_exception(name_error)}" unrecognized '
            f"(i.e., single-quoted substring '{attr_name}' found but not a "
            f'valid Python identifier).'
        ) from name_error
    # Else, this name error is a Python identifier.

    # Return this basename.
    return attr_name
