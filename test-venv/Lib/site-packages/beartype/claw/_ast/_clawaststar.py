#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **abstract syntax tree (AST) star imports** (i.e., set of all
``import`` statements importing attributes required by beartype-specific code
dynamically injected into otherwise beartype-agnostic user code by the
:class:`beartype.claw._ast.clawastmain.BeartypeNodeTransformer` subclass).

This private submodule is a "clearing house" of beartype AST imports, intended
to be dynamically injected as a single **star-import statement** (e.g., of the
syntactic form ``from beartype.claw._ast._clawaststar import *``) injected into
the module scope of otherwise beartype-agnostic user code by the
:class:`beartype.claw._ast.clawastmain.BeartypeNodeTransformer` subclass. Doing
so enables all *other* such beartype-specific code to conveniently reference the
attributes explicitly imported and implicitly exported by this submodule.

This private submodule is *not* intended for importation by downstream callers.

Caveats
-------
This private submodule intentionally imports the original attributes into the
currently visited submodule under obfuscated beartype-specific names suffixed by
the arbitrary substring ``"_beartype__"``, significantly reducing the likelihood
of a namespace collision with existing attributes of the same name in that
submodule. Since all visited submodules are user-defined and thus outside
beartype control, some level of obfuscation is effectively mandatory.
'''

#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: *ALL* imports performed below *MUST* be explicitly listed in the
# "__all__" dunder global declared before to actually have an effect.
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

# ....................{ IMPORTS                            }....................
# Imports required by PEP-agnostic nodes injected into the current AST by the
# "beartype.claw._ast..clawastmain.BeartypeNodeTransformer" superclass.

# Import our beartype decorator to be applied by our AST transformer to all
# applicable callables and classes in third-party modules.
from beartype._decor.decorcache import beartype as __beartype__

# Import our beartype import hook state (i.e., non-thread-safe singleton
# centralizing *all* global state maintained by beartype import hooks).
from beartype.claw._clawstate import claw_state as __claw_state_beartype__

# ....................{ IMPORTS ~ pep : 526                }....................
# Imports required by PEP 526-compliant nodes injected into the current AST by
# "beartype.claw._ast._pep.clawastpep526.BeartypeNodeTransformerPep526Mixin".

# Import our beartype exception-raiser (i.e., beartype-specific function raising
# exceptions on runtime type-checking violations, applied by our AST transformer
# to all applicable PEP 526-compliant annotated variable assignments).
#
# Note that we intentionally import this exception-raiser from our private
# "beartype.door._doorcheck" submodule rather than our public "beartype.door"
# subpackage. Why? Because the former consumes marginally less space and time to
# import than the latter. Whereas the latter imports the full "TypeHint" type
# hierarchy, the former only imports low-level utility functions.
from beartype.door._func.doorcheck import (
    die_if_unbearable as __die_if_unbearable_beartype__)

# ....................{ IMPORTS ~ pep : 695                }....................
# Imports required by PEP 695-compliant nodes injected into the current AST by
# "beartype.claw._ast._pep.clawastpep695.BeartypeNodeTransformerPep695Mixin".

# Import our PEP 695-compliant type alias forward reference proxy factory
# iterator (i.e., generator iteratively creating and yielding one forward
# reference proxy for each unqualified relative forward reference in the passed
# PEP 695-compliant type alias).
from beartype._util.hint.pep.proposal.pep695 import (
    iter_hint_pep695_unsubbed_forwardrefs as __iter_hint_pep695_forwardref_beartype__)

# ....................{ GLOBALS                            }....................
__all__ = [
    '__beartype__',
    '__claw_state_beartype__',
    '__die_if_unbearable_beartype__',
    '__iter_hint_pep695_forwardref_beartype__',
]
'''
Special list global of the unqualified names of all public submodule attributes
explicitly exported by and thus safely importable from this submodule.

Note that this global *must* be defined. If this global is *not* defined, then
importing star imports from this submodule silently reduces to a noop.
'''
