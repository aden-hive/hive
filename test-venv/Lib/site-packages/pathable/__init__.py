"""Pathable module"""

from pathable.accessors import NodeAccessor
from pathable.accessors import PathAccessor
from pathable.paths import AccessorPath
from pathable.paths import BasePath
from pathable.paths import FilesystemPath
from pathable.paths import LookupPath
from pathable.paths import LookupPath as DictPath
from pathable.paths import LookupPath as ListPath

__author__ = "Artur Maciag"
__email__ = "maciag.artur@gmail.com"
__version__ = "0.5.0"
__url__ = "https://github.com/p1c2u/pathable"
__license__ = "Apache License, Version 2.0"

__all__ = [
    "BasePath",
    "AccessorPath",
    "FilesystemPath",
    "LookupPath",
    "DictPath",
    "ListPath",
    "NodeAccessor",
    "PathAccessor",
]
