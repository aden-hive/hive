#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **decorator position globals** (i.e., global constants defining the
initial user-configurable contents of the beforelist automating decorator
positioning for :mod:`beartype.claw` import hooks).

:mod:`beartype.claw` import hooks initialize user-configurable beforelists via
these globals of third-party decorators well-known to be **decorator-hostile**
(i.e., decorators hostile to other decorators by prematurely terminating
decorator chaining, such that *no* decorators may appear above these decorators
in any chain of one or more decorators).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Dict,
    Optional,
)
from beartype._conf.decorplace.confplacetrie import (
    BeartypeDecorPlacePackagesTrie,
    BeartypeDecorPlacePackageTrie,
    BeartypeDecorPlaceTypeTrie,
)

# ....................{ HINTS                              }....................
#FIXME: Actually define these hints as proper type aliases *AFTER* we drop
#support for Python 3.11, please: e.g.,
#   type _ClawBeforelist = Dict[str, Union[FrozenSet[str], _ClawBeforelist]]

BeartypeDecorPlaceSubtrie = Optional[Dict[str, 'BeartypeDecorPlaceSubtrie']]
'''
PEP-compliant recursive alias matching a **beforelist subtrie** (i.e.,
corresponding value of some key-value pair signifying a child node of a parent
beforelist (sub)trie), constrained to be either:

* If this is a leaf child node terminating a branch of that (sub)trie,
  :data:`None`.
* If this is a stem child node perpetuating a branch of that (sub)trie, yet
  another such recursively nested dictionary mapping from the unqualified
  basenames of problematic third-party attributes imported into a scope of the
  currently visited module to yet another (sub)trie child node.
'''


BeartypeDecorPlaceTrie = Dict[str, Dict[str, BeartypeDecorPlaceSubtrie]]
'''
PEP-compliant recursive alias matching a **beforelist trie** (i.e., recursive
tree structure whose nodes are the unqualified basenames of problematic
third-party attributes imported into a scope of the currently visited module,
defined as a frozen dictionary mapping from strings to either yet another such
recursively nested frozen dictionary *or* :data:`None` signifying a terminal
leaf node).

Note that the root trie is guaranteed to map from strings to *only* nested
frozen dictionaries (rather than to both nested frozen dictionaries and
:data:`None`). Consequently, this hint intentionally differentiates between
matching the root and non-root nesting levels of this trie.
'''

# ....................{ TRIES                              }....................
#FIXME: *BEFORE* openly publishing this data structure to the world, let's do
#something about the hideously ambiguous "None" references we're stuffing into
#this data structure. Specifically:
#* Define a new "BeartypeDecorPlaceNode" class and associated
#  "BeartypeDecorPlaceDecoratorHostileNode" global singleton: e.g.,
#      class BeartypeDecorPlaceNode(object):
#          pass
#
#      BeartypeDecorPlaceDecoratorHostileNode = BeartypeDecorPlaceNode()
#* Globally replace *ALL* ambiguous "None" references both here and in the
#  associated "clawastimport" submodule with unambiguous
#  "BeartypeDecorPlaceDecoratorHostileNode" references instead.
#
#Why are "None" references ambiguous? Because we'd like to eventually stuff a
#wide variety of metadata into this data structure. For example, third-party
#*DECORATOR-DISABLING DECORATORS*. "But what are decorator-disabling
#decorators!?", you might now be cogitating. As the term suggests, they're
#decorators whose existence in a chain of one or more decorators signals to
#other decorators that those decorators should *NOT* be applied in the first
#place. A great real-world example of a decorator-disabling decorator is the
#@jaxtyping.jaxtyped decorator, which already internally applies a runtime
#type-checking decorator like @beartype; ergo, @beartype should *NOT* be
#erroneously re-applied to callables and types decorated by @jaxtyping.jaxtyped.
#That decorator effectively disables other decorators.
#
#Unambiguous node singletons give us the future flexibility we need to
#eventually support features like this. Pump that fist, bear bros! \o/
DECOR_HOSTILE_ATTR_NAME_TRIE: BeartypeDecorPlaceTrie = (
    BeartypeDecorPlacePackagesTrie({
        # ....................{ FUNCTIONS                  }....................
        # Third-party decorator-hostile decorator *FUNCTIONS* directly defined
        # by functional (i.e., *NOT* object-oriented) APIs.

        # The third-party @chain decorator function of the
        # "langchain_core.runnables" package of the LangChain API. See also:
        #     https://github.com/beartype/beartype/issues/541
        'langchain_core': BeartypeDecorPlacePackageTrie(
            {'runnables': BeartypeDecorPlacePackageTrie({'chain': None})}),

        # ....................{ METHODS                    }....................
        # Third-party decorator-hostile decorator *METHODS* directly defined by
        # types directly defined by object-oriented (OO) APIs.

        # The third-party @task decorator method of the "celery.Celery" type of
        # the Celery API. See also:
        #     https://github.com/beartype/beartype/issues/500
        'celery': BeartypeDecorPlacePackageTrie({
            'Celery': BeartypeDecorPlaceTypeTrie({'task': None})}),

        # The third-party @tool decorator function of the "fastmcp.FastMCP" type
        # of the FastMCP API. See also:
        #     https://github.com/beartype/beartype/issues/540
        'fastmcp': BeartypeDecorPlacePackageTrie({
            'FastMCP': BeartypeDecorPlaceTypeTrie({'tool': None})}),
}))
'''
**Decorator-hostile decorator attribute name trie** (i.e., frozen dictionary
mapping from the unqualified basename of each third-party (sub)package and
(sub)module transitively defining one or more decorator-hostile decorators to
either yet another such recursively nested frozen dictionary *or* :data`None`,
in which case the corresponding key is the unqualified basename of a
decorator-hostile decorator directly defined by that (sub)package, (sub)module,
type, or instance).
'''
