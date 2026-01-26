from typing import Any, ClassVar, TypeVar, cast

from elastic_transport import (
    JsonSerializer,
    NdjsonSerializer,
    ObjectApiResponse,
    SerializationError,
)
from elasticsearch import AsyncElasticsearch


def get_body_from_response(response: ObjectApiResponse[Any]) -> dict[str, Any]:
    if not (body := response.body):  # pyright: ignore[reportAny]
        return {}

    if not isinstance(body, dict) or not all(isinstance(key, str) for key in body):  # pyright: ignore[reportUnknownVariableType]
        return {}

    return cast("dict[str, Any]", body)


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


def get_hits_from_response(response: ObjectApiResponse[Any]) -> list[dict[str, Any]]:
    if not (body := response.body):  # pyright: ignore[reportAny]
        return []

    if not isinstance(body, dict) or not all(isinstance(key, str) for key in body):  # pyright: ignore[reportUnknownVariableType]
        return []

    body_dict: dict[str, Any] = cast("dict[str, Any]", body)

    if not (hits := body_dict.get("hits")):
        return []

    hits_dict: dict[str, Any] = cast("dict[str, Any]", hits)

    if not (hits_list := hits_dict.get("hits")):
        return []

    if not all(isinstance(hit, dict) for hit in hits_list):  # pyright: ignore[reportAny]
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

    if not all(isinstance(item, value_type) for item in value):  # pyright: ignore[reportAny]
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


class LessCapableJsonSerializer(JsonSerializer):
    """A JSON Serializer that doesnt try to be smart with datetime, floats, etc."""

    mimetype: ClassVar[str] = "application/json"
    compatibility_mimetype: ClassVar[str] = "application/vnd.elasticsearch+json"

    def default(self, data: Any) -> Any:
        raise SerializationError(
            message=f"Unable to serialize to JSON: {data!r} (type: {type(data).__name__})",
        )

    @classmethod
    def install_default_serializer(cls, client: AsyncElasticsearch) -> None:
        cls.install_serializer(client=client)
        client.transport.serializers.default_serializer = cls()

    @classmethod
    def install_serializer(cls, client: AsyncElasticsearch) -> None:
        client.transport.serializers.serializers.update(
            {
                cls.mimetype: cls(),
                cls.compatibility_mimetype: cls(),
            }
        )


class LessCapableNdjsonSerializer(NdjsonSerializer):
    """A NDJSON Serializer that doesnt try to be smart with datetime, floats, etc."""

    mimetype: ClassVar[str] = "application/x-ndjson"
    compatibility_mimetype: ClassVar[str] = "application/vnd.elasticsearch+x-ndjson"

    def default(self, data: Any) -> Any:
        return LessCapableJsonSerializer.default(self=self, data=data)  # pyright: ignore[reportCallIssue, reportUnknownVariableType, reportArgumentType]

    @classmethod
    def install_serializer(cls, client: AsyncElasticsearch) -> None:
        client.transport.serializers.serializers.update(
            {
                cls.mimetype: cls(),
                cls.compatibility_mimetype: cls(),
            }
        )
