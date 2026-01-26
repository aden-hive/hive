#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **type hints** (i.e., PEP-compliant type hints annotating callables
and classes declared throughout this codebase, either for compliance with
:pep:`561`-compliant static type checkers like :mod:`mypy` or simply for
documentation purposes).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: This submodule *CANNOT* import from the companion "datatypingport"
# submodule due to circular import dependencies between these two submodules.
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

import beartype #  <-- satisfy mypy [note to self: i can't stand you, mypy]
from ast import (
    AST,
    AsyncFunctionDef,
    ClassDef,
    FunctionDef,
)
from beartype.typing import (
    AbstractSet,
    Any,
    Callable,
    Collection,
    Dict,
    ForwardRef,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Literal,
    Mapping,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)
from beartype._cave._cavefast import (
    FunctionType,
    HintPep604Type,
    HintPep612ParamSpecType,
    HintPep646TypeVarTupleType,
    HintPep646692UnpackedType,
    HintPep695TypeAlias,
    MethodBoundInstanceOrClassType,
    MethodDecoratorClassType,
    MethodDecoratorPropertyType,
    MethodDecoratorStaticType,
    ModuleType,
)
from beartype._data.func.datafuncarg import ARG_VALUE_UNPASSED
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.kind.datakindiota import Iota
from collections import ChainMap
from collections.abc import Callable as CallableABC
from importlib.abc import PathEntryFinder
from pathlib import Path
from types import (
    CodeType,
    FrameType,
    GeneratorType,
)
from typing import TYPE_CHECKING

#FIXME: Doesn't seem to help. mypy 0.19.0 appears to busted, sadly. We sigh.
# # If a static type-checker is type-checking us, import circular imports. Ugh!
# if TYPE_CHECKING:
#     from beartype._check.forward.reference.fwdrefabc import (
#         BeartypeForwardRefABC)
# # Else, Python is running us. Bless ye, Python. Bless ye.

# ....................{ AST                                }....................
NodeCallable = FunctionDef | AsyncFunctionDef
'''
PEP-compliant type hint matching a **callable node** (i.e., abstract syntax tree
(AST) node encapsulating the definition of a pure-Python function or method that
is either synchronous or asynchronous).
'''


NodeDecoratable = NodeCallable | ClassDef
'''
PEP-compliant type hint matching a **decoratable node** (i.e., abstract syntax
tree (AST) node encapsulating the definition of a pure-Python object supporting
decoration by one or more ``"@"``-prefixed decorations, including both
pure-Python classes *and* callables).
'''


NodeVisitResult = AST | list[AST] | None
'''
PEP-compliant type hint matching a **node visitation result** (i.e., object
returned by any visitor method of an :class:`ast.NodeVisitor` subclass).

Specifically, this hint matches either:

* A single node, in which case a visitor method has effectively preserved the
  currently visited node passed to that method in the AST.
* A list of zero or more nodes, in which case a visitor method has replaced the
  currently visited node passed to that method with those nodes in the AST.
* :data:`None`, in which case a visitor method has effectively destroyed the
  currently visited node passed to that method from the AST.
'''


NodesList = list[AST]
'''
PEP-compliant type hint matching an **abstract syntax tree (AST) node list**
(i.e., list of zero or more AST nodes).
'''

# ....................{ BOOL                               }....................
BoolTristate = Literal[True, False, None]
'''
PEP-compliant type hint matching a **tri-state boolean** whose value may be
either:

* :data:`True`.
* :data:`False`.
* :data:`None`, implying that the actual value of this boolean is contextually
  dependent on context-sensitive program state.
'''


BoolTristateUnpassable = Literal[True, False, None, ARG_VALUE_UNPASSED]  # type: ignore[valid-type]
'''
PEP-compliant type hint matching an **unpassable tri-state boolean** whose value
may be either:

* :data:`True`.
* :data:`False`.
* :data:`None`, implying that the actual value of this boolean is contextually
  dependent on context-sensitive program state.
* :data:`.ARG_VALUE_UNPASSED`, enabling any callable that annotates a tri-state
  boolean parameter by this type hint to deterministically identify whether the
  caller explicitly passed that parameter or not. Since the caller may
  explicitly pass :data:`None` as a valid value, testing that parameter against
  :data:`None` does *not* suffice to decide this decision problem.
'''

# ....................{ CALLABLE ~ early                   }....................
# Callable-specific type hints required by subsequent type hints below.

CallableAny = Callable[..., Any]
'''
PEP-compliant type hint matching any callable in a manner explicitly matching
all possible callable signatures.
'''

# ....................{ PEP 484 ~ typevar : early          }....................
# Type variables required by subsequent type hints below.

BeartypeableT = TypeVar(
    'BeartypeableT',
    # The @beartype decorator decorates objects that are either...
    #
    # Note that this hint *MUST* be defined as an obsolete PEP 484-compliant old
    # union rather than a PEP 604-compliant new union to avoid static
    # type-checker complaints resembling:
    #     beartype/_data/typing/datatyping.py:267: error: Type variable
    #     "beartype._data.typing.datatyping.BeartypeableT" is invalid as target
    #     for type alias  [misc]
    bound=Union[
        # Arbitrary class *OR*...
        type,

        # Arbitrary callable *OR*...
        CallableAny,

        # C-based unbound class method descriptor (i.e., a pure-Python unbound
        # function decorated by the builtin @classmethod decorator) *OR*...
        MethodDecoratorClassType,

        # C-based unbound property method descriptor (i.e., a pure-Python
        # unbound function decorated by the builtin @property decorator) *OR*...
        MethodDecoratorPropertyType |

        # C-based unbound static method descriptor (i.e., a pure-Python
        # unbound function decorated by the builtin @staticmethod decorator).
        MethodDecoratorStaticType,

        #FIXME: Currently unused, but preserved for posterity.
        # # C-based bound method descriptor (i.e., a pure-Python unbound
        # # function bound to an object instance on Python's instantiation of that
        # # object) *OR*...
        # MethodBoundInstanceOrClassType,
    ],
)
'''
:pep:`484`-compliant **generic beartypeable type variable** (i.e., type hint
matching any arbitrary object decoratable by the :func:`beartype.beartype`
decorator, including pure-Python callables and classes, C-based descriptors, and
even more exotic objects).

This type variable notifies static analysis performed by both static type
checkers (e.g., :mod:`mypy`) and type-aware IDEs (e.g., VSCode) that the
:func:`beartype.beartype` decorator preserves:

* Callable signatures by creating and returning callables with the same
  signatures as passed callables.
* Class hierarchies by preserving passed classes with respect to inheritance,
  including metaclasses and method-resolution orders (MRO) of those classes.
'''

# ....................{ CALLABLE                           }....................
# Callable-specific type hints *NOT* required by subsequent type hints below.

CallableRaiser = Callable[[object], None]
'''
PEP-compliant type hint matching a **raiser callable** (i.e., arbitrary callable
accepting a single arbitrary object and either raising an exception or emitting
a warning rather than returning any value).
'''


CallableRaiserOrTester = Callable[[object], bool | None]
'''
PEP-compliant type hint matching a **raiser or tester callable** (i.e.,
arbitrary callable accepting a single arbitrary object and either returning no
value or returning either :data:`True` if that object satisfies an arbitrary
constraint *or* :data:`False` otherwise).
'''


CallableStrFormat = Callable[..., str]
'''
PEP-compliant type hint matching the signature of the standard
:meth:`str.format` method.
'''


CallableTester = Callable[[object], bool]
'''
PEP-compliant type hint matching a **tester callable** (i.e., arbitrary callable
accepting a single arbitrary object and returning either :data:`True` if that
object satisfies an arbitrary constraint *or* :data:`False` otherwise).
'''


Codeobjable = Callable | CodeType | FrameType | GeneratorType
'''
PEP-compliant type hint matching a **codeobjable** (i.e., pure-Python object
directly associated with a code object and thus safely passable as the first
parameter to the :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj`
getter retrieving the code object associated with this codeobjable).

Specifically, this hint matches:

* Code objects.
* Pure-Python callables, including generators (but *not* C-based callables,
  which lack code objects).
* Pure-Python callable stack frames.
'''

# ....................{ CALLABLE ~ args                    }....................
CallableMethodGetitemArg = int | slice
'''
PEP-compliant type hint matching the standard type of the single positional
argument accepted by the ``__getitem__` dunder method.
'''

# ....................{ CALLABLE ~ decorator               }....................
BeartypeConfedDecorator = Callable[[BeartypeableT], BeartypeableT]
'''
PEP-compliant type hint matching a **configured beartype decorator** (i.e.,
closure created and returned from the :func:`beartype.beartype` decorator when
passed a beartype configuration via the optional ``conf`` parameter rather than
an arbitrary object to be decorated via the optional ``obj`` parameter).
'''


# Note that this hint *MUST* be defined as an obsolete PEP 484-compliant old
# union rather than a PEP 604-compliant new union to avoid static type-checker
# complaints resembling:
#     beartype/_decor/decormain.py:106: error: Variable
#         "beartype._data.typing.datatyping.BeartypeReturn" is not valid as a
#         type  [valid-type]
#     beartype/_decor/decormain.py:106: note: See
#         https://mypy.readthedocs.io/en/stable/common_issues.html#variables-vs-type-aliases
BeartypeReturn = Union[BeartypeableT, BeartypeConfedDecorator]
'''
PEP-compliant type hint matching any possible value returned by any invocation
of the :func:`beartype.beartype` decorator, including calls to that decorator
in both configuration and decoration modes.
'''

# ....................{ CALLABLE ~ descriptor              }....................
MethodDescriptorBuiltin = (
    # C-based unbound class method descriptor (i.e., a pure-Python unbound
    # function decorated by the builtin @classmethod decorator).
    MethodDecoratorClassType |

    # C-based unbound property method descriptor (i.e., a pure-Python unbound
    # function decorated by the builtin @property decorator).
    MethodDecoratorPropertyType |

    # C-based unbound static method descriptor (i.e., a pure-Python unbound
    # function decorated by the builtin @staticmethod decorator).
    MethodDecoratorStaticType
)
'''
PEP-compliant type hint matching any **builtin unbound method descriptor**
(i.e., C-based decorator type builtin to Python whose instance is typically
uncallable but encapsulates a callable pure-Python method).
'''


MethodDescriptorNondata = (
    # C-based unbound class method descriptor (i.e., a pure-Python unbound
    # function decorated by the builtin @classmethod decorator).
    MethodDecoratorClassType |

    # C-based unbound static method descriptor (i.e., a pure-Python unbound
    # function decorated by the builtin @staticmethod decorator).
    MethodDecoratorStaticType |

    # C-based bound method descriptor (i.e., a pure-Python unbound function
    # bound to an object instance on Python's instantiation of that object).
    MethodBoundInstanceOrClassType
)
'''
PEP-compliant type hint matching any **builtin method non-data descriptor**
(i.e., C-based descriptor builtin to Python defining only the ``__get__()``
dunder method, encapsulating read-only access to some kind of method).
'''

# ....................{ COLLECTION                         }....................
CollectionStrs = Collection[str]
'''
PEP-compliant type hint matching *any* collection of zero or more strings.
'''

# ....................{ DICT                               }....................
DictTypeToAny = Dict[type, Any]
'''
PEP-compliant type hint matching a dictionary mapping from types to arbitrary
objects.
'''

# ....................{ DICT ~ str                         }....................
DictStrToAny = Dict[str, Any]
'''
PEP-compliant type hint matching a dictionary mapping from strings to arbitrary
objects.
'''


DictStrToType = Dict[str, type]
'''
PEP-compliant type hint matching a dictionary mapping from strings to types.
'''


DictStrToFrozenSetStrs = Dict[str, FrozenSet[str]]
'''
PEP-compliant type hint matching a dictionary mapping from strings to frozen
sets of strings.
'''

# ....................{ CHAINMAP ~ str                     }....................
ChainMapStrToAny = ChainMap[str, Any]
'''
PEP-compliant type hint matching a chain map mapping from strings to arbitrary
objects.
'''

# ....................{ LIST                               }....................
ListStrs = List[str]
'''
PEP-compliant type hint matching a list of strings.
'''

# ....................{ MAPPING                            }....................
MappingStrToAny = Mapping[str, object]
'''
PEP-compliant type hint matching a mapping mapping from keys to arbitrary
objects.
'''

# ....................{ SIGN                               }....................
HintSignOrNoneOrSentinel = HintSign | None | Iota
'''
PEP-compliant type hint matching either a **sign** (i.e., :class:`.HintSign`
object uniquely identifying type hint), the :data:`None` singleton, or the
sentinel placeholder.
'''

# ....................{ SIGN ~ container                   }....................
FrozenSetHintSign = FrozenSet[HintSign]
'''
PEP-compliant type matching matching a frozen set of **signs** (i.e.,
:class:`.HintSign` objects uniquely identifying type hints).
'''


IterableHintSign = Iterable[HintSign]
'''
PEP-compliant type matching matching a iterable of **signs** (i.e.,
:class:`.HintSign` objects uniquely identifying type hints).
'''

# ....................{ SIGN ~ container : dict            }....................
DictStrToHintSign = Dict[str, HintSign]
'''
PEP-compliant type hint matching a dictionary mapping from strings to **signs**
(i.e., :class:`.HintSign` objects uniquely identifying type hints).
'''


HintSignTrie = Dict[str, Union[HintSign, 'HintSignTrie']]
'''
PEP-compliant type hint matching a **sign trie** (i.e.,
dictionary-of-dictionaries tree data structure enabling efficient mapping from
the machine-readable representations of type hints created by an arbitrary
number of type hint factories defined by an external third-party package to
their identifying sign).
'''


HintSignToCallableStrFormat = Dict[HintSign, CallableStrFormat]
'''
PEP-compliant type hint matching a **sign-to-string-formatter map** (i.e.,
dictionary mapping from signs uniquely identifying type hints to
:meth:`str.format` methods bound to code snippets type-checking various aspects
of those type hints).
'''

# ....................{ CODE                               }....................
LexicalScope = DictStrToAny
'''
PEP-compliant type hint matching a **lexical scope** (i.e., dictionary mapping
from the relative unqualified name to value of each locally or globally scoped
attribute accessible to a callable or class).
'''


CodeGenerated = Tuple[str, LexicalScope, Tuple[str, ...]]
'''
PEP-compliant type hint matching **generated code** (i.e., a tuple containing
a Python code snippet dynamically generated on-the-fly by a
:mod:`beartype`-specific code generator and metadata describing that code).

Specifically, this hint matches a 3-tuple ``(func_wrapper_code,
func_wrapper_scope, hint_refs_type_basename)``, where:

* ``func_wrapper_code`` is a Python code snippet type-checking an arbitrary
  object against this hint. For the common case of code generated for a
  :func:`beartype.beartype`-decorated callable, this snippet type-checks a
  previously localized parameter or return value against this hint.
* ``func_wrapper_scope`` is the **local scope** (i.e., dictionary mapping from
  the name to value of each attribute referenced one or more times in this code)
  of the body of the function embedding this code.
* ``hint_refs_type_basename`` is a tuple of the unqualified classnames
  of :pep:`484`-compliant relative forward references visitable from this hint
  (e.g., ``('MuhClass', 'YoClass')`` given the hint ``Union['MuhClass',
  List['YoClass']]``).
'''

# ....................{ ITERABLE                           }....................
IterableStrs = Iterable[str]
'''
PEP-compliant type hint matching *any* iterable of zero or more strings.
'''

# ....................{ ITERATOR                           }....................
EnumeratorItem = Tuple[int, object]
'''
PEP-compliant type hint matching *any* **enumerator item** (i.e., item of the
iterator created and returned by the :func:`enumerate` builtin). An enumerator
item is a 2-tuple of the form ``(item_index, item)``, where:

* ``item_index`` is the 0-based index of the currently enumerated item.
* ``item`` is the currently enumerated item.
'''


Enumerator = Iterator[EnumeratorItem]
'''
PEP-compliant type hint matching *any* **enumerator** (i.e., arbitrary iterator
satisfying the :func:`enumerate` protocol). This iterator is expected to yield
zero or more 2-tuples of the form ``(item_index, item)``, where:

* ``item_index`` is the 0-based index of the currently enumerated item.
* ``item`` is the currently enumerated item.
'''

# ....................{ OBJECT                             }....................
GetObjectAttrsDir = List[str] | None
'''
PEP-compliant type hint matching the ``obj_dir`` parameter accepted by all
**object attribute getters** (e.g.,
:func:`beartype._util.utilobject.get_object_attrs_name_to_value_explicit`).
'''


GetObjectAttrsPredicate = Callable[[str, object], bool] | None
'''
PEP-compliant type hint matching the ``predicate`` parameter accepted by all
**object attribute getters** (e.g.,
:func:`beartype._util.utilobject.get_object_attrs_name_to_value_explicit`).
'''

# ....................{ PATH                               }....................
CommandWords = IterableStrs
'''
PEP-compliant type hint matching **command words** (i.e., an iterable of one or
more shell words comprising a shell command, suitable for passing as the
``command_words`` parameter accepted by most callables declared in the
test-specific :mod:`beartype_test._util.command.pytcmdrun` submodule).
'''

# ....................{ SET                                }....................
SetStrs = Set[str]
'''
PEP-compliant type hint matching *any* mutable set of zero or more strings.
'''

# ....................{ SET ~ frozenset                    }....................
FrozenSetInts = FrozenSet[int]
'''
PEP-compliant type hint matching *any* frozen set of zero or more integers.
'''


FrozenSetStrs = FrozenSet[str]
'''
PEP-compliant type hint matching *any* frozen set of zero or more strings.
'''


FrozenSetTypes = FrozenSet[type]
'''
PEP-compliant type hint matching *any* frozen set of zero or more types.
'''

# ....................{ TYPE                               }....................
AbstractSetTypes = AbstractSet[type]
'''
:pep:`585`-compliant type hint matching *any* set of zero or more classes.
'''


IterableTypes = Iterable[type]
'''
PEP-compliant type hint matching an iterable of zero or more types.
'''


SetTypes = Set[type]
'''
PEP-compliant type hint matching a mutable set of zero or more types.
'''


TupleTypes = Tuple[type, ...]
'''
:pep:`585`-compliant type hint matching a tuple of zero or more classes.

Equivalently, this hint matches all tuples passable as the second parameters to
the :func:`isinstance` and :func:`issubclass` builtins.
'''


IsBuiltinOrSubclassableTypes = type | TupleTypes | HintPep604Type
'''
PEP-compliant type hint matching any objects passable as the second parameter
to the :func:`isinstance` and :func:`issubclass` builtins.

Specifically, this hint matches either:

* A single type.
* A tuple of zero or more types.
* A :pep:`604`-compliant **new union** (i.e., two or more types delimited by the
  ``|`` operator under Python >= 3.10).
'''


SetOrTupleTypes = TupleTypes | AbstractSetTypes
'''
PEP-compliant type hint matching a set *or* tuple of zero or more types.
'''


TypeOrTupleTypes = type | TupleTypes
'''
PEP-compliant type hint matching either a type *or* tuple of zero or more types.
'''


TypeOrSetOrTupleTypes = type | TupleTypes | AbstractSetTypes
'''
PEP-compliant type hint matching either a type *or* set or tuple of zero or more
types.
'''


TypeStack = TupleTypes | None
'''
PEP-compliant type hint matching a **type stack** (i.e., either tuple of zero or
more arbitrary types *or* :data:`None`).

Objects matched by this hint are guaranteed to be either:

* If the **beartypeable** (i.e., object currently being decorated by the
  :func:`beartype.beartype` decorator) is an attribute (e.g., method, nested
  class) of a class currently being decorated by that decorator, the **type
  stack** (i.e., tuple of one or more lexically nested classes that are either
  currently being decorated *or* have already been decorated by this decorator
  in descending order of top- to bottom-most lexically nested) such that:

  * The first item of this tuple is expected to be the **root decorated class**
    (i.e., module-scoped class initially decorated by this decorator whose
    lexical scope encloses this beartypeable).
  * The last item of this tuple is expected to be the **current decorated
    class** (i.e., possibly nested class currently being decorated by this
    decorator).

* Else, this beartypeable was decorated directly by this decorator. In this
  case, :data:`None`.

Parameters annotated by this hint typically default to :data:`None`.

Note that :func:`beartype.beartype` requires *both* the root and currently
decorated class to correctly resolve edge cases under :pep:`563`: e.g.,

.. code-block:: python

   from __future__ import annotations
   from beartype import beartype

   @beartype
   class Outer(object):
       class Inner(object):
           # At this time, the "Outer" class has been fully defined but is *NOT*
           # yet accessible as a module-scoped attribute. Ergo, the *ONLY* means
           # of exposing the "Outer" class to the recursive decoration of this
           # get_outer() method is to explicitly pass the "Outer" class as the
           # "cls_root" parameter to all decoration calls.
           def get_outer(self) -> Outer:
               return Outer()

Note also that nested classes have *no* implicit access to either their parent
classes *or* to class variables declared by those parent classes. Nested classes
*only* have explicit access to module-scoped classes -- exactly like any other
arbitrary objects: e.g.,

.. code-block:: python

   class Outer(object):
       my_str = str

       class Inner(object):
           # This induces a fatal compile-time exception resembling:
           #     NameError: name 'my_str' is not defined
           def get_str(self) -> my_str:
               return 'Oh, Gods.'

Ergo, the *only* owning class of interest to :mod:`beartype` is the root owning
class containing other nested classes; *all* of those other nested classes are
semantically and syntactically irrelevant. Nonetheless, this tuple intentionally
preserves *all* of those other nested classes. Why? Because :pep:`563`
resolution can only find the parent callable lexically containing that nested
class hierarchy on the current call stack (if any) by leveraging the total
number of classes lexically nesting the currently decorated class as input
metadata, as trivially provided by the length of this tuple.
'''

# ....................{ MODULE ~ beartype                  }....................
#FIXME: mypy used to type-check this properly. Pyright never did. But even mypy
#1.19.0 no longer accepts this. Weird stuff. Oh, well... who cares, huh?
BeartypeForwardRef = Type[
    'beartype._check.forward.reference.fwdrefabc.BeartypeForwardRefABC']   # type: ignore[name-defined]
'''
PEP-compliant type hint matching a **forward reference proxy** (i.e., concrete
subclass of the abstract
:class:`beartype._check.forward.reference.fwdrefabc.BeartypeForwardRefABC`
superclass).
'''


BeartypeForwardRefArgs = Tuple[str | None, str, TupleTypes]
'''
PEP-compliant type hint matching a **forward reference proxy argument list**
(i.e., tuple of all parameters passed to each call of the low-level private
:func:`beartype._check.forward.reference.fwdrefmake._make_forwardref_subtype`
factory function, in the same order as positionally accepted by that function).
'''

# ....................{ MODULE ~ importlib                 }....................
# Type hints specific to the standard "importlib" package.

ImportPathHook = Callable[[str], PathEntryFinder]
'''
PEP-compliant type hint matching an **import path hook** (i.e., factory closure
creating and returning a new :class:`importlib.abc.PathEntryFinder` instance
creating and leveraging a new :class:`importlib.machinery.FileLoader` instance).
'''

# ....................{ MODULE ~ pathlib                   }....................
# Type hints specific to the standard "pathlib" package.

PathnameLike = str | Path
'''
PEP-compliant type hint matching a **pathname-like object** (i.e., either a
low-level string possibly signifying a pathname *or* a high-level :class:`Path`
instance definitely encapsulating a pathname).
'''


#FIXME: Shift into the "_cavefast" submodule, please. *sigh*
PathnameLikeTuple = (str, Path)
'''
2-tuple of the types of all **pathname-like objects** (i.e., either
low-level strings possibly signifying pathnames *or* high-level :class:`Path`
instances definitely encapsulating pathnames).
'''

# ....................{ PEP ~ 484                          }....................
# Type hints required to fully comply with PEP 484.
#
# Note that type unions are intentionally defined to preferably be PEP
# 604-compliant (e.g., "float | int"). Why? Because obsolete PEP 484-compliant
# type unions (e.g., "Union[float, int]") fail to support various edge cases,
# including recursive "beartype.HintOverrides" globally defined by the
# "beartype._conf._confoverrides" submodule.

Pep484TowerComplex = complex | float | int
'''
:pep:`484`-compliant type hint matching the **implicit complex tower** (i.e.,
complex numbers, floating-point numbers, and integers).
'''


Pep484TowerFloat = float | int
'''
:pep:`484`-compliant type hint matching the **implicit floating-point tower**
(i.e., both floating-point numbers and integers).
'''

# ....................{ PEP ~ 484 : typevar                }....................
T = TypeVar('T')
'''
**Unbound type variable** (i.e., matching *any* arbitrary type) locally bound to
different types throughout the :mod:`beartype` codebase.
'''


CallableT = TypeVar('CallableT', bound=CallableABC)
'''
**Callable type variable** (i.e., bound to match *only* callables).
'''


NodeT = TypeVar('NodeT', bound=AST)
'''
**Node type variable** (i.e., type variable constrained to match *only* abstract
syntax tree (AST) nodes).
'''

# ....................{ PEP ~ 484 : typevar : container    }....................
SetTypeVars = Set[TypeVar]
'''
:pep:`585`-compliant type hint matching a mutable set of zero or more
:pep:`484`-compliant **type variables** (i.e., :class:`.TypeVar` objects).
'''


TupleTypeVars = Tuple[TypeVar, ...]
'''
:pep:`585`-compliant type hint matching a tuple of zero or more
:pep:`484`-compliant **type variables** (i.e., :class:`.TypeVar` objects).
'''

# ....................{ PEP ~ (484|585)                    }....................
# Type hints required to fully comply with both PEP 484 *AND* 585.

Pep484585ForwardRef = str | ForwardRef
'''
Union of all :pep:`484`- or :pep:`585`-compliant **forward reference types**
(i.e., classes of all forward reference objects).

See Also
--------
:data:`.HINT_PEP484585_FORWARDREF_TYPES`
    Further details.
'''

# ....................{ PEP ~ (484|612|646)                }....................
# Type hints required to fully comply with PEP 484, 612, and 646 -- the
# standards collectively covering type parameters.

Pep484612646TypeArgPacked = (
    TypeVar | HintPep612ParamSpecType | HintPep646TypeVarTupleType)
'''
PEP-compliant type hint matching a :pep:`484`-, pep:`612`-, or
:pep:`646`-compliant **packed type parameter** (i.e., :pep:`484`-compliant type
variable, pep:`612`-compliant parameter specification, or :pep:`646`-compliant
type variable tuple).
'''


Pep484612646TypeArgUnpacked = TypeVar | HintPep646692UnpackedType
'''
:pep:`484`-compliant union matching a :pep:`484`-, pep:`612`-, or
:pep:`646`-compliant **type parameter** (i.e., :pep:`484`-compliant type
variable, :pep:`612`-compliant unpacked parameter specification, or
:pep:`646`-compliant unpacked type variable tuple).

This hint intentionally matches :pep:`646`-compliant unpacked type variable
tuples (e.g., ``*Ts``) rather than merely :pep:`646`-compliant type variable
tuples (e.g., ``Ts`` where ``Ts = typing.TypeVarTuple('Ts')``). Since Python
requires that *all* type variable tuples be unpacked, matching type variable
tuples in non-unpacked form is (largely) useless.

This hint unintentionally matches :pep:`692`-compliant unpacked typed
dictionaries (e.g., ``typing.Unpack[TypedDict[{}]]``) as well. Although this
hint invites ambiguous false negatives and should thus be used with caution,
this hint is still preferable to even more ambiguous alternatives like
:obj:`typing.Any` or :class:`object`.
'''


TuplePep484612646TypeArgsPacked = Tuple[Pep484612646TypeArgPacked, ...]
'''
:pep:`585`-compliant type hint matching a tuple of zero or more **packed type
parameters** (i.e., :pep:`484`-compliant type variables, pep:`612`-compliant
parameter specifications, or :pep:`646`-compliant type variable tuples).
'''


TuplePep484612646TypeArgsUnpacked = Tuple[Pep484612646TypeArgUnpacked, ...]
'''
:pep:`585`-compliant type hint matching a tuple of zero or more :pep:`484`-,
pep:`612`-, or :pep:`646`-compliant **unpacked type parameters** (i.e.,
:pep:`484`-compliant type variables, :pep:`612`-compliant unpacked parameter
specification, or :pep:`646`-compliant unpacked type variable tuples).
'''

# ....................{ PEP ~ 649                          }....................
# Objects defining PEP 649-compliant __annotate__() dunder methods are either...
Pep649Hintable = type | Callable | ModuleType
'''
:pep:`649`-compliant type hint matching any **hintable** (i.e., ideally
pure-Python object defining the ``__annotations__`` dunder attribute as well as
the :pep:`649`-compliant ``__annotate__`` dunder method if the active Python
interpreter targets Python >= 3.14).
'''


Pep649HintableAnnotations = DictStrToAny
'''
:pep:`649`-compliant type hint matching any **hintable annotations** (i.e.,
dictionary mapping from the name of each annotated parameter or return of a
callable *or* annotated variable of a class or module to the type hint
annotating that parameter, return, or variable).
'''

# ....................{ PEP ~ 695                          }....................
Pep695Parameterizable = type | FunctionType | HintPep695TypeAlias
'''
:pep:`695`-compliant type hint matching *any* :pep:`695` **parameterizable**
(i.e., object that may be parametrized by a :pep:`695`-compliant list of one or
more implicitly instantiated :pep:`484`-compliant type variables,
pep:`612`-compliant parameter specifications, or :pep:`646`-compliant type
variable tuples).

Specifically, this hint matches:

* *Any* pure-Python class.
* *Any* pure-Python function.
* *Any* :pep:`695`-compliant type alias.
'''

# ....................{ TYPE                               }....................
TypeException = Type[Exception]
'''
PEP-compliant type hint matching *any* exception class.
'''


TypeWarning = Type[Warning]
'''
PEP-compliant type hint matching *any* warning category.
'''
