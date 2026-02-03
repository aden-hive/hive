"""
validation schemas for mcp agent builder tools.

provides pydantic models for validating tool inputs with:
- id format validation (alphanumeric + underscore)
- string length limits
- required field checks
"""

import re

from pydantic import BaseModel, Field, field_validator

# max lengths for various string inputs
MAX_ID_LENGTH = 64
MAX_NAME_LENGTH = 128
MAX_DESCRIPTION_LENGTH = 2048
MAX_PROMPT_LENGTH = 16384
MAX_JSON_LENGTH = 32768


def validate_id_format(value: str, field_name: str = "id") -> str:
    """
    validate that an id is alphanumeric with underscores and hyphens only.

    this prevents injection attacks and ensures consistent id formatting.
    """
    if not value:
        raise ValueError(f"{field_name} cannot be empty")

    if len(value) > MAX_ID_LENGTH:
        raise ValueError(f"{field_name} exceeds max length of {MAX_ID_LENGTH}")

    # allow alphanumeric, underscores, hyphens
    pattern = r"^[a-zA-Z][a-zA-Z0-9_-]*$"
    if not re.match(pattern, value):
        raise ValueError(
            f"{field_name} must start with a letter and contain only "
            f"alphanumeric characters, underscores, and hyphens"
        )

    return value


class GoalInput(BaseModel):
    """validation model for set_goal inputs."""

    goal_id: str = Field(..., min_length=1, max_length=MAX_ID_LENGTH)
    name: str = Field(..., min_length=1, max_length=MAX_NAME_LENGTH)
    description: str = Field(..., min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    success_criteria: str = Field(..., max_length=MAX_JSON_LENGTH)
    constraints: str = Field(default="[]", max_length=MAX_JSON_LENGTH)

    @field_validator("goal_id")
    @classmethod
    def validate_goal_id(cls, v: str) -> str:
        return validate_id_format(v, "goal_id")

    @field_validator("success_criteria", "constraints")
    @classmethod
    def validate_json_string(cls, v: str) -> str:
        # just check its valid json format (brackets)
        v = v.strip()
        if v and not (v.startswith("[") or v.startswith("{")):
            raise ValueError("must be a JSON array or object")
        return v


class NodeInput(BaseModel):
    """validation model for add_node inputs."""

    node_id: str = Field(..., min_length=1, max_length=MAX_ID_LENGTH)
    name: str = Field(..., min_length=1, max_length=MAX_NAME_LENGTH)
    description: str = Field(..., min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    node_type: str = Field(..., min_length=1, max_length=32)
    input_keys: str = Field(default="[]", max_length=MAX_JSON_LENGTH)
    output_keys: str = Field(default="[]", max_length=MAX_JSON_LENGTH)
    system_prompt: str = Field(default="", max_length=MAX_PROMPT_LENGTH)
    tools: str = Field(default="[]", max_length=MAX_JSON_LENGTH)
    routes: str = Field(default="{}", max_length=MAX_JSON_LENGTH)

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, v: str) -> str:
        return validate_id_format(v, "node_id")

    @field_validator("node_type")
    @classmethod
    def validate_node_type(cls, v: str) -> str:
        allowed_types = ["llm_generate", "llm_tool_use", "router", "function"]
        if v not in allowed_types:
            raise ValueError(f"node_type must be one of: {allowed_types}")
        return v


class EdgeInput(BaseModel):
    """validation model for add_edge inputs."""

    edge_id: str = Field(..., min_length=1, max_length=MAX_ID_LENGTH)
    source: str = Field(..., min_length=1, max_length=MAX_ID_LENGTH)
    target: str = Field(..., min_length=1, max_length=MAX_ID_LENGTH)
    condition: str = Field(default="on_success", max_length=32)
    condition_expr: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)
    priority: int = Field(default=0, ge=-1000, le=1000)

    @field_validator("edge_id")
    @classmethod
    def validate_edge_id(cls, v: str) -> str:
        return validate_id_format(v, "edge_id")

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        return validate_id_format(v, "source")

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        return validate_id_format(v, "target")

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, v: str) -> str:
        allowed = ["always", "on_success", "on_failure", "conditional", "llm_decide"]
        if v not in allowed:
            raise ValueError(f"condition must be one of: {allowed}")
        return v


class SessionInput(BaseModel):
    """validation model for create_session inputs."""

    name: str = Field(..., min_length=1, max_length=MAX_NAME_LENGTH)


class SuccessCriterionInput(BaseModel):
    """validation model for success criteria objects."""

    id: str = Field(..., min_length=1, max_length=MAX_ID_LENGTH)
    description: str = Field(..., min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    metric: str = Field(default="", max_length=MAX_NAME_LENGTH)
    target: str = Field(default="", max_length=MAX_NAME_LENGTH)
    weight: float = Field(default=1.0, ge=0.0, le=100.0)

    @field_validator("id")
    @classmethod
    def validate_criterion_id(cls, v: str) -> str:
        return validate_id_format(v, "criterion_id")


class ConstraintInput(BaseModel):
    """validation model for constraint objects."""

    id: str = Field(..., min_length=1, max_length=MAX_ID_LENGTH)
    description: str = Field(..., min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    constraint_type: str = Field(default="hard", max_length=32)
    category: str = Field(default="safety", max_length=64)
    check: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)

    @field_validator("id")
    @classmethod
    def validate_constraint_id(cls, v: str) -> str:
        return validate_id_format(v, "constraint_id")

    @field_validator("constraint_type")
    @classmethod
    def validate_constraint_type(cls, v: str) -> str:
        allowed = ["hard", "soft"]
        if v not in allowed:
            raise ValueError(f"constraint_type must be one of: {allowed}")
        return v


def validate_goal_input(
    goal_id: str,
    name: str,
    description: str,
    success_criteria: str,
    constraints: str = "[]",
) -> tuple[bool, list[str]]:
    """
    validate goal input parameters.

    returns (is_valid, list of error messages)
    """
    errors = []

    try:
        GoalInput(
            goal_id=goal_id,
            name=name,
            description=description,
            success_criteria=success_criteria,
            constraints=constraints,
        )
    except Exception as e:
        errors.append(str(e))

    return len(errors) == 0, errors


def validate_node_input(
    node_id: str,
    name: str,
    description: str,
    node_type: str,
    input_keys: str = "[]",
    output_keys: str = "[]",
    system_prompt: str = "",
    tools: str = "[]",
    routes: str = "{}",
) -> tuple[bool, list[str]]:
    """
    validate node input parameters.

    returns (is_valid, list of error messages)
    """
    errors = []

    try:
        NodeInput(
            node_id=node_id,
            name=name,
            description=description,
            node_type=node_type,
            input_keys=input_keys,
            output_keys=output_keys,
            system_prompt=system_prompt,
            tools=tools,
            routes=routes,
        )
    except Exception as e:
        errors.append(str(e))

    return len(errors) == 0, errors


def validate_edge_input(
    edge_id: str,
    source: str,
    target: str,
    condition: str = "on_success",
    condition_expr: str = "",
    priority: int = 0,
) -> tuple[bool, list[str]]:
    """
    validate edge input parameters.

    returns (is_valid, list of error messages)
    """
    errors = []

    try:
        EdgeInput(
            edge_id=edge_id,
            source=source,
            target=target,
            condition=condition,
            condition_expr=condition_expr,
            priority=priority,
        )
    except Exception as e:
        errors.append(str(e))

    return len(errors) == 0, errors
