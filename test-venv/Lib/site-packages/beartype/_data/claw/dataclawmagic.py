#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **import hook magic** (i.e., global constants widely leveraged
throughout submodules of the :mod:`beartype.claw` subpackage).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.meta import (
    NAME,
    VERSION,
)

# ....................{ STRINGS                            }....................
BEARTYPE_OPTIMIZATION_MARKER = f'{NAME}{VERSION.replace(".", "v")}'
'''
**Beartype optimization marker** (i.e., placeholder substring suffixing the
``optimization`` parameter passed to the magical hidden
:func:`importlib._bootstrap_external.cache_from_source` function with metadata
unique to the currently installed package name and version of :mod:`beartype`).

This marker uniquifies the filename of bytecode files compiled under beartype
import hooks to the abstract syntax tree (AST) transformation applied by this
version of :mod:`beartype`. Why? Because external callers can trivially enable
and disable that transformation for any module by either calling or not calling
beartype import hooks that accept package name arguments (e.g.,
:func:`beartype.claw.beartype_package`) with the name of a package transitively
containing that module. Compiling a beartyped variant of that module to the same
bytecode file as the non-beartyped variant of that module would erroneously
persist beartyping to that module -- even *after* removing the relevant call to
the :func:`beartype.claw.beartype_package` function! Clearly, that's awful.
Enter @agronholm's phenomenal patch, stage left.

Caveats
-------
**Python requires all optimization markers to be alphanumeric strings.** If this
or *any* other optimization marker contains a non-alphanumeric character, Python
raises a fatal exception resembling:

    ValueError: '-beartype-0.14.2' is not alphanumeric

Ergo, this string globally replaces *all* non-alphanumeric characters that are
otherwise commonly present in the version specifier for this version of
:mod:`beartype` by the arbitrary character ``"v`"" (which is *not* present in
the name of this package and thus suitable as a machine-readable delimiter).
'''

# ....................{ STRINGS ~ names                    }....................
BEARTYPE_DECORATOR_FUNC_NAME = '__beartype__'
'''
Unqualified basename of the beartype decorator as imported into the current
user-defined module being imported and thus transformed by the
:class:`beartype.claw._ast.clawastmain.BeartypeNodeTransformer` subclass.
'''


BEARTYPE_RAISER_FUNC_NAME = '__die_if_unbearable_beartype__'
'''
Unqualified basename of the beartype exception-raiser as imported into the
current user-defined module being imported and thus transformed by the
:class:`beartype.claw._ast.clawastmain.BeartypeNodeTransformer` subclass.
'''

# ....................{ STRINGS ~ names ~ claw             }....................
BEARTYPE_CLAW_STATE_OBJ_NAME = '__claw_state_beartype__'
'''
Unqualified basename of the beartype import hook state as imported into the
current user-defined module being imported and thus transformed by the
:class:`beartype.claw._ast.clawastmain.BeartypeNodeTransformer` subclass.
'''


BEARTYPE_CLAW_STATE_CONF_CACHE_VAR_NAME = 'module_name_to_beartype_conf'
'''
Unqualified basename of the **hooked module beartype configuration cache**
(i.e., dictionary mapping from the fully-qualified name of each previously
imported submodule of each package previously registered in our global package
trie to the beartype configuration configuring type-checking by the
:func:`beartype.beartype` decorator of that submodule) relative to the
beartype import hook state, which contains this cache.
'''

# ....................{ STRINGS ~ names : pep : 695        }....................
BEARTYPE_HINT_PEP695_FORWARDREF_ITER_FUNC_NAME = (
    '__iter_hint_pep695_forwardref_beartype__')
'''
Unqualified basename of the :pep:`695`-compliant **type alias unqualified
relative forward reference iterator** (i.e., generator iteratively creating and
yielding one forward reference proxy for each unqualified relative forward
reference in the passed :pep:`695`-compliant type alias  as imported into the
current user-defined module being imported and thus transformed by the
:class:`beartype.claw._ast.clawastmain.BeartypeNodeTransformer` subclass.
'''
