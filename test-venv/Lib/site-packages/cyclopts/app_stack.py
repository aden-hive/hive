from collections.abc import Sequence
from contextlib import contextmanager
from itertools import chain
from typing import TYPE_CHECKING, Any, TypeVar, cast, overload

from cyclopts.group_extractors import inverse_groups_from_app
from cyclopts.parameter import Parameter

if TYPE_CHECKING:
    from cyclopts.core import App


V = TypeVar("V")


class AppStack:
    def __init__(self, app):
        # the ``stack`` is guaranteed to have the self-referencing app at the top of the stack.
        self.stack: list[list[App]] = [[app]]
        # Stack of overrides passed to parse_args/call that should be propagated
        self.overrides_stack: list[dict[str, Any]] = [{}]

    @contextmanager
    def __call__(self, apps: Sequence["App"] | Sequence[str], overrides: dict[str, Any] | None = None):
        # set `overrides` default-values with current overrides so that they properly propagate down the call-stack.
        overrides = self.overrides | (overrides or {})

        self.overrides_stack.append(overrides or {})

        if not apps:
            try:
                yield
            finally:
                self.overrides_stack.pop()
            return

        # Convert strings to Apps if needed
        if isinstance(apps[0], str):
            str_apps = cast(Sequence[str], apps)
            _, apps_tuple, _ = self.stack[0][0].parse_commands(str_apps, include_parent_meta=True)
            resolved_apps: list[App] = list(apps_tuple)
        else:
            resolved_apps = cast(list["App"], list(apps))
        del apps

        if not resolved_apps:
            try:
                yield
            finally:
                self.overrides_stack.pop()
            return

        so_far = []
        app_ids = {id(app) for app in resolved_apps}
        for app in resolved_apps:
            if app._meta_parent is None:
                # Do not include the prior meta-app.
                while so_far and so_far[-1]._meta_parent is not None:
                    so_far.pop()

            so_far.append(app)
            app.app_stack.stack.append(so_far.copy())
            # Also push the overrides onto this app's stack
            app.app_stack.overrides_stack.append(overrides or {})

            # Also traverse the app's meta app
            meta_app = app
            while (meta_app := meta_app._meta) is not None:
                if id(meta_app) in app_ids:
                    # It will be handled conventionally
                    continue
                meta_subapps = so_far.copy()
                meta_subapps.append(meta_app)
                meta_app.app_stack.stack.append(meta_subapps)
                # Also push the overrides onto the meta app's stack
                meta_app.app_stack.overrides_stack.append(overrides or {})
        try:
            yield
        finally:
            for app in resolved_apps:
                app.app_stack.stack.pop()
                app.app_stack.overrides_stack.pop()
                # Also pop from meta apps
                meta_app = app
                while (meta_app := meta_app._meta) is not None:
                    if id(meta_app) in app_ids:
                        continue
                    meta_app.app_stack.stack.pop()
                    meta_app.app_stack.overrides_stack.pop()
            # Pop overrides from stack
            self.overrides_stack.pop()

    @property
    def overrides(self) -> dict:
        out = {}
        for overrides_frame in reversed(self.overrides_stack):
            for key, value in overrides_frame.items():
                if value is not None:
                    out.setdefault(key, value)
        return out

    @property
    def default_parameter(self) -> Parameter:
        """default_parameter has special resolution since it needs to include the command groups in the derivation."""
        cparams = []
        for child_app in chain.from_iterable(self.stack):
            if child_app._meta_parent:
                continue
            cparams.extend([group.default_parameter for group in child_app.app_stack.command_groups])
            cparams.append(child_app.default_parameter)

        return Parameter.combine(*cparams)

    @property
    def current_frame(self) -> list["App"]:
        if not self.stack:
            raise ValueError

        return self.stack[-1]

    @overload
    def resolve(self, attribute: str) -> Any: ...

    @overload
    def resolve(self, attribute: str, override: V) -> V: ...

    @overload
    def resolve(self, attribute: str, override: V | None, fallback: V) -> V: ...

    @overload
    def resolve(self, attribute: str, override: V | None = None, *, fallback: V) -> V: ...

    def resolve(self, attribute: str, override: V | None = None, fallback: V | None = None) -> V | None:
        """Resolve an attribute from the App hierarchy."""
        if override is not None:
            return override

        # Check if we have a stored override from parent invocations (most recent first)
        for overrides_frame in reversed(self.overrides_stack):
            if attribute in overrides_frame:
                value = overrides_frame[attribute]
                if value is not None:
                    return value

        # `reversed` so that "closer" apps have higher priority.
        for app in reversed(list(chain.from_iterable(self.stack))):
            result = getattr(app, attribute)
            if result is not None:
                return result

            # Check parenting meta app(s)
            meta_app = app
            while (meta_app := meta_app._meta_parent) is not None:
                result = getattr(meta_app, attribute)
                if result is not None:
                    return result

        return fallback

    @property
    def command_groups(self) -> list:
        command_app = self.current_frame[-1]
        try:
            current_app: App | None = self.current_frame[-2]
        except IndexError:
            current_app = None

        while current_app is not None:
            try:
                return next(x for x in inverse_groups_from_app(current_app) if x[0] is command_app)[1]
            except StopIteration:
                current_app = current_app._meta_parent
        return []
