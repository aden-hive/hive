#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`557`-compliant **testers** (i.e., low-level callables testing
various properties of dataclasses standardized by :pep:`557`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep557Exception
from beartype._data.typing.datatyping import (
    TypeException,
)
from dataclasses import (  # type: ignore[attr-defined]
    # Public attributes of the "dataclasses" module.
    is_dataclass,

    # Private attributes of the "dataclasses" module. Although non-ideal, the
    # extreme non-triviality of this module leaves us little choice. *shrug*
    _PARAMS,  # pyright: ignore
)

# ....................{ RAISERS                            }....................
def die_unless_type_pep557_dataclass(
    # Mandatory parameters.
    cls: type,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep557Exception,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception of the passed type unless the passed class is a
    **dataclass** (i.e., :pep:`557`-compliant class decorated by the standard
    :func:`dataclasses.dataclass` decorator).

    Parameters
    ----------
    cls : type
        Class to be inspected.
    exception_cls : TypeException, default: BeartypeDecorHintPep557Exception
        Type of exception to be raised.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exceptions messages.

    Raises
    ------
    BeartypeDecorHintPep557Exception
        If this class is *not* a :pep:`557`-compliant dataclass.
    '''

    # If this class is *NOT* a PEP 557-compliant dataclass...
    if not is_type_pep557_dataclass(
        cls=cls,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    ):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not exception type.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise an exception.
        raise exception_cls(
            f'{exception_prefix}class {repr(cls)} not PEP 557 dataclass '
            f'(i.e., not decorated by @dataclasses.dataclass decorator).'
        )

# ....................{ TESTERS                            }....................
def is_type_pep557_dataclass(
    # Mandatory parameters.
    cls: type,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep557Exception,
    exception_prefix: str = '',
) -> bool:
    '''
    :data:`True` only if the passed class is a **dataclass** (i.e.,
    :pep:`557`-compliant class decorated by the standard
    :func:`dataclasses.dataclass` decorator).

    This tester is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    cls : type
        Class to be inspected.
    exception_cls : TypeException, default: BeartypeDecorHintPep557Exception
        Type of exception to be raised.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exceptions messages.

    Returns
    -------
    bool
        :data:`True` only if this class is a dataclass.

    Raises
    ------
    exception_cls
        If this object is *not* a class.
    '''

    # Avoid circular import dependencies.
    from beartype._util.cls.utilclstest import die_unless_type

    # If this object is *NOT* a type, raise an exception.
    die_unless_type(
        cls=cls,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this object is a type.

    # Return true only if this type is a dataclass.
    #
    # Note that the is_dataclass() tester was intentionally implemented
    # ambiguously to return true for both actual dataclasses *AND*
    # instances of dataclasses. Since the prior validation omits the
    # latter, this call unambiguously returns true *ONLY* if this object is
    # an actual dataclass. (Dodged a misfired bullet there, folks.)
    return is_dataclass(cls)


def is_pep557_dataclass_frozen(
    # Mandatory parameters.
    datacls: type,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep557Exception,
    exception_prefix: str = '',
) -> bool:
    '''
    :data:`True` only if the passed **dataclass** (i.e.,
    :pep:`557`-compliant :func:`dataclasses.dataclass`-decorated class) is
    **frozen** (i.e., immutable due to being passed the ``frozen=True`` keyword
    parameter at decoration time).

    This tester is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    datacls: type
        Dataclass to be inspected.
    exception_cls : TypeException, default: BeartypeDecorHintPep557Exception
        Type of exception to be raised.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exceptions messages.

    Returns
    -------
    bool
        :data:`True` only if this class is a dataclass.

    Raises
    ------
    exception_cls
        If this dataclass is *not* actually a dataclass.
    '''

    # Object encapsulating all keyword parameters configuring this dataclass.
    dataclass_kwargs = get_pep557_dataclass_kwargs(
        datacls=datacls,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # Return true only if this dataclass was configured to be frozen.
    return dataclass_kwargs.frozen  # type: ignore[attr-defined]

# ....................{ GETTERS                            }....................
def get_pep557_dataclass_kwargs(
    # Mandatory parameters.
    datacls: type,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep557Exception,
    exception_prefix: str = '',
) -> object:
    '''
    Object encapsulating all keyword parameter originally passed to the
    :pep:`557`-compliant :func:`dataclasses.dataclass` decorator decorating the
    passed dataclass.

    For each keyword parameter accepted by the :func:`dataclasses.dataclass`
    decorator, the object returned by this getter defines an instance variable
    of the same name whose value is the value either explicitly passed *or*
    implicitly defaulting to that keyword parameter.

    Caveats
    -------
    **The type of the object returned by this getter is private.** Callers
    should *not* rely on this type, which is likely to change between between
    Python versions.

    **The type of the object returned by this getter is currently just a thin
    wrapper.** This type fails to define any meaningful API apart from public
    instance variables encapsulating these keyword parameters. In particular,
    this type fails to override the ``__eq__()`` or ``__hash__()`` dunder
    methods. Sadly, this directly implies that:

    * **Objects returned by this getter cannot be meaningfully compared.**
    * **Objects returned by this getter cannot be meaningfully added to
      containers dependent on sane hashability** (e.g., dictionaries, sets).

    In short, this getter sucks. Avoid doing *anything* with the object returned
    by this getter except directly accessing their public instance variables.

    Parameters
    ----------
    datacls: type
        Dataclass to be inspected.
    exception_cls : TypeException, default: BeartypeDecorHintPep557Exception
        Type of exception to be raised.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exceptions messages.

    Returns
    -------
    Object
        Object encapsulating all keyword arguments originally configuring this
        dataclass.

    Raises
    ------
    exception_cls
        If this dataclass is *not* actually a dataclass.
    '''

    # If this dataclass is *NOT* actually a dataclass, raise an exception.
    die_unless_type_pep557_dataclass(
        cls=datacls,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this dataclass is actually a dataclass.

    # Dictionary of all keyword arguments originally passed to @dataclass.
    dataclass_kwargs = getattr(datacls, _PARAMS)

    # Return this dictionary.
    return dataclass_kwargs
