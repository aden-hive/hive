#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **forward reference metaclasses** (i.e., low-level metaclasses of
classes deferring the resolution of a stringified type hint referencing an
attribute that has yet to be defined and annotating a class or callable
decorated by the :func:`beartype.beartype` decorator).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeCallHintForwardRefException
from beartype.typing import Dict
from beartype._data.typing.datatyping import BeartypeForwardRef
from beartype._util.cls.pep.clspep3119 import (
    die_unless_object_isinstanceable)
# from beartype._util.func.utilfuncframe import is_frame_caller_beartype
from beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget import (
    get_hint_pep484585_generic_type)
from beartype._util.hint.pep.proposal.pep484585.generic.pep484585gentest import (
    is_hint_pep484585_generic)
from beartype._util.module.utilmodimport import import_module_attr
from beartype._util.text.utiltextidentifier import is_dunder

# ....................{ METACLASSES                        }....................
class BeartypeForwardRefMeta(type):
    '''
    **Forward reference metaclass** (i.e., metaclass of the
    :class:`.BeartypeForwardRefABC` superclass deferring the resolution of a
    stringified type hint referencing an attribute that has yet to be defined
    and annotating a class or callable decorated by the
    :func:`beartype.beartype` decorator).

    This metaclass memoizes each **forward reference** (i.e.,
    :class:`.BeartypeForwardRefABC` instance) according to the fully-qualified
    name of the attribute referenced by that forward reference. Doing so ensures
    that only the first :class:`.BeartypeForwardRefABC` instance referring to a
    unique attribute is required to dynamically resolve that attribute at
    runtime; all subsequent :class:`.BeartypeForwardRefABC` instances referring
    to the same attribute transparently reuse the attribute previously resolved
    by the first such instance, effectively reducing the time cost of resolving
    forward references to a constant-time operation with negligible constants.

    This metaclass dynamically and efficiently resolves each forward reference
    in a just-in-time (JIT) manner on the first :func:`isinstance` call whose
    second argument is that forward reference. Forward references *never* passed
    to the :func:`isinstance` builtin are *never* resolved, which is good.
    '''

    # ....................{ DUNDERS                        }....................
    #FIXME: That's great, but still insufficient. Additionally:
    #* If the caller resides in a "beartype."-prefixed submodule, do what we
    #  currently do.
    #* Else, immediately resolve the referent by accessing "__type_beartype__"
    #  and then (as above) proxy the __getattr__() of this referent by calling
    #  getattr() against this referent.
    def __getattr__(  # type: ignore[misc]
        cls: BeartypeForwardRef, hint_name: str) -> BeartypeForwardRef:
        '''
        **Fully-qualified forward reference subclass** (i.e.,
        :class:`.BeartypeForwardRefABC` subclass whose metaclass is this
        metaclass and whose :attr:`.BeartypeForwardRefABC.__name_beartype__`
        class variable is the fully-qualified name of an external class).

        This dunder method creates and returns a new forward reference subclass
        referring to an external class whose name is concatenated from (in
        order):

        #. The fully-qualified name of the external package or module referred
           to by the passed forward reference subclass.
        #. The passed unqualified basename, presumably referring to a
           subpackage, submodule, or class of that external package or module.

        Design
        ------
        The syntactic implementation of this dunder method is largely trivial.
        The semantic justification for this implementation is, however, anything
        but. Indeed, justifying this implementation warrants a full-length
        dissertation on runtime resolution of forward references. This is that
        dissertation.

        Broadly speaking, there are two use cases for which CPython implicitly
        invokes this dunder method: two use cases whose intentions and
        requirements are so at odds with one another that seamlessly satisfying
        both is an exercise in code torture.

        The first use case is the intended (and also most common) use case:
        **absolute forward reference resolution deferral.** Given a
        :pep:`484`-compliant stringified absolute forward reference to a
        subscripted generic that has yet to be defined (e.g.,
        ``"some_package.some_submodule.SomeType[T]"``), how *exactly* does
        :mod:`beartype` resolve that subscripted generic in a manner consistent
        with efficient runtime type-checking? Is such resolution even feasible?
        The answers, of course, are: "Carefully." and "Yuppers."

        One brute-force approach to resolving stringified forward references
        containing arbitrarily complex Python expressions at runtime would be to
        parse those references through a Python-specific Parser Expression
        Grammar (PEG). Although technically feasible, embedding a full-blown
        Python parser within :mod:`beartype` would be so fragile and inefficient
        as to be effectively infeasible. Consequently, :mod:`beartype` does
        *not* do that. Instead, :mod:`beartype` is clever.

        The clever approach is to charm Python itself into parsing those
        references. After all, Python clearly knows how to parse Python.
        :mod:`beartype` simply needs to transform those references into some
        format readily digestible by Python's builtin Python parser. Our
        solution? The :func:`eval` builtin coupled with our non-standard
        :class:`beartype._check.forward.fwdscope.BeartypeForwardScope`
        dictionary subclass, which overrides the ``__missing__`` dunder method
        explicitly called by the superclass :meth:`dict.__getitem__` method
        implicitly called on each ``[``- and ``]``-delimited attempt to access a
        forward reference whose type has yet to be resolved by mapping the name
        of that reference to an actual **forward reference proxy** (i.e.,
        instance of this metaclass). The :func:`eval` builtin then implicitly
        instantiates one forward reference proxy encapsulating each undefined
        top-level attribute inside the passed absolute forward reference. Given
        ``"some_package.some_submodule.SomeType[T]"``, :func:`eval` then first
        instantiates one forward reference proxy encapsulating the undefined
        top-level attribute ``"some_package"``. Clearly, a forward reference
        proxy for ``"some_package"`` does *not* suffice to proxy the entire
        ``"some_package.some_submodule.SomeType[T]"`` forward reference.

        Cue this dunder method. :func:`eval` then attempts to access the
        ``"some_submodule"`` attribute of the forward reference proxy for
        ``"some_package"``. Doing so implicitly invokes this dunder method,
        which then instantiates another forward reference proxy encapsulating
        the undefined mid-level attribute ``"some_submodule"``. :func:`eval`
        then attempts to access the ``"SomeType[T]"`` attribute of the forward
        reference proxy for ``"some_submodule"``. Doing so implicitly invokes
        this dunder method, which then instantiates a final forward reference
        proxy encapsulating the undefined leaf-level attribute
        ``"SomeType[T]"``. Lastly, :func:`eval` then evaluates the expression
        ``"some_package.some_submodule.SomeType[T]"`` to the proxy for
        ``"SomeType[T]"``, which :func:`eval` then returns as its value. The
        intermediate proxies for both ``"some_package"`` and
        ``"some_submodule"`` are now irrelevant and thus garbage-collectable.

        This scheme is simple, effective, and (most importantly) efficient. But
        it's also prone to overly permissive proxying that intersects poorly
        with the second use case. Why? Because this scheme naively assumes that
        each invocation of this dunder method is **trustworthy**: that is, that
        each invocation of this dunder method is an attempt to access some valid
        module attribute that is known *a priori* to exist. This assumption
        holds for stringified absolute forward references used as type hints by
        the caller internally proxied by :mod:`beartype`. This assumption breaks
        when an invocation of this dunder method is **untrustworthy**: that is,
        when an invocation of this dunder method is merely an attempt to decide
        whether a module contains an attribute that is not known *a priori* to
        exist. In short, the second use case is the :func:`hasattr` builtin.

        The :func:`hasattr` builtin is actually implemented in terms of the
        :func:`getattr` builtin via the Easier to Ask for Permission than
        Forgiveness (EAFP) principle, implying that :func:`hasattr` internally
        invokes this dunder method. Although implemented in low-level C, a
        pure-Python implementation of :func:`hasattr` might vaguely resemble:

        .. code-block:: python

           def hasattr(obj: object, attr_name: str) -> bool:
               try:
                   getattr(obj, attr_name)
               except AttributeError:
                   return False
               return True

        The :func:`hasattr` builtin thus expects this dunder method to raise the
        :exc:`AttributeError` exception when the module proxied by this forward
        reference proxy fails to define an attribute with the passed name.
        However, this expectation conflicts with the overly permissive proxying
        performed by the scheme outlined above. In that first use case,
        :mod:`beartype` encapsulates an external module that is *not* safely
        importable with this forward reference proxy. Since :mod:`beartype` has
        *no* safe means of deciding whether that module actually defines an
        attribute with the passed name or not, :mod:`beartype` naively assumes
        that module to define that attribute. Under the scheme outlined above,
        this dunder method would *never* raise the :exc:`AttributeError` and the
        :func:`hasattr` attribute would *always* return :data:`True` when passed
        a forward reference proxy.

        Does this second use case arise in practice? In theory, it shouldn't.
        After all, forward reference proxies are mostly isolated to private
        subpackages in the :mod:`beartype` codebase... *mostly.* In practice,
        this second use case commonly arises. For efficiency, :mod:`beartype`
        replaces unusable stringified absolute forward references that are root
        type hints annotating the parameters and returns of
        :func:`beartype.beartype`-decorated callable with usable forward
        reference proxies. Popular third-party frameworks like ``pytest`` and
        Django then introspect those forward reference proxies during their
        non-trivial workloads. This introspection either directly calls the
        :func:`hasattr` builtin *or* replicates that builtin in pure-Python to
        detect whether those forward reference proxies define framework-specific
        dunder attributes of relevance to those frameworks.

        Parameters
        ----------
        cls : Type[BeartypeForwardRefABC]
            Forward reference subclass to concatenate this basename against.
        hint_name : str
            Unqualified basename to be concatenated against this forward
            reference subclass.

        Returns
        -------
        BeartypeForwardRef
            Fully-qualified forward reference subclass concatenated as above.
        '''

        #FIXME: Unit test up this edge case, please.
        # If this forward reference proxy has already been resolved to its
        # referent (e.g., by a prior isinstance() or issubclass() check),
        # forward this dunder method call directly to that referent.
        if _is_forwardref_resolved(cls):
            return getattr(cls.__type_beartype__, hint_name)
        # Else, this forward reference proxy has yet to be resolved.
        #
        # If a non-existent dunder attribute was requested, assume this
        # erroneous attempt to access a non-existent attribute of this forward
        # reference proxy to *ACTUALLY* be an Easier to Ask for Permission than
        # Forgiveness (EAFP)-driven to detect whether this forward scope defines
        # this attribute ala the hasattr() builtin. See also the "Design"
        # subsection of this dunder method's docstring for further commentary.
        elif is_dunder(hint_name):
            # Raise the standard "AttributeError" exception expected by EAFP.
            #
            # Note that we intentionally avoid suffixing the exception message
            # by a "." character here. Why? Because Python treats
            # "AttributeError" exceptions as special. Notably, Python appears to
            # actually:
            # 1. Parse apart the messages of these exceptions for the
            #    double-quoted attribute name embedded in these messages.
            # 2. Suffix these messages by a "." character followed by a sentence
            #    suggesting an existing attribute with a similar name to that of
            #    the attribute name previously parsed from these messages.
            #
            # For example, given an erroneous lookup of a non-existent dunder
            # attribute "__nomnom_beartype__", Python expands the exception
            # message raised below into:
            #     AttributeError: Forward reference proxy "MuhRef" dunder
            #     attribute "__nomnom_beartype__" not found. Did you mean:
            #     '__name_beartype__'?
            raise AttributeError(
                f'Forward reference proxy "{cls.__name__}" '
                f'dunder attribute "{hint_name}" not found'
            )
        # Else, the caller resides inside the "beartype" package and is
        # requesting a non-existent non-dunder attribute. In this case, safely
        # assume this request to comprise a higher-level attempt to resolve an
        # absolute stringified forward reference (e.g., the request for the
        # "some_submodule" attribute from the "some_package" forward reference
        # proxy given the initial absolute stringified forward reference
        # "some_package.some_submodule.SomeType").

        # Avoid circular import dependencies.
        from beartype._check.forward.reference.fwdrefmake import (
            make_forwardref_indexable_subtype)

        # Return a new fully-qualified forward reference subclass concatenated
        # as described above.
        return make_forwardref_indexable_subtype(
            cls.__scope_name_beartype__,  # type: ignore[arg-type]
            f'{cls.__name_beartype__}.{hint_name}',
        )


    def __instancecheck__(cls: BeartypeForwardRef, obj: object) -> bool:  # type: ignore[misc]
        '''
        :data:`True` only if the passed object is an instance of the external
        class referenced by the passed **forward reference subclass** (i.e.,
        :class:`.BeartypeForwardRefABC` subclass whose metaclass is this
        metaclass and whose :attr:`.BeartypeForwardRefABC.__name_beartype__`
        class variable is the fully-qualified name of that external class).

        Parameters
        ----------
        cls : Type[BeartypeForwardRefABC]
            Forward reference subclass to test this object against.
        obj : object
            Arbitrary object to be tested as an instance of the external class
            referenced by this forward reference subclass.

        Returns
        -------
        bool
            :data:`True` only if this object is an instance of the external
            class referenced by this forward reference subclass.
        '''

        # Return true only if this forward reference subclass insists that this
        # object satisfies the external class referenced by this subclass.
        return cls.__is_instance_beartype__(obj)


    def __subclasscheck__(cls: BeartypeForwardRef, obj: object) -> bool:  # type: ignore[misc]
        '''
        :data:`True` only if the passed object is a subclass of the external
        class referenced by the passed **forward reference subclass** (i.e.,
        :class:`.BeartypeForwardRefABC` subclass whose metaclass is this
        metaclass and whose :attr:`.BeartypeForwardRefABC.__name_beartype__`
        class variable is the fully-qualified name of that external class).

        Parameters
        ----------
        cls : Type[BeartypeForwardRefABC]
            Forward reference subclass to test this object against.
        obj : object
            Arbitrary object to be tested as a subclass of the external class
            referenced by this forward reference subclass.

        Returns
        -------
        bool
            :data:`True` only if this object is a subclass of the external class
            referenced by this forward reference subclass.
        '''

        # Return true only if this forward reference subclass insists that this
        # object is an instance of the external class referenced by this
        # subclass.
        return cls.__is_subclass_beartype__(obj)


    def __repr__(cls: BeartypeForwardRef) -> str:  # type: ignore[misc]
        '''
        Machine-readable string representing this forward reference subclass.
        '''

        # Machine-readable representation to be returned.
        #
        # Note that this representation is intentionally prefixed by the
        # @beartype-specific substring "<forwardref ", resembling the
        # representation of classes (e.g., "<class 'bool'>"). Why? Because
        # various other @beartype submodules ignore objects whose
        # representations are prefixed by the "<" character, which are usefully
        # treated as having a standard representation that is ignorable for most
        # intents and purposes. This includes:
        # * The die_if_hint_pep604_inconsistent() raiser.
        cls_repr = (
            f'<forwardref {cls.__name__}('
              f'__name_beartype__={repr(cls.__name_beartype__)}'
            f', __scope_name_beartype__={repr(cls.__scope_name_beartype__)}'
        )

        #FIXME: Unit test this edge case, please.
        # If this is a subscripted forward reference subclass, append additional
        # metadata representing this subscription.
        #
        # Ideally, we would test whether this is a subclass of the
        # "_BeartypeForwardRefIndexedABC" superclass as follows:
        #     if issubclass(cls, _BeartypeForwardRefIndexedABC):
        #
        # Sadly, doing so invokes the __subclasscheck__() dunder method defined
        # above, which invokes the
        # BeartypeForwardRefABC.__is_subclass_beartype__() method defined
        # above, which tests the type referred to by this subclass rather than
        # this subclass itself. In short, this is why you play with madness.
        try:
            cls_repr += (
                f', __args_beartype__={repr(cls.__args_beartype__)}'
                f', __kwargs_beartype__={repr(cls.__kwargs_beartype__)}'
            )
        # If doing so fails with the expected "AttributeError", then this is
        # *NOT* a subscripted forward reference subclass. Since this is
        # ignorable, silently ignore this common case. *sigh*
        except AttributeError:
            pass

        # Close this representation.
        cls_repr += ')>'

        # Return this representation.
        return cls_repr

    # ....................{ PROPERTIES                     }....................
    @property
    def __type_beartype__(cls: BeartypeForwardRef) -> type:  # type: ignore[misc]
        '''
        **Forward referent** (i.e., type hint referenced by this forward
        reference subclass, which is usually but *not* necessarily a class).

        This class property is manually memoized for efficiency. However, note
        this class property is *not* automatically memoized (e.g., by the
        ``property_cached`` decorator). Why? Because manual memoization enables
        other functionality in the beartype codebase to explicitly unmemoize all
        previously memoized forward referents across all forward reference
        proxies, effectively forcing all subsequent calls of this property
        across all forward reference proxies to reimport their forward referents.
        Why is that desirable? Because other functionality in the beartype
        codebase detects when the user has manually reloaded user-defined
        modules defining user-defined types annotating user-defined callables
        previously decorated by the :mod:`beartype.beartype` decorator. Since
        reloading those modules redefines those types, all previously cached
        types (including those memoized by this property) *must* then be assumed
        to be invalid and thus uncached. In short, manual memoization allows
        beartype to avoid desynchronization between memoized and actual types.

        This class property is officially in the public :mod:`beartype` API and
        guaranteed to be available across *all* current and future
        :mod:`beartype` releases.

        Caveats
        -------
        Downstream callers consuming callable type hints modified by a
        previously applied :mod:`beartype.beartype` decorator may occasionally
        encounter **forward reference proxies** (i.e., instances of this
        metaclass). Forward reference proxies are *not* intended to be usable as
        perfect substitutes for the underlying classes they proxy. Instead,
        downstream callers are recommended to manually resolve these proxies to
        the underlying classes they proxy by accessing this property. Consider
        this trivial one-liner that does so for a type hint ``type_hint``:

        .. code-block:: python

           # If this type hint is actually a @beartype-specific forward
           # reference proxy that only refers to the desired type hint,
           # dereference that proxy to obtain that type hint.
           type_hint = getattr(type_hint, '__type_beartype__', type_hint)

        Raises
        ------
        BeartypeCallHintForwardRefException
            If either:

            * This forward referent is unimportable.
            * This forward referent is importable but either:

              * Not a type.
              * A type that is this forward reference proxy, implying this proxy
                circularly proxies itself.
        '''

        # Forward referent referred to by this forward reference proxy if a prior
        # access of this property has already resolved this referent *OR* "None"
        # otherwise (i.e., if this is the first access of this property).
        referent = _forwardref_to_referent_get(cls)

        # If this forward referent has yet to be resolved, this is the first call
        # to this property. In this case...
        if referent is None:  # type: ignore[has-type]
            # print(f'Importing forward ref "{cls.__name_beartype__}" from module "{cls.__scope_name_beartype__}"...')

            # Exception subclass and prefix to be raised below.
            EXCEPTION_CLS = BeartypeCallHintForwardRefException
            EXCEPTION_PREFIX = 'Forward reference '

            # Forward referent dynamically imported from this module.
            referent = import_module_attr(
                attr_name=cls.__name_beartype__,
                module_name=cls.__scope_name_beartype__,
                exception_cls=EXCEPTION_CLS,
                exception_prefix=EXCEPTION_PREFIX,
            )

            # If this referent is this forward reference subclass, then this
            # subclass circularly proxies itself. Since allowing this edge case
            # would openly invite infinite recursion, we detect this edge case
            # and instead raise a human-readable exception.
            if referent is cls:
                raise BeartypeCallHintForwardRefException(
                    f'Forward reference proxy {repr(cls)} circularly '
                    f'(i.e., infinitely recursively) references itself.'
                )
            # Else, this referent is *NOT* this forward reference subclass.
            #
            # If this referent is a subscripted generic (e.g.,
            # "MuhGeneric[int]"), reduce this referent to the class subscripting
            # this generic (e.g., "int").
            elif is_hint_pep484585_generic(referent):
                referent = get_hint_pep484585_generic_type(
                    hint=referent,
                    exception_cls=EXCEPTION_CLS,
                    exception_prefix=EXCEPTION_PREFIX,
                )
            # Else, this referent is *NOT* a subscripted generic.

            # Cache this referent for subsequent lookup by this property
            # *BEFORE* validating this referent to be isinstanceable. If this
            # property is validated to *NOT* be isinstanceable, this referent
            # will be immediately uncached. Of course, this is insane. Ideally,
            # this referent would be cached only *AFTER* validating this
            # referent to be isinstanceable. Pragmatically, doing so invites
            # infinite recursion as follows (in order):
            # * This __type_beartype__() property getter calls...
            # * die_unless_object_isinstanceable(), which calls...
            # * "isinstance(None, cls)", which calls...
            # * BeartypeForwardRefMeta.__subclasscheck__(), which calls...
            # * "issubclass(obj, cls.__type_beartype__)", which calls...
            # * This __type_beartype__() property getter, which calls...
            # * die_unless_object_isinstanceable(). Repeat as needed for pain.
            #
            # Caching this referent first circumvents this recursion by ensuring
            # that all subsequent access of this property after the first access
            # of this property casually returns this referent rather than
            # repeatedly (thus uselessly) calling the
            # die_unless_object_isinstanceable() validator.
            _forwardref_to_referent[cls] = referent

            #FIXME: *SUPER-AWKWARD.* Slow, too. Ideally, we should instead:
            #* Define a new is_object_isinstanceable() tester. Note that this
            #  will be somewhat non-trivial (well -- tedious, mostly), which is
            #  why we haven't bothered yet. *sigh*
            #* Refactor the following "try: ... except Exception:" logic as follows:
            #     if not is_object_isinstanceable(referent):
            #         del _forwardref_to_referent[cls]
            #         die_unless_object_isinstanceable(
            #             obj=referent,
            #             exception_cls=BeartypeCallHintForwardRefException,
            #             exception_prefix='Forward reference ',
            #         )

            # Attempt to...
            try:
                # If this referent is *NOT* isinstanceable, raise an exception.
                die_unless_object_isinstanceable(
                    obj=referent,
                    exception_cls=EXCEPTION_CLS,
                    exception_prefix=EXCEPTION_PREFIX,

                    # If this referent is itself a forward reference proxy,
                    # raise an exception if that proxy *CANNOT* be resolved to
                    # the referent that proxy refers to. While an unlikely edge
                    # case, unlikely edge cases are like million-to-one chances
                    # in a Pratchett novel: you just know it's coming up.
                    is_forwardref_valid=False,
                )
                # Else, this referent is isinstanceable.
            # If doing so raised *ANY* exception whatsoever...
            except Exception:
                # Uncache this referent. See above.
                del _forwardref_to_referent[cls]

                # Re-raise this exception as is.
                raise
        # Else, this referent has already been resolved.
        #
        # In either case, this referent is now resolved.

        # Return this previously resolved referent.
        return referent  # type: ignore[return-value]

# ....................{ PRIVATE ~ globals                  }....................
_forwardref_to_referent: Dict[BeartypeForwardRef, type] = {}
'''
**Forward reference referent cache** (i.e., dictionary mapping from each forward
reference proxy to the arbitrary class referred to by that proxy).

This cache serves a dual purpose. Notably, this cache both enables:

* External callers to iterate over all previously instantiated forward reference
  proxies. This is particularly useful when responding to module reloading,
  which requires that *all* previously cached types be uncached.
* The
  :attr:`.BeartypeForwardRefMeta.__type_beartype__` property to internally
  memoize the arbitrary class referred to by this referent. Since the existing
  ``property_cached`` decorator could trivially do so as well, however, this is
  only a negligible side effect.
'''


_forwardref_to_referent_get = _forwardref_to_referent.get
'''
:meth:`dict.get` method bound to the :data:`._forwardref_to_referent` global
dictionary, globalized as a negligible microoptimization.
'''

# ....................{ PRIVATE ~ globals                  }....................
#FIXME: Unit test us up, please.
def _is_forwardref_resolved(hint: BeartypeForwardRef) -> bool:
    '''
    :data:`True` only if the passed **forward reference proxy** (i.e.,
    :class:`BeartypeForwardRef` object) is already been resolved to its
    **referent** (i.e., the object referred to by this reference).

    Parameters
    ----------
    hint : BeartypeForwardRef
        Forward reference proxy to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this proxy has been resolved to its referent.
    '''

    # Return true only if this proxy has been resolved to its referent.
    return hint in _forwardref_to_referent
