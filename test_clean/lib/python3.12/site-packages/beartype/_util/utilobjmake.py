#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **object factory utilities** (i.e., low-level callables
instantiating arbitrary objects in a general-purpose manner).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilTypeException
from beartype.typing import Optional
from beartype._cave._cavemap import NoneTypeOr
from beartype._data.typing.datatyping import (
    T,
    FrozenSetStrs,
    LexicalScope,
    TypeException,
)
from beartype._data.kind.datakindiota import SENTINEL

# ....................{ PERMUTERS                          }....................
#FIXME: Unit test us up, please.
def permute_object(
    # Mandatory parameters.
    obj: T,
    init_arg_name_to_value: LexicalScope,
    init_arg_names: FrozenSetStrs,

    # Optional parameters.
    copy_var_names: Optional[FrozenSetStrs] = None,
    exception_cls: TypeException = _BeartypeUtilTypeException,
) -> T:
    '''
    Shallow copy of the passed object such that each passed keyword parameter
    overwrites an instance variable of the same name in this copy.

    This function effectively offers an intelligent alternative to the standard
    brute-force :func:`copy.copy` function, which lacks support for parameter
    permutation.

    Caveats
    -------
    **This function intentionally modifies the passed**
    ``init_arg_name_to_value`` **dictionary for efficiency.** Notably, this
    function "fills in" all missing parameters of that dictionary. For the name
    of each **missing parameter** (i.e., name in the passed ``copy_var_names``
    set but *not* in the passed ``init_arg_name_to_value`` dictionary), this
    function adds a new key-value pair to the passed ``init_arg_name_to_value``
    dictionary mapping from this name to the current value of an instance
    variable of the same name on this object.

    Parameters
    ----------
    obj : T
        Object to be permuted.
    init_arg_name_to_value : LexicalScope
        Dictionary mapping from the name to value of each:

        * Parameter to be passed to the ``__init__`` method of the type of the
          passed object.
        * Corresponding instance variable of the passed object.
    init_arg_names : FrozenSetStrs
        Frozen set of the names of *all* parameters accepted by the ``__init__``
        method of the type of the passed object.
    copy_var_names : Optional[FrozenSetStrs], default: None
        Frozen set of the names of *all* instance variables of the passed object
        whose values will be copied as the default values of all **unpassed
        parameters** (i.e., parameters in the passed ``init_arg_names`` set but
        *not* in the passed ``init_arg_name_to_value`` dictionary), defined as
        either:

        * If this set differs from that of ``init_arg_names``, this set. It is
          the caller's responsibility to ensure that **unpassed undefaulted
          parameters** (i.e., parameters neither in this ``copy_var_names`` set
          *nor* the passed ``init_arg_name_to_value`` dictionary) are declared
          as optional by the ``__init__`` method of the type of the passed
          object, which is then responsible for defaulting these parameters.
        * If these two sets are equal, :data:`None`. In this case, this
          parameter defaults to the passed ``init_arg_names`` set.

        Defaults to :data:`None` and thus ``init_arg_names``.
    exception_cls : TypeException, optional
        Type of exception to raise in the event of a fatal error. Defaults to
        :exc:`._BeartypeUtilTypeException`.

    Returns
    -------
    T
        Shallow copy of this object such that each keyword parameter overwrites
        the instance variable of the same name in this copy.

    Raises
    ------
    exception_cls
        If the name of any passed keyword parameter is either:

        * *Not* that of a parameter accepted by the :meth:`init` method of the
          type of this object.
        * *Not* that of an existing instance variable of this object.

    Examples
    --------
    .. code-block:: pycon

       >>> from beartype._util.utilobjmake import permute_object

       >>> sleuth = ViolationCause(
       ...     pith=[42,]
       ...     hint=typing.List[int],
       ...     cause_indent='',
       ...     exception_prefix='List of integers',
       ... )
       >>> sleuth_copy = permute_object(
       ...     obj=sleuth,
       ...     init_arg_name_to_value=dict(pith=[24,]),
       ...     init_arg_names=frozenset((
       ...         'hint', 'pith', 'cause_indent', 'exception_prefix',)),
       ... )

       >>> sleuth_copy.pith
       [24,]
       >>> sleuth_copy.hint
       typing.List[int]
    '''
    assert isinstance(init_arg_name_to_value, dict), (
        f'{repr(init_arg_name_to_value)} not dictionary.')
    assert isinstance(init_arg_names, frozenset), (
        f'{repr(init_arg_names)} not frozen set.')
    assert isinstance(copy_var_names, NoneTypeOr[frozenset]), (
        f'{repr(copy_var_names)} neither frozen set nor "None".')
    assert isinstance(exception_cls, type), (
        f'{repr(exception_cls)} not exception type.')

    # ....................{ LOCALS                         }....................
    # Type of this object.
    cls = obj.__class__

    # If the caller passed *NO* frozen set of the names of instance variables of
    # this object whose values will be copied as the default values of all
    # unpassed parameters, default this to the frozen set of the names of all
    # parameters accepted by the __init__() method of the type of this object.
    if copy_var_names is None:
        copy_var_names = init_arg_names
    # Else, the caller passed this frozen set. Preserve this set as is.

    # ....................{ VALIDATE                       }....................
    # For the name of each passed keyword parameter...
    for init_arg_name in init_arg_name_to_value:
        # If this name is *NOT* that of a parameter accepted by the __init__()
        # method of this type, raise an exception.
        if init_arg_name not in init_arg_names:
            raise exception_cls(
                f'{cls}.__init__() parameter "{init_arg_name}" unrecognized.')
        # Else, this name is that of a parameter accepted by that method.

    # ....................{ DEFAULT                        }....................
    # For the name of each instance variable of this object to be passed as the
    # default value of the unpassed parameter of the same name accepted by that
    # method...
    for copy_var_name in copy_var_names:
        # If this name is *NOT* that of a parameter accepted by the __init__()
        # method of this type, raise an exception.
        if copy_var_name not in init_arg_names:
            raise exception_cls(
                f'{cls}.__init__() parameter "{copy_var_name}" unrecognized.')
        # Else, this name is that of a parameter accepted by that method.

        # If this parameter was *NOT* explicitly passed by the caller...
        if copy_var_name not in init_arg_name_to_value:
            # Current value of this parameter as an instance variable of this
            # object if this object defines this variable *OR* the sentinel
            # placeholder otherwise.
            copy_var_value = getattr(obj, copy_var_name, SENTINEL)

            # If the current value of this parameter is *NOT* the sentinel
            # placeholder, this object defines this variable. In this case...
            if copy_var_value is not SENTINEL:
                # Default this parameter to its current value from this object.
                init_arg_name_to_value[copy_var_name] = copy_var_value
            # Else, this object fails to define this variable. In this case,
            # assume this parameter to be optional and thus safely undefinable.
        # Else, this parameter was explicitly passed by the caller. In this
        # case, preserve this parameter as is.

    # ....................{ RETURN                         }....................
    # New instance of this class initialized with these parameter.
    object_permuted = cls(**init_arg_name_to_value)

    # Return this instance.
    return object_permuted
