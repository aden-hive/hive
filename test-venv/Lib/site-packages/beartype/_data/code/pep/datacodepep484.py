#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484` **type-checking expression snippets** (i.e., triple-quoted
pure-Python string constants formatted and concatenated together to dynamically
generate boolean expressions type-checking arbitrary objects against
:pep:`484`-compliant type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.code.datacodename import (
    ARG_NAME_FUNC,
    VAR_NAME_PITH_ROOT,
)

# ....................{ CODE                               }....................
#FIXME: *FALSE.* The following comment is entirely wrong, sadly. Although that
#comment does, in fact, apply to asynchronous generators, that comment does
#*NOT* apply to coroutines. PEP 484 stipulates that the returns of coroutines
#are annotated in the exact same standard way as the returns of synchronous
#callables are annotated: e.g.,
#   # This is valid, but @beartype currently fails to support this.
#   async def muh_coroutine() -> typing.NoReturn:
#       await asyncio.sleep(0)
#       raise ValueError('Dude, who stole my standards compliance?')
#
#Generalize this snippet to contain a "{{func_call_prefix}}" substring prefixing
#the "{ARG_NAME_FUNC}(*args, **kwargs)" call, please.

# Unlike above, this snippet intentionally omits the "{{func_call_prefix}}"
# substring prefixing the "{ARG_NAME_FUNC}(*args, **kwargs)" call. Why? Because
# callables whose returns are annotated by "typing.NoReturn" *MUST* necessarily
# be synchronous (rather than asynchronous) and thus require no such prefix.
# Why? Because the returns of asynchronous callables are either unannotated
# *OR* annotated by either "Coroutine[...]" *OR* "AsyncGenerator[...]" type
# hints. Since "typing.NoReturn" is neither, "typing.NoReturn" *CANNOT*
# annotate the returns of asynchronous callables. The implication then follows.
PEP484_CODE_CHECK_NORETURN = f'''
    # Call this function with all passed parameters and localize the value
    # returned from this call.
    {VAR_NAME_PITH_ROOT} = {{func_call_prefix}}{ARG_NAME_FUNC}(*args, **kwargs)

    # Since this function annotated by "typing.NoReturn" successfully returned a
    # value rather than raising an exception or halting the active Python
    # interpreter, unconditionally raise an exception.
    #
    # Noop required to artificially increase indentation level. Note that
    # CPython implicitly optimizes this conditional away. Isn't that nice?
    if True'''
'''
:pep:`484`-compliant code snippet calling the decorated callable annotated by
the :attr:`typing.NoReturn` singleton and raising an exception if this call
successfully returned a value rather than raising an exception or halting the
active Python interpreter.
'''
