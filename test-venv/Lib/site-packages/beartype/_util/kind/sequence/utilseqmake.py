#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **sequence factories** (i.e., low-level functions creating and
returning various kinds of sequences, both mutable and immutable).
'''

# ....................{ IMPORTS                            }....................
from collections.abc import (
    Sequence as SequenceABC,
)

# ....................{ FACTORIES                          }....................
def make_stack(sequence: SequenceABC) -> list:
    '''
    **Stack** (i.e., efficiently poppable list of all items in the passed
    sequence, intentionally reordered in reverse order such that the first item
    of this sequence is the last item of this list).

    Parameters
    ----------
    sequence : SequenceABC
        Sequence to be coerced into a stack.

    Returns
    -------
    List
        Stack coerced from this sequence.
    '''
    assert isinstance(sequence, SequenceABC), f'{repr(sequence)} not sequence.'

    # Stack coerced from this sequence.
    stack: list = None  # type: ignore[assignment]

    # If this sequence is also a list...
    if isinstance(sequence, list):
        # Non-destructively reverse this list into a reversed copy of this list.
        # Note that this is well-known to be the most efficient means of
        # reversing an existing list into a newly reversed list. See also:
        #     https://stackoverflow.com/a/3705705/2809027
        stack = sequence[::-1]  # behold! the Martian smiley face emoji! ::-1
    # Else, this sequence is *NOT* also a list. In this case...
    else:
        # Coerce this non-list sequence into a list and then destructively
        # reverse this list.
        #
        # Note that this is well-known to be the most efficient means of
        # reversing an arbitrary non-list sequence into a list. See also:
        #     https://stackoverflow.com/a/3705705/2809027
        stack = list(sequence)
        stack.reverse()

    # Return this stack.
    return stack
