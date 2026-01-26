#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **PEP-noncompliant type hint reducers** (i.e., low-level callables
converting higher-level type hints that do *not* comply with any specific PEP
but are nonetheless shallowly supported by :mod:`beartype` to lower-level type
hints more readily consumable by :mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._check.metadata.hint.hintsane import HINT_SANE_IGNORABLE
from beartype._data.typing.datatypingport import Hint
from beartype._util.hint.utilhinttest import die_unless_hint

# ....................{ REDUCERS                           }....................
def reduce_hint_nonpep_type(hint: Hint, exception_prefix: str) -> Hint:
    '''
    Reduce the passed **PEP-noncompliant type hint** (i.e., type hint identified
    by *no* sign, typically but *not* necessarily implying this hint to be an
    isinstanceable type) if this hint satisfies various conditions to another
    possibly PEP-compliant type hint.

    Specifically, if this hint is either:

    * A valid PEP-noncompliant isinstanceable type, this reducer preserves this
      type as is.
    * A valid PEP-compliant hint unrecognized by beartype, this reducer raises
      a :exc:`.BeartypeDecorHintPepUnsupportedException` exception.
    * An invalid and thus PEP-noncompliant hint, this reducer raises an
      :exc:`.BeartypeDecorHintNonpepException` exception.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation trivially reduces to a
    one-liner.

    Parameters
    ----------
    hint : Hint
        PEP-noncompliant hint to be reduced.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    Returns
    -------
    Hint
        Either:

        * If this hint is the root :class:`object` superclass, the ignorable
          :data:`.HINT_SANE_IGNORABLE` singleton. :class:`object` is the transitive
          superclass of all classes. Attributes annotated as :class:`object`
          unconditionally match *all* objects under :func:`isinstance`-based
          type covariance and thus semantically reduce to unannotated attributes
          -- which is to say, they are ignorable.
        * Else, this PEP-noncompliant hint unmodified.

    Raises
    ------
    BeartypeDecorHintPepUnsupportedException
        If this object is a PEP-compliant type hint currently unsupported by
        the :func:`beartype.beartype` decorator.
    BeartypeDecorHintNonpepException
        If this object is neither a:

        * Supported PEP-compliant type hint.
        * Supported PEP-noncompliant type hint.
    '''

    # If this hint is unsupported by @beartype, raise an exception.
    die_unless_hint(hint=hint, exception_prefix=exception_prefix)
    # Else, this hint is supported by @beartype.

    # If this hint is the root "object" superclass, reduce this type to the
    # ignorable ".HINT_SANE_IGNORABLE" singleton.
    if hint is object:
        return HINT_SANE_IGNORABLE
    # Else, this hint is *NOT* the root "object" superclass.

    # Return this hint as is unmodified, which then halts reduction. By
    # definition, PEP-noncompliant hints are irreducible. If this hint was
    # instead reducible, the get_hint_pep_sign_or_none() getter called by the
    # parent _reduce_hint_cached() function would have instead returned a unique
    # sign identifying this hint (rather than "None").
    return hint
