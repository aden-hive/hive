import errno
import os
from abc import ABC, abstractmethod
from collections.abc import Iterable
from contextlib import suppress
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Any

from attrs import define, field

from cyclopts.argument import ArgumentCollection, update_argument_collection
from cyclopts.exceptions import CycloptsError
from cyclopts.utils import to_tuple_converter

if TYPE_CHECKING:
    from cyclopts.core import App


@define(kw_only=True)
class ConfigBase(ABC):
    """Base class for configuration sources.

    Handles the common logic of processing configuration dictionaries
    and updating ArgumentCollections.
    """

    root_keys: Iterable[str] = field(default=(), converter=to_tuple_converter)
    allow_unknown: bool = field(default=False)
    use_commands_as_keys: bool = field(default=True)
    _source: str | None = field(default=None, alias="source")

    @property
    @abstractmethod
    def config(self) -> dict[str, Any]:
        """Return the configuration dictionary."""
        raise NotImplementedError

    @property
    @abstractmethod
    def source(self) -> str:
        """Return a string identifying the configuration source for error messages."""
        raise NotImplementedError

    def __call__(
        self,
        app: "App",
        commands: tuple[str, ...],
        arguments: ArgumentCollection,
    ):
        config: dict[str, Any] = self.config.copy()
        try:
            for key in chain(self.root_keys, commands if self.use_commands_as_keys else ()):
                config = config[key]
        except KeyError:
            return

        # Hierarchical config uses current app; flat config uses root app to filter sibling commands
        if self.use_commands_as_keys:
            filter_app = app
        else:
            filter_app = next((a for a in app.app_stack.current_frame if not a._meta_parent), app)
        config = {k: v for k, v in config.items() if k not in filter_app}

        update_argument_collection(
            config,
            self.source,
            arguments,
            app.app_stack.stack[-1],
            root_keys=self.root_keys,
            allow_unknown=self.allow_unknown,
        )


class FileCacheKey:
    """Abstraction to quickly check if a file needs to be read again.

    If a newly instantiated ``CacheKey`` doesn't equal a previously instantiated ``CacheKey``,
    then the file needs to be re-read.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).absolute()
        if self.path.exists():
            stat = self.path.stat()
            self._mtime = stat.st_mtime
            self._size = stat.st_size
        else:
            self._mtime = None
            self._size = None

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False

        return self._mtime == other._mtime and self._size == other._size and self.path == other.path


@define
class ConfigFromFile(ConfigBase):
    """Configuration source that loads from a file.

    Supports file caching and parent directory searching.
    """

    path: str | Path = field(converter=Path)
    must_exist: bool = field(default=False, kw_only=True)
    search_parents: bool = field(default=False, kw_only=True)

    _config: dict[str, Any] | None = field(default=None, init=False, repr=False)
    "Loaded configuration structure (to be loaded by subclassed ``_load_config`` method)."

    _config_cache_key: FileCacheKey | None = field(default=None, init=False, repr=False)
    "Conditions under which ``_config`` was loaded."

    @abstractmethod
    def _load_config(self, path: Path) -> dict[str, Any]:
        """Load the config dictionary from path.

        Do **not** do any downstream caching; ``ConfigFromFile`` handles caching.

        Parameters
        ----------
        path: Path
            Path to the file. Guaranteed to exist.

        Returns
        -------
        dict
            Loaded configuration.
        """
        raise NotImplementedError

    @property
    def config(self) -> dict[str, Any]:
        assert isinstance(self.path, Path)
        for parent in self.path.expanduser().resolve().absolute().parents:
            candidate = parent / self.path.name
            if candidate.exists():
                cache_key = FileCacheKey(candidate)
                if self._config_cache_key == cache_key:
                    return self._config or {}

                try:
                    self._config = self._load_config(candidate)
                    self._config_cache_key = cache_key
                except CycloptsError:
                    raise
                except Exception as e:
                    msg = getattr(type(e), "__name__", "")
                    with suppress(IndexError):
                        exception_msg = e.args[0]
                        if msg:
                            msg += ": "
                        msg += exception_msg
                    raise CycloptsError(msg=msg) from e
                return self._config
            elif self.search_parents:
                # Continue iterating over parents.
                continue
            elif self.must_exist:
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(self.path))

        # No matching file was found.
        if self.must_exist:
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(self.path))

        self._config = {}
        return self._config

    @property
    def source(self) -> str:
        """Return a string identifying the configuration source for error messages."""
        if self._source is not None:
            return self._source
        assert isinstance(self.path, Path)
        return str(self.path.absolute())

    @source.setter
    def source(self, value: str) -> None:
        self._source = value


@define
class Dict(ConfigBase):
    """Configuration source from an in-memory dictionary.

    Useful for programmatically generated configurations.
    """

    data: dict[str, Any]

    @property
    def config(self) -> dict[str, Any]:
        return self.data

    @property
    def source(self) -> str:
        """Return a string identifying the configuration source for error messages."""
        if self._source is not None:
            return self._source
        return "dict"

    @source.setter
    def source(self, value: str) -> None:
        self._source = value
