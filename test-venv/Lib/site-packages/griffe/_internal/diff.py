# This module exports "breaking changes" related utilities.
# The logic here is to iterate on objects and their members recursively,
# to yield found breaking changes.
#
# The breakage class definitions might sound a bit verbose,
# but declaring them this way helps with (de)serialization,
# which we don't use yet, but could use in the future.

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from griffe._internal.enumerations import BreakageKind, ExplanationStyle, ParameterKind
from griffe._internal.exceptions import AliasResolutionError
from griffe._internal.git import _WORKTREE_PREFIX
from griffe._internal.logger import logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from griffe._internal.models import Alias, Attribute, Class, Function, Object

_POSITIONAL = frozenset((ParameterKind.positional_only, ParameterKind.positional_or_keyword))
_KEYWORD = frozenset((ParameterKind.keyword_only, ParameterKind.positional_or_keyword))
_POSITIONAL_KEYWORD_ONLY = frozenset((ParameterKind.positional_only, ParameterKind.keyword_only))
_VARIADIC = frozenset((ParameterKind.var_positional, ParameterKind.var_keyword))


# Colors for terminal output.
class _ANSI:
    FG_BLACK = "\033[30m"
    FG_RED = "\033[31m"
    FG_GREEN = "\033[32m"
    FG_YELLOW = "\033[33m"
    FG_BLUE = "\033[34m"
    FG_MAGENTA = "\033[35m"
    FG_CYAN = "\033[36m"
    FG_WHITE = "\033[37m"
    FG_RESET = "\033[39m"
    FG_LIGHTBLACK_EX = "\033[90m"
    FG_LIGHTRED_EX = "\033[91m"
    FG_LIGHTGREEN_EX = "\033[92m"
    FG_LIGHTYELLOW_EX = "\033[93m"
    FG_LIGHTBLUE_EX = "\033[94m"
    FG_LIGHTMAGENTA_EX = "\033[95m"
    FG_LIGHTCYAN_EX = "\033[96m"
    FG_LIGHTWHITE_EX = "\033[97m"
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"
    BG_RESET = "\033[49m"
    BG_LIGHTBLACK_EX = "\033[100m"
    BG_LIGHTRED_EX = "\033[101m"
    BG_LIGHTGREEN_EX = "\033[102m"
    BG_LIGHTYELLOW_EX = "\033[103m"
    BG_LIGHTBLUE_EX = "\033[104m"
    BG_LIGHTMAGENTA_EX = "\033[105m"
    BG_LIGHTCYAN_EX = "\033[106m"
    BG_LIGHTWHITE_EX = "\033[107m"
    BRIGHT = "\033[1m"
    DIM = "\033[2m"
    NORMAL = "\033[22m"
    RESET_ALL = "\033[0m"


class Breakage:
    """Breakages can explain what broke from a version to another."""

    kind: BreakageKind
    """The kind of breakage."""

    def __init__(self, obj: Object, old_value: Any, new_value: Any, details: str = "") -> None:
        """Initialize the breakage.

        Parameters:
            obj: The object related to the breakage.
            old_value: The old value.
            new_value: The new, incompatible value.
            details: Some details about the breakage.
        """
        self.obj = obj
        """The object related to the breakage."""
        self.old_value = old_value
        """The old value."""
        self.new_value = new_value
        """The new, incompatible value."""
        self.details = details
        """Some details about the breakage."""

    def __str__(self) -> str:
        return self.kind.value

    def __repr__(self) -> str:
        return self.kind.name

    def as_dict(self, *, full: bool = False, **kwargs: Any) -> dict[str, Any]:  # noqa: ARG002
        """Return this object's data as a dictionary.

        Parameters:
            full: Whether to return full info, or just base info.
            **kwargs: Additional serialization options.

        Returns:
            A dictionary.
        """
        return {
            "kind": self.kind,
            "object_path": self.obj.path,
            "old_value": self.old_value,
            "new_value": self.new_value,
        }

    def explain(self, style: ExplanationStyle = ExplanationStyle.ONE_LINE) -> str:
        """Explain the breakage by showing old and new value.

        Parameters:
            style: The explanation style to use.

        Returns:
            An explanation.
        """
        return getattr(self, f"_explain_{style.value}")()

    @property
    def _filepath(self) -> Path:
        if self.obj.is_alias:
            return self.obj.parent.filepath  # ty:ignore[invalid-return-type, unresolved-attribute]
        return self.obj.filepath  # ty:ignore[invalid-return-type]

    @property
    def _relative_filepath(self) -> Path:
        if self.obj.is_alias:
            return self.obj.parent.relative_filepath  # ty:ignore[unresolved-attribute]
        return self.obj.relative_filepath

    @property
    def _relative_package_filepath(self) -> Path:
        if self.obj.is_alias:
            return self.obj.parent.relative_package_filepath  # ty:ignore[unresolved-attribute]
        return self.obj.relative_package_filepath

    @property
    def _location(self) -> Path:
        # Absolute file path probably means temporary worktree.
        # We use our worktree prefix to remove some components
        # of the path on the left (`/tmp/griffe-worktree-*/griffe_*/repo`).
        if self._relative_filepath.is_absolute():
            parts = self._relative_filepath.parts
            for index, part in enumerate(parts):
                if part.startswith(_WORKTREE_PREFIX):
                    return Path(*parts[index + 2 :])
        return self._relative_filepath

    @property
    def _canonical_path(self) -> str:
        if self.obj.is_alias:
            return self.obj.path
        return self.obj.canonical_path

    @property
    def _module_path(self) -> str:
        if self.obj.is_alias:
            return self.obj.parent.module.path  # ty:ignore[unresolved-attribute]
        return self.obj.module.path

    @property
    def _relative_path(self) -> str:
        return self._canonical_path[len(self._module_path) + 1 :] or "<module>"

    @property
    def _lineno(self) -> int:
        # If the object was removed, and we are able to get the location (file path)
        # as a relative path, then we use 0 instead of the original line number
        # (it helps when checking current sources, and avoids pointing to now missing contents).
        if self.kind is BreakageKind.OBJECT_REMOVED and self._relative_filepath != self._location:
            return 0
        if self.obj.is_alias:
            return self.obj.alias_lineno or 0  # ty:ignore[unresolved-attribute]
        return self.obj.lineno or 0

    def _format_location(self, *, colors: bool = True) -> str:
        bright = _ANSI.BRIGHT if colors else ""
        reset = _ANSI.RESET_ALL if colors else ""
        return f"{bright}{self._location}{reset}:{self._lineno}"

    def _format_title(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return self._relative_path

    def _format_kind(self, *, colors: bool = True) -> str:
        yellow = _ANSI.FG_YELLOW if colors else ""
        reset = _ANSI.FG_RESET if colors else ""
        return f"{yellow}{self.kind.value}{reset}"

    def _format_old_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return str(self.old_value)

    def _format_new_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return str(self.new_value)

    def _explain_oneline(self) -> str:
        explanation = f"{self._format_location()}: {self._format_title()}: {self._format_kind()}"
        old = self._format_old_value()
        new = self._format_new_value()
        if old and new:
            change = f"{old} -> {new}"
        elif old:
            change = old
        elif new:
            change = new
        else:
            change = ""
        if change:
            return f"{explanation}: {change}"
        return explanation

    def _explain_verbose(self) -> str:
        lines = [f"{self._format_location()}: {self._format_title()}:"]
        kind = self._format_kind()
        old = self._format_old_value()
        new = self._format_new_value()
        if old or new:
            lines.append(f"{kind}:")
        else:
            lines.append(kind)
        if old:
            lines.append(f"  Old: {old}")
        if new:
            lines.append(f"  New: {new}")
        if self.details:
            lines.append(f"  Details: {self.details}")
        lines.append("")
        return "\n".join(lines)

    def _explain_markdown(self) -> str:
        explanation = f"- `{self._relative_path}`: *{self.kind.value}*"
        old = self._format_old_value(colors=False)
        if old and old != "unset":
            old = f"`{old}`"
        new = self._format_new_value(colors=False)
        if new and new != "unset":
            new = f"`{new}`"
        if old and new:
            change = f"{old} -> {new}"
        elif old:
            change = old
        elif new:
            change = new
        else:
            change = ""
        if change:
            return f"{explanation}: {change}"
        return explanation

    def _explain_github(self) -> str:
        location = f"file={self._location},line={self._lineno}"
        title = f"title={self._format_title(colors=False)}"
        explanation = f"::warning {location},{title}::{self.kind.value}"
        old = self._format_old_value(colors=False)
        if old and old != "unset":
            old = f"`{old}`"
        new = self._format_new_value(colors=False)
        if new and new != "unset":
            new = f"`{new}`"
        if old and new:
            change = f"{old} -> {new}"
        elif old:
            change = old
        elif new:
            change = new
        else:
            change = ""
        if change:
            return f"{explanation}: {change}"
        return explanation


class ParameterMovedBreakage(Breakage):
    """Specific breakage class for moved parameters."""

    kind: BreakageKind = BreakageKind.PARAMETER_MOVED

    @property
    def _relative_path(self) -> str:
        return f"{super()._relative_path}({self.old_value.name})"

    def _format_title(self, *, colors: bool = True) -> str:
        blue = _ANSI.FG_BLUE if colors else ""
        reset = _ANSI.FG_RESET if colors else ""
        return f"{super()._relative_path}({blue}{self.old_value.name}{reset})"

    def _format_old_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return ""

    def _format_new_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return ""


class ParameterRemovedBreakage(Breakage):
    """Specific breakage class for removed parameters."""

    kind: BreakageKind = BreakageKind.PARAMETER_REMOVED

    @property
    def _relative_path(self) -> str:
        return f"{super()._relative_path}({self.old_value.name})"

    def _format_title(self, *, colors: bool = True) -> str:
        blue = _ANSI.FG_BLUE if colors else ""
        reset = _ANSI.FG_RESET if colors else ""
        return f"{super()._relative_path}({blue}{self.old_value.name}{reset})"

    def _format_old_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return ""

    def _format_new_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return ""


class ParameterChangedKindBreakage(Breakage):
    """Specific breakage class for parameters whose kind changed."""

    kind: BreakageKind = BreakageKind.PARAMETER_CHANGED_KIND

    @property
    def _relative_path(self) -> str:
        return f"{super()._relative_path}({self.old_value.name})"

    def _format_title(self, *, colors: bool = True) -> str:
        blue = _ANSI.FG_BLUE if colors else ""
        reset = _ANSI.FG_RESET if colors else ""
        return f"{super()._relative_path}({blue}{self.old_value.name}{reset})"

    def _format_old_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return str(self.old_value.kind.value)

    def _format_new_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return str(self.new_value.kind.value)


class ParameterChangedDefaultBreakage(Breakage):
    """Specific breakage class for parameters whose default value changed."""

    kind: BreakageKind = BreakageKind.PARAMETER_CHANGED_DEFAULT

    @property
    def _relative_path(self) -> str:
        return f"{super()._relative_path}({self.old_value.name})"

    def _format_title(self, *, colors: bool = True) -> str:
        blue = _ANSI.FG_BLUE if colors else ""
        reset = _ANSI.FG_RESET if colors else ""
        return f"{super()._relative_path}({blue}{self.old_value.name}{reset})"

    def _format_old_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return str(self.old_value.default)

    def _format_new_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return str(self.new_value.default)


class ParameterChangedRequiredBreakage(Breakage):
    """Specific breakage class for parameters which became required."""

    kind: BreakageKind = BreakageKind.PARAMETER_CHANGED_REQUIRED

    @property
    def _relative_path(self) -> str:
        return f"{super()._relative_path}({self.old_value.name})"

    def _format_title(self, *, colors: bool = True) -> str:
        blue = _ANSI.FG_BLUE if colors else ""
        reset = _ANSI.FG_RESET if colors else ""
        return f"{super()._relative_path}({blue}{self.old_value.name}{reset})"

    def _format_old_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return ""

    def _format_new_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return ""


class ParameterAddedRequiredBreakage(Breakage):
    """Specific breakage class for new parameters added as required."""

    kind: BreakageKind = BreakageKind.PARAMETER_ADDED_REQUIRED

    @property
    def _relative_path(self) -> str:
        return f"{super()._relative_path}({self.new_value.name})"

    def _format_title(self, *, colors: bool = True) -> str:
        blue = _ANSI.FG_BLUE if colors else ""
        reset = _ANSI.FG_RESET if colors else ""
        return f"{super()._relative_path}({blue}{self.new_value.name}{reset})"

    def _format_old_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return ""

    def _format_new_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return ""


class ReturnChangedTypeBreakage(Breakage):
    """Specific breakage class for return values which changed type."""

    kind: BreakageKind = BreakageKind.RETURN_CHANGED_TYPE


class ObjectRemovedBreakage(Breakage):
    """Specific breakage class for removed objects."""

    kind: BreakageKind = BreakageKind.OBJECT_REMOVED

    def _format_old_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return ""

    def _format_new_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return ""


class ObjectChangedKindBreakage(Breakage):
    """Specific breakage class for objects whose kind changed."""

    kind: BreakageKind = BreakageKind.OBJECT_CHANGED_KIND

    def _format_old_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return self.old_value.value

    def _format_new_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return self.new_value.value


class AttributeChangedTypeBreakage(Breakage):
    """Specific breakage class for attributes whose type changed."""

    kind: BreakageKind = BreakageKind.ATTRIBUTE_CHANGED_TYPE


class AttributeChangedValueBreakage(Breakage):
    """Specific breakage class for attributes whose value changed."""

    kind: BreakageKind = BreakageKind.ATTRIBUTE_CHANGED_VALUE


class ClassRemovedBaseBreakage(Breakage):
    """Specific breakage class for removed base classes."""

    kind: BreakageKind = BreakageKind.CLASS_REMOVED_BASE

    def _format_old_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return "[" + ", ".join(base.canonical_path for base in self.old_value) + "]"

    def _format_new_value(self, *, colors: bool = True) -> str:  # noqa: ARG002
        return "[" + ", ".join(base.canonical_path for base in self.new_value) + "]"


# TODO: Check decorators? Maybe resolved by extensions and/or dynamic analysis.
def _class_incompatibilities(
    old_class: Class,
    new_class: Class,
    *,
    seen_paths: set[str],
) -> Iterable[Breakage]:
    yield from ()
    if new_class.bases != old_class.bases and len(new_class.bases) < len(old_class.bases):
        yield ClassRemovedBaseBreakage(new_class, old_class.bases, new_class.bases)
    yield from _member_incompatibilities(old_class, new_class, seen_paths=seen_paths)


# TODO: Check decorators? Maybe resolved by extensions and/or dynamic analysis.
def _function_incompatibilities(old_function: Function, new_function: Function) -> Iterator[Breakage]:
    new_param_names = [param.name for param in new_function.parameters]
    param_kinds = {param.kind for param in new_function.parameters}
    has_variadic_args = ParameterKind.var_positional in param_kinds
    has_variadic_kwargs = ParameterKind.var_keyword in param_kinds

    for old_index, old_param in enumerate(old_function.parameters):
        # Check if the parameter was removed.
        if old_param.name not in new_function.parameters:
            swallowed = (
                (old_param.kind is ParameterKind.keyword_only and has_variadic_kwargs)
                or (old_param.kind is ParameterKind.positional_only and has_variadic_args)
                or (old_param.kind is ParameterKind.positional_or_keyword and has_variadic_args and has_variadic_kwargs)
            )
            if not swallowed:
                yield ParameterRemovedBreakage(new_function, old_param, None)
            continue

        # Check if the parameter became required.
        new_param = new_function.parameters[old_param.name]
        if new_param.required and not old_param.required:
            yield ParameterChangedRequiredBreakage(new_function, old_param, new_param)

        # Check if the parameter was moved.
        if old_param.kind in _POSITIONAL and new_param.kind in _POSITIONAL:
            new_index = new_param_names.index(old_param.name)
            if new_index != old_index:
                details = f"position: from {old_index} to {new_index} ({new_index - old_index:+})"
                yield ParameterMovedBreakage(new_function, old_param, new_param, details=details)

        # Check if the parameter changed kind.
        if old_param.kind is not new_param.kind:
            incompatible_kind = any(
                (
                    # Positional-only to keyword-only.
                    old_param.kind is ParameterKind.positional_only and new_param.kind is ParameterKind.keyword_only,
                    # Keyword-only to positional-only.
                    old_param.kind is ParameterKind.keyword_only and new_param.kind is ParameterKind.positional_only,
                    # Positional or keyword to positional-only/keyword-only.
                    old_param.kind is ParameterKind.positional_or_keyword
                    and new_param.kind in _POSITIONAL_KEYWORD_ONLY,
                    # Not keyword-only to variadic keyword, without variadic positional.
                    new_param.kind is ParameterKind.var_keyword
                    and old_param.kind is not ParameterKind.keyword_only
                    and not has_variadic_args,
                    # Not positional-only to variadic positional, without variadic keyword.
                    new_param.kind is ParameterKind.var_positional
                    and old_param.kind is not ParameterKind.positional_only
                    and not has_variadic_kwargs,
                ),
            )
            if incompatible_kind:
                yield ParameterChangedKindBreakage(new_function, old_param, new_param)

        # Check if the parameter changed default.
        breakage = ParameterChangedDefaultBreakage(new_function, old_param, new_param)
        non_required = not old_param.required and not new_param.required
        non_variadic = old_param.kind not in _VARIADIC and new_param.kind not in _VARIADIC
        if non_required and non_variadic:
            try:
                if old_param.default != new_param.default:
                    yield breakage
            except Exception:  # noqa: BLE001 (equality checks sometimes fail, e.g. numpy arrays)
                # NOTE: Emitting breakage on a failed comparison could be a preference.
                yield breakage

    # Check if required parameters were added.
    for new_param in new_function.parameters:
        if new_param.name not in old_function.parameters and new_param.required:
            yield ParameterAddedRequiredBreakage(new_function, None, new_param)

    if not _returns_are_compatible(old_function, new_function):
        yield ReturnChangedTypeBreakage(new_function, old_function.returns, new_function.returns)


def _attribute_incompatibilities(old_attribute: Attribute, new_attribute: Attribute) -> Iterable[Breakage]:
    # TODO: Support annotation breaking changes.
    if old_attribute.value != new_attribute.value:
        if new_attribute.value is None:
            yield AttributeChangedValueBreakage(new_attribute, old_attribute.value, "unset")
        else:
            yield AttributeChangedValueBreakage(new_attribute, old_attribute.value, new_attribute.value)


def _alias_incompatibilities(
    old_obj: Object | Alias,
    new_obj: Object | Alias,
    *,
    seen_paths: set[str],
) -> Iterable[Breakage]:
    try:
        old_member = old_obj.target if old_obj.is_alias else old_obj  # ty:ignore[unresolved-attribute]
        new_member = new_obj.target if new_obj.is_alias else new_obj  # ty:ignore[unresolved-attribute]
    except AliasResolutionError:
        logger.debug("API check: %s | %s: skip alias with unknown target", old_obj.path, new_obj.path)
        return

    yield from _type_based_yield(old_member, new_member, seen_paths=seen_paths)


def _member_incompatibilities(
    old_obj: Object | Alias,
    new_obj: Object | Alias,
    *,
    seen_paths: set[str] | None = None,
) -> Iterator[Breakage]:
    seen_paths = set() if seen_paths is None else seen_paths
    for name, old_member in old_obj.all_members.items():
        if not old_member.is_public:
            logger.debug("API check: %s.%s: skip non-public object", old_obj.path, name)
            continue
        logger.debug("API check: %s.%s", old_obj.path, name)
        try:
            new_member = new_obj.all_members[name]
        except KeyError:
            if (not old_member.is_alias and old_member.is_module) or old_member.is_public:
                yield ObjectRemovedBreakage(old_member, old_member, None)  # ty:ignore[invalid-argument-type]
        else:
            yield from _type_based_yield(old_member, new_member, seen_paths=seen_paths)


def _type_based_yield(
    old_member: Object | Alias,
    new_member: Object | Alias,
    *,
    seen_paths: set[str],
) -> Iterator[Breakage]:
    if old_member.path in seen_paths:
        return
    seen_paths.add(old_member.path)
    if old_member.is_alias or new_member.is_alias:
        # Should be first, since there can be the case where there is an alias and another kind of object,
        # which may not be a breaking change.
        yield from _alias_incompatibilities(
            old_member,
            new_member,
            seen_paths=seen_paths,
        )
    elif new_member.kind != old_member.kind:
        yield ObjectChangedKindBreakage(new_member, old_member.kind, new_member.kind)  # ty:ignore[invalid-argument-type]
    elif old_member.is_module:
        yield from _member_incompatibilities(
            old_member,
            new_member,
            seen_paths=seen_paths,
        )
    elif old_member.is_class:
        yield from _class_incompatibilities(
            old_member,  # ty:ignore[invalid-argument-type]
            new_member,  # ty:ignore[invalid-argument-type]
            seen_paths=seen_paths,
        )
    elif old_member.is_function:
        yield from _function_incompatibilities(old_member, new_member)  # ty:ignore[invalid-argument-type]
    elif old_member.is_attribute:
        yield from _attribute_incompatibilities(old_member, new_member)  # ty:ignore[invalid-argument-type]


def _returns_are_compatible(old_function: Function, new_function: Function) -> bool:
    # We consider that a return value of `None` only is not a strong contract,
    # it just means that the function returns nothing. We don't expect users
    # to be asserting that the return value is `None`.
    # Therefore we don't consider it a breakage if the return changes from `None`
    # to something else: the function just gained a return value.
    if old_function.returns is None:
        return True

    if new_function.returns is None:
        # NOTE: Should it be configurable to allow/disallow removing a return type?
        return False

    with contextlib.suppress(AttributeError):
        if new_function.returns == old_function.returns:
            return True

    # TODO: Support annotation breaking changes.
    return True


_sentinel = object()


def find_breaking_changes(
    old_obj: Object | Alias,
    new_obj: Object | Alias,
) -> Iterator[Breakage]:
    """Find breaking changes between two versions of the same API.

    The function will iterate recursively on all objects
    and yield breaking changes with detailed information.

    Parameters:
        old_obj: The old version of an object.
        new_obj: The new version of an object.

    Yields:
        Breaking changes.

    Examples:
        >>> import sys, griffe
        >>> new = griffe.load("pkg")
        >>> old = griffe.load_git("pkg", "1.2.3")
        >>> for breakage in griffe.find_breaking_changes(old, new)
        ...     print(breakage.explain(style=style), file=sys.stderr)
    """
    yield from _member_incompatibilities(old_obj, new_obj)
