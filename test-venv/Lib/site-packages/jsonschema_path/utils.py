from typing import Any


def is_ref(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and "$ref" in item
        and isinstance(item["$ref"], str)
    )
