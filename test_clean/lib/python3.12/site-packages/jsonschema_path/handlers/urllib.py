"""JSONSchema spec handlers urllib module."""

from contextlib import closing
from typing import ContextManager
from typing import Optional
from urllib.request import urlopen

from jsonschema_path.handlers.file import BaseFilePathHandler
from jsonschema_path.handlers.file import FileHandler
from jsonschema_path.handlers.protocols import SupportsRead


class UrllibHandler(BaseFilePathHandler):
    """URL (urllib) scheme handler."""

    def __init__(
        self,
        *allowed_schemes: str,
        file_handler: Optional[FileHandler] = None,
        timeout: int = 10
    ):
        super().__init__(*allowed_schemes, file_handler=file_handler)
        self.timeout = timeout

    def _open(self, uri: str) -> ContextManager[SupportsRead]:
        return closing(urlopen(uri, timeout=self.timeout))
