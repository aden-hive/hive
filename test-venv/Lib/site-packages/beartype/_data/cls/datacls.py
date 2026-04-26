#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **class globals** (i.e., global constants describing various
well-known types).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    ForwardRef,
    Generic,
    Union,

    # The non-standard "beartype.typing.Protocol" superclass subclasses the
    # standard "typing.Protocol" superclass. Since "typing.Protocol" is the
    # proper superset of "beartype.typing.Protocol" and thus more
    # general-purpose, we intentionally:
    # * Reserve the name "Protocol" for the standard "typing.Protocol"
    #   superclass throughout this submodule.
    # * Preserve disambiguity by renaming "beartype.typing.Protocol" away.
    Protocol as ProtocolFast,
)
from beartype._cave._cavefast import (
    ClassType,
    EnumMemberType,
    FunctionType,
    HintPep695TypeAlias,
    MethodDecoratorBuiltinTypes,
    NoneType,
)
from beartype._data.typing.datatyping import (
    DictStrToType,
    FrozenSetTypes,
    TupleTypes,
)
from collections.abc import (
    Set as SetABC,
)
from pathlib import Path

# Intentionally import from the standard "typing" module rather than the
# forward-compatible "beartype.typing" subpackage to ensure PEP 484-compliance.
from typing import (
    BinaryIO,
    IO,
    Protocol,
    TextIO,
)

# ....................{ TYPES ~ abc                        }....................
TYPES_CONTEXTMANAGER_FAKE: TupleTypes = (Path,)
'''
Tuple of all **fake context manager types** (i.e., types that erroneously
masquerade as being context managers by defining fake ``__enter__()`` dunder
methods, which typically emit non-fatal warnings and reduce to noops).

This set includes:

* The :class:`pathlib.Path` superclass, whose subclasses under Python < 3.13
  defined fake ``__enter__()`` dunder methods that are now deprecated.
'''


TYPES_SET_OR_TUPLE: TupleTypes = (tuple, SetABC,)
'''
Tuple of all **set and tuple types** (i.e., superclasses of all sets and
tuples).

Note that the :class:`Set` abstract base class (ABC) rather than the concrete
:class:`set` subclass is intentionally listed here, as the concrete
:class:`frozenset` subclass subclasses the former but *not* latter: e.g.,

.. code-block:: python

   >>> from collections.abc import Set
   >>> issubclass(frozenset, Set)
   True
   >>> issubclass(frozenset, set)
   False
'''

# ....................{ TYPES ~ beartype                   }....................
# Types of *ALL* objects that may be decorated by @beartype, intentionally
# listed in descending order of real-world prevalence for negligible efficiency
# gains when performing isinstance()-based tests against this tuple. These
# include the types of *ALL*...
TYPES_BEARTYPEABLE: TupleTypes = (
    # Pure-Python unbound functions and methods.
    FunctionType,
    # Pure-Python classes.
    ClassType,
) + (
    # C-based builtin method descriptors wrapping pure-Python unbound methods,
    # including class methods, static methods, and property methods.
    MethodDecoratorBuiltinTypes
)
'''
Tuple of all **beartypeable types** (i.e., types of all objects that may be
decorated by the :func:`beartype.beartype` decorator).
'''

# ....................{ TYPES ~ builtin                    }....................
# Defined below by the _init() function.
TYPE_BUILTIN_NAME_TO_TYPE: DictStrToType = None  # type: ignore[assignment]
'''
Dictionary mapping from the name of each **non-fake builtin type** (i.e.,
globally accessible C-based type implicitly accessible from all scopes and thus
requiring *no* explicit importation) to that type.

This dictionary intentionally ignores **fake builtin types** (i.e., types that
are *not* builtin but nonetheless erroneously masquerade as being builtin,
including the type of the :data:`None` singleton).
'''


# Defined below by the _init() function.
TYPES_BUILTIN: FrozenSetTypes = None  # type: ignore[assignment]
'''
Frozen set of all **non-fake builtin types** (i.e., globally accessible C-based
types implicitly accessible from all scopes and thus requiring *no* explicit
importation).

This set intentionally ignores **fake builtin types** (i.e., types that are
*not* builtin but nonetheless erroneously masquerade as being builtin, including
the type of the :data:`None` singleton).
'''


TYPES_BUILTIN_SCALAR: FrozenSetTypes = frozenset((
    bytes,
    complex,
    float,
    int,
    str,
))
'''
Frozen set of all **builtin scalar types** (i.e., globally accessible C-based
types whose instances are scalar values).
'''


TYPES_BUILTIN_CONTAINER_MUTABLE: FrozenSetTypes = frozenset((
    bytearray,
    dict,
    list,
    set,
))
'''
Frozen set of all **builtin mutable container types** (i.e., C-based container
types globally accessible *without* requiring explicit importation, whose items
may be modified after instantiation).

All builtin mutable container types define these methods:

* ``clear()``, reducing the current object to the empty container.
'''

# ....................{ TYPES ~ exception                  }....................
TYPES_EXCEPTION_NAMESPACE = (
    # Standard exception raised when attempting to access a currently undefined
    # attribute of a defined object via "." syntax (e.g., an undefined attribute
    # "obj.attr" of a defined object "obj").
    AttributeError,
    # Standard exception raised when attempting to access an object defined in
    # neither the current local or global scopes.
    NameError,
)
'''
Tuple of all **standard scope exception types** (i.e., types of all standard
exceptions raised when a **namespace** (e.g., global or local scope, class or
object dictionary) fails to define a given attribute or name).
'''

# ....................{ TYPES ~ non-pep                    }....................
TYPES_NONPEP_TYPEARGS_PACKED = frozenset((
    # ....................{ PEP (484|604)                  }....................
    # The PEP 484- and 604-compliant unsubscripted "typing.Union" hint
    # semantically equivalent to the subscripted "typing.Union[typing.Any]" hint
    # is a valid C-based type whose whose "__parameters__" dunder attribute is a
    # C-based slotted class attribute of some obscure type under Python >= 3.14:
    #     >>> from typing import Union
    #     >>> Union.__parameters__
    #     <attribute '__parameters__' of 'typing.Union' objects>
    Union,

    # ....................{ PEP 695                        }....................
    # The PEP 695-compliant "typing.TypeAliasType" type of all PEP 695-compliant
    # type aliases of the syntactic form "type = {alias}" is a valid C-based
    # type whose whose "__parameters__" dunder attribute is a C-based slotted
    # class attribute of some obscure type under Python >= 3.12:
    #     >>> from typing import TypeAliasType
    #     >>> TypeAliasType.__parameters__
    #     <attribute '__parameters__' of 'typing.TypeAliasType' objects>
    HintPep695TypeAlias,
))
'''
Frozen set of all **PEP-noncompliant packed type parameters types** (i.e.,
standard types well-known to violate PEP standards by defining the
``__parameters__`` dunder attribute to *not* be a tuple of :pep:`484`-,
:pep:`612`-, and :pep:`646`-compliant packed type parameters).

These types are typically C-based unsubscripted type hint factories defined by
the private standard :class:`_typing` C extension. For unknown (and presumably
uninteresting) reasons, these factories define the ``__parameters__`` dunder
attribute to be a C-based slotted class attribute of some obscure type rather
than a tuple -- fundamentally violating :pep:`484`, :pep:`612`, and :pep:`646`.

When passed any of these types, the
:func:`beartype._util.hint.pep.utilpepget.get_hint_pep_typeargs_packed` getter
ignores erroneous ``__parameters__`` dunder attributes defined on these types by
returning the empty tuple (rather than raising obscure exceptions).
'''

# ....................{ TYPES ~ pep : 484                  }....................
TYPES_PEP484_GENERIC_IO = frozenset((BinaryIO, IO, TextIO,))
'''
Frozen set of all :pep:`484`-compliant **I/O generics** (i.e., public
:pep:`484`-compliant :class:`typing.Generic` subclasses defined by the standard
:mod:`typing` module, covering input/output use cases albeit in a non-optimized
and completely unconstrained manner).

Note that these generics are *not* :pep:`544`-compliant protocols. These
generics are thus mostly useless for most real-world purposes.
'''

# ....................{ TYPES ~ pep : (484|585)            }....................
TYPES_PEP484585_REF = (str, ForwardRef)
'''
Tuple union of all :pep:`484`- or :pep:`585`-compliant **forward reference
types** (i.e., classes of all forward reference objects).

Specifically, this union contains:

* :class:`str`, the class of all :pep:`585`-compliant forward reference objects
  implicitly preserved by all :pep:`585`-compliant type hint factories when
  subscripted by a string.
* :class:`HINT_PEP484_FORWARDREF_TYPE`, the class of all :pep:`484`-compliant
  forward reference objects implicitly created by all :mod:`typing` type hint
  factories when subscripted by a string.

While :pep:`585`-compliant type hint factories preserve string-based forward
references as is, :mod:`typing` type hint factories coerce string-based forward
references into higher-level objects encapsulating those strings. The latter
approach is the demonstrably wrong approach, because encapsulating strings only
harms space and time complexity at runtime with *no* concomitant benefits.
'''

# ....................{ TYPES ~ pep : 544                  }....................
#FIXME: *YIKES.* This omits "typing_extensions.Protocol", which is a distinct
#type from "typing.Protocol". *sigh*

TYPES_PEP544_PROTOCOL = frozenset((Protocol, ProtocolFast,))
'''
Frozen set of all **protocol superclasses** (i.e., types defined by the standard
:mod:`typing` and non-standard :mod:`beartype.typing` modules, guaranteed to be
the superclasses of all :pep:`544`-compliant protocols).

Note that callers typically reference this frozen set to efficiently detect
whether a type hint is an unsubscripted protocol superclass. Although
:class:`beartype.typing.Protocol` subclasses :class:`typing.Protocol`, both thus
*must* be explicitly enumerated here.
'''


TYPES_PEP484544_GENERIC = frozenset((Generic,)) | TYPES_PEP544_PROTOCOL
'''
Frozen set of all **generic superclasses** (i.e., types defined by the standard
:mod:`typing` module guaranteed to be the superclasses of all
:pep:`484`-compliant generics and/or :pep:`544`-compliant protocols).
'''

# ....................{ TYPES ~ pep : 586                  }....................
TYPES_PEP586_ARG = (bool, bytes, int, str, EnumMemberType, NoneType)
'''
Tuple of the types of all objects permissible as arguments subscripting the
:pep:`586`-compliant :attr:`typing.Literal` singleton.

These types are explicitly listed by :pep:`586` as follows:

    Literal may be parameterized with literal ints, byte and unicode strings,
    bools, Enum values and None.
'''

# ....................{ PRIVATE ~ init                     }....................
def _init() -> None:
    '''
    Initialize this submodule.
    '''

    # ....................{ IMPORTS                        }....................
    # Function-specific imports.
    from builtins import __dict__ as BUILTIN_NAME_TO_TYPE  # type: ignore[attr-defined]

    # ....................{ LOCALS                         }....................
    # Frozen set of all fake builtin types (i.e., types that erroneously
    # masquerade as being builtin). This includes:
    # * The type of the "None" singleton. For unknown reasons:
    #   * The CPython implementation of the standard "builtin" module correctly
    #     omits this type.
    #   * The PyPy implementation of the standard "builtin" module *INCORRECTLY*
    #     includes this type. Technically, this type should *ONLY* be included
    #     under PyPy. Pragmatically, unconditionally including this type under
    #     *ALL* Python implementations does no harm. This type is *ALWAYS*
    #     guaranteed to be fake wherever it appears.
    _FAKE_BUILTIN_TYPES = frozenset((NoneType,))

    # ....................{ GLOBALs                        }....................
    # Global variables redefined below.
    global TYPE_BUILTIN_NAME_TO_TYPE, TYPES_BUILTIN

    # Dictionary mapping from...
    TYPE_BUILTIN_NAME_TO_TYPE = {
        # The name of each builtin type to that type...
        builtin_name: builtin_value
        # For each attribute defined by the standard "builtins" module...
        for builtin_name, builtin_value in BUILTIN_NAME_TO_TYPE.items()
        # If...
        if (
            # This attribute is a type *AND*...
            isinstance(builtin_value, type) and
            # This is not a fake builtin type *AND*...
            builtin_value not in _FAKE_BUILTIN_TYPES and
            # This is not a dunder attribute (i.e., attribute whose name is both
            # prefixed and suffixed by double underscores)...
            not (
                builtin_name.startswith('__') and
                builtin_name.endswith  ('__')
            )
        )
    }

    # Frozenset of all builtin types, derived from this dictionary.
    TYPES_BUILTIN = frozenset(TYPE_BUILTIN_NAME_TO_TYPE.values())


# Initialize this submodule.
_init()
