"""
Failure Classifier - Classifies agent failures according to the taxonomy.

Follows the HybridJudge pattern:
1. Rules first - check for known patterns
2. LLM fallback - for ambiguous cases
3. Confidence threshold - low confidence -> UNKNOWN
"""

from __future__ import annotations

import logging
import re
from typing import Any

from framework.schemas.failure_taxonomy import (
    CATEGORY_DESCRIPTIONS,
    ClassifiedFailure,
    FailureCategory,
    EvolutionStrategy,
)
from framework.schemas.run import Problem, Run

logger = logging.getLogger(__name__)


FAILURE_PATTERNS: dict[FailureCategory, list[str]] = {
    FailureCategory.TIMEOUT: [
        r"timeout",
        r"timed out",
        r"exceeded.*time",
        r"deadline exceeded",
        r"took too long",
    ],
    FailureCategory.TOOL_ERROR: [
        r"rate.?limit",
        r"429",
        r"api.?error",
        r"service.?unavailable",
        r"503",
        r"502",
        r"500",
        r"connection refused",
        r"connection reset",
        r"network error",
        r"tool.*failed",
        r"tool.*error",
    ],
    FailureCategory.COST_OVERRUN: [
        r"budget.*exceeded",
        r"cost.*limit",
        r"token.*limit",
        r"max.*tokens",
        r"quota.*exceeded",
        r"billing",
    ],
    FailureCategory.EXTERNAL_DEPENDENCY: [
        r"unavailable",
        r"not reachable",
        r"dns.*error",
        r"ssl.*error",
        r"certificate",
        r"service.*down",
        r"dependency.*failed",
    ],
    FailureCategory.CONSTRAINT_VIOLATION: [
        r"constraint.*violated",
        r"bypassed.*constraint",
        r"invalid.*state",
        r"forbidden",
        r"not allowed",
        r"unauthorized",
        r"401",
        r"403",
    ],
    FailureCategory.HALLUCINATION: [
        r"hallucinat",
        r"fabricated",
        r"incorrect.*data",
        r"wrong.*fact",
        r"made up",
        r"fictional",
        r"nonexistent",
    ],
    FailureCategory.GOAL_AMBIGUITY: [
        r"unclear.*goal",
        r"ambiguous",
        r"insufficient.*information",
        r"missing.*context",
        r"undefined.*objective",
        r"goal.*not.*clear",
    ],
    FailureCategory.ROUTING_ERROR: [
        r"wrong.*branch",
        r"incorrect.*path",
        r"routing.*error",
        r"edge.*condition",
        r"should.*have.*gone.*to",
        r"misrouted",
    ],
    FailureCategory.OUTPUT_QUALITY: [
        r"quality.*issue",
        r"poor.*output",
        r"invalid.*output",
        r"output.*not.*match",
        r"format.*error",
        r"schema.*violation",
        r"validation.*failed",
    ],
}

NODE_INDICATORS: dict[FailureCategory, list[str]] = {
    FailureCategory.ROUTING_ERROR: ["router", "dispatcher", "selector", "decision"],
    FailureCategory.TOOL_ERROR: ["tool", "api", "call", "fetch", "request"],
    FailureCategory.OUTPUT_QUALITY: ["format", "validate", "transform", "output"],
    FailureCategory.HALLUCINATION: ["generate", "create", "write", "compose"],
}


class FailureClassifier:
    """Classifies failures using rules-first then LLM fallback."""

    def __init__(
        self,
        confidence_threshold: float = 0.7,
        llm_provider: Any = None,
    ):
        self.confidence_threshold = confidence_threshold
        self.llm_provider = llm_provider
        self._compiled_patterns: dict[FailureCategory, list[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        for category, patterns in FAILURE_PATTERNS.items():
            self._compiled_patterns[category] = [re.compile(p, re.IGNORECASE) for p in patterns]

    def classify(self, run: Run) -> ClassifiedFailure | None:
        """Classify the failure from a failed run."""
        if run.status.value != "failed":
            return None

        if not run.problems:
            return ClassifiedFailure(
                category=FailureCategory.UNKNOWN,
                confidence=0.3,
                evidence=["Run failed but no problems were recorded"],
                affected_nodes=run.metrics.nodes_executed,
            )

        rules_result = self._classify_by_rules(run)
        if rules_result and rules_result.confidence >= self.confidence_threshold:
            return rules_result

        if rules_result:
            rules_result.evidence.append(
                f"Confidence {rules_result.confidence:.2f} below threshold, consider manual review"
            )
            return rules_result

        return ClassifiedFailure(
            category=FailureCategory.UNKNOWN,
            confidence=0.5,
            evidence=["Could not classify failure automatically"],
            affected_nodes=run.metrics.nodes_executed,
        )

    def classify_problem(
        self, problem: Problem, context: dict[str, Any] | None = None
    ) -> ClassifiedFailure:
        """Classify a single problem."""
        text_sources = [problem.description]
        if problem.root_cause:
            text_sources.append(problem.root_cause)
        if problem.suggested_fix:
            text_sources.append(problem.suggested_fix)
        combined_text = " ".join(text_sources)

        rules_result = self._classify_text(combined_text)
        if rules_result and rules_result.confidence >= self.confidence_threshold:
            if problem.decision_id:
                rules_result.affected_nodes.append(problem.decision_id)
            return rules_result

        if rules_result:
            return rules_result

        return ClassifiedFailure(
            category=FailureCategory.UNKNOWN,
            confidence=0.3,
            evidence=[f"Could not classify: {problem.description[:100]}"],
            raw_error=problem.root_cause,
        )

    def _classify_by_rules(self, run: Run) -> ClassifiedFailure | None:
        """Apply rule-based classification to a run."""
        best_match: tuple[FailureCategory, float, list[str]] | None = None

        for problem in run.problems:
            text_sources = [problem.description]
            if problem.root_cause:
                text_sources.append(problem.root_cause)
            if problem.suggested_fix:
                text_sources.append(problem.suggested_fix)
            combined_text = " ".join(text_sources)

            for category, patterns in self._compiled_patterns.items():
                evidence = []
                match_count = 0
                for pattern in patterns:
                    if pattern.search(combined_text):
                        match_count += 1
                        evidence.append(f"Pattern '{pattern.pattern}' matched")

                if match_count > 0:
                    confidence = min(0.95, 0.5 + (match_count * 0.15))
                    if best_match is None or confidence > best_match[1]:
                        affected_nodes = []
                        if problem.decision_id:
                            affected_nodes.append(problem.decision_id)
                        affected_nodes.extend(run.metrics.nodes_executed)
                        best_match = (category, confidence, evidence)

        if best_match:
            category, confidence, evidence = best_match
            return ClassifiedFailure(
                category=category,
                confidence=confidence,
                evidence=evidence,
                affected_nodes=list(set(run.metrics.nodes_executed)),
                raw_error=run.problems[0].root_cause if run.problems else None,
            )

        return None

    def _classify_text(self, text: str) -> ClassifiedFailure | None:
        """Classify text using rules."""
        best_match: tuple[FailureCategory, float, list[str]] | None = None

        for category, patterns in self._compiled_patterns.items():
            evidence = []
            match_count = 0
            for pattern in patterns:
                if pattern.search(text):
                    match_count += 1
                    evidence.append(f"Pattern '{pattern.pattern}' matched")

            if match_count > 0:
                confidence = min(0.95, 0.5 + (match_count * 0.15))
                if best_match is None or confidence > best_match[1]:
                    best_match = (category, confidence, evidence)

        if best_match:
            category, confidence, evidence = best_match
            return ClassifiedFailure(
                category=category,
                confidence=confidence,
                evidence=evidence,
                raw_error=text[:500] if len(text) > 500 else text,
            )

        return None

    async def _classify_by_llm(self, run: Run) -> ClassifiedFailure | None:
        """Use LLM to classify failure when rules don't provide high confidence."""
        if not self.llm_provider:
            return None

        problem_descriptions = []
        for p in run.problems:
            desc = f"[{p.severity}] {p.description}"
            if p.root_cause:
                desc += f" - Root cause: {p.root_cause}"
            problem_descriptions.append(desc)

        failed_decisions = []
        for d in run.decisions:
            if not d.was_successful:
                failed_decisions.append(d.summary_for_builder())

        prompt = f"""Classify this agent failure into one of these categories:

Categories:
{self._format_categories()}

Run Information:
- Status: {run.status.value}
- Duration: {run.duration_ms}ms
- Problems: {chr(10).join(problem_descriptions) if problem_descriptions else "None"}
- Failed Decisions: {chr(10).join(failed_decisions) if failed_decisions else "None"}
- Nodes Executed: {", ".join(run.metrics.nodes_executed)}

Based on the problems and decision failures, classify this failure.

Respond in exactly this format:
CATEGORY: (one of the category names above)
CONFIDENCE: 0.X
EVIDENCE: (brief reason for classification)
SUBCATEGORY: (optional more specific type)
"""

        try:
            response = await self.llm_provider.acomplete(
                messages=[{"role": "user", "content": prompt}],
                system="You are a failure classification assistant. Be precise and concise.",
                max_tokens=500,
                max_retries=1,
            )
            if response.content:
                return self._parse_llm_response(response.content, run)
        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")

        return None

    async def classify_by_llm_problem_async(
        self, problem: Problem, context: dict[str, Any] | None = None
    ) -> ClassifiedFailure | None:
        """Use LLM to classify a single problem."""
        if not self.llm_provider:
            return None

        context_info = ""
        if context:
            context_info = f"\nContext: {context}"

        prompt = f"""Classify this problem into one of these categories:

Categories:
{self._format_categories()}

Problem:
- Severity: {problem.severity}
- Description: {problem.description}
- Root Cause: {problem.root_cause or "Unknown"}
- Suggested Fix: {problem.suggested_fix or "None"}{context_info}

Respond in exactly this format:
CATEGORY: (one of the category names above)
CONFIDENCE: 0.X
EVIDENCE: (brief reason for classification)
"""

        try:
            response = await self.llm_provider.acomplete(
                messages=[{"role": "user", "content": prompt}],
                system="You are a failure classification assistant. Be precise and concise.",
                max_tokens=300,
                max_retries=1,
            )
            if response.content:
                return self._parse_llm_response_simple(response.content, problem)
        except Exception as e:
            logger.warning(f"LLM problem classification failed: {e}")

        return None

    def _parse_llm_response(self, response: str, run: Run) -> ClassifiedFailure:
        """Parse LLM response into ClassifiedFailure."""
        category = FailureCategory.UNKNOWN
        confidence = 0.5
        evidence = []
        subcategory = None

        for line in response.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("CATEGORY:"):
                cat_str = line.split(":", 1)[1].strip().upper().replace(" ", "_")
                try:
                    category = FailureCategory(cat_str.lower())
                except ValueError:
                    pass
            elif line.upper().startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                    confidence = max(0.0, min(1.0, confidence))
                except ValueError:
                    pass
            elif line.upper().startswith("EVIDENCE:"):
                evidence.append(line.split(":", 1)[1].strip())
            elif line.upper().startswith("SUBCATEGORY:"):
                subcategory = line.split(":", 1)[1].strip()

        return ClassifiedFailure(
            category=category,
            subcategory=subcategory,
            confidence=confidence,
            evidence=evidence if evidence else ["LLM classification"],
            affected_nodes=list(set(run.metrics.nodes_executed)),
        )

    def _parse_llm_response_simple(self, response: str, problem: Problem) -> ClassifiedFailure:
        """Parse LLM response for single problem classification."""
        category = FailureCategory.UNKNOWN
        confidence = 0.5
        evidence = []

        for line in response.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("CATEGORY:"):
                cat_str = line.split(":", 1)[1].strip().upper().replace(" ", "_")
                try:
                    category = FailureCategory(cat_str.lower())
                except ValueError:
                    pass
            elif line.upper().startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.upper().startswith("EVIDENCE:"):
                evidence.append(line.split(":", 1)[1].strip())

        affected_nodes = [problem.decision_id] if problem.decision_id else []
        return ClassifiedFailure(
            category=category,
            confidence=confidence,
            evidence=evidence if evidence else ["LLM classification"],
            affected_nodes=affected_nodes,
            raw_error=problem.root_cause,
        )

    def _format_categories(self) -> str:
        """Format categories for LLM prompt."""
        lines = []
        for cat in FailureCategory:
            if cat != FailureCategory.UNKNOWN:
                desc = CATEGORY_DESCRIPTIONS.get(cat, "")
                lines.append(f"- {cat.value}: {desc}")
        return "\n".join(lines)


def classify_failure(run: Run, llm_provider: Any = None) -> ClassifiedFailure | None:
    """Convenience function to classify a failed run."""
    classifier = FailureClassifier(llm_provider=llm_provider)
    return classifier.classify(run)


def classify_problem(
    problem: Problem, context: dict[str, Any] | None = None, llm_provider: Any = None
) -> ClassifiedFailure:
    """Convenience function to classify a single problem."""
    classifier = FailureClassifier(llm_provider=llm_provider)
    return classifier.classify_problem(problem, context)
