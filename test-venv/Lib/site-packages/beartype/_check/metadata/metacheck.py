#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype type-check call metadata dataclass** (i.e., class aggregating *all*
metadata required by the current call to the wrapper function type-checking a
:func:`beartype.beartype`-decorated callable).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import TYPE_CHECKING
from beartype._cave._cavemap import NoneTypeOr
from beartype._check.metadata.metadecor import BeartypeDecorMeta
from beartype._conf.confmain import BeartypeConf
from beartype._data.typing.datatyping import TypeStack
from beartype._data.typing.datatypingport import DictStrToHint
from collections.abc import Callable

# ....................{ CLASSES                            }....................
#FIXME: Unit test us up, please.
class BeartypeCheckMeta(object):
    '''
    **Beartype type-check call metadata** (i.e., object encapsulating *all*
    metadata required by each call to the wrapper function type-checking the
    callable currently being decorated by the :func:`beartype.beartype`
    decorator).

    Design
    ------
    This type-checking-time dataclass is effectively the proper subset of the
    comparable -- but *much* more complex in both space, time, and code
    complexity -- **decoration call metadata dataclass** (i.e.,
    :class:`beartype._check.metadata.metadecor.BeartypeDecorMeta`).
    Theoretically, this type-checking-time dataclass is thus redundant; the
    existing decoration call metadata dataclass could simply be used in lieu of
    this type-checking-time dataclass. Pragmatically, this type-checking-time
    dataclass significantly reduces the sheer quantity of metadata needed to
    type-check :func:`beartype.beartype`-decorated callables and thus the space
    consumption associated with that type-checking. In short, this is necessary.

    Attributes
    ----------
    cls_stack : TypeStack
        **Type stack** (i.e., either tuple of zero or more arbitrary types *or*
        :data:`None`). See also the parameter of the same name accepted by the
        :func:`beartype._decor.decorcore.beartype_object` function for details.
    conf : BeartypeConf
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all flags, options, settings, and other metadata configuring the
        current decoration of the decorated callable).
    func : Callable
        **Decorated callable** (i.e., high-level callable currently being
        decorated by the :func:`beartype.beartype` decorator).
    func_annotations : dict[str, Hint]
        **Type hint dictionary** (i.e., mapping from the name of each annotated
        parameter accepted by the decorated callable to the type hint annotating
        that parameter).
    '''

    # ..................{ CLASS VARIABLES                    }..................
    # Slot all instance variables defined on this object to minimize the time
    # complexity of both reading and writing variables across frequently
    # called @beartype decorations. Slotting has been shown to reduce read and
    # write costs by approximately ~10%, which is non-trivial.
    __slots__ = (
        'cls_stack',
        'conf',
        'func',
        'func_annotations',
    )

    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        cls_stack: TypeStack
        conf: BeartypeConf
        func: Callable
        func_annotations: DictStrToHint

    # Coerce instances of this class to be unhashable, preventing spurious
    # issues when accidentally passing these instances to memoized callables by
    # implicitly raising a "TypeError" exception on the first call to those
    # callables. There exists no tangible benefit to permitting these instances
    # to be hashed (and thus also cached), since these instances are:
    # * Specific to the decorated callable and thus *NOT* safely cacheable
    #   across functions applying to different decorated callables.
    #
    # See also:
    #     https://docs.python.org/3/reference/datamodel.html#object.__hash__
    __hash__ = None  # type: ignore[assignment]

    # ..................{ INITIALIZERS                       }..................
    def __init__(
        self,
        conf: BeartypeConf,
        cls_stack: TypeStack,
        func: Callable,
        func_annotations: DictStrToHint,
    ) -> None:
        '''
        Initialize this metadata with the passed parameters.

        Caveats
        -------
        **Avoid calling this low-level initializer directly.** Instead,
        instantiate instances of this dataclass by calling the
        :meth:`make_from_decor_meta` class method -- reducing existing
        instances of the parent :class:`.BeartypeDecorMeta` dataclass to
        instances of this child dataclass.

        Parameters
        ----------
        cls_stack : TypeStack
            **Type stack** (i.e., either tuple of zero or more arbitrary types
            *or* :data:`None`). See also the parameter of the same name accepted
            by the :func:`beartype._decor.decorcore.beartype_object` function
            for details.
        conf : BeartypeConf
            **Beartype configuration** (i.e., self-caching dataclass
            encapsulating all flags, options, settings, and other metadata
            configuring the current decoration of the decorated callable).
        func : Callable
            **Decorated callable** (i.e., high-level callable currently being
            decorated by the :func:`beartype.beartype` decorator).
        func_annotations : dict[str, Hint]
            **Type hint dictionary** (i.e., mapping from the name of each
            annotated parameter accepted by the decorated callable to the type
            hint annotating that parameter).
        '''
        assert isinstance(cls_stack, NoneTypeOr[tuple]), (
            f'{repr(cls_stack)} neither tuple nor "None".')
        assert isinstance(conf, BeartypeConf), (
            f'{repr(conf)} not beartype configuration.')
        assert callable(func), f'{repr(func)} uncallable.'
        assert isinstance(func_annotations, dict), (
            f'{repr(func_annotations)} not dictionary.')

        # Classify all passed parameters as instance variables.
        self.cls_stack = cls_stack
        self.conf = conf
        self.func = func
        self.func_annotations = func_annotations

    # ..................{ CLASS METHODS                      }..................
    @classmethod
    def make_from_decor_meta(
        cls, decor_meta: BeartypeDecorMeta) -> 'BeartypeCheckMeta':
        '''
        **Beartype type-check call metadata** (i.e., object encapsulating *all*
        metadata required by the current call to the wrapper function
        type-checking the callable currently being decorated by the
        :func:`beartype.beartype` decorator) reduced from the passed **beartype
        decorator call metadata** (i.e., object encapsulating *all* metadata for
        that callable).

        Parameters
        ----------
        decor_meta : BeartypeDecorMeta
            Beartype decorator call metadata to be reduced.
        '''
        assert isinstance(decor_meta, BeartypeDecorMeta)

        # Create and return a new instance of this child dataclass reduced from
        # the passed parent dataclass.
        return BeartypeCheckMeta(
            conf=decor_meta.conf,
            cls_stack=decor_meta.cls_stack,
            func=decor_meta.func_wrappee,
            func_annotations=decor_meta.func_annotations,
        )


    @classmethod
    def make_from_decor_meta_kwargs(cls, **kwargs) -> 'BeartypeCheckMeta':
        '''
        **Beartype type-check call metadata** (i.e., object encapsulating *all*
        metadata required by the current call to the wrapper function
        type-checking the callable currently being decorated by the
        :func:`beartype.beartype` decorator) reduced from the passed **beartype
        decorator call metadata keyword parameters** (i.e., keyword parameters
        to be passed to the :meth:`BeartypeDecorMeta.reinit` method).

        This factory method is a high-level convenience principally intended to
        be called from unit tests.

        Parameters
        ----------
        All passed keyword parameters are passed as is to the
        :meth:`BeartypeDecorMeta.reinit` method.
        '''

        # Beartype decorator call metadata with which to instantiate a new
        # instance of this dataclass.
        decor_meta = BeartypeDecorMeta()
        decor_meta.reinit(**kwargs)

        # Beartype type-checking call metadata reduced from this metadata.
        return cls.make_from_decor_meta(decor_meta)
