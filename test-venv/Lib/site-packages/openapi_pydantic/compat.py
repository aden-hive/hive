"""Compatibility layer to make this package usable with Pydantic 1 or 2"""

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from pydantic.version import VERSION as PYDANTIC_VERSION

__all__ = [
    "PYDANTIC_V2",
    "ConfigDict",
    "JsonSchemaMode",
    "models_json_schema",
    "RootModel",
    "Extra",
    "v1_schema",
    "DEFS_KEY",
    "min_length_arg",
]

PYDANTIC_MAJOR_VERSION = int(PYDANTIC_VERSION.split(".", 1)[0])
PYDANTIC_MINOR_VERSION = int(PYDANTIC_VERSION.split(".")[1])
PYDANTIC_V2 = PYDANTIC_MAJOR_VERSION >= 2

if TYPE_CHECKING:
    # Provide stubs for either version of Pydantic

    from enum import Enum
    from typing import Any, Literal, Type, TypedDict

    from pydantic import BaseModel
    from pydantic import ConfigDict as PydanticConfigDict

    def ConfigDict(
        extra: Literal["allow", "ignore", "forbid"] = "allow",
        json_schema_extra: Optional[Dict[str, Any]] = None,
        populate_by_name: bool = True,
    ) -> PydanticConfigDict:
        """Stub for pydantic.ConfigDict in Pydantic 2"""
        ...

    class Extra(Enum):
        """Stub for pydantic.Extra in Pydantic 1"""

        allow = "allow"
        ignore = "ignore"
        forbid = "forbid"

    class RootModel(BaseModel):
        """Stub for pydantic.RootModel in Pydantic 2"""

    JsonSchemaMode = Literal["validation", "serialization"]

    def models_json_schema(
        models: List[Tuple[Type[BaseModel], JsonSchemaMode]],
        *,
        by_alias: bool = True,
        ref_template: str = "#/$defs/{model}",
        schema_generator: Optional[type] = None,
    ) -> Tuple[Dict, Dict[str, Any]]:
        """Stub for pydantic.json_schema.models_json_schema in Pydantic 2"""
        ...

    def v1_schema(
        models: List[Type[BaseModel]],
        *,
        by_alias: bool = True,
        ref_prefix: str = "#/$defs",
    ) -> Dict[str, Any]:
        """Stub for pydantic.schema.schema in Pydantic 1"""
        ...

    DEFS_KEY = "$defs"

    class MinLengthArg(TypedDict):
        pass

    def min_length_arg(min_length: int) -> MinLengthArg:
        """Generate a min_length or min_items parameter for Field(...)"""
        ...

elif PYDANTIC_V2:
    from typing import TypedDict

    from pydantic import ConfigDict, RootModel
    from pydantic.json_schema import JsonSchemaMode, models_json_schema

    # Pydantic 2 renders JSON schemas using the keyword "$defs"
    DEFS_KEY = "$defs"

    class MinLengthArg(TypedDict):
        min_length: int

    def min_length_arg(min_length: int) -> MinLengthArg:
        return {"min_length": min_length}

    # Create V1 stubs. These should not be used when PYDANTIC_V2 is true.
    Extra = None
    v1_schema = None


else:
    from typing import TypedDict

    from pydantic import Extra
    from pydantic.schema import schema as v1_schema

    # Pydantic 1 renders JSON schemas using the keyword "definitions"
    DEFS_KEY = "definitions"

    class MinLengthArg(TypedDict):
        min_items: int

    def min_length_arg(min_length: int) -> MinLengthArg:
        return {"min_items": min_length}

    # Create V2 stubs. These should not be used when PYDANTIC_V2 is false.
    ConfigDict = None
    models_json_schema = None
    JsonSchemaMode = None
    RootModel = None
