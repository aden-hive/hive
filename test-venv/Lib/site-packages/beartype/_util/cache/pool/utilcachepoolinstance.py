#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Typed object pool** (i.e., submodule whose thread-safe API caches previously
instantiated objects of arbitrary types for space- and time-efficient reuse by
the :func:`beartype.beartype` decorator across decoration calls).

This private submodule is *not* intended for importation by downstream callers.

Caveats
-------
**This submodule only pools objects defining an** ``__init__()`` **method
accepting no parameters.** Why? Because this submodule unconditionally pools
all objects of the same types under those types. This submodule provides *no*
mechanism for pooling objects of the same types under different parameters
instantiated with those parameters and thus only implements a coarse- rather
than fine-grained object cache. If insufficient, consider defining a new
submodule implementing a fine-grained object cache unique to those objects. For
example:

* This submodule unconditionally pools all instances of the
  :class:`beartype._check.metadata.metadecor.BeartypeDecorMeta` class under that
  type.
* The parallel :mod:`beartype._util.cache.pool.utilcachepoollistfixed`
  submodule conditionally pools every instance of the
  :class:`beartype._util.cache.pool.utilcachepoollistfixed.FixedList` class of
  the same length under that length.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Any,
    Type,
)
from beartype._data.cls.datacls import TYPES_BUILTIN_CONTAINER_MUTABLE
from beartype._data.typing.datatyping import T
from beartype._util.cache.pool.utilcachepool import KeyPool

# ....................{ (ACQUIRERS|RELEASERS)              }....................
def acquire_instance(cls: Type[T]) -> T:
    '''
    Acquire an arbitrary object of the passed type.

    If this type is that of a **builtin mutable container** (i.e.,
    :class:`bytearray`, :class:`dict`, :class:`list`, :class:`set`), this
    function guarantees the returned container to be empty. Specifically, this
    function internally calls the ``clear()`` method of this container *before*
    returning this container.

    Caveats
    -------
    **The contents of this object are otherwise arbitrary.** Aside from the
    aforementioned call to the ``clear()`` method of builtin mutable containers,
    callers should make *no* assumptions as to this object's state. Instead,
    callers should reinitialize this object immediately after acquiring this
    object.

    Parameters
    ----------
    cls : Type[T]
        Type of the object to be acquired.

    Returns
    -------
    T
        Arbitrary object of this type.
    '''
    assert isinstance(cls, type), f'{repr(cls)} not type.'

    # Thread-safely acquire an object of this type.
    instance = _instance_pool_acquire(cls)  # type: ignore[arg-type]
    # assert isinstance(instance, cls), (
    #     '{!r} not a {!r}.'.format(instance, cls))

    # If this type is that of a builtin mutable container (i.e., "bytearray",
    # "dict", "list", "set"), safely empty this container on behalf of the
    # caller. Since all callers requesting a builtin mutable container prefer
    # this container to be empty *AND* since detecting builtin mutable container
    # types is trivially fast, we do so on behalf of the caller.
    if cls in TYPES_BUILTIN_CONTAINER_MUTABLE:
        instance.clear()  # type: ignore[attr-defined]
    # Else, this type is *NOT* that of a builtin mutable container. In this
    # case, preserve this instance as is.

    # Return this object.
    return instance  # type: ignore[return-value]


def release_instance(obj: Any) -> None:
    '''
    Release the passed object acquired by a prior call to the
    :func:`acquire_instance` function.

    Caveats
    -------
    **This object is not safely accessible after calling this function.**
    Callers should make *no* attempts to read, write, or otherwise access this
    object, but should instead nullify *all* variables referring to this object
    immediately after releasing this object (e.g., by setting these variables
    to the ``None`` singleton *or* by deleting these variables).

    Parameters
    ----------
    obj : object
        Previously acquired object to be released.
    '''

    # Thread-safely release this object.
    #
    # Note that we intentionally pass parameters positionally rather than by
    # keyword as a negligible microoptimization.
    _instance_pool_release(obj, obj.__class__)

# ....................{ SINGLETONS ~ private               }....................
_instance_pool = KeyPool(item_maker=lambda cls: cls())
'''
Thread-safe **typed object pool** (i.e., :class:`.KeyPool` singleton caching
previously instantiated objects of the same types under those types).

Caveats
-------
**Avoid accessing this private singleton externally.** Instead, call the public
:func:`acquire_instance` and :func:`release_instance` functions, which
efficiently validate both input *and* output to conform to sane expectations.
'''


_instance_pool_acquire = _instance_pool.acquire
'''
:meth:`.KeyPool.acquire` method bound to the :data:`._object_type_pool`,
globalized as a negligible microoptimization.
'''


_instance_pool_release = _instance_pool.release
'''
:meth:`.KeyPool.release` method bound to the :data:`._object_type_pool`,
globalized as a negligible microoptimization.
'''
