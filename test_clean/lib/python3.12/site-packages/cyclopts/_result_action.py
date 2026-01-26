import sys
from collections.abc import Callable, Iterable
from typing import Any, Literal, cast

from cyclopts.utils import is_iterable

ResultActionSingle = (
    Literal[
        "return_value",
        "call_if_callable",
        "print_non_int_return_int_as_exit_code",
        "print_str_return_int_as_exit_code",
        "print_str_return_zero",
        "print_non_none_return_int_as_exit_code",
        "print_non_none_return_zero",
        "return_int_as_exit_code_else_zero",
        "print_non_int_sys_exit",
        "sys_exit",
        "return_none",
        "return_zero",
        "print_return_zero",
        "sys_exit_zero",
        "print_sys_exit_zero",
    ]
    | Callable[[Any], Any]
)

ResultAction = ResultActionSingle | Iterable[ResultActionSingle]


def handle_result_action(
    result: Any,
    action: ResultAction,
    print_fn: Callable[[Any], None],
) -> Any:
    """Handle command result based on result_action.

    When ``action`` is a sequence, actions are applied left-to-right in a pipeline,
    where each action receives the result of the previous action. For example,
    with ``result_action=[uppercase, add_greeting]``:

        result → uppercase(result) → add_greeting(uppercase(result))

    Parameters
    ----------
    result : Any
        The command's return value.
    action : ResultAction
        The action (or sequence of actions) to take with the result.
        If a sequence, actions are chained left-to-right.
    print_fn : Callable[[Any], None]
        Function to call to print output (e.g., console.print).

    Returns
    -------
    Any
        Processed result based on action (may call sys.exit() and not return).
    """
    if is_iterable(action):
        for single_action in cast(Iterable[ResultActionSingle], action):
            result = handle_result_action(result, single_action, print_fn)
        return result

    if callable(action):
        return action(result)

    match action:
        case "print_non_int_sys_exit":
            if isinstance(result, bool):
                sys.exit(0 if result else 1)
            elif isinstance(result, int):
                sys.exit(result)
            elif result is not None:
                print_fn(result)
                sys.exit(0)
            else:
                sys.exit(0)
        case "return_value":
            return result
        case "call_if_callable":
            if callable(result):
                return result()
            return result
        case "sys_exit":
            if isinstance(result, bool):
                sys.exit(0 if result else 1)
            elif isinstance(result, int):
                sys.exit(result)
            else:
                sys.exit(0)
        case "print_non_int_return_int_as_exit_code":
            if isinstance(result, bool):
                return 0 if result else 1
            elif isinstance(result, int):
                return result
            elif result is not None:
                print_fn(result)
                return 0
            else:
                return 0
        case "print_str_return_int_as_exit_code":
            if isinstance(result, str):
                print_fn(result)
                return 0
            elif isinstance(result, bool):
                return 0 if result else 1
            elif isinstance(result, int):
                return result
            else:
                return 0
        case "print_str_return_zero":
            if isinstance(result, str):
                print_fn(result)
            return 0
        case "print_non_none_return_int_as_exit_code":
            if result is not None:
                print_fn(result)
            if isinstance(result, bool):
                return 0 if result else 1
            elif isinstance(result, int):
                return result
            return 0
        case "print_non_none_return_zero":
            if result is not None:
                print_fn(result)
            return 0
        case "return_int_as_exit_code_else_zero":
            if isinstance(result, bool):
                return 0 if result else 1
            elif isinstance(result, int):
                return result
            else:
                return 0
        case "return_none":
            return None
        case "return_zero":
            return 0
        case "print_return_zero":
            print_fn(result)
            return 0
        case "sys_exit_zero":
            sys.exit(0)
        case "print_sys_exit_zero":
            print_fn(result)
            sys.exit(0)
        case _:
            raise ValueError
