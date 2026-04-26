#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **Decidedly Object-Oriented Runtime-checking (DOOR) generic type hint
classes** (i.e., :class:`beartype.door.TypeHint` subclasses implementing support
for :pep:`484`- and :pep:`585`-compliant classes subclassing subclassable type
hints, including the ``typing.Generic[...]`` and ``typing.Protocol[...]`` type
hint superclasses).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.door._cls.doorsuper import TypeHint
from beartype.door._cls.pep.pep484.doorpep484class import ClassTypeHint
from beartype.door._cls.pep.pep484585.doorpep484585subscripted import (
    SubscriptedTypeHint as SubscriptedTypeHint)
from beartype.roar import BeartypeDoorIsSubhintException
from beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget import (
    get_hint_pep484585_generic_args_full)

# ....................{ SUBCLASSES                         }....................
class GenericTypeHint(TypeHint):
    '''
    **Generic type hint wrapper** (i.e., high-level object encapsulating a
    low-level subclass of the :pep:`484`-compliant :class:`typing.Generic`
    superclass, :pep:`544`-compliant :class:`typing.Protocol` superclass, or any
    :pep:`585`-compliant subscripted type hint (e.g., ``class
    GenericListOfStrs(list[str]): ...``).
    '''

    # ..................{ PRIVATE ~ testers                  }..................
    def _is_subhint_branch(self, branch: TypeHint) -> bool:
        # print(f'Entering GenericTypeHint._is_subhint_branch({self}, {branch})...')

        # If the unsubscripted type originating this generic is *NOT* a subclass
        # of the unsubscripted type originating that branch, this generic is
        # *NOT* a subhint of that branch. In this case, return false.
        if not issubclass(self._origin, branch._origin):
            # print(f'{self._origin} not subclass of {branch._origin})!')
            return False
        # Else, the unsubscripted type originating this generic is a subclass
        # of the unsubscripted type originating that branch. Note, however, that
        # this does *NOT* imply this generic to be a subhint of that branch.
        # The issubclass() builtin ignores parametrizations and thus returns
        # false positives for parametrized generics: e.g.,
        #     >>> from typing import Generic, TypeVar
        #     >>> T = TypeVar('T')
        #     >>> class MuhGeneric(Generic[T]): pass
        #     >>> issubclass(MuhGeneric, MuhGeneric[int])
        #     True
        #
        # Clearly, the unsubscripted generic "MuhGeneric" is a superhint
        # (rather than a subhint) of the subscripted generic
        # "MuhGeneric[int]". Further introspection is needed.
        #
        # If that branch is unsubscripted, assume that branch to have been
        # subscripted by "Any". Since *ANY* child hint subscripting this hint is
        # necessarily a subhint of "Any", this hint is a subhint of that branch.
        # Return true immediately.
        #
        # Note that this this common edge case implicitly handles comparison of
        # this generic against an unsubscripted simple class encapsulated by the
        # "ClassTypeHint" wrapper. Why? Because the
        # "ClassTypeHint._is_args_ignorable" property unconditionally returns
        # "True". Ergo, "ClassTypeHint" need *NOT* be handled below.
        elif branch._is_args_ignorable:
            # print(f'is_subhint_branch({self}, {branch} [unsubscripted])')
            return True
        # Else, that branch is subscripted.
        #
        # If this generic and that subscripted branch are incommensurable (i.e.,
        # encapsulated by incomparable type hint wrappers *NOT* supporting
        # comparison between a generic and a possibly non-generic type hint),
        # this generic is *NOT* a subhint of that branch. In this case, return
        # false.
        elif not isinstance(branch, _IS_SUBHINT_TYPES_COMMENSURABLE):
            # print(f'{branch.__class__} not in {_IS_SUBHINT_TYPES_COMMENSURABLE})!')
            return False
        # Else, this generic and that subscripted branch are commensurable
        # (i.e., encapsulated by comparable type hint wrappers supporting
        # comparison between a generic and a possibly non-generic type hint).
        #
        # By elimination, that branch *MUST* now be encapsulated by either:
        # * If that branch is also a PEP 484- or 585-compliant user-defined
        #   subscripted generic, "GenericTypeHint".
        # * Else, that branch *MUST* be a PEP 484- or 585-compliant subscripted
        #   non-generic (e.g., "list[int]", "collections.abc.Sized[str]").

        # Human-readable substring prefixing exception messages raised below.
        exception_prefix = f'{self} <= {branch} undecidable, as '

        # Tuple of the zero or more child hints transitively (i.e., *NOT*
        # directly) subscripting this generic *WITH RESPECT TO THAT BRANCH*.
        # This tuple generalizes the original tuple of child type hints directly
        # (i.e., *NOT* transitively) subscripting this generic. A generic is
        # transitively subscripted by the tuple of all child hints directly
        # subscripting this generic and all pseudo-superclasses of this generic.
        #
        # Deciding this tuple requires a highly non-trivial algorithm
        # performing a recursive depth-first search (DFS) over the
        # pseudo-superclass hierarchy implied by this generic. Doing so greedily
        # replaces in the original tuple as many abstract PEP 484-compliant type
        # variables (i.e., "typing.TypeVar" objects) as there are concrete child
        # hints directly subscripting this generic. Doing so effectively
        # "bubbles up" these concrete children up the class hierarchy into the
        # "empty placeholders" established by the type variables transitively
        # subscripting all pseudo-superclasses of this generic.  # <-- lolwat
        #
        # Note that this getter is memoized for efficiency and thus
        # intentionally accepts *NO* keyword parameters. It is what it is.
        self_args_full = get_hint_pep484585_generic_args_full(
            # This generic.
            self._hint,

            # The target pseudo-superclass of this generic to be searched for in
            # the pseudo-superclass hierarchy implied by this generic.
            branch._hint,  # pyright: ignore

            # Exception class to be raised in the event of fatal error.
            BeartypeDoorIsSubhintException,

            # Human-readable substring prefixing raised exception messages.
            exception_prefix,
        )
        # print(f'Found self {self} full child hints: {self_args_full}')

        #FIXME: Unit test us up, please.
        # If that branch is a subscripted non-generic (e.g., "Sequence[int]")...
        if isinstance(branch, SubscriptedTypeHint):
            # print(f'Comparing against subscripted non-generic {branch}...')

            # If these two hints are subscripted by a differing number of child
            # hints, raise an exception. See the superclass method for details.
            #
            # Note that this should *NEVER* occur. Therefore, this will occur.
            if len(self_args_full) != len(branch._args_wrapped_tuple):  # pragma: no cover
                # Number of child hints subscripting that branch.
                branch_args_len = len(branch._args_wrapped_tuple)

                # Raise an exception embedding these numbers.
                raise BeartypeDoorIsSubhintException(
                    f'{exception_prefix}'
                    f'{self._hint} transitively subscripted by child hints '
                    f'{self_args_full} whose length differs from '
                    f'{branch._hint} directly subscripted by child hints '
                    f'{branch.args} '
                    f'(i.e., {len(self_args_full)} != {branch_args_len}).'
                )
            # Else, these two hints are subscripted by the same number of child
            # hints.

            # For the 0-based index of each child hint transitively subscripting
            # this generic and this hint...
            for self_arg_full_index, self_arg_full in enumerate(self_args_full):
                # Hint wrapper encapsulating this child hint transitively
                # subscripting this generic.
                self_child = TypeHint(self_arg_full)

                # Hint wrapper encapsulating the corresponding child hint
                # directly subscripting that non-generic branch.
                branch_child = branch._args_wrapped_tuple[self_arg_full_index]

                # If this child hint is *NOT* a subhint of that child hint, this
                # generic is *NOT* a subhint of that non-generic branch. In this
                # case, short-circuit by immediately returning false.
                if not self_child.is_subhint(branch_child):
                    # print(f'{self_child} <= {branch_child} == False!')
                    return False
                # Else, this child hint is a subhint of that child hint. In this
                # case, this generic *COULD* be a subhint of that non-generic
                # branch. Decide by continuing to the next pair of child hints.

                # print(f'{self_child} <= {branch_child} == True...')
            # Else, each child hint of this generic is a subhint of the
            # corresponding child hint of that non-generic branch. In this case,
            # this generic is a subhint of that non-generic branch.
        # Else, that branch is *NOT* a subscripted non-generic
        # (e.g., "Sequence[int]"). By the above validation, that branch is both
        # subscripted and commensurable with this generic. By elimination, that
        # branch *MUST* be a subscripted generic (e.g., "MuhGeneric[T]"). In
        # this case...
        else:
            # print(f'Comparing against subscripted generic {branch}...')

            # Validate that that branch is, in fact, a subscripted generic.
            assert isinstance(branch, GenericTypeHint), (
                f'{branch} not PEP 484 or 585 subscripted generic '
                f'(i.e., "beartype.door.GenericTypeHint" instance).')

            # Tuple of the zero or more child hints transitively subscripting
            # that generic branch. See above for further details.
            branch_args_full = get_hint_pep484585_generic_args_full(
                # That generic branch.
                branch._hint,

                # *NO* target pseudo-superclass of that generic branch. Instead,
                # completely decide the full tuple of child hints transitively
                # subscripting that generic branch.
                None,

                # Exception class to be raised in the event of fatal error.
                BeartypeDoorIsSubhintException,

                # Human-readable substring prefixing raised exception messages.
                exception_prefix,
            )
            # print(f'Found branch {branch} full child hints: {branch_args_full}')

            # If these two generics are transitively subscripted by a differing
            # number of child hints, raise an exception. See above for details.
            #
            # Note that this should *NEVER* occur. Therefore, this will occur.
            if len(self_args_full) != len(branch_args_full):  # pragma: no cover
                # Raise an exception embedding these numbers.
                raise BeartypeDoorIsSubhintException(
                    f'{exception_prefix}'
                    f'{self._hint} transitively subscripted by child hints '
                    f'{self_args_full} whose length differs from '
                    f'{branch._hint} transitively subscripted by child hints '
                    f'{branch_args_full} '
                    f'(i.e., {len(self_args_full)} != {len(branch_args_full)}).'
                )
            # Else, these two generics are transitively subscripted by the same
            # number of child hints.

            # For the 0-based index of each child hint transitively subscripting
            # this generic and this hint...
            for self_arg_full_index, self_arg_full in enumerate(self_args_full):
                # Hint wrapper encapsulating this child hint transitively
                # subscripting this generic.
                self_child = TypeHint(self_arg_full)

                # Hint wrapper encapsulating the corresponding child hint
                # directly subscripting that generic branch.
                branch_child = TypeHint(branch_args_full[self_arg_full_index])
                # print(f'{self_child} <= {branch_child}?')

                # If this child hint is *NOT* a subhint of that child hint, this
                # generic is *NOT* a subhint of that generic branch. In this
                # case, short-circuit by immediately returning false.
                if not self_child.is_subhint(branch_child):
                    # print(f'{self_child} <= {branch_child} == False!')
                    return False
                # Else, this child hint is a subhint of that child hint. In this
                # case, this generic *COULD* be a subhint of that generic
                # branch. Decide by continuing to the next pair of child hints.

                # print(f'{self_child} <= {branch_child} == True...')
            # Else, each child hint of this generic is a subhint of the
            # corresponding child hint of that generic branch. In this case,
            # this generic is a subhint of that generic branch.

        # Return true! We have liftoff.
        return True

# ....................{ PRIVATE ~ constants                }....................
_IS_SUBHINT_TYPES_COMMENSURABLE = (
    # Generics are commensurable with other generics, clearly.
    GenericTypeHint,

    # Generics are also commensurable with subscripted type hints: e.g.,
    #     >>> from collections.abc import Sequence
    #     >>> class MuhSequence[T](Sequence[T]): pass
    #     >>> is_subhint(MuhSequence[int], Sequence[int])
    #     True
    SubscriptedTypeHint,

    # Generics are also commensurable with unsubscripted simple classes: e.g.,
    #     >>> from collections.abc import Sequence
    #     >>> class MuhSequence[T](Sequence[T]): pass
    #     >>> is_subhint(MuhSequence[T], Sequence)
    #     True
    ClassTypeHint,
)
'''
Tuple of all **commensurable generic types** (i.e., concrete :class:`.TypeHint`
subclasses such that the :meth:`GenericTypeHint._is_subhint_branch` method
returns :data:`False` if the passed ``branch`` parameter is *not* an instance of
a type in this tuple).

When passed a ``branch`` parameter that is *not* an instance of a type in this
tuple, the :meth:`GenericTypeHint._is_subhint_branch` method returns
:data:`False` due to that parameter being **incommensurable** (i.e.,
incomparable) with a :pep:`484`-compliant :class:`typing.Generic`.
'''
