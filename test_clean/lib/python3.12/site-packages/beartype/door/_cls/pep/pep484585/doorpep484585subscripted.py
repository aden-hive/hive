#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **Decidedly Object-Oriented Runtime-checking (DOOR) subscripted type
hint classes** (i.e., :class:`beartype.door.TypeHint` subclasses implementing
support for :pep:`484`- and :pep:`585`-compliant subscripted type hints *not*
already matched by any more fine-grained :class:`beartype.door.TypeHint`
subclass).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.door._cls.doorsuper import TypeHint
from beartype.roar import BeartypeDoorPepArgsLenException
from beartype._data.hint.sign.datahintsignmap import (
    HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE)

# ....................{ SUBCLASSES                         }....................
class SubscriptedTypeHint(TypeHint):
    '''
    **Subscripted type hint wrapper** (i.e., high-level object encapsulating
    a low-level parent type hint satisfying various conditions).

    Notably, this wrapper wraps hints that both:

    * Are either :pep:`484`- or :pep:`585`-compliant.
    * Are subscripted (indexed) by a predetermined number of one or more
      low-level child type hints.
    * Originate from an **isinstanceable class** such that *all* objects
      satisfying this hint are instances of that class.
    '''

    # ..................{ PRIVATE ~ factories                }..................
    def _make_args(self) -> tuple:

        # Tuple of the zero or more low-level child type hints subscripting
        # (indexing) the low-level parent type hint wrapped by this wrapper.
        args = super()._make_args()

        # Argument length range (i.e., "range" object covering the minimum and
        # maximum number of child type hints that may subscript this low-level
        # parent type hint factory) if this factory has been associated with
        # such a range *OR* "None" otherwise (i.e., if this factory has *NOT*
        # been associated with such a range).
        args_len_range = HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE.get(
            self._hint_sign)  # type: ignore[arg-type]

        # If this factory has *NOT* been associated with such a range, raise an
        # exception. Note that this edge case should *NEVER occur. ----gulp----
        if args_len_range is None:  # pragma: no cover
            raise BeartypeDoorPepArgsLenException(  # pragma: no cover
                f'Type hint {repr(self._hint)} argument length range unknown.')
        # Else, this factory has been associated with such a range.

        #FIXME: Consider actually testing this. This *IS* technically
        #testable and should thus *NOT* be marked as "pragma: no cover".

        # If this hint was subscripted by an unexpected number of child hints...
        #
        # Note that this edge case commonly occurs with PEP 585-compliant type
        # hints (e.g., "list[str]"), which fail to validate their number of
        # child type hints: e.g.,
        #     >>> list[str, int]
        #     list[str, int]  # <-- wat
        if len(args) not in args_len_range:  # pragma: no cover
            #FIXME: This seems sensible, but currently provokes test failures.
            #Let's investigate further at a later time, please.
            # # If this hint was subscripted by *NO* parameters, comply with PEP
            # # 484 standards by silently pretending this hint was subscripted by
            # # the "typing.Any" fallback for all missing parameters.
            # if len(self._args) == 0:
            #     return (Any,)*self._args_len_expected

            # Exception message to be raised.
            exception_message = (
                f'PEP 585 type hint {repr(self._hint)} '
                f'not subscripted (indexed) by '
            )

            # Minimum and maximum number of arguments accepted by this factory.
            #
            # Note that the "stop" instance variable defined by "range" objects
            # is exclusive rather than inclusive. Substracting 1 from that
            # yields the inclusive maximum of this range.
            ARGS_LEN_MIN = args_len_range.start
            ARGS_LEN_MAX = args_len_range.stop - 1

            # If this factory accepts a constant (rather than variable) number
            # of child hints, raise a human-readable exception denoting this.
            if ARGS_LEN_MIN == ARGS_LEN_MAX:
                # Human-readable noun describing the grammatically correct
                # plurality of the number of expected child type hints. English!
                exception_noun = (
                    'child type hint' if len(args) == 1 else 'child type hints')

                # Append this number to this exception message.
                exception_message += (
                    f'{ARGS_LEN_MAX} {exception_noun} (i.e., '
                    f'subscripted by {len(args)} != '
                    f'{ARGS_LEN_MAX} child type hints).'
                )
            # Else, this factory accepts a variable number of child hints. Raise
            # a human-readable exception denoting this.
            else:
                # Append this number to this exception message.
                exception_message += (
                    f'[{ARGS_LEN_MIN}, {ARGS_LEN_MAX}] arguments (i.e., '
                    f'subscripted by {len(args)} child type hints).'
                )

            # Raise this exception.
            raise BeartypeDoorPepArgsLenException(exception_message)
        # Else, this hint was subscripted by the expected number of child hints.

        # Return these child hints.
        return args

    # ..................{ PRIVATE ~ testers                  }..................
    # Note that this redefinition of the superclass _is_equal() method is
    # technically unnecessary, as that method is already sufficiently
    # general-purpose to suffice for *ALL* possible subclasses (including this
    # subclass). Nonetheless, we wrote this method first. More importantly, this
    # method is *SUBSTANTIALLY* faster than the superclass method. Although
    # efficiency is typically *NOT* a pressing concern for the DOOR API,
    # discarding faster working code would be senseless.
    def _is_equal(self, other: TypeHint) -> bool:

        # If *ALL* of the child type hints subscripting both of these parent
        # type hints are ignorable, return true only if these parent type hints
        # both originate from the same isinstanceable class.
        if self._is_args_ignorable and other._is_args_ignorable:
            return self._origin == other._origin
        # Else, one or more of the child type hints subscripting either of these
        # parent type hints are unignorable.
        #
        # If either...
        elif (
            # These hints have differing signs *OR*...
            self._hint_sign is not other._hint_sign or
            # These hints have a differing number of child type hints...
            len(self._args_wrapped_tuple) != len(other._args_wrapped_tuple)
        ):
            # Then these hints are unequal.
            return False
        # Else, these hints share the same sign and number of child type hints.

        # Return true only if all child type hints of these hints are equal.
        return all(
            this_child == that_child
            #FIXME: Probably more efficient and maintainable to write this as:
            #    for this_child in self
            #    for that_child in other
            for this_child, that_child in zip(
                self._args_wrapped_tuple, other._args_wrapped_tuple)
        )
