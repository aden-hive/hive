import enum


class DataType(str, enum.Enum):
    """Data type of an object.

    Note: OpenAPI 3.0.x does not support null as a data type.
    """

    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
