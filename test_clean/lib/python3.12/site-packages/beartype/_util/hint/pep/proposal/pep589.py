#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`589`-compliant **typed dictionary** (i.e.,
:class:`typing.TypedDict` subclass) utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._util.cls.utilclstest import is_type_subclass
from beartype._util.py.utilpyversion import IS_PYTHON_AT_LEAST_3_14

# ....................{ TESTERS                            }....................
def is_hint_pep589(hint: object) -> bool:
    '''
    :data:`True` only if the passed object is a :pep:`589`-compliant **typed
    dictionary** (i.e., :class:`typing.TypedDict` subclass).

    This getter is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation trivially reduces to a
    one-liner. Moreover, callers are *not* expected to call this tester
    directly. Instead, callers are expected to (in order):

    #. Call the memoized
       :func:`beartype._util.hint.pep.utilpepget.get_hint_pep_sign_or_none`
       getter, which internally calls this unmemoized tester.
    #. Compare the object returned by that getter against the
       :attr:`beartype._util.data.hint.pep.sign.datahintsigns.HintSignTypedDict`
       sign.

    Motivation
    ----------
    The implementation of the :obj:`typing.TypedDict` attribute substantially
    varies across Python interpreter *and* :mod:`typing` implementation.
    Notably, the :obj:`typing.TypedDict` attribute under Python >= 3.9 is *not*
    actually a superclass but instead a factory function masquerading as a
    superclass by setting the subversive ``__mro_entries__`` dunder attribute to
    a tuple containing a private :obj:`typing._TypedDict` superclass. That
    superclass then defines various requisite dunder attributes. Passing the
    passed hint with that superclass to the :func:`issubclass` builtin fails, as
    the metaclass of that superclass prohibits :func:`issubclass` checks. I am
    throwing up in my mouth as I write this.

    Unfortunately, all of the above complications are further complicated by the
    :class:`dict` type under Python >= 3.10. For unknown reasons, Python >= 3.10
    adds spurious ``__annotations__`` dunder attributes to *all* :class:`dict`
    subclasses -- even if those subclasses annotate *no* class or instance
    variables. While a likely bug, we have little choice but to at least
    temporarily support this insanity.

    Parameters
    ----------
    hint : object
        Object to be tested.

    Returns
    -------
    bool
        :data:`True` only if this object is a typed dictionary.
    '''

    # Return true only...
    #
    # Note that:
    # * This detection scheme is technically susceptible to false positives in
    #   unlikely edge cases. Specifically, this test queries for dunder
    #   attributes and thus erroneously returns true for user-defined "dict"
    #   subclasses *NOT* subclassing the "typing.TypedDict" superclass but
    #   nonetheless declaring the same dunder attributes declared by that
    #   superclass. Since the likelihood of any user-defined "dict" subclass
    #   accidentally defining these attributes is vanishingly small *AND* since
    #   "typing.TypedDict" usage is sorta discouraged in the typing community,
    #   this error is unlikely to meaningfully arise in real-world use cases.
    #   Ergo, it is preferable to implement this test portably, safely, and
    #   efficiently rather than accommodate this error.
    # * This detection scheme would ideally trivially reduce to this one-liner:
    #       from typing import is_typeddict
    #       return is_typeddict(hint)
    #
    #   Deferring to that official tester suffices for typed dictionaries
    #   defined with the official "typing.TypedDict" but *NOT* third-party
    #   "typing_extensions.TypedDict" superclass. Even that constraint could be
    #   circumvented by noting that the is_typeddict() tester itself trivially
    #   reduces to a similar one-liner:
    #       return isinstance(tp, _TypedDictMeta)
    #
    #   An alternate working solution covering both the "typing.TypedDict" and
    #   "typing_extensions.TypedDict" superclasses would then resemble:
    #       _TYPED_DICT_BASES = (
    #            typing._TypedDictMeta, typing_extensions._TypedDictMeta,)
    #       return isinstance(tp, _TYPED_DICT_BASES)
    #
    #   Of course, that solution would *STILL* violate privacy encapsulation
    #   across not one but two distinct APIs, inviting future breakage.
    #
    # In short, the current approach is strongly preferable.
    return (
        # This hint is a "dict" subclass *AND*...
        #
        # If this hint is *NOT* a "dict" subclass, this hint *CANNOT* be a typed
        # dictionary. By definition, typed dictionaries are "dict" subclasses.
        # Note that PEP 589 actually lies about the type of typed dictionaries:
        #     Methods are not allowed, since the runtime type of a TypedDict
        #     object will always be just dict (it is never a subclass of dict).
        #
        # This is *ABSOLUTELY* untrue. PEP 589 authors plainly forgot to
        # implement this constraint. Contrary to the above:
        # * All typed dictionaries are subclasses of "dict".
        # * The type of typed dictionaries is the private
        #   "typing._TypedDictMeta" metaclass across all Python versions (as of
        #   this comment). Although this metaclass *COULD* currently be used to
        #   detect "TypedDict" subclasses, doing so would increase the fragility
        #   of this fragile codebase by unnecessarily violating privacy
        #   encapsulation.
        #
        # This is where we generously and repeatedly facepalm ourselves.
        is_type_subclass(hint, dict) and
        # The set intersection of the set of the names of all class attributes
        # of this "dict" subclass with the frozen set of the names of all class
        # attributes unique to all "TypedDict" subclasses produces a new set
        # whose length is exactly that of the latter frozen set. Although
        # cumbersome to cognitively parse, this test is *REALLY* fast.
        len(hint.__dict__.keys() & _TYPED_DICT_UNIQUE_ATTR_NAMES) == (
            _TYPED_DICT_UNIQUE_ATTR_NAMES_LEN)
    )

# ....................{ PRIVATE ~ globals                  }....................
# The is_hint_pep589() tester defined above uniquely identifies "TypedDict"
# subclasses as types declaring *ALL* of:
_TYPED_DICT_UNIQUE_ATTR_NAMES = frozenset((
    (
        # If the active Python interpreter targets Python >= 3.14, this PEP
        # 649-compliant dunder attribute. CPython now dynamically creates the
        # "__annotations__" dunder dictionary on first access. Ergo, the
        # "__annotations__" dunder dictionary is no longer guaranteed to exist
        # as an item of the "__dict__" dunder dictionary of "TypedDict" types.
        '__annotate_func__'
        if IS_PYTHON_AT_LEAST_3_14 else
        # Else, the active Python interpreter targets Python <= 3.13. In this
        # case, this PEP 484-compliant dunder attribute.
        '__annotations__'
    ),
    '__optional_keys__',
    '__required_keys__',
    '__total__',
))
'''
Frozen set of the names of all class attributes universally unique to *all*
:class:`typing.TypedDict` subclasses and thus suitable for differentiating
:class:`typing.TypedDict` subclasses from unrelated :class:`dict` subclasses.
'''


_TYPED_DICT_UNIQUE_ATTR_NAMES_LEN = len(_TYPED_DICT_UNIQUE_ATTR_NAMES)
'''
Number of class attributes unique to *all* :class:`typing.TypedDict` subclasses.
'''
