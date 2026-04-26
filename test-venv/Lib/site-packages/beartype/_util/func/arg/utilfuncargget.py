#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **callable parameter getter utilities** (i.e., low-level functions
introspecting metadata on various kinds of parameters accepted by arbitrary
callables).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilCallableException
from beartype.typing import (
    Optional,
    Tuple,
)
from beartype._data.typing.datatyping import (
    Codeobjable,
    TypeException,
)
from beartype._util.func.arg.utilfuncargiter import (
    ARG_META_INDEX_KIND,
    ArgKind,
    ArgMeta,
    iter_func_args,
)
from beartype._util.func.arg.utilfuncarglen import get_func_args_len
from beartype._util.func.utilfunccodeobj import get_func_codeobj

# ....................{ GETTERS ~ meta                     }....................
#FIXME: [SPEED] Consider refactoring this O(n) iteration into an O(1) lookup.
#Although extremely non-trivial, doing so *SHOULD* be feasible based on the
#current internal implementation of the iter_func_args() generator
#comprehension. Basically, we'll need to:
#* Augment get_func_args_lens() to additionally cache and return *ALL* of
#  the remaining "sub-lengths" internally computed by iter_func_args().
#  *ALL*. And there are quite a few, indeed.
#* Call get_func_args_lens() here.
#* Get the name of the variadic positional parameter by simply indexing:
#      func_args_len = get_func_args_len(*args, **kwargs)
#      func_codeobj.co_varnames[func_args_len + hur_der_hur_something]
#  ...where "hur_der_hur_something" is the index of the variadic positional
#  parameter in the "co_varnames" list, computed by adding all requisite
#  "sub-lengths" together. We shrug.
#FIXME: Unit test us up, please.
def get_func_arg_meta_variadic_positional_or_none(
    *args, **kwargs) -> Optional[ArgMeta]:
    '''
    Callable parameter metadata describing the variadic positional parameter
    accepted by the passed pure-Python callable if that callable accepts a
    variadic positional parameter *or* :data:`None` otherwise (i.e., if that
    callable accepts no variadic positional parameter).

    Caveats
    -------
    **This getter exhibits worst-case linear-time complexity** :math:`O(n)`
    **for** :math:`O(n)` **the total number of parameters accepted by that
    callable** due to unavoidably performing a linear search for a variadic
    positional parameter with this name is this callable's parameter list. This
    getter should thus be called sparingly.

    Parameters
    ----------
    All remaining parameters are passed as is to the lower-level
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj` getter.

    Returns
    -------
    Optional[ArgMeta]
        Either:

        * If that callable accepts a variadic positional parameter, callable
          parameter metadata describing that parameter.
        * Else, :data:`None`.

    Raises
    ------
    exception_cls
         If the passed callable is *not* pure-Python.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.arg.utilfuncargtest import (
        is_func_arg_variadic_positional)

    # If the passed callable accepts *NO* variadic positional parameter,
    # silently reduce to a noop.
    if not is_func_arg_variadic_positional(*args, **kwargs):
        return None
    # Else, that callable accepts a variadic positional parameter.

    # For metadata describing each parameter accepted by that callable...
    for arg_meta in iter_func_args(*args, **kwargs):
        # If this is a variadic positional parameter, return this metadata.
        if arg_meta[ARG_META_INDEX_KIND] is ArgKind.VARIADIC_POSITIONAL:
            return arg_meta
        # Else, this is *NOT* a variadic positional parameter. In this case,
        # silently continue to the next parameter.
    # Else, that callable accepts *NO* variadic positional parameter. But, by
    # the above validation, that callable accepts a variadic positional
    # parameter! We are now off the deep end.

    # Raise an exception as a last-ditch fallback.
    #
    # Note that this should *NEVER* occur. Naturally, this just occurred.
    raise _BeartypeUtilCallableException(  # pragma: no cover
        f'Callable inexplicably accepts no variadic positional parameter '
        f'despite claiming to do so:\n\t{repr(args)}\n\t{repr(kwargs)}'
    )


#FIXME: Unit test us up, please.
def get_func_arg_meta_variadic_keyword_or_none(
    *args, **kwargs) -> Optional[ArgMeta]:
    '''
    Callable parameter metadata describing the variadic keyword parameter
    accepted by the passed pure-Python callable if that callable accepts a
    variadic keyword parameter *or* :data:`None` otherwise (i.e., if that
    callable accepts no variadic keyword parameter).

    Caveats
    -------
    **This getter exhibits worst-case linear-time complexity** :math:`O(n)`
    **for** :math:`O(n)` **the total number of parameters accepted by that
    callable** due to unavoidably performing a linear search for a variadic
    keyword parameter with this name is this callable's parameter list. This
    getter should thus be called sparingly.

    Parameters
    ----------
    All remaining parameters are passed as is to the lower-level
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj` getter.

    Returns
    -------
    Optional[ArgMeta]
        Either:

        * If that callable accepts a variadic keyword parameter, callable
          parameter metadata describing that parameter.
        * Else, :data:`None`.

    Raises
    ------
    exception_cls
         If the passed callable is *not* pure-Python.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.arg.utilfuncargtest import (
        is_func_arg_variadic_keyword)

    # If the passed callable accepts *NO* variadic keyword parameter,
    # silently reduce to a noop.
    if not is_func_arg_variadic_keyword(*args, **kwargs):
        return None
    # Else, that callable accepts a variadic keyword parameter.

    # For metadata describing each parameter accepted by that callable...
    for arg_meta in iter_func_args(*args, **kwargs):
        # If this is a variadic keyword parameter, return this metadata.
        if arg_meta[ARG_META_INDEX_KIND] is ArgKind.VARIADIC_KEYWORD:
            return arg_meta
        # Else, this is *NOT* a variadic keyword parameter. In this case,
        # silently continue to the next parameter.
    # Else, that callable accepts *NO* variadic keyword parameter. But, by
    # the above validation, that callable accepts a variadic keyword
    # parameter! We are now off the deep end.

    # Raise an exception as a last-ditch fallback.
    #
    # Note that this should *NEVER* occur. Naturally, this just occurred.
    raise _BeartypeUtilCallableException(  # pragma: no cover
        f'Callable inexplicably accepts no variadic keyword parameter '
        f'despite claiming to do so:\n\t{repr(args)}\n\t{repr(kwargs)}'
    )

# ....................{ GETTERS ~ name                     }....................
def get_func_arg_name_first_or_none(*args, **kwargs) -> Optional[str]:
    '''
    Name of the first parameter listed in the signature of the passed
    pure-Python callable if any *or* :data:`None` otherwise (i.e., if that
    callable accepts *no* parameters and is thus parameter-less).

    Parameters
    ----------
    All arguments are passed as is to the lower-level
    :func:`.get_func_arg_names` getter.

    Returns
    -------
    Optional[str]
        Either:

        * If that callable accepts one or more parameters, the name of the first
          parameter listed in the signature of that callable.
        * Else, :data:`None`.

    Raises
    ------
    exception_cls
         If that callable is *not* pure-Python.
    '''

    # Tuple of the names of all parameters accepted by the passed callable.
    func_arg_names = get_func_arg_names(*args, **kwargs)

    # Return either...
    return (
        # If that callable accepts one or more parameters, the name of the first
        # parameter accepted by that callable;
        func_arg_names[0]
        if func_arg_names else
        # Else, that callable accepts *NO* parameters. In this case, "None".
        None
    )


def get_func_arg_names(
    # Mandatory parameters.
    func: Codeobjable,

    # Optional parameters.
    is_omit_boundmethod_arg_first: bool = True,
    is_unwrap: bool = True,
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> Tuple[str, ...]:
    '''
    Tuple of the names of all parameters accepted by the passed pure-Python
    callable.

    Ideally, this getter would have returned a set rather than a tuple. Sadly,
    sets *still* fail to guarantee insertion order despite comparable
    dictionaries doing so. A tuple is the next-best-thing. It is what it is.

    Caveats
    -------
    **Order is insignificant.** Ideally, this getter would return parameter
    names in the same order as the original callable signature declared those
    parameters. While feasible, doing so would require manual iteration over
    parameters exhibiting :math:`O(n)` time complexity. Instead, this getter
    performs a trivial slicing the ``co_varnames`` instance variable of the code
    object of that callable exhibiting :math:`O(1)` time complexity. Although
    extremely fast, doing so has the minor disadvantage of returning parameter
    names in an occasionally unexpected order. The sole exception to this rule
    is the first parameter name returned by this getter, which is guaranteed to
    be the first parameter declared by that callable.

    Parameters
    ----------
    func : Codeobjable
        Pure-Python callable, frame, or code object to be inspected.
    is_omit_boundmethod_arg_first : bool, optional
        :data:`True` only if this getter implicitly omits the first mandatory
        flexible parameter accepted by that callable if that callable is a
        C-based bound method descriptor encapsulating either an instance method
        bound to an instance of a class *or* a class method bound to a class.
        Defaults to :data:`True`, instructing this getter to transparently yield
        the *actual* high-level parameters accepted by this bound method
        descriptor (rather than the low-level parameters accepted by the unbound
        method encapsulated by this bound method descriptor). While the default
        behaviour is typically desirable, valid use cases for the non-default
        behaviour do exist (e.g., crudely detecting the kind of that based on
        whether the unbound method encapsulated by this bound method descriptor
        accepts a first parameter named ``cls`` or ``self``).

        The default behaviour enables:

        * This getter to transparently support bound method descriptors, which
          then enables...
        * The private :func:`beartype._decor._nontype.decornontype.beartype_pseudofunc`
          decorator to type-check the bound ``__call__()`` method descriptor
          encapsulating the unbound ``__call__()`` dunder method defined on the
          class of pseudo-callable objects, which then enables...
        * The public :func:`beartype.beartype` decorator to type-check
          pseudo-callable objects.

        How? In this case, the aforementioned ``beartype_pseudofunc``
        decorator wraps this bound method descriptor with a dynamically
        generated wrapper function that does *not* accept a ``self`` or ``cls``
        parameter, since a bound method does *not* accept a ``self`` or ``cls``
        parameter. After all, that's why bound methods exist; they implicitly
        pass the instance or class to which they are bound as the value of the
        ``self`` or ``cls`` parameter to the unbound method they encapsulate.
        However, the code object of a bound method descriptor is only an alias
        to the code object of the corresponding unbound method. Since the latter
        accepts a ``self`` parameter, so too does the former.

        The default behaviour resolves this internal discrepancy (contradiction)
        that arises between:

        * The code object of a bound method descriptor, which declares that
          callable object to accept a ``self`` parameter.
        * The real-world calling semantics of a bound method descriptor, which
          by definition accepts *no* ``self`` parameter.
    is_unwrap: bool, optional
        :data:`True` only if this getter implicitly calls the
        :func:`beartype._util.func.utilfuncwrap.unwrap_func_all` function.
        Defaults to :data:`True` for safety. See :func:`.get_func_codeobj` for
        further commentary.
    exception_cls : type, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :class:`._BeartypeUtilCallableException`.
    exception_prefix : str, optional
        Human-readable label prefixing the message of any exception raised in
        the event of a fatal error. Defaults to the empty string.

    Returns
    -------
    Tuple[str, ...]
        Tuple of the names of all parameters accepted by that callable.

    Raises
    ------
    exception_cls
         If the passed callable is *not* pure-Python.
    '''
    assert isinstance(is_omit_boundmethod_arg_first, bool), (
        f'{repr(is_omit_boundmethod_arg_first)} not boolean.')

    # Avoid circular import dependencies.
    from beartype._util.func.utilfunctest import is_func_boundmethod

    # Code object underlying the passed callable if any *OR* "None" otherwise
    # (i.e., that callable has *NO* code object).
    func_codeobj = get_func_codeobj(
        func=func,
        is_unwrap=is_unwrap,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # Total number of parameters accepted by that callable.
    func_args_len = get_func_args_len(
        func=func_codeobj,
        is_unwrap=False,  # <-- "func" was already unwrapped above. I sigh.
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # Tuple of the names of all parameters accepted by the passed callable.
    func_arg_names = func_codeobj.co_varnames[:func_args_len]  # <-- BOOM

    # If...
    if (
        # If that callable accepts one or more parameters *AND*...
        func_arg_names and
        # Omitting the first mandatory flexible parameter accepted by that
        # callable if that callable is a C-based bound method descriptor
        # encapsulating either an instance method bound to an instance of a
        # class or a class method bound to a class *AND*...
        is_omit_boundmethod_arg_first and
        # That callable is such a C-based bound method descriptor...
        is_func_boundmethod(func)
    ):
        # Omit the first parameter accepted by that bound method descriptor.
        #
        # Note that that callable is guaranteed to accept at least one
        # parameter, due to being a bound method descriptor.
        func_arg_names = func_arg_names[1:]

    # Return this tuple.
    return func_arg_names
