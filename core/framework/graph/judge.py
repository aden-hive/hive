"""
Hybrid Judge for Evaluating Plan Step Results.

The HybridJudge evaluates step execution results using:
1. Rule-based evaluation (fast, deterministic)
2. LLM-based evaluation (fallback for ambiguous cases)

Escalation path: rules → LLM → human
"""

from dataclasses import dataclass, field
from typing import Any

from framework.graph.code_sandbox import safe_eval
from framework.graph.goal import Goal
from framework.graph.plan import (
    EvaluationRule,
    Judgment,
    JudgmentAction,
    PlanStep,
)
from framework.llm.provider import LLMProvider


@dataclass
class RuleEvaluationResult:
    """Result of rule-based evaluation."""

    is_definitive: bool  # True if a rule matched definitively
    judgment: Judgment | None = None
    context: dict[str, Any] = field(default_factory=dict)
    rules_checked: int = 0
    rule_matched: str | None = None


class HybridJudge:
    """
    Evaluates plan step results using rules first, then LLM fallback.

    Usage:
        judge = HybridJudge(llm=llm_provider)
        judge.add_rule(EvaluationRule(
            id="success_check",
            condition="result.get('success') == True",
            action=JudgmentAction.ACCEPT,
        ))

        judgment = await judge.evaluate(step, result, goal)
    """

    def __init__(
        self,
        llm: LLMProvider | None = None,
        rules: list[EvaluationRule] | None = None,
        llm_confidence_threshold: float = 0.7,
    ):
        """
        Initialize the HybridJudge.

        Args:
            llm: LLM provider for ambiguous cases
            rules: Initial evaluation rules
            llm_confidence_threshold: Confidence below this triggers escalation
        """
        self.llm = llm
        self.rules: list[EvaluationRule] = rules or []
        self.llm_confidence_threshold = llm_confidence_threshold

        # Sort rules by priority (higher first)
        self._sort_rules()

    def _sort_rules(self):
        """Sort rules by priority."""
        self.rules.sort(key=lambda r: -r.priority)

    def add_rule(self, rule: EvaluationRule) -> None:
        """Add an evaluation rule."""
        self.rules.append(rule)
        self._sort_rules()

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID. Returns True if found and removed."""
        for i, rule in enumerate(self.rules):
            if rule.id == rule_id:
                self.rules.pop(i)
                return True
        return False

    async def evaluate(
        self,
        step: PlanStep,
        result: Any,
        goal: Goal,
        context: dict[str, Any] | None = None,
    ) -> Judgment:
        """
        Evaluate a step result.

        Args:
            step: The executed plan step
            result: The result of executing the step
            goal: The goal context for evaluation
            context: Additional context from previous steps

        Returns:
            Judgment with action and feedback
        """
        context = context or {}

        # Try rule-based evaluation first
        rule_result = self._evaluate_rules(step, result, goal, context)

        if rule_result.is_definitive:
            return rule_result.judgment

        # Fall back to LLM evaluation
        if self.llm:
            return await self._evaluate_llm(step, result, goal, context, rule_result)

        # No LLM available - default to accept with low confidence
        return Judgment(
            action=JudgmentAction.ACCEPT,
            reasoning="No definitive rule matched and no LLM available for evaluation",
            confidence=0.5,
            llm_used=False,
        )

    def _evaluate_rules(
        self,
        step: PlanStep,
        result: Any,
        goal: Goal,
        context: dict[str, Any],
    ) -> RuleEvaluationResult:
        """Evaluate step using rules."""
        rules_checked = 0

        # Build evaluation context
        eval_context = {
            "step": step.model_dump() if hasattr(step, "model_dump") else step,
            "result": result,
            "goal": goal.model_dump() if hasattr(goal, "model_dump") else goal,
            "context": context,
            "success": isinstance(result, dict) and result.get("success", False),
            "error": isinstance(result, dict) and result.get("error"),
        }

        for rule in self.rules:
            rules_checked += 1

            # Evaluate rule condition
            eval_result = safe_eval(rule.condition, eval_context)

            if eval_result.success and eval_result.result:
                # Rule matched!
                feedback = self._format_feedback(rule.feedback_template, eval_context)

                return RuleEvaluationResult(
                    is_definitive=True,
                    judgment=Judgment(
                        action=rule.action,
                        reasoning=rule.description,
                        feedback=feedback if feedback else None,
                        rule_matched=rule.id,
                        confidence=1.0,
                        llm_used=False,
                    ),
                    rules_checked=rules_checked,
                    rule_matched=rule.id,
                )

        # No rule matched definitively
        return RuleEvaluationResult(
            is_definitive=False,
            context=eval_context,
            rules_checked=rules_checked,
        )

    def _format_feedback(
        self,
        template: str,
        context: dict[str, Any],
    ) -> str:
        """Format feedback template with context values."""
        if not template:
            return ""

        try:
            return template.format(**context)
        except (KeyError, ValueError):
            return template

    async def _evaluate_llm(
        self,
        step: PlanStep,
        result: Any,
        goal: Goal,
        context: dict[str, Any],
        rule_result: RuleEvaluationResult,
    ) -> Judgment:
        """Evaluate step using LLM."""
        system_prompt = self._build_llm_system_prompt(goal)
        user_prompt = self._build_llm_user_prompt(step, result, context, rule_result)

        try:
            response = self.llm.complete(
                messages=[{"role": "user", "content": user_prompt}],
                system=system_prompt,
            )

            # Parse LLM response
            judgment = self._parse_llm_response(response.content)
            judgment.llm_used = True

            # Check confidence threshold
            if judgment.confidence < self.llm_confidence_threshold:
                # Low confidence - escalate
                return Judgment(
                    action=JudgmentAction.ESCALATE,
                    reasoning=(
                        f"LLM confidence ({judgment.confidence:.2f}) "
                        f"below threshold ({self.llm_confidence_threshold})"
                    ),
                    feedback=judgment.feedback,
                    confidence=judgment.confidence,
                    llm_used=True,
                    context={"original_judgment": judgment.model_dump()},
                )

            return judgment

        except Exception as e:
            # LLM failed - escalate
            return Judgment(
                action=JudgmentAction.ESCALATE,
                reasoning=f"LLM evaluation failed: {e}",
                feedback="Human review needed due to LLM error",
                llm_used=True,
            )

    def _build_llm_system_prompt(self, goal: Goal) -> str:
        """Build system prompt for LLM judge."""
        return f"""You are a judge evaluating the execution of a plan step.

GOAL: {goal.description}

SUCCESS CRITERIA:
{chr(10).join(f"- {sc.description}" for sc in goal.success_criteria)}

CONSTRAINTS:
{chr(10).join(f"- {c.description}" for c in goal.constraints)}

Your task is to evaluate whether the step was executed successfully and decide the next action.

Respond in this exact format:
ACTION: [ACCEPT|RETRY|REPLAN|ESCALATE]
CONFIDENCE: [0.0-1.0]
REASONING: [Your reasoning]
FEEDBACK: [Feedback for retry/replan, or empty if accepting]

Actions:
- ACCEPT: Step completed successfully, continue to next step
- RETRY: Step failed but can be retried with feedback
- REPLAN: Step failed in a way that requires replanning
- ESCALATE: Requires human intervention
"""

    def _build_llm_user_prompt(
        self,
        step: PlanStep,
        result: Any,
        context: dict[str, Any],
        rule_result: RuleEvaluationResult,
    ) -> str:
        """Build user prompt for LLM judge."""
        return f"""Evaluate this step execution:

STEP: {step.description}
STEP ID: {step.id}
ACTION TYPE: {step.action.action_type}
EXPECTED OUTPUTS: {step.expected_outputs}

RESULT:
{result}

CONTEXT FROM PREVIOUS STEPS:
{context}

RULES CHECKED: {rule_result.rules_checked} (none matched definitively)

Please evaluate and provide your judgment."""

    def _parse_llm_response(self, response: str) -> Judgment:
        """Parse LLM response into Judgment."""
        lines = response.strip().split("\n")

        action = JudgmentAction.ACCEPT
        confidence = 0.8
        reasoning = ""
        feedback = ""

        for line in lines:
            line = line.strip()
            if line.startswith("ACTION:"):
                action_str = line.split(":", 1)[1].strip().upper()
                try:
                    action = JudgmentAction(action_str.lower())
                except ValueError:
                    action = JudgmentAction.ESCALATE

            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                except ValueError:
                    confidence = 0.5

            elif line.startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()

            elif line.startswith("FEEDBACK:"):
                feedback = line.split(":", 1)[1].strip()

        return Judgment(
            action=action,
            reasoning=reasoning or "LLM evaluation",
            feedback=feedback if feedback else None,
            confidence=confidence,
        )


# Factory function for creating judge with common rules
def create_default_judge(llm: LLMProvider | None = None) -> HybridJudge:
    """
    Create a HybridJudge with commonly useful default rules.

    Args:
        llm: LLM provider for fallback evaluation

    Returns:
        Configured HybridJudge instance
    """
    judge = HybridJudge(llm=llm)

    # Rule: Accept on explicit success flag
    judge.add_rule(
        EvaluationRule(
            id="explicit_success",
            description="Step explicitly marked as successful",
            condition="isinstance(result, dict) and result.get('success') == True",
            action=JudgmentAction.ACCEPT,
            priority=100,
        )
    )

    # Rule: Retry on transient errors
    judge.add_rule(
        EvaluationRule(
            id="transient_error_retry",
            description="Transient error that can be retried",
            condition=(
                "isinstance(result, dict) and "
                "result.get('error_type') in ['timeout', 'rate_limit', 'connection_error']"
            ),
            action=JudgmentAction.RETRY,
            feedback_template="Transient error: {result[error]}. Please retry.",
            priority=90,
        )
    )

    # Rule: Replan on missing data
    judge.add_rule(
        EvaluationRule(
            id="missing_data_replan",
            description="Required data not available",
            condition="isinstance(result, dict) and result.get('error_type') == 'missing_data'",
            action=JudgmentAction.REPLAN,
            feedback_template="Missing required data: {result[error]}. Plan needs adjustment.",
            priority=80,
        )
    )

    # Rule: Escalate on security issues
    judge.add_rule(
        EvaluationRule(
            id="security_escalate",
            description="Security issue detected",
            condition="isinstance(result, dict) and result.get('error_type') == 'security'",
            action=JudgmentAction.ESCALATE,
            feedback_template="Security issue detected: {result[error]}",
            priority=200,
        )
    )

    # Rule: Fail on max retries exceeded
    judge.add_rule(
        EvaluationRule(
            id="max_retries_fail",
            description="Maximum retries exceeded",
            condition="step.get('attempts', 0) >= step.get('max_retries', 3)",
            action=JudgmentAction.REPLAN,
            feedback_template="Step '{step[id]}' failed after {step[attempts]} attempts",
            priority=150,
        )
    )

    return judge
