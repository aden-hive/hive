#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **Python module importer** utilities (i.e., callables dynamically
importing modules and/or attributes from modules).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeModuleUnimportableWarning
from beartype.roar._roarexc import _BeartypeUtilModuleException
from beartype.typing import (
    Any,
    Optional,
)
from beartype._cave._cavefast import ModuleType
from beartype._cave._cavemap import NoneTypeOr
from beartype._data.cls.datacls import TYPE_BUILTIN_NAME_TO_TYPE
from beartype._data.typing.datatyping import TypeException
from beartype._util.error.utilerrwarn import issue_warning
from beartype._util.text.utiltextidentifier import die_unless_identifier
from beartype._data.kind.datakindiota import SENTINEL
from importlib import import_module as importlib_import_module

# ....................{ IMPORTERS                          }....................
#FIXME: Preserved until requisite, which shouldn't be long.
#FIXME: Unit test us up, please.
# def import_module(
#     # Mandatory parameters.
#     module_name: str,
#
#     # Optional parameters.
#     exception_cls: TypeException = _BeartypeUtilModuleException,
# ) -> ModuleType:
#     '''
#     Dynamically import and return the module, package, or C extension with the
#     passed fully-qualified name if importable *or* raise an exception
#     otherwise (i.e., if that module, package, or C extension is unimportable).
#
#     Parameters
#     ----------
#     module_name : str
#         Fully-qualified name of the module to be imported.
#     exception_cls : type
#         Type of exception to be raised by this function. Defaults to
#         :class:`_BeartypeUtilModuleException`.
#
#     Raises
#     ----------
#     exception_cls
#         If no module with this name exists.
#     Exception
#         If a module with this name exists *but* that module is unimportable
#         due to raising module-scoped exceptions at importation time. Since
#         modules may perform arbitrary Turing-complete logic at module scope,
#         callers should be prepared to handle *any* possible exception.
#     '''
#     assert isinstance(exception_cls, type), (
#         f'{repr(exception_cls)} not type.')
#
#     # Module with this name if this module is importable *OR* "None" otherwise.
#     module = import_module_or_none(module_name)
#
#     # If this module is unimportable, raise an exception.
#     if module is None:
#         raise exception_cls(
#             f'Module "{module_name}" not found.') from exception
#     # Else, this module is importable.
#
#     # Return this module.
#     return module


def import_module_or_none(
    # Mandatory parameters.
    module_name: str,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilModuleException,
    exception_prefix: str = 'Module attribute ',
) -> Optional[ModuleType]:
    '''
    Dynamically import and return the module, package, or C extension with the
    passed fully-qualified name if importable *or* return :data:`None` otherwise
    (i.e., if that module, package, or C extension is unimportable).

    For safety, this function also emits a non-fatal warning when that module,
    package, or C extension exists but is still unimportable (e.g., due to
    raising an exception at module scope).

    Parameters
    ----------
    module_name : str
        Fully-qualified name of the module to be imported.
    exception_cls : type[Exception], default: _BeartypeUtilModuleException
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeUtilModuleException`.
    exception_prefix : str, default: "Module attribute "
        Human-readable substring prefixing raised exception messages. Defaults
        to a reasonably sensible prefix.

    Returns
    -------
    Either:

    * If a module, package, or C extension with this fully-qualified name is
      importable, that module, package, or C extension.
    * Else, :data:`None`.

    Raises
    ------
    exception_cls
        If this name is *not* a syntactically valid Python identifier.

    Warns
    -----
    BeartypeModuleUnimportableWarning
        If a module with this name exists *but* that module is unimportable due
        to raising module-scoped exceptions at importation time.
    '''

    # Avoid circular import dependencies.
    from beartype._util.module.utilmodget import get_module_imported_or_none

    # If this module name is *NOT* a syntactically valid Python identifier,
    # raise an exception.
    die_unless_identifier(
        text=module_name,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this module name is a syntactically valid Python identifier.

    # Module cached with "sys.modules" if this module has already been imported
    # elsewhere under the active Python interpreter *OR* "None" otherwise.
    module = get_module_imported_or_none(module_name)

    # If this module has already been imported, return this cached module.
    if module is not None:
        return module
    # Else, this module has yet to be imported.

    # Attempt to dynamically import and return this module.
    try:
        return importlib_import_module(module_name)
    # If this module does *NOT* exist, return "None".
    except ModuleNotFoundError:
        pass
    # If this module exists but raises unexpected exceptions from module scope,
    # first emit a non-fatal warning notifying the user and then return "None".
    except Exception as exception:
        issue_warning(
            cls=BeartypeModuleUnimportableWarning,
            message=(
                f'Ignoring module "{module_name}" importation exception:\n'
                f'    {exception.__class__.__name__}: {exception}'
            ),
        )

    # Inform the caller that this module is unimportable.
    return None

# ....................{ IMPORTERS ~ attr                   }....................
def import_module_attr(
    # Mandatory parameters.
    attr_name: str,

    # Optional parameters.
    module_name: Optional[str] = None,
    exception_cls: TypeException = _BeartypeUtilModuleException,
    exception_prefix: str = 'Module attribute ',
) -> Any:
    '''
    Dynamically import and return the **module attribute** (i.e., object
    declared at module scope) with the passed possibly unqualified name from
    the module with the passed fully-qualified name if importable *or* raise an
    exception otherwise.

    Parameters
    ----------
    attr_name : str
        Possibly unqualified name of the module attribute to be imported.
    module_name: Optional[str]
        Either:

        * If this attribute name is unqualified (i.e., contains *no* ``.``
          delimiters), the fully-qualified name of the module declaring this
          attribute.
        * Else, this parameter is silently ignored.

        Defaults to :data:`None`, in which case this attribute name must be
        either fully-qualified *or* the unqualified name of a builtin type.
    exception_cls : Type[Exception]
        Type of exception to be raised by this function. Defaults to
        :class:`._BeartypeUtilModuleException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    object
        The module attribute with this fully-qualified name.

    Raises
    ------
    exception_cls
        If either:

        * This attribute or module name is syntactically invalid.
        * *No* module with this name exists.
        * A module with by this name exists *but* that module declares no
          attribute by this name.

    Warns
    -----
    BeartypeModuleUnimportableWarning
        If a module prefixed by this name exists *but* that module is
        unimportable due to module-scoped side effects at importation time.

    See Also
    --------
    :func:`.import_module_attr_or_sentinel`
        Further commentary.
    '''

    # Attribute with this name dynamically imported from that module if
    # importable *OR* the sentinel placeholder otherwise (i.e., if this
    # attribute is unimportable).
    module_attr = import_module_attr_or_sentinel(
        attr_name=attr_name,
        module_name=module_name,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # If this attribute is unimportable...
    if module_attr is SENTINEL:
        assert isinstance(exception_cls, type), f'{exception_cls} not type.'
        assert isinstance(exception_prefix, str), (
            f'{exception_prefix} not string.')

        # Avoid circular import dependencies.
        from beartype._util.module.utilmodtest import is_module

        # Exception message to be raised.
        exception_message = f'{exception_prefix}"{attr_name}" unimportable'

        # If this attribute name contains *NO* "." characters, this is an
        # unqualified basename. In this case...
        if '.' not in attr_name:
            # If either no module name was passed *OR* only an empty module name
            # was passed, then an empty module name was passed *AND* this
            # attribute contains no "." characters. Ergo, this is an unqualified
            # basename. Moreover, since the above importation failed, this
            # attribute is *NOT* the name of a builtin type. Explain this edge
            # case with an appropriate substring.
            if not module_name:
                exception_message += (
                    ', as:\n'
                    '* Not relative to a package or module '
                    '(i.e., contains no "." delimiters).\n'
                    '* Not the name of a builtin type (e.g., "int", "str").'
                )
            # Else, a non-empty module name was passed.
            #
            # If this module is importable, append an appropriate substring.
            elif is_module(module_name):
                exception_message += f' from module "{module_name}".'
            # Else, this module is unimportable. Append an appropriate
            # substring.
            else:
                exception_message += (
                    f' from unimportable module "{module_name}".')
        # Else, this attribute name contains one or more "." characters. In
        # this case...
        else:
            # Fully-qualified name of the module declaring this attribute.
            module_name, _, _ = attr_name.rpartition('.')

            # If this module is importable, append an appropriate substring.
            if is_module(module_name):
                exception_message += '.'
            # Else, this module is unimportable. Append an appropriate
            # substring.
            else:
                exception_message += (
                    f' from unimportable module "{module_name}".')

        # Raise this exception.
        raise exception_cls(exception_message)
    # Else, this module declares this attribute.

    # Else, return this attribute.
    return module_attr


#FIXME: Fix up all tests of this function, please.
def import_module_attr_or_sentinel(
    # Mandatory parameters.
    attr_name: str,

    # Optional parameters.
    module_name: Optional[str] = None,
    exception_cls: TypeException = _BeartypeUtilModuleException,
    exception_prefix: str = 'Module attribute ',
) -> Any:
    '''
    Dynamically import and return the **module attribute** (i.e., object
    declared at module scope) with the passed possibly unqualified name from
    the module with the passed fully-qualified name if importable *or* the
    placeholder :data:`.SENTINEL` otherwise.

    This importer expects this attribute name to be either:

    * **Fully-qualified** (i.e., contain one or more ``.`` delimiters), in which
      case this module name is silently ignored and may thus be :data:`None` or
      the empty string *or*...
    * **Unqualified** (i.e., contain *no* ``.`` delimiters), in which case
      either:

      * This module name *must* be a non-empty string *or*...
      * This unqualified attribute name *must* be that of a **builtin type**
        (e.g., ``"int"``, ``"str"``).

    Parameters
    ----------
    attr_name : str
        Possibly unqualified name of the module attribute to be imported.
    module_name: Optional[str]
        Either:

        * If this attribute name is unqualified (i.e., contains *no* ``.``
          delimiters), the fully-qualified name of the module declaring this
          attribute.
        * Else, this parameter is silently ignored.

        Defaults to :data:`None`, in which case ``attr_name`` must be either
        fully-qualified *or* the unqualified name of a builtin type.
    exception_cls : Type[Exception]
        Type of exception to be raised by this function. Defaults to
        :class:`._BeartypeUtilModuleException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    object
        Either:

        * If *no* module with this name exists, :data:`.SENTINEL`.
        * If a module with by this name exists *but* that module declares no
          attribute by this name, :data:`.SENTINEL`.
        * Else, the module attribute with this fully-qualified name.

    Raises
    ------
    exception_cls
        If this name is syntactically invalid.

    Warns
    -----
    BeartypeModuleUnimportableWarning
        If a module prefixed by this name exists *but* that module is
        unimportable due to module-scoped side effects at importation time.
    '''
    assert isinstance(module_name, NoneTypeOr[str]), (
        f'{repr(module_name)} neither string nor "None".')

    # If this attribute name is *NOT* a syntactically valid Python identifier,
    # raise an exception.
    die_unless_identifier(
        text=attr_name,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this attribute name is a syntactically valid Python identifier.

    # True only if this attribute name contains *NO* "." characters and is thus
    # an unqualified basename relative to this module name.
    is_attr_name_unqualified = '.' not in attr_name

    # Unqualified basename of this attribute, defaulting to this attribute name.
    attr_basename = attr_name

    # If this attribute name is an unqualified basename...
    if is_attr_name_unqualified:
        # If either no module name was passed *OR* only an empty module name was
        # passed...
        if not module_name:
            # Builtin type with this name if any *OR* the sentinel otherwise
            # (i.e., if *NO* builtin type with this name exists).
            module_attr = TYPE_BUILTIN_NAME_TO_TYPE.get(attr_name, SENTINEL)

            # Return this object.
            return module_attr
        # Else, a non-empty module name was passed.
    # Else, this attribute name contains one or more "." characters.
    else:
        # Fully-qualified name of the module declaring this attribute *AND* the
        # unqualified basename of this attribute relative to this module,
        # efficiently split from the passed name.
        #
        # Note that:
        # * This silently overrides the passed module name with the module name
        #   prefixing the name of this attribute, which is presumed to be
        #   authoritative. The passed module name is only an optional fallback
        #   in the event that this attribute name contains *NO* "." characters.
        # * By the prior validation, this split is guaranteed to be safe.
        module_name, _, attr_basename = attr_name.rpartition('.')
    # In any case:
    # * "module_name" is now a non-empty string.
    # * "attr_basename" is now an unqualified basename.

    # Module with this fully-qualified name if importable *OR* "None" otherwise.
    module = import_module_or_none(module_name)

    # If that module is unimportable, return "None".
    if module is None:
        return SENTINEL
    # Else, that module is importable.

    # Attribute with this name if that module declares this attribute *OR* the
    # sentinel otherwise.
    module_attr = getattr(module, attr_basename, SENTINEL)

    # If...
    if (
        # That module does not declare this attribute *AND*...
        module_attr is SENTINEL and
        # This attribute name is an unqualified basename...
        is_attr_name_unqualified
    # Then this attribute was imported relative to this module. In this case,
    # this attribute could still be the name of a builtin type.
    ):
        # Builtin type with this name if any *OR* the sentinel otherwise
        # (i.e., if *NO* builtin type with this name exists).
        #
        # Note that this edge case is distinct from the prior edge case and thus
        # *MUST* be handled distinctly. Why? Because this module *COULD* have
        # globally overridden a builtin type by declaring a global attribute of
        # the same name. Although extremely unlikely (and strongly frowned
        # upon), Python *DOES* permit insanity like:
        #     # In some user-defined module at global scope...
        #     class int(object): ...  # <-- by all the gods never do this
        module_attr = TYPE_BUILTIN_NAME_TO_TYPE.get(attr_basename, SENTINEL)
        # print(f'Attempting to import "{attr_basename}" as builtin type {repr(module_attr)}...')
        # print(f'TYPE_BUILTIN_NAME_TO_TYPE: {TYPE_BUILTIN_NAME_TO_TYPE}')
    # Else, either that module declared this attribute *OR* this attribute name
    # is fully-qualified and thus not the name of a builtin type. In either
    # case, return this attribute as is.

    # Return this attribute.
    return module_attr


def import_module_attr_or_none(*args, **kwargs) -> Any:
    '''
    Dynamically import and return the **module attribute** (i.e., object
    declared at module scope) with the passed fully-qualified name if importable
    *or* :data:`None` otherwise.

    Caveats
    -------
    **This importer ambiguously returns false negatives in edge cases and is
    thus mildly unsafe.** Consider calling the unambiguous
    :func:`.import_module_attr_or_sentinel` importer instead. Why? Because this
    importer returns :data:`None` both when this attribute is unimportable *and*
    when this attribute is importable but has a value of :data:`None`.
    Nonetheless, this importer remains convenient for various use cases in which
    this distinction is mostly irrelevant.

    Parameters
    ----------
    All parameters are passed as is to the lower-level
    :func:`.import_module_attr_or_sentinel` importer.

    Returns
    -------
    object
        Either:

        * If *no* module prefixed this name exists, :data:`None`.
        * If a module prefixed by this name exists *but* that module declares
          no attribute by this name, :data:`None`.
        * Else, the module attribute with this fully-qualified name.

    Raises
    ------
    exception_cls
        If this name is syntactically invalid.

    Warns
    -----
    BeartypeModuleUnimportableWarning
        If a module prefixed by this name exists *but* that module is
        unimportable due to module-scoped side effects at importation time.
    '''

    # Module attribute with this name if that module declares this attribute
    # *OR* the sentinel placeholder otherwise.
    module_attr = import_module_attr_or_sentinel(*args, **kwargs)

    # Return either this attribute if importable *OR* "None" otherwise.
    return module_attr if module_attr is not SENTINEL else None
