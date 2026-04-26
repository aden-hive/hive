#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **third-party module globals** (i.e., global constants broadly
concerning various third-party modules and packages rather than one specific
third-party module or package).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.typing.datatyping import DictStrToFrozenSetStrs
from beartype._util.kind.maplike.utilmapfrozen import FrozenDict

# ....................{ DICTS                              }....................
BLACKLIST_MODULE_NAME_TO_TYPE_NAMES: DictStrToFrozenSetStrs = FrozenDict({
    # ....................{ ANTIPATTERN ~ decor-hostile    }....................
    # These third-party packages and modules widely employ the decorator-hostile
    # decorator antipattern throughout their codebases and are thus
    # runtime-hostile.

    # The object-oriented @fastmcp.FastMCP.tool decorator method destructively
    # transforms callable user-defined functions and methods into *UNCALLABLE*
    # FastMCP-specific instances of this type. Why, FastMCP!? WHY!?!!?? *sigh*
    'fastmcp.tools.tool': frozenset(('FunctionTool',)),

    # The object-oriented @langchain_core.runnables.chain decorator method
    # destructively transforms callable user-defined functions and methods into
    # *UNCALLABLE* LangChain-specific instances of this type. Why, LangChain!?!
    'langchain_core.runnables.base': frozenset(('RunnableLambda',)),
})
'''
Frozen dictionary mapping from the fully-qualified name of each problematic
third-party package and module to a frozen set of the unqualified basenames of
all **beartype-blacklisted types** defined by that package or module. These
types are well-known to be hostile to runtime type-checking in general and
:mod:`beartype` specifically, usually due to employing one or more of the
following antipatterns:

* The **decorator-hostile decorator antipattern,** a harmful design pattern
  unofficially promoted throughout the large language model (LLM) community.
  This antipattern abuses the standard PEP-compliant decorator paradigm (which
  supports decorator chaining by permitting arbitrary decorators to be applied
  to other decorators) by prohibiting decorator chaining. Many open-source LLM
  APIs, for example, define decorator-hostile decorators destructively transform
  callable user-defined functions and methods into uncallable instances of
  non-standard types usable *only* by those APIs. Due to being uncallable *and*
  non-standard, those instances then obstruct trivial wrapping by the
  :func:`beartype.beartype` decorator.
'''


BLACKLIST_TYPE_MRO_ROOT_MODULE_NAME_TO_TYPE_NAMES: DictStrToFrozenSetStrs = (
    FrozenDict({
        # ....................{ ANTIPATTERN ~ decor-hostile    }....................
        # These third-party packages and modules widely employ the decorator-hostile
        # decorator antipattern throughout their codebases and are thus
        # runtime-hostile.

        # The object-oriented @celery.Celery.task decorator method transforms
        # callable user-defined functions and methods into callable
        # Celery-specific instances of this type, known as Celery tasks. For
        # better or worse, Celery tasks masquerade as the user-defined callables
        # they wrap and thus are *ONLY* accessible as the root MRO item:
        #     # Define a trivial Celery task.
        #     >>> from celery import Celery
        #     >>> celery_server = Celery(broker='memory://')
        #     >>> @celery_server.task()
        #     >>> def muh_celery_task() -> None: pass
        #
        #     # Prove that Celery tasks lie about everything.
        #     >>> muh_celery_task.__module__
        #     celery.local  # <-- weird, but okay
        #     >>> muh_celery_task.__name__
        #     muh_celery_task  # <-- *LIAR*! you're actually a "Task" instance!!
        #     >>> muh_celery_task.__class__.__module__
        #     __main__  # <-- *LIAR*! you're actually a "Task" instance!!
        #     >>> muh_celery_task.__class__.__name__
        #     muh_celery_task  # <-- *LIAR*! you're actually a "Task" instance!!
        #     >>> muh_celery_task.__class__.__mro__
        #     (<class '__main__.muh_celery_task'>, <class
        #     'celery.app.task.Task'>, <class 'celery.app.task.Task'>, <class
        #     'object'>)  # <-- *FINALLY*. at last. the truth is revealed.
        'celery.app.task': frozenset(('Task',)),
    }))
'''
Frozen dictionary mapping from the fully-qualified name of each problematic
third-party package and module to a frozen set of the unqualified basenames of
all **beartype-blacklisted types** defined by that package or module such that
these high-level types masquerade as the low-level user-defined callables that
they wrap, typically by an even higher-level decorator wrapping callables with
those types.

These types hide themselves from public view and thus are *only* accessible as
the **root method-resolution order (MRO) item** (i.e., second-to-last item of
the ``__mro__`` dunder dictionary of these types, thus ignoring the ignorable
:class:`object` guaranteed to be the last item of all such dictionaries).

See Also
--------
:data:`.BLACKLIST_MODULE_NAME_TO_TYPE_NAMES`
    Further details.
'''

# ....................{ SETS                               }....................
#FIXME: Apply this blacklist to the following things:
#* Arbitrary callables to be decorated by @beartype, possibly. Consider defining
#  a new beartype._util.bear.utilbearfunc.is_func_thirdparty_blacklisted()
#  tester returning True *ONLY* if the passed callable has a "__module__" dunder
#  attribute whose value is a string residing in this frozenset.
BLACKLIST_PACKAGE_NAMES = frozenset((
    # ....................{ ANTIPATTERN ~ forward ref      }....................
    # These third-party packages and modules widely employ the forward reference
    # antipattern throughout their codebases and are thus runtime-hostile.

    # Pydantic employs the forward reference antipattern everywhere: e.g.,
    #     from __future__ import annotations as _annotations
    #     import typing
    #     ...
    #
    #     if typing.TYPE_CHECKING:
    #         ...
    #         from ..main import BaseModel  # <-- undefined at runtime
    #
    #     ...
    #     def wrapped_model_post_init(
    #         self: BaseModel, context: Any, /) -> None:  # <-- unresolvable at runtime
    #
    # See also this @beartype-specific issue on Pydantic:
    #     https://github.com/beartype/beartype/issues/444
    'pydantic',

    # "urllib3" employs the forward reference antipattern everywhere: e.g.,
    #     import typing
    #     ...
    #
    #     if typing.TYPE_CHECKING:
    #         from typing import Final  # <-- undefined at runtime
    #
    #     ...
    #
    #     _DEFAULT_TIMEOUT: Final[_TYPE_DEFAULT] = _TYPE_DEFAULT.token
    #
    # See also this @beartype-specific comment on "urllib3":
    #     https://github.com/beartype/beartype/issues/223#issuecomment-2525261497
    'urllib3',

    # xarray employs the forward reference antipattern everywhere: e.g.,
    #     from __future__ import annotations
    #     from typing import IO, TYPE_CHECKING, Any, Generic, Literal, cast, overload
    #     ...
    #
    #     if TYPE_CHECKING:
    #         ...
    #         from xarray.core.dataarray import DataArray  # <-- undefined at runtime
    #
    #     ...
    #
    #     class Dataset(
    #         DataWithCoords,
    #         DatasetAggregations,
    #         DatasetArithmetic,
    #         Mapping[Hashable, "DataArray"],  # <-- unresolvable at runtime
    #     ):
    #
    # See also this @beartype-specific issue on xarray:
    #     https://github.com/beartype/beartype/issues/456
    'xarray',
))
'''
Frozen set of the fully-qualified names of all **beartype-blacklisted
third-party packages** well-known to be hostile to runtime type-checking in
general and :mod:`beartype` specifically, usually due to employing one or more
of the following antipatterns:

* The **forward reference antipattern,** a `harmful design pattern officially
  promoted throughout "mypy" documentation <antipattern_>`__. This antipattern
  leverages both :pep:`563` *and* the :pep:`484`-compliant
  :obj:`typing.TYPE_CHECKING` global (both of which are well-known to be hostile
  to runtime type-checking) to conditionally define relative forward references
  visible *only* to pure static type-checkers like ``mypy`` and ``pyright``.
  These references are undefined at runtime and thus inaccessible to hybrid
  runtime-static type-checkers like :mod:`beartype` and :mod:`typeguard`.

  As an example, consider this hypothetical usage of the forward reference
  antipattern in a mock third-party package named ``"awful_package"``:

  .. code-block:: python

     from __future__ import annotations  # <-- pep 563
     from typing import TYPE_CHECKING    # <-- pep 484

     if TYPE_CHECKING:                         # <---- "False" at runtime
         from awful_package import AwfulClass  # <-- undefined at runtime

     # PEP 563 (i.e., "from __future__ import annotations") stringifies the
     # undefined "AwfulClass" class to the string "'AwfulClass'" at runtime.
     # Since the "AwfulClass" class is undefined, however, neither @beartype nor
     # any other runtime type-checker can resolve this relative forward
     # reference to the external "awful_package.AwfulClass" class it refers to.
     def awful_func(awful_arg: AwfulClass): ...

.. _antipattern:
   https://mypy.readthedocs.io/en/latest/runtime_troubles.html#import-cycles
'''
