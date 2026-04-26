#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **abstract syntax tree (AST) scope beforelist** (i.e., low-level
dataclass aggregating all metadata required to manage the beforelist automating
decorator positioning for lexical scopes recursively visited by AST
transformers).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeConfParamException
from beartype.typing import (
    TYPE_CHECKING,
    ChainMap as ChainMapHint,
    Optional,
)
from beartype._cave._cavemap import NoneTypeOr
from beartype._data.conf.dataconfplace import (
    DECOR_HOSTILE_ATTR_NAME_TRIE,
    BeartypeDecorPlaceTrie,
    BeartypeDecorPlaceSubtrie,
)
from beartype._data.typing.datatyping import (
    FrozenSetStrs,
    TypeException,
)
from beartype._data.typing.datatypingport import TypeIs
from beartype._util.kind.maplike.utilmapfrozen import FrozenDict
from collections import ChainMap

# ....................{ HINTS                              }....................
ScopedAttrNameTrie = ChainMapHint[str, BeartypeDecorPlaceSubtrie]
'''
PEP-compliant recursive alias matching a **beforelist imported attribute name
trie** (i.e., recursive tree structure whose nodes are the unqualified basenames
of problematic third-party attributes imported into a scope of the currently
visited module, defined as a chain map mapping from strings to either the
:data:`None` singleton placeholder signifying a terminal leaf node *or* yet
another such recursively nested dictionary).
'''

# ....................{ CLASSES                            }....................
#FIXME: Unit test us up, please. *sigh*
class BeartypeNodeScopeBeforelist(object):
    '''
    Beartype **abstract syntax tree (AST) scoped beforelist** (i.e., low-level
    dataclass aggregating all metadata required to manage the beforelist
    automating decorator positioning for lexical scopes recursively visited by
    AST transformers).

    Attributes
    ----------
    schema_attr_basename_trie : BeartypeDecorPlaceTrie
        **Source attribute name trie schema** (i.e., recursive tree structure
        whose nodes are the unqualified basenames of third-party attributes that
        *could* possibly be imported into a scope of the currently visited
        module such that these attributes are either themselves
        decorator-hostile decorators *or* submodules transitively defining
        decorator-hostile decorators).

        This tree structure is internally consumed as input by the higher-level
        :class:`beartype.claw._ast._kind.clawastimport.BeartypeNodeTransformerImportMixin`
        transformer. This immutable tree structure is produced by dynamically
        merging the contents of the immutable
        :data:`.DECOR_HOSTILE_ATTR_NAME_TRIE` singleton with those of the
        immutable
        :attr:`beartype.BeartypeConf.claw_beforelist_decor_hostile_func_trie`
        configuration option.

        This tree structure is implemented as a frozen dictionary mapping from
        the unqualified basename of each third-party (sub)package and
        (sub)module transitively defining one or more decorator-hostile
        decorator functions to either a frozen set of the unqualified basenames
        of those functions *or* yet another such recursively nested frozen
        dictionary.
    schema_package_names : frozenset[str]
        **Source module name schema** (i.e., frozen set of the fully-qualified
        names of all root packages and modules transitively defining one or more
        decorator-hostile decorators).
    scoped_attr_basename_trie : Optional[ScopedAttrNameTrie]
        **Target scoped attribute name trie** (i.e., recursive tree structure
        whose nodes are the unqualified basenames of third-party attributes
        imported into a scope of the currently visited module such that these
        attributes are either themselves decorator-hostile decorators *or*
        submodules, types, or instances transitively defining decorator-hostile
        decorators).

        This tree structure is initially :data:`None`, in which case external
        callers are expected to explicitly initialize this attribute to the
        empty dictionary in a just-in-time (JIT) manner as needed.

        This tree structure is internally produced as output by the higher-level
        :class:`beartype.claw._ast._kind.clawastimport.BeartypeNodeTransformerImportMixin`
        transformer, serving as the glue between:

        * That transformer's visitor methods, which initially parse import
          statements importing decorator-hostile decorators into a scope of the
          currently visited module.
        * That transformer's decorator methods, which subsequently produce AST
          nodes injecting the :func:`beartype.beartype` decorator into chains of
          possibly decorator-hostile decorators decorating types and callables.

        This tree structure is implemented as a chain map mapping from strings
        to either the :data:`None` singleton placeholder signifying a leaf node
        terminating this recursion *or* yet another such recursively nested
        dictionary. This tree structure is intentionally implemented as a chain
        map of one or more dictionaries rather than as merely one dictionary to
        transparently support both:

        * Global lexical scopes, which do *not* require a chain map.
        * Local lexical scopes, which require a chain map chaining imports
          across all nested local and global scopes (in that order from most to
          least nested).
    '''

    # ..................{ CLASS VARIABLES                    }..................
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Subclasses declaring uniquely subclass-specific instance
    # variables *MUST* additionally slot those variables. Subclasses violating
    # this constraint will be usable but unslotted, which defeats our purposes.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # Slot all instance variables defined on this object to reduce the costs of
    # both reading and writing these variables by approximately ~10%.
    __slots__ = (
        'schema_attr_basename_trie',
        'schema_package_names',
        'scoped_attr_basename_trie',
    )

    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        schema_attr_basename_trie: BeartypeDecorPlaceTrie
        schema_package_names: FrozenSetStrs
        scoped_attr_basename_trie: Optional[ScopedAttrNameTrie]

    # ....................{ INITIALIZERS                   }....................
    def __init__(
        self,

        # Mandatory parameters.
        schema_attr_basename_trie: BeartypeDecorPlaceTrie,

        # Optional parameters.
        schema_package_names: Optional[FrozenSetStrs] = None,
        scoped_attr_basename_trie: Optional[ScopedAttrNameTrie] = None,
        is_validate: bool = True,
    ) -> None:
        '''
        Initialize this scoped beforelist.

        Parameters
        ----------
        schema_attr_basename_trie : BeartypeDecorPlaceTrie
            **Source attribute name trie schema.** See the class docstring.
        schema_package_names : Optional[FrozenSetStrs], default: None
            **Source module name schema.** See the class docstring.
            Defaults to :data:`None`, in which case this frozen set is
            implicitly constructed as the union of all keys of the passed
            decorator function and method beforelists.
        scoped_attr_basename_trie : Optional[ScopedAttrNameTrie], default: None
            **Target scoped attribute name trie.** See the class docstring.
            Defaults to :data:`None`, in which case callers explicitly
            initialize this trie in a just-in-time (JIT) manner as needed.
        is_validate : bool, default: False
            Either:

            * :data:`False`, in which case this method avoids recursively
              re-validating the contents of all passed data structures for
              efficiency. This should only be passed when this scoped beforelist
              is being constructed by a call to the :meth:`.permute` method.
            * :data:`True`, in which case this method recursively validates the
              contents of these data structures for safety.

            Defaults to :data:`True`.
        '''

        # ....................{ DEFAULTS                   }....................
        # If the caller passed *NO* decorator-hostile module names, initialize
        # this frozen set as the union of all keys of these decorator function
        # and method beforelists.
        if schema_package_names is None:
            schema_package_names = frozenset(
                schema_attr_basename_trie.keys())
            # print(f'Defaulted "schema_package_names" to {schema_package_names}.')
        # Else, the caller passed decorator-hostile module names. In either
        # case, these names are now defined.

        # ....................{ VALIDATE                   }....................
        # Shallowly type-check these data structures.
        assert isinstance(schema_attr_basename_trie, FrozenDict), (
            f'{repr(schema_package_names)} not frozen dictionary.')
        assert isinstance(schema_package_names, frozenset), (
            f'{repr(schema_package_names)} not frozen set.')
        assert isinstance(scoped_attr_basename_trie, NoneTypeOr[ChainMap]), (
            f'{repr(scoped_attr_basename_trie)} neither chain map nor "None".')
        assert isinstance(is_validate, bool), (
            f'{repr(is_validate)} not boolean.')

        #FIXME: Additionally recursively validate the contents of:
        #* "scoped_attr_basename_trie".
        #
        #We can't be bothered at the moment. One catastrophe at a time! *shrug*

        # If recursively validating the contents of these data structures...
        if is_validate:
            # If this parameter is *NOT* a valid decorator function beforelist,
            # raise an exception.
            die_unless_decor_hostile_func_trie(schema_attr_basename_trie)
            # Else, this parameter is a valid decorator function beforelist.

            # Deeply type-check the contents of these data structures.
            assert all(
                isinstance(schema_package_name, str)
                for schema_package_name in schema_package_names
            ), (
                f'{repr(schema_package_names)} not frozen set of strings.')
        # Else, the contents of these data structures are assumed to be valid.

        # ....................{ CLASSIFY                   }....................
        # Classify all passed parameters.
        self.schema_attr_basename_trie = schema_attr_basename_trie
        self.schema_package_names = schema_package_names
        self.scoped_attr_basename_trie = scoped_attr_basename_trie

    # ..................{ DUNDERS                            }..................
    def __repr__(self) -> str:

        return '\n'.join((
            f'{self.__class__.__name__}(\n',
            f'    schema_attr_basename_trie={repr(self.schema_attr_basename_trie)},\n',
            f'    schema_package_names={repr(self.schema_package_names)},\n',
            f'    scoped_attr_basename_trie={repr(self.scoped_attr_basename_trie)},\n',
            f')',
        ))

    # ..................{ PERMUTERS                          }..................
    def permute(self) -> 'BeartypeNodeScopeBeforelist':
        '''
        Shallow copy of this scope beforelist, typically called to produce a
        mutable copy of this scope beforelist isolated to a new local (e.g.,
        function) scope being visited by the abstract syntax tree (AST)
        transformer tracking problematic third-party imports.

        Specifically, this shallow copy permutes this scope as follows:

        * The :attr:`.schema_attr_basename_trie` instance variable is
          shallowly copied by calling its :meth:`.ChainMap.new_child` method,
          whose :attr:`.ChainMap.maps` list is then prefixed by a new empty
          dictionary enabling callers to track local imports safely.
        * The :attr:`.module_to_type_to_method_decor_names` instance variable
          is shallowly copied in the same manner.

        Returns
        -------
        BeartypeNodeScopeBeforelist
            Shallow copy of this scope beforelist.
        '''
        # print('Permuting scope beforelist...')

        # Imported attribute name trie unique to this new local scope,
        # initialized to either...
        scoped_attr_basename_trie = (
            # If *NO* transitive parent scope of this scope imported a
            # decorator-hostile decorator, this scope is the first scope in this
            # hierarchy of scopes to require an imported attribute name trie. In
            # this case, instantiate this trie as an empty chain map.
            ChainMap()
            if self.scoped_attr_basename_trie is None else
            # Else, some transitive parent scope of this scope already imported
            # a decorator-hostile decorator and thus required this trie. In this
            # case, enable callers to track imports safely across this new scope
            # by shallowly copying this trie unique to this scope.
            self.scoped_attr_basename_trie.new_child()
        )

        # Create and return a shallow copy of this parent beforelist.
        return BeartypeNodeScopeBeforelist(
            scoped_attr_basename_trie=scoped_attr_basename_trie,

            # Share all remaining data structures of this parent beforelist
            # with this child beforelist.
            schema_attr_basename_trie=self.schema_attr_basename_trie,
            schema_package_names=self.schema_package_names,

            # Avoid uselessly recursively re-validating the contents of these
            # data structures for efficiency.
            is_validate=False,
        )

# ....................{ RAISERS                            }....................
def die_unless_decor_hostile_func_trie(
    # Mandatory parameters.
    schema_attr_basename_trie: BeartypeDecorPlaceTrie,

    # Optional parameters.
    exception_cls: TypeException = BeartypeConfParamException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed data structure is a valid **decorator
    function beforelist** (i.e., recursive tree structure whose nodes are the
    unqualified basenames of decorator-hostile decorator functions and the
    third-party (sub)packages and (sub)modules transitively defining those
    functions).

    Parameters
    ----------
    schema_attr_basename_trie : BeartypeDecorPlaceTrie
        Decorator function beforelist to be validated.
    exception_cls : type[Exception], default: BeartypeConfParamException
        Type of exception to be raised in the event of a fatal error. Defaults
        to :class:`.BeartypeConfParamException`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
        If this data structure is *not* a valid decorator function beforelist.
    '''
    assert isinstance(exception_cls, type), (
        f'{repr(exception_cls)} not exception type.')
    assert isinstance(exception_prefix, str), (
        f'{repr(exception_prefix)} not string.')

    # If this data structure is *not* a frozen dictionary, raise an exception.
    if not isinstance(schema_attr_basename_trie, FrozenDict):
        raise exception_cls(
            f'{exception_prefix}{repr(schema_attr_basename_trie)} not '
            f'frozen dictionary.'
        )
    # Else, this data structure is a frozen dictionary.

    # If this data structure is *not* a valid decorator function beforelist,
    # raise an exception.
    if not is_decor_hostile_func_trie(schema_attr_basename_trie):
        raise exception_cls(
            f'{exception_prefix}{repr(schema_attr_basename_trie)} not '
            f'decorator-hostile decorator name trie (i.e., '
            f'recursive tree structure satisfying the recursive type hint '
            f'BeartypeDecorPlaceTrie = FrozenDict[str, FrozenDict[str, '
            f'"BeartypeDecorPlaceTrie"]]).'
        )
    # Else, this data structure is a valid decorator function beforelist.

# ....................{ TESTERS                            }....................
def is_decor_hostile_func_trie(
    schema_attr_basename_trie: object) -> TypeIs[BeartypeDecorPlaceTrie]:
    '''
    :data:`True` only if the passed data structure is a valid **decorator
    function beforelist** (i.e., recursive tree structure whose nodes are the
    unqualified basenames of decorator-hostile decorator functions and the
    third-party (sub)packages and (sub)modules transitively defining those
    functions).

    Parameters
    ----------
    schema_attr_basename_trie : BeartypeDecorPlaceTrie
        Decorator function beforelist to be inspected.

    Raises
    ------
    bool
        :data:`True` only if this is a valid decorator function beforelist.
    '''

    #FIXME: *INSUFFICIENT.* To quote the "BeartypeDecorPlaceTrie" hint:
    #    "Note that the root trie is guaranteed to map from strings to *only*
    #    nested frozen dictionaries (rather than to both nested frozen
    #    dictionaries and :data:`None`). Consequently, this hint intentionally
    #    differentiates between matching the root and non-root nesting levels of
    #    this trie."
    #
    #Ergo, we need to expand this validation to:
    #* Non-recursively match the outermost layer to *NOT* map to "None".
    #* Recursively match all non-inner layers to map to
    #  "BeartypeDecorPlaceTrieABC" instances.
    #* Recursively match all inner layers to optionally map to "None".

    # Return true only if...
    return (
        # The passed object is a frozen dictionary *AND*...
        isinstance(schema_attr_basename_trie, FrozenDict) and
        # For each key-value pair of this frozen dictionary...
        all(
            (
                # This key is a string *AND*...
                isinstance(module_name, str) and
                # This value is either...
                (
                    # "None", signifying a terminal leaf node.
                    submodule_or_func_name is None or
                    # A recursively nested frozen dictionary satisfying the same
                    # data structure, signifying a non-terminal stem node.
                    is_decor_hostile_func_trie(submodule_or_func_name)
                )
            )
            for module_name, submodule_or_func_name in (
                schema_attr_basename_trie.items())
        )
    )

# ....................{ FACTORIES                          }....................
#FIXME: Unit test us up, please.
def make_node_scope_beforelist_global() -> BeartypeNodeScopeBeforelist:
    '''
    Beartype **abstract syntax tree (AST) global scope beforelist** (i.e.,
    low-level dataclass aggregating all metadata required to manage the
    beforelist automating decorator positioning for the global scope of the
    module being recursively visited by the current AST transformer).

    Returns
    -------
    BeartypeNodeScopeBeforelist
        Global scope beforelist of the currently visited module.
    '''

    # Create and return this global scope beforelist.
    return BeartypeNodeScopeBeforelist(
        schema_attr_basename_trie=DECOR_HOSTILE_ATTR_NAME_TRIE)
