"""Pathable module"""
from pathable.paths import AccessorPath
from pathable.paths import BasePath
from pathable.paths import LookupPath
from pathable.paths import LookupPath as DictPath
from pathable.paths import LookupPath as ListPath

__author__ = "Artur Maciag"
__email__ = "maciag.artur@gmail.com"
__version__ = "0.4.4"
__url__ = "https://github.com/p1c2u/pathable"
__license__ = "Apache License, Version 2.0"

__all__ = [
    "BasePath",
    "AccessorPath",
    "LookupPath",
    "DictPath",
    "ListPath",
]
