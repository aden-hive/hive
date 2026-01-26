#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **object attribute caching utilities** (i.e., low-level callables
caching :mod:`beartype`-specific attributes describing user-defined
pure-Python functions, classes, and modules, typically by monkey-patching those
attributes directly into those objects).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilCacheObjectAttributeException
from beartype.typing import Dict
from beartype._cave._cavefast import (
    FunctionType,
    ModuleType,
)
from beartype._data.typing.datatyping import TypeException
from beartype._data.kind.datakindiota import SENTINEL
from functools import wraps
from threading import RLock

# ....................{ HINTS                              }....................
# Attribute-cachables are either...
ObjectAttrTypes = (
    # Pure-python functions *AR*...
    FunctionType,
    # Pure-python types *OR*...
    type,
    # Pure-python modules.
    ModuleType,
)
'''
Tuple of the types of all **attribute-cachables** (i.e., objects for which
arbitrary attributes may be safely cached, equivalent to objects accepted by the
:func:`.get_object_attr_cached_or_sentinel` getter and
:func:`.set_object_attr_cached` setter).
'''

# ....................{ GLOBALS                            }....................
OBJECT_ATTR_CACHE_LOCK = RLock()
'''
**Reentrant object attribute cache thread lock** (i.e., low-level thread locking
mechanism implemented as a highly efficient C extension, defined as a global for
reentrant reuse elsewhere as a context manager).

This lock is intentionally public, enabling external callers to synchronize
threading behaviour against the same object attribute caches synchronized by
this lock.

Note that a reentrant :class:`threading.RLock` is required, as higher-level
locked functions (e.g., :func:`.get_object_attr_cached_or_sentinel`) frequently
invoke lower-level locked functions (e.g.,
:func:`.get_type_attr_cached_or_sentinel`).
'''

# ....................{ CLEARERS                           }....................
#FIXME: Unit test us up, please.
def clear_object_attr_caches() -> None:
    '''
    Clear (i.e., empty) *all* private caches internally defined by this
    submodule, enabling callers to reset this submodule to its initial state.
    '''

    # Thread-safely...
    with OBJECT_ATTR_CACHE_LOCK:
        # Clear all private caches defined below.
        _MODULE_NAME_TO_ATTR_NAME_TO_VALUE.clear()

# ....................{ GETTERS                            }....................
#FIXME: Implement us up, please.
#FIXME: Docstring up the "attr_name_*" family of attributes, please.
def get_object_attr_cached_or_sentinel(
    # Mandatory parameters.
    obj: object,
    attr_name_if_obj_function: str,
    attr_name_if_obj_type_or_module: str,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCacheObjectAttributeException,
    exception_prefix: str = '',
) -> object:
    '''
    **Memoized object attribute** (i.e., :mod:`beartype`-specific attribute
    memoizing the prior result of an expensive decision problem unique to the
    passed object) with the passed name previously cached about this object by a
    prior call to the :func:`.set_object_attr_cached` setter passed the same
    name if such a call occurred *or* the sentinel placeholder otherwise (e.g.,
    if no such call occurred).

    This getter is thread-safe with respect to the corresponding
    :func:`.set_object_attr_cached` setter.

    Caveats
    -------
    **This getter does not support arbitrary objects.** For safety, this getter
    *only* supports pure-Python functions, types, and modules. If the passed
    object is *any* type kind of object, this getter raises an exception of the
    passed type.

    Parameters
    ----------
    obj : object
        Object to be inspected.
    attr_name_if_obj_function : str
        Name of the memoized object attribute to be accessed on this object if
        this object is a pure-Python function. To avoid namespace collisions
        with both official dunder attributes (e.g., ``__module__``,
        ``__name__``) *and* third-party attributes also monkey-patched into this
        function, this name should be uniquified with a unique prefix and/or
        suffix (e.g., ``__beartype_attr__``, ``__attr_beartype__``).
    attr_name_if_obj_type_or_module : str
        Name of the memoized object attribute to be accessed on this object if
        this object is either a pure-Python type or module. Since this name is
        only internally used as the key of a private dictionary rather than an
        actual Python attribute, this name need *not* be uniquified with a
        unique prefix and/or suffix.
    exception_cls : TypeException, default: _BeartypeUtilCacheObjectAttributeException
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeUtilCacheObjectAttributeException`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    object
        Either:

        * If a prior call to the :func:`.set_type_attr_cached` setter passed the
          same name previously monkey-patched this memoized type attribute into
          this type, the value of this attribute.
        * Else, the **sentinel placeholder** (i.e., :data:`.SENTINEL`).

    Raises
    ------
    exception_cls
        If this object is neither a pure-Python function, type, nor module.
    '''

    # Thread-safely...
    with OBJECT_ATTR_CACHE_LOCK:
        # Value of the attribute to be returned if previously cached on this
        # object *OR* the sentinel placeholder otherwise.
        attr_value: object = SENTINEL

        # If this object is a pure-Python function...
        #
        # Note that most objects of interest are pure-Python functions. This
        # common case is intentionally detected first as a microoptimization.
        if isinstance(obj, FunctionType):
            assert isinstance(attr_name_if_obj_function, str), (
                f'{repr(attr_name_if_obj_function)} not string.')

            # Value of this attribute if previously monkey-patched into this
            # function *OR* the sentinel placeholder otherwise.
            #
            # Note that attributes are intentionally monkey-patched into
            # functions rather than cached as nested dictionary entries as with
            # modules. Why? Because the latter approach would require each
            # function to have a unique name. You are now thinking: "B-b-but...
            # functions all have unique names! Don't they?" Sadly, the answer
            # is: "Nope." Property getters, setters, and deleters are *ALL*
            # pure-Python functions that share the same names. They're also
            # incredibly common. Because of the mere existence of @property
            # objects, attributes *MUST* instead be monkey-patched directly into
            # functions. Python do be like that.
            attr_value = getattr(obj, attr_name_if_obj_function, SENTINEL)
        # Else, this object is *NOT* a pure-Python function.
        #
        # If this object is a pure-Python type, defer to the lower-level getter
        # specific to types.
        #
        # Note that many objects of interest are pure-Python types. This common
        # case is intentionally detected next as a microoptimization.
        elif isinstance(obj, type):
            attr_value = get_type_attr_cached_or_sentinel(
                obj, attr_name_if_obj_type_or_module)
        # Else, this object is *NOT* a pure-Python type.
        #
        # If this object is a pure-Python module...
        #
        # Note that very few objects of interest are pure-Python modules. This
        # common case is intentionally detected last as a microoptimization.
        elif isinstance(obj, ModuleType):
            assert isinstance(attr_name_if_obj_type_or_module, str), (
                f'{repr(attr_name_if_obj_type_or_module)} not string.')

            # Avoid circular import dependencies.
            from beartype._util.module.utilmodget import get_module_name

            # Fully-qualified name of this module.
            module_name = get_module_name(obj)

            # Nested dictionary mapping from name to value of each previously
            # memoized attribute of this module if any *OR* "None" otherwise.
            attr_name_to_value = (
                _MODULE_NAME_TO_ATTR_NAME_TO_VALUE.get(module_name))

            # If no such nested dictionary exists, fallback to a new empty
            # nested dictionary.
            if not attr_name_to_value:
                attr_name_to_value = (
                    _MODULE_NAME_TO_ATTR_NAME_TO_VALUE[module_name]) = {}
            # Else, this nested dictionary has already been memoized.
            #
            # In either case, this nested dictionary now exists.

            # Value of this attribute if previously cached into this nested
            # dictionary *OR* the sentinel placeholder otherwise.
            attr_value = attr_name_to_value.get(
                attr_name_if_obj_type_or_module, SENTINEL)
        # Since this object is of an unknown type, arbitrary attributes *CANNOT*
        # be safely monkey-patched into this object; likewise, this object has
        # no unique identifier with which to cache arbitrary attributes inside
        # external datastores. This object is *NOT* cacheable. In this case...
        else:
            assert isinstance(exception_cls, type), (
                f'{repr(exception_cls)} not type.')
            assert isinstance(exception_prefix, str), (
                f'{repr(exception_prefix)} not string.')

            # Raise an exception.
            raise exception_cls(
                f'{exception_prefix}object {repr(obj)} neither '
                f'pure-Python function, class, nor module.'
            )

        # Return the value of this attribute.
        return attr_value


#FIXME: Unit test us up, please.
def get_type_attr_cached_or_sentinel(
    # Mandatory parameters.
    cls: type,
    attr_name: str,

    # Optional parameters.
    is_dirty: bool = False,
) -> object:
    '''
    **Memoized type attribute** (i.e., :mod:`beartype`-specific attribute
    memoizing the prior result of an expensive decision problem unique to the
    passed type) with the passed name previously monkey-patched into this type
    by a prior call to the :func:`.set_type_attr_cached` setter passed the same
    name if such a call occurred *or* the sentinel placeholder otherwise (e.g.,
    if no such call occurred).

    This getter is thread-safe with respect to the corresponding
    :func:`.set_type_attr_cached` setter.

    Caveats
    -------
    **Memoized type attributes are only accessible by calling this getter.**
    Memoized type attributes are *not* monkey-patched directly into types.
    Memoized type attributes are only monkey-patched indirectly into types.
    Specifically, the :func:`.set_type_attr_cached` setter monkey-patches
    memoized type attributes into pure-Python ``__sizeof__()`` dunder methods
    monkey-patched into types. Why? Safety. Monkey-patching attributes directly
    into types would conflict with user expectations, which expect class
    dictionaries to remain untrammelled by third-party decorators.

    Parameters
    ----------
    cls : type
        Type to be inspected.
    attr_name : str
        Unqualified basename of the memoized type attribute to be retrieved.
    is_dirty : bool, default: False
        :data:`True` only if the current cache entry for this attribute is
        **dirty** (i.e., stale, desynchronized), in which case this getter
        additionally **invalidates** (i.e., clears, removes) this dirty cache
        entry as a beneficial side-effect. Defaults to :data:`False`.

    Returns
    -------
    object
        Either:

        * If a prior call to the :func:`.set_type_attr_cached` setter passed the
          same name previously monkey-patched this memoized type attribute into
          this type, the value of this attribute.
        * Else, the **sentinel placeholder** (i.e., :data:`.SENTINEL`).
    '''
    assert isinstance(cls, type), f'{repr(cls)} not type.'
    assert isinstance(attr_name, str), f'{repr(attr_name)} not string.'
    assert isinstance(is_dirty, bool), f'{repr(is_dirty)} not boolean.'

    # Thread-safely...
    with OBJECT_ATTR_CACHE_LOCK:
        # __sizeof__() dunder method currently declared by this class, which the
        # set_type_attr_cached() setter has possibly wrapped with a pure-Python
        # __sizeof__() dunder method. Why? Tangential reasons that are obscure,
        # profane, and have *NOTHING* to do with the __sizeof__() dunder method
        # itself. Succinctly, we need a reasonably safe place to persist
        # @beartype-specific attributes pertaining to this class.
        #
        # Clearly, the obvious place would be this class itself. However, doing
        # so would fundamentally modify this class and thus *ALL* instances of
        # this class in an unexpected and thus possibly unsafe manner. Consider
        # common use cases like slots, introspection, pickling, and sizing.
        # Clearly, monkey-patching attributes into class dictionaries without
        # the explicit consent of class designers (i.e., users) is an
        # ill-advised approach.
        #
        # A less obvious but safer place is required. A method of this class
        # would be the ideal candidate; whereas everybody cares about object
        # attributes and thus class dictionaries, nobody cares about method
        # attributes. This is why @beartype safely monkey-patches attributes
        # into @beartype-decorated methods. However, which method? Most methods
        # are *NOT* guaranteed to exist across all possible classes. Adding a
        # new method to this class would be no better than adding a new
        # attribute to this class; both modify class dictionaries. Fortunately,
        # Python currently guarantees *ALL* classes to define at least 24 dunder
        # methods as of Python 3.11. How? Via the root "object" superclass.
        # Unfortunately, *ALL* of these methods are C-based and thus do *NOT*
        # directly support monkey-patching: e.g.,
        #     >>> class AhMahGoddess(object): pass
        #     >>> AhMahGoddess.__init__.__beartyped_cls = AhMahGoddess
        #     AttributeError: 'wrapper_descriptor' object has no attribute
        #     '__beartyped_cls'
        #
        # Fortunately, *ALL* of these methods may be wrapped by pure-Python
        # equivalents whose implementations defer to their original C-based
        # methods. Unfortunately, doing so slightly reduces the efficiency of
        # calling these methods. Fortunately, a subset of these methods are
        # rarely called under production workloads; slightly reducing the
        # efficiency of calling these methods is irrelevant to almost all use
        # cases. Of these, the most obscure, largely useless, poorly documented,
        # and single-use is the __sizeof__() dunder method -- which is only ever
        # called by the sys.getsizeof() utility function, which itself is only
        # ever called manually in a REPL or by third-party object sizing
        # packages. In short, __sizeof__() is perfect.
        cls_sizeof = cls.__sizeof__

        # If this method is *NOT* pure-Python, this method is C-based and thus
        # *CANNOT* possibly have been monkey-patched by a prior call to the
        # set_type_attr_cached() setter, which would have necessarily wrapped
        # this non-monkey-patchable C-based method with a monkey-patchable
        # pure-Python equivalent. In this case, return the sentinel placeholder.
        if not isinstance(cls_sizeof, FunctionType):
            return SENTINEL
        # Else, this method is pure-Python and thus *COULD* possibly have been
        # monkey-patched by a prior call to the set_type_attr_cached() setter.

        # Memoized type attribute cache (i.e., dictionary mapping from each type
        # in a type hierarchy passed to this setter to a nested dictionary
        # mapping from the name to value of each memoized type attribute cached
        # by a call to this setter) if the set_type_attr_cached() setter has
        # already been passed this type at least once *OR* "None" (i.e., if that
        # setter has yet to be passed this type). See that setter for details.
        type_to_attr_name_to_value = getattr(
            cls_sizeof, _TYPE_ATTR_CACHE_NAME, None)

        # If this cache does *NOT* exist, the passed type attribute *CANNOT*
        # possibly have been cached by a prior call to that setter. In this
        # case, return the sentinel placeholder.
        if not type_to_attr_name_to_value:
            return SENTINEL
        # Else, this cache exists. This type attribute *COULD* possibly have
        # been cached by a prior call to that setter.

        # Nested dictionary mapping from the name to value of each memoized type
        # attribute cached for this type by a prior call to that setter if this
        # nested dictionary exists *OR* "None" otherwise.
        attr_name_to_value = type_to_attr_name_to_value.get(cls)

        # If this nested dictionary has yet to be created, the passed type
        # attribute *CANNOT* possibly have been cached by a prior call to that
        # setter. In this case, return the sentinel placeholder.
        if not attr_name_to_value:
            return SENTINEL
        # Else, this nested dictionary. This type attribute *COULD* possibly
        # have been cached by a prior call to that setter.

        # Value of this type attribute cached by a prior call to that setter if
        # any *OR* the sentinel placeholder otherwise.
        attr_value = attr_name_to_value.get(attr_name, SENTINEL)

        # If...
        if (
            # The caller requests this attribute be marked "dirty" and thus
            # removed as an entry of this nested dictionary *AND*...
            is_dirty and
            # This attribute is an entry of this nested dictionary...
            attr_value is not SENTINEL
        ):
            # Remove this entry from this nested dictionary.
            del attr_name_to_value[attr_name]
        # Else, either the caller did not request this attribute to be
        # marked "dirty" *OR* this attribute has not yet been monkey-patched
        # into this function, preserve this attribute as is.

        # Return this value.
        return attr_value

# ....................{ SETTERS                            }....................
#FIXME: Unit test us up, please.
def set_object_attr_cached(
    # Mandatory parameters.
    obj: object,
    attr_name_if_obj_function: str,
    attr_name_if_obj_type_or_module: str,
    attr_value: object,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCacheObjectAttributeException,
    exception_prefix: str = '',
) -> None:
    '''
    Monkey-patch the **memoized type attribute** (i.e., :mod:`beartype`-specific
    attribute memoizing the prior result of an expensive decision problem unique
    to the passed type) with the passed name and value this type.

    This setter is thread-safe with respect to the corresponding
    :func:`.get_object_attr_cached_or_sentinel` getter.

    Caveats
    -------
    **This setter does not support arbitrary objects.** For safety, this setter
    *only* supports pure-Python functions, types, and modules. If the passed
    object is *any* type kind of object, this setter raises an exception of the
    passed type.

    Parameters
    ----------
    cls : type
        Type to be inspected.
    attr_name_if_obj_function : str
        Name of the memoized object attribute to be accessed on this object if
        this object is a pure-Python function. To avoid namespace collisions
        with both official dunder attributes (e.g., ``__module__``,
        ``__name__``) *and* third-party attributes also monkey-patched into this
        function, this name should be uniquified with a unique prefix and/or
        suffix (e.g., ``__beartype_attr__``, ``__attr_beartype__``).
    attr_name_if_obj_type_or_module : str
        Name of the memoized object attribute to be accessed on this object if
        this object is either a pure-Python type or module. Since this name is
        only internally used as the key of a private dictionary rather than an
        actual Python attribute, this name need *not* be uniquified with a
        unique prefix and/or suffix.
    attr_value : object
        New value of this attribute.
    exception_cls : TypeException, default: _BeartypeUtilCacheObjectAttributeException
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeUtilCacheObjectAttributeException`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.
    '''

    # Thread-safely...
    with OBJECT_ATTR_CACHE_LOCK:
        # If this object is a pure-Python function...
        #
        # Note that most objects of interest are pure-Python functions. This
        # common case is intentionally detected first as a microoptimization.
        if isinstance(obj, FunctionType):
            assert isinstance(attr_name_if_obj_function, str), (
                f'{repr(attr_name_if_obj_function)} not string.')

            # Monkey-patch the new value of this attribute into this function.
            setattr(obj, attr_name_if_obj_function, attr_value)
        # Else, this object is *NOT* a pure-Python function.
        #
        # If this object is a pure-Python type, defer to the lower-level getter
        # specific to types.
        #
        # Note that many objects of interest are pure-Python types. This common
        # case is intentionally detected next as a microoptimization.
        elif isinstance(obj, type):
            set_type_attr_cached(
                cls=obj,
                attr_name=attr_name_if_obj_type_or_module,
                attr_value=attr_value,
            )
        # Else, this object is *NOT* a pure-Python type.
        #
        # If this object is a pure-Python module...
        #
        # Note that very few objects of interest are pure-Python modules. This
        # common case is intentionally detected last as a microoptimization.
        elif isinstance(obj, ModuleType):
            assert isinstance(attr_name_if_obj_type_or_module, str), (
                f'{repr(attr_name_if_obj_type_or_module)} not string.')

            # Avoid circular import dependencies.
            from beartype._util.module.utilmodget import get_module_name

            # Fully-qualified name of this module.
            module_name = get_module_name(obj)

            # Nested dictionary mapping from name to value of each previously
            # memoized attribute of this module if any *OR* "None" otherwise.
            attr_name_to_value = (
                _MODULE_NAME_TO_ATTR_NAME_TO_VALUE.get(module_name))

            # If no such nested dictionary exists, fallback to a new empty
            # nested dictionary.
            if not attr_name_to_value:
                attr_name_to_value = (
                    _MODULE_NAME_TO_ATTR_NAME_TO_VALUE[module_name]) = {}
            # Else, this nested dictionary has already been memoized.
            #
            # In either case, this nested dictionary now exists.

            # Cache the new value of this attribute into this nested dictionary.
            attr_name_to_value[attr_name_if_obj_type_or_module] = attr_value
        # Since this object is of an unknown type, arbitrary attributes *CANNOT*
        # be safely monkey-patched into this object; likewise, this object has
        # no unique identifier with which to cache arbitrary attributes inside
        # external datastores. This object is *NOT* cacheable. In this case...
        else:
            assert isinstance(exception_cls, type), (
                f'{repr(exception_cls)} not type.')
            assert isinstance(exception_prefix, str), (
                f'{repr(exception_prefix)} not string.')

            # Raise an exception.
            raise exception_cls(
                f'{exception_prefix}object {repr(obj)} neither '
                f'pure-Python function, class, nor module.'
            )


#FIXME: Unit test us up, please.
def set_type_attr_cached(
    cls: type, attr_name: str, attr_value: object) -> None:
    '''
    Monkey-patch the **memoized type attribute** (i.e., :mod:`beartype`-specific
    attribute memoizing the prior result of an expensive decision problem unique
    to the passed type) with the passed name and value this type.

    This setter is thread-safe with respect to the corresponding
    :func:`.get_type_attr_cached_or_sentinel` getter.

    Caveats
    -------
    **Memoized type attributes are only mutatable by calling this setter.**
    Memoized type attributes are *not* monkey-patched directly into types.
    Memoized type attributes are only monkey-patched indirectly into types.
    Specifically, this setter monkey-patches memoized type attributes into
    pure-Python ``__sizeof__()`` dunder methods monkey-patched into types. Why?
    Safety. Monkey-patching attributes directly into types would conflict with
    user expectations, which expect class dictionaries to remain untrammelled by
    third-party decorators like :mod:`beartype`.

    Parameters
    ----------
    cls : type
        Type to be inspected.
    attr_name : str
        Unqualified basename of the memoized type attribute to be mutated.
    attr_value : object
        New value of this attribute.
    '''
    assert isinstance(cls, type), f'{repr(cls)} not type.'
    assert isinstance(attr_name, str), f'{repr(attr_name)} not string.'

    # Thread-safely...
    with OBJECT_ATTR_CACHE_LOCK:
        # __sizeof__() dunder method currently declared by this class. See the
        # get_type_attr_cached_or_sentinel() getter for details.
        cls_sizeof_old = cls.__sizeof__

        # If this method is already pure-Python, this method is already
        # monkey-patchable. In this case, monkey-patch this method directly.
        if isinstance(cls_sizeof_old, FunctionType):
            cls_sizeof = cls_sizeof_old  # pyright: ignore
        # Else, this method is *NOT* pure-Python, implying this method is
        # C-based and *NOT* monkey-patchable. In this case...
        else:
            # Avoid circular import dependencies.
            from beartype._util.cls.utilclsset import set_type_attr

            # New pure-Python __sizeof__() dunder method wrapping the original
            # C-based __sizeof__() dunder method declared by this class.
            @wraps(cls_sizeof_old)
            def cls_sizeof(self) -> int:
                return cls_sizeof_old(self)  # type: ignore[call-arg]

            # Replace the original C-based __sizeof__() dunder method with this
            # wrapper. For safety, we intentionally call our high-level
            # set_type_attr() setter rather than attempting to directly set this
            # attribute. The latter approach succeeds for standard pure-Python
            # mutable classes but catastrophically fails for non-standard
            # C-based immutable classes (e.g., "enum.Enum" subclasses).
            set_type_attr(cls, '__sizeof__', cls_sizeof)
        # Else, this method is already pure-Python.
        #
        # In any case, this method is now pure-Python and thus monkey-patchable.

        # Memoized type attribute cache (i.e., dictionary mapping from each type
        # in a type hierarchy passed to this setter to a nested dictionary
        # mapping from the name to value of each memoized type attribute cached
        # by a call to this setter) if this setter has already been passed this
        # type at least once *OR* "None" (i.e., if this setter has yet to be
        # passed this type).
        #
        # Ideally, this dictionary would *NOT* be required. Instead, this setter
        # would simply monkey-patch memoized type attributes directly into this
        # pure-Python __sizeof__() dunder method. Indeed, that overly simplistic
        # approach *DOES* work for a subset of cases: namely, if this type has
        # *NO* subclasses that are also passed to this setter. But if this type
        # his a subclass that is also passed to this setter, that approach would
        # cache the incorrect values. Why? Because subclasses of this type
        # inherit this pure-Python __sizeof__() dunder method and thus *ALL*
        # attributes monkey-patched by this setter into that method: e.g.,
        #     >>> class Superclass(): pass
        #     >>> def patch_sizeof(cls):
        #     ...     sizeof_old = cls.__sizeof__
        #     ...     def sizeof_new(self):
        #     ...         return sizeof_old(self)
        #     ...     cls.__sizeof__ = sizeof_new
        #     >>> Superclass.__sizeof__
        #     <method '__sizeof__' of 'object' objects>
        #     >>> patch_sizeof(Superclass)
        #     >>> Superclass.__sizeof__
        #     <function patch_sizeof.<locals>.sizeof_new at 0x7f1981393110>
        #
        #     >>> class Subclass(Superclass): pass
        #     >>> Subclass.__sizeof__
        #     <function patch_sizeof.<locals>.sizeof_new at 0x7f1981393110>
        #
        # Cache entries *MUST* thus be uniquified across type hierarchies.
        type_to_attr_name_to_value = getattr(
            cls_sizeof, _TYPE_ATTR_CACHE_NAME, None)

        # If *NO* memoized type attribute cache has been monkey-patched into
        # this pure-Python __sizeof__() dunder method yet, do so.
        if type_to_attr_name_to_value is None:
            type_to_attr_name_to_value = cls_sizeof._TYPE_ATTR_CACHE_NAME = {}  # type: ignore[attr-defined]
        # Else, a memoized type attribute cache has already been monkey-patched
        # into this pure-Python __sizeof__() dunder method.
        #
        # In either case, this cache now exists.

        # Nested dictionary mapping from the name to value of each memoized type
        # attribute cached for this type by a prior call to this setter if this
        # nested dictionary exists *OR* "None" otherwise.
        attr_name_to_value = type_to_attr_name_to_value.get(cls)

        # If this nested dictionary has yet to be created, do so.
        if attr_name_to_value is None:
            attr_name_to_value = type_to_attr_name_to_value[cls] = {}
        # Else, this nested dictionary has already been created.
        #
        # In either case, this nested dictionary now exists.

        # Cache this memoized type attribute into this nested dictionary. Phew!
        attr_name_to_value[attr_name] = attr_value  # type: ignore[index, assignment]

# ....................{ PRIVATE ~ globals                  }....................
_MODULE_NAME_TO_ATTR_NAME_TO_VALUE: Dict[str, Dict[str, object]] = {}
'''
Dictionary mapping from the fully-qualified name of each module associated with
one or more memoized module attributes to a nested dictionary mapping from the
name to value of each such attribute.
'''


_TYPE_ATTR_CACHE_NAME = '__beartype_type_attr_cache'
'''
Arbitrary :mod:`beartype`-specific name of the **memoized type attribute cache**
(i.e., dictionary mapping from each type in a type hierarchy passed to the
:func:`set_type_attr_cached` setter to a nested dictionary mapping from the name
to value of each memoized type attribute cached by a prior call to that setter)
monkey-patched into types passed to that setter.
'''
