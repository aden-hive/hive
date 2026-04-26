#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **Python version-agnostic signs** (i.e., instances of the
:class:`beartype._data.hint.sign.datahintsigncls.HintSign` class
uniquely identifying PEP-compliant type hints in a safe, non-deprecated manner
regardless of the Python version targeted by the active Python interpreter).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: Attributes imported here at module scope *MUST* be explicitly
# deleted from this module's namespace below.
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
from beartype.typing import (
    FrozenSet,
    List,
)
from beartype._data.hint.sign.datahintsigncls import HintSign as _HintSign

# ....................{ SIGNS ~ implicit : pep : (484|585) }....................
# User-defined generics, defined here rather than below to enable explicit
# "typing" exports signed below to trivially alias these generic signs.

HintSignPep484585GenericUnsubbed = _HintSign(
    name='Pep484585GenericUnsubscripted')
'''
Sign uniquely identifying all :pep:`484`- or :pep:`585`-compliant
**unsubscripted generics** (i.e., types subclassing either the
:pep:`484`-compliant :class:`typing.Generic` superclass, the
:pep:`544`-compliant :class:`typing.Protocol` superclass, or a
:pep:`585`-compliant type hint).
'''


HintSignPep484585GenericSubbed = _HintSign(
    name='Pep484585GenericSubscripted')
'''
Sign uniquely identifying all :pep:`484`- or :pep:`585`-compliant **subscripted
generics** (i.e., unsubscripted generic types originally parametrized by one or
more :pep:`484`-compliant type variables subscripted by a corresponding number
of arbitrary child type hints): e.g.,

.. code-block:: pycon

   >>> from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none

   # Unsubscripted PEP 585 generic parametrized by a PEP 484 type variable.
   >>> class MuhGeneric[T](list[T]): pass
   >>> get_hint_pep_sign_or_none(MuhGeneric)
   HintSignPep484585GenericUnsubbed

   # Subscripted PEP 585 generic replacing that type variable with a type.
   >>> get_hint_pep_sign_or_none(MuhGeneric[int])
   HintSignPep484585GenericSubbed
'''

# ....................{ SIGNS ~ explicit : setup           }....................
_HINT_SIGNS_TYPING_LIST: List[_HintSign] = []
'''
List of the signs identifying *all* standard :mod:`typing` type hints and type
hint factories.

This private list only exists for a brief window of time. Specifically:

#. This list initializes the public :data:`HINT_SIGNS_TYPING` frozen set below.
#. This list is then immediately deleted to avoid polluting the module namespace
   with temporary globals.
'''


def _make_typing_hint_sign(name: str) -> _HintSign:
    '''
    Sign with an explicit analogue in the standard :mod:`typing` module.

    This factory additionally adds this sign to the :data:`.HINT_SIGNS_TYPING`
    frozen set of the signs identifying *all* standard :mod:`typing` type hints
    and type hint factories.

    Caveats
    -------
    **This higher-level factory should always be used in lieu of the
    lower-level** :class:`._HintSign` **class to instantiate signs identifying
    standard** :mod:`typing` **type hints and type hint factories.**

    Parameters
    ----------
    name : str
        Name of this :mod:`typing` sign.

    Returns
    -------
    _HintSign
        This :mod:`typing` sign.
    '''

    # Sign with this same.
    hint_sign = _HintSign(name)

    # Append this sign to this list.
    _HINT_SIGNS_TYPING_LIST.append(hint_sign)

    # Return this sign.
    return hint_sign

# ....................{ SIGNS ~ explicit : define          }....................
# Signs with explicit analogues in the standard "typing" module.
#
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: Signs defined by this module are synchronized with the "__all__"
# list global of the "typing" module bundled with the most recent CPython
# release. For that reason, these signs are:
# * Intentionally declared in the exact same order prefixed by the exact same
#   inline comments as for that list global.
# * Intentionally *NOT* commented with docstrings, both because:
#   * These docstrings would all trivially reduce to a single-line sentence
#     fragment resembling "Alias of typing attribute."
#   * These docstrings would inhibit diffing and synchronization by inspection.
# * Intentionally *NOT* conditionally isolated to the specific range of Python
#   versions whose "typing" module lists these attributes. For example, the
#   "HintSignAsyncContextManager" sign identifying the
#   "typing.AsyncContextManager" attribute that only exists under Python >=
#   3.7 could be conditionally isolated to that range of Python versions.
#   Technically, there exists *NO* impediment to doing so; pragmatically, doing
#   so would be ineffectual. Why? Because attributes *NOT* defined by the
#   "typing" module of the active Python interpreter cannot (by definition) be
#   used to annotate callables decorated by the @beartype decorator.
#
# When bumping beartype to support a new CPython release:
# * Declare one new attribute here for each new "typing" attribute added by
#   that CPython release regardless of whether beartype explicitly supports
#   that attribute yet. The subsequently called die_unless_hint_pep_supported()
#   validator will raise exceptions when passed these attributes.
# * Preserve attributes here that have since been removed from the "typing"
#   module in that CPython release to ensure their continued usability when
#   running beartype against older CPython releases.
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

# Super-special typing primitives.
HintSignAnnotated       = _make_typing_hint_sign('Annotated')
HintSignAny             = _make_typing_hint_sign('Any')
HintSignCallable        = _make_typing_hint_sign('Callable')
HintSignClassVar        = _make_typing_hint_sign('ClassVar')
HintSignConcatenate     = _make_typing_hint_sign('Concatenate')
HintSignFinal           = _make_typing_hint_sign('Final')
HintSignForwardRef      = _make_typing_hint_sign('ForwardRef')
# Generic  <-- ambiguous between subscripted and unsubscripted variants (disambiguated below)
HintSignLiteral         = _make_typing_hint_sign('Literal')

#FIXME: Excise this *AFTER* dropping Python <= 3.13 support. Python >= 3.14
#unifies all unions under "HintSignUnion", thankfully. Phew!
HintSignOptional        = _make_typing_hint_sign('Optional')
HintSignParamSpec       = _make_typing_hint_sign('ParamSpec')
HintSignParamSpecArgs   = _make_typing_hint_sign('ParamSpecArgs')
HintSignParamSpecKwargs = _make_typing_hint_sign('ParamSpecKwargs')
HintSignProtocol        = _make_typing_hint_sign('Protocol')

#FIXME: Rename all *UNAMBIGUOUS* references to "HintSignTuple" to
#"HintSignPep484585TupleVariadic" for disambiguity. Note, however, that some
#references to "HintSignTuple" are ambiguous (in the sense that it is unclear in
#that early context whether the tuple type hint in question refers to a fixed-
#or variadic-length tuple type hint). Ergo, this rename *CANNOT* be automated
#with a global regex but should be applied manually one-by-one. *sigh*

# Note that the name of this sign is intentionally the ambiguous name "Tuple"
# rather than the unambiguous name "Pep484585TupleVariadic". Why? Because...
# actually, we have no particularly good reason. For disambiguity, the name of
# this sign should ideally be the latter. Sadly, doing so currently induces
# spurious test failures. We can't bother to dissect this at the moment. Ergo,
# the unctuous status quo prevails. Laziness: "It's not always a virtue."
HintSignTuple = HintSignPep484585TupleVariadic = _make_typing_hint_sign('Tuple')
# HintSignTuple = HintSignPep484585TupleVariadic = _make_typing_hint_sign(
#     'Pep484585TupleVariadic')
'''
Sign uniquely identifying **variable-length tuple type hints,** including:

* :pep:`484`-compliant type hints of the form ``typing.Tuple[{hint_child_1},
  ...]`` where the last child type hint subscripting this parent hint is an
  ellipses (i.e., ``"..."`` string, :data:`Ellipses` singleton).
* :pep:`585`-compliant type hints of the form ``tuple[{hint_child_1}, ...]``
  where the last child type hint subscripting this parent hint is an ellipses
  (i.e., ``"..."`` string, :data:`Ellipses` singleton).

See Also
--------
HintSignPep484585TupleFixed
    Sign uniquely identifying **fixed-length tuple type hints.**
HintSignPep646TupleFixedVariadic
    Sign uniquely identifying mixed fixed-variadic tuple type hints.
'''

HintSignType         = _make_typing_hint_sign('Type')
HintSignTypeVar      = _make_typing_hint_sign('TypeVar')
HintSignTypeVarTuple = _make_typing_hint_sign('TypeVarTuple')
HintSignUnion        = _make_typing_hint_sign('Union')

# ABCs (from collections.abc).
HintSignAbstractSet         = _make_typing_hint_sign('AbstractSet')

#FIXME: Permanently remove this sign *AFTER* dropping support for Python 3.15.
HintSignByteString          = _make_typing_hint_sign('ByteString')

HintSignContainer           = _make_typing_hint_sign('Container')
HintSignContextManager      = _make_typing_hint_sign('ContextManager')
HintSignHashable            = _make_typing_hint_sign('Hashable')
HintSignItemsView           = _make_typing_hint_sign('ItemsView')
HintSignIterable            = _make_typing_hint_sign('Iterable')
HintSignIterator            = _make_typing_hint_sign('Iterator')
HintSignKeysView            = _make_typing_hint_sign('KeysView')
HintSignMapping             = _make_typing_hint_sign('Mapping')
HintSignMappingView         = _make_typing_hint_sign('MappingView')
HintSignMutableMapping      = _make_typing_hint_sign('MutableMapping')
HintSignMutableSequence     = _make_typing_hint_sign('MutableSequence')
HintSignMutableSet          = _make_typing_hint_sign('MutableSet')
HintSignSequence            = _make_typing_hint_sign('Sequence')
HintSignSized               = _make_typing_hint_sign('Sized')
HintSignValuesView          = _make_typing_hint_sign('ValuesView')
HintSignAwaitable           = _make_typing_hint_sign('Awaitable')
HintSignAsyncIterator       = _make_typing_hint_sign('AsyncIterator')
HintSignAsyncIterable       = _make_typing_hint_sign('AsyncIterable')
HintSignCoroutine           = _make_typing_hint_sign('Coroutine')
HintSignCollection          = _make_typing_hint_sign('Collection')
HintSignAsyncGenerator      = _make_typing_hint_sign('AsyncGenerator')
HintSignAsyncContextManager = _make_typing_hint_sign('AsyncContextManager')

# Structural checks, a.k.a. protocols.
HintSignReversible = _make_typing_hint_sign('Reversible')
# SupportsAbs   <-- not a useful type hint (already an isinstanceable ABC)
# SupportsBytes   <-- not a useful type hint (already an isinstanceable ABC)
# SupportsComplex   <-- not a useful type hint (already an isinstanceable ABC)
# SupportsFloat   <-- not a useful type hint (already an isinstanceable ABC)
# SupportsIndex   <-- not a useful type hint (already an isinstanceable ABC)
# SupportsInt   <-- not a useful type hint (already an isinstanceable ABC)
# SupportsRound   <-- not a useful type hint (already an isinstanceable ABC)

# Concrete collection types.
HintSignChainMap = _make_typing_hint_sign('ChainMap')
HintSignCounter = _make_typing_hint_sign('Counter')
HintSignDeque = _make_typing_hint_sign('Deque')
HintSignDict = _make_typing_hint_sign('Dict')
HintSignDefaultDict = _make_typing_hint_sign('DefaultDict')
HintSignList = _make_typing_hint_sign('List')
HintSignOrderedDict = _make_typing_hint_sign('OrderedDict')
HintSignSet = _make_typing_hint_sign('Set')
HintSignFrozenSet = _make_typing_hint_sign('FrozenSet')
HintSignNamedTuple = _make_typing_hint_sign('NamedTuple')
HintSignTypedDict = _make_typing_hint_sign('TypedDict')
HintSignGenerator = _make_typing_hint_sign('Generator')

# Other concrete types.
HintSignMatch = _make_typing_hint_sign('Match')
HintSignPattern = _make_typing_hint_sign('Pattern')

# Other concrete type aliases.
# IO  <-- ambiguous between subscripted and unsubscripted variants
HintSignBinaryIO = HintSignPep484585GenericUnsubbed
HintSignTextIO = HintSignPep484585GenericUnsubbed

# One-off things.
# AnyStr   <-- not a unique type hint (merely a constrained "TypeVar")
# assert_never   <-- unusable as a type hint
# assert_type   <-- unusable as a type hint
# cast   <-- unusable as a type hint
# clear_overloads   <-- unusable as a type hint
# dataclass_transform   <-- unusable as a type hint
# final   <-- unusable as a type hint
# get_args   <-- unusable as a type hint
# get_origin   <-- unusable as a type hint
# get_type_hints   <-- unusable as a type hint
# is_protocol    <-- unusable as a type hint
# is_typeddict   <-- unusable as a type hint
HintSignLiteralString = _make_typing_hint_sign('LiteralString')
HintSignNever         = _make_typing_hint_sign('Never')
HintSignNewType       = _make_typing_hint_sign('NewType')
# no_type_check   <-- unusable as a type hint
# no_type_check_decorator   <-- unusable as a type hint
HintSignNoDefault     = _make_typing_hint_sign('NoDefault')

# Note that "NoReturn" is contextually valid *ONLY* as a top-level return hint.
# Since this use case is extremely limited, we explicitly generate code for this
# use case outside of the general-purpose code generation pathway for standard
# type hints. Since "NoReturn" is an unsubscriptable singleton, we explicitly
# detect this type hint with an identity test and thus require *NO* sign to
# uniquely identify this type hint.
#
# Theoretically, explicitly defining a sign uniquely identifying this type hint
# could erroneously encourage us to use that sign elsewhere; we should avoid
# that, as "NoReturn" is invalid in almost all possible contexts. Pragmatically,
# doing so nonetheless improves orthogonality when detecting and validating
# PEP-compliant type hints, which ultimately matters more than our subjective
# feelings about the matter. Wisely, we choose pragmatics.
#
# In short, "NoReturn" is insane.
HintSignNoReturn = _make_typing_hint_sign('NoReturn')

HintSignNotRequired     = _make_typing_hint_sign('NotRequired')
# overload   <-- unusable as a type hint
# override   <-- unusable as a type hint
HintSignParamSpecArgs   = _make_typing_hint_sign('ParamSpecArgs')
HintSignParamSpecKwargs = _make_typing_hint_sign('ParamSpecKwargs')
HintSignReadOnly        = _make_typing_hint_sign('ReadOnly')
HintSignRequired        = _make_typing_hint_sign('Required')
# reveal_type         <-- unusable as a type hint
# runtime_checkable   <-- unusable as a type hint
HintSignSelf            = _make_typing_hint_sign('Self')
# Text   <-- not actually a type hint (literal alias for "str")
# TYPE_CHECKING   <-- unusable as a type hint
HintSignTypeAlias       = _make_typing_hint_sign('TypeAlias')
HintSignTypeGuard       = _make_typing_hint_sign('TypeGuard')
HintSignTypeIs          = _make_typing_hint_sign('TypeIs')
# TypeAliasType  <-- not a unique type hint (merely a C-based type)
HintSignUnpack          = _make_typing_hint_sign('Unpack')

# Wrapper namespace for re type aliases.
#
# Note that "typing.__all__" intentionally omits the "Match" and "Pattern"
# attributes, which it oddly considers to comprise another namespace. *shrug*

# ....................{ SIGNS ~ explicit : teardown        }....................
HINT_SIGNS_TYPING: FrozenSet[_HintSign] = frozenset(_HINT_SIGNS_TYPING_LIST)
'''
Frozen set of all **typing signs** (i.e., identifying *all* standard
PEP-compliant :mod:`typing` type hints and type hint factories available in the
most recent stable CPython release).
'''

# ....................{ SIGNS ~ implicit                   }....................
# Signs with *NO* explicit analogues in the stdlib "typing" module but
# nonetheless standardized by one or more PEPs.

HintSignNone = _HintSign(name='None')
'''
Sign uniquely identifying the :data:`None` singleton, explicitly supported by
:pep:`484` but lacking an explicit analogue in the standard :mod:`typing`
module:

    When used in a type hint, the expression None is considered equivalent to
    type(None).
'''

# ....................{ SIGNS ~ implicit : lib             }....................
# Signs identifying PEP-noncompliant third-party type hints published by...
#
# ....................{ SIGNS ~ implicit : lib : numpy     }....................
HintSignNumpyArray = _HintSign(name='NumpyArray')   # <-- "numpy.typing.NDArray"
'''
...the :mod:`numpy.typing` subpackage.
'''

# ....................{ SIGNS ~ implicit : lib : pandera   }....................
HintSignPanderaAny = _HintSign(name='PanderaAny')   # <-- "pandera.typing.*"
'''
...the :mod:`pandera.typing` subpackage.

Specifically, define a single sign unconditionally matching *all* type hints
published by the :mod:`pandera.typing` subpackage. Why? Because Pandera insanely
publishes its own Pandera-specific PEP-noncompliant runtime type-checking
decorator :func:`pandera.check_types` that supports *only* Pandera-specific
PEP-noncompliant :mod:`pandera.typing` type hints. Since Pandera users are
already accustomed to decorating *all* Pandera-based callables (i.e., callables
accepting one or more parameters and/or returning one or more values which are
Pandera objects) by :func:`pandera.check_types`, attempting to type-check the
same objects already type-checked by that decorator would only inefficiently and
needlessly slow :mod:`beartype` down. Ergo, we ignore *all* Pandera type hints
by:

* Defining this catch-all singleton for Pandera type hints here.
* Denoting this singleton to be unconditionally ignorable elsewhere.
'''

# ....................{ SIGNS ~ implicit : pep : (484|585) }....................
HintSignPep484585TupleFixed = _HintSign(name='Pep484585TupleFixed')
'''
Sign uniquely identifying **fixed-length tuple type hints,** including:

* :pep:`484`-compliant type hints of the form ``typing.Tuple[{hint_child_1},
  ..., {hint_child_N}]`` where ``{hint_child_N}`` is *not* an ellipses (i.e.,
  ``"..."`` string, :data:`Ellipses` singleton).
* :pep:`585`-compliant type hints of the form ``tuple[{hint_child_1}, ...,
  {hint_child_N}]`` where ``{hint_child_N}`` is *not* an ellipses (i.e.,
  ``"..."`` string, :data:`Ellipses` singleton).

Note that:

* The ``"..."`` substring above is *not* a literal ellipses but simply denotes
  an arbitrary number of non-ellipses child type hints.
* The existing :data:`.HintSignTuple` sign uniquely identifies variable-length
  tuple type hints. Why? Because that sign naturally matches the unsubscripted
  :obj:`typing.Tuple` type hint factory, which is semantically equivalent to the
  ``typing.Tuple[object, ...]`` type hint, which is the widest possible
  variable-length tuple type hint.

See Also
--------
HintSignTuple
    Sign uniquely identifying variadic-length tuple type hints.
HintSignPep646TupleFixedVariadic
    Sign uniquely identifying mixed fixed-variadic tuple type hints.
'''

# ....................{ SIGNS ~ implicit : pep : 557       }....................
# dataclasses.InitVar[...].
HintSignPep557DataclassInitVar = _HintSign(name='Pep557DataclassInitVar')
'''
:pep:`557`-compliant :obj:`dataclasses.InitVar` type hint factory, annotating
class-scoped variable annotations of :func:`dataclass.dataclass`-decorated
data classes.
'''

# ....................{ SIGNS ~ implicit : pep : 585       }....................
# os.PathLike[...], weakref.weakref[...], et al.
HintSignPep585BuiltinSubscriptedUnknown = _HintSign(
    name='Pep585BuiltinSubscriptedUnknown')
'''
:pep:`585`-compliant C-based :class:`types.GenericAlias` superclass inheritable
by PEP-noncompliant pure-Python subclasses in either the standard library or
third-party packages, which when subscripted by otherwise PEP-compliant child
type hints produce PEP-noncompliant **unrecognized subscripted builtin type
hints** (i.e., C-based type hints that are *not* isinstanceable types,
instantiated by subscripting pure-Python origin classes unrecognized by
:mod:`beartype` and thus PEP-noncompliant).

Examples include:

* ``os.PathLike[...]`` type hints.
* ``weakref.weakref[...]`` type hints.

Unsurprisingly, :mod:`beartype` reduces C-based unrecognized subscripted builtin
type hints (which are *not* type-checkable as is) to their unsubscripted
pure-Python origin classes (which are type-checkable as is).
'''

# ....................{ SIGNS ~ implicit : pep : 646       }....................
#FIXME: Excise after generalizing our dynamic code generator for tuple hints to
#flexibly support PEP 646-compliant tuple hints. *sigh*

HintSignPep646TupleFixedVariadic = _HintSign(
    name='Pep646TupleFixedVariadic')
'''
Sign uniquely identifying :pep:`646`-compliant **mixed fixed-variadic tuple type
hints,** defined as hints of the form "tuple[{hint_child_1}, ...,
{hint_child_N}]" where:

* Exactly one "{hint_child_I}" for some :math:`1 <= I <= N` is either:

  * A :pep:`646`-compliant **unpacked type variable tuple** (i.e., type hint of
    either the implicit form "*T" *or* explicit form "typing.Unpack[T]" for an
    arbitrary Python identifier "T") .
  * A :pep:`646`-compliant **unpacked child tuple hint** (i.e., type hint of the
    form "*tuple[{hint_child_child_1}, ..., {hint_child_child_M}]").

* "{hint_child_N}" is *not* an ellipses (i.e., "..." string, :data:`Ellipses`
  singleton).

Note that the "..." substring above is *not* a literal ellipses but simply
denotes an arbitrary number of non-ellipses child type hints.

See Also
--------
HintSignTuple
    Sign uniquely identifying variadic-length tuple type hints.
HintSignPep484585TupleFixed
    Sign uniquely identifying fixed-length tuple type hints.
'''


HintSignPep646TupleUnpacked = _HintSign(name='Pep646TupleUnpacked')
'''
Sign uniquely identifying :pep:`646`-compliant **unpacked tuple type hints,**
defined as child tuple hints of the form "*tuple[{hint_child_child_1}, ...,
{hint_child_child_M}]" subscripting parent tuple hints of the form
"tuple[{hint_child_1}, ..., *tuple[{hint_child_child_1}, ...,
{hint_child_child_M}], ..., {hint_child_N}]".

Note that the ``"..."`` substring above is *not* a literal ellipses but simply
denotes an arbitrary number of non-ellipses child type hints.
'''


HintSignPep646TypeVarTupleUnpacked = _HintSign(
    name='Pep646TypeVarTupleUnpacked')
'''
Sign uniquely identifying :pep:`646`-compliant **unpacked type variable
tuples,** defined as child tuple hints of the form "*{typevartuple}" (where
"{typevartuple}" is an instance of the :class:`typing.TypeVarTuple` type)
subscripting parent tuple hints of the form
"tuple[{hint_child_1}, ..., *{typevartuple}, ..., {hint_child_N}]".

Note that the ``"..."`` substring above is *not* a literal ellipses but simply
denotes an arbitrary number of non-ellipses child type hints.
'''

# ....................{ SIGNS ~ implicit : pep : 692       }....................
HintSignPep692TypedDictUnpacked = _HintSign(name='Pep692TypedDictUnpacked')
'''
Sign uniquely identifying :pep:`692`-compliant **unpacked typed dictionaries,**
defined as type hints of the form "typing.Unpack[{typeddict}]" where
"{typeddict}" is a :class:`typing.TypedDict` subclass.
'''

# ....................{ SIGNS ~ implicit : pep : 695       }....................
# "type {alias_name}[{typevar_name}] = {alias_value}" statements.

HintSignPep695TypeAliasUnsubscripted = _HintSign(
    name='Pep695TypeAliasUnsubscripted')
'''
:pep:`695`-compliant C-based :class:`types.TypeAliasType` class of all
:pep:`695`-compliant **unsubscripted type aliases** (i.e., objects created as
the left-hand sides of statements of the form ``type {alias_name} =
{alias_value}``).

Most real-world type aliases are unsubscripted and thus identified by this sign.
'''


HintSignPep695TypeAliasSubscripted = _HintSign(
    name='Pep695TypeAliasSubscripted')
'''
Sign uniquely identifying all :pep:`695`-compliant **subscripted type aliases**
(i.e., unsubscripted type aliases originally parametrized by one or more
:pep:`484`-compliant type variables subscripted by a corresponding number of
arbitrary child type hints): e.g.,

.. code-block:: pycon

   >>> from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none

   # Unsubscripted PEP 695 type alias parametrized by a PEP 484 type variable.
   >>> MuhTypeAlias[T] = T | float
   >>> get_hint_pep_sign_or_none(MuhTypeAlias)
   HintSignPep695TypeAliasUnsubscripted

   # Subscripted PEP 695 type alias replacing that type variable with a type.
   >>> get_hint_pep_sign_or_none(MuhTypeAlias[int])
   HintSignPep695TypeAliasSubscripted
'''

# ....................{ CLEANUP                            }....................
# Prevent all attributes imported above from polluting this namespace. Why?
# Logic elsewhere subsequently assumes a one-to-one mapping between the
# attributes of this namespace and signs.
del (
    FrozenSet,
    List,
    _HINT_SIGNS_TYPING_LIST,
    _HintSign,
    _make_typing_hint_sign,
)
