#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **non-class decoration globals** (i.e., global constants required
by the private :mod:`beartype._decor._nontype.decornontype` submodule to decorate
non-class objects with runtime type-checking).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._decor._nontype._decordescriptor import (
    beartype_descriptor_decorator_builtin_class_or_static_method,
    beartype_descriptor_decorator_builtin_property,
)
from beartype._util.api.external.utilclick import beartype_click_command

# ....................{ MAPPINGS                           }....................
# Note that this dispatch table is effectively untypeable, thanks to the general
# insanity of pure-static type-checkers (e.g., mypy, pyright). We sigh. *sigh*
MODULE_TO_TYPE_NAME_TO_BEARTYPE_DECORATOR = {
    # ....................{ BUILTINS                       }....................
    # Standard builtins globally accessible *WITHOUT* requiring importation.
    'builtins': {
        'classmethod': (
            beartype_descriptor_decorator_builtin_class_or_static_method),
        'staticmethod': (
            beartype_descriptor_decorator_builtin_class_or_static_method),
        'property': (
            beartype_descriptor_decorator_builtin_property),
    },
}
'''
**Beartype callable decorator exact class dispatch table** (i.e., dictionary
mapping the fully-qualified name of each package or module to the unqualified
basename of each type of an object decoratable by the :func:`beartype.beartype`
decorator defined by that package or module to a decorator function decorating
that object with dynamically generated type-checking).

This dispatch table maps to decorator functions with signatures resembling:

.. code-block:: python

   def {func_name}(func: BeartypeableT, **kwargs) -> BeartypeableT:

The first parameter is passed positionally. All remaining parameters are passed
by keyword and intended to be transitively (i.e., eventually) passed on to the
lower-level :func:`.beartype_func` decorator. In other words, all keyword
parameters accepted by :func:`.beartype_func` are also unconditionally accepted
by *all* of these higher-level decorators.

See Also
--------
:data:`._MODULE_TO_SUPERTYPE_NAME_TO_BEARTYPE_DECORATOR`
    Generalization of this dictionary applicable to the entire method-resolution
    order (MRO) of arbitrary objects.
'''


MODULE_TO_SUPERTYPE_NAME_TO_BEARTYPE_DECORATOR = {
    # ....................{ THIRD-PARTY                    }....................
    # Non-standard types declared by external third-party packages.

    # Click, a popular pure-Python framework for CLI- and TUI-based apps.
    'click.core': {
        # Type created and returned by the @click.command() decorator.
        'Command': beartype_click_command,
    }
}
'''
**Beartype callable decorator superclass dispatch table** (i.e., dictionary
mapping the fully-qualified name of each package or module to the unqualified
basename of each superclass in the method-resolution order (MRO) of an object
decoratable by the :func:`beartype.beartype` decorator defined by that package
or module to a decorator function decorating that object with dynamically
generated type-checking).

See Also
--------
:data:`._MODULE_TO_TYPE_NAME_TO_BEARTYPE_DECORATOR`
    Specialization of this dictionary applicable *only* to the exact class of
    arbitrary objects (rather than the full method-resolution order (MRO) of
    arbitrary objects).
'''

# ....................{ METHODS                            }....................
MODULE_TO_TYPE_NAME_TO_BEARTYPE_DECORATOR_get = (
    MODULE_TO_TYPE_NAME_TO_BEARTYPE_DECORATOR.get)
'''
:meth:`dict.get` method bound to the
:data:`._MODULE_TO_TYPE_NAME_TO_BEARTYPE_DECORATOR` global dictionary,
globalized as an attribute to reduce lookup costs elsewhere.
'''


MODULE_TO_SUPERTYPE_NAME_TO_BEARTYPE_DECORATOR_get = (
    MODULE_TO_SUPERTYPE_NAME_TO_BEARTYPE_DECORATOR.get)
'''
:meth:`dict.get` method bound to the
:data:`._MODULE_TO_SUPERTYPE_NAME_TO_BEARTYPE_DECORATOR` global dictionary,
globalized as an attribute to reduce lookup costs elsewhere.
'''
