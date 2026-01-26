#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **Python expression-specific magic numbers** (i.e., integer
constants describing dynamically generated Python expressions).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ INTEGERS                           }....................
LINE_RSTRIP_INDEX_AND = -len(' and')
'''
Negative index relative to the end of any arbitrary newline-delimited Python
code string suffixed by the boolean operator ``" and"`` required to strip that
suffix from that substring.
'''


LINE_RSTRIP_INDEX_OR = -len(' or')
'''
Negative index relative to the end of any arbitrary newline-delimited Python
code string suffixed by the boolean operator ``" or"`` required to strip that
suffix from that substring.
'''
