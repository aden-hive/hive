#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **magic error substrings** (i.e., string constants intended to be
embedded in exception and warning messages or otherwise pertaining to exceptions
and warnings).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ STRINGS                            }....................
EXCEPTION_PLACEHOLDER = '$%ROOT_PITH_LABEL/~'
'''
Non-human-readable source substring to be globally replaced by a human-readable
target substring in the messages of memoized exceptions passed to the
:func:`reraise_exception` function.

This substring prefixes most exception messages raised by memoized callables,
including code generation factories memoized on passed PEP-compliant type hints
(e.g., the :mod:`beartype._check` and :mod:`beartype._decor` submodules). The
:func:`beartype._util.error.utilerrraise.reraise_exception_placeholder` function
then dynamically replaces this prefix of the message of the passed exception
with a human-readable synopsis of the current unmemoized exception context,
including the name of both the currently decorated callable *and* the currently
iterated parameter or return of that callable for aforementioned code generation
factories.

Usage
-----
This substring is typically hard-coded into non-human-readable exception
messages raised by low-level callables memoized with the
:func:`beartype._util.cache.utilcachecall.callable_cached` decorator. Why?
Memoization prohibits those callables from raising human-readable exception
messages. Why? Doing so would require those callables to accept fine-grained
parameters unique to each call to those callables, which those callables would
then dynamically format into human-readable exception messages raised by those
callables. The standard example would be a ``exception_prefix`` parameter
labelling the human-readable category of type hint being inspected by the
current call (e.g., ``@beartyped muh_func() parameter "muh_param" PEP type hint
"List[int]"`` for a ``List[int]`` type hint on the `muh_param` parameter of a
``muh_func()`` function decorated by the :func:`beartype.beartype` decorator).
Since the whole point of memoization is to cache callable results between calls,
any callable accepting any fine-grained parameter unique to each call to that
callable is effectively *not* memoizable in any meaningful sense of the
adjective "memoizable." Ergo, memoized callables *cannot* raise human-readable
exception messages unique to each call to those callables.

This substring indirectly solves this issue by inverting the onus of human
readability. Rather than requiring memoized callables to raise human-readable
exception messages unique to each call to those callables (which we've shown
above to be pragmatically infeasible), memoized callables instead raise
non-human-readable exception messages containing this substring where they
instead would have contained the human-readable portions of their messages
unique to each call to those callables. This indirection renders exceptions
raised by memoized callables generic between calls and thus safely memoizable.

This indirection has the direct consequence, however, of shifting the onus of
human readability from those lower-level memoized callables onto higher-level
non-memoized callables -- which are then required to explicitly (in order):

#. Catch exceptions raised by those lower-level memoized callables.
#. Call the :func:`reraise_exception_placeholder` function with those
   exceptions and desired human-readable substrings. That function then:

   #. Replaces this magic substring hard-coded into those exception messages
      with those human-readable substring fragments.
   #. Reraises the original exceptions in a manner preserving their original
      tracebacks.

Unsurprisingly, as with most inversion of control schemes, this approach is
non-intuitive. Surprisingly, however, the resulting code is actually *more*
elegant than the standard approach of raising human-readable exceptions from
low-level callables. Why? Because the standard approach percolates
human-readable substring fragments from the higher-level callables defining
those fragments to the lower-level callables raising exception messages
containing those fragments. The indirect approach avoids percolation, thus
streamlining the implementations of all callables involved. Phew!
'''


EXCEPTION_PREFIX_DEFAULT = f'{EXCEPTION_PLACEHOLDER}default '
'''
Non-human-readable source substring to be globally replaced by a human-readable
target substring in the messages of memoized exceptions passed to the
:func:`reraise_exception` function caused by violations raised when
type-checking the default values of optional parameters for
:func:`beartype.beartype`-decorated callables.
'''
