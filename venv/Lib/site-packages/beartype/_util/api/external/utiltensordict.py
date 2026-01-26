#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **TensorDict utilities** (i.e., low-level callables handling the
third-party :mod:`tensordict` package).

This private submodule is *not* intended for importation by downstream callers.
'''

#FIXME: Preserved for posterity. It's unclear whether @beartype currently
#requires (or desires) explicit TensorDict support. Ideally, it doesn't!

# # ....................{ IMPORTS                            }....................
# #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# # CAUTION: The top-level of this module should avoid importing from third-party
# # optional libraries, both because those libraries cannot be guaranteed to be
# # either installed or importable here *AND* because those imports are likely to
# # be computationally expensive, particularly for imports transitively importing
# # C extensions (e.g., anything from NumPy or SciPy).
# #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# # from dataclasses import is_dataclass
#
# # ....................{ TESTERS                            }....................
# #FIXME: Unit test us up, please.
# def is_tensorclass(obj: object) -> bool:
#     '''
#     :data:`True` only if the passed object is a **tensorclass** (i.e.,
#     :obj:`tensordict.tensorclass`-decorated type).
#
#     Tensorclasses currently violate :func:`beartype.beartype`-based
#     type-checking. Consequently, :mod:`beartype` *must* explicitly ignore and
#     thus detect tensorclasses. However, tensorclasses lack an identifiable
#     metaclass or superclass! Ergo, even detecting tensorclasses is non-trivial.
#     Although the :func:`tensordict.is_tensorclass` public function appears to
#     superficially serve a similar purpose as this homegrown tester, calling the
#     former would effectively require importing the extremely costly
#     :mod:`tensordict` package from a global scope in :mod:`beartype`! Ergo, we
#     intentionally define this competing alternative instead -- which does *not*
#     require importing that package and thus remains highly efficient.
#
#     Parameters
#     ----------
#     obj: object
#         Object to be inspected.
#
#     See Also
#     --------
#     https://github.com/beartype/beartype/issues/501
#         Upstream issue strongly inspiring this implementation.
#     '''
#
#     # Return true only if...
#     return (
#         #FIXME: Does this actually work? If so, this is preferable:
#         # is_dataclass(obj) and
#
#         # This object is a type *AND*...
#         isinstance(obj, type) and
#
#         # The type of this type is the "type" superclass (implying this type to
#         # have *NO* metaclass) *AND*...
#         obj.__class__ is type and
#
#         #FIXME: What does the tensordict.is_tensorclass() tester do? This?
#         #Something else? Whatever that tester does, we should do maybe too.
#         # This class defines the @tensorclass-specific private "_is_tensorclass"
#         # attribute. While fragile, the inadequate @tensorclass API leaves us
#         # little leg room. Fragility is the best we can currently do.
#         hasattr(obj, '_is_tensorclass')
#     )
