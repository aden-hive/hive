"""
Standardized HITL (Human-In-The-Loop) Protocol

This module defines the formal structure for pause/resume interactions
where agents need to gather input from humans.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HITLInputType(str, Enum):
    """Type of input expected from human."""

    FREE_TEXT = "free_text"  # Open-ended text response
    STRUCTURED = "structured"  # Specific fields to fill
    SELECTION = "selection"  # Choose from options
    APPROVAL = "approval"  # Yes/no/modify decision
    MULTI_FIELD = "multi_field"  # Multiple related inputs


@dataclass
class HITLQuestion:
    """A single question to ask the human."""

    id: str
    question: str
    input_type: HITLInputType = HITLInputType.FREE_TEXT

    # For SELECTION type
    options: list[str] = field(default_factory=list)

    # For STRUCTURED type
    fields: dict[str, str] = field(default_factory=dict)  # {field_name: description}

    # Metadata
    required: bool = True
    help_text: str = ""


@dataclass
class HITLRequest:
    """
    Formal request for human input at a pause node.

    This is what the agent produces when it needs human input.
    """

    # Context
    objective: str  # What we're trying to accomplish
    current_state: str  # Where we are in the process

    # What we need
    questions: list[HITLQuestion] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)

    # Guidance
    instructions: str = ""
    examples: list[str] = field(default_factory=list)

    # Metadata
    request_id: str = ""
    node_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "objective": self.objective,
            "current_state": self.current_state,
            "questions": [
                {
                    "id": q.id,
                    "question": q.question,
                    "input_type": q.input_type.value,
                    "options": q.options,
                    "fields": q.fields,
                    "required": q.required,
                    "help_text": q.help_text,
                }
                for q in self.questions
            ],
            "missing_info": self.missing_info,
            "instructions": self.instructions,
            "examples": self.examples,
            "request_id": self.request_id,
            "node_id": self.node_id,
        }


@dataclass
class HITLResponse:
    """
    Human's response to a HITL request.

    This is what gets passed back when resuming from a pause.
    """

    # Original request reference
    request_id: str

    # Human's answers
    answers: dict[str, Any] = field(default_factory=dict)  # {question_id: answer}
    raw_input: str = ""  # Raw text if provided

    # Metadata
    response_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "request_id": self.request_id,
            "answers": self.answers,
            "raw_input": self.raw_input,
            "response_time_ms": self.response_time_ms,
        }


class HITLProtocol:
    """
    Standardized protocol for HITL interactions.

    Usage in pause nodes:

    1. Pause Node: Generates HITLRequest with questions
    2. Executor: Saves state and returns request to user
    3. User: Provides HITLResponse with answers
    4. Resume Node: Processes response and merges into context
    """

    @staticmethod
    def create_request(
        objective: str,
        questions: list[HITLQuestion],
        missing_info: list[str] | None = None,
        node_id: str = "",
    ) -> HITLRequest:
        """Create a standardized HITL request."""
        return HITLRequest(
            objective=objective,
            current_state="Awaiting clarification",
            questions=questions,
            missing_info=missing_info or [],
            request_id=f"{node_id}_{hash(objective) % 10000}",
            node_id=node_id,
        )

    @staticmethod
    def parse_response(
        raw_input: str,
        request: HITLRequest,
        use_haiku: bool = True,
    ) -> HITLResponse:
        """
        Parse human's raw input into structured response.

        Uses Haiku to intelligently extract answers for each question.
        """
        import os

        response = HITLResponse(request_id=request.request_id, raw_input=raw_input)

        # If no questions, just return raw input
        if not request.questions:
            return response

        # Try to use Haiku for intelligent parsing
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not use_haiku or not api_key:
            # Simple fallback: treat as answer to first question
            if request.questions:
                response.answers[request.questions[0].id] = raw_input
            return response

        # Use Haiku to extract answers
        try:
            import json

            import anthropic

            questions_str = "\n".join(
                [f"{i + 1}. {q.question} (id: {q.id})" for i, q in enumerate(request.questions)]
            )

            prompt = f"""Parse the user's response and extract answers for each question.

Questions asked:
{questions_str}

User's response:
{raw_input}

Extract the answer for each question. Output JSON with question IDs as keys.

Example format:
{{"question-1": "answer here", "question-2": "answer here"}}"""

            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse Haiku's response
            import re

            response_text = message.content[0].text.strip()
            json_match = re.search(r"\{[^{}]*\}", response_text, re.DOTALL)

            if json_match:
                parsed = json.loads(json_match.group())
                response.answers = parsed

        except Exception:
            # Fallback: use raw input for first question
            if request.questions:
                response.answers[request.questions[0].id] = raw_input

        return response

    @staticmethod
    def format_for_display(request: HITLRequest) -> str:
        """Format HITL request for user-friendly display."""
        parts = []

        if request.objective:
            parts.append(f"📋 Objective: {request.objective}")

        if request.current_state:
            parts.append(f"📍 Current State: {request.current_state}")

        if request.instructions:
            parts.append(f"\n{request.instructions}")

        if request.questions:
            parts.append(f"\n❓ Questions ({len(request.questions)}):")
            for i, q in enumerate(request.questions, 1):
                parts.append(f"{i}. {q.question}")
                if q.help_text:
                    parts.append(f"   💡 {q.help_text}")
                if q.options:
                    parts.append(f"   Options: {', '.join(q.options)}")

        if request.missing_info:
            parts.append("\n📝 Missing Information:")
            for info in request.missing_info:
                parts.append(f"  • {info}")

        if request.examples:
            parts.append("\n📚 Examples:")
            for example in request.examples:
                parts.append(f"  • {example}")

        return "\n".join(parts)
