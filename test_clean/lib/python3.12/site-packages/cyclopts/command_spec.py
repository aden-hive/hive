"""Lazy-loadable command specification for deferred imports."""

import importlib
from itertools import chain
from typing import TYPE_CHECKING, Any

from attrs import Factory, define, field

if TYPE_CHECKING:
    from cyclopts.core import App


@define
class CommandSpec:
    """Specification for a command that will be lazily loaded on first access.

    This allows registering commands via import path strings (e.g., "myapp.commands:create")
    without importing them until they're actually used, improving CLI startup time.

    Parameters
    ----------
    import_path : str
        Import path in the format "module.path:attribute_name".
        The attribute should be either a function or an App instance.
    name : str | tuple[str, ...] | None
        CLI command name. If None, will be derived from the attribute name via name_transform.
        For function imports: used as the name of the wrapper App.
        For App imports: must match the App's internal name, or ValueError is raised at resolution.
    app_kwargs : dict
        Keyword arguments to pass to App() if wrapping a function.
        Raises ValueError if used with App imports (Apps should be configured in their own definition).

    Examples
    --------
    >>> from cyclopts import App
    >>> app = App()
    >>> # Lazy load - doesn't import myapp.commands until "create" is executed
    >>> app.command("myapp.commands:create_user", name="create")
    >>> app()
    """

    import_path: str
    name: str | tuple[str, ...] | None = None
    app_kwargs: dict[str, Any] = Factory(dict)

    _resolved: "App | None" = field(init=False, default=None, repr=False)

    def resolve(self, parent_app: "App") -> "App":
        """Import and resolve the command on first access.

        Parameters
        ----------
        parent_app : App
            Parent app to inherit defaults from (help_flags, version_flags, groups).
            Required to match the behavior of direct command registration.

        Returns
        -------
        App
            The resolved App instance, either imported directly or wrapping a function.

        Raises
        ------
        ValueError
            If import_path is not in the correct format "module.path:attribute_name".
        ImportError
            If the module cannot be imported.
        AttributeError
            If the attribute doesn't exist in the module.
        """
        if self._resolved is not None:
            return self._resolved

        # Parse import path
        module_path, _, attr_name = self.import_path.rpartition(":")
        if not module_path or not attr_name:
            raise ValueError(
                f"Invalid import path: {self.import_path!r}. Expected format: 'module.path:attribute_name'"
            )

        # Import the module and get the attribute
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise ImportError(f"Cannot import module {module_path!r} from {self.import_path!r}") from e

        try:
            target = getattr(module, attr_name)
        except AttributeError as e:
            raise AttributeError(
                f"Module {module_path!r} has no attribute {attr_name!r} (from import path {self.import_path!r})"
            ) from e

        # Wrap in App if needed
        from cyclopts.core import App

        if isinstance(target, App):
            # Validate that no kwargs were provided for App imports
            if self.app_kwargs:
                raise ValueError(
                    f"Cannot apply configuration to imported App. "
                    f"Import path {self.import_path!r} resolves to an App, "
                    f"but kwargs were specified: {self.app_kwargs!r}. "
                    f"Configure the App in its definition instead."
                )

            # Validate that the App's name matches the expected CLI command name
            # The name used for CLI registration is stored in self.name
            if self.name is not None and target.name[0] != self.name:
                raise ValueError(
                    f"Imported App name mismatch. "
                    f"Import path {self.import_path!r} resolves to an App with name={target.name[0]!r}, "
                    f"but it was registered with CLI command name={self.name!r}. "
                    f"Either use app.command('{self.import_path}', name='{target.name[0]}') "
                    f"or change the App's name to match."
                )

            # Copy parent groups if not set (matches direct App registration behavior)
            from cyclopts.core import _apply_parent_defaults_to_app

            _apply_parent_defaults_to_app(target, parent_app)

            self._resolved = target
        else:
            # It's a function - wrap it in an App with parent defaults
            # Match the behavior of direct function registration
            app_kwargs = dict(self.app_kwargs)  # Copy to avoid mutating

            from cyclopts.core import _apply_parent_groups_to_kwargs

            app_kwargs.setdefault("help_flags", parent_app.help_flags)
            app_kwargs.setdefault("version_flags", parent_app.version_flags)
            if "version" not in app_kwargs and parent_app.version is not None:
                app_kwargs["version"] = parent_app.version

            _apply_parent_groups_to_kwargs(app_kwargs, parent_app)

            self._resolved = App(name=self.name, **app_kwargs)
            self._resolved.default(target)

        # Hide help and version flags from subapp help output
        # This matches the behavior of direct App/function registration in core.py
        for flag in chain(self._resolved.help_flags, self._resolved.version_flags):
            self._resolved[flag].show = False

        return self._resolved

    @property
    def is_resolved(self) -> bool:
        """Check if this command has been imported and resolved yet."""
        return self._resolved is not None
