from typing import Any
from typing import Hashable
from typing import Mapping
from typing import Optional


def is_ref(item: Optional[Mapping[Hashable, Any]]) -> bool:
    return isinstance(item, dict) and "$ref" in item and item["$ref"].__hash__
