"""JSONSchema spec readers module."""

from pathlib import Path
from typing import Any
from typing import Hashable
from typing import Mapping
from typing import Tuple

from jsonschema_path.handlers import all_urls_handler
from jsonschema_path.handlers import file_handler
from jsonschema_path.handlers.protocols import SupportsRead


class BaseReader:
    def read(self) -> Tuple[Mapping[Hashable, Any], str]:
        raise NotImplementedError


class FileReader(BaseReader):
    def __init__(self, fileobj: SupportsRead):
        self.fileobj = fileobj

    def read(self) -> Tuple[Mapping[Hashable, Any], str]:
        return file_handler(self.fileobj), ""


class PathReader(BaseReader):
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> Tuple[Mapping[Hashable, Any], str]:
        if not self.path.is_file():
            raise OSError(f"No such file: {self.path}")

        uri = self.path.as_uri()
        return all_urls_handler(uri), uri


class FilePathReader(PathReader):
    def __init__(self, file_path: str):
        path = Path(file_path).absolute()
        super().__init__(path)
