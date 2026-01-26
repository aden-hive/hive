from collections.abc import Callable

from beartype import BeartypeConf, BeartypeStrategy, beartype
from typing_extensions import ParamSpec, TypeVar

no_bear_type_check_conf = BeartypeConf(strategy=BeartypeStrategy.O0)

no_bear_type = beartype(conf=no_bear_type_check_conf)

enforce_bear_type_conf = BeartypeConf(strategy=BeartypeStrategy.O1, violation_type=TypeError)
enforce_bear_type = beartype(conf=enforce_bear_type_conf)

P = ParamSpec(name="P")
R = TypeVar(name="R")


def no_bear_type_check(func: Callable[P, R]) -> Callable[P, R]:
    return no_bear_type(func)


def bear_enforce(func: Callable[P, R]) -> Callable[P, R]:
    """Enforce beartype with exceptions instead of warnings."""
    return enforce_bear_type(func)


bear_spray = no_bear_type_check
