"""
Comprehensive test suite for HITL (Human-In-The-Loop) Protocol.

Tests the HITLProtocol module which handles critical human-agent interaction:
- Request creation and serialization
- Response parsing (with and without LLM)
- Display formatting for CLI
- Edge cases and error handling

This is a user-facing module where bugs directly impact UX.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from framework.graph.hitl import (
    HITLInputType,
    HITLProtocol,
    HITLQuestion,
    HITLRequest,
    HITLResponse,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def simple_question() -> HITLQuestion:
    """Create a simple free-text question."""
    return HITLQuestion(
        id="q1",
        question="What is the topic of your research?",
        input_type=HITLInputType.FREE_TEXT,
    )


@pytest.fixture
def selection_question() -> HITLQuestion:
    """Create a selection question with options."""
    return HITLQuestion(
        id="q2",
        question="Choose an analysis approach:",
        input_type=HITLInputType.SELECTION,
        options=["Deep Analysis", "Quick Summary", "Skip"],
        help_text="Select based on time available",
    )


@pytest.fixture
def structured_question() -> HITLQuestion:
    """Create a structured question with fields."""
    return HITLQuestion(
        id="q3",
        question="Provide search parameters:",
        input_type=HITLInputType.STRUCTURED,
        fields={"keywords": "Search keywords", "date_range": "Date range to search"},
        required=True,
    )


@pytest.fixture
def approval_question() -> HITLQuestion:
    """Create an approval question."""
    return HITLQuestion(
        id="q4",
        question="Approve the generated report?",
        input_type=HITLInputType.APPROVAL,
        options=["Yes", "No", "Modify"],
    )


@pytest.fixture
def multi_question_request(
    simple_question: HITLQuestion,
    selection_question: HITLQuestion,
) -> HITLRequest:
    """Create a request with multiple questions."""
    return HITLRequest(
        objective="Gather research parameters",
        current_state="Initial data collection",
        questions=[simple_question, selection_question],
        missing_info=["Topic area", "Depth preference"],
        instructions="Please answer all questions to proceed",
        examples=["Example: 'machine learning' for topic"],
        request_id="req-001",
        node_id="gather-input",
    )


# =============================================================================
# Test HITLInputType Enum
# =============================================================================


class TestHITLInputType:
    """Test HITLInputType enum values and behavior."""

    def test_all_input_types_exist(self):
        """Verify all expected input types are defined."""
        assert HITLInputType.FREE_TEXT == "free_text"
        assert HITLInputType.STRUCTURED == "structured"
        assert HITLInputType.SELECTION == "selection"
        assert HITLInputType.APPROVAL == "approval"
        assert HITLInputType.MULTI_FIELD == "multi_field"

    def test_input_type_is_string_enum(self):
        """HITLInputType should be a string enum for JSON serialization."""
        assert isinstance(HITLInputType.FREE_TEXT.value, str)
        assert str(HITLInputType.FREE_TEXT) == "HITLInputType.FREE_TEXT"

    def test_input_type_count(self):
        """Ensure we have exactly 5 input types."""
        assert len(HITLInputType) == 5


# =============================================================================
# Test HITLQuestion Dataclass
# =============================================================================


class TestHITLQuestion:
    """Test HITLQuestion creation and defaults."""

    def test_create_minimal_question(self):
        """Create question with only required fields."""
        q = HITLQuestion(id="q1", question="What is your name?")

        assert q.id == "q1"
        assert q.question == "What is your name?"
        assert q.input_type == HITLInputType.FREE_TEXT  # default
        assert q.options == []
        assert q.fields == {}
        assert q.required is True  # default
        assert q.help_text == ""

    def test_create_selection_question(self, selection_question: HITLQuestion):
        """Create selection question with options."""
        assert selection_question.input_type == HITLInputType.SELECTION
        assert len(selection_question.options) == 3
        assert "Deep Analysis" in selection_question.options

    def test_create_structured_question(self, structured_question: HITLQuestion):
        """Create structured question with fields."""
        assert structured_question.input_type == HITLInputType.STRUCTURED
        assert "keywords" in structured_question.fields
        assert "date_range" in structured_question.fields

    def test_question_with_help_text(self, selection_question: HITLQuestion):
        """Question can have help text."""
        assert selection_question.help_text == "Select based on time available"

    def test_optional_question(self):
        """Create optional question."""
        q = HITLQuestion(
            id="opt1",
            question="Additional notes?",
            required=False,
        )
        assert q.required is False


# =============================================================================
# Test HITLRequest Creation (6 tests as per issue)
# =============================================================================


class TestHITLRequestCreation:
    """Test HITL request creation and serialization."""

    def test_create_request_with_multiple_choice_options(
        self, selection_question: HITLQuestion
    ):
        """Create request with multiple choice options."""
        request = HITLProtocol.create_request(
            objective="Choose analysis approach",
            questions=[selection_question],
            node_id="analysis-node",
        )

        assert request.objective == "Choose analysis approach"
        assert len(request.questions) == 1
        assert request.questions[0].input_type == HITLInputType.SELECTION
        assert len(request.questions[0].options) == 3

    def test_create_request_with_freeform_input(self, simple_question: HITLQuestion):
        """Create request with freeform input."""
        request = HITLProtocol.create_request(
            objective="Get research topic",
            questions=[simple_question],
            node_id="topic-node",
        )

        assert request.questions[0].input_type == HITLInputType.FREE_TEXT

    def test_create_request_with_context_explanation(
        self, multi_question_request: HITLRequest
    ):
        """Create request with context/explanation."""
        assert multi_question_request.instructions != ""
        assert "answer all questions" in multi_question_request.instructions

    def test_request_serialization_deserialization(
        self, multi_question_request: HITLRequest
    ):
        """Request can be serialized to dict and back."""
        serialized = multi_question_request.to_dict()

        assert isinstance(serialized, dict)
        assert serialized["objective"] == "Gather research parameters"
        assert len(serialized["questions"]) == 2
        assert serialized["questions"][0]["id"] == "q1"

        # Verify JSON serializable
        json_str = json.dumps(serialized)
        parsed = json.loads(json_str)
        assert parsed["objective"] == "Gather research parameters"

    def test_request_with_long_context(self):
        """Create request with long context (>1000 chars)."""
        long_context = "A" * 2000
        question = HITLQuestion(
            id="q1",
            question="Review the context and provide feedback",
            help_text=long_context,
        )

        request = HITLProtocol.create_request(
            objective="Review document",
            questions=[question],
        )

        assert len(request.questions[0].help_text) == 2000

    def test_request_with_code_blocks_in_context(self):
        """Create request with code blocks in context."""
        code_example = """```python
def analyze(data):
    return sum(data) / len(data)
```"""
        request = HITLRequest(
            objective="Review code",
            current_state="Code review",
            instructions=f"Review this code:\n{code_example}",
            questions=[HITLQuestion(id="q1", question="Is this code correct?")],
        )

        assert "```python" in request.instructions
        assert "def analyze" in request.instructions


# =============================================================================
# Test HITLResponse Creation and Parsing (10 tests - Critical Path)
# =============================================================================


class TestHITLResponseParsing:
    """Test response parsing - CRITICAL PATH for user interaction."""

    def test_parse_selection_response_exact_match(
        self, selection_question: HITLQuestion
    ):
        """Parse exact selection response."""
        request = HITLProtocol.create_request(
            objective="Choose approach",
            questions=[selection_question],
        )

        response = HITLProtocol.parse_response(
            raw_input="Deep Analysis",
            request=request,
            use_haiku=False,
        )

        assert response.request_id == request.request_id
        assert response.raw_input == "Deep Analysis"
        # Without LLM, falls back to first question
        assert selection_question.id in response.answers

    def test_parse_freeform_text_response(self, simple_question: HITLQuestion):
        """Parse freeform text response."""
        request = HITLProtocol.create_request(
            objective="Get topic",
            questions=[simple_question],
        )

        response = HITLProtocol.parse_response(
            raw_input="I want to research machine learning applications in healthcare",
            request=request,
            use_haiku=False,
        )

        assert response.answers[simple_question.id] == (
            "I want to research machine learning applications in healthcare"
        )

    def test_parse_response_with_explanation(self, selection_question: HITLQuestion):
        """Parse response that includes explanation."""
        request = HITLProtocol.create_request(
            objective="Choose approach",
            questions=[selection_question],
        )

        response = HITLProtocol.parse_response(
            raw_input="I'll go with Deep Analysis because I need thorough results",
            request=request,
            use_haiku=False,
        )

        # Without LLM, entire response goes to first question
        assert "Deep Analysis" in response.answers[selection_question.id]

    def test_parse_empty_response_returns_empty_answer(
        self, simple_question: HITLQuestion
    ):
        """Empty response should still create valid response object."""
        request = HITLProtocol.create_request(
            objective="Get input",
            questions=[simple_question],
        )

        response = HITLProtocol.parse_response(
            raw_input="",
            request=request,
            use_haiku=False,
        )

        assert response.raw_input == ""
        assert response.answers[simple_question.id] == ""

    def test_parse_response_no_questions(self):
        """Parse response when request has no questions."""
        request = HITLRequest(
            objective="Just confirmation",
            current_state="Waiting",
            questions=[],
        )

        response = HITLProtocol.parse_response(
            raw_input="OK, proceed",
            request=request,
            use_haiku=False,
        )

        assert response.raw_input == "OK, proceed"
        assert response.answers == {}

    def test_parse_multiline_response(self, simple_question: HITLQuestion):
        """Parse multiline response."""
        request = HITLProtocol.create_request(
            objective="Get details",
            questions=[simple_question],
        )

        multiline_input = """First line of my response.
Second line with more details.
Third line with conclusion."""

        response = HITLProtocol.parse_response(
            raw_input=multiline_input,
            request=request,
            use_haiku=False,
        )

        assert "First line" in response.answers[simple_question.id]
        assert "Third line" in response.answers[simple_question.id]

    def test_parse_response_preserves_request_id(
        self, multi_question_request: HITLRequest
    ):
        """Response should preserve request ID for correlation."""
        response = HITLProtocol.parse_response(
            raw_input="test response",
            request=multi_question_request,
            use_haiku=False,
        )

        assert response.request_id == multi_question_request.request_id

    def test_response_serialization(self, simple_question: HITLQuestion):
        """Response can be serialized to dict."""
        request = HITLProtocol.create_request(
            objective="Test",
            questions=[simple_question],
        )

        response = HITLProtocol.parse_response(
            raw_input="test answer",
            request=request,
            use_haiku=False,
        )

        serialized = response.to_dict()
        assert isinstance(serialized, dict)
        assert serialized["raw_input"] == "test answer"
        assert simple_question.id in serialized["answers"]

    def test_parse_response_with_special_characters(
        self, simple_question: HITLQuestion
    ):
        """Parse response with special characters."""
        request = HITLProtocol.create_request(
            objective="Get query",
            questions=[simple_question],
        )

        special_input = 'Search for "machine learning" & AI/ML topics <2024>'

        response = HITLProtocol.parse_response(
            raw_input=special_input,
            request=request,
            use_haiku=False,
        )

        assert response.answers[simple_question.id] == special_input

    def test_parse_response_with_numbers(self, simple_question: HITLQuestion):
        """Parse response with numbers and numeric content."""
        request = HITLProtocol.create_request(
            objective="Get count",
            questions=[simple_question],
        )

        response = HITLProtocol.parse_response(
            raw_input="I need 100 results from the past 30 days",
            request=request,
            use_haiku=False,
        )

        assert "100" in response.answers[simple_question.id]
        assert "30" in response.answers[simple_question.id]


# =============================================================================
# Test LLM Parsing Integration (5 tests)
# =============================================================================


class TestHITLLLMParsing:
    """Test LLM-powered parsing integration."""

    def test_fallback_when_api_key_missing(self, simple_question: HITLQuestion):
        """Should fallback to simple parsing when API key missing."""
        request = HITLProtocol.create_request(
            objective="Test",
            questions=[simple_question],
        )

        # Ensure no API key
        with patch.dict(os.environ, {}, clear=True):
            response = HITLProtocol.parse_response(
                raw_input="my answer",
                request=request,
                use_haiku=True,  # Request LLM but key missing
            )

        # Should fallback gracefully
        assert response.answers[simple_question.id] == "my answer"

    def test_fallback_when_use_haiku_false(self, simple_question: HITLQuestion):
        """Should use simple parsing when use_haiku=False."""
        request = HITLProtocol.create_request(
            objective="Test",
            questions=[simple_question],
        )

        response = HITLProtocol.parse_response(
            raw_input="simple answer",
            request=request,
            use_haiku=False,
        )

        assert response.answers[simple_question.id] == "simple answer"

    def test_fallback_on_llm_exception(self, multi_question_request: HITLRequest):
        """Should fallback gracefully on LLM exceptions."""
        import anthropic as anthropic_module

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(
                anthropic_module, "Anthropic", side_effect=Exception("API Error")
            ):
                response = HITLProtocol.parse_response(
                    raw_input="test answer",
                    request=multi_question_request,
                    use_haiku=True,
                )

        # Should fallback to first question
        first_question_id = multi_question_request.questions[0].id
        assert response.answers[first_question_id] == "test answer"

    @pytest.mark.skipif(
        "ANTHROPIC_API_KEY" not in os.environ,
        reason="Requires Anthropic API key for integration test",
    )
    @pytest.mark.integration
    def test_haiku_parses_natural_language(self):
        """Integration test: Haiku parses natural language correctly."""
        question = HITLQuestion(
            id="approach",
            question="Which approach should we use?",
            input_type=HITLInputType.SELECTION,
            options=["Analyze deeply", "Quick summary", "Skip"],
        )

        request = HITLProtocol.create_request(
            objective="Choose approach",
            questions=[question],
        )

        response = HITLProtocol.parse_response(
            raw_input="I think we should analyze this more carefully and thoroughly",
            request=request,
            use_haiku=True,
        )

        # Haiku should understand this maps to "Analyze deeply"
        assert "approach" in response.answers

    def test_llm_parsing_with_mocked_response(
        self, multi_question_request: HITLRequest
    ):
        """Test LLM parsing with mocked Anthropic response."""
        import anthropic as anthropic_module

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"q1": "topic answer", "q2": "Deep Analysis"}')]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(
                anthropic_module, "Anthropic", return_value=mock_client
            ):
                response = HITLProtocol.parse_response(
                    raw_input="I want to research ML, using deep analysis",
                    request=multi_question_request,
                    use_haiku=True,
                )

        assert response.answers.get("q1") == "topic answer"
        assert response.answers.get("q2") == "Deep Analysis"


# =============================================================================
# Test Display Formatting (5 tests)
# =============================================================================


class TestHITLDisplayFormatting:
    """Test display formatting for CLI."""

    def test_format_basic_request(self, simple_question: HITLQuestion):
        """Format a basic request for display."""
        request = HITLProtocol.create_request(
            objective="Get research topic",
            questions=[simple_question],
        )

        formatted = HITLProtocol.format_for_display(request)

        assert "Objective:" in formatted
        assert "Get research topic" in formatted
        assert "Questions" in formatted
        assert "What is the topic" in formatted

    def test_format_with_options(self, selection_question: HITLQuestion):
        """Format request with options."""
        request = HITLProtocol.create_request(
            objective="Choose approach",
            questions=[selection_question],
        )

        formatted = HITLProtocol.format_for_display(request)

        assert "Options:" in formatted
        assert "Deep Analysis" in formatted
        assert "Quick Summary" in formatted
        assert "Skip" in formatted

    def test_format_with_help_text(self, selection_question: HITLQuestion):
        """Format request showing help text."""
        request = HITLProtocol.create_request(
            objective="Choose approach",
            questions=[selection_question],
        )

        formatted = HITLProtocol.format_for_display(request)

        assert "Select based on time" in formatted

    def test_format_with_missing_info(self, multi_question_request: HITLRequest):
        """Format request showing missing information."""
        formatted = HITLProtocol.format_for_display(multi_question_request)

        assert "Missing Information:" in formatted
        assert "Topic area" in formatted
        assert "Depth preference" in formatted

    def test_format_with_examples(self, multi_question_request: HITLRequest):
        """Format request showing examples."""
        formatted = HITLProtocol.format_for_display(multi_question_request)

        assert "Examples:" in formatted
        assert "machine learning" in formatted

    def test_format_multiple_questions(self, multi_question_request: HITLRequest):
        """Format request with multiple questions shows numbering."""
        formatted = HITLProtocol.format_for_display(multi_question_request)

        assert "1." in formatted
        assert "2." in formatted
        assert "Questions (2):" in formatted

    def test_format_empty_request(self):
        """Format minimal request."""
        request = HITLRequest(
            objective="",
            current_state="",
            questions=[],
        )

        formatted = HITLProtocol.format_for_display(request)

        # Should not crash, may be mostly empty
        assert isinstance(formatted, str)


# =============================================================================
# Test Edge Cases (4+ tests)
# =============================================================================


class TestHITLEdgeCases:
    """Test edge cases and error handling."""

    def test_unicode_in_questions_and_responses(self):
        """Handle Unicode characters in questions and responses."""
        question = HITLQuestion(
            id="emoji-q",
            question="Rate your experience: 😊 or 😞?",
            input_type=HITLInputType.SELECTION,
            options=["😊 Great", "😐 Okay", "😞 Poor"],
        )

        request = HITLProtocol.create_request(
            objective="Get feedback",
            questions=[question],
        )

        response = HITLProtocol.parse_response(
            raw_input="😊 Great",
            request=request,
            use_haiku=False,
        )

        assert response.answers["emoji-q"] == "😊 Great"

        formatted = HITLProtocol.format_for_display(request)
        assert "😊" in formatted

    def test_special_characters_in_options(self):
        """Handle special characters (quotes, newlines) in options."""
        question = HITLQuestion(
            id="special-q",
            question="Select query:",
            input_type=HITLInputType.SELECTION,
            options=[
                'Search for "exact phrase"',
                "Query with 'single quotes'",
                "Path/with/slashes",
            ],
        )

        request = HITLProtocol.create_request(
            objective="Select query",
            questions=[question],
        )

        formatted = HITLProtocol.format_for_display(request)
        assert '"exact phrase"' in formatted
        assert "Path/with/slashes" in formatted

    def test_extremely_long_response(self, simple_question: HITLQuestion):
        """Handle extremely long response (>10KB)."""
        request = HITLProtocol.create_request(
            objective="Get details",
            questions=[simple_question],
        )

        # 20KB response
        long_response = "A" * 20000

        response = HITLProtocol.parse_response(
            raw_input=long_response,
            request=request,
            use_haiku=False,
        )

        # Should handle without crashing
        assert len(response.raw_input) == 20000
        assert response.answers[simple_question.id] == long_response

    def test_newlines_in_response(self, simple_question: HITLQuestion):
        """Handle newlines and whitespace in response."""
        request = HITLProtocol.create_request(
            objective="Get details",
            questions=[simple_question],
        )

        response = HITLProtocol.parse_response(
            raw_input="\n\n  answer with whitespace  \n\n",
            request=request,
            use_haiku=False,
        )

        # Should preserve whitespace
        assert response.raw_input == "\n\n  answer with whitespace  \n\n"

    def test_request_id_generation(self):
        """Request ID should be deterministically generated."""
        request1 = HITLProtocol.create_request(
            objective="Same objective",
            questions=[],
            node_id="node1",
        )

        request2 = HITLProtocol.create_request(
            objective="Same objective",
            questions=[],
            node_id="node1",
        )

        # Same inputs should produce same request_id
        assert request1.request_id == request2.request_id

    def test_different_node_ids_different_request_ids(self):
        """Different node IDs should produce different request IDs."""
        request1 = HITLProtocol.create_request(
            objective="Same objective",
            questions=[],
            node_id="node1",
        )

        request2 = HITLProtocol.create_request(
            objective="Same objective",
            questions=[],
            node_id="node2",
        )

        assert request1.request_id != request2.request_id

    def test_null_bytes_in_response(self, simple_question: HITLQuestion):
        """Handle null bytes in response."""
        request = HITLProtocol.create_request(
            objective="Get input",
            questions=[simple_question],
        )

        response = HITLProtocol.parse_response(
            raw_input="answer\x00with\x00nulls",
            request=request,
            use_haiku=False,
        )

        # Should handle null bytes
        assert "\x00" in response.raw_input


# =============================================================================
# Test HITLResponse Dataclass
# =============================================================================


class TestHITLResponse:
    """Test HITLResponse dataclass."""

    def test_create_minimal_response(self):
        """Create response with minimal fields."""
        response = HITLResponse(request_id="req-001")

        assert response.request_id == "req-001"
        assert response.answers == {}
        assert response.raw_input == ""
        assert response.response_time_ms == 0

    def test_create_full_response(self):
        """Create response with all fields."""
        response = HITLResponse(
            request_id="req-002",
            answers={"q1": "answer1", "q2": "answer2"},
            raw_input="Full raw input text",
            response_time_ms=1500,
        )

        assert response.request_id == "req-002"
        assert len(response.answers) == 2
        assert response.response_time_ms == 1500

    def test_response_to_dict(self):
        """Response can be converted to dict."""
        response = HITLResponse(
            request_id="req-003",
            answers={"q1": "test"},
            raw_input="test input",
            response_time_ms=500,
        )

        d = response.to_dict()

        assert d["request_id"] == "req-003"
        assert d["answers"]["q1"] == "test"
        assert d["raw_input"] == "test input"
        assert d["response_time_ms"] == 500


# =============================================================================
# Test Integration Scenarios
# =============================================================================


class TestHITLIntegrationScenarios:
    """Test realistic integration scenarios."""

    def test_full_workflow_without_llm(self):
        """Test complete HITL workflow without LLM."""
        # 1. Create questions
        topic_q = HITLQuestion(
            id="topic",
            question="What topic should we research?",
            input_type=HITLInputType.FREE_TEXT,
        )

        depth_q = HITLQuestion(
            id="depth",
            question="How deep should the analysis be?",
            input_type=HITLInputType.SELECTION,
            options=["Surface level", "Medium", "Deep dive"],
        )

        # 2. Create request
        request = HITLProtocol.create_request(
            objective="Configure research parameters",
            questions=[topic_q, depth_q],
            missing_info=["Research topic", "Analysis depth"],
            node_id="config-node",
        )

        # 3. Format for display
        display = HITLProtocol.format_for_display(request)
        assert "Configure research parameters" in display
        assert "1." in display
        assert "2." in display

        # 4. Parse response
        response = HITLProtocol.parse_response(
            raw_input="Machine learning in healthcare",
            request=request,
            use_haiku=False,
        )

        # 5. Verify response
        assert response.request_id == request.request_id
        assert "topic" in response.answers

        # 6. Serialize for storage
        request_dict = request.to_dict()
        response_dict = response.to_dict()

        assert json.dumps(request_dict)  # Should be JSON serializable
        assert json.dumps(response_dict)

    def test_approval_workflow(self):
        """Test approval-type HITL workflow."""
        approval_q = HITLQuestion(
            id="approve",
            question="Do you approve this action?",
            input_type=HITLInputType.APPROVAL,
            options=["Approve", "Reject", "Modify"],
            help_text="Review the generated content before proceeding",
        )

        request = HITLProtocol.create_request(
            objective="Get approval for generated report",
            questions=[approval_q],
            node_id="approval-gate",
        )

        # User approves
        response = HITLProtocol.parse_response(
            raw_input="Approve",
            request=request,
            use_haiku=False,
        )

        assert response.answers["approve"] == "Approve"

    def test_multi_field_workflow(self):
        """Test multi-field input workflow."""
        multi_q = HITLQuestion(
            id="search-params",
            question="Provide search parameters:",
            input_type=HITLInputType.MULTI_FIELD,
            fields={
                "keywords": "Search keywords",
                "date_from": "Start date",
                "date_to": "End date",
                "max_results": "Maximum results",
            },
        )

        request = HITLProtocol.create_request(
            objective="Configure search",
            questions=[multi_q],
        )

        formatted = HITLProtocol.format_for_display(request)
        assert isinstance(formatted, str)
        assert "search-params" in request.questions[0].id

        # Without LLM, structured parsing would need custom logic
        response = HITLProtocol.parse_response(
            raw_input="keywords: AI, date_from: 2024-01-01, max_results: 100",
            request=request,
            use_haiku=False,
        )

        assert response.raw_input != ""
