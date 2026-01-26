#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`328`-compliant **relative module name utilities** (i.e.,
low-level callables pertaining to :pep:`328`-compliant ``"."``-prefixed relative
module names).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilModulePep328Exception
from beartype._data.typing.datatyping import (
    ListStrs,
    TypeException,
)

# ....................{ CANONICALIZERS                     }....................
def canonicalize_pep328_module_name_relative(
    # Mandatory parameters.
    module_name_relative: str,
    module_basenames_absolute: ListStrs,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilModulePep328Exception,
    exception_prefix: str = 'Module attribute ',
) -> str:
    '''
    Canonicalize (i.e., convert from relative to absolute) the passed
    :pep:`328`-compliant **relative module name** (i.e., partially-qualified
    module name prefixed by one or more ``"."`` delimiters) relative to the
    passed list of unqualified basenames comprising the fully-qualified name of
    the **parent package** (i.e., transitively containing that relative module).

    Parameters
    ----------
    module_name_relative : str
        Partially-qualified relative module name to be canonicalized into a
        fully-qualified absolute module name.
    module_basenames_absolute : list[str]
        List of the unqualified basenames comprising the fully-qualified name of
        the originating module to which this relative module is relative.
    exception_cls : type[Exception], default: _BeartypeUtilModulePep328Exception
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeUtilModulePep328Exception`.
    exception_prefix : str, default: "Module attribute "
        Human-readable substring prefixing raised exception messages. Defaults
        to a reasonably sensible prefix.

    Returns
    -------
    str
        Fully-qualified absolute module name canonicalized from this
        partially-qualified relative module name.

    Raises
    ------
    exception_cls
        If that module name is *not* prefixed by one or more ``"."`` delimiters
        and thus is neither relative nor :pep:`328`-compliant.
    '''
    assert isinstance(module_name_relative, str), (
        f'{repr(module_name_relative)} not string.')
    assert isinstance(module_basenames_absolute, list), (
        f'{repr(module_basenames_absolute)} not list of strings.')

    # ....................{ LOCALS                         }....................
    # The passed relative module name stripped of *ALL* prefixing "." delimiters
    # (e.g., from "..subpackage.submodule" to merely "subpackage.submodule").
    module_name_relative_stripped = module_name_relative.lstrip('.')

    # ....................{ LOCALS ~ length                }....................
    # Number of characters in this relative module name.
    module_name_relative_len = len(module_name_relative)

    # Number of "." delimiters prefixing this relative module name.
    module_name_relative_prefix_len = (
        module_name_relative_len - len(module_name_relative_stripped))

    # If this relative module name is prefixed by *NO* "." delimiters, this
    # module name is neither relative nor PEP 328-compliant. In this case...
    if not module_name_relative_prefix_len:
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not exception type.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise an exception.
        raise exception_cls(
            f'{exception_prefix}'
            f'PEP 328 relative module name "{module_name_relative}" '
            f'prefixed by no "." delimiters and thus '
            f'neither relative nor PEP 328-compliant.'
        )
    # Else, this relative module name is prefixed by one or more "." delimiters.

    # ....................{ LOCALS ~ slice                 }....................
    # Slice of unqualified basenames comprising the fully-qualified name of the
    # parent (sub)package to which this relative module name is relative.
    # Happily, the negative 0-based index of one after the last unqualified
    # basename of the passed list of unqualified basenames comprising the
    # fully-qualified name of the originating module such that the slice
    # "module_basenames_absolute[:module_basenames_absolute_index_last]" yields
    # the proper subset of unqualified basenames comprising the fully-qualified
    # name of the parent (sub)package to which this relative module name is
    # relative is *EXACTLY* the negation of the number of "." delimiters
    # prefixing this relative module name. Praise Guido! \o/
    module_basenames_absolute_sliced = module_basenames_absolute[
        :-module_name_relative_prefix_len]

    # Fully-qualified name of the parent (sub)package to which this relative
    # module name is relative.
    module_name_absolute_prefix = '.'.join(module_basenames_absolute_sliced)
    # print(f'module_name_absolute_prefix: {module_name_absolute_prefix}')
    # print(f'module_name_relative_stripped: {module_name_relative_stripped}')

    # Fully-qualified name of this relative module name.
    module_name = (
        f'{module_name_absolute_prefix}.{module_name_relative_stripped}'
        if module_name_relative_stripped else
        module_name_absolute_prefix
    )

    # ....................{ RETURN                         }....................
    # Return this name.
    return module_name
