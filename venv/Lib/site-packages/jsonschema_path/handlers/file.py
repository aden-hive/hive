"""JSONSchema spec handlers file module."""

from json import dumps
from json import loads
from typing import Any
from typing import ContextManager
from typing import Optional
from typing import Tuple
from urllib.parse import urlparse

from yaml import load

from jsonschema_path.handlers.protocols import SupportsRead
from jsonschema_path.handlers.utils import uri_to_path
from jsonschema_path.loaders import JsonschemaSafeLoader


class FileHandler:
    """File-like object handler."""

    def __init__(self, loader: Any = JsonschemaSafeLoader):
        self.loader = loader

    def __call__(self, stream: SupportsRead) -> Any:
        data = self._load(stream)
        return loads(dumps(data))

    def _load(self, stream: SupportsRead) -> Any:
        return load(stream, self.loader)


class BaseFilePathHandler:
    """Base file path handler."""

    allowed_schemes: Tuple[str, ...] = NotImplemented

    def __init__(
        self, *allowed_schemes: str, file_handler: Optional[FileHandler] = None
    ):
        self.allowed_schemes = allowed_schemes or self.allowed_schemes
        self.file_handler = file_handler or FileHandler()

    def __call__(self, uri: str) -> Any:
        parsed_url = urlparse(uri)
        if parsed_url.scheme not in self.allowed_schemes:
            raise ValueError(f"Scheme {parsed_url.scheme} not allowed")

        with self._open(uri) as stream:
            return self.file_handler(stream)

    def _open(self, uri: str) -> ContextManager[SupportsRead]:
        raise NotImplementedError


class FilePathHandler(BaseFilePathHandler):
    """File path handler."""

    allowed_schemes = ("file",)

    def __init__(
        self,
        *allowed_schemes: str,
        file_handler: Optional[FileHandler] = None,
        encoding: str = "utf-8",
    ):
        super().__init__(*allowed_schemes, file_handler=file_handler)
        self.encoding = encoding

    def _open(self, uri: str) -> ContextManager[SupportsRead]:
        filepath = uri_to_path(uri)
        return open(filepath, encoding=self.encoding)
