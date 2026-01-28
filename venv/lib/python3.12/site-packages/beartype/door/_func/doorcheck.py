#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **Decidedly Object-Oriented Runtime-checking (DOOR) procedural
type-checkers** (i.e., high-level functions type-checking arbitrary objects
against type hints at *any* time during the lifecycle of the active Python
process).
'''

# ....................{ TODO                               }....................
#FIXME: Consider adding the following new tester:
#    def is_objects_similar(
#        # Mandatory parameters.
#        obj: object,
#        schema: object,
#
#        # Optional keyword-only parameters.
#        *,
#        conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
#    ) -> bool:
#        schema_hint = infer_hint(schema, conf=conf)
#        return is_bearable(obj, schema_hint, conf=conf)
#
#This test implements a new **typing structural similarity** metric answering
#the question: "Do these two objects have a similar structure?" This is a softer
#metric than object equality, which is a softer metric than object identity.
#Nonetheless, this metric is *INCREDIBLY* useful for certain use cases: e.g.,
#data validation, where one predefined exemplar archetypal object defined by the
#developer serves as a templating "schema" used to validate other arbitrary
#objects defined and passed in by users.

# ....................{ IMPORTS                            }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: This submodule intentionally does *not* import the
# @beartype.beartype decorator. Why? Because that decorator conditionally
# reduces to a noop under certain contexts (e.g., `python3 -O` optimization),
# whereas the API defined by this submodule is expected to unconditionally
# operate as expected regardless of the current context.
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
from beartype._check.checkmake import (
    make_func_raiser,
    make_func_tester,
)
from beartype._conf.confmain import BeartypeConf
from beartype._conf.confcommon import BEARTYPE_CONF_DEFAULT
from beartype._data.typing.datatypingport import (
    Hint,
    HintBare,
    TypeIs,
)
from beartype._data.typing.datatyping import T

# ....................{ VALIDATORS                         }....................
def die_if_unbearable(
    # Mandatory flexible parameters.
    obj: object,
    hint: Hint,

    # Optional keyword-only parameters.
    *,
    conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
    exception_prefix: str = 'die_if_unbearable() ',
) -> None:
    '''
    Raise an exception if the passed arbitrary object violates the passed type
    hint under the passed beartype configuration.

    To configure the type of violation exception raised by this function, set
    the :attr:`.BeartypeConf.violation_door_type` option of the passed ``conf``
    parameter accordingly.

    Parameters
    ----------
    obj : object
        Arbitrary object to be type-checked against this hint.
    hint : Hint
        Type hint to type-check this object against.
    conf : BeartypeConf, optional
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all settings configuring type-checking for the passed object). Defaults
        to ``BeartypeConf()``, the default :math:`O(1)` constant-time
        configuration.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to a reasonably sensible string.

    Raises
    ------
    ``conf.violation_door_type``
        If this object violates this hint.
    beartype.roar.BeartypeDecorHintNonpepException
        If this hint is *not* PEP-compliant (i.e., complies with *no* Python
        Enhancement Proposals (PEPs) currently supported by :mod:`beartype`).
    beartype.roar.BeartypeDecorHintPepUnsupportedException
        If this hint is currently unsupported by :mod:`beartype`.

    Examples
    --------
    .. code-block:: pycon

       >>> from beartype.door import die_if_unbearable
       >>> die_if_unbearable(['And', 'what', 'rough', 'beast,'], list[str])
       >>> die_if_unbearable(['its', 'hour', 'come', 'round'], list[int])
       beartype.roar.BeartypeDoorHintViolation: Object ['its', 'hour', 'come',
       'round'] violates type hint list[int], as list index 0 item 'its' not
       instance of int.
    '''
    # conf._is_debug = True

    # Memoized low-level type-checking raiser function either raising an
    # exception or emitting a warning only if the passed object passed violates
    # the type hint passed to this high-level type-checking raiser function.
    #
    # Note that parameters are intentionally passed positionally for efficiency.
    # Since make_func_raiser() is memoized, passing parameters by keyword would
    # raise a non-fatal
    # "_BeartypeUtilCallableCachedKwargsWarning" warning.
    func_raiser = make_func_raiser(hint, conf, exception_prefix)  # pyright: ignore

    # Either raise an exception or emit a warning only if the passed object
    # violates this hint.
    func_raiser(obj)  # pyright: ignore

# ....................{ TESTERS ~ is_bearable              }....................
def is_bearable(
    # Mandatory flexible parameters.
    obj: object,
    hint: HintBare[T],

    # Optional keyword-only parameters.
    *,
    conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
) -> TypeIs[T]:  # pyright: ignore
    '''
    :data:`True` only if the passed arbitrary object satisfies the passed
    type hint under the passed beartype configuration.

    Note that this tester is a :pep:`647`- and :pep:`742`-compliant **smart type
    guard** (i.e., annotated by either the :pep:`742`-compliant return type hint
    ``typing.TypeIs[T]`` *or* the :pep:`647`-compliant return type hint
    ``typing.TypeGuard[T]`` conditionally depending on whether the active Python
    interpreter targets Python >= 3.13 or not). Specifically:

    * If the passed type hint is a valid **type** (i.e., subclass of the builtin
      :class:`type` superclass), this tester is a general-purpose type guard
      that performs type narrowing on the passed object: e.g.,

      .. code-block:: python

         from beartype.door import is_bearable

         def narrow_types_like_a_boss_with_beartype(lst: list[int | str]):
             # If "lst" is a list of integers, instruct static type-checkers
             # (e.g., mypy, pyright) that the call to munch_list_of_integers()
             # function expecting a list of integers is valid.
             #
             # Note that this works only because the is_bearable() tester
             # complies with PEP 647. If this were *NOT* the case, then static
             # type-checkers would raise a type-checking violation here.
             if is_bearable(lst, list[int]):
                 munch_list_of_integers(lst)
             # Else if "lst" is a list of strings, behave similarly as above.
             elif is_bearable(lst, list[str]):
                 munch_list_of_strings(lst)

         def munch_list_of_strings(lst: list[str]): ...
         def munch_list_of_integers(lst: list[int]): ....

    * If the passed type hint is *not* a valid type (e.g., the
      :pep:`586`-compliant ``typing.Literal['totally', 'not', 'a', 'type']``,
      which is clearly *not* a type), this tester is *not* a type guard and thus
      performs *no* type narrowing on the passed object. This is due to
      inadequacies in :pep:`647` rather than :mod:`beartype`.

    Parameters
    ----------
    obj : object
        Arbitrary object to be tested against this hint.
    hint : Hint
        Type hint to test this object against.
    conf : BeartypeConf, optional
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all settings configuring type-checking for the passed object). Defaults
        to ``BeartypeConf()``, the default constant-time configuration.

    Returns
    -------
    bool
        :data:`True` only if this object satisfies this hint.

    Raises
    ------
    beartype.roar.BeartypeConfException
        If this configuration is *not* a :class:`BeartypeConf` instance.
    beartype.roar.BeartypeDecorHintForwardRefException
        If this hint contains one or more relative forward references, which
        this tester explicitly prohibits to improve both the efficiency and
        portability of calls to this tester.
    beartype.roar.BeartypeDecorHintNonpepException
        If this hint is *not* PEP-compliant (i.e., complies with *no* Python
        Enhancement Proposals (PEPs) currently supported by :mod:`beartype`).
    beartype.roar.BeartypeDecorHintPepUnsupportedException
        If this hint is currently unsupported by :mod:`beartype`.

    Examples
    --------
    .. code-block:: pycon

       >>> from beartype.door import is_bearable
       >>> is_bearable(['Things', 'fall', 'apart;'], list[str])
       True
       >>> is_bearable(['the', 'centre', 'cannot', 'hold;'], list[int])
       False
    '''

    # Memoized low-level type-checking tester function returning true only if
    # the object passed to that tester satisfies the type hint passed to this
    # high-level type-checking tester function.
    #
    # Note that parameters are intentionally passed positionally for efficiency.
    # Since make_func_tester() is memoized, passing parameters by keyword would
    # raise a non-fatal
    # "_BeartypeUtilCallableCachedKwargsWarning" warning.
    func_tester = make_func_tester(hint, conf)  # pyright: ignore

    # Return true only if the passed object satisfies this hint.
    return func_tester(obj)  # pyright: ignore

# ....................{ TESTERS                            }....................
def is_subhint(subhint: Hint, superhint: Hint) -> bool:
    '''
    :data:`True` only if the first passed hint is a **subhint** of the second
    passed hint, in which case this second hint is a **superhint** of this first
    hint.

    Equivalently, this tester returns :data:`True` only if *all* of the
    following conditions apply:

    * These two hints are **semantically related** (i.e., convey broadly similar
      semantics enabling these two hints to be reasonably compared). For
      example:

      * ``callable.abc.Iterable[str]`` and ``callable.abc.Sequence[int]`` are
        semantically related. These two hints both convey container semantics.
        Despite their differing child hints, these two hints are broadly similar
        enough to be reasonably comparable.
      * ``callable.abc.Iterable[str]`` and ``callable.abc.Callable[[], int]``
        are *not* semantically related. Whereas the first hint conveys a
        container semantic, the second hint conveys a callable semantic. Since
        these two semantics are unrelated, these two hints are dissimilar
        enough to *not* be reasonably comparable.

    * The first hint is **semantically equivalent** to or **narrower** than the
      second hint. Formally:

      * The first hint matches less than or equal to the total number of all
        possible objects matched by the second hint.
      * The size of the countably infinite set of all possible objects matched
        by the first hint is less than or equal to that of those matched by the
        second hint.

    * The first hint is **compatible** with the second hint. Since the first
      hint is semantically narrower than the second, APIs annotated by the first
      hint may safely replace that hint with the second hint; doing so preserves
      backward compatibility.

    Parameters
    ----------
    subhint : Hint
        Type hint or type to be tested as the subhint.
    superhint : Hint
        Type hint or type to be tested as the superhint.

    Returns
    -------
    bool
        :data:`True` only if this first hint is a subhint of this second hint.

    Examples
    --------
    .. code-block:: pycon

       >>> from beartype.door import is_subhint
       >>> is_subhint(int, int)
       True
       >>> is_subhint(Callable[[], list], Callable[..., Sequence[Any]])
       True
       >>> is_subhint(Callable[[], list], Callable[..., Sequence[int]])
       False
    '''

    # Avoid circular import dependencies.
    from beartype.door._cls.doorsuper import TypeHint

    # The one-liner is mightier than the... many-liner.
    return TypeHint(subhint).is_subhint(TypeHint(superhint))
