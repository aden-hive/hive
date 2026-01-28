#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **cache clearerers** (i.e., low-level callables safely resetting
global caches distributed throughout the :mod:`beartype` codebase).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ CLEARERS                           }....................
def clear_caches() -> None:
    '''
    Clear (i.e., empty) *all* internal caches leveraged throughout the
    :mod:`beartype` codebase, enabling callers to reset this codebase to its
    initial state.

    This function is typically cleared on detecting a **hot reload** (i.e.,
    attempt by the end user to reimport a presumably redefined user-defined
    module, type, or other object commonly cached by :mod:`beartype`). Notably,
    this function clears:

    * The **annotations dictionary cache** (i.e., private
      :data:`beartype._util.hint.pep.proposal.pep649._MODULE_NAME_TO_HINTABLE_BASENAME_TO_ANNOTATIONS`
      dictionary).
    * The **forward reference proxy cache** (i.e., private
      :data:`beartype._check.forward.reference.fwdrefmake._forwardref_args_to_forwardref`
      dictionary).
    * The **forward reference referee cache** (i.e., private
      :data:`beartype._check.forward.reference.fwdrefmeta._forwardref_to_referent`
      dictionary).
    * The **tuple union cache** (i.e., private
      :data:`beartype._check.code.codescope._tuple_union_to_tuple_union`
      dictionary).
    * The **type hint coercion cache** (i.e., private
      :data:`beartype._check.convert._convcoerce._hint_repr_to_hint`
      dictionary).
    * The **type hint wrapper cache** (i.e., private
      :data:`beartype._door._cls.doormeta._HINT_KEY_TO_WRAPPER` cache).
    '''
    # print('Clearing all \"beartype._check\" caches...')

    # Defer possibly heavyweight imports. Whereas importing this submodule is a
    # common occurrence, cache clearing and thus calls to this function are a
    # comparatively rarer occurrence. We optimize for the common case.
    from beartype.door._cls.doormeta import _HINT_KEY_TO_WRAPPER
    from beartype._check.code.codescope import _tuple_union_to_tuple_union
    from beartype._check.convert._convcoerce import _hint_repr_to_hint
    from beartype._check.forward.reference.fwdrefmake import (
        _forwardref_args_to_forwardref)
    from beartype._check.forward.reference.fwdrefmeta import (
        _forwardref_to_referent)
    from beartype._util.cache.utilcacheobjattr import clear_object_attr_caches

    # Clear all relevant caches used throughout this subpackage.
    clear_object_attr_caches()
    _HINT_KEY_TO_WRAPPER.clear()
    _forwardref_args_to_forwardref.clear()
    _forwardref_to_referent.clear()
    _hint_repr_to_hint.clear()
    _tuple_union_to_tuple_union.clear()
