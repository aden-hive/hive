#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Unmemoized beartype type decorators** (i.e., low-level decorators decorating
classes on behalf of the parent :mod:`beartype._decor.decorcore` submodule).

This private submodule is effectively the :func:`beartype.beartype` decorator
despite *not* actually being that decorator (due to being unmemoized).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Dict,
    Set,
)
from beartype._cave._cavemap import NoneTypeOr
from beartype._conf.confmain import BeartypeConf
from beartype._data.cls.datacls import TYPES_BEARTYPEABLE
from beartype._data.typing.datatyping import (
    BeartypeableT,
    TypeStack,
)
from beartype._decor._type._pep._decortypepep557 import (
    beartype_pep557_dataclass)
from beartype._util.cache.utilcacheclear import clear_caches
from beartype._util.cls.pep.clspep557 import is_type_pep557_dataclass
from beartype._util.cls.utilclsset import set_type_attr
from beartype._util.cache.utilcacheobjattr import (
    get_type_attr_cached_or_sentinel,
    set_type_attr_cached,
)
from beartype._util.module.utilmodget import get_object_module_name_or_none
from collections import defaultdict

# ....................{ DECORATORS ~ type                  }....................
def beartype_type(
    # Mandatory parameters.
    cls: BeartypeableT,
    conf: BeartypeConf,

    # Optional parameters.
    cls_stack: TypeStack = None,
) -> BeartypeableT:
    '''
    Decorate the passed class with dynamically generated type-checking.

    Parameters
    ----------
    cls : BeartypeableT
        Class to be decorated by :func:`beartype.beartype`.
    conf : BeartypeConf
        Beartype configuration configuring :func:`beartype.beartype` uniquely
        specific to this class.
    cls_stack : TypeStack, optional
        **Type stack** (i.e., either a tuple of the one or more
        :func:`beartype.beartype`-decorated classes lexically containing the
        class variable or method annotated by this hint *or* :data:`None`).
        Defaults to :data:`None`.

    Returns
    ----------
    BeartypeableT
        This class decorated by :func:`beartype.beartype`.
    '''
    assert isinstance(cls, type), f'{repr(cls)} not type.'
    assert isinstance(cls_stack, NoneTypeOr[tuple]), (
        f'{repr(cls_stack)} neither tuple nor "None".')
    # assert isinstance(conf, BeartypeConf), f'{repr(conf)} not configuration.'
    # print(f'Decorating type {repr(obj)}...')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._decor.decorcore import beartype_object

    # ....................{ NOOP                           }....................
    # If the memoized type beartyped attribute already exists for this type, a
    # prior call to this decorator has already decorated this class. In this
    # case, silently reduce to a noop by returning this class as is.
    if get_type_attr_cached_or_sentinel(
        cls, _TYPE_ATTR_NAME_IS_BEARTYPED) is True:
        # print(f'Ignoring repeat decoration of {repr(cls)}...')
        return cls  # type: ignore[return-value]
    # # Else, this decorator has yet to decorate this class.

    # ....................{ LOCALS                         }....................
    # Replace the passed class stack with a new class stack appending this
    # decorated class to the top of this stack, reflecting the fact that this
    # decorated class is now the most deeply lexically nested class for the
    # currently recursive chain of @beartype-decorated classes.
    cls_stack = (
        # If the caller passed *NO* class stack, then this class is necessarily
        # the first decorated class being decorated directly by @beartype and
        # thus the root decorated class.
        #
        # Note this is the common case and thus tested first. Since nested
        # classes effectively do *NOT* exist in the wild, this comprises
        # 99.999% of all real-world cases.
        (cls,)
        if cls_stack is None else
        # Else, the caller passed a clack stack comprising at least a root
        # decorated class. Preserve that class as is to properly expose that
        # class elsewhere.
        cls_stack + (cls,)
    )

    # ....................{ DECORATE                       }....................
    # Clear *ALL* beartype-specific internal caches that have been shown to fail
    # when a class is redefined if the passed class is detected as having been
    # redefined in its module.
    _uncache_beartype_if_type_redefined(cls)

    # For the unqualified name and value of each direct (i.e., *NOT* indirectly
    # inherited) attribute of this class...
    for attr_name, attr_value in cls.__dict__.items():  # pyright: ignore[reportGeneralTypeIssues]
        # If this attribute is...
        if (
            # True only if this attribute is directly beartypeable (e.g., is either
            # a function, class, or builtin method descriptor).
            isinstance(attr_value, TYPES_BEARTYPEABLE) and
            # It is *NOT* the case that...
            #
            # Note that this condition intentionally ignores class variables
            # whose values are types, thus preventing @beartype from erroneously
            # decorating those types. Why? Because the caller did *NOT*
            # explicitly instruct us to decorate those types. Moreover,
            # attempting to do so could ignite infinite recursion in common edge
            # cases and is thus fundamentally dangerous.
            #
            # Consider this sample user-defined class:
            #     class ParentClass(object):
            #         class_var: type = type
            #         class NestedClass(object):
            #             pass
            #
            # Syntactically, the class variable "ParentClass.class_var" and
            # nested class "ParentClass.NestedClass" share *NO* commonality.
            # Semantically, however, @beartype treats those two attributes of
            # the parent class "ParentClass" as effectively identical. The
            # values of those two attributes are both classes, which @beartype
            # typically tries to recursively decorate. But only the latter are
            # safely decoratable by @beartype.
            #
            # Class variables whose values are types are *NOT* safely
            # decoratable by @beartype. In the best case, doing so would
            # decorate external classes *NOT* intended to be decorated; in the
            # worst case, doing so would provoke infinite recursion. Indeed, the
            # worst case is exactly what once happened. Previously, decorating
            # concrete "enum.Enum" subclasses with @beartype once provoked
            # infinite recursion. Why? Because:
            #
            # * *ALL* "enum.Enum" subclasses define a private "_member_type_"
            #   attribute whose value is the "object" superclass, which
            #   @beartype then decorated.
            # * However, the "object" superclass defines the "__class__" dunder
            #   attribute whose value is the "type" superclass, which @beartype
            #   then decorated.
            # * However, the "type" superclass defines the "__base__" dunder
            #   attribute whose value is the "object" superclass, which
            #   @beartype then decorated.
            # * *INFINITE FRIGGIN' RECURSION*. Anarchy today.
            #
            # In both the best and worst cases above, class variables whose
            # values are types *CANNOT* be safely decorated by @beartype.
            not (
                # The value of this attribute is also a class *AND*...
                isinstance(attr_value, type) and
                # That class was declared elsewhere and merely defined here as a
                # class attribute of the currently decorated class whose value
                # is that class (rather than as a nested class of the currently
                # decorated class)...
                not attr_value.__qualname__.startswith(cls.__qualname__)
            )
        ):
            # print(f'Decorating {repr(cls)} attribute "{attr_name}"...')

            # This attribute decorated with type-checking configured by this
            # configuration if *NOT* already decorated.
            attr_value_beartyped = beartype_object(  # type: ignore[type-var]
                obj=attr_value, conf=conf, cls_stack=cls_stack)

            # If this decorated attribute differs from the original attribute,
            # @beartype actually decorated this attribute with type-checking. In
            # this case...
            if attr_value_beartyped is not attr_value:
                # Safely replace this undecorated attribute with this decorated
                # attribute.
                set_type_attr(cls, attr_name, attr_value_beartyped)
                # print(f'Decorated {repr(cls)} attribute "{attr_name}".')
            # Else, this decorated attribute is the same as the original
            # attribute, implying that @beartype refused to decorate this
            # attribute with type-checking (e.g., due to this attribute being
            # unannotated by type hints). In this case, silently preserve this
            # attribute as is rather than brutally and uselessly replacing this
            # attribute with itself.
            # print(f'type: {type(attr_value)}; dir: {dir(attr_value)}')
        # Else, this attribute is *NOT* beartypeable. In this case, silently
        # ignore this attribute.

    # ....................{ DECORATE ~ pep : 557           }....................
    # If...
    if (
        # This beartype configuration enables type-checking of PEP 557-compliant
        # dataclasses *AND*...
        conf.is_pep557_fields and
        # This type is a PEP 557-compliant dataclass...
        is_type_pep557_dataclass(cls)
    ):
        # Monkey-patch type-checking of *ALL* PEP 557-compliant dataclass fields
        # into this dataclass.
        beartype_pep557_dataclass(datacls=cls, conf=conf)
    # Else, either this beartype configuration disables type-checking of PEP
    # 557-compliant dataclasses *OR* this type is *NOT* a PEP 557-compliant
    # dataclass. In either case, PEP 557 does *NOT* apply to this type.

    # ....................{ RETURN                         }....................
    # Memoize the type beartyped attribute for this type to notify subsequent
    # calls to this decorator that this type has already been decorated.
    set_type_attr_cached(cls, _TYPE_ATTR_NAME_IS_BEARTYPED, True)

    # Return this class as is.
    return cls  # type: ignore[return-value]

# ....................{ PRIVATE ~ globals                  }....................
_TYPE_ATTR_NAME_IS_BEARTYPED = 'is_beartyped'
'''
Unique name of the **memoized type beartyped attribute** (i.e., attribute cached
for each type passed to the :func:`.beartype_type` decorator whose existence
suggests this type to already have been decorated by that decorator and thus
neither require nor desire re-decoration by that decorator).

The value of this attribute is equally arbitrary but typically :data:`True`,
merely as a readability and debuggability aid.
'''


_BEARTYPED_MODULE_TO_TYPE_NAME: Dict[str, Set[str]] = defaultdict(set)
'''
**Decorated classname registry (i.e., dictionary mapping from the
fully-qualified name of each module defining one or more classes decorated by
the :func:`beartype.beartype` decorator to the set of the unqualified basenames
of all classes in that module decorated by that decorator).
'''

# ....................{ PRIVATE ~ globals                  }....................
def _uncache_beartype_if_type_redefined(cls: type) -> None:
    '''
    Clear *all* :mod:`beartype`-specific internal caches that have been shown to
    fail when a class is redefined if the passed class is detected as having
    been redefined in its module.

    If a class with the same unqualified basename defined in a module with the
    same fully-qualified name has already been marked as decorated by this
    decorator, then either:

    * That module has been externally reloaded. In this case, this class (along
      with the remainder of that module) has now been redefined. Common examples
      include:

      * Rerunning a Jupyter cell defining this class.
      * Refreshing a web app enabling hot reloading (i.e., automatic reloading
        of on-disk modules whose contents have been externally modified *after*
        that app was initially run). Since most Python web app frameworks (e.g.,
        Flask, Streamlit) support hot reloading, this is the common case.

    * That module has internally redefined this class two or more times. This
      behaviour, while typically a bug, is also technically valid: e.g.,

      .. code-block:: python

         @beartype
         def MuhClass(object): ...
         @beartype
         def MuhClass(object): ...   # <-- this makes me squint

    In either case, this class has been redefined. Since :mod:`beartype` has no
    efficient means of deciding which internal caches to clear in response,
    :mod:`beartype` instead now unconditionally clears *all* internal caches.
    Doing so incurs a minor performance penalty whenever a module reload occurs
    while preserving user-facing usability across module reloads. In short, the
    minor performance penalty is worth this major usability gain.
    '''

    # Fully-qualified name of the module defining this class if this class is
    # defined by a module *OR* "None" otherwise (e.g., if this class is only
    # dynamically defined in-memory outside of any module structure).
    module_name = get_object_module_name_or_none(cls)

    # If this class is defined by a module...
    if module_name:
        # Unqualified basename of this class.
        type_name = cls.__name__

        # Set of the unqualified basenames of *ALL* classes in that module
        # previously decorated by this decorator.
        type_names_beartyped = _BEARTYPED_MODULE_TO_TYPE_NAME[module_name]

        # If a class with the same unqualified basename defined in a module with
        # the same fully-qualified name has already been marked as decorated by
        # this decorator, then this class is currently being redefined. In this
        # case, clear *ALL* beartype-specific internal caches that have been
        # shown to fail when classes are redefined.
        if type_name in type_names_beartyped:
            #FIXME: Consider emitting a logging message instead if this branch
            #ever becomes computationally intensive, please.
            # print(f'@beartyped class "{module_name}.{type_name}" redefined!')

            # Clear *ALL* type-checking caches. Notably:
            # * The forward reference referee cache (i.e., private
            #   "beartype._check.forward.reference.fwdrefmeta._forwardref_to_referent"
            #   dictionary) is problematic, due to mapping from forward
            #   reference proxies (which are themselves classes) to arbitrary
            #   (and thus usually user-defined) classes -- one or more of which
            #   might be this class or other similarly redefined classes.
            # * The type hint coercion cache (i.e., private
            #   "beartype._check.convert._convcoerce._hint_repr_to_hint"
            #   dictionary) is problematic, due to mapping from the
            #   machine-readable representations of previously seen
            #   non-self-cached type hints (e.g., "list[MuhClass]") to the first
            #   seen instance of those hints (e.g., list[MuhClass]). Since this
            #   class has been redefined, the first seen instance of those hints
            #   could contain a reference to the first definition of this class.
            #
            # If any of these caches contain such desynchronized key-value
            # pairs, there now exists a discrepancy between the current
            # definition of this class and existing references in these caches
            # to the prior definition of this class. For safety, all caches
            # possibly containing those references must now be assumed to be
            # invalid. Failing to clear these caches causes @beartype-decorated
            # wrapper functions to raise erroneous type-checking violations.
            clear_caches()

            # Clear the previously accessed set of the unqualified basenames of
            # *ALL* classes in that module previously decorated by this
            # decorator. Technically, this is optional. Pragmatically, this
            # *SHOULD* significantly improve the space and time constraints
            # associated with this class redefinition. Why? Because this class
            # being redefined implies that the module defining this class is
            # being redefined, which implies that all classes in that module are
            # being redefined as well. If we did *NOT* clear this set here, then
            # this set would continue to contain the unqualified basenames of
            # those other classes in that module; each @beartype-decorated
            # redefinition of those other classes would then unnecessarily clear
            # the same caches already cleared by the first @beartype-decorated
            # redefinition of a class in that module. Since doing so would be
            # overly aggressive and thus inefficient, avoiding doing so improves
            # efficiency in the common case of module redefinition.
            _BEARTYPED_MODULE_TO_TYPE_NAME.clear()

            # Set of the unqualified basenames of *ALL* classes in that module
            # previously decorated by this decorator, redefined *AFTER* clearing
            # that set above to enable the addition of this type back to this
            # new set below. Nobody ever said type-checking was gonna be easy.
            type_names_beartyped = _BEARTYPED_MODULE_TO_TYPE_NAME[module_name]
        # Else, this is the first decoration of this class by this decorator.

        # Record that this class has now been decorated by this decorator.
        # Technically, this should (probably) be performed *AFTER* this
        # decorator has actually successfully decorated this class.
        # Pragmatically, doing so here is simply faster and... simpler.
        type_names_beartyped.add(type_name)
    # Else, this class is *NOT* defined by a module.
