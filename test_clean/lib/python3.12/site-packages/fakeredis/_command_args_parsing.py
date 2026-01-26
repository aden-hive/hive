from typing import Tuple, List, Dict, Any, Sequence, Optional

from . import _msgs as msgs
from ._commands import Int, Float
from ._helpers import SimpleError, null_terminate


def _count_params(s: str) -> int:
    res = 0
    while res < len(s) and s[res] in ".+*~":
        res += 1
    return res


def _encode_arg(s: str) -> bytes:
    return s[_count_params(s) :].encode()


def _default_value(s: str) -> Any:
    if s[0] == "~":
        return None
    ind = _count_params(s)
    if ind == 0:
        return False
    elif ind == 1:
        return None
    else:
        return [None] * ind


def extract_args(
    actual_args: Tuple[bytes, ...],
    expected: Tuple[str, ...],
    error_on_unexpected: bool = True,
    left_from_first_unexpected: bool = True,
    exception: Optional[str] = None,
) -> Tuple[List[Any], Sequence[Any]]:
    """Parse argument values.

    Extract from actual arguments which arguments exist and their value if relevant.

    :param actual_args: The actual arguments to parse
    :param expected: Arguments to look for, see below explanation.
    :param error_on_unexpected: Should an error be raised when actual_args contain an unexpected argument?
    :param left_from_first_unexpected: Once reaching an unexpected argument in actual_args, Should parsing stop?
    :param exception: What exception msg to raise
    :returns:
        - List of values for expected arguments.
        - List of remaining args.

    An expected argument can have parameters:
    - A numerical (Int) parameter is identified with '+'
    - A float (Float) parameter is identified with '.'
    - A non-numerical parameter is identified with a '*'
    - An argument with potentially ~ or = between the
      argument name and the value is identified with a '~'
    - A numberical argument with potentially ~ or = between the
      argument name and the value marked with a '~+'

    E.g.
    '++limit' will translate as an argument with 2 int parameters.

    >>> extract_args((b'nx', b'ex', b'324', b'xx',), ('nx', 'xx', '+ex', 'keepttl'))
    [True, True, 324, False], None

    >>> extract_args(
        (b'maxlen', b'10',b'nx', b'ex', b'324', b'xx',),
        ('~+maxlen', 'nx', 'xx', '+ex', 'keepttl'))
    10, [True, True, 324, False], None
    """
    args_info: Dict[bytes, Tuple[int, int]] = {_encode_arg(k): (i, _count_params(k)) for (i, k) in enumerate(expected)}

    def _parse_params(key: bytes, ind: int, _actual_args: Tuple[bytes, ...]) -> Tuple[Any, int]:
        """Parse an argument from actual args.
        :param key: Argument name to parse
        :param ind: index of argument in actual_args
        :param _actual_args: actual args
        """
        pos, expected_following = args_info[key]
        argument_name = expected[pos]

        # Deal with parameters with optional ~/= before numerical value.
        arg: Any
        if argument_name[0] == "~":
            if ind + 1 >= len(_actual_args):
                raise SimpleError(msgs.SYNTAX_ERROR_MSG)
            if _actual_args[ind + 1] != b"~" and _actual_args[ind + 1] != b"=":
                arg, _parsed = _actual_args[ind + 1], 1
            elif ind + 2 >= len(_actual_args):
                raise SimpleError(msgs.SYNTAX_ERROR_MSG)
            else:
                arg, _parsed = _actual_args[ind + 2], 2
            if argument_name[1] == "+":
                arg = Int.decode(arg)
            return arg, _parsed
        # Boolean parameters
        if expected_following == 0:
            return True, 0

        if ind + expected_following >= len(_actual_args):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        temp_res = []
        for i in range(expected_following):
            curr_arg: Any = _actual_args[ind + i + 1]
            if argument_name[i] == "+":
                curr_arg = Int.decode(curr_arg)
            elif argument_name[i] == ".":
                curr_arg = Float.decode(curr_arg)
            temp_res.append(curr_arg)

        if len(temp_res) == 1:
            return temp_res[0], expected_following
        else:
            return temp_res, expected_following

    results: List[Any] = [_default_value(key) for key in expected]
    left_args = []
    i = 0
    while i < len(actual_args):
        found = False
        for key in args_info:
            if null_terminate(actual_args[i]) == key:
                arg_position, _ = args_info[key]
                results[arg_position], parsed = _parse_params(key, i, actual_args)
                i += parsed
                found = True
                break

        if not found:
            if error_on_unexpected:
                raise (
                    SimpleError(msgs.SYNTAX_ERROR_MSG)
                    if exception is None
                    else SimpleError(exception.format(actual_args[i]))
                )
            if left_from_first_unexpected:
                return results, actual_args[i:]
            left_args.append(actual_args[i])
        i += 1
    return results, left_args
