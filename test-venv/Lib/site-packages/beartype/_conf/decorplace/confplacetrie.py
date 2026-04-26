#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **abstract syntax tree (AST) scope decorator position frozen dictionary
class hierarchy** (i.e., private classes implementing immutable mappings that
convey hierarchically-structured metadata unique to the beforelist automating
decorator positioning for scopes recursively visited by AST transformers).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._util.kind.maplike.utilmapfrozen import FrozenDict

# ....................{ SUBCLASSES                         }....................
class BeartypeDecorPlaceTrieABC(FrozenDict):
    '''
    Beartype **decorator position trie abstract base class (ABC)** (i.e.,
    superclass of all recursive tree structures describing third-party
    decorators known to be hostile to the :func:`beartype.beartype` decorator).
    '''

    pass


class BeartypeDecorPlacePackagesTrie(BeartypeDecorPlaceTrieABC):
    '''
    Beartype **decorator position packages trie** (i.e., recursive tree
    structure describing third-party packages and modules known to be hostile to
    the :func:`beartype.beartype` decorator, such that those packages and
    modules all transitively define one or more decorator-hostile decorators).

    This trie is defined as a frozen dictionary mapping from the name of each
    third-party root (i.e., non-nested) package or module transitively defining
    one or more such decorator-hostile decorators to a nested
    :class:`.BeartypeDecorPlacePackageTrie` frozen dictionary describing the
    problematic contents of that package or module.
    '''

    pass


class BeartypeDecorPlacePackageTrie(BeartypeDecorPlaceTrieABC):
    '''
    Beartype **decorator position (sub)package trie** (i.e., recursive tree
    structure describing the problematic contents of third-party packages and
    modules known to be hostile to the :func:`beartype.beartype` decorator, such
    that those packages and modules all transitively define one or more
    decorator-hostile decorators).

    This trie is defined as a frozen dictionary mapping from the unqualified
    basename of each attribute of a third-party (sub)package transitively
    defining one or more such decorator-hostile decorators to either:

    * :data:`None`, in which case the corresponding key is the unqualified
      basename of a decorator-hostile decorator function directly defined by
      that (sub)package. :data:`None` thus signifies a terminal leaf node
      terminating the recursive tree structure.
    * A recursively nested :class:`.BeartypeDecorPlaceTypeTrie` frozen
      dictionary, in which case the corresponding key is the unqualified
      basename of a type directly defined by that (sub)package. That type is
      then assumed to define one or more decorator-hostile decorator methods.
    * A recursively nested :class:`.BeartypeDecorPlaceInstanceTrie` frozen
      dictionary, in which case the corresponding key is the unqualified
      basename of an arbitrary instance directly defined by that (sub)package.
      That object is then assumed to define one or more decorator-hostile
      decorator methods bound to that instance.
    '''

    pass


class BeartypeDecorPlaceTypeTrie(BeartypeDecorPlaceTrieABC):
    '''
    Beartype **decorator position type trie** (i.e., non-recursive tree
    structure describing all third-party types known to be hostile to the
    :func:`beartype.beartype` decorator, such that those types all directly
    define one or more decorator-hostile decorator methods).

    This trie is defined as a frozen dictionary mapping from the unqualified
    basename of each decorator-hostile decorator method of a third-party type to
    :data:`None` -- signifying a terminal leaf node terminating this tree
    structure.
    '''

    pass


class BeartypeDecorPlaceInstanceTrie(BeartypeDecorPlaceTrieABC):
    '''
    Beartype **decorator position instance trie** (i.e., non-recursive tree
    structure describing all third-party instances known to be hostile to the
    :func:`beartype.beartype` decorator, such that those instances all directly
    define one or more decorator-hostile decorator methods bound to those
    instances).

    This trie is defined as a frozen dictionary mapping from the unqualified
    basename of each decorator-hostile decorator method of a third-party
    instance to :data:`None` -- signifying a terminal leaf node terminating this
    tree structure.
    '''

    pass
