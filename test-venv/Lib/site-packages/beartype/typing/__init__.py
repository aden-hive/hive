#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :mod:`typing` **compatibility layer.**

This submodule declares the exact same set of **public typing attributes**
(i.e., module-scoped attributes listed by the :attr:`typing.__all__` global) as
declared by the :mod:`typing` module for your current Python version. Although
the attributes declared by this submodule *mostly* share the same values as
the attributes declared by :mod:`typing`, notable differences include:

* :pep:`585`-deprecated typing attributes. :pep:`585` deprecated **38 public
  typing attributes** to "...be removed from the typing module in the first
  Python version released 5 years after the release of Python 3.9.0." This
  submodule preserves those attributes under their original names for the
  Python 3.8-specific version of the :mod:`typing` module, thus preserving
  forward compatibility with future Python versions. These include:

  * :obj:`typing.AbstractSet`.
  * :obj:`typing.AsyncContextManager`.
  * :obj:`typing.AsyncGenerator`.
  * :obj:`typing.AsyncIterable`.
  * :obj:`typing.AsyncIterator`.
  * :obj:`typing.Awaitable`.
  * :obj:`typing.ByteString`.
  * :obj:`typing.Callable`.
  * :obj:`typing.ChainMap`.
  * :obj:`typing.Collection`.
  * :obj:`typing.Container`.
  * :obj:`typing.ContextManager`.
  * :obj:`typing.Coroutine`.
  * :obj:`typing.Counter`.
  * :obj:`typing.DefaultDict`.
  * :obj:`typing.Deque`.
  * :obj:`typing.Dict`.
  * :obj:`typing.FrozenSet`.
  * :obj:`typing.Generator`.
  * :obj:`typing.ItemsView`.
  * :obj:`typing.Iterable`.
  * :obj:`typing.Iterator`.
  * :obj:`typing.KeysView`.
  * :obj:`typing.List`.
  * :obj:`typing.Mapping`.
  * :obj:`typing.MappingView`.
  * :obj:`typing.Match`.
  * :obj:`typing.MutableMapping`.
  * :obj:`typing.MutableSequence`.
  * :obj:`typing.MutableSet`.
  * :obj:`typing.OrderedDict`.
  * :obj:`typing.Pattern`.
  * :obj:`typing.Reversible`.
  * :obj:`typing.Set`.
  * :obj:`typing.Tuple`.
  * :obj:`typing.Type`.
  * :obj:`typing.Sequence`.
  * :obj:`typing.ValuesView`.

Usage
----------
:mod:`beartype` users are strongly encouraged to import typing attributes from
this submodule rather than from :mod:`typing` directly: e.g.,

.. code-block:: python

   # Instead of this...
   from typing import Tuple, List, Dict, Set, FrozenSet, Type

   # ...always do this.
   from beartype.typing import Tuple, List, Dict, Set, FrozenSet, Type
'''

# ....................{ TODO                               }....................
#FIXME: Fundamentally generalize this submodule to optionally backport
#attributes from "typing_extensions" where available, resolving issue #237 at:
#    https://github.com/beartype/beartype/issues/237
#
#To do so, we'll basically want to discard the entire current implementation of
#this submodule in favour of a fundamentally superior approach resembling:
#    # In "beartype.typing.__init__": the future of typing backports begins today.
#    from typing import TYPE_CHECKING
#
#    # If @beartype is currently being statically type-checked (e.g.,
#    # by mypy or pyright), just defer to the third-party
#    # "typing_extensions" package.
#    #
#    # Note that this does *NOT* mean that @beartype now unconditionally
#    # requires "typing_extensions" at either runtime or static
#    # type-checking time. Any code in an "if TYPE_CHECKING:" is (basically)
#    # just a convincing semantic lie that everything syntactically ignores.
#    if TYPE_CHECKING:
#        from typing_extensions import *  # <-- heh
#    # Else, @beartype is currently being imported from at runtime. This is
#    # the common case. This is also the non-trivial case, because @beartype
#    # does *NOT* require "typing_extensions" as a mandatory runtime
#    # dependency, because @beartype requires *NOTHING* as a runtime
#    # dependency. This is the only rule in @beartype's Rule of Law.
#    else:
#        #FIXME: Unfortunately, to avoid circular import dependencies, these
#        #imports will need to be copy-and-pasted into equivalent condensed
#        #submodules of a new "beartype.typing._util" subpackage.
#        # Import the requisite machinery that will make the magic happen.
#        from beartype._util.hint.utilhintfactory import TypeHintTypeFactory
#        from beartype._util.api.standard.utiltyping import (
#            import_typing_attr_or_fallback as _import_typing_attr_or_fallback)
#
#        # Dynamically define the "Self" type hint as follows:
#        # * If the active Python interpreter targets Python >= 3.11, just
#        #   defer to the canonical "typing.Self" type hint.
#        # * Else if "typing_extensions" is importable *AND* of a sufficiently
#        #   recent version to define the backported "typing_extensions.Self"
#        #   type hint, fallback to that hint.
#        # * Else, synthesize a placeholder type hint that @beartype internally
#        #   recognizes as semantically equivalent to "typing.Self".
#        Self = _import_typing_attr_or_fallback('Self', object)
#        LiteralString = _import_typing_attr_or_fallback('Self', str)
#        TypeGuard = _import_typing_attr_or_fallback('Self', bool)
#        Annotated = _import_typing_attr_or_fallback('Annotated', bool)
#
#        #FIXME: Repeat the above logic for *ALL* existing "typing" attributes.
#FIXME: Actually, ain't nobody got time for that at the moment. The low-hanging
#fruit here is to just trivially alias this submodule to the "typing" module
#like so:
#    from typing import *
#
#Then:
#* Remove almost *ALL* of this submodule.
#* Conditionally redefine various attributes (e.g., deprecated PEP 484 stuff,
#  slow "Protocol" superclass) as needed.
#
#This has the dramatic improvement of innately synchronizing this submodule,
#which has become a *NIGHTMARE* to maintain, against the official
#implementation. Python 3.14 @beartype users hit this when early release
#candidates of Python 3.14 removed "typing.ByteString", only for the final
#release of Python 3.14 to add it back. @beartype then began raising exceptions
#on importation. Since "typing" is a moving target nightmare, exposing ourselves
#to that nightmare no longer makes sense at all.
#
#The only possible issue might be mypy and pyright. If either complain, we'll
#have no choice but to eventually *DEPRECATE* this entire submodule -- probably
#in the run up to @beartype 1.0.0. Ugly stuff, but inviting synchronization woes
#is even uglier.

# ....................{ IMPORTS                            }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# WARNING: To avoid polluting the public module namespace, external attributes
# *NOT* intended for public importation should be locally imported at module
# scope *ONLY* under alternate private names (e.g., "import re as _re" rather
# than merely "from re").
# WARNING: To preserve PEP 561 compliance with static type checkers (e.g.,
# mypy), external attributes *MUST* be explicitly imported with standard static
# import machinery rather than non-standard dynamic import shenanigans (e.g.,
# "from typing import Annotated" rather than
# "import_typing_attr_or_none('Annotated')").
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
from beartype._util.py.utilpyversion import (
    IS_PYTHON_AT_MOST_3_16  as _IS_PYTHON_AT_MOST_3_16,
    IS_PYTHON_AT_MOST_3_15  as _IS_PYTHON_AT_MOST_3_15,
    IS_PYTHON_AT_MOST_3_13  as _IS_PYTHON_AT_MOST_3_13,
    IS_PYTHON_AT_LEAST_3_14 as _IS_PYTHON_AT_LEAST_3_14,
    IS_PYTHON_AT_LEAST_3_13 as _IS_PYTHON_AT_LEAST_3_13,
    IS_PYTHON_AT_LEAST_3_12 as _IS_PYTHON_AT_LEAST_3_12,
    IS_PYTHON_AT_LEAST_3_11 as _IS_PYTHON_AT_LEAST_3_11,
)

# ....................{ IMPORTS ~ all                      }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# WARNING: To prevent "mypy --no-implicit-reexport" from raising literally
# hundreds of errors at static analysis time, *ALL* public attributes *MUST* be
# explicitly reimported under the same names with "{exception_name} as
# {exception_name}" syntax rather than merely "{exception_name}". Yes, this is
# ludicrous. Yes, this is mypy. For posterity, these failures resemble:
#     beartype/_cave/_cavefast.py:47: error: Module "beartype.roar" does not
#     explicitly export attribute "BeartypeCallUnavailableTypeException";
#     implicit reexport disabled  [attr-defined]
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

# Import all public attributes of the "typing" module both available under all
# supported Python versions and *NOT* deprecated by a subsequent Python version
# under their original names.
from typing import (
    TYPE_CHECKING as TYPE_CHECKING,
    Any as Any,
    Annotated as Annotated,
    BinaryIO as BinaryIO,
    ClassVar as ClassVar,
    Concatenate as Concatenate,  # pyright: ignore
    Final as Final,  # pyright: ignore
    ForwardRef as ForwardRef,
    Generic as Generic,
    IO as IO,
    Literal as Literal,  # pyright: ignore
    NewType as NewType,
    NamedTuple as NamedTuple,
    NoReturn as NoReturn,
    Optional as Optional,
    ParamSpec as ParamSpec,  # pyright: ignore
    ParamSpecArgs as ParamSpecArgs,  # pyright: ignore
    ParamSpecKwargs as ParamSpecKwargs,  # pyright: ignore
    Reversible as Reversible,  # pyright: ignore
    TypedDict as TypedDict,  # pyright: ignore
    Text as Text,
    TextIO as TextIO,
    TypeAlias as TypeAlias,  # pyright: ignore
    TypeGuard as TypeGuard,  # pyright: ignore
    TypeVar as TypeVar,
    Union as Union,
    cast as cast,
    final as final,  # pyright: ignore
    get_args as get_args,  # pyright: ignore
    get_origin as get_origin,  # pyright: ignore
    get_type_hints as get_type_hints,
    is_typeddict as is_typeddict,  # pyright: ignore
    no_type_check as no_type_check,
    no_type_check_decorator as no_type_check_decorator,
    overload as overload,
)

# ....................{ IMPORTS ~ version : at least       }....................
# Import all public attributes of the "typing" module both available under at
# least some Python interpreter version *AN* not yet deprecated by a subsequent
# Python interpreter version under their original names.

#FIXME: mypy is now emitting non-fatal warnings about our failing to import from
#"typing_extensions", which is both an overly strongly opinionated position for
#mypy to stake out *AND* a bad opinion at that, because "typing_extensions" is
#a third-party package. Ideally, mypy shouldn't be pushing *ANY* third-party
#packages. These warnings resemble:
#    beartype/typing/__init__.py:145: note: Use `from typing_extensions import Final` instead
#    beartype/typing/__init__.py:145: note: See https://mypy.readthedocs.io/en/stable/runtime_troubles.html#using-new-additions-to-the-typing-module
#    beartype/typing/__init__.py:145: note: Use `from typing_extensions import Literal` instead
#
#That's not the worst, however. mypy is erroneously ignoring our intentional
#"# type: ignore[attr-defined]" pragmas here. It's likely that the ultimate
#culprit is our use of beartype-specific "IS_PYTHON_AT_LEAST_*" boolean globals.
#Instead, mypy appears to only support hard-coded tests against the
#"sys.version_info" tuple: e.g.,
#    if sys.version_info >= (3, 8):
#
#To resolve this, we should consider:
#* Abandoning our usage of beartype-specific "IS_PYTHON_AT_LEAST_*" boolean
#  globals for hard-coded tests against the "sys.version_info" tuple (above).
#* Submitting an upstream issue requesting that mypy respect the
#  "# type: ignore[attr-defined]" pragma rather than emitting warnings here.

# If the active Python interpreter targets Python >= 3.11...
if _IS_PYTHON_AT_LEAST_3_11:
    from typing import (  # type: ignore[attr-defined]
       LiteralString as LiteralString,  # pyright: ignore
       Never as Never,  # pyright: ignore
       NotRequired as NotRequired,  # pyright: ignore
       Required as Required,  # pyright: ignore
       Self as Self,  # pyright: ignore
       TypeVarTuple as TypeVarTuple,  # pyright: ignore
       Unpack as Unpack,  # pyright: ignore
       assert_never as assert_never,  # pyright: ignore
       assert_type as assert_type,  # pyright: ignore
       clear_overloads as clear_overloads,  # pyright: ignore
       dataclass_transform as dataclass_transform,  # pyright: ignore
       get_overloads as get_overloads,  # pyright: ignore
       reveal_type as reveal_type,  # pyright: ignore
    )

    # If the active Python interpreter targets Python >= 3.12...
    if _IS_PYTHON_AT_LEAST_3_12:
        from typing import (  # type: ignore[attr-defined]
            TypeAliasType as TypeAliasType,  # pyright: ignore
            override as override,  # pyright: ignore
        )

        # If the active Python interpreter targets Python >= 3.13...
        if _IS_PYTHON_AT_LEAST_3_13:
            from typing import (  # type: ignore[attr-defined]
                NoDefault as NoDefault,  # pyright: ignore
                ReadOnly as ReadOnly,  # pyright: ignore
                TypeIs as TypeIs,  # pyright: ignore
                get_protocol_members as get_protocol_members,  # pyright: ignore
                is_protocol as is_protocol,  # pyright: ignore
            )

            # If the active Python interpreter targets Python >= 3.14...
            if _IS_PYTHON_AT_LEAST_3_14:
                from typing import (  # type: ignore[attr-defined]
                    evaluate_forward_ref as evaluate_forward_ref,  # pyright: ignore
                )

# ....................{ IMPORTS ~ version : at most        }....................
# Import all public attributes of the "typing" module both available under at
# most some Python interpreter version (typically due to having been deprecated
# by a prior Python interpreter version).

# If the active Python interpreter targets at most Python <= 3.16...
if _IS_PYTHON_AT_MOST_3_16:
    # Import the PEP 585-compliant "collections.abc.ByteString" attribute
    # under 3.9 <= Python <= 3.13. Both "collections.abc.ByteString" *AND*
    # "typing.ByteString" have been scheduled for removal under Python 3.17 by
    # the upstream CPython issue:
    #     https://github.com/python/cpython/issues/91896
    #
    # Note that these attributes were originally scheduled for removal under
    # Python 3.14. This removal was since deferred by three minor versions (and
    # thus three years) to inform downstream third-party packages with proper
    # "DeprecationWarning" warnings emitted by the "typing" module.
    from collections.abc import ByteString as ByteString  # type: ignore[attr-defined]

    # If the active Python interpreter targets at most Python <= 3.15...
    if _IS_PYTHON_AT_MOST_3_15:
        # Import the PEP 484-compliant "typing.AnyStr" attribute under 3.9 <=
        # Python <= 3.15. This attribute has been scheduled for removal under
        # Python 3.16 by the upstream CPython issue:
        #     https://github.com/python/cpython/issues/105578
        from typing import AnyStr as AnyStr

# ....................{ PEP ~ 544                          }....................
# If this interpreter is performing static type-checking (e.g., via mypy), defer
# to the standard library versions of the family of "Supports*" protocols.
if TYPE_CHECKING:
    from typing import (  # type: ignore[attr-defined]
        Protocol as Protocol,  # pyright: ignore
        SupportsAbs as SupportsAbs,
        SupportsBytes as SupportsBytes,
        SupportsComplex as SupportsComplex,
        SupportsFloat as SupportsFloat,
        SupportsIndex as SupportsIndex,  # pyright: ignore
        SupportsInt as SupportsInt,
        SupportsRound as SupportsRound,
        runtime_checkable as runtime_checkable,  # pyright: ignore
    )
# Else, this interpreter is *NOT* performing static type-checking. In this
# case, prefer our optimized PEP 544 attributes.
else:
    from beartype.typing._typingpep544 import (
        Protocol as Protocol,
        SupportsAbs as SupportsAbs,
        SupportsBytes as SupportsBytes,
        SupportsComplex as SupportsComplex,
        SupportsFloat as SupportsFloat,
        SupportsIndex as SupportsIndex,
        SupportsInt as SupportsInt,
        SupportsRound as SupportsRound,
        runtime_checkable as runtime_checkable,
    )

# ....................{ PEP ~ 585                          }....................
# If the active Python interpreter is performing static type-checking (e.g.,
# "mypy"), import *ALL* public attributes of the "typing" module deprecated by
# PEP 585 as their original values.
#
# This is intentionally performed *BEFORE* the corresponding "else:" branch.
# Why? Because "mypy". If the order of these two branches is reversed, "mypy"
# emits errors when attempting to subscript *ANY* builtin type: e.g.,
#     error: "tuple" is not subscriptable  [misc]
if TYPE_CHECKING:
    from typing import (
        AbstractSet as AbstractSet,
        AsyncContextManager as AsyncContextManager,
        AsyncGenerator as AsyncGenerator,
        AsyncIterable as AsyncIterable,
        AsyncIterator as AsyncIterator,
        Awaitable as Awaitable,
        Callable as Callable,
        ChainMap as ChainMap,
        Collection as Collection,
        Container as Container,
        ContextManager as ContextManager,
        Coroutine as Coroutine,
        Counter as Counter,
        DefaultDict as DefaultDict,
        Deque as Deque,
        Dict as Dict,
        FrozenSet as FrozenSet,
        Generator as Generator,
        Hashable as Hashable,
        ItemsView as ItemsView,
        Iterable as Iterable,
        Iterator as Iterator,
        KeysView as KeysView,
        List as List,
        Mapping as Mapping,
        Match as Match,
        MappingView as MappingView,
        MutableMapping as MutableMapping,
        MutableSequence as MutableSequence,
        MutableSet as MutableSet,
        OrderedDict as OrderedDict,
        Pattern as Pattern,
        Reversible as Reversible,
        Set as Set,
        Sized as Sized,
        Tuple as Tuple,
        Type as Type,
        Sequence as Sequence,
        ValuesView as ValuesView,
    )
# Else, the active Python interpreter is *NOT* performing static type-checking.
# In this case, alias *ALL* public attributes of the "typing" module deprecated
# by PEP 585 to their equivalent values elsewhere in the standard library.
else:
    from collections import (
        ChainMap as ChainMap,
        Counter as Counter,
        OrderedDict as OrderedDict,
        defaultdict as DefaultDict,
        deque as Deque,
    )
    from collections.abc import (
        AsyncIterable as AsyncIterable,
        AsyncIterator as AsyncIterator,
        AsyncGenerator as AsyncGenerator,
        Awaitable as Awaitable,
        Callable as Callable,
        Collection as Collection,
        Container as Container,
        Coroutine as Coroutine,
        Generator as Generator,
        Hashable as Hashable,
        ItemsView as ItemsView,
        Iterable as Iterable,
        Iterator as Iterator,
        KeysView as KeysView,
        Mapping as Mapping,
        MappingView as MappingView,
        MutableMapping as MutableMapping,
        MutableSequence as MutableSequence,
        MutableSet as MutableSet,
        Reversible as Reversible,
        Sequence as Sequence,
        Sized as Sized,
        ValuesView as ValuesView,
        Set as AbstractSet,
    )
    from contextlib import (
        AbstractContextManager as ContextManager,
        AbstractAsyncContextManager as AsyncContextManager,
    )
    from re import (
        Match as Match,
        Pattern as Pattern,
    )

    Dict = dict  # type: ignore[misc]
    FrozenSet = frozenset  # type: ignore[misc]
    List = list  # type: ignore[misc]
    Set = set  # type: ignore[misc]
    Tuple = tuple  # type: ignore[assignment]
    Type = type  # type: ignore[assignment]
