#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype Decidedly Object-Oriented Runtime-checking (DOOR) API.**

This subpackage provides an object-oriented type hint class hierarchy,
encapsulating the crude non-object-oriented type hint declarative API
standardized by the :mod:`typing` module.
'''

# ....................{ TODO                               }....................
#FIXME: Create one unique "TypeHint" subclass *FOR EACH UNIQUE KIND OF TYPE
#HINT.* We're currently simply reusing the same
#"_TypeHintOriginIsinstanceableArgs*" family of concrete subclasses to
#transparently handle these unique kinds of type hints. That's fine as an
#internal implementation convenience. Sadly, that's *NOT* fine for users
#actually trying to introspect types. That's the great disadvantage of standard
#"typing" types, after all; they're *NOT* introspectable by type. Ergo, we need
#to explicitly define subclasses like:
#* "beartype.door.ListTypeHint".
#* "beartype.door.MappingTypeHint".
#* "beartype.door.SequenceTypeHint".
#
#And so on. There are a plethora, but ultimately a finite plethora, which is all
#that matters. Do this for our wonderful userbase, please.

# ....................{ IMPORTS                            }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# WARNING: To avoid polluting the public module namespace, external attributes
# should be locally imported at module scope *ONLY* under alternate private
# names (e.g., "from argparse import ArgumentParser as _ArgumentParser" rather
# than merely "from argparse import ArgumentParser").
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
from beartype.door._cls.doorsuper import (
    TypeHint as TypeHint)
from beartype.door._cls.pep.doorpep484604 import (
    UnionTypeHint as UnionTypeHint)
from beartype.door._cls.pep.doorpep586 import (
    LiteralTypeHint as LiteralTypeHint)
from beartype.door._cls.pep.doorpep593 import (
    AnnotatedTypeHint as AnnotatedTypeHint)
from beartype.door._cls.pep.pep484.doorpep484any import (
    AnyTypeHint as AnyTypeHint)
from beartype.door._cls.pep.pep484.doorpep484class import (
    ClassTypeHint as ClassTypeHint)
from beartype.door._cls.pep.pep484.doorpep484newtype import (
    NewTypeTypeHint as NewTypeTypeHint)
from beartype.door._cls.pep.pep484.doorpep484typevar import (
    TypeVarTypeHint as TypeVarTypeHint)
from beartype.door._cls.pep.pep484585.doorpep484585callable import (
    CallableTypeHint as CallableTypeHint)
from beartype.door._cls.pep.pep484585.doorpep484585generic import (
    GenericTypeHint as GenericTypeHint)
from beartype.door._cls.pep.pep484585.doorpep484585subscripted import (
    SubscriptedTypeHint as SubscriptedTypeHint)
from beartype.door._cls.pep.pep484585.doorpep484585tuple import (
    TupleFixedTypeHint,
    TupleVariableTypeHint,
)
from beartype.door._func.doorcheck import (
    die_if_unbearable as die_if_unbearable,
    is_bearable as is_bearable,
    is_subhint as is_subhint,
)

# ....................{ DUNDERS                            }....................
def __getattr__(attr_name: str) -> object:
    '''
    Dynamically retrieve a deprecated attribute with the passed unqualified name
    from this submodule and emit a non-fatal deprecation warning on each such
    retrieval if this submodule defines this attribute *or* raise an exception
    otherwise.

    The Python interpreter implicitly calls this :pep:`562`-compliant module
    dunder function under Python >= 3.7 *after* failing to directly retrieve an
    explicit attribute with this name from this submodule. Since this dunder
    function is only called in the event of an error, neither space nor time
    efficiency are a concern here.

    Parameters
    ----------
    attr_name : str
        Unqualified name of the deprecated attribute to be retrieved.

    Returns
    -------
    object
        Value of this deprecated attribute.

    Warns
    -----
    DeprecationWarning
        If this attribute is deprecated.

    Raises
    ------
    AttributeError
        If this attribute is unrecognized and thus erroneous.
    '''

    # Isolate imports to avoid polluting the module namespace.
    from beartype._util.module.utilmoddeprecate import deprecate_module_attr

    # Package scope (i.e., dictionary mapping from the names to values of all
    # non-deprecated attributes defined by this package).
    attr_nondeprecated_name_to_value = globals()

    # If this deprecated attribute is the deprecated infer_hint() function,
    # forcibly import the non-deprecated "beartype.bite" subpackage now defining
    # this function into this package scope. For efficiency, this subpackage
    # does *NOT* unconditionally import and expose the "beartype.bite"
    # subpackage above. That subpackage does *NOT* exist in the globals()
    # dictionary defaulted to above and *MUST* now be forcibly injected there.
    if attr_name == 'infer_hint':
        from beartype.bite import infer_hint
        attr_nondeprecated_name_to_value = {
            'beartype.bite.infer_hint': infer_hint}
        attr_nondeprecated_name_to_value.update(globals())
    # Else, this deprecated attribute is any other attribute.

    # Return the value of this deprecated attribute and emit a warning.
    return deprecate_module_attr(
        attr_deprecated_name=attr_name,
        attr_deprecated_name_to_nondeprecated_name={
            'infer_hint': 'beartype.bite.infer_hint',
        },
        attr_nondeprecated_name_to_value=attr_nondeprecated_name_to_value,
    )
