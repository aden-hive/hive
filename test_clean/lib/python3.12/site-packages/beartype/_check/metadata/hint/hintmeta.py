#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **type-checking code classes** (i.e., low-level classes storing
metadata describing each iteration of the breadth-first search (BFS) dynamically
generating pure-Python code snippets type-checking arbitrary objects against
PEP-compliant type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    TYPE_CHECKING,
    Optional,
)
from beartype._cave._cavemap import NoneTypeOr
from beartype._check.code.snip.codesnipcls import HINT_INDEX_TO_HINT_PLACEHOLDER
from beartype._check.metadata.hint.hintsane import HintSane
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.kind.datakindiota import SENTINEL

# ....................{ DATACLASSES                        }....................
#FIXME: Unit test us up, please.
class HintMeta(object):
    '''
    **Type hint type-checking metadata** (i.e., low-level dataclass storing
    metadata describing the possibly nested type hint visited by the current
    iteration of the breadth-first search (BFS) dynamically generating
    pure-Python type-checking code snippets in the
    :func:`beartype._check.code.codemain.make_check_expr` factory).

    Attributes
    ----------
    hint_placeholder : str
        **Type-checking placeholder substring** to be globally replaced in the
        **type-checking wrapper function code snippet** (i.e., the
        ``func_wrapper_code`` local defined by the
        :func:`beartype._check.code.codemain.make_check_expr` factory) by a
        Python code snippet type-checking the **current pith expression** (i.e.,
        the ``pith_var_name`` local) against the **currently visited type hint**
        (i.e., the :attr:`hint` instance variable).
    hint_sane : HintSane
        **Sanified type hint metadata** (i.e., immutable and thus hashable
        object encapsulating *all* metadata returned by
        :mod:`beartype._check.convert.convmain` sanifiers after sanitizing
        this possibly PEP-noncompliant hint into a fully PEP-compliant hint)
        describing the type hint currently visited by this BFS.
    hint_sign : Optional[HintSign]
        Either:

        * If this hint is PEP-compliant, the **sign** (i.e., singleton instance
          of the :class:`.HintSign` class) uniquely identifying this hint.
        * Else, :data:`None`.
    indent_level : int
        **Indentation level** (i.e., 1-based positive integer providing the
        level of indentation appropriate for this hint).
        Indexing the
        :obj:`beartype._data.code.datacodeindent.INDENT_LEVEL_TO_CODE`
        dictionary singleton by this integer efficiently yields the current
        **indendation string** suitable for prefixing each line of code
        type-checking the current pith against this hint.
    pith_expr : str
        **Pith expression** (i.e., Python code snippet evaluating to the value
        of) the current **pith** (i.e., possibly nested object of the passed
        parameter or return to be type-checked against this hint). Note that
        this expression is intentionally *not* an assignment expression but
        rather the original inefficient expression provided by the parent type
        hint of this hint.
    pith_var_name_index : int
        **Pith variable name index** (i.e., 0-based integer suffixing the name
        of each local variable assigned the value of the current pith in an
        assignment expression, thus uniquifying this variable in the body of the
        current wrapper function). Indexing the
        :obj:`beartype._check.code.snip.codesnipcls.PITH_INDEX_TO_VAR_NAME`
        dictionary singleton by this integer efficiently yields the current
        **pith variable name** locally storing the value of the current pith.
    '''

    # ..................{ CLASS VARIABLES                    }..................
    # Slot all instance variables defined on this object to minimize the time
    # complexity of both reading and writing variables across frequently called
    # cache dunder methods. Slotting has been shown to reduce read and write
    # costs by approximately ~10%, which is non-trivial.
    __slots__ = (
        'hint_placeholder',
        'hint_sane',
        'hint_sign',
        'indent_level',
        'pith_expr',
        'pith_var_name_index',
    )

    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        hint_placeholder: str
        hint_sane: HintSane
        hint_sign: Optional[HintSign]
        indent_level: int
        pith_expr: str
        pith_var_name_index: int

    # ..................{ INITIALIZERS                       }..................
    def __init__(self, hint_index: int) -> None:
        '''
        Initialize this type-checking metadata.

        Parameters
        ----------
        hint_index : int
            0-based index of this type-checking metadata in the parent
            :class:`.HintsMeta` list containing this metadata.
        '''
        assert isinstance(hint_index, int), f'{repr(hint_index)} not integer.'
        assert hint_index >= 0, f'{repr(hint_index)} < 0.'

        # Placeholder string to be globally replaced by code type-checking the
        # current pith against this hint.
        self.hint_placeholder = HINT_INDEX_TO_HINT_PLACEHOLDER[hint_index]

        # Nullify all remaining instance variables for safety.
        self.hint_sane = SENTINEL  # type: ignore[assignment]
        self.hint_sign = SENTINEL  # type: ignore[assignment]
        self.indent_level = SENTINEL  # type: ignore[assignment]
        self.pith_expr = SENTINEL  # type: ignore[assignment]
        self.pith_var_name_index = SENTINEL  # type: ignore[assignment]


    def reinit(
        self,
        hint_sane: HintSane,
        hint_sign: Optional[HintSign],
        indent_level: int,
        pith_expr: str,
        pith_var_name_index: int,
    ) -> None:
        '''
        Reinitialize this type-checking metadata to reflect a newly visited type
        hint during the breadth-first search (BFS) over the current tree of type
        hints.

        Parameters
        ----------
        hint_sane : HintSane
            Metadata describing the sanification of this hint.
        hint_sign : Optional[HintSign]
            Either:

            * If this hint is PEP-compliant, the sign identifying this hint.
            * Else, :data:`None`.
        indent_level : int
            1-based indentation level describing the current level of
            indentation appropriate for this hint.
        pith_expr : str
            Python code snippet evaluating to the child pith to be type-checked
            against this hint.
        pith_var_name_index : int
            0-based integer suffixing the name of each local variable assigned
            the value of the current pith in an assignment expression.

        See Also
        --------
        Class docstring for further details on the passed parameters.
        '''
        assert isinstance(hint_sane, HintSane), (
            f'{repr(hint_sane)} not sanified hint metadata.')
        assert isinstance(hint_sign, NoneTypeOr[HintSign]), (
            f'{repr(hint_sign)} neither hint sign nor "None".')
        assert isinstance(indent_level, int), (
            f'{repr(indent_level)} not integer.')
        assert isinstance(pith_expr, str), (
            f'{repr(pith_expr)} not string.')
        assert isinstance(pith_var_name_index, int), (
            f'{repr(pith_var_name_index)} not integer.')
        assert indent_level >= 1, f'{repr(indent_level)} < 1.'
        assert pith_expr, f'{repr(pith_expr)} empty.'
        assert pith_var_name_index >= 0, f'{repr(pith_var_name_index)} < 0.'

        # Classify all passed parameters.
        self.hint_sane = hint_sane
        self.hint_sign = hint_sign
        self.indent_level = indent_level
        self.pith_expr = pith_expr
        self.pith_var_name_index = pith_var_name_index

    # ..................{ DUNDERS                            }..................
    def __repr__(self) -> str:
        '''
        Machine-readable representation of this metadata.
        '''

        # Represent this metadata with just the minimal subset of metadata
        # needed to reasonably describe this metadata.
        return (
            f'{self.__class__.__name__}('
            f'hint_sane={repr(self.hint_sane)}, '
            f'hint_sign={repr(self.hint_sign)}, '
            f'indent_level={repr(self.indent_level)}, '
            f'pith_expr={repr(self.pith_expr)}, '
            f'pith_var_name_index={repr(self.pith_var_name_index)}, '
            f')'
        )
