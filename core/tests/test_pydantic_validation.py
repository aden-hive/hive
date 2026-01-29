"""
Tests for Pydantic validation of LLM outputs.

Tests the new output_model feature in NodeSpec that allows
validating LLM responses against Pydantic models.
"""

from pydantic import BaseModel, Field

from framework.graph.node import NodeResult, NodeSpec
from framework.graph.validator import OutputValidator, ValidationResult


# Test Pydantic models
class SimpleOutput(BaseModel):
    """Simple test model."""

    message: str
    count: int


class ComplexOutput(BaseModel):
    """Complex test model with nested types."""

    query: str
    results: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class TicketAnalysis(BaseModel):
    """Realistic use case model."""

    category: str
    priority: int = Field(ge=1, le=5)
    summary: str = Field(min_length=10)
    suggested_action: str


class TestNodeSpecOutputModel:
    """Tests for output_model field in NodeSpec."""

    def test_nodespec_accepts_output_model(self):
        """NodeSpec should accept a Pydantic model class."""
        node = NodeSpec(
            id="test_node",
            name="Test Node",
            description="A test node",
            node_type="llm_generate",
            output_model=SimpleOutput,
        )

        assert node.output_model == SimpleOutput
        assert node.max_validation_retries == 2  # default

    def test_nodespec_output_model_optional(self):
        """output_model should be optional (None by default)."""
        node = NodeSpec(
            id="test_node",
            name="Test Node",
            description="A test node",
        )

        assert node.output_model is None

    def test_nodespec_custom_validation_retries(self):
        """Should support custom max_validation_retries."""
        node = NodeSpec(
            id="test_node",
            name="Test Node",
            description="A test node",
            output_model=SimpleOutput,
            max_validation_retries=5,
        )

        assert node.max_validation_retries == 5


class TestOutputValidatorPydantic:
    """Tests for validate_with_pydantic method."""

    def test_validate_valid_output(self):
        """Should pass for valid output matching model."""
        validator = OutputValidator()
        output = {"message": "Hello", "count": 5}

        result, validated = validator.validate_with_pydantic(output, SimpleOutput)

        assert result.success is True
        assert len(result.errors) == 0
        assert validated is not None
        assert validated.message == "Hello"
        assert validated.count == 5

    def test_validate_missing_required_field(self):
        """Should fail when required field is missing."""
        validator = OutputValidator()
        output = {"message": "Hello"}  # missing 'count'

        result, validated = validator.validate_with_pydantic(output, SimpleOutput)

        assert result.success is False
        assert len(result.errors) > 0
        assert "count" in result.errors[0]
        assert validated is None

    def test_validate_wrong_type(self):
        """Should fail when field has wrong type."""
        validator = OutputValidator()
        output = {"message": "Hello", "count": "five"}  # count should be int

        result, validated = validator.validate_with_pydantic(output, SimpleOutput)

        assert result.success is False
        assert len(result.errors) > 0
        assert validated is None

    def test_validate_complex_model(self):
        """Should validate complex nested models."""
        validator = OutputValidator()
        output = {
            "query": "test query",
            "results": ["result1", "result2"],
            "confidence": 0.85,
            "metadata": {"source": "test"},
        }

        result, validated = validator.validate_with_pydantic(output, ComplexOutput)

        assert result.success is True
        assert validated is not None
        assert validated.query == "test query"
        assert len(validated.results) == 2
        assert validated.confidence == 0.85

    def test_validate_field_constraints(self):
        """Should validate field constraints (min_length, ge, le, etc.)."""
        validator = OutputValidator()

        # Empty results list (violates min_length=1)
        output = {
            "query": "test",
            "results": [],  # should have at least 1 item
            "confidence": 0.5,
        }

        result, validated = validator.validate_with_pydantic(output, ComplexOutput)

        assert result.success is False
        assert "results" in result.error

    def test_validate_range_constraints(self):
        """Should validate range constraints (ge, le)."""
        validator = OutputValidator()

        # Confidence out of range
        output = {
            "query": "test",
            "results": ["r1"],
            "confidence": 1.5,  # should be <= 1
        }

        result, validated = validator.validate_with_pydantic(output, ComplexOutput)

        assert result.success is False
        assert "confidence" in result.error

    def test_validate_realistic_model(self):
        """Should work with realistic use case models."""
        validator = OutputValidator()

        output = {
            "category": "Technical Support",
            "priority": 3,
            "summary": "User is experiencing login issues with error 401",
            "suggested_action": "Reset password and verify account status",
        }

        result, validated = validator.validate_with_pydantic(output, TicketAnalysis)

        assert result.success is True
        assert validated is not None
        assert validated.category == "Technical Support"
        assert validated.priority == 3


class TestValidationFeedback:
    """Tests for format_validation_feedback method."""

    def test_format_feedback_includes_errors(self):
        """Feedback should include validation errors."""
        validator = OutputValidator()
        output = {"message": "Hello"}  # missing count

        result, _ = validator.validate_with_pydantic(output, SimpleOutput)
        feedback = validator.format_validation_feedback(result, SimpleOutput)

        assert "validation errors" in feedback.lower()
        assert "count" in feedback
        assert "SimpleOutput" in feedback

    def test_format_feedback_includes_schema(self):
        """Feedback should include expected schema information."""
        validator = OutputValidator()
        result = ValidationResult(success=False, errors=["test error"])

        feedback = validator.format_validation_feedback(result, SimpleOutput)

        assert "message" in feedback
        assert "count" in feedback
        assert "required" in feedback.lower()


class TestNodeResultValidationErrors:
    """Tests for validation_errors field in NodeResult."""

    def test_noderesult_includes_validation_errors(self):
        """NodeResult should store validation errors."""
        result = NodeResult(
            success=False,
            error="Pydantic validation failed",
            validation_errors=["count: field required", "priority: must be >= 1"],
        )

        assert len(result.validation_errors) == 2
        assert "count" in result.validation_errors[0]

    def test_noderesult_empty_validation_errors_by_default(self):
        """validation_errors should be empty list by default."""
        result = NodeResult(success=True, output={"key": "value"})

        assert result.validation_errors == []


# Integration-style tests
class TestPydanticValidationIntegration:
    """Integration tests for Pydantic validation in node execution."""

    def test_nodespec_serialization_with_output_model(self):
        """NodeSpec with output_model should serialize correctly."""
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test node",
            output_model=SimpleOutput,
        )

        # model_dump should work (Pydantic serialization)
        dumped = node.model_dump()
        assert "output_model" in dumped
        # The model class itself is stored, not serialized
        assert dumped["output_model"] == SimpleOutput


# Phase 3: JSON Schema Generation Tests
class TestJSONSchemaGeneration:
    """Tests for auto-generating JSON schema from Pydantic model."""

    def test_simple_model_schema_generation(self):
        """Should generate correct JSON schema for simple model."""
        schema = SimpleOutput.model_json_schema()

        assert "properties" in schema
        assert "message" in schema["properties"]
        assert "count" in schema["properties"]
        assert schema["properties"]["message"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"

    def test_complex_model_schema_generation(self):
        """Should generate correct JSON schema for complex model."""
        schema = ComplexOutput.model_json_schema()

        assert "properties" in schema
        assert "query" in schema["properties"]
        assert "results" in schema["properties"]
        assert "confidence" in schema["properties"]
        # Check constraints are in schema
        conf_props = schema["properties"]["confidence"]
        assert "minimum" in conf_props or "exclusiveMinimum" in conf_props

    def test_schema_includes_required_fields(self):
        """JSON schema should include required fields."""
        schema = SimpleOutput.model_json_schema()

        assert "required" in schema
        assert "message" in schema["required"]
        assert "count" in schema["required"]

    def test_schema_can_be_used_in_response_format(self):
        """Schema should be usable in LLM response_format parameter."""
        schema = TicketAnalysis.model_json_schema()

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": TicketAnalysis.__name__,
                "schema": schema,
                "strict": True,
            },
        }

        # Should be valid structure
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["name"] == "TicketAnalysis"
        assert "properties" in response_format["json_schema"]["schema"]


# Phase 2: Retry with Feedback Tests
class TestRetryWithFeedback:
    """Tests for retry-with-feedback functionality."""

    def test_validation_feedback_format(self):
        """Feedback should be properly formatted for LLM retry."""
        validator = OutputValidator()
        output = {"priority": 10}  # Invalid: missing fields and priority > 5

        result, _ = validator.validate_with_pydantic(output, TicketAnalysis)
        feedback = validator.format_validation_feedback(result, TicketAnalysis)

        # Should include error details
        assert "ERRORS:" in feedback
        assert "EXPECTED SCHEMA:" in feedback
        assert "TicketAnalysis" in feedback
        # Should mention missing required fields
        assert "category" in feedback or "summary" in feedback

    def test_feedback_mentions_fix_instruction(self):
        """Feedback should include instruction to fix errors."""
        validator = OutputValidator()
        result = ValidationResult(success=False, errors=["test error"])

        feedback = validator.format_validation_feedback(result, SimpleOutput)

        assert "fix" in feedback.lower() or "valid JSON" in feedback

    def test_max_validation_retries_default(self):
        """Default max_validation_retries should be 2."""
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test node",
            output_model=SimpleOutput,
        )

        assert node.max_validation_retries == 2

    def test_max_validation_retries_customizable(self):
        """max_validation_retries should be customizable."""
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test node",
            output_model=SimpleOutput,
            max_validation_retries=5,
        )

        assert node.max_validation_retries == 5

    def test_zero_retries_allowed(self):
        """Should allow 0 retries (immediate failure on validation error)."""
        node = NodeSpec(
            id="test",
            name="Test",
            description="Test node",
            output_model=SimpleOutput,
            max_validation_retries=0,
        )

        assert node.max_validation_retries == 0

    def test_feedback_includes_all_error_types(self):
        """Feedback should include various error types."""
        validator = OutputValidator()

        # Create output with multiple errors
        output = {
            "category": "X",  # too short if there was min_length
            "priority": 10,  # out of range (should be 1-5)
            "summary": "short",  # too short (min_length=10)
            # missing suggested_action
        }

        result, _ = validator.validate_with_pydantic(output, TicketAnalysis)
        feedback = validator.format_validation_feedback(result, TicketAnalysis)

        # Should contain error details
        assert "ERRORS:" in feedback
        # Should list multiple errors
        assert result.errors is not None
        assert len(result.errors) >= 1


# Extended Integration Tests
class TestPydanticValidationIntegrationExtended:
    """Extended integration tests for the complete validation flow."""

    def test_nodespec_with_all_validation_options(self):
        """NodeSpec should accept all validation-related options."""
        node = NodeSpec(
            id="full_test",
            name="Full Validation Test",
            description="Tests all validation options",
            node_type="llm_generate",
            output_keys=["category", "priority", "summary", "suggested_action"],
            output_model=TicketAnalysis,
            max_validation_retries=3,
        )

        assert node.output_model == TicketAnalysis
        assert node.max_validation_retries == 3
        assert len(node.output_keys) == 4

    def test_validator_preserves_model_defaults(self):
        """Validated model should preserve default values."""
        validator = OutputValidator()

        # metadata has a default (default_factory=dict)
        output = {
            "query": "test",
            "results": ["r1"],
            "confidence": 0.5,
            # metadata not provided, should use default
        }

        result, validated = validator.validate_with_pydantic(output, ComplexOutput)

        assert result.success is True
        assert validated.metadata == {}  # default value

    def test_validation_result_error_property(self):
        """ValidationResult.error should combine all errors."""
        result = ValidationResult(success=False, errors=["error1", "error2", "error3"])

        error_str = result.error

        assert "error1" in error_str
        assert "error2" in error_str
        assert "error3" in error_str
        assert "; " in error_str  # errors joined with "; "
