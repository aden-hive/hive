"""
Guardrails Framework - Runtime safety constraints for agent execution.

Guardrails are checks that run before/after node execution to enforce:
- Budget limits (cost, tokens)
- Rate limiting
- Content filtering
- Custom business rules

Usage:
    from framework.runtime.guardrails import (
        Guardrail, GuardrailResult, GuardrailViolation,
        BudgetGuardrail, RateLimitGuardrail, ContentFilterGuardrail,
    )
    
    # Create guardrails
    budget = BudgetGuardrail(max_cost_usd=10.0, max_tokens=100000)
    rate_limit = RateLimitGuardrail(max_requests_per_minute=60)
    content = ContentFilterGuardrail(blocked_patterns=["password", "secret"])
    
    # Check before execution
    result = budget.check_pre_execution(ctx)
    if not result.passed:
        # Handle violation
        print(f"Blocked: {result.violation.message}")
"""

import re
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from collections import deque

logger = logging.getLogger(__name__)


class GuardrailSeverity(str, Enum):
    """Severity level for guardrail violations."""
    WARNING = "warning"      # Log but continue
    SOFT_BLOCK = "soft_block"  # Block but allow override
    HARD_BLOCK = "hard_block"  # Block unconditionally


class GuardrailPhase(str, Enum):
    """When the guardrail check runs."""
    PRE_EXECUTION = "pre_execution"   # Before node executes
    POST_EXECUTION = "post_execution"  # After node executes
    BOTH = "both"                      # Both phases


@dataclass
class GuardrailViolation:
    """Details about a guardrail violation."""
    guardrail_id: str
    message: str
    severity: GuardrailSeverity
    details: dict[str, Any] = field(default_factory=dict)
    suggested_action: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "guardrail_id": self.guardrail_id,
            "message": self.message,
            "severity": self.severity.value,
            "details": self.details,
            "suggested_action": self.suggested_action,
        }


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    guardrail_id: str
    phase: GuardrailPhase
    violation: GuardrailViolation | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def allow(cls, guardrail_id: str, phase: GuardrailPhase, **metadata) -> "GuardrailResult":
        """Create a passing result."""
        return cls(passed=True, guardrail_id=guardrail_id, phase=phase, metadata=metadata)
    
    @classmethod
    def deny(
        cls, 
        guardrail_id: str, 
        phase: GuardrailPhase, 
        message: str,
        severity: GuardrailSeverity = GuardrailSeverity.HARD_BLOCK,
        details: dict[str, Any] | None = None,
        suggested_action: str | None = None,
    ) -> "GuardrailResult":
        """Create a failing result."""
        return cls(
            passed=False,
            guardrail_id=guardrail_id,
            phase=phase,
            violation=GuardrailViolation(
                guardrail_id=guardrail_id,
                message=message,
                severity=severity,
                details=details or {},
                suggested_action=suggested_action,
            ),
        )


@dataclass
class GuardrailContext:
    """Context passed to guardrail checks."""
    node_id: str
    node_type: str
    input_data: dict[str, Any]
    goal_id: str
    run_id: str
    # Accumulated metrics
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0
    step_count: int = 0
    # Output data (only for post-execution)
    output_data: dict[str, Any] | None = None
    success: bool | None = None
    # Extra context
    extra: dict[str, Any] = field(default_factory=dict)


class Guardrail(ABC):
    """
    Base class for all guardrails.
    
    Implement check_pre_execution and/or check_post_execution to create
    custom guardrails. The framework calls these at the appropriate phase.
    """
    
    def __init__(
        self, 
        guardrail_id: str,
        severity: GuardrailSeverity = GuardrailSeverity.HARD_BLOCK,
        enabled: bool = True,
    ):
        self.guardrail_id = guardrail_id
        self.severity = severity
        self.enabled = enabled
    
    @property
    @abstractmethod
    def phase(self) -> GuardrailPhase:
        """Which execution phase(s) this guardrail applies to."""
        ...
    
    def check_pre_execution(self, ctx: GuardrailContext) -> GuardrailResult:
        """
        Check before node execution.
        
        Override this to implement pre-execution checks.
        Default implementation passes.
        """
        return GuardrailResult.allow(self.guardrail_id, GuardrailPhase.PRE_EXECUTION)
    
    def check_post_execution(self, ctx: GuardrailContext) -> GuardrailResult:
        """
        Check after node execution.
        
        Override this to implement post-execution checks.
        Default implementation passes.
        """
        return GuardrailResult.allow(self.guardrail_id, GuardrailPhase.POST_EXECUTION)


class BudgetGuardrail(Guardrail):
    """
    Guardrail that enforces budget limits.
    
    Blocks execution when cost or token limits are exceeded.
    
    Example:
        budget = BudgetGuardrail(
            max_cost_usd=10.0,
            max_tokens=100000,
            warning_threshold=0.8,  # Warn at 80%
        )
    """
    
    def __init__(
        self,
        max_cost_usd: float | None = None,
        max_tokens: int | None = None,
        warning_threshold: float = 0.8,
        severity: GuardrailSeverity = GuardrailSeverity.HARD_BLOCK,
    ):
        super().__init__(guardrail_id="budget", severity=severity)
        self.max_cost_usd = max_cost_usd
        self.max_tokens = max_tokens
        self.warning_threshold = warning_threshold
    
    @property
    def phase(self) -> GuardrailPhase:
        return GuardrailPhase.PRE_EXECUTION
    
    def check_pre_execution(self, ctx: GuardrailContext) -> GuardrailResult:
        """Check if budget limits would be exceeded."""
        violations = []
        warnings = []
        
        # Check cost limit
        if self.max_cost_usd is not None:
            usage_pct = ctx.total_cost_usd / self.max_cost_usd
            if ctx.total_cost_usd >= self.max_cost_usd:
                violations.append(f"Cost limit exceeded: ${ctx.total_cost_usd:.4f} >= ${self.max_cost_usd:.2f}")
            elif usage_pct >= self.warning_threshold:
                warnings.append(f"Cost at {usage_pct:.0%} of limit (${ctx.total_cost_usd:.4f}/${self.max_cost_usd:.2f})")
        
        # Check token limit
        if self.max_tokens is not None:
            usage_pct = ctx.total_tokens / self.max_tokens
            if ctx.total_tokens >= self.max_tokens:
                violations.append(f"Token limit exceeded: {ctx.total_tokens:,} >= {self.max_tokens:,}")
            elif usage_pct >= self.warning_threshold:
                warnings.append(f"Tokens at {usage_pct:.0%} of limit ({ctx.total_tokens:,}/{self.max_tokens:,})")
        
        # Log warnings
        for warning in warnings:
            logger.warning(f"⚠ Budget warning: {warning}")
        
        if violations:
            return GuardrailResult.deny(
                guardrail_id=self.guardrail_id,
                phase=GuardrailPhase.PRE_EXECUTION,
                message="; ".join(violations),
                severity=self.severity,
                details={
                    "total_cost_usd": ctx.total_cost_usd,
                    "total_tokens": ctx.total_tokens,
                    "max_cost_usd": self.max_cost_usd,
                    "max_tokens": self.max_tokens,
                },
                suggested_action="Increase budget limits or optimize agent to use fewer tokens",
            )
        
        return GuardrailResult.allow(
            self.guardrail_id, 
            GuardrailPhase.PRE_EXECUTION,
            warnings=warnings,
        )


class RateLimitGuardrail(Guardrail):
    """
    Guardrail that enforces rate limits using a sliding window.
    
    Example:
        rate_limit = RateLimitGuardrail(
            max_requests_per_minute=60,
            max_requests_per_hour=1000,
        )
    """
    
    def __init__(
        self,
        max_requests_per_minute: int | None = None,
        max_requests_per_hour: int | None = None,
        severity: GuardrailSeverity = GuardrailSeverity.SOFT_BLOCK,
    ):
        super().__init__(guardrail_id="rate_limit", severity=severity)
        self.max_per_minute = max_requests_per_minute
        self.max_per_hour = max_requests_per_hour
        # Sliding window tracking
        self._request_times: deque[float] = deque()
    
    @property
    def phase(self) -> GuardrailPhase:
        return GuardrailPhase.PRE_EXECUTION
    
    def _clean_old_requests(self, current_time: float, window_seconds: float) -> None:
        """Remove requests older than the window."""
        cutoff = current_time - window_seconds
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()
    
    def _count_requests_in_window(self, current_time: float, window_seconds: float) -> int:
        """Count requests within the time window."""
        cutoff = current_time - window_seconds
        return sum(1 for t in self._request_times if t >= cutoff)
    
    def check_pre_execution(self, ctx: GuardrailContext) -> GuardrailResult:
        """Check if rate limits would be exceeded."""
        current_time = time.time()
        
        # Clean old entries (use the larger window)
        self._clean_old_requests(current_time, 3600)  # 1 hour
        
        violations = []
        
        # Check per-minute limit
        if self.max_per_minute is not None:
            count = self._count_requests_in_window(current_time, 60)
            if count >= self.max_per_minute:
                violations.append(f"Minute limit: {count} >= {self.max_per_minute}")
        
        # Check per-hour limit
        if self.max_per_hour is not None:
            count = self._count_requests_in_window(current_time, 3600)
            if count >= self.max_per_hour:
                violations.append(f"Hour limit: {count} >= {self.max_per_hour}")
        
        if violations:
            return GuardrailResult.deny(
                guardrail_id=self.guardrail_id,
                phase=GuardrailPhase.PRE_EXECUTION,
                message=f"Rate limit exceeded: {'; '.join(violations)}",
                severity=self.severity,
                details={
                    "requests_last_minute": self._count_requests_in_window(current_time, 60),
                    "requests_last_hour": self._count_requests_in_window(current_time, 3600),
                    "max_per_minute": self.max_per_minute,
                    "max_per_hour": self.max_per_hour,
                },
                suggested_action="Wait before retrying or increase rate limits",
            )
        
        # Record this request
        self._request_times.append(current_time)
        
        return GuardrailResult.allow(self.guardrail_id, GuardrailPhase.PRE_EXECUTION)


class ContentFilterGuardrail(Guardrail):
    """
    Guardrail that filters content for sensitive patterns.
    
    Checks both input (pre-execution) and output (post-execution) for
    blocked patterns like passwords, API keys, etc.
    
    Example:
        content_filter = ContentFilterGuardrail(
            blocked_patterns=[
                r"password\s*[:=]\s*\S+",
                r"api[_-]?key\s*[:=]\s*\S+",
                r"secret\s*[:=]\s*\S+",
            ],
            blocked_keywords=["DROP TABLE", "DELETE FROM"],
        )
    """
    
    def __init__(
        self,
        blocked_patterns: list[str] | None = None,
        blocked_keywords: list[str] | None = None,
        case_sensitive: bool = False,
        severity: GuardrailSeverity = GuardrailSeverity.HARD_BLOCK,
    ):
        super().__init__(guardrail_id="content_filter", severity=severity)
        self.blocked_keywords = blocked_keywords or []
        self.case_sensitive = case_sensitive
        
        # Compile regex patterns
        flags = 0 if case_sensitive else re.IGNORECASE
        self.blocked_patterns = [
            re.compile(p, flags) for p in (blocked_patterns or [])
        ]
    
    @property
    def phase(self) -> GuardrailPhase:
        return GuardrailPhase.BOTH
    
    def _check_content(self, content: str, phase: GuardrailPhase) -> GuardrailResult:
        """Check content for blocked patterns and keywords."""
        matches = []
        
        # Check regex patterns
        for pattern in self.blocked_patterns:
            if pattern.search(content):
                matches.append(f"Pattern: {pattern.pattern}")
        
        # Check keywords
        check_content = content if self.case_sensitive else content.lower()
        for keyword in self.blocked_keywords:
            check_keyword = keyword if self.case_sensitive else keyword.lower()
            if check_keyword in check_content:
                matches.append(f"Keyword: {keyword}")
        
        if matches:
            return GuardrailResult.deny(
                guardrail_id=self.guardrail_id,
                phase=phase,
                message=f"Blocked content detected: {', '.join(matches)}",
                severity=self.severity,
                details={"matches": matches, "phase": phase.value},
                suggested_action="Remove sensitive content before processing",
            )
        
        return GuardrailResult.allow(self.guardrail_id, phase)
    
    def _extract_text(self, data: dict[str, Any]) -> str:
        """Recursively extract all text from a dict."""
        texts = []
        
        def extract(obj: Any) -> None:
            if isinstance(obj, str):
                texts.append(obj)
            elif isinstance(obj, dict):
                for v in obj.values():
                    extract(v)
            elif isinstance(obj, (list, tuple)):
                for item in obj:
                    extract(item)
        
        extract(data)
        return " ".join(texts)
    
    def check_pre_execution(self, ctx: GuardrailContext) -> GuardrailResult:
        """Check input data for blocked content."""
        text = self._extract_text(ctx.input_data)
        return self._check_content(text, GuardrailPhase.PRE_EXECUTION)
    
    def check_post_execution(self, ctx: GuardrailContext) -> GuardrailResult:
        """Check output data for blocked content."""
        if ctx.output_data:
            text = self._extract_text(ctx.output_data)
            return self._check_content(text, GuardrailPhase.POST_EXECUTION)
        return GuardrailResult.allow(self.guardrail_id, GuardrailPhase.POST_EXECUTION)


class MaxStepsGuardrail(Guardrail):
    """
    Guardrail that limits the number of execution steps.
    
    Prevents infinite loops and runaway agents.
    
    Example:
        max_steps = MaxStepsGuardrail(max_steps=50)
    """
    
    def __init__(
        self,
        max_steps: int = 100,
        severity: GuardrailSeverity = GuardrailSeverity.HARD_BLOCK,
    ):
        super().__init__(guardrail_id="max_steps", severity=severity)
        self.max_steps = max_steps
    
    @property
    def phase(self) -> GuardrailPhase:
        return GuardrailPhase.PRE_EXECUTION
    
    def check_pre_execution(self, ctx: GuardrailContext) -> GuardrailResult:
        """Check if step limit would be exceeded."""
        if ctx.step_count >= self.max_steps:
            return GuardrailResult.deny(
                guardrail_id=self.guardrail_id,
                phase=GuardrailPhase.PRE_EXECUTION,
                message=f"Max steps exceeded: {ctx.step_count} >= {self.max_steps}",
                severity=self.severity,
                details={"step_count": ctx.step_count, "max_steps": self.max_steps},
                suggested_action="Increase max_steps limit or simplify the agent workflow",
            )
        return GuardrailResult.allow(self.guardrail_id, GuardrailPhase.PRE_EXECUTION)


class CustomGuardrail(Guardrail):
    """
    Guardrail that uses custom check functions.
    
    Example:
        def check_business_hours(ctx):
            hour = datetime.now().hour
            if not (9 <= hour < 17):
                return False, "Agent can only run during business hours (9-17)"
            return True, None
        
        business_hours = CustomGuardrail(
            guardrail_id="business_hours",
            check_fn=check_business_hours,
            phase=GuardrailPhase.PRE_EXECUTION,
        )
    """
    
    def __init__(
        self,
        guardrail_id: str,
        check_fn: Callable[[GuardrailContext], tuple[bool, str | None]],
        guardrail_phase: GuardrailPhase = GuardrailPhase.PRE_EXECUTION,
        severity: GuardrailSeverity = GuardrailSeverity.HARD_BLOCK,
    ):
        super().__init__(guardrail_id=guardrail_id, severity=severity)
        self.check_fn = check_fn
        self._phase = guardrail_phase
    
    @property
    def phase(self) -> GuardrailPhase:
        return self._phase
    
    def _run_check(self, ctx: GuardrailContext, phase: GuardrailPhase) -> GuardrailResult:
        """Run the custom check function."""
        try:
            passed, message = self.check_fn(ctx)
            if passed:
                return GuardrailResult.allow(self.guardrail_id, phase)
            else:
                return GuardrailResult.deny(
                    guardrail_id=self.guardrail_id,
                    phase=phase,
                    message=message or "Custom guardrail check failed",
                    severity=self.severity,
                )
        except Exception as e:
            return GuardrailResult.deny(
                guardrail_id=self.guardrail_id,
                phase=phase,
                message=f"Custom guardrail error: {e}",
                severity=GuardrailSeverity.HARD_BLOCK,
            )
    
    def check_pre_execution(self, ctx: GuardrailContext) -> GuardrailResult:
        if self._phase in (GuardrailPhase.PRE_EXECUTION, GuardrailPhase.BOTH):
            return self._run_check(ctx, GuardrailPhase.PRE_EXECUTION)
        return GuardrailResult.allow(self.guardrail_id, GuardrailPhase.PRE_EXECUTION)
    
    def check_post_execution(self, ctx: GuardrailContext) -> GuardrailResult:
        if self._phase in (GuardrailPhase.POST_EXECUTION, GuardrailPhase.BOTH):
            return self._run_check(ctx, GuardrailPhase.POST_EXECUTION)
        return GuardrailResult.allow(self.guardrail_id, GuardrailPhase.POST_EXECUTION)


class GuardrailRegistry:
    """
    Registry that manages multiple guardrails and runs checks.
    
    Example:
        registry = GuardrailRegistry()
        registry.add(BudgetGuardrail(max_cost_usd=10.0))
        registry.add(RateLimitGuardrail(max_requests_per_minute=60))
        
        # Check all guardrails
        results = registry.check_pre_execution(ctx)
        for result in results:
            if not result.passed:
                print(f"Blocked by {result.guardrail_id}: {result.violation.message}")
    """
    
    def __init__(self):
        self._guardrails: list[Guardrail] = []
    
    def add(self, guardrail: Guardrail) -> "GuardrailRegistry":
        """Add a guardrail to the registry."""
        self._guardrails.append(guardrail)
        return self
    
    def remove(self, guardrail_id: str) -> bool:
        """Remove a guardrail by ID."""
        original_len = len(self._guardrails)
        self._guardrails = [g for g in self._guardrails if g.guardrail_id != guardrail_id]
        return len(self._guardrails) < original_len
    
    def get(self, guardrail_id: str) -> Guardrail | None:
        """Get a guardrail by ID."""
        for g in self._guardrails:
            if g.guardrail_id == guardrail_id:
                return g
        return None
    
    def list_all(self) -> list[Guardrail]:
        """List all registered guardrails."""
        return list(self._guardrails)
    
    def check_pre_execution(self, ctx: GuardrailContext) -> list[GuardrailResult]:
        """Run all pre-execution guardrail checks."""
        results = []
        for guardrail in self._guardrails:
            if not guardrail.enabled:
                continue
            if guardrail.phase in (GuardrailPhase.PRE_EXECUTION, GuardrailPhase.BOTH):
                results.append(guardrail.check_pre_execution(ctx))
        return results
    
    def check_post_execution(self, ctx: GuardrailContext) -> list[GuardrailResult]:
        """Run all post-execution guardrail checks."""
        results = []
        for guardrail in self._guardrails:
            if not guardrail.enabled:
                continue
            if guardrail.phase in (GuardrailPhase.POST_EXECUTION, GuardrailPhase.BOTH):
                results.append(guardrail.check_post_execution(ctx))
        return results
    
    def has_violations(self, results: list[GuardrailResult]) -> bool:
        """Check if any results contain violations."""
        return any(not r.passed for r in results)
    
    def get_violations(self, results: list[GuardrailResult]) -> list[GuardrailViolation]:
        """Get all violations from results."""
        return [r.violation for r in results if not r.passed and r.violation]
    
    def get_hard_blocks(self, results: list[GuardrailResult]) -> list[GuardrailViolation]:
        """Get only hard-block violations that should stop execution."""
        violations = self.get_violations(results)
        return [v for v in violations if v.severity == GuardrailSeverity.HARD_BLOCK]
