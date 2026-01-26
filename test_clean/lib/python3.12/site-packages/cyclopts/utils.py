"""To prevent circular dependencies, this module should never import anything else from Cyclopts."""

import functools
import importlib
import inspect
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import suppress
from operator import itemgetter
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from attrs import field, frozen

T = TypeVar("T")

# https://threeofwands.com/attra-iv-zero-overhead-frozen-attrs-classes/
if TYPE_CHECKING:
    from json import JSONDecodeError

    from attrs import frozen
    from rich.console import Console
else:
    from attrs import define

    frozen = functools.partial(define, unsafe_hash=True)

from sys import stdlib_module_names


class SentinelMeta(type):
    def __repr__(cls) -> str:
        return f"<{cls.__name__}>"

    def __bool__(cls) -> Literal[False]:
        return False


class Sentinel(metaclass=SentinelMeta):
    def __new__(cls):
        raise ValueError("Sentinel objects are not intended to be instantiated. Subclass instead.")


class UNSET(Sentinel):
    """Special sentinel value indicating that no data was provided. **Do not instantiate**."""


def record_init(target: str) -> Callable[[type[T]], type[T]]:
    """Class decorator that records init argument names as a tuple to ``target``."""

    def decorator(cls: type[T]) -> type[T]:
        original_init = cls.__init__
        function_signature = inspect.signature(original_init)
        param_names = tuple(name for name in function_signature.parameters if name != "self")

        @functools.wraps(original_init)
        def new_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            # Circumvent frozen protection.
            object.__setattr__(self, target, tuple(param_names[i] for i in range(len(args))) + tuple(kwargs))

        cls.__init__ = new_init
        return cls

    return decorator


def is_iterable(obj) -> bool:
    if isinstance(obj, list | tuple | set | dict):  # Fast path for common types
        return True
    return not isinstance(obj, str) and isinstance(obj, Iterable)


def is_class_and_subclass(hint, target_class) -> bool:
    """Safely check if a type is both a class and a subclass of target_class.

    Parameters
    ----------
    hint : Any
        The type to check.
    target_class : type
        The target class to check subclass relationship against.

    Returns
    -------
    bool
        True if hint is a class and is a subclass of target_class, False otherwise.
    """
    try:
        return inspect.isclass(hint) and issubclass(hint, target_class)
    except TypeError:
        # issubclass() raises TypeError for non-class arguments like Union types
        return False


def to_tuple_converter(value: None | Any | Iterable[Any]) -> tuple[Any, ...]:
    """Convert a single element or an iterable of elements into a tuple.

    Intended to be used in an ``attrs.Field``. If :obj:`None` is provided, returns an empty tuple.
    If a single element is provided, returns a tuple containing just that element.
    If an iterable is provided, converts it into a tuple.

    Parameters
    ----------
    value: Any | Iterable[Any] | None
        An element, an iterable of elements, or None.

    Returns
    -------
    tuple[Any, ...]: A tuple containing the elements.
    """
    if value is None:
        return ()
    elif is_iterable(value):
        return tuple(value)
    else:
        return (value,)


def to_list_converter(value: None | Any | Iterable[Any]) -> list[Any]:
    return list(to_tuple_converter(value))


def optional_to_tuple_converter(value: None | Any | Iterable[Any]) -> tuple[Any, ...] | None:
    """Convert a string or Iterable or None into an Iterable or None.

    Intended to be used in an ``attrs.Field``.
    """
    if value is None:
        return None

    if not value:
        return ()

    return to_tuple_converter(value)


def sort_key_converter(value: Any) -> Any:
    """Convert sort_key value, consuming generators with :func:`next`.

    Parameters
    ----------
    value : Any
        The sort_key value to convert. Can be None, a generator, or any other value.

    Returns
    -------
    Any
        UNSET if value is None, ``next(value)`` if generator, otherwise value unchanged.
    """
    if value is None:
        return UNSET
    elif inspect.isgenerator(value):
        return next(value)
    else:
        return value


def help_formatter_converter(
    input_value: None | Literal["default", "plain"] | Any,
) -> Any | None:
    """Convert string literals to help formatter instances.

    Parameters
    ----------
    input_value : None | Literal["default", "plain"] | Any
        The input value to convert. Can be None, "default", "plain", or a formatter instance.

    Returns
    -------
    Any | None
        None, or a HelpFormatter instance.

    Notes
    -----
    Lazily imports formatters to avoid importing Rich during normal execution.
    """
    if input_value is None:
        return None
    elif isinstance(input_value, str):
        if input_value == "default":
            from cyclopts.help.formatters import DefaultFormatter

            return DefaultFormatter()
        elif input_value == "plain":
            from cyclopts.help.formatters import PlainFormatter

            return PlainFormatter()
        else:
            raise ValueError(f"Unknown formatter: {input_value!r}. Must be 'default' or 'plain'")
    else:
        # Assume it's already a HelpFormatter instance
        return input_value


def _pascal_to_snake(s: str) -> str:
    # (Borrowed from pydantic)
    # Handle the sequence of uppercase letters followed by a lowercase letter
    snake = re.sub(r"([A-Z]+)([A-Z][a-z])", lambda m: f"{m.group(1)}_{m.group(2)}", s)
    # Insert an underscore between a lowercase letter and an uppercase letter
    snake = re.sub(r"([a-z])([A-Z])", lambda m: f"{m.group(1)}_{m.group(2)}", snake)
    # Insert an underscore between a digit and an uppercase letter
    snake = re.sub(r"([0-9])([A-Z])", lambda m: f"{m.group(1)}_{m.group(2)}", snake)
    return snake.lower()


def default_name_transform(s: str) -> str:
    """Converts a python identifier into a CLI token.

    Performs the following operations (in order):

    1. Convert PascalCase to snake_case.
    2. Convert the string to all lowercase.
    3. Replace ``_`` with ``-``.
    4. Strip any leading/trailing ``-`` (also stripping ``_``, due to point 3).

    Intended to be used with :attr:`App.name_transform` and :attr:`Parameter.name_transform`.

    Parameters
    ----------
    s: str
        Input python identifier string.

    Returns
    -------
    str
        Transformed name.
    """
    return _pascal_to_snake(s).lower().replace("_", "-").strip("-")


def grouper(iterable: Sequence[Any], n: int) -> Iterator[tuple[Any, ...]]:
    """Collect data into non-overlapping fixed-length chunks or blocks.

    https://docs.python.org/3/library/itertools.html#itertools-recipes

    Parameters
    ----------
    iterable: Sequence[Any]
        Some iterable sequence to group.
    n: int
        Number of elements to put in each group.
    """
    if len(iterable) % n:
        raise ValueError(f"{iterable!r} is not divisible by {n}.")
    iterators = [iter(iterable)] * n
    return zip(*iterators, strict=False)


def is_option_like(token: str, *, allow_numbers=False) -> bool:
    """Checks if a token looks like an option.

    Namely, negative numbers are not options, but a token like ``--foo`` is.

    Parameters
    ----------
    token: str
        String to interpret.
    allow_numbers: bool
        If :obj:`True`, then negative numbers (e.g. ``"-2"``) will return :obj:`True`.
        Otherwise, numbers will be interpreted as non-option-like (:obj:`False`).
        Note: ``-j`` **is option-like**, even though it can represent an imaginary number.

    Returns
    -------
    bool
        Whether or not the ``token`` is option-like.
    """
    if not allow_numbers:
        with suppress(ValueError):
            complex(token)
            if token.lower() == "-j":
                # ``complex("-j")`` is a valid imaginary number, but more than likely
                # the caller meant it as a short flag.
                # https://github.com/BrianPugh/cyclopts/issues/328
                return True
            return False
    return token.startswith("-")


def is_builtin(obj: Any) -> bool:
    return getattr(obj, "__module__", "").split(".")[0] in stdlib_module_names


def resolve_callables(t, *args, **kwargs):
    """Recursively resolves callable elements in a tuple.

    Returns an object that "looks like" the input, but with all callable's invoked
    and replaced with their return values. Positional and keyword elements will be
    passed along to each invocation.
    """
    if isinstance(t, type(Sentinel)):
        return t

    if callable(t):
        return t(*args, **kwargs)
    elif is_iterable(t):
        resolved = []
        for element in t:
            if isinstance(element, type(Sentinel)):
                resolved.append(element)
            elif callable(element):
                resolved.append(element(*args, **kwargs))
            elif is_iterable(element):
                resolved.append(resolve_callables(element, *args, **kwargs))
            else:
                resolved.append(element)
        return tuple(resolved)
    else:
        return t


@frozen
class SortHelper:
    """Sort a list of objects by an external key and retrieve the objects in-order."""

    key: Any
    """Primary key to sort by.

    SortHelpers with ``key`` :obj:`None` or :obj:`.UNSET` go last (alphabetically).
    """

    fallback_key: Any = field(converter=to_tuple_converter)
    """Secondary key to sort by.
    """

    value: Any
    """Actual object that caller wants to retrieve in the sorted order."""

    @staticmethod
    def sort(entries: Sequence["SortHelper"]) -> list["SortHelper"]:
        """Sorts a sequence of :class:`SortHelper`."""
        from cyclopts.group import (
            DEFAULT_ARGUMENTS_GROUP_SORT_MARKER,
            DEFAULT_COMMANDS_GROUP_SORT_MARKER,
            DEFAULT_PARAMETERS_GROUP_SORT_MARKER,
        )

        default_commands_group = []
        default_arguments_group = []
        default_parameters_group = []

        user_sort_key = []
        ordered_no_user_sort_key = []
        no_user_sort_key = []

        for entry in entries:
            if entry.key is DEFAULT_COMMANDS_GROUP_SORT_MARKER:
                default_commands_group.append((None, entry))
            elif entry.key is DEFAULT_ARGUMENTS_GROUP_SORT_MARKER:
                default_arguments_group.append((None, entry))
            elif entry.key is DEFAULT_PARAMETERS_GROUP_SORT_MARKER:
                default_parameters_group.append((None, entry))
            elif entry.key in (UNSET, None):
                no_user_sort_key.append((entry.fallback_key, entry))
            elif is_iterable(entry.key) and entry.key[0] in (UNSET, None):
                # Items that are ordered internal to Cyclopts, but have lower order than user-provided sort_keys.
                # Primarily to handle :meth:`Group.create_ordered`.
                ordered_no_user_sort_key.append((entry.key[1:] + entry.fallback_key, entry))
            else:
                user_sort_key.append(((entry.key, entry.fallback_key), entry))

        user_sort_key.sort(key=itemgetter(0))
        ordered_no_user_sort_key.sort(key=itemgetter(0))
        no_user_sort_key.sort(key=itemgetter(0))

        combined = (
            default_commands_group
            + default_arguments_group
            + default_parameters_group
            + user_sort_key
            + ordered_no_user_sort_key
            + no_user_sort_key
        )
        return [x[1] for x in combined]


def json_decode_error_verbosifier(decode_error: "JSONDecodeError", context: int = 20) -> str:
    """Not intended to be a super robust implementation, but robust enough to be helpful.

    Parameters
    ----------
    context: int
        Number of surrounding-character context
    """
    lines = decode_error.doc.splitlines()
    line = lines[decode_error.lineno - 1]

    error_index = decode_error.colno - 1  # colno is 1-indexed
    start = error_index - context
    if start <= 0:
        start = 0
        prefix_ellipsis = ""
        segment_error_index = error_index
    else:
        prefix_ellipsis = "... "
        segment_error_index = error_index - start

    end = error_index + context
    if end >= len(line):
        end = len(line) + 1
        suffix_ellipsis = ""
    else:
        suffix_ellipsis = " ..."

    segment = line[start:end]
    carat_pointer = " " * (len(prefix_ellipsis) + segment_error_index) + "^"

    response = (
        f"JSONDecodeError:\n    {prefix_ellipsis}{segment}{suffix_ellipsis}\n    {carat_pointer}\n{str(decode_error)}"
    )
    return response


def create_error_console_from_console(console: "Console") -> "Console":
    """Create an error console (stderr=True) that inherits settings from a source console.

    Parameters
    ----------
    console : Console
        Source Rich Console to copy settings from.

    Returns
    -------
    Console
        New Rich Console with stderr=True and inherited settings.
    """
    from rich.console import Console

    color_system = console.color_system or "auto"

    return Console(
        stderr=True,
        color_system=color_system,  # type: ignore[arg-type]
        force_terminal=getattr(console, "_force_terminal", None),
        force_jupyter=console.is_jupyter or None,
        force_interactive=console.is_interactive or None,
        soft_wrap=console.soft_wrap,
        width=console._width,
        height=getattr(console, "_height", None),
        tab_size=console.tab_size,
        markup=getattr(console, "_markup", True),
        emoji=getattr(console, "_emoji", True),
        emoji_variant=getattr(console, "_emoji_variant", None),
        highlight=getattr(console, "_highlight", True),
        no_color=console.no_color,
        legacy_windows=console.legacy_windows,
        safe_box=console.safe_box,
        _environ=getattr(console, "_environ", None),
        get_datetime=getattr(console, "get_datetime", None),
        get_time=getattr(console, "get_time", None),
    )


def import_app(module_path: str):
    """Import a Cyclopts App from a module path.

    Parameters
    ----------
    module_path : str
        Module path in format "module.name" or "module.name:app_name".
        If ":app_name" is omitted, auto-discovers by searching for common
        names (app, cli, main) or any public App instance.

    Returns
    -------
    App
        The imported Cyclopts App instance.

    Raises
    ------
    ImportError
        If the module cannot be imported.
    AttributeError
        If the specified app name doesn't exist or no App is found.
    TypeError
        If the specified attribute is not a Cyclopts App instance.
    """
    from cyclopts import App

    if ":" in module_path:
        module_name, app_name = module_path.rsplit(":", 1)
    else:
        module_name, app_name = module_path, None

    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ImportError(f"Cannot import module '{module_name}': {e}") from e

    if app_name:
        if not hasattr(module, app_name):
            raise AttributeError(f"Module '{module_name}' has no attribute '{app_name}'")
        app = getattr(module, app_name)
        if not isinstance(app, App):
            raise TypeError(f"'{app_name}' is not a Cyclopts App instance")
        return app

    # Auto-discovery: search for App instance
    for name in ["app", "cli", "main"]:
        obj = getattr(module, name, None)
        if isinstance(obj, App):
            return obj

    # Search all public attributes
    for name in dir(module):
        if not name.startswith("_"):
            obj = getattr(module, name)
            if isinstance(obj, App):
                return obj

    raise AttributeError(f"No Cyclopts App found in '{module_name}'. Specify explicitly: '{module_name}:app_name'")
