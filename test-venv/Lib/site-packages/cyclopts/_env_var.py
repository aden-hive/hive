import os
from pathlib import Path
from typing import Any, get_args

from cyclopts._convert import resolve, token_count


def _is_path(type_) -> bool:
    if type_ is Path:
        return True

    for inner_type in get_args(type_):
        inner_type = resolve(inner_type)
        if _is_path(inner_type):
            return True

    return False


def env_var_split(
    type_: Any,
    val: str,
    *,
    delimiter: str | None = None,
) -> list[str]:
    """Type-dependent environment variable value splitting.

    Converts a single string into a list of strings. Splits when:

    * The ``type_`` is some variant of ``Iterable[pathlib.Path]`` objects.
      If Windows, split on ``;``, otherwise split on ``:``.

    * Otherwise, if the ``type_`` is an ``Iterable``, split on whitespace.
      Leading/trailing whitespace of each output element will be stripped.

    This function is the default value for :attr:`cyclopts.App.env_var_split`.

    Parameters
    ----------
    type_: type
        Type hint that we will eventually coerce into.
    val: str
        String to split.
    delimiter: str | None
        Delimiter to split ``val`` on.
        If None, defaults to whitespace.

    Returns
    -------
    list[str]
        List of individual string tokens.
    """
    type_ = resolve(type_)
    count, consume_all = token_count(type_)

    if count > 1 or consume_all:
        return val.split(os.pathsep) if _is_path(type_) else val.split(delimiter)
    else:
        return [val]
