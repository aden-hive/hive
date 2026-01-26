#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **Python expression indentation substrings** (i.e., string
constants intended to be embedded as syntactically valid indentation in
dynamically generated Python expressions).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ PRIVATE ~ subclasses               }....................
class _IndentLevelToCode(dict):
    '''
    **Indentation cache** (i.e., dictionary mapping from 1-based indentation
    levels to the corresponding indentation string constant).

    See Also
    --------
    :data:`.INDENT_LEVEL_TO_CODE`
        Singleton instance of this dictionary subclass.
    '''

    # ....................{ DUNDERS                        }....................
    def __missing__(self, indent_level: int) -> str:
        '''
        Dunder method explicitly called by the superclass
        :meth:`dict.__getitem__` method implicitly called on the first ``[``-
        and ``]``-delimited attempt to access an indentation string constant
        with the passed indentation level.

        Parameters
        ----------
        indent_level : int
            1-based level of indentation to be created, cached, and returned.

        Returns
        -------
        str
            String constant indented to this level of indentation.

        Raises
        ------
        AssertionError
            If either:

            * ``indent_level`` is *not* an integer.
            * ``indent_level`` is a **non-positive integer** (i.e., is less than
              or equal to 0).
        '''
        assert isinstance(indent_level, int), (
            f'{repr(indent_level)} not integer.')
        assert indent_level > 0, f'{indent_level} <= 0.'
        # print(f'Generating indentation level {indent_level}...')

        # String constant indented to this level of indentation.
        #
        # Note that this could also be done recursively (e.g., as
        # "self[indent_level - 1]"), but that doing so would be needlessly cute,
        # overly slow, and dangerously fragile for *NO* good reason.
        indent_code = '    ' * indent_level

        # Cache this string constant.
        self[indent_level] = indent_code

        # Return this string constant.
        return indent_code

# ....................{ MAPPINGS                           }....................
INDENT_LEVEL_TO_CODE = _IndentLevelToCode()
'''
**Indentation cache singleton** (i.e., global dictionary efficiently mapping
from 1-based indentation levels to the corresponding indentation string
constant).

Caveats
-------
**Indentation string constants should always be accessed via this cache rather
than manually generated.** This cache dynamically creates and efficiently caches
indentation string constants on the first access of those constants, obviating
the performance cost of string formatting required to create these constants.

Examples
--------
.. code-block:: pycon

   >>> from beartype._data.code.datacodeindent import INDENT_LEVEL_TO_CODE
   >>> INDENT_LEVEL_TO_CODE[1]
   '    '
   >>> INDENT_LEVEL_TO_CODE[2]
   '        '
'''

# ....................{ STRINGS                            }....................
CODE_INDENT_1 = INDENT_LEVEL_TO_CODE[1]
'''
Code snippet expanding to a single level of indentation.
'''


CODE_INDENT_2 = INDENT_LEVEL_TO_CODE[2]
'''
Code snippet expanding to two levels of indentation.
'''


CODE_INDENT_3 = INDENT_LEVEL_TO_CODE[3]
'''
Code snippet expanding to three levels of indentation.
'''
