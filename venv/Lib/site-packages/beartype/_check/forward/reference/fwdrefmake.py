#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **forward reference factories** (i.e.,  low-level callables creating
and returning forward reference proxy subclasses deferring the resolution of a
stringified type hint referencing an attribute that has yet to be defined and
annotating a class or callable decorated by the :func:`beartype.beartype`
decorator).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintForwardRefException
from beartype.typing import (
    Dict,
    Optional,
    Type,
)
from beartype._cave._cavemap import NoneTypeOr
from beartype._data.typing.datatyping import (
    BeartypeForwardRef,
    BeartypeForwardRefArgs,
    TupleTypes,
)
from beartype._check.forward.reference.fwdrefabc import (
    _BeartypeForwardRefIndexableABC,
    _BeartypeForwardRefIndexableABC_BASES,
)
from beartype._util.cls.utilclsmake import make_type
from beartype._util.text.utiltextidentifier import die_unless_identifier

# ....................{ FACTORIES                          }....................
def make_forwardref_indexable_subtype(
    scope_name: Optional[str],
    hint_name: str,
) -> Type[_BeartypeForwardRefIndexableABC]:
    '''
    Create and return a new **subscriptable forward reference subclass** (i.e.,
    concrete subclass of the :class:`._BeartypeForwardRefIndexableABC` abstract
    base class (ABC) deferring the resolution of the unresolved type hint with
    the passed name, transparently permitting this type hint to be subscripted
    by any arbitrary positional and keyword parameters).

    This factory is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the lower-level private
    :func:`._make_forwardref_subtype` factory called by this higher-level public
    factory is itself memoized.

    Parameters
    ----------
    scope_name : Optional[str]
        Possibly ignored lexical scope name. Specifically:

        * If ``hint_name`` is absolute (i.e., contains one or more ``.``
          delimiters), this parameter is silently ignored in favour of the
          fully-qualified name of the module prefixing ``hint_name``.
        * If ``hint_name`` is relative (i.e., contains *no* ``.`` delimiters),
          this parameter declares the absolute (i.e., fully-qualified) name of
          the lexical scope to which this unresolved type hint is relative.

        The fully-qualified name of the module prefixing ``hint_name`` (if any)
        thus *always* takes precedence over this lexical scope name, which only
        provides a fallback to resolve relative forward references. While
        unintuitive, this is needed to resolve absolute forward references.
    hint_name : str
        Relative (i.e., unqualified) or absolute (i.e., fully-qualified) name of
        this unresolved type hint to be referenced.

    Returns
    -------
    Type[_BeartypeForwardRefIndexableABC]
        Subscriptable forward reference subclass referencing this type hint.

    Raises
    ------
    BeartypeDecorHintForwardRefException
        If either:

        * ``hint_name`` is *not* a syntactically valid Python identifier.
        * ``scope_name`` is neither:

          * A syntactically valid Python identifier.
          * :data:`None`.
    '''

    # Subscriptable forward reference to be returned.
    return _make_forwardref_subtype(  # type: ignore[return-value]
        scope_name=scope_name,
        hint_name=hint_name,
        type_bases=_BeartypeForwardRefIndexableABC_BASES,
    )

# ....................{ PRIVATE ~ factories                }....................
def _make_forwardref_subtype(
    scope_name: Optional[str],
    hint_name: str,
    type_bases: TupleTypes,
) -> BeartypeForwardRef:
    '''
    Create and return a new **forward reference subclass** (i.e., concrete
    subclass of the passed abstract base class (ABC) deferring the resolution of
    the type hint with the passed name transparently).

    This factory is internally memoized for efficiency.

    Parameters
    ----------
    scope_name : Optional[str]
        Possibly ignored lexical scope name. See
        :func:`.make_forwardref_indexable_subtype` for further details.
    hint_name : str
        Absolute (i.e., fully-qualified) or relative (i.e., unqualified) name of
        the type hint referenced by this forward reference subclass.
    type_bases : Tuple[type, ...]
        Tuple of all base classes to be inherited by this forward reference
        subclass. For simplicity, this *must* be a 1-tuple ``(type_base,)``
        where ``type_base`` is a :class:`._BeartypeForwardRefIndexableABC`
        subclass.

    Returns
    -------
    BeartypeForwardRef
        Forward reference subclass referencing this type hint.

    Raises
    ------
    BeartypeDecorHintForwardRefException
        If either:

        * ``hint_name`` is *not* a syntactically valid Python identifier.
        * ``scope_name`` is neither:

          * A syntactically valid Python identifier.
          * :data:`None`.
    '''

    # Tuple of all passed parameters (in arbitrary order).
    args: BeartypeForwardRefArgs = (scope_name, hint_name, type_bases)

    # Forward reference proxy previously created and returned by a prior call to
    # this function passed these parameters if any *OR* "None" otherwise (i.e.,
    # if this is the first call to this function passed these parameters).
    # forwardref_subtype: Optional[BeartypeForwardRef] = (
    forwardref_subtype = _forwardref_args_to_forwardref.get(args, None)

    # If this proxy has already been created, reuse and return this proxy as is.
    if forwardref_subtype is not None:
        return forwardref_subtype
    # Else, this proxy has yet to be created.

    assert isinstance(scope_name, NoneTypeOr[str]), (
        f'{repr(scope_name)} neither string nor "None".')
    assert isinstance(hint_name, str), f'{repr(hint_name)} not string.'
    assert len(type_bases) == 1, (
        f'{repr(type_bases)} not 1-tuple of a single superclass.')

    # If this attribute name is *NOT* a syntactically valid Python identifier,
    # raise an exception.
    die_unless_identifier(
        text=hint_name,
        exception_cls=BeartypeDecorHintForwardRefException,
        exception_prefix='Forward reference ',
    )
    # Else, this attribute name is a syntactically valid Python identifier.

    # Possibly empty fully-qualified module name and unqualified basename of the
    # type referred to by this forward reference.
    type_module_name, _, type_name = hint_name.rpartition('.')

    # If this module name is empty, fallback to the passed module name if any.
    #
    # Note that we intentionally perform *NO* additional validation. Why?
    # Builtin types. Notably, it is valid to pass an unqualified "hint_name"
    # and a "scope_name" that is "None" only if "hint_name" is the name of a
    # builtin type (e.g., "int", "str"). Since validating this edge case is
    # non-trivial, we defer this validation to subsequent importation logic.
    if not type_module_name:
        type_module_name = scope_name
    # Else, this module name is non-empty.

    # Forward reference proxy to be returned.
    forwardref_subtype = make_type(
        type_name=type_name,
        type_module_name=type_module_name,
        type_bases=type_bases,
        exception_cls=BeartypeDecorHintForwardRefException,
        exception_prefix='Forward reference ',
    )

    # Classify passed parameters with this proxy.
    forwardref_subtype.__name_beartype__ = hint_name  # pyright: ignore
    forwardref_subtype.__scope_name_beartype__ = scope_name  # pyright: ignore

    # Cache this proxy for reuse by subsequent calls to this factory function
    # passed the same parameters.
    _forwardref_args_to_forwardref[args] = forwardref_subtype

    # Return this proxy.
    return forwardref_subtype

# ....................{ PRIVATE ~ globals                  }....................
_forwardref_args_to_forwardref: Dict[
    BeartypeForwardRefArgs, BeartypeForwardRef] = {}
'''
**Forward reference proxy cache** (i.e., dictionary mapping from the tuple of
all parameters passed to each prior call of the
:func:`._make_forwardref_subtype` factory function to the forward reference
proxy dynamically created and returned by that call).

This cache serves a dual purpose. Notably, this cache both enables:

* External callers to iterate over all previously instantiated forward reference
  proxies. This is particularly useful when responding to module reloading,
  which requires that *all* previously cached types be uncached.
* :func:`._make_forwardref_subtype` to internally memoize itself over its
  passed parameters. Since the existing ``callable_cached`` decorator could
  trivially do so as well, however, this is only a negligible side effect.
'''
