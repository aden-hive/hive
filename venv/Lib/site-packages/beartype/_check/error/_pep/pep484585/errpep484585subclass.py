#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484`-compliant :attr:`typing.NoReturn` **type hint violation
describers** (i.e., functions returning human-readable strings explaining
violations of :pep:`484`-compliant :attr:`typing.NoReturn` type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeCallHintForwardRefException
from beartype.roar._roarexc import _BeartypeCallHintPepRaiseException
from beartype._check.error.errcause import ViolationCause
from beartype._check.metadata.hint.hintsane import HINT_SANE_IGNORABLE
from beartype._data.typing.datatyping import TypeOrTupleTypes
from beartype._data.hint.sign.datahintsigns import (
    HintSignForwardRef,
    HintSignType,
    HintSignUnion,
)
from beartype._util.cls.pep.clspep3119 import die_unless_object_issubclassable
from beartype._util.cls.utilclstest import is_type_subclass
from beartype._util.hint.pep.proposal.pep484585.pep484585ref import (
    import_pep484585_ref_type)
from beartype._util.hint.pep.utilpepget import get_hint_pep_args
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none
from beartype._util.text.utiltextjoin import join_delimited_disjunction_types
from beartype._util.text.utiltextlabel import label_type
from beartype._util.text.utiltextrepr import represent_pith

# ....................{ GETTERS                            }....................
def find_cause_pep484585_subclass(cause: ViolationCause) -> ViolationCause:
    '''
    Output cause describing whether the pith of the passed input cause either is
    or is not a subclass of the issubclassable type of that cause.

    Parameters
    ----------
    cause : ViolationCause
        Input cause providing this data.

    Returns
    -------
    ViolationCause
        Output cause type-checking this data.
    '''
    assert isinstance(cause, ViolationCause), f'{repr(cause)} not cause.'
    assert cause.hint_sign is HintSignType, (
        f'{cause.hint_sign} not HintSignType.')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._check.error._nonpep.errnonpeptype import (
        find_cause_type_instance_origin)

    # ....................{ SHALLOW                        }....................
    # Shallow output cause describing the failure of this path to be a type if
    # this pith a non-type *OR* "None" otherwise (i.e., if this pith is a type).
    cause_shallow = find_cause_type_instance_origin(cause)

    # If this pith is *NOT* a type, return this shallow cause.
    if cause_shallow.cause_str_or_none is not None:
        return cause_shallow
    # Else, this pith is a type.

    # ....................{ LOCALS                         }....................
    # Metadata encapsulating the sanification of the superclass this pith is
    # required to be a subclass of.
    hint_child_sane = cause.hint_childs_sane[0]

    # If this superclass is ignorable, then *ALL* types including this pith
    # satisfy this superclass. In this case, return the passed cause as is.
    if hint_child_sane is HINT_SANE_IGNORABLE:
        return cause
    # Else, this superclass is unignorable.

    # Superclass this pith is required to be a subclass of.
    hint_child: TypeOrTupleTypes = hint_child_sane.hint  # type: ignore[assignment]

    # Arbitrary object uniquely identifying this superclass.
    hint_child_sign = get_hint_pep_sign_or_none(hint_child)  # pyright: ignore

    # If this child hint is a forward reference to a superclass...
    if hint_child_sign is HintSignForwardRef:
        # Superclass referred to by this absolute or relative forward reference.
        hint_child = import_pep484585_ref_type(
            hint=hint_child,  # type: ignore[arg-type]
            cls_stack=cause.cls_stack,
            func=cause.func,
            exception_cls=BeartypeCallHintForwardRefException,
            exception_prefix=cause.exception_prefix,
        )
    # Else, this child hint is *NOT* a forward reference.
    #
    # If this child hint is a union of superclasses, reduce this union to a
    # tuple of superclasses. Only the latter is safely passable as the second
    # parameter to the issubclass() builtin under all supported Python versions.
    elif hint_child_sign is HintSignUnion:
        hint_child = get_hint_pep_args(hint_child)
    # Else, this child hint is *NOT* a union. By process of elimination, this
    # child hint *MUST be a class. In this case, preserve this class as is.

    # If this child hint is *NOT* an issubclassable object, raise an exception.
    #
    # Technically, this validation is only necessary when this child hint was a
    # forward reference. Pragmatically, there's *NO* harm in performing this
    # validation in all possible cases. Ergo, we do. *shrug*
    die_unless_object_issubclassable(
        obj=hint_child,
        exception_cls=_BeartypeCallHintPepRaiseException,
        exception_prefix=cause.exception_prefix,

        # If this child hint is still a forward reference, raise an exception.
        # Ideally, the above conditional should already have resolved all
        # forward references.
        is_forwardref_valid=False,
    )
    # Else, this child hint is an issubclassable object.

    # ....................{ DEEP                           }....................
    # If this pith subclasses this superclass, return the passed cause as is.
    if is_type_subclass(cause.pith, hint_child):
        return cause
    # Else, this pith does *NOT* subclass this superclass. In this case...
    else:
        # Output cause to be returned, permuted from this input cause.
        cause_return = cause.permute_cause()

        # Description of this superclasses, defined as either...
        hint_child_label = (
            # If this superclass is a type, a description of this type;
            label_type(cls=hint_child, is_color=cause.conf.is_color)
            if isinstance(hint_child, type) else
            # Else, this superclass is a tuple of types. In this case, a
            # description of these types...
            join_delimited_disjunction_types(
                types=hint_child, is_color=cause.conf.is_color)
        )

        # Human-readable string describing this failure.
        cause_return.cause_str_or_none = (
            f'{represent_pith(cause.pith)} not subclass of {hint_child_label}')

    # Return this cause.
    return cause_return
