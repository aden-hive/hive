#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **beartype blacklist utilities** (i.e., low-level callables
detecting whether passed objects are blacklisted and thus ignorable with respect
to :mod:`beartype`-specific type-checking, typically due to residing in
third-party packages or modules well-known to be hostile to runtime
type-checking and thus :mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.conf.dataconfblack import (
    BLACKLIST_MODULE_NAME_TO_TYPE_NAMES,
    BLACKLIST_PACKAGE_NAMES,
    BLACKLIST_TYPE_MRO_ROOT_MODULE_NAME_TO_TYPE_NAMES,
)
from beartype._util.cache.utilcachecall import callable_cached

# ....................{ TESTERS ~ object                   }....................
@callable_cached
def is_object_blacklisted(obj: object) -> bool:
    '''
    :data:`True` only if the passed object (e.g., callable, class) is
    **beartype-blacklisted** (i.e., resides in a third-party package or modules
    well-known to be hostile to runtime type-checking and thus :mod:`beartype`).

    This tester is memoized for efficiency.

    Parameters
    ----------
    obj : object
        Arbitrary object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is beartype-blacklisted.

    See Also
    --------
    :data:`.BLACKLIST_PACKAGE_NAMES`
        Detailed discussion of beartype-blacklisting.
    '''

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._util.module.utilmodget import get_object_module_name_or_none

    # ....................{ PHASES                         }....................
    # This tester is internally implemented as a series of sequential phases --
    # each increasingly more time- and/or space-complex than the last and thus
    # intentionally ordered from least to most complex.

    # ....................{ PHASE ~ type -> module         }....................
    # In this early phase, we efficiently test whether the combination of the
    # fully-qualified name of the module defining the type of the passed object
    # *AND* the unqualified basename of that type is known to be blacklisted.

    # Type of this object.
    obj_type = obj.__class__

    # Fully-qualified name of the package or module defining this object's type
    # if any *OR* "None" otherwise (e.g., if this type is defined in-memory).
    obj_type_module_name = get_object_module_name_or_none(obj_type)

    # If this type defines *NO* module name, this type is *NOT* blacklisted.
    # Why? Because the only types that @beartype blacklists are all defined in
    # modules that physically exist and thus have names. But this type has *NO*
    # module name! In this case, silently reduce to a noop.
    if not obj_type_module_name:
        # print(f'Ignoring unmoduled object {repr(obj)}!')
        return False
    # Else, this type defines this name.

    #FIXME: [SPEED] Globalize the dict.get() bound method called here. *shrug*
    # Frozen set of the unqualified basenames of all beartype-blacklisted types
    # defined by that package or module if any *OR* "None" otherwise (if that
    # package or module defines *NO* beartype-blacklisted types).
    blacklist_obj_type_names = BLACKLIST_MODULE_NAME_TO_TYPE_NAMES.get(
        obj_type_module_name)
    # print(f'obj: {obj}')
    # print(f'obj_type_module_name: {obj_type_module_name}')
    # print(f'blacklist_obj_type_names: {blacklist_obj_type_names}')

    # If...
    if (
        # That package or module defines beartype-blacklisted types *AND*...
        blacklist_obj_type_names and
        # The unqualified basename of this object's type is blacklisted...
        obj_type.__name__ in blacklist_obj_type_names
    ):
        # print(f'Object {obj} blacklisted via "type -> module" heuristic!')

        # Then immediately return true.
        return True
    # Else, this object's type is *NOT* beartype-blacklisted. However, this
    # object could still be beartype-blacklisted in some way. Continue testing!

    # ....................{ PHASE ~ type -> mro -> module  }....................
    # In this early phase, we efficiently test whether the combination of the
    # fully-qualified name of the module defining the type of the passed object
    # *AND* the unqualified basename of that type is known to be blacklisted
    # such that that type masquerades as the low-level user-defined callable it
    # wraps and is thus *ONLY* accessible as the root method-resolution order
    # (MRO) item (i.e., second-to-last item of the "__mro__" dunder dictionary
    # of this type, thus ignoring the ignorable "object" guaranteed to be the
    # last item of all such dictionaries).
    #
    # @beartype doesn't make the rules. It only complains about and breaks them.

    # MRO of this type.
    #
    # Note that all types are guaranteed to have a root MRO item *EXCEPT* the
    # "object" superclass, whose simplistic "(object,)" MRO lacks a root item.
    # While we could manually exclude this superclass, the existence of even a
    # single exception to this guarantee suggests that devious users could
    # circumvent this guarantee... somehow. Users are devious. Who can fathom
    # their ways? For safety, we assume this guarantee to *NOT* globally hold.
    obj_type_mro = obj_type.__mro__

    # If this MRO contains two or more items, this type is *NOT* the trivial
    # "object" superclass or something like that superclass. In this case...
    if len(obj_type_mro) >= 2:
        # Root MRO item of this type, ignoring the trivial "object" superclass.
        obj_type_mro_root = obj_type_mro[-2]

        # Fully-qualified name of the package or module defining this object's
        # root MRO type if any *OR* "None" otherwise (e.g., if this type is
        # defined in-memory).
        obj_type_mro_root_module_name = get_object_module_name_or_none(
            obj_type_mro_root)

        # If this type defines this name...
        if obj_type_mro_root_module_name:
            #FIXME: [SPEED] Globalize the dict.get() bound method called here.
            # Frozen set of the unqualified basenames of all
            # beartype-blacklisted types defined by that package or module if
            # any *OR* "None" otherwise (if that package or module defines *NO*
            # beartype-blacklisted types).
            blacklist_obj_type_mro_root_type_names = (
                BLACKLIST_TYPE_MRO_ROOT_MODULE_NAME_TO_TYPE_NAMES.get(
                    obj_type_mro_root_module_name))
            # print(f'obj: {obj}')
            # print(f'obj_type_mro_root_module_name: {obj_type_mro_root_module_name}')
            # print(f'blacklist_obj_type_mro_root_type_names: {blacklist_obj_type_mro_root_type_names}')

            # If...
            if (
                # That package or module defines beartype-blacklisted types
                # *AND*...
                blacklist_obj_type_mro_root_type_names and
                # The unqualified basename of this object's type is
                # blacklisted...
                obj_type_mro_root.__name__ in (
                    blacklist_obj_type_mro_root_type_names)
            ):
                # print(f'Object {obj} blacklisted via "type -> mro -> module" heuristic!')

                # Then immediately return true.
                return True
            # Else, this object's type is *NOT* beartype-blacklisted. However,
            # this object could still be beartype-blacklisted in some way.
            # Continue testing!
        # Else, this type defines *NO* module name. This object's type is *NOT*
        # beartype-blacklisted. However, this object could still be
        # beartype-blacklisted in some way. Continue testing!
    # Else, this type is the trivial "object" superclass or something like that
    # superclass.

    # ....................{ PHASE ~ package                }....................
    # In this late phase, we inefficiently test whether the combination of the
    # fully-qualified name of the top-level root package directly defining the
    # passed object is known to be blacklisted. This heuristic is less
    # efficient, as stripping this package name from this module name
    # constitutes a string-munging operation.

    # Fully-qualified name of the package or module defining this object if any
    # *OR* "None" otherwise (e.g., if this object is defined in-memory).
    obj_module_name = get_object_module_name_or_none(obj)

    # If this object defines *NO* module name, silently reduce to a noop.
    if not obj_module_name:
        # print(f'Ignoring unmoduled object {repr(obj)}!')
        return False
    # Else, this object defines this name and is thus *PROBABLY* either a
    # pure-Python class or callable.

    # Fully-qualified name of the top-level root package or module transitively
    # containing that package or module (e.g., "some_package" when
    # "obj_module_name" is "some_package.some_module.some_submodule").
    #
    # Note this has been profiled to be the fastest one-liner for parsing the
    # first "."-suffixed substring from a "."-delimited string.
    obj_package_name = obj_module_name.partition('.')[0]
    # print(f'Testing package {repr(obj_package_name)} for blacklisting...')

    # If this package is globally beartype-blacklisted, immediately return true.
    if obj_package_name in BLACKLIST_PACKAGE_NAMES:
        return True
    # Else, this package is *NOT* globally beartype-blacklisted. However, this
    # object could still be specifically beartype-blacklisted. Continue testing!

    # Return false as a feeble fallback.
    return False
