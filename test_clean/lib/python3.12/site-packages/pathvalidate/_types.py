from pathlib import Path
from typing import TypeVar

from ._const import Platform


PathType = TypeVar("PathType", str, Path)
PlatformType = TypeVar("PlatformType", str, Platform)
