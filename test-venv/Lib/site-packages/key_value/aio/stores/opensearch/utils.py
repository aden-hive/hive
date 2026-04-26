from typing import Any, TypeVar, cast

from opensearchpy import AsyncOpenSearch
from opensearchpy.serializer import JSONSerializer


def get_body_from_response(response: Any) -> dict[str, Any]:
    if not response:
        return {}

    if isinstance(response, dict):
        return cast("dict[str, Any]", response)

    # OpenSearch response objects might have a body attribute
    if hasattr(response, "body"):
        body = response.body
        if not body:
            return {}
        if isinstance(body, dict):
            return cast("dict[str, Any]", body)

    return {}


def get_source_from_body(body: dict[str, Any]) -> dict[str, Any]:
    if not (source := body.get("_source")):
        return {}

    if not isinstance(source, dict) or not all(isinstance(key, str) for key in source):  # pyright: ignore[reportUnknownVariableType]
        return {}

    return cast("dict[str, Any]", source)


def get_aggregations_from_body(body: dict[str, Any]) -> dict[str, Any]:
    if not (aggregations := body.get("aggregations")):
        return {}

    if not isinstance(aggregations, dict) or not all(
        isinstance(key, str)
        for key in aggregations  # pyright: ignore[reportUnknownVariableType]
    ):
        return {}

    return cast("dict[str, Any]", aggregations)


def get_hits_from_response(response: Any) -> list[dict[str, Any]]:
    body = get_body_from_response(response=response)

    if not body:
        return []

    if not (hits := body.get("hits")):
        return []

    if not isinstance(hits, dict):
        return []

    hits_dict: dict[str, Any] = cast("dict[str, Any]", hits)

    if not (hits_list := hits_dict.get("hits")):
        return []

    if not all(isinstance(hit, dict) for hit in hits_list):
        return []

    hits_list_dict: list[dict[str, Any]] = cast("list[dict[str, Any]]", hits_list)

    return hits_list_dict


T = TypeVar("T")


def get_fields_from_hit(hit: dict[str, Any]) -> dict[str, list[Any]]:
    if not (fields := hit.get("fields")):
        return {}

    if not isinstance(fields, dict) or not all(isinstance(key, str) for key in fields):  # pyright: ignore[reportUnknownVariableType]
        msg = f"Fields in hit {hit} is not a dict"
        raise TypeError(msg)

    if not all(isinstance(value, list) for value in fields.values()):  # pyright: ignore[reportUnknownVariableType]
        msg = f"Fields in hit {hit} is not a dict of lists"
        raise TypeError(msg)

    return cast("dict[str, list[Any]]", fields)


def get_field_from_hit(hit: dict[str, Any], field: str) -> list[Any]:
    if not (fields := get_fields_from_hit(hit=hit)):
        return []

    if not (value := fields.get(field)):
        msg = f"Field {field} is not in hit {hit}"
        raise TypeError(msg)

    return value


def get_values_from_field_in_hit(hit: dict[str, Any], field: str, value_type: type[T]) -> list[T]:
    if not (value := get_field_from_hit(hit=hit, field=field)):
        msg = f"Field {field} is not in hit {hit}"
        raise TypeError(msg)

    if not all(isinstance(item, value_type) for item in value):
        msg = f"Field {field} in hit {hit} is not a list of {value_type}"
        raise TypeError(msg)

    return cast("list[T]", value)


def get_first_value_from_field_in_hit(hit: dict[str, Any], field: str, value_type: type[T]) -> T:
    values: list[T] = get_values_from_field_in_hit(hit=hit, field=field, value_type=value_type)
    if len(values) != 1:
        msg: str = f"Field {field} in hit {hit} is not a single value"
        raise TypeError(msg)
    return values[0]


def new_bulk_action(action: str, index: str, document_id: str) -> dict[str, Any]:
    return {action: {"_index": index, "_id": document_id}}


class LessCapableJsonSerializer(JSONSerializer):
    """A JSON Serializer that doesnt try to be smart with datetime, floats, etc."""

    def default(self, data: Any) -> Any:
        msg = f"Unable to serialize to JSON: {data!r} (type: {type(data).__name__})"
        raise TypeError(msg)

    @classmethod
    def install_serializer(cls, client: AsyncOpenSearch) -> None:
        # OpenSearch uses a different serializer architecture
        client.transport.serializer = cls()
