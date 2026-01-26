#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **abstract syntax tree (AST) scope** (i.e., low-level dataclass
aggregating all metadata required to detect and manage a lexical scope being
recursively visited by the current AST transformer).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from ast import (
    AST,
    # Module,
)
from beartype.claw._ast._scope.clawastscopebefore import (
    BeartypeNodeScopeBeforelist)
from beartype.typing import (
    TYPE_CHECKING,
    Type,
)

# ....................{ CLASSES                            }....................
#FIXME: Unit test us up, please. *sigh*
class BeartypeNodeScope(object):
    '''
    Beartype **abstract syntax tree (AST) scope** (i.e., low-level dataclass
    aggregating all metadata required to detect and manage a lexical scope
    being recursively visited by the current AST transformer).

    Attributes
    ----------
    beforelist : BeartypeNodeScopeBeforelist
        **Abstract syntax tree (AST) scope beforelist** (i.e., dataclass
        aggregating all metadata required to manage the beforelist automating
        decorator positioning for this scope being recursively visited by the
        parent AST transformer).
    name : str
        Fully-qualified name of the current lexical scope (i.e., ``.``-delimited
        absolute name of the module containing this scope followed by the
        relative basenames of zero or more classes and/or callables). This name
        is guaranteed to be prefixed by the current value of the
        :attr:`.module_name` instance variable.
    node_type : type[AST]
        **Lexical scope node type** (i.e., type of the "closest" parent lexical
        scope node of the current node being recursively visited by this AST
        transformer such that that parent node declares a new lexical scope).
        Specifically, if this is:

        * :class:`ast.Module`, the current node directly resides in the **global
          scope** of the current module.
        * :class:`ast.ClassDef`, the current node directly resides in the
          **class scope** of the current class.
        * :class:`ast.FunctionDef`, the current node directly resides in the
          **callable scope** of the current callable.
    _is_beforelist_mutable : bool
        :data:`True` only if this scope's beforelist is **modifiable** (i.e., if
        this scope's beforelist is unique to this scope). Defaults to
        :data:`False` until the caller explicitly calls the
        :meth:`permute_beforelist_if_needed` method, at which point this boolean
        permanently flips to :data:`True` for the lifetime of this scope.
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
        'beforelist',
        'name',
        'node_type',
        '_is_beforelist_mutable',
    )

    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        beforelist: BeartypeNodeScopeBeforelist
        name: str
        node_type: Type[AST]
        _is_beforelist_mutable: bool

    # ....................{ INITIALIZERS                   }....................
    def __init__(
        self,
        beforelist: BeartypeNodeScopeBeforelist,
        name: str,
        node_type: Type[AST],
    ) -> None:
        '''
        Initialize this beforelist scope.

        Parameters
        ----------
        beforelist : BeartypeNodeScopeBeforelist
            **Lexical scope beforelist.** See the class docstring.
        name : str
            Fully-qualified name of the current lexical scope (i.e.,
            ``.``-delimited absolute name of the module containing this scope
            followed by the relative basenames of zero or more classes and/or
            callables).
        node_type : type[AST]
            **Lexical scope node type.** See the class docstring.
        '''
        assert isinstance(beforelist, BeartypeNodeScopeBeforelist), (
            f'{repr(beforelist)} not beforelist scope.')
        assert isinstance(name, str), f'{repr(name)} not string.'
        assert isinstance(node_type, type), f'{repr(node_type)} not type.'
        assert issubclass(node_type, AST), f'{repr(node_type)} not node type.'

        # Classify all passed parameters.
        self.beforelist = beforelist
        self.name = name
        self.node_type = node_type

        # Nullify all remaining instance variables.
        self._is_beforelist_mutable = False

    # ..................{ DUNDERS                            }..................
    def __repr__(self) -> str:

        return '\n'.join((
            f'{self.__class__.__name__}(\n',
            f'    beforelist={repr(self.beforelist)},\n',
            f'    name={repr(self.name)},\n',
            f'    node_type={repr(self.node_type)},\n',
            f'    _is_beforelist_mutable={repr(self._is_beforelist_mutable)},\n',
            f')',
        ))

    # ..................{ BEFORELIST                         }..................
    def permute_beforelist_if_needed(self) -> None:
        '''
        Render this scope's beforelist safe for modification by external callers
        (e.g., to track problematic third-party imports) if this beforelist is
        *not* yet safely **modifiable** (i.e., if this beforelist is still a
        reference to a parent scope's beforelist and is thus *not* unique to
        this scope).

        For both space and time efficiency, beforelists obey the copy-on-write
        design pattern inspired by modern filesystems (e.g., Btrfs). Before
        attempting to modify the contents of this beforelist, callers should
        call this method to render this beforelist safe for modification.
        '''
        # print(f'Permuting scope "{self.name}" if needed...')

        # If this beforelist is *NOT* yet safely modifiable, this beforelist is
        # still a reference to a parent scope's beforelist and is thus *NOT*
        # unique to this scope. In this case...
        if not self._is_beforelist_mutable:
            # print(f'Permuting scope "{self.name}"...')

            # Replace this shared beforelist with a new beforelist unique to
            # this scope, which may then be safely modified by callers.
            self.beforelist = self.beforelist.permute()

            # Record that this beforelist is now safely modifiable.
            self._is_beforelist_mutable = True
