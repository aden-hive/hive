from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra, min_length_arg

from .datatype import DataType
from .discriminator import Discriminator
from .external_documentation import ExternalDocumentation
from .reference import Reference
from .xml import XML

_examples = [
    {"type": "string", "format": "email"},
    {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "address": {"$ref": "#/components/schemas/Address"},
            "age": {"type": "integer", "format": "int32", "minimum": 0},
        },
    },
    {"type": "object", "additionalProperties": {"type": "string"}},
    {
        "type": "object",
        "additionalProperties": {"$ref": "#/components/schemas/ComplexModel"},
    },
    {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "format": "int64"},
            "name": {"type": "string"},
        },
        "required": ["name"],
        "example": {"name": "Puma", "id": 1},
    },
    {
        "type": "object",
        "required": ["message", "code"],
        "properties": {
            "message": {"type": "string"},
            "code": {"type": "integer", "minimum": 100, "maximum": 600},
        },
    },
    {
        "allOf": [
            {"$ref": "#/components/schemas/ErrorModel"},
            {
                "type": "object",
                "required": ["rootCause"],
                "properties": {"rootCause": {"type": "string"}},
            },
        ]
    },
    {
        "type": "object",
        "discriminator": {"propertyName": "petType"},
        "properties": {
            "name": {"type": "string"},
            "petType": {"type": "string"},
        },
        "required": ["name", "petType"],
    },
    {
        "description": "A representation of a cat. "
        "Note that `Cat` will be used as the discriminator value.",
        "allOf": [
            {"$ref": "#/components/schemas/Pet"},
            {
                "type": "object",
                "properties": {
                    "huntingSkill": {
                        "type": "string",
                        "description": "The measured skill for hunting",
                        "default": "lazy",
                        "enum": [
                            "clueless",
                            "lazy",
                            "adventurous",
                            "aggressive",
                        ],
                    }
                },
                "required": ["huntingSkill"],
            },
        ],
    },
    {
        "description": "A representation of a dog. "
        "Note that `Dog` will be used as the discriminator value.",
        "allOf": [
            {"$ref": "#/components/schemas/Pet"},
            {
                "type": "object",
                "properties": {
                    "packSize": {
                        "type": "integer",
                        "format": "int32",
                        "description": ("the size of the pack the dog is from"),
                        "default": 0,
                        "minimum": 0,
                    }
                },
                "required": ["packSize"],
            },
        ],
    },
]


class Schema(BaseModel):
    """
    The Schema Object allows the definition of input and output data types.
    These types can be objects, but also primitives and arrays.
    This object is an extended subset of the [JSON Schema Specification Wright Draft 00](https://json-schema.org/).

    For more information about the properties,
    see [JSON Schema Core](https://tools.ietf.org/html/draft-wright-json-schema-00)
    and [JSON Schema Validation](https://tools.ietf.org/html/draft-wright-json-schema-validation-00).
    Unless stated otherwise, the property definitions follow the JSON Schema.
    """

    """
    The following properties are taken directly from the JSON Schema definition and 
    follow the same specifications:
    """

    title: Optional[str] = None
    """
    The value of "title" MUST be a string.

    The title can be used to decorate a user interface with
    information about the data produced by this user interface.
    The title will preferrably be short.
    """

    multipleOf: Optional[float] = Field(default=None, gt=0.0)
    """
    The value of "multipleOf" MUST be a number, strictly greater than 0.
    
    A numeric instance is only valid if division by this keyword's value
    results in an integer.
    """

    maximum: Optional[float] = None
    """
    The value of "maximum" MUST be a number, representing an upper limit
    for a numeric instance.
    
    If the instance is a number, then this keyword validates if
    "exclusiveMaximum" is true and instance is less than the provided
    value, or else if the instance is less than or exactly equal to the
    provided value.
    """

    exclusiveMaximum: Optional[bool] = None
    """
    The value of "exclusiveMaximum" MUST be a boolean, representing
    whether the limit in "maximum" is exclusive or not.  An undefined
    value is the same as false.
    
    If "exclusiveMaximum" is true, then a numeric instance SHOULD NOT be
    equal to the value specified in "maximum".  If "exclusiveMaximum" is
    false (or not specified), then a numeric instance MAY be equal to the
    value of "maximum".
    """

    minimum: Optional[float] = None
    """
    The value of "minimum" MUST be a number, representing a lower limit
    for a numeric instance.
    
    If the instance is a number, then this keyword validates if
    "exclusiveMinimum" is true and instance is greater than the provided
    value, or else if the instance is greater than or exactly equal to
    the provided value.
    """

    exclusiveMinimum: Optional[bool] = None
    """
    The value of "exclusiveMinimum" MUST be a boolean, representing
    whether the limit in "minimum" is exclusive or not.  An undefined
    value is the same as false.
    
    If "exclusiveMinimum" is true, then a numeric instance SHOULD NOT be
    equal to the value specified in "minimum".  If "exclusiveMinimum" is
    false (or not specified), then a numeric instance MAY be equal to the
    value of "minimum".
    """

    maxLength: Optional[int] = Field(default=None, ge=0)
    """
    The value of this keyword MUST be a non-negative integer.

    The value of this keyword MUST be an integer.  This integer MUST be
    greater than, or equal to, 0.
    
    A string instance is valid against this keyword if its length is less
    than, or equal to, the value of this keyword.
    
    The length of a string instance is defined as the number of its
    characters as defined by RFC 7159 [RFC7159].
    """

    minLength: Optional[int] = Field(default=None, ge=0)
    """
    A string instance is valid against this keyword if its length is
    greater than, or equal to, the value of this keyword.
    
    The length of a string instance is defined as the number of its
    characters as defined by RFC 7159 [RFC7159].
    
    The value of this keyword MUST be an integer.  This integer MUST be
    greater than, or equal to, 0.
    
    "minLength", if absent, may be considered as being present with
    integer value 0.
    """

    pattern: Optional[str] = None
    """
    The value of this keyword MUST be a string.  This string SHOULD be a
    valid regular expression, according to the ECMA 262 regular
    expression dialect.
    
    A string instance is considered valid if the regular expression
    matches the instance successfully.  Recall: regular expressions are
    not implicitly anchored.
    """

    maxItems: Optional[int] = Field(default=None, ge=0)
    """
    The value of this keyword MUST be an integer.  This integer MUST be
    greater than, or equal to, 0.
    
    An array instance is valid against "maxItems" if its size is less
    than, or equal to, the value of this keyword.
    """

    minItems: Optional[int] = Field(default=None, ge=0)
    """
    The value of this keyword MUST be an integer.  This integer MUST be
    greater than, or equal to, 0.
    
    An array instance is valid against "minItems" if its size is greater
    than, or equal to, the value of this keyword.
    
    If this keyword is not present, it may be considered present with a
    value of 0.
    """

    uniqueItems: Optional[bool] = None
    """
    The value of this keyword MUST be a boolean.

    If this keyword has boolean value false, the instance validates
    successfully.  If it has boolean value true, the instance validates
    successfully if all of its elements are unique.
    
    If not present, this keyword may be considered present with boolean
    value false.
    """

    maxProperties: Optional[int] = Field(default=None, ge=0)
    """
    The value of this keyword MUST be an integer.  This integer MUST be
    greater than, or equal to, 0.
    
    An object instance is valid against "maxProperties" if its number of
    properties is less than, or equal to, the value of this keyword.
    """

    minProperties: Optional[int] = Field(default=None, ge=0)
    """
    The value of this keyword MUST be an integer.  This integer MUST be
    greater than, or equal to, 0.
    
    An object instance is valid against "minProperties" if its number of
    properties is greater than, or equal to, the value of this keyword.
    
    If this keyword is not present, it may be considered present with a
    value of 0.
    """

    required: Optional[List[str]] = Field(default=None, **min_length_arg(1))
    """
    The value of this keyword MUST be an array.  This array MUST have at
    least one element.  Elements of this array MUST be strings, and MUST
    be unique.
    
    An object instance is valid against this keyword if its property set
    contains all elements in this keyword's array value.
    """

    enum: Optional[List[Any]] = Field(default=None, **min_length_arg(1))
    """
    The value of this keyword MUST be an array.  This array SHOULD have
    at least one element.  Elements in the array SHOULD be unique.
    
    Elements in the array MAY be of any type, including null.
    
    An instance validates successfully against this keyword if its value
    is equal to one of the elements in this keyword's array value.
    """

    """
    The following properties are taken from the JSON Schema definition
    but their definitions were adjusted to the OpenAPI Specification.
    """

    type: Optional[DataType] = None
    """
    **From OpenAPI spec:
    Value MUST be a string. Multiple types via an array are not supported.**
    
    From JSON Schema:
    The value of this keyword MUST be either a string or an array.  If it
    is an array, elements of the array MUST be strings and MUST be
    unique.
    
    String values MUST be one of the seven primitive types defined by the
    core specification.
    
    An instance matches successfully if its primitive type is one of the
    types defined by keyword.  Recall: "number" includes "integer".
    """

    allOf: Optional[List[Union[Reference, "Schema"]]] = None
    """
    **From OpenAPI spec:
    Inline or referenced schema MUST be of a [Schema Object](#schemaObject) and not a 
    standard JSON Schema.**
    
    From JSON Schema:
    This keyword's value MUST be an array.  This array MUST have at least
    one element.
    
    Elements of the array MUST be objects.  Each object MUST be a valid
    JSON Schema.
    
    An instance validates successfully against this keyword if it
    validates successfully against all schemas defined by this keyword's
    value.
    """

    oneOf: Optional[List[Union[Reference, "Schema"]]] = None
    """
    **From OpenAPI spec:
    Inline or referenced schema MUST be of a [Schema Object](#schemaObject) and not a 
    standard JSON Schema.**
    
    From JSON Schema:
    This keyword's value MUST be an array.  This array MUST have at least
    one element.
    
    Elements of the array MUST be objects.  Each object MUST be a valid
    JSON Schema.
    
    An instance validates successfully against this keyword if it
    validates successfully against exactly one schema defined by this
    keyword's value.
    """

    anyOf: Optional[List[Union[Reference, "Schema"]]] = None
    """
    **From OpenAPI spec:
    Inline or referenced schema MUST be of a [Schema Object](#schemaObject) and not a 
    standard JSON Schema.**
    
    From JSON Schema:
    This keyword's value MUST be an array.  This array MUST have at least
    one element.
    
    Elements of the array MUST be objects.  Each object MUST be a valid
    JSON Schema.
    
    An instance validates successfully against this keyword if it
    validates successfully against at least one schema defined by this
    keyword's value.
    """

    schema_not: Optional[Union[Reference, "Schema"]] = Field(default=None, alias="not")
    """
    **From OpenAPI spec:
    Inline or referenced schema MUST be of a [Schema Object](#schemaObject) and not a 
    standard JSON Schema.**
    
    From JSON Schema:
    This keyword's value MUST be an object.  This object MUST be a valid
    JSON Schema.
    
    An instance is valid against this keyword if it fails to validate
    successfully against the schema defined by this keyword.
    """

    items: Optional[Union[Reference, "Schema"]] = None
    """
    **From OpenAPI spec:
    Value MUST be an object and not an array.
    Inline or referenced schema MUST be of a [Schema Object](#schemaObject) and not a 
    standard JSON Schema. `items` MUST be present if the `type` is `array`.**
    
    From JSON Schema:
    The value of "items" MUST be either a schema or array of schemas.

    Successful validation of an array instance with regards to these two
    keywords is determined as follows:
    
    - if "items" is not present, or its value is an object, validation
      of the instance always succeeds, regardless of the value of
      "additionalItems";
    - if the value of "additionalItems" is boolean value true or an
      object, validation of the instance always succeeds;
    - if the value of "additionalItems" is boolean value false and the
      value of "items" is an array, the instance is valid if its size is
      less than, or equal to, the size of "items".
    """

    properties: Optional[Dict[str, Union[Reference, "Schema"]]] = None
    """
    **From OpenAPI spec:
    Property definitions MUST be a [Schema Object](#schemaObject)
    and not a standard JSON Schema (inline or referenced).**
    
    From JSON Schema:
    The value of "properties" MUST be an object.  Each value of this
    object MUST be an object, and each object MUST be a valid JSON
    Schema.
    
    If absent, it can be considered the same as an empty object.
    """

    additionalProperties: Optional[Union[bool, Reference, "Schema"]] = None
    """
    **From OpenAPI spec:
    Value can be boolean or object.
    Inline or referenced schema MUST be of a [Schema Object](#schemaObject) and not a 
    standard JSON Schema.
    Consistent with JSON Schema, `additionalProperties` defaults to `true`.**
    
    From JSON Schema:
    The value of "additionalProperties" MUST be a boolean or a schema.

    If "additionalProperties" is absent, it may be considered present
    with an empty schema as a value.
    
    If "additionalProperties" is true, validation always succeeds.
    
    If "additionalProperties" is false, validation succeeds only if the
    instance is an object and all properties on the instance were covered
    by "properties" and/or "patternProperties".
    
    If "additionalProperties" is an object, validate the value as a
    schema to all of the properties that weren't validated by
    "properties" nor "patternProperties".
    """

    description: Optional[str] = None
    """
    **From OpenAPI spec:
    [CommonMark syntax](https://spec.commonmark.org/) MAY be used for rich text 
    representation.**
    
    From JSON Schema:
    The value "description" MUST be a string.

    The description can be used to decorate a user interface with
    information about the data produced by this user interface.
    The description will provide explanation about the purpose of
    the instance described by this schema.
    """

    schema_format: Optional[str] = Field(default=None, alias="format")
    """
    **From OpenAPI spec:
    [Data Type Formats](#dataTypeFormat) for further details.
    While relying on JSON Schema's defined formats, the OAS offers a few additional 
    predefined formats.**
    
    From JSON Schema:
    Structural validation alone may be insufficient to validate that an
    instance meets all the requirements of an application.  The "format"
    keyword is defined to allow interoperable semantic validation for a
    fixed subset of values which are accurately described by
    authoritative resources, be they RFCs or other external
    specifications.
    
    The value of this keyword is called a format attribute.  It MUST be a
    string.  A format attribute can generally only validate a given set
    of instance types.  If the type of the instance to validate is not in
    this set, validation for this format attribute and instance SHOULD
    succeed.
    """

    default: Optional[Any] = None
    """
    **From OpenAPI spec:
    The default value represents what would be assumed by the consumer of the input
    as the value of the schema if one is not provided.
    Unlike JSON Schema, the value MUST conform to the defined type for the Schema 
    Object defined at the same level. For example, if `type` is `string`, then 
    `default` can be `"foo"` but cannot be `1`.**
    
    From JSON Schema:
    There are no restrictions placed on the value of this keyword.
    
    This keyword can be used to supply a default JSON value associated
    with a particular schema.  It is RECOMMENDED that a default value be
    valid against the associated schema.
    
    This keyword MAY be used in root schemas, and in any subschemas.
    """

    """
    Other than the JSON Schema subset fields, the following fields MAY be used for 
    further schema documentation:
    """

    nullable: Optional[bool] = None
    """
    A `true` value adds `"null"` to the allowed type specified by the `type` keyword,
    only if `type` is explicitly defined within the same Schema Object.
    Other Schema Object constraints retain their defined behavior,
    and therefore may disallow the use of `null` as a value.
    A `false` value leaves the specified or default `type` unmodified.
    The default value is `false`.
    """

    discriminator: Optional[Discriminator] = None
    """
    Adds support for polymorphism.
    The discriminator is an object name that is used to differentiate between other 
    schemas which may satisfy the payload description.
    See [Composition and Inheritance](#schemaComposition) for more details.
    """

    readOnly: Optional[bool] = None
    """
    Relevant only for Schema `"properties"` definitions.
    Declares the property as "read only".
    This means that it MAY be sent as part of a response but SHOULD NOT be sent as part 
    of the request. If the property is marked as `readOnly` being `true` and is in the 
    `required` list, the `required` will take effect on the response only.
    A property MUST NOT be marked as both `readOnly` and `writeOnly` being `true`.
    Default value is `false`.
    """

    writeOnly: Optional[bool] = None
    """
    Relevant only for Schema `"properties"` definitions.
    Declares the property as "write only".
    Therefore, it MAY be sent as part of a request but SHOULD NOT be sent as part of 
    the response. If the property is marked as `writeOnly` being `true` and is in the 
    `required` list, the `required` will take effect on the request only.
    A property MUST NOT be marked as both `readOnly` and `writeOnly` being `true`.
    Default value is `false`.
    """

    xml: Optional[XML] = None
    """
    This MAY be used only on properties schemas.
    It has no effect on root schemas.
    Adds additional metadata to describe the XML representation of this property.
    """

    externalDocs: Optional[ExternalDocumentation] = None
    """
    Additional external documentation for this schema.
    """

    example: Optional[Any] = None
    """
    A free-form property to include an example of an instance for this schema.
    To represent examples that cannot be naturally represented in JSON or YAML,
    a string value can be used to contain the example with escaping where necessary.
    """

    deprecated: Optional[bool] = None
    """ 
    Specifies that a schema is deprecated and SHOULD be transitioned out of usage.
    Default value is `false`.
    """

    if PYDANTIC_V2:
        model_config = ConfigDict(
            extra="allow",
            populate_by_name=True,
            json_schema_extra={"examples": _examples},
        )

    else:

        class Config:
            extra = Extra.allow
            allow_population_by_field_name = True
            schema_extra = {"examples": _examples}


if TYPE_CHECKING:

    def schema_validate(
        obj: Any,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Schema: ...

elif PYDANTIC_V2:
    schema_validate = Schema.model_validate

else:
    schema_validate = Schema.parse_obj
