#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

"""
Project-wide **string munging** (i.e., generic low-level operations
transforming strings into new derivative strings) utilities.

This private submodule is *not* intended for importation by downstream callers.
"""

# ....................{ IMPORTS                            }....................
from beartype.roar._roarwarn import _BeartypeUtilCallableWarning
# from beartype.typing import Dict
from beartype._cave._cavefast import NumberType
from beartype._data.typing.datatyping import TypeWarning
from beartype._data.kind.datakindtext import CHARS_PUNCTUATION
from beartype._util.utilobject import get_object_basename_scoped_or_none
from collections.abc import Callable
from pprint import saferepr

# ....................{ REPRESENTERS                       }....................
def represent_object(
    # Mandatory parameters.
    obj: object,

    # Optional parameters.
    max_len: int = 96,
) -> str:
    '''
    Pretty-printed quasi-human-readable variant of the string returned by the
    non-pretty-printed machine-readable :meth:`obj.__repr__` dunder method of
    the passed object, truncated to the passed maximum string length.

    Specifically, this function (in order):

    #. Obtains this object's representation by calling ``repr(object)``.
    #. If this representation is neither suffixed by a punctuation character
       (i.e., character in the standard :attr:`string.punctuation` set) *nor*
       representing a byte-string whose representations are prefixed by ``b'``
       and suffixed by ``'`` (e.g., ``b'Check, mate.'``), double-quotes this
       representation for disambiguity with preceding characters -- notably,
       sequence indices. Since strings returned by this function commonly
       follow sequence indices in error messages, failing to disambiguate the
       two produces non-human-readable output:

           >>> def wat(mate: typing.List[str]) -> int: return len(mate)
           >>> get_func_pith_violation(
           ...     func=muh_func, pith_name='mate', pith_value=[7,])
           beartype.roar.BeartypeCallHintParamViolation: @beartyped wat()
           parameter mate=[7] violates PEP type hint typing.List[str], as list
           item 0 value 7 not a str.

       Note the substring "item 0 value 7", which misreads like a blatant bug.
       Double-quoting the "7" suffices to demarcate values from indices.
    #. If this representation exceeds the passed maximum length, replaces the
       suffix of this representation exceeding this length with an ellipses
       (i.e., ``"..."`` substring).

    Caveats
    -------
    **This function is unavoidably slow and should thus not be called from
    optimized performance-critical code.** This function internally performs
    mildly expensive operations, including iterating-based string munging.
    Ideally, this function should *only* be called to create user-oriented
    exception messages where performance is a negligible concern.

    **This function preserves all quote-protected newline characters** (i.e.,
    ``"\\n"``) **in this representation.** Since the :meth:`str.__repr__`
    dunder method implicitly quote-protects all newlines in the original
    string, this function effectively preserves all newlines in strings.

    Parameters
    ----------
    obj : object
        Object to be represented.
    max_len: int, optional
        Maximum length of the string to be returned. Defaults to a standard
        line length of 100 characters minus output indentation of 4 characters.

    Returns
    -------
    str
        Pretty-printed quasi-human-readable variant of this object's
        non-pretty-printed machine-readable representation.
    '''
    assert isinstance(max_len, int), f'{repr(max_len)} not integer.'

    #FIXME: [SPEED] Note that the popular BSD-licensed Celerity project's
    #celerity.utils.saferepr.saferepr() function claims to actually be faster
    #than the repr() builtin under certain circumstances. While impressive,
    #repurposing Celerity's saferepr() implementation for @beartype will be
    #non-trivial; that function internally leverages a number of non-trivial
    #internal functions, including a streaming iterator that appears to be
    #performing some sort of ad-hoc tokenization (!) on the input object's
    #string representation. Although that submodule is less than 300 lines,
    #that's 300 *INTENSE* lines. Until someone pounds their fists on our issue
    #tracker (so, never), let's pretend no one cares. See also:
    #   https://github.com/celery/celery/blob/master/celery/utils/saferepr.py

    # For efficiency, initially attempt to *NON-RECURSIVELY* introspect the
    # machine-readable string describing this object. Note that:
    # * This representation quote-protects all newlines in this representation.
    #   Ergo, "\n" *MUST* be matched as r"\n" instead below.
    # * For debuggability, the verbose (albeit less readable) output of repr()
    #   is preferred to the terse (albeit more readable) output of str().
    # * For safety, the pprint.saferepr() function explicitly protected against
    #   recursive data structures *WOULD* typically be preferred to the unsafe
    #   repr() builtin *NOT* protected against such recursion. Sadly,
    #   pprint.saferepr() is extremely unoptimized and thus susceptible to
    #   extreme performance regressions when passed a worst-case object (e.g.,
    #   deeply nested container).
    try:
        obj_repr = repr(obj)
    # If doing so fails with a recursion error, the passed object is recursive.
    # In this case, fallback to recursively introspecting the machine-readable
    # string describing this object. Note that doing so is *EXTREMELY*
    # inefficient and thus performed only as a last-ditch desperate fallback.
    except RecursionError:
        obj_repr = saferepr(obj)

    # If this representation is empty, return empty double-quotes. Although
    # most objects (including outlier singletons like "None" and the empty
    # string) have non-empty representations, caller-defined classes may
    # maliciously override the __repr__() dunder method to return an empty
    # string rather than the representation of an empty string (i.e., '""').
    if not obj_repr:
        return '""'
    # Else, this representation is non-empty.
    #
    # If this representation is neither...
    elif not (
        # Prefixed by punctuation *NOR*...
        obj_repr[0] in CHARS_PUNCTUATION or
        # An instance of a class whose representations do *NOT* benefit from
        # explicit quoting...
        isinstance(obj, _TYPES_UNQUOTABLE)
    ):
    # Then this representation is *NOT* demarcated from preceding characters in
    # the parent string embedding this representation. In this case,
    # double-quote this representation for disambiguity with preceding
    # characters (e.g., sequence indices).
        obj_repr = f'"{obj_repr}"'
    # Else, this representation is either prefixed by punctuation *OR* an
    # instance of a class whose representations do *NOT* benefit from quoting.

    # If this representation exceeds this maximum length...
    if len(obj_repr) > max_len:
        # Avoid circular import dependencies.
        from beartype._util.text.utiltextmunge import truncate_str

        # Truncate this representation to this maximum length.
        obj_repr = truncate_str(text=obj_repr, max_len=max_len)
        # print(f'obj repr truncated: {obj_repr}')
    # Else, this representation is less than or equal to this maximum length.

    # Return this representation.
    return obj_repr

# ....................{ REPRESENTER ~ callable             }....................
def represent_func(
    # Mandatory parameters.
    func: Callable,

    # Optional parameters.
    warning_cls: TypeWarning = _BeartypeUtilCallableWarning,
) -> str:
    '''
    Machine-readable representation of the passed callable.

    Caveats
    -------
    **This function is unavoidably slow and should thus not be called from
    optimized performance-critical code.** This function internally performs
    extremely expensive operations, including abstract syntax tree (AST)-based
    parsing of Python scripts and modules deserialized from disk. Ideally, this
    function should *only* be called to create user-oriented exception messages
    where performance is a negligible concern.

    Parameters
    ----------
    func : Callable
        Callable to be represented.
    warning_cls : TypeWarning, optional
        Type of warning to be emitted in the event of a non-fatal error.
        Defaults to :class:`_BeartypeUtilCallableWarning`.

    Warns
    -----
    :class:`warning_cls`
        If this callable is a pure-Python lambda function whose definition is
        *not* parsable from the script or module defining that lambda.

    Returns
    -------
    str
        Machine-readable representation of that callable.
    '''
    assert callable(func), f'{repr(func)} not callable.'

    # Avoid circular import dependencies.
    from beartype._util.func.utilfunccode import get_func_code_or_none
    from beartype._util.func.utilfunctest import is_func_lambda

    # If that callable is a pure-Python lambda function, return either:
    # * If this lambda is defined by an on-disk script or module source file,
    #   the exact substring of that file defining this lambda.
    # * Else (e.g., if this lambda is dynamically defined in-memory), a
    #   placeholder string.
    if is_func_lambda(func):
        return (
            get_func_code_or_none(func=func, warning_cls=warning_cls) or
            '<lambda>'
        )
    # Else, that callable is *NOT* a pure-Python lambda function.

    #FIXME: Actually, we should be calling a new get_object_name_or_none()
    #function instead -- but that function currently doesn't exist and we're
    #lazy. The issue with get_object_basename_scoped_or_none() is that this
    #getter fails to return the module name of this function. *shrug*
    func_basename_scoped = get_object_basename_scoped_or_none(func)

    # If that callable is named, return this name.
    if func_basename_scoped:
        return func_basename_scoped
    # Else, that callable is unnamed due to failing to define both the
    # "__qualname__" and "__name__" dunder attributes and thus have *NO* names.
    # Although most callables are named, some are not. This includes:
    # * Callable "functools.partial" objects.

    # Return the machine-readable representation of that callable as a fallback.
    return repr(func)

# ....................{ REPRESENTERS ~ pith                }....................
def represent_pith(
    # Mandatory parameters.
    pith: object,

    # Optional parameters.
    is_color: bool = True,
) -> str:
    '''
    Human-readable description of the passed **pith** (i.e., arbitrary object
    violating the current type check) intended to be embedded in an exception
    message explaining this violation.

    Parameters
    ----------
    pith : object
        Arbitrary object violating the current type check.
    is_color : bool, optional
        :data:`True` only if embellishing this label with colour. Defaults to
        :data:`True` for convenience.

    Returns
    -------
    str
        Human-readable description of this object.
    '''

    # Avoid circular import dependencies.
    from beartype._util.text.utiltextlabel import label_pith_value
    from beartype._util.text.utiltextprefix import prefix_pith_type

    # Create and return this representation.
    return (
        f'{prefix_pith_type(pith=pith, is_color=is_color)}'
        f'{label_pith_value(pith=pith, is_color=is_color)}'
    )

# ....................{ PRIVATE ~ globals                  }....................
_TYPES_UNQUOTABLE = (
    # Byte strings, whose representations are already quoted as "b'...'".
    bytes,
    # Numbers, whose representations are guaranteed to both contain *NO*
    # whitespace and be sufficiently terse as to benefit from *NO* quoting.
    NumberType,
)
'''
**Unquotable tuple union** (i.e., isinstancable tuple of all classes such that
the :func:`represent_object` function intentionally avoids double-quoting the
machine-readable representations all instances of these classes, typically due
to these representations either being effectively quoted already *or*
sufficiently terse as to not benefit from being quoted).
'''
