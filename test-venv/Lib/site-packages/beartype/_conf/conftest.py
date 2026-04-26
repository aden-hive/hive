#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **configuration class testers** (i.e., low-level callables testing and
validating various metadata of interest to the high-level
:class:`beartype.BeartypeConf` dataclass).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
import beartype
from beartype.roar import (
    BeartypeConfException,
    BeartypeConfParamException,
    BeartypeCallHintParamViolation,
    BeartypeCallHintReturnViolation,
    BeartypeDoorHintViolation,
)
from beartype._cave._cavemap import NoneTypeOr
from beartype._conf.confenum import (
    BeartypeStrategy,
    BeartypeViolationVerbosity,
)
from beartype._conf.decorplace.confplaceenum import BeartypeDecorPlace
from beartype._conf._confoverrides import sanify_conf_kwargs_is_pep484_tower
from beartype._data.typing.datatyping import (
    DictStrToAny,
    TypeException,
)
from beartype._util.cls.utilclstest import is_type_subclass
from beartype._util.error.utilerrwarn import issue_warning
from beartype._util.kind.maplike.utilmapfrozen import FrozenDict
from beartype._util.text.utiltextidentifier import is_identifier
from collections.abc import (
    Collection as CollectionABC,
)

# ....................{ DEFAULTERS                         }....................
def default_conf_kwargs(conf_kwargs: DictStrToAny) -> None:
    '''
    Default all parameters not explicitly passed by the user in the passed
    dictionary of configuration parameters to sane internal defaults *before*
    the :func:`.die_if_conf_kwargs_invalid` raiser validates these parameters.

    Parameters
    ----------
    conf_kwargs : Dict[str, object]
        Dictionary mapping from the names to values of *all* possible keyword
        parameters configuring this configuration.
    '''
    assert isinstance(conf_kwargs, dict), f'{repr(conf_kwargs)} not dictionary.'

    # ..................{ DEFAULT ~ violation_*type          }..................
    # Default violation type if passed *OR* "None" if unpassed.
    violation_type = conf_kwargs['violation_type']

    # If...
    if (
        # The caller explicitly passed a default violation type...
        violation_type is not None and
        # That is *NOT* an exception subclass...
        not is_type_subclass(violation_type, Exception)
    # Raise an exception.
    ):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "violation_type" value '
            f'{repr(violation_type)} not exception type.'
        )
    # Else, the caller either passed *NO* default violation type or passed a
    # valid default violation type.

    # If the caller did *NOT* explicitly pass a DOOR violation type, default
    # this type to either the default violation type if passed *OR* the default
    # DOOR violation type if unpassed.
    if conf_kwargs['violation_door_type'] is None:
        conf_kwargs['violation_door_type'] = (
            violation_type or BeartypeDoorHintViolation)
    # Else, the caller explicitly passed a DOOR violation type.

    # If the caller did *NOT* explicitly pass a parameter violation type,
    # default this type to either the default violation type if passed *OR* the
    # default DOOR violation type if unpassed.
    if conf_kwargs['violation_param_type'] is None:
        conf_kwargs['violation_param_type'] = (
            violation_type or BeartypeCallHintParamViolation)

    # If the caller did *NOT* explicitly pass a return violation type, default
    # this type to either the default violation type if passed *OR* the default
    # DOOR violation type if unpassed.
    if conf_kwargs['violation_return_type'] is None:
        conf_kwargs['violation_return_type'] = (
            violation_type or BeartypeCallHintReturnViolation)
    # Else, the caller explicitly passed a DOOR violation type.

# ....................{ RAISERS                            }....................
def die_unless_conf(
    # Mandatory parameters.
    conf: 'beartype.BeartypeConf',

    # Optional parameters.
    exception_cls: TypeException = BeartypeConfException,
) -> None:
    '''
    Raise an exception unless the passed object is a beartype configuration.

    Parameters
    ----------
    conf : beartype.BeartypeConf
        Object to be validated.
    exception_cls : Type[Exception]
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeConfException`.

    Raises
    ------
    exception_cls
        If this object is *not* a beartype configuration.
    '''

    # Avoid circular import dependencies.
    from beartype._conf.confmain import BeartypeConf

    # If this object is *NOT* a configuration, raise an exception.
    if not isinstance(conf, BeartypeConf):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not exception type.')

        raise exception_cls(
            f'Beartype configuration {repr(conf)} invalid '
            f'(i.e., not "beartype.BeartypeConf" instance).'
        )
    # Else, this object is a configuration.


def die_if_conf_kwargs_invalid(conf_kwargs: DictStrToAny) -> None:
    '''
    Raise an exception if one or more configuration parameters in the passed
    dictionary of such parameters are invalid.

    Parameters
    ----------
    conf_kwargs : Dict[str, object]
        Dictionary mapping from the names to values of *all* possible keyword
        parameters configuring this configuration.

    Raises
    ------
    BeartypeConfParamException
        If one or more configurations parameter in this dictionary are invalid.
    '''

    # ..................{ VALIDATE                           }..................
    # If "claw_decor_place_func" is *NOT* an enumeration member, raise
    # an exception.
    if not isinstance(
        conf_kwargs['claw_decor_place_func'],
        BeartypeDecorPlace
    ):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "claw_decor_place_func" '
            f'value {repr(conf_kwargs["claw_decor_place_func"])} not '
            f'"beartype.BeartypeDecorPlace" enumeration member.'
        )
    # Else, "claw_decor_place_func" is an enumeration member.
    #
    # If "claw_decor_place_type" is *NOT* an enumeration member, raise
    # an exception.
    elif not isinstance(
        conf_kwargs['claw_decor_place_type'],
        BeartypeDecorPlace
    ):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "claw_decor_place_type" '
            f'value {repr(conf_kwargs["claw_decor_place_type"])} not '
            f'"beartype.BeartypeDecorPlace" enumeration member.'
        )
    # Else, "claw_decor_place_type" is an enumeration member.
    #
    # If "claw_is_pep526" is *NOT* a boolean, raise an exception.
    elif not isinstance(conf_kwargs['claw_is_pep526'], bool):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "claw_is_pep526" '
            f'value {repr(conf_kwargs["claw_is_pep526"])} not boolean.'
        )
    # Else, "claw_is_pep526" is a boolean.
    #
    # If "claw_skip_package_names" is *NOT* an iterable of non-empty strings,
    # raise an exception. Specifically, if the value of this parameter is not...
    elif not (
        # A collection *AND*...
        isinstance(conf_kwargs['claw_skip_package_names'], CollectionABC) and
        all(
            (
                # This item is a string *AND*...
                isinstance(claw_skip_package_name, str) and
                # This string is a "."-delimited Python identifier...
                is_identifier(claw_skip_package_name)
            )
            # For each item of this iterable.
            for claw_skip_package_name in conf_kwargs['claw_skip_package_names']
        )
    ):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "claw_skip_package_names" '
            f'value {repr(conf_kwargs["claw_skip_package_names"])} not '
            f'collection of "."-delimited Python identifiers.'
        )
    # Else, "claw_skip_package_names" is an iterable of non-empty strings.
    #
    # If "hint_overrides" is *NOT* a frozen dict, raise an exception.
    elif not isinstance(conf_kwargs['hint_overrides'], FrozenDict):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "hint_overrides" '
            f'value {repr(conf_kwargs["hint_overrides"])} not '
            f'frozen dictionary '
            f'(i.e., "beartype.FrozenDict" instance).'
        )
    # Else, "hint_overrides" is a frozen dict.
    #
    # If "is_pep557_fields" is *NOT* a boolean, raise an exception.
    elif not isinstance(conf_kwargs['is_pep557_fields'], bool):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "is_pep557_fields" '
            f'value {repr(conf_kwargs["is_pep557_fields"])} not boolean.'
        )
    # Else, "is_pep557_fields" is a boolean.
    #
    # If "is_color" is *NOT* a tri-state boolean, raise an exception.
    elif not isinstance(conf_kwargs['is_color'], NoneTypeOr[bool]):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "is_color" '
            f'value {repr(conf_kwargs["is_color"])} not tri-state boolean '
            f'(i.e., "True", "False", or "None").'
        )
    # Else, "is_color" is a tri-state boolean.
    #
    # If "is_debug" is *NOT* a boolean, raise an exception.
    elif not isinstance(conf_kwargs['is_debug'], bool):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "is_debug" '
            f'value {repr(conf_kwargs["is_debug"])} not boolean.'
        )
    # Else, "is_debug" is a boolean.
    #
    # If "is_pep484_tower" is *NOT* a boolean, raise an exception.
    elif not isinstance(conf_kwargs['is_pep484_tower'], bool):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "is_pep484_tower" '
            f'value {repr(conf_kwargs["is_debug"])} not boolean.'
        )
    # Else, "is_pep484_tower" is a boolean.
    #
    # If "strategy" is *NOT* an enumeration member, raise an exception.
    elif not isinstance(conf_kwargs['strategy'], BeartypeStrategy):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "strategy" '
            f'value {repr(conf_kwargs["strategy"])} not '
            f'"beartype.BeartypeStrategy" enumeration member.'
        )
    # Else, "strategy" is an enumeration member.
    #
    # If "violation_verbosity" is *NOT* an enumeration member, raise an
    # exception.
    elif not isinstance(
        conf_kwargs['violation_verbosity'], BeartypeViolationVerbosity):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter "violation_verbosity" '
            f'value {repr(conf_kwargs["violation_verbosity"])} not '
            f'"beartype.BeartypeViolationVerbosity" enumeration member.'
        )
    # Else, "violation_verbosity" is an enumeration member.
    #
    # If "warning_cls_on_decorator_exception" is neither "None" *NOR* a
    # warning category, raise an exception.
    elif not (
        conf_kwargs['warning_cls_on_decorator_exception'] is None or
        is_type_subclass(
            conf_kwargs['warning_cls_on_decorator_exception'], Warning)
    ):
        raise BeartypeConfParamException(
            f'Beartype configuration parameter '
            f'"warning_cls_on_decorator_exception" value '
            f'{repr(conf_kwargs["warning_cls_on_decorator_exception"])} '
            f'neither "None" nor warning category '
            f'(i.e., "Warning" subclass).'
        )
    # Else, "warning_cls_on_decorator_exception" is either "None" *OR* a
    # warning category.

    # For the name of each keyword parameter whose value is expected to be an
    # exception subclass...
    for arg_name_exception_subclass in _ARG_NAMES_EXCEPTION_SUBCLASS:
        # If the value of this keyword parameter is *NOT* an exception subclass,
        # raise an exception.
        if not is_type_subclass(
            conf_kwargs[arg_name_exception_subclass], Exception):
            raise BeartypeConfParamException(
                f'Beartype configuration parameter '
                f'"{arg_name_exception_subclass}" value '
                f'{repr(conf_kwargs[arg_name_exception_subclass])} not '
                f'exception type.'
            )

# ....................{ DEPRECATORS                        }....................
def issue_warning_deprecated_option(
    option_name_old: str, option_name_new: str) -> None:
    '''
    Issue a non-fatal deprecation warning advising the caller that the parameter
    with the passed "old" name has been deprecated in favour of the parameter
    with the passed "new" name.

    Parameters
    ----------
    option_name_old : str
        Name of the deprecated "old" configuration option passed by the caller.
    option_name_new : str
        Name of the corresponding non-deprecated "new" configuration option
        *not* passed by the caller.
    '''
    assert isinstance(option_name_old, str)
    assert isinstance(option_name_new, str)

    # Issue this non-fatal deprecation warning.
    issue_warning(
        cls=DeprecationWarning,
        message=(
            f'Beartype configuration option "{option_name_old}" '
            f'deprecated by new option "{option_name_new}", '
            f'because beartype is here to annoy you when you were '
            f'just about to go home.\n'
            f'tl;dr: pass "{option_name_new}" instead, please. *sigh*'
        ),
    )

# ....................{ SANIFIERS                          }....................
def sanify_conf_kwargs(conf_kwargs: DictStrToAny) -> None:
    '''
    Sanify (i.e., sanitize) the passed dictionary of configuration parameters
    *after* the :func:`.die_if_conf_kwargs_invalid` raiser validates these
    parameters.

    Parameters
    ----------
    conf_kwargs : Dict[str, object]
        Dictionary mapping from the names to values of *all* possible keyword
        parameters configuring this configuration.
    '''
    assert isinstance(conf_kwargs, dict), f'{repr(conf_kwargs)} not dictionary.'

    # ..................{ DEFAULT ~ hint_overrides           }..................
    # If enabling the PEP 484-compliant implicit numeric tower, dynamically
    # synthesize this tower from this existing configuration.
    if conf_kwargs['is_pep484_tower']:
        sanify_conf_kwargs_is_pep484_tower(conf_kwargs)
    # Else, the PEP 484-compliant implicit numeric tower is disabled.

# ....................{ PRIVATE ~ globals                  }....................
_ARG_NAMES_EXCEPTION_SUBCLASS = (
    'violation_door_type',
    'violation_param_type',
    'violation_return_type',
)
'''
Tuple of the names of all keyword parameters to the
:meth:`beartype.BeartypeConf.__new__` dunder method whose values are expected to
be exception subclasses.
'''
