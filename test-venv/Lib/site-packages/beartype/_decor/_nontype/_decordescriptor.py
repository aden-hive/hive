#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Unmemoized beartype builtin descriptor decorators** (i.e., low-level
decorators decorating low-level C-based objects produced by **builtin
decorators** (i.e., :class:`classmethod`, :class:`property`,
:class:`staticmethod`)).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._cave._cavefast import (
    MethodBoundInstanceOrClassType,
    MethodDecoratorPropertyType,
)
from beartype._data.typing.datatyping import BeartypeableT
from beartype._util.func.utilfuncget import get_func_boundmethod_self
from beartype._util.func.utilfunctest import is_func_boundmethod
from beartype._util.func.utilfuncwrap import (
    unwrap_func_boundmethod_once,
    unwrap_func_class_or_static_method_once,
)

# ....................{ DECORATORS                         }....................
def beartype_descriptor_boundmethod(
    descriptor: BeartypeableT, **kwargs) -> BeartypeableT:
    '''
    Decorate the passed **builtin bound method object** (i.e., C-based bound
    method descriptor produced by Python on instantiation for each instance and
    class method defined by the class being instantiated) with dynamically
    generated type-checking.

    Parameters
    ----------
    descriptor : BeartypeableT
        Descriptor to be decorated by :func:`beartype.beartype`.

    All remaining keyword parameters are passed as is to the lower-level
    :func:`.beartype_func` decorator internally called by this higher-level
    decorator on the pure-Python function encapsulated in this descriptor.

    Returns
    -------
    BeartypeableT
        New pure-Python callable wrapping this descriptor with type-checking.
    '''
    assert is_func_boundmethod(descriptor), (
        f'{repr(descriptor)} not builtin bound method descriptor.')

    # Avoid circular import dependencies.
    from beartype._decor._nontype.decornontype import beartype_func

    # Possibly C-based callable wrappee object encapsulated by this descriptor.
    descriptor_wrappee = unwrap_func_boundmethod_once(descriptor)

    # Instance object to which this descriptor was bound at instantiation time.
    descriptor_self = get_func_boundmethod_self(descriptor)

    # Pure-Python unbound function decorating the similarly pure-Python unbound
    # function encapsulated by this descriptor with type-checking.
    #
    # Note that doing so:
    # * Implicitly propagates dunder attributes (e.g., "__annotations__",
    #   "__doc__") from the original function onto this new function. Good.
    # * Does *NOT* implicitly propagate the same dunder attributes from the
    #   original descriptor encapsulating the original function to the new
    #   descriptor (created below) encapsulating this wrapper function. Bad!
    #   Thankfully, only one such attribute exists as of this time: "__doc__".
    #   We propagate this attribute manually below.
    func_checked = beartype_func(func=descriptor_wrappee, **kwargs)  # pyright: ignore

    # New instance method descriptor rebinding this function to the instance of
    # the class bound to the prior descriptor.
    #
    # Note that:
    # * This is required, as the "__func__" attribute of method descriptors is
    #   read-only. Attempting to do so raises this non-human-readable exception:
    #     AttributeError: readonly attribute
    #   This implies that the passed descriptor *CANNOT* be meaningfully
    #   modified. Our only recourse is to define an entirely new descriptor,
    #   effectively discarding the passed descriptor, which will then be
    #   subsequently garbage-collected. This is wasteful. This is Python.
    # * This can also be implemented by abusing the descriptor protocol:
    #       descriptor_new = descriptor_func_new.__get__(descriptor.__self__)
    #   That said, there exist *NO* benefits to doing so. Indeed, doing so only
    #   reduces the legibility and maintainability of this operation.
    descriptor_new = MethodBoundInstanceOrClassType(
        func_checked, descriptor_self)  # type: ignore[return-value]

    #FIXME: Actually, Python doesn't appear to support this at the moment.
    #Attempting to do so raises this exception:
    #    AttributeError: attribute '__doc__' of 'method' objects is not writable
    #
    #See also this open issue on the Python bug tracker requesting this be
    #resolved. Sadly, Python has yet to resolve this:
    #    https://bugs.python.org/issue47153
    # # Propagate the docstring from the prior to the new descriptor.
    # #
    # # Note that Python guarantees this attribute to exist. If the original
    # # function had a docstring, this attribute is non-"None"; else, this
    # # attribute is "None". In either case, this attribute exists. Ergo,
    # # additional validation is neither required nor desired.
    # descriptor_new.__doc__ = descriptor.__doc__

    # Return this new descriptor, implicitly destroying the prior descriptor.
    return descriptor_new  # type: ignore[return-value]


def beartype_descriptor_decorator_builtin_property(
    descriptor: BeartypeableT, **kwargs) -> BeartypeableT:
    '''
    Decorate the passed **builtin property decorator object** (i.e., C-based
    unbound method descriptor instantiated by the builtin :class:`property`
    decorator type) with dynamically generated type-checking.

    Parameters
    ----------
    descriptor : BeartypeableT
        Property descriptor to be decorated by :func:`beartype.beartype`.

    All remaining keyword parameters are passed as is to the lower-level
    :func:`.beartype_func` decorator internally called by this higher-level
    decorator on the pure-Python function encapsulated in this descriptor.

    Returns
    -------
    BeartypeableT
        New pure-Python callable wrapping this descriptor with type-checking.
    '''
    assert isinstance(descriptor, MethodDecoratorPropertyType), (
        f'{repr(descriptor)} not builtin @property method descriptor.')

    # Avoid circular import dependencies.
    from beartype._decor._nontype.decornontype import beartype_func

    # Pure-Python unbound getter, setter, and deleter functions wrapped by this
    # descriptor if any *OR* "None" otherwise (i.e., for each such function
    # currently unwrapped by this descriptor).
    descriptor_getter  = descriptor.fget  # type: ignore[assignment,union-attr]
    descriptor_setter  = descriptor.fset  # type: ignore[assignment,union-attr]
    descriptor_deleter = descriptor.fdel  # type: ignore[assignment,union-attr]

    # Decorate this getter function with type-checking.
    #
    # Note that *ALL* property method descriptors wrap at least a getter
    # function (but *NOT* necessarily a setter or deleter function). This
    # function is thus guaranteed to be non-"None".
    descriptor_getter = beartype_func(  # type: ignore[type-var]
        func=descriptor_getter,  # pyright: ignore
        **kwargs
    )

    # If this property method descriptor additionally wraps a setter and/or
    # deleter function, type-check those functions as well.
    if descriptor_setter is not None:
        descriptor_setter = beartype_func(descriptor_setter, **kwargs)
    if descriptor_deleter is not None:
        descriptor_deleter = beartype_func(descriptor_deleter, **kwargs)

    # Return a new property method descriptor decorating all of these functions,
    # implicitly destroying the prior descriptor.
    #
    # Note that the "property" class interestingly has this signature:
    #     class property(fget=None, fset=None, fdel=None, doc=None): ...
    return property(  # type: ignore[return-value]
        fget=descriptor_getter,
        fset=descriptor_setter,
        fdel=descriptor_deleter,
        doc=descriptor.__doc__,
    )


def beartype_descriptor_decorator_builtin_class_or_static_method(
    descriptor: BeartypeableT, **kwargs) -> BeartypeableT:
    '''
    Decorate the passed **builtin class or static method decorator object**
    (i.e., C-based unbound method descriptor instantiated by either the builtin
    :class:`classmethod` or :class:`staticmethod` decorator types) with
    dynamically generated type-checking.

    Parameters
    ----------
    descriptor : BeartypeableT
        Class or static method descriptor to be decorated by
        :func:`beartype.beartype`.

    All remaining keyword parameters are passed as is to the lower-level
    :func:`.beartype_func` decorator internally called by this higher-level
    decorator on the pure-Python function encapsulated in this descriptor.

    Returns
    -------
    BeartypeableT
        New pure-Python callable wrapping this descriptor with type-checking.
    '''

    # Avoid circular import dependencies.
    from beartype._decor.decorcore import beartype_object

    # Possibly C-based callable wrappee object decorated by this descriptor.
    #
    # Note that this wrappee is typically but *NOT* necessarily a pure-Python
    # unbound function. This descriptor explicitly permits the decorated object
    # to be a callable C-based type (i.e., defining the __call__() dunder
    # method), which numerous standard and third-party pure-Python classes then
    # leverage to augment those classes into subscriptable type hint factories
    # via a simple one-liner: e.g.,
    #     from abc import ABCMeta
    #     from beartype import beartype
    #     from types import GenericAlias
    #
    #     @beartype
    #     class MuhTypeHintFactory(metaclass=ABCMeta):
    #         # This exact one liner appears verbatim throughout the
    #         # standard library (as well as third-party packages).
    #         __class_getitem__ = classmethod(GenericAlias)
    #
    # Ergo, the name "__func__" of this dunder attribute is disingenuous. This
    # descriptor does *NOT* merely decorate functions; this descriptor
    # permissively decorates all callable objects.
    descriptor_wrappee = unwrap_func_class_or_static_method_once(descriptor)  # type: ignore[arg-type]

    # Pure-Python unbound function type-checking this wrappee. Note that:
    # * Python 3.8, 3.9, and 3.10 explicitly permit the @classmethod decorator
    #   to be chained into the @property decorator: e.g.,
    #       class MuhClass(object):
    #           @classmethod  # <-- this is fine under Python < 3.11
    #           @property
    #           def muh_property(self) -> ...: ...
    # * Python ≥ 3.11 explicitly prohibits that by emitting a non-fatal
    #   "DeprecationWarning" on each attempt to do so. Under Python ≥ 3.11,
    #   users *MUST* instead refactor the above simplistic decorator chaining
    #   use case as follows:
    #   * Define a metaclass for each class requiring a class property.
    #   * Define each class property on that metaclass rather than on that class
    #     instead.
    #
    #   In other words:
    #       class MuhClassMeta(type):  # <-- Python ≥ 3.11 demands sacrifice
    #          '''
    #          Metaclass of the :class`.MuhClass` class, defining class
    #          properties for that class.
    #          '''
    #
    #          @property
    #          def muh_property(cls) -> ...: ...
    #
    #      class MuhClass(object, metaclass=MuhClassMeta):
    #          pass
    # * Technically, all Python versions currently supported by @beartype permit
    #   this. Ergo, @beartype currently defers to:
    #   * The high-level beartype_object() decorator (which permits the passed
    #     object to be the descriptor created and returned by the @property
    #     decorator and thus implicitly allows @classmethod to be chained into
    #     @property) rather than...
    #   * The low-level beartype_func() decorator (which requires the passed
    #     object to be callable, which the descriptor created and returned by
    #     the @property decorator is *NOT*).
    descriptor_wrappee_checked = beartype_object(descriptor_wrappee, **kwargs) # type: ignore[union-attr]

    # Return a new class or static method descriptor decorating the pure-Python
    # unbound function wrapped by this descriptor with type-checking, implicitly
    # destroying the prior descriptor.
    return descriptor.__class__(descriptor_wrappee_checked)  # type: ignore[misc,return-value]
