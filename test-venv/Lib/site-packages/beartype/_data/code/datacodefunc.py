#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **wrapper function code snippets** (i.e., triple-quoted pure-Python
string constants formatted and concatenated together to dynamically generate the
implementations of wrapper functions type-checking
:func:`beartype.beartype`-decorated callables).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.code.datacodename import (
    ARG_NAME_ARGS_NAME_KEYWORDABLE,
    ARG_NAME_FUNC,
    ARG_NAME_GET_VIOLATION,
    VAR_NAME_ARGS_LEN,
    VAR_NAME_PITH_ROOT,
)
from beartype._data.code.datacodeindent import CODE_INDENT_1
from beartype._data.typing.datatyping import CallableStrFormat
from beartype._util.func.arg.utilfuncargiter import ArgKind

# ....................{ CODE                               }....................
CODE_SIGNATURE = f'''{{code_signature_prefix}}def {{func_name}}(
    *args,
{{code_signature_scope_args}}{CODE_INDENT_1}**kwargs
):'''
'''
Code snippet declaring the signature of a type-checking callable.

Note that the :func:`beartype._check.signature.make_signature` factory function
internally interpolates these format variables into this string as follows:

* ``code_signature_prefix`` is replaced by:

  * For synchronous callables, the empty string.
  * For asynchronous coroutines (but *not* asynchronous generators, curiously),
    the space-suffixed keyword ``"async "``.

* ``code_signature_scope_args`` is replaced by a comma-delimited string listing
  all :mod:`beartype`-specific hidden parameters internally required to
  type-check the currently decorated callable.
'''


CODE_INIT_ARGS_LEN = f'''
    # Localize the number of passed positional arguments for efficiency.
    {VAR_NAME_ARGS_LEN} = len(args)'''
'''
Code snippet localizing the number of passed positional arguments for callables
accepting one or more such arguments.
'''

# ....................{ CODE ~ arg                         }....................
ARG_KIND_TO_CODE_LOCALIZE = {
    # Snippet localizing any positional-only parameter (e.g.,
    # "{posonlyarg}, /") by lookup in the wrapper's "*args" dictionary.
    ArgKind.POSITIONAL_ONLY: f'''
    # If this positional-only parameter was passed...
    if {VAR_NAME_ARGS_LEN} > {{arg_index}}:
        # Localize this positional-only parameter.
        {VAR_NAME_PITH_ROOT} = args[{{arg_index}}]''',

    # Snippet localizing any positional or keyword parameter as follows:
    #
    # * If this parameter's 0-based index (in the parameter list of the
    #   decorated callable's signature) does *NOT* exceed the number of
    #   positional parameters passed to the wrapper function, localize this
    #   positional parameter from the wrapper's variadic "*args" tuple.
    # * Else if this parameter's name is in the dictionary of keyword
    #   parameters passed to the wrapper function, localize this keyword
    #   parameter from the wrapper's variadic "*kwargs" tuple.
    # * Else, this parameter is unpassed. In this case, localize this parameter
    #   as a placeholder value guaranteed to *NEVER* be passed to any wrapper
    #   function: the private "__beartypistry" singleton passed to this wrapper
    #   function as a hidden default parameter and thus accessible here. While
    #   we could pass a "__beartype_sentinel" parameter to all wrapper
    #   functions defaulting to "object()" and then use that here instead,
    #   doing so would slightly reduce efficiency for no tangible gain. *shrug*
    ArgKind.POSITIONAL_OR_KEYWORD: f'''
    # Localize this positional or keyword parameter if passed *OR* to the
    # sentinel "__beartype_raise_exception" guaranteed to never be passed.
    {VAR_NAME_PITH_ROOT} = (
        args[{{arg_index}}] if {VAR_NAME_ARGS_LEN} > {{arg_index}} else
        kwargs.get({{arg_name!r}}, {ARG_NAME_GET_VIOLATION})
    )

    # If this parameter was passed...
    if {VAR_NAME_PITH_ROOT} is not {ARG_NAME_GET_VIOLATION}:''',

    # Snippet localizing any keyword-only parameter (e.g., "*, {kwarg}") by
    # lookup in the wrapper's variadic "**kwargs" dictionary. (See above.)
    ArgKind.KEYWORD_ONLY: f'''
    # Localize this keyword-only parameter if passed *OR* to the sentinel value
    # "__beartype_raise_exception" guaranteed to never be passed.
    {VAR_NAME_PITH_ROOT} = kwargs.get({{arg_name!r}}, {ARG_NAME_GET_VIOLATION})

    # If this parameter was passed...
    if {VAR_NAME_PITH_ROOT} is not {ARG_NAME_GET_VIOLATION}:''',

    #FIXME: [SPEED] Optimize this from a "for" into "while" loop, please.
    #"while" loops internally raise *NO* "StopException" whereas "for" loops do.
    #Snippet iteratively localizing all variadic positional parameters. *sigh*
    ArgKind.VARIADIC_POSITIONAL: f'''
    # For all excess positional parameters in the passed "*args" parameter...
    for {VAR_NAME_PITH_ROOT} in args[{{arg_index!r}}:]:''',

    #FIXME: [SPEED] Optimize this from a "for" into "while" loop. See above!
    # Snippet iteratively localizing all variadic keyword parameters.
    ArgKind.VARIADIC_KEYWORD: f'''
    # For all excess keyword parameters in the passed "**kwargs" parameter,
    # decided by subtracting the subset of all keywordable parameters
    # explicitly accepted by this callable from the set of all parameters passed
    # by keyword to this callable...
    for {VAR_NAME_PITH_ROOT} in (
        (kwargs[kwarg_name] for kwarg_name in kwargs.keys() - {ARG_NAME_ARGS_NAME_KEYWORDABLE})):''',
}
'''
Dictionary mapping from the type of each callable parameter supported by the
:func:`beartype.beartype` decorator to a code snippet localizing that callable's
next parameter to be type-checked.
'''

# ....................{ CODE ~ return ~ check              }....................
CODE_CALL_CHECKED = f'''
    # Call this function with all passed parameters and localize the value
    # returned from this call.
    {VAR_NAME_PITH_ROOT} = {{func_call_prefix}}{ARG_NAME_FUNC}(*args, **kwargs)

    # Noop required to artificially increase indentation level. Note that
    # CPython implicitly optimizes this conditional away. Isn't that nice?
    if True:'''
'''
Code snippet calling the decorated callable and localizing the value returned by
that call.

Note that:

* The :func:`beartype._decor._nontype._wrap.wrapmaingenerate_code` factory
  function internally interpolates these format variables into this string as
  follows:

  * ``func_call_prefix`` is replaced by:

    * For synchronous callables, the empty string.
    * For asynchronous coroutine factories (but *not* asynchronous generator
      factories, curiously), the space-suffixed keyword ``"await "``.

* This snippet intentionally terminates on a noop increasing the indentation
  level, enabling subsequent type-checking code to effectively ignore
  indentation level and thus uniformly operate on both:

  * Parameters localized via values of the
    :data:`.PARAM_KIND_TO_PEP_CODE_LOCALIZE` dictionary.
  * Return values localized via this snippet.

See Also
--------
https://stackoverflow.com/a/18124151/2809027
    Bytecode disassembly demonstrating that CPython optimizes away the spurious
   ``if True:`` conditional hardcoded into this snippet.
'''


CODE_NORMAL_RETURN_CHECKED = f'''
    return {VAR_NAME_PITH_ROOT}'''
'''
Code snippet returning from the wrapper function the successfully type-checked
value returned from the **normal callable** (either synchronous or asynchronous
non-generator callable decorated by :func:`beartype.beartype`).
'''

# ....................{ CODE ~ return ~ uncheck            }....................
CODE_NORMAL_RETURN_UNCHECKED_SYNC = f'''
    # Call this function with all passed parameters and return the value
    # returned from this call as is (without being type-checked).
    return {ARG_NAME_FUNC}(*args, **kwargs)'''
'''
Code snippet calling the **normal synchronous callable** (non-generator callable
decorated by :func:`beartype.beartype` defined with the ``def`` rather than
``async def`` keyword) *without* type-checking the value returned by that call
(if any).
'''


CODE_NORMAL_RETURN_UNCHECKED_ASYNC = f'''
    # Call this function with all passed parameters and return the value
    # returned from this call as is (without being type-checked).
    return await {ARG_NAME_FUNC}(*args, **kwargs)'''
'''
Code snippet calling the **normal asynchronous callable** (non-generator
callable decorated by :func:`beartype.beartype` defined with the ``async def``
rather than ``def`` keywords) *without* type-checking the value returned by that
call (if any).
'''

# ..................{ FORMATTERS                             }..................
# str.format() methods, globalized to avoid inefficient dot lookups elsewhere.
# This is an absurd micro-optimization. *fight me, github developer community*
CODE_CALL_CHECKED_format: CallableStrFormat = CODE_CALL_CHECKED.format
