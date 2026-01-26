import os

from beartype import (
    BeartypeConf,
    BeartypeStrategy,
)
from beartype.claw import beartype_this_package

disable_beartype = os.environ.get("PY_KEY_VALUE_DISABLE_BEARTYPE", "false").lower() in ("true", "1", "yes")

strategy = BeartypeStrategy.O0 if disable_beartype else BeartypeStrategy.O1

beartype_this_package(conf=BeartypeConf(violation_type=UserWarning, strategy=strategy))
