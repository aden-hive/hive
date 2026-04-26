#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`525` **type-checking expression snippets** (i.e.,
triple-quoted pure-Python string constants formatted and concatenated together
to dynamically generate boolean expressions type-checking arbitrary objects
against :pep:`525`-compliant asynchronous generator factories).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.code.datacodename import (
    ARG_NAME_FUNC,
    VAR_NAME_PITH_ROOT,
)

# ....................{ CODE                               }....................
# This pure-Python code snippet is *EXTREMELY* inspired by a comparable snippet
# exhibited in the "Formal Semantics" subsection of PEP 380, which standardized
# the "yield from" expression applicable *ONLY* to synchronous generators:
#     https://peps.python.org/pep-0380/#formal-semantics
#
# PEP 380 differs from most PEPs. Code snippets in most PEPs commonly contain
# syntactic and semantic errors; those snippets were *NEVER* actually tested.
# PEP 695 is the canonical example, containing this particular nugget of bad:
#     # A type alias that includes a forward reference
#     type AnimalOrVegetable = Animal | "Vegetable"
#
# Let's charitably assume the "Animal" type exists. Even then, evaluating that
# PEP 695-compliant type alias raises the expected "TypeError". Why? Because
# strings fail to support the "|" operator, of course:
#     >>> type AnimalOrVegetable = Animal | "Vegetable"
#     >>> class Animal(): ...
#     >>> AnimalOrVegetable.__value__
#     TypeError: unsupported operand type(s) for |: 'type' and 'str'
#
# PEPs are thus untrustworthy with respect to code snippets. For safety, it's
# best to charitably assume *ALL* PEP code to be guilty before proven innocent.
#
# PEP 380 differs. The pure-Python code snippet exhibited in the "Formal
# Semantics" subsection of PEP 380 works -- but it doesn't just work. It appears
# to be the best possible pure-Python approximation of the underlying default C
# implementation of the "yield from" expression in CPython. It doesn't appear
# possible to profitably optimize, refactor, or otherwise improve that snippet.
# We can only surmise that Gregory Ewing (the ingenious author of PEP 380)
# implemented "yield from" with that exact pure-Python snippet as a fully
# working proof-of-concept before eventually unrolling his equivalent C
# implementation -- which makes a great deal of sense. Iterative development is
# considerably faster, easier, and more productive in Python than C. It only
# makes sense to perfect the Python implementation before finalizing that in C.
#
# We thus caution against making *ANY* modifications (however well-intended) to
# this code snippet. You may think you are doing the right thing. You probably
# even believe what you think. But you are wrong. This snippet maximally covers
# all possible edge cases, of which there are uncountably many. With only three
# exceptions, this snippet cannot be improved. These exceptions are:
# 1. Unreadability. For unknown reasons, the original snippet in PEP 380
#    intentionally privatized *ALL* local variables used throughout that snippet
#    as single-letter variable names of the form "_{letter}" (e.g., "_m", "_y").
#    Why? No idea. It doesn't promote readability, usability, or debuggability.
#    The only reason to do that is to obfuscate -- an indefensible reason that
#    has no place in PEP standards. We surmise that Gregory Ewing intended to
#    dissuade brave readers from hand-rolling their own pure-Python alternatives
#    in favour of the standard "yield from" expression. That's an indefensible
#    reason, though. Obfuscation only favours those with something to hide. We
#    globally rename *ALL* such local variables with more appropriate
#    "__beartype_"-prefixed camel-cased nomenclature.
# 2. Type-safety. For generality and safety, the original snippet in PEP 380
#    supports operands that are *NOT* guaranteed to be synchronous generators.
#    Notably, it accesses methods necessarily bound to synchronous generators
#    (but not other objects) with one "try: ... except AttributeError: ..."
#    block for each such method access: e.g.,
#        try:
#            _m = _i.close
#        except AttributeError:
#            pass
#        else:
#            _m()
#
#    Although a sensible precaution for the general-case, this isn't that case.
#    The code snippet defined below applies *ONLY* to callables that are
#    guaranteed to create and return asynchronous generators at call time. Since
#    type safety and thus the existence of these methods is safeguarded, We
#    reduce that defensive coding style to trivial method calls.
# 3. Type-checking. Obviously, the original snippet in PEP 380 fails to apply
#    type-checking. Thankfully, doing so is mostly trivial. Thus, we do.
#
# Lastly, note that Asynchronous generators *CANNOT* return values -- unlike
# synchronous generators, which may. While the original snippet in PEP 380
# handles such returns, the snippet below *CANNOT* and is thus somewhat terser.
CODE_PEP525_RETURN_CHECKED = f'''
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # [BEGIN "async yield from"] What follows is the pure-Python implementation
    # of the "async yield from" expression... if that existed, which it doesn't.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # Attempt to...
    try:
        # Prime the inner generator by awaiting the value yielded by iterating
        # the inner generator once. Note that *ALL* generators are intrinsically
        # iterable without needing to call either the iter() or aiter()
        # builtins, both of which simply return the passed generator as is.
        __beartype_agen_yield_pith = await anext({VAR_NAME_PITH_ROOT})
    # If doing so raised a PEP 525-compliant "StopAsyncIteration" exception,
    # the inner generator finished immediately without yielding anything. This
    # is a valid use case. Squelch this exception and silently reduce to a noop.
    except StopAsyncIteration:
        return
    # Else, doing so raised *NO* exception. In this case...
    #
    # Note that this "else:" branch *CANNOT* be merged into the main body of the
    # sibling "try:" block defined above. Doing so would allow the caller to
    # erroneously halt the inner generator by passing a "StopAsyncIteration"
    # exception to the athrow() method of this outer generator. Generators may
    # be prematurely halted *ONLY* by calling the aclose() method.
    else:
        # PEP 525-compliant bidirectional communication loop, shuttling values
        # and exceptions between the caller above and inner generator below.
        while True:
            # Attempt to...
            try:
                # Yield the value previously yielded by the inner generator up
                # to the caller *AND* capture any value sent in from the caller.
                __beartype_agen_send_pith = yield __beartype_agen_yield_pith
            # If the caller threw a PEP 525-compliant "GeneratorExit" exception
            # into this outer generator, the caller instructed this outer
            # generator to prematurely close prior to completion by calling the
            # aclose() method on this outer generator. This is a valid use case.
            except GeneratorExit as exception:
                # Propagate this closure request to the inner generator.
                await {VAR_NAME_PITH_ROOT}.aclose()

                # Re-raise this exception for orthogonality with PEP 380.
                raise
            # If the caller threw an exception into this outer generator by
            # passing this exception to the athrow() method of this outer
            # generator...
            except BaseException as __beartype_agen_exception:
                # Propagate this exception to the inner generator *AND*, if the
                # inner generator also catches this exception and then resumes
                # operation by yielding a value, capture this value.
                #
                # Note that *ONLY* the anext() method is efficiently
                # accessible as a builtin. For unknown reasons, the athrow()
                # method is *NOT* and must instead be looked up explicitly.
                try:
                    __beartype_agen_yield_pith = (
                        await {VAR_NAME_PITH_ROOT}.athrow(
                            __beartype_agen_exception))
                # If doing so raised a PEP 525-compliant "StopAsyncIteration"
                # exception, the inner generator caught this exception and then
                # finished immediately without yielding anything further. This
                # is a valid use case. Squelch this exception and halt looping.
                except StopAsyncIteration:
                    return
            # Else, doing so raised *NO* exception. In this case...
            #
            # Note that this "else:" branch *CANNOT* be merged into the main
            # body of the sibling "try:" block defined above. See above.
            else:
                # Attempt to...
                try:
                    # If the caller did *NOT* send a value into this outer
                    # generator, the caller iterated this outer generator.
                    # Iterate the inner generator *AND* capture the value
                    # yielded in response. This is the common case.
                    if __beartype_agen_send_pith is None:
                        __beartype_agen_yield_pith = await anext(
                            {VAR_NAME_PITH_ROOT})
                    # Else, the caller sent a value into this outer generator.
                    # Propagate this value to the inner generator *AND* capture
                    # the value yielded in response. This is an edge case.
                    #
                    # Note that *ONLY* the anext() method is efficiently
                    # accessible as a builtin. For unknown reasons, the asend()
                    # method is *NOT* and must instead be looked up explicitly.
                    else:
                        __beartype_agen_yield_pith = (
                            await {VAR_NAME_PITH_ROOT}.asend(
                                __beartype_agen_send_pith))
                # If doing so raised a PEP 525-compliant "StopAsyncIteration"
                # exception, the inner generator finished immediately without
                # yielding anything further. This is a valid use case. Squelch
                # this exception and halt looping.
                #
                # Note that this exception handling *CANNOT* be merged into the
                # exception handling performed by the parent "try:" block. The
                # latter handles exceptions thrown into this outer generator by
                # the caller calling either the aclose() or athrow() methods on
                # this outer generator. Catching this "StopAsyncIteration"
                # exception in the parent "try:" block would allow the caller to
                # erroneously halt the inner generator by passing this exception
                # to the athrow() method of this outer generator. Generators may
                # be prematurely halted *ONLY* by calling the aclose() method.
                except StopAsyncIteration:
                    return
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # [END "async yield from"]
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!'''
'''
:pep:`525`-compliant code snippet facilitating full-blown bidirectional
communication between the higher-level caller and lower-level asynchronous
generator factory wrapped by :func:`beartype.beartype`-driven type-checking.

This pure-Python code snippet safely implements the hypothetical equivalent of
the ``"async yield from "`` expression -- if that expression existed, which it
does not. Although :pep:`525` claims either pure-Python or C-based
implementations of this expression to currently be infeasible, this snippet
trivially proves that to *not* be the case:

    While it is theoretically possible to implement "yield from" support for
    asynchronous generators, it would require a serious redesign of the
    generators implementation.

See Also
--------
https://github.com/beartype/beartype/issues/592#issuecomment-3559076610
    GitHub issue thread strongly inspiring this implementation. In this thread,
    GitHub users @rboredi and @Glinte present a brilliant first-draft
    pure-Python decorator performing the hypothetical syntactic equivalent of
    the ``"async yield from "`` expression. This code snippet owes a
    considerable debt to @rboredi in particular, who would soon go on to
    extrapolate this explosion of elegance into a full-fledged Python package
    named ``future-async-yield-from``. See below.
https://github.com/rbroderi/future-async-yield-from
    Pure-Python package generalizing the above commentary into a general-purpose
    solution applicable throughout the wider Python ecosystem.
'''


CODE_PEP525_RETURN_UNCHECKED = f'''
    {VAR_NAME_PITH_ROOT} = {ARG_NAME_FUNC}(*args, **kwargs)
    {CODE_PEP525_RETURN_CHECKED}'''
'''
:pep:`525`-compliant code snippet facilitating full-blown bidirectional
communication between the higher-level caller and lower-level asynchronous
generator factory wrapped by :func:`beartype.beartype` *without* type-checking
any values asynchronously produced by that generator (including yields, sends,
and returns).

This snippet is an optimization for the common case in which the return of that
factory is left unannotated.
'''
