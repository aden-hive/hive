#!/usr/bin/env python3
#--------------------( LICENSE                             )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Decidedly Object-Oriented Runtime-checking (DOOR) callable type hint classes**
(i.e., :class:`beartype.door.TypeHint` subclasses implementing support for
:pep:`484`- and :pep:`585`-compliant ``Tuple[...]`` type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.door._cls.doorsuper import TypeHint
from beartype.door._cls.pep.pep484585.doorpep484585subscripted import (
    SubscriptedTypeHint)
from beartype._util.hint.pep.proposal.pep484585646 import (
    is_hint_pep484585646_tuple_empty,
    is_hint_pep484585646_tuple_variadic,
)

# ....................{ SUBCLASSES                         }....................
class TupleFixedTypeHint(TypeHint):
    '''
    **Fixed-length tuple type hint wrapper** (i.e., high-level object
    encapsulating a low-level :pep:`484`- or :pep:`585`-compliant type hint of
    the form ``tuple[{child_hint_1}, ..., {child_hint_N}]``).
    '''

    # ..................{ INITIALIZERS                       }..................
    def _make_args(self) -> tuple:

        # Tuple of the zero or more low-level child type hints subscripting
        # (indexing) the low-level parent type hint wrapped by this wrapper.
        args = super()._make_args()

        # If this is the empty fixed-length tuple type hint (e.g., "tuple[()]"),
        # reduce this awkward nested-empty-tuple-in-a-1-tuple to an elegant
        # empty tuple as expected by sane users. Even if users wanted us to
        # return an awkward nested-empty-tuple-in-a-1-tuple, we couldn't. Why?
        # Because an empty tuple is *NOT* otherwise a valid type hint and
        # *CANNOT* thus be wrapped by an instance of the "TypeHint" superclass.
        if is_hint_pep484585646_tuple_empty(self._hint):
            args = ()
        # Else, this is a non-empty fixed-length tuple type hint (e.g.,
        # "tuple[int, str]"). In this case, preserve these child hints as is.

        # Return these child hints.
        return args

    # ..................{ PRIVATE ~ properties               }..................
    @property
    def _is_args_ignorable(self) -> bool:

        # Prevent the child type hints subscripting *ANY* fixed-length tuple
        # type hints from being ignored as a whole, even if one or all of those
        # child type hints are technically ignorable. Why? Because ignoring all
        # child type hints as a whole would then prevent the length of this
        # tuple type hint from being type-checked, which would rather defeat the
        # purpose of the whole thing really.
        return False

    # ..................{ PRIVATE ~ testers                  }..................
    def _is_subhint_branch(self, branch: TypeHint) -> bool:

        # print(f'self: {repr(self)}; branch: {repr(branch)}')

        # If the other hint branch is unsubscripted (e.g., "typing.Callable"),
        # assume that hint to be subscripted as "typing.Callable[..., Any]" by
        # reducing to a test for compatible origin types.
        if branch._is_args_ignorable:
            return issubclass(self._origin, branch._origin)
        # Else, that hint is subscripted.
        #
        # If that hint is a variable-length tuple, then this fixed-length tuple
        # is commensurable (i.e., comparable) with that hint despite having a
        # differing class. In this case...
        elif isinstance(branch, TupleVariableTypeHint):
            # Child hint subscripting that variable-length tuple.
            branch_child = branch._args_wrapped_tuple[0]

            # Return true only if *ALL* child hints subscripting this
            # fixed-length tuple are subhints of the single child hint
            # subscripting that variable-length tuple: e.g.,
            #     >>> TypeHint(tuple[str, str]) <= TypeHint(tuple[str, ...])
            #     True
            #     >>> TypeHint(tuple[str, int]) <= TypeHint(tuple[str, ...])
            #     False
            return all(
                self_child <= branch_child
                for self_child in self._args_wrapped_tuple
            )
        # Else, the other hint is *NOT* a variable-length tuple.
        #
        # If the other hint is also *NOT* a fixed-length tuple, these two hints
        # are incommensurable. In this case, return false.
        elif not isinstance(branch, TupleFixedTypeHint):
            return False
        # Else, the other hint is also a fixed-length tuple.
        #
        # If these two hints are subscripted by a differing number of child
        # hints, return false.
        elif len(self) != len(branch):
            return False
        # Else, these two hints are subscripted by the same number of child
        # hints.

        # Return true only if each child hint subscripting this hint is a
        # subhint of the corresponding child hint subscripting that hint.
        return all(
            self_child <= branch_child
            for self_child, branch_child in zip(
                self._args_wrapped_tuple, branch._args_wrapped_tuple)
        )


class TupleVariableTypeHint(SubscriptedTypeHint):
    '''
    **Variable-length tuple type hint wrapper** (i.e., high-level object
    encapsulating a low-level :pep:`484`- or :pep:`585`-compliant type hint of
    the form ``tuple[{child_hint}, ...]``).
    '''

    # ..................{ INITIALIZERS                       }..................
    def _make_args(self) -> tuple:

        # Tuple of the two low-level child type hints subscripting (indexing)
        # the low-level parent type hint wrapped by this wrapper.
        args = super()._make_args()

        # Validate this parent type hint to be subscripted sanely.
        #
        # Note that the previously called get_hint_pep_sign() getter already
        # validated this to be the case.
        assert is_hint_pep484585646_tuple_variadic(self._hint), (
            f'PEP 585 variable-length tuple type hint {repr(self._hint)} '
            f'not of the form "tuple[{{child_hint}}, ...]".'
        )

        # Reduce this tuple to the 1-tuple consisting *ONLY* of the first child
        # type hint subscripting this parent type hint. Equivalently, ignore the
        # second child type subscripting this parent type hint; by the above
        # validation, the latter is guaranteed to be the ellipses singleton,
        # which is *NOT* otherwise a valid type hint and *CANNOT* thus be
        # wrapped by an instance of the "TypeHint" superclass.
        return (args[0],)
