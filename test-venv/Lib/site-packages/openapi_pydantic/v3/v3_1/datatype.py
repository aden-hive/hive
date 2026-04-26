from enum import Enum


class DataType(str, Enum):
    """Data type of an object."""

    NULL = "null"
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
