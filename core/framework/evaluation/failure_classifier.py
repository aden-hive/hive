"""Extended failure classification for runtime agent evaluation."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FailureCategory(StrEnum):
    """Failure taxonomy for runtime evaluation.

    Categories map to remediation strategies in the evolution loop.
    """

    # LLM failures
    LLM_HALLUCINATION = "llm_hallucination"
    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_CONTENT_FILTER = "llm_content_filter"
    LLM_INVALID_OUTPUT = "llm_invalid_output"
    LLM_EMPTY_RESPONSE = "llm_empty_response"
    LLM_CONTEXT_OVERFLOW = "llm_context_overflow"

    # Tool failures
    TOOL_API_ERROR = "tool_api_error"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_INVALID_RESPONSE = "tool_invalid_response"
    TOOL_AUTH_FAILURE = "tool_auth_failure"
    TOOL_NOT_FOUND = "tool_not_found"

    # Graph/logic failures
    GRAPH_DEAD_END = "graph_dead_end"
    GRAPH_INFINITE_LOOP = "graph_infinite_loop"
    GRAPH_MISSING_OUTPUT = "graph_missing_output"
    GRAPH_VALIDATION_ERROR = "graph_validation_error"

    # Constraint violations
    CONSTRAINT_COST_EXCEEDED = "constraint_cost_exceeded"
    CONSTRAINT_TIME_EXCEEDED = "constraint_time_exceeded"
    CONSTRAINT_QUALITY_BELOW = "constraint_quality_below"
    CONSTRAINT_SAFETY_VIOLATION = "constraint_safety_violation"

    # Resource failures
    RESOURCE_BUDGET_EXHAUSTED = "resource_budget_exhausted"
    RESOURCE_MEMORY_EXCEEDED = "resource_memory_exceeded"
    RESOURCE_CONCURRENCY_LIMIT = "resource_concurrency_limit"

    UNKNOWN = "unknown"


class FailureRecord(BaseModel):
    """Structured record of a classified failure."""

    category: FailureCategory
    severity: str
    node_id: str | None = None
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    remediation_hint: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}

    @property
    def is_retriable(self) -> bool:
        retriable = {
            FailureCategory.LLM_RATE_LIMIT,
            FailureCategory.LLM_EMPTY_RESPONSE,
            FailureCategory.TOOL_TIMEOUT,
            FailureCategory.TOOL_API_ERROR,
            FailureCategory.RESOURCE_CONCURRENCY_LIMIT,
        }
        return self.category in retriable

    @property
    def requires_graph_change(self) -> bool:
        graph_change = {
            FailureCategory.GRAPH_DEAD_END,
            FailureCategory.GRAPH_INFINITE_LOOP,
            FailureCategory.GRAPH_MISSING_OUTPUT,
            FailureCategory.LLM_HALLUCINATION,
            FailureCategory.CONSTRAINT_QUALITY_BELOW,
        }
        return self.category in graph_change


# Pattern tables for classification

_LLM_PATTERNS: list[tuple[str, FailureCategory]] = [
    (r"rate.?limit|429|too many requests", FailureCategory.LLM_RATE_LIMIT),
    (r"content.?filter|safety|blocked|moderation", FailureCategory.LLM_CONTENT_FILTER),
    (r"empty.?response|no.?content|empty.?stream", FailureCategory.LLM_EMPTY_RESPONSE),
    (r"context.?(length|window|overflow)|too.?many.?tokens", FailureCategory.LLM_CONTEXT_OVERFLOW),
    (r"hallucin|fabricat|made.?up|not.?grounded", FailureCategory.LLM_HALLUCINATION),
    (r"invalid.?json|parse.?error|malformed.?output", FailureCategory.LLM_INVALID_OUTPUT),
]

_TOOL_PATTERNS: list[tuple[str, FailureCategory]] = [
    (r"timeout|timed?.?out|deadline.?exceeded", FailureCategory.TOOL_TIMEOUT),
    (r"auth|unauthorized|403|401|forbidden", FailureCategory.TOOL_AUTH_FAILURE),
    (r"tool.?not.?found|unknown.?tool|no.?such.?tool", FailureCategory.TOOL_NOT_FOUND),
    (r"api.?error|500|502|503|service.?unavailable", FailureCategory.TOOL_API_ERROR),
    (r"invalid.?response|unexpected.?format", FailureCategory.TOOL_INVALID_RESPONSE),
]

_GRAPH_PATTERNS: list[tuple[str, FailureCategory]] = [
    (r"dead.?end|no.?next.?node|terminal.?without", FailureCategory.GRAPH_DEAD_END),
    (r"infinite.?loop|max.?visits|cycle.?detect", FailureCategory.GRAPH_INFINITE_LOOP),
    (r"missing.?output|required.?key|output.?not.?set", FailureCategory.GRAPH_MISSING_OUTPUT),
    (r"validation.?error|schema.?mismatch|pydantic", FailureCategory.GRAPH_VALIDATION_ERROR),
]

_CONSTRAINT_PATTERNS: list[tuple[str, FailureCategory]] = [
    (r"budget|cost.?exceed|spending.?limit", FailureCategory.CONSTRAINT_COST_EXCEEDED),
    (r"time.?exceed|too.?slow|latency.?exceed", FailureCategory.CONSTRAINT_TIME_EXCEEDED),
    (r"quality.?below|accuracy.?below|score.?too.?low", FailureCategory.CONSTRAINT_QUALITY_BELOW),
    (r"safety|pii|sensitive.?data|violation", FailureCategory.CONSTRAINT_SAFETY_VIOLATION),
]

_RESOURCE_PATTERNS: list[tuple[str, FailureCategory]] = [
    (r"budget.?exhaust|no.?budget|funds.?depleted", FailureCategory.RESOURCE_BUDGET_EXHAUSTED),
    (r"memory.?exceed|oom|out.?of.?memory", FailureCategory.RESOURCE_MEMORY_EXCEEDED),
    (r"concurrency|too.?many.?agents|parallel.?limit", FailureCategory.RESOURCE_CONCURRENCY_LIMIT),
]

_ALL_PATTERN_GROUPS = [
    _CONSTRAINT_PATTERNS,
    _RESOURCE_PATTERNS,
    _LLM_PATTERNS,
    _TOOL_PATTERNS,
    _GRAPH_PATTERNS,
]

_SEVERITY_MAP: dict[FailureCategory, str] = {
    FailureCategory.CONSTRAINT_SAFETY_VIOLATION: "critical",
    FailureCategory.RESOURCE_BUDGET_EXHAUSTED: "critical",
    FailureCategory.LLM_HALLUCINATION: "high",
    FailureCategory.GRAPH_INFINITE_LOOP: "high",
    FailureCategory.GRAPH_DEAD_END: "high",
    FailureCategory.CONSTRAINT_COST_EXCEEDED: "high",
    FailureCategory.TOOL_AUTH_FAILURE: "high",
    FailureCategory.LLM_RATE_LIMIT: "low",
    FailureCategory.LLM_EMPTY_RESPONSE: "low",
    FailureCategory.TOOL_TIMEOUT: "low",
}

_HINT_MAP: dict[FailureCategory, str] = {
    FailureCategory.LLM_HALLUCINATION: "Add output validation or grounding check after LLM calls.",
    FailureCategory.LLM_RATE_LIMIT: "Add fallback provider or increase retry backoff.",
    FailureCategory.LLM_CONTENT_FILTER: "Review system prompt; add input sanitization.",
    FailureCategory.LLM_INVALID_OUTPUT: "Add structured output schema or output parsing node.",
    FailureCategory.LLM_EMPTY_RESPONSE: "Retry with different model or check token budget.",
    FailureCategory.LLM_CONTEXT_OVERFLOW: "Implement context compression or split into sub-tasks.",
    FailureCategory.TOOL_API_ERROR: "Add retry with exponential backoff; check endpoint health.",
    FailureCategory.TOOL_TIMEOUT: "Increase timeout or add circuit breaker.",
    FailureCategory.TOOL_INVALID_RESPONSE: "Add response validation and fallback parsing.",
    FailureCategory.TOOL_AUTH_FAILURE: "Refresh credentials or check API key validity.",
    FailureCategory.TOOL_NOT_FOUND: "Register the required tool in mcp_servers.json.",
    FailureCategory.GRAPH_DEAD_END: "Add fallback edge or terminal node for unhandled paths.",
    FailureCategory.GRAPH_INFINITE_LOOP: "Add max_node_visits constraint or convergence check.",
    FailureCategory.GRAPH_MISSING_OUTPUT: "Ensure required output keys are set before terminal.",
    FailureCategory.GRAPH_VALIDATION_ERROR: "Fix Pydantic schema or node output shape.",
    FailureCategory.CONSTRAINT_COST_EXCEEDED: "Enable budget-based model degradation.",
    FailureCategory.CONSTRAINT_TIME_EXCEEDED: "Parallelize nodes or use faster models.",
    FailureCategory.CONSTRAINT_QUALITY_BELOW: "Upgrade model or improve prompts.",
    FailureCategory.CONSTRAINT_SAFETY_VIOLATION: "Add PII detection and content moderation.",
    FailureCategory.RESOURCE_BUDGET_EXHAUSTED: "Increase daily budget or add degradation policy.",
    FailureCategory.RESOURCE_MEMORY_EXCEEDED: "Implement memory pruning.",
    FailureCategory.RESOURCE_CONCURRENCY_LIMIT: "Queue requests or scale agent instances.",
}


class FailureClassifier:
    """Classify execution failures into actionable categories.

    Two-pass approach: structural analysis of ExecutionResult fields,
    then pattern matching on error messages.
    """

    def __init__(self) -> None:
        self._compiled: list[tuple[re.Pattern[str], FailureCategory]] = []
        for group in _ALL_PATTERN_GROUPS:
            for pattern_str, category in group:
                self._compiled.append((re.compile(pattern_str, re.IGNORECASE), category))

    def classify(self, execution_result: Any) -> list[FailureRecord]:
        """Classify all failures in an ExecutionResult."""
        records: list[FailureRecord] = []

        records.extend(self._check_structural(execution_result))

        error_text = self._extract_error_text(execution_result)
        if error_text:
            records.extend(self._match_patterns(error_text))

        records = self._deduplicate(records)

        success = getattr(execution_result, "success", True)
        if not success and not records:
            records.append(
                FailureRecord(
                    category=FailureCategory.UNKNOWN,
                    severity="medium",
                    message=(
                        getattr(execution_result, "error", "Unknown failure") or "Unknown failure"
                    ),
                    remediation_hint="Manual investigation required.",
                )
            )

        return records

    def classify_error(self, error_message: str, node_id: str | None = None) -> FailureRecord:
        """Classify a single error string."""
        for pattern, category in self._compiled:
            if pattern.search(error_message):
                return FailureRecord(
                    category=category,
                    severity=_SEVERITY_MAP.get(category, "medium"),
                    node_id=node_id,
                    message=error_message[:500],
                    remediation_hint=_HINT_MAP.get(category, "Manual investigation required."),
                )
        return FailureRecord(
            category=FailureCategory.UNKNOWN,
            severity="medium",
            node_id=node_id,
            message=error_message[:500],
            remediation_hint="Manual investigation required.",
        )

    def _check_structural(self, result: Any) -> list[FailureRecord]:
        records: list[FailureRecord] = []

        quality = getattr(result, "execution_quality", "clean")
        if quality == "failed":
            for node_id in getattr(result, "nodes_with_failures", []):
                retry_count = getattr(result, "retry_details", {}).get(node_id, 0)
                records.append(
                    FailureRecord(
                        category=FailureCategory.GRAPH_VALIDATION_ERROR,
                        severity="high",
                        node_id=node_id,
                        message=f"Node '{node_id}' failed after {retry_count} retries",
                        context={"retries": retry_count},
                        remediation_hint="Review node implementation or add error handling.",
                    )
                )

        total_tokens = getattr(result, "total_tokens", 0)
        if total_tokens > 100_000:
            records.append(
                FailureRecord(
                    category=FailureCategory.CONSTRAINT_COST_EXCEEDED,
                    severity="medium",
                    message=f"High token usage: {total_tokens:,} tokens",
                    context={"total_tokens": total_tokens},
                    remediation_hint="Consider prompt compression or model degradation.",
                )
            )

        total_latency = getattr(result, "total_latency_ms", 0)
        if total_latency > 120_000:
            records.append(
                FailureRecord(
                    category=FailureCategory.CONSTRAINT_TIME_EXCEEDED,
                    severity="medium",
                    message=f"High latency: {total_latency:,}ms",
                    context={"total_latency_ms": total_latency},
                    remediation_hint="Consider parallelizing nodes or reducing LLM calls.",
                )
            )

        return records

    def _extract_error_text(self, result: Any) -> str:
        parts: list[str] = []
        error = getattr(result, "error", None)
        if error:
            parts.append(str(error))
        output = getattr(result, "output", {})
        if isinstance(output, dict) and "error" in output:
            parts.append(str(output["error"]))
        return " ".join(parts)

    def _match_patterns(self, error_text: str) -> list[FailureRecord]:
        records: list[FailureRecord] = []
        seen: set[FailureCategory] = set()
        for pattern, category in self._compiled:
            if category in seen:
                continue
            if pattern.search(error_text):
                seen.add(category)
                records.append(
                    FailureRecord(
                        category=category,
                        severity=_SEVERITY_MAP.get(category, "medium"),
                        message=error_text[:500],
                        remediation_hint=_HINT_MAP.get(category, "Manual investigation required."),
                    )
                )
        return records

    def _deduplicate(self, records: list[FailureRecord]) -> list[FailureRecord]:
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        best: dict[FailureCategory, FailureRecord] = {}
        for r in records:
            existing = best.get(r.category)
            if existing is None or severity_order.get(r.severity, 9) < severity_order.get(
                existing.severity, 9
            ):
                best[r.category] = r
        return list(best.values())
