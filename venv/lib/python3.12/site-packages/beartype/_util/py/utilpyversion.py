#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **Python interpreter version utilities**.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from sys import version_info

# ....................{ CONSTANTS                          }....................
# While cumbersome, the current approach is substantially faster than automated
# alternatives (e.g., dictionary subclasses overriding the __missing__() dunder
# method to implement crude caches). Faster >>>> every other concern here, as
# Python interpreter version checks appear so frequently in critical code paths.

IS_PYTHON_AT_LEAST_4_0 = version_info >= (4, 0)
'''
:data:`True` only if the active Python interpreter targets at least Python
4.0.0.
'''


#FIXME: After dropping Python 3.16 support:
#* Refactor all code conditionally testing this global to be unconditional.
#* Remove this global.
#* Remove all decorators resembling:
#  @skip_if_python_version_less_than('3.17.0')
IS_PYTHON_AT_LEAST_3_17 = IS_PYTHON_AT_LEAST_4_0 or version_info >= (3, 17)
'''
:data:`True` only if the active Python interpreter targets at least Python
3.17.0.
'''


#FIXME: After dropping Python 3.16 support:
#* Remove all code conditionally testing this global.
#* Remove this global.
IS_PYTHON_AT_MOST_3_16 = not IS_PYTHON_AT_LEAST_3_17
'''
:data:`True` only if the active Python interpreter targets at most Python
3.16.x.
'''


#FIXME: After dropping Python 3.15 support:
#* Refactor all code conditionally testing this global to be unconditional.
#* Remove this global.
#* Remove all decorators resembling:
#  @skip_if_python_version_less_than('3.16.0')
IS_PYTHON_AT_LEAST_3_16 = IS_PYTHON_AT_LEAST_3_17 or version_info >= (3, 16)
'''
:data:`True` only if the active Python interpreter targets at least Python
3.16.0.
'''


#FIXME: After dropping Python 3.15 support:
#* Remove all code conditionally testing this global.
#* Remove this global.
IS_PYTHON_AT_MOST_3_15 = not IS_PYTHON_AT_LEAST_3_16
'''
:data:`True` only if the active Python interpreter targets at most Python
3.15.x.
'''


#FIXME: After dropping Python 3.14 support:
#* Refactor all code conditionally testing this global to be unconditional.
#* Remove this global.
#* Remove all decorators resembling:
#  @skip_if_python_version_less_than('3.15.0')
IS_PYTHON_AT_LEAST_3_15 = IS_PYTHON_AT_LEAST_3_16 or version_info >= (3, 15)
'''
:data:`True` only if the active Python interpreter targets at least Python
3.15.0.
'''


#FIXME: Preserved if we ever require this. *shrug*
# #FIXME: After dropping Python 3.14 support:
# #* Remove all code conditionally testing this global.
# #* Remove this global.
# IS_PYTHON_AT_MOST_3_14 = not IS_PYTHON_AT_LEAST_3_15
# '''
# :data:`True` only if the active Python interpreter targets at most Python
# 3.14.x.
# '''


#FIXME: After dropping Python 3.13 support:
#* Refactor all code conditionally testing this global to be unconditional.
#* Remove this global.
#* Remove all decorators resembling:
#  @skip_if_python_version_less_than('3.14.0')
IS_PYTHON_AT_LEAST_3_14 = IS_PYTHON_AT_LEAST_3_15 or version_info >= (3, 14)
'''
:data:`True` only if the active Python interpreter targets at least Python
3.14.0.
'''


#FIXME: After dropping Python 3.13 support:
#* Remove all code conditionally testing this global.
#* Remove this global.
IS_PYTHON_AT_MOST_3_13 = not IS_PYTHON_AT_LEAST_3_14
'''
:data:`True` only if the active Python interpreter targets at most Python
3.13.x.
'''


#FIXME: After dropping Python 3.12 support:
#* Refactor all code conditionally testing this global to be unconditional.
#* Remove this global.
#* Remove all decorators resembling:
#  @skip_if_python_version_less_than('3.13.0')
IS_PYTHON_AT_LEAST_3_13 = IS_PYTHON_AT_LEAST_3_14 or version_info >= (3, 13)
'''
:data:`True` only if the active Python interpreter targets at least Python
3.13.0.
'''


#FIXME: After dropping Python 3.11 support:
#* Refactor all code conditionally testing this global to be unconditional.
#* Remove this global.
#* Remove all decorators resembling:
#  @skip_if_python_version_less_than('3.12.0')
IS_PYTHON_AT_LEAST_3_12 = IS_PYTHON_AT_LEAST_3_13 or version_info >= (3, 12)
'''
:data:`True` only if the active Python interpreter targets at least Python
3.13.0.
'''


#FIXME: After dropping Python 3.11 support:
#* Remove all code conditionally testing this global.
#* Remove this global.
IS_PYTHON_AT_MOST_3_11 = not IS_PYTHON_AT_LEAST_3_12
'''
:data:`True` only if the active Python interpreter targets at most Python
3.11.x.
'''


#FIXME: After dropping Python 3.10 support:
#* Refactor all code conditionally testing this global to be unconditional.
#* Remove this global.
#* Remove all decorators resembling:
#  @skip_if_python_version_less_than('3.11.0')
IS_PYTHON_AT_LEAST_3_11 = IS_PYTHON_AT_LEAST_3_12 or version_info >= (3, 11)
'''
:data:`True` only if the active Python interpreter targets at least Python
3.11.0.
'''


#FIXME: After dropping Python 3.11 support:
#* Refactor all code conditionally testing this global to be unconditional.
#* Remove this global.
IS_PYTHON_3_11 = version_info[:2] == (3, 11)
'''
:data:`True` only if the active Python interpreter targets exactly Python
3.11.x.
'''


#FIXME: After dropping Python 3.10 support:
#* Remove all code conditionally testing this global.
#* Remove this global.
IS_PYTHON_AT_MOST_3_10 = not IS_PYTHON_AT_LEAST_3_11
'''
:data:`True` only if the active Python interpreter targets at most Python
3.10.x.
'''

# ....................{ GETTERS                            }....................
def get_python_version_major_minor() -> str:
    '''
    ``"."``-delimited major and minor version of the active Python interpreter
    (e.g., ``3.11``, ``3.7``), excluding the patch version of this interpreter.
    '''

    # Heroic one-liners are an inspiration to us all.
    return f'{version_info[0]}.{version_info[1]}'
