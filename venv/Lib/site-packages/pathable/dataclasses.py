from dataclasses import dataclass
from typing import Hashable
from typing import List


@dataclass
class BasePathData:

    parts: List[Hashable]
    separator: str
