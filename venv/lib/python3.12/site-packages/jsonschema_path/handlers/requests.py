"""JSONSchema spec handlers requests module."""

from contextlib import closing
from io import StringIO
from typing import ContextManager
from typing import Optional
from typing import Union

import requests

from jsonschema_path.handlers.file import BaseFilePathHandler
from jsonschema_path.handlers.file import FileHandler
from jsonschema_path.handlers.protocols import SupportsRead


class UrlRequestsHandler(BaseFilePathHandler):
    """URL (requests) scheme handler."""

    def __init__(
        self,
        *allowed_schemes: str,
        file_handler: Optional[FileHandler] = None,
        timeout: int = 10,
        verify: Optional[Union[bool, str]] = True,
    ):
        super().__init__(*allowed_schemes, file_handler=file_handler)
        self.timeout = timeout
        self.verify = verify

    def _open(self, uri: str) -> ContextManager[SupportsRead]:
        response = requests.get(uri, timeout=self.timeout, verify=self.verify)
        response.raise_for_status()

        data = StringIO(response.text)
        return closing(data)
