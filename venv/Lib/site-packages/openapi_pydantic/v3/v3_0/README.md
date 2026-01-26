# OpenAPI v3.0 schema classes

## Alias

Due to the reserved words in python and pydantic,
the following fields are used with [alias](https://pydantic-docs.helpmanual.io/usage/schema/#field-customisation) feature provided by pydantic:

| Class | Field name in the class | Alias (as in OpenAPI spec) |
| ----- | ----------------------- | -------------------------- |
| Header[*](#header_param_in) | param_in | in |
| MediaType | media_type_schema | schema |
| Parameter | param_in | in |
| Parameter | param_schema | schema |
| PathItem | ref | $ref |
| Reference | ref | $ref |
| SecurityScheme | security_scheme_in | in |
| Schema | schema_format | format |
| Schema | schema_not | not |

> <a name="header_param_in"></a>The "in" field in Header object is actually a constant (`{"in": "header"}`).

> For convenience of object creation, the classes mentioned in above
> have configured `allow_population_by_field_name=True` (Pydantic V1) or `populate_by_name=True` (Pydantic V2).
>
> Reference: [Pydantic's Model Config](https://pydantic-docs.helpmanual.io/usage/model_config/)

## Non-pydantic schema types

Due to the constriants of python typing structure (not able to handle dynamic field names),
the following schema classes are actually just a typing of `Dict`:

| Schema Type | Implementation |
| ----------- | -------------- |
| Callback | `Callback = Dict[str, PathItem]` |
| Paths | `Paths = Dict[str, PathItem]` |
| Responses | `Responses = Dict[str, Union[Response, Reference]]` |
| SecurityRequirement | `SecurityRequirement = Dict[str, List[str]]` |

On creating such schema instances, please use python's `dict` type instead to instantiate.
