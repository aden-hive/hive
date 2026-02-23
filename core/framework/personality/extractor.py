"""
PersonalityExtractor - Mines personality signals from session logs and outputs.

Analyzes completed sessions to extract behavioral patterns including:
- Communication style patterns (tone, formality, vocabulary)
- Decision patterns (risk tolerance, confirmation tendencies)
- Escalation behavior (when/how to ask for human help)
- Domain-specific heuristics
- Successful and avoided patterns

Signals are extracted async after session completion to avoid latency impact.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.personality.dna import (
    CommunicationStyle,
    PersonalitySignal,
    RiskToleranceLevel,
)

logger = logging.getLogger(__name__)


class PersonalityExtractor:
    """
    Extracts personality signals from session logs and outputs.

    Analyzes session data to identify behavioral patterns that can be
    synthesized into stable personality traits.

    Example:
        extractor = PersonalityExtractor()

        signals = await extractor.extract_from_session(
            session_state=session_state,
            session_log=runtime_log,
        )
    """

    def __init__(self):
        self._formal_patterns = [
            r"\b(I would|I should|Please allow me|May I|Would you mind)\b",
            r"\b(Furthermore|Moreover|Additionally|In addition)\b",
            r"\b(Therefore|Consequently|Thus|Hence)\b",
        ]

        self._casual_patterns = [
            r"\b(hey|hi there|cool|awesome|gotcha|sure thing|no problem)\b",
            r"\b(lol|haha|yeah|nope|kinda|sorta)\b",
            r"\b(!+|[\u2600-\u27BF]|[\uD83C-\uDBFF][\uDC00-\uDFFF])",
        ]

        self._technical_patterns = [
            r"\b(implement|optimize|refactor|deprecated|asynchronous)\b",
            r"\b(API|endpoint|schema|validation|middleware)\b",
            r"\b(algorithm|complexity|recursive|iterative)\b",
        ]

        self._escalation_patterns = [
            r"\b(I'?m not sure|I'?m uncertain|This is unclear|I need guidance)\b",
            r"\b(I recommend (consulting|asking|escalating))\b",
            r"\b(beyond my (scope|capabilities|knowledge))\b",
            r"\b(please (verify|confirm|check))\b",
        ]

        self._conservative_patterns = [
            r"\b(I'?ll verify|let me confirm|to be safe|cautious)\b",
            r"\b(risk|careful|double-check|verify)\b",
        ]

        self._aggressive_patterns = [
            r"\b(quickly|fast|immediately|right away|ASAP)\b",
            r"\b(Let'?s just|I'?ll assume|probably fine|likely works)\b",
        ]

    async def extract_from_session(
        self,
        agent_id: str,
        session_id: str,
        session_state: dict[str, Any],
        session_log: dict[str, Any] | None = None,
        decisions: list[dict[str, Any]] | None = None,
        conversations: list[dict[str, Any]] | None = None,
    ) -> list[PersonalitySignal]:
        """
        Extract personality signals from a completed session.

        Args:
            agent_id: The agent's identifier
            session_id: The session's identifier
            session_state: Session state dict from state.json
            session_log: Optional runtime log entries
            decisions: Optional list of decisions made during session
            conversations: Optional list of conversation turns

        Returns:
            List of extracted personality signals
        """
        signals: list[PersonalitySignal] = []

        session_outcome = self._determine_session_outcome(session_state)

        if conversations:
            comm_signals = await self._extract_communication_signals(
                agent_id, session_id, conversations, session_outcome
            )
            signals.extend(comm_signals)

        if decisions:
            decision_signals = await self._extract_decision_signals(
                agent_id, session_id, decisions, session_outcome
            )
            signals.extend(decision_signals)

        if conversations:
            escalation_signals = await self._extract_escalation_signals(
                agent_id, session_id, conversations, session_outcome
            )
            signals.extend(escalation_signals)

        if session_log:
            heuristic_signals = await self._extract_heuristic_signals(
                agent_id, session_id, session_log, session_outcome
            )
            signals.extend(heuristic_signals)

        pattern_signals = await self._extract_pattern_signals(
            agent_id, session_id, session_state, decisions, conversations, session_outcome
        )
        signals.extend(pattern_signals)

        logger.info(f"Extracted {len(signals)} signals from session {session_id}")
        return signals

    def _determine_session_outcome(self, session_state: dict[str, Any]) -> str:
        """Determine if session was successful, failed, or unknown."""
        status = session_state.get("status", "unknown")
        if status == "completed":
            return "success"
        elif status in ("failed", "cancelled"):
            return "failure"
        return "unknown"

    async def _extract_communication_signals(
        self,
        agent_id: str,
        session_id: str,
        conversations: list[dict[str, Any]],
        session_outcome: str,
    ) -> list[PersonalitySignal]:
        """Extract communication style signals from conversations."""
        signals: list[PersonalitySignal] = []

        all_agent_text = ""
        for turn in conversations:
            if turn.get("role") == "assistant":
                all_agent_text += " " + turn.get("content", "")

        if not all_agent_text.strip():
            return signals

        formal_score = self._count_patterns(all_agent_text, self._formal_patterns)
        casual_score = self._count_patterns(all_agent_text, self._casual_patterns)
        technical_score = self._count_patterns(all_agent_text, self._technical_patterns)

        text_length = len(all_agent_text.split())

        if formal_score > casual_score * 1.5:
            style = CommunicationStyle.FORMAL
            style_confidence = min(1.0, formal_score / (text_length / 100 + 1))
        elif casual_score > formal_score * 1.5:
            style = CommunicationStyle.CASUAL
            style_confidence = min(1.0, casual_score / (text_length / 100 + 1))
        elif technical_score > max(formal_score, casual_score):
            style = CommunicationStyle.TECHNICAL
            style_confidence = min(1.0, technical_score / (text_length / 100 + 1))
        else:
            style = CommunicationStyle.ADAPTIVE
            style_confidence = 0.5

        signals.append(
            PersonalitySignal(
                session_id=session_id,
                trait_category="communication_style",
                trait_name="style",
                signal_type="observed_pattern",
                value=style.value,
                confidence=style_confidence,
                evidence=f"Formal: {formal_score}, Casual: {casual_score}, Technical: {technical_score}",
                session_outcome=session_outcome,
            )
        )

        formality = (formal_score - casual_score) / (formal_score + casual_score + 1)
        signals.append(
            PersonalitySignal(
                session_id=session_id,
                trait_category="communication_style",
                trait_name="formality_score",
                signal_type="computed",
                value=(formality + 1) / 2,
                confidence=0.6,
                session_outcome=session_outcome,
            )
        )

        emoji_count = len(
            re.findall(r"[\u2600-\u27BF]|[\uD83C-\uDBFF][\uDC00-\uDFFF]", all_agent_text)
        )
        emoji_usage = min(1.0, emoji_count / (text_length / 50 + 1))
        signals.append(
            PersonalitySignal(
                session_id=session_id,
                trait_category="communication_style",
                trait_name="emoji_usage",
                signal_type="observed_pattern",
                value=emoji_usage,
                confidence=0.7,
                evidence=f"Found {emoji_count} emojis in {text_length} words",
                session_outcome=session_outcome,
            )
        )

        avg_response_length = text_length / max(
            1, len([t for t in conversations if t.get("role") == "assistant"])
        )
        if avg_response_length < 30:
            length_pref = "concise"
        elif avg_response_length > 100:
            length_pref = "verbose"
        else:
            length_pref = "medium"

        signals.append(
            PersonalitySignal(
                session_id=session_id,
                trait_category="communication_style",
                trait_name="response_length_preference",
                signal_type="computed",
                value=length_pref,
                confidence=0.5,
                evidence=f"Average response: {avg_response_length:.0f} words",
                session_outcome=session_outcome,
            )
        )

        return signals

    async def _extract_decision_signals(
        self,
        agent_id: str,
        session_id: str,
        decisions: list[dict[str, Any]],
        session_outcome: str,
    ) -> list[PersonalitySignal]:
        """Extract decision-making pattern signals from decisions."""
        signals: list[PersonalitySignal] = []

        if not decisions:
            return signals

        confirmation_count = 0
        verification_count = 0
        risk_taking_count = 0
        total_decisions = len(decisions)

        for decision in decisions:
            reasoning = decision.get("reasoning", "").lower()

            if any(
                p.search(reasoning)
                for p in [re.compile(p, re.I) for p in self._conservative_patterns]
            ):
                verification_count += 1

            if any(
                p.search(reasoning)
                for p in [re.compile(p, re.I) for p in self._aggressive_patterns]
            ):
                risk_taking_count += 1

            options = decision.get("options", [])
            if len(options) > 3:
                confirmation_count += 1

        if verification_count > risk_taking_count * 1.5:
            risk_level = RiskToleranceLevel.CONSERVATIVE
            risk_confidence = min(
                1.0, (verification_count - risk_taking_count) / (total_decisions + 1)
            )
        elif risk_taking_count > verification_count * 1.5:
            risk_level = RiskToleranceLevel.AGGRESSIVE
            risk_confidence = min(
                1.0, (risk_taking_count - verification_count) / (total_decisions + 1)
            )
        else:
            risk_level = RiskToleranceLevel.MODERATE
            risk_confidence = 0.5

        signals.append(
            PersonalitySignal(
                session_id=session_id,
                trait_category="decision_patterns",
                trait_name="risk_tolerance",
                signal_type="inferred",
                value=risk_level.value,
                confidence=risk_confidence,
                evidence=f"Conservative: {verification_count}, Aggressive: {risk_taking_count}",
                session_outcome=session_outcome,
            )
        )

        confirmation_threshold = min(1.0, confirmation_count / (total_decisions + 1))
        signals.append(
            PersonalitySignal(
                session_id=session_id,
                trait_category="decision_patterns",
                trait_name="confirmation_threshold",
                signal_type="computed",
                value=0.5 + confirmation_threshold * 0.3,
                confidence=0.5,
                evidence=f"Considered multiple options in {confirmation_count}/{total_decisions} decisions",
                session_outcome=session_outcome,
            )
        )

        return signals

    async def _extract_escalation_signals(
        self,
        agent_id: str,
        session_id: str,
        conversations: list[dict[str, Any]],
        session_outcome: str,
    ) -> list[PersonalitySignal]:
        """Extract escalation behavior signals from conversations."""
        signals: list[PersonalitySignal] = []

        escalation_count = 0
        uncertainty_count = 0
        total_turns = 0

        for turn in conversations:
            if turn.get("role") != "assistant":
                continue

            total_turns += 1
            content = turn.get("content", "")

            for pattern in self._escalation_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    escalation_count += 1
                    break

            if "uncertain" in content.lower() or "not sure" in content.lower():
                uncertainty_count += 1

        if total_turns == 0:
            return signals

        escalation_rate = escalation_count / total_turns

        signals.append(
            PersonalitySignal(
                session_id=session_id,
                trait_category="escalation_behavior",
                trait_name="escalation_frequency",
                signal_type="observed_pattern",
                value=escalation_rate,
                confidence=min(1.0, total_turns / 10),
                evidence=f"Escalated {escalation_count} times in {total_turns} turns",
                session_outcome=session_outcome,
            )
        )

        if uncertainty_count > 0:
            signals.append(
                PersonalitySignal(
                    session_id=session_id,
                    trait_category="escalation_behavior",
                    trait_name="uncertainty_threshold",
                    signal_type="inferred",
                    value=1.0 - (uncertainty_count / total_turns),
                    confidence=0.4,
                    evidence=f"Expressed uncertainty {uncertainty_count} times",
                    session_outcome=session_outcome,
                )
            )

        return signals

    async def _extract_heuristic_signals(
        self,
        agent_id: str,
        session_id: str,
        session_log: dict[str, Any],
        session_outcome: str,
    ) -> list[PersonalitySignal]:
        """Extract domain-specific heuristic signals from session log."""
        signals: list[PersonalitySignal] = []

        entries = session_log.get("entries", [])
        if not entries:
            return signals

        successful_actions: dict[str, list[str]] = {}
        failed_actions: dict[str, list[str]] = {}

        for entry in entries:
            if entry.get("event_type") != "tool_call":
                continue

            tool_name = entry.get("tool_name", "")
            result = entry.get("result", {})
            context = entry.get("context", "general")

            if result.get("success"):
                if context not in successful_actions:
                    successful_actions[context] = []
                successful_actions[context].append(tool_name)
            else:
                if context not in failed_actions:
                    failed_actions[context] = []
                failed_actions[context].append(tool_name)

        for context, tools in successful_actions.items():
            if len(tools) >= 2:
                from collections import Counter

                common_tools = Counter(tools).most_common(2)
                for tool, count in common_tools:
                    signals.append(
                        PersonalitySignal(
                            session_id=session_id,
                            trait_category="domain_heuristics",
                            trait_name=f"preferred_tool.{context}",
                            signal_type="success_pattern",
                            value=tool,
                            confidence=min(0.9, count / 5),
                            context=context,
                            evidence=f"Used {tool} {count} times successfully",
                            session_outcome=session_outcome,
                        )
                    )

        for context, tools in failed_actions.items():
            if len(tools) >= 2:
                from collections import Counter

                common_failures = Counter(tools).most_common(1)
                for tool, count in common_failures:
                    signals.append(
                        PersonalitySignal(
                            session_id=session_id,
                            trait_category="domain_heuristics",
                            trait_name=f"avoid_tool.{context}",
                            signal_type="failure_pattern",
                            value=tool,
                            confidence=min(0.7, count / 3),
                            context=context,
                            evidence=f"Tool {tool} failed {count} times",
                            session_outcome=session_outcome,
                        )
                    )

        return signals

    async def _extract_pattern_signals(
        self,
        agent_id: str,
        session_id: str,
        session_state: dict[str, Any],
        decisions: list[dict[str, Any]] | None,
        conversations: list[dict[str, Any]] | None,
        session_outcome: str,
    ) -> list[PersonalitySignal]:
        """Extract successful and avoided pattern signals."""
        signals: list[PersonalitySignal] = []

        if session_outcome == "success":
            if conversations:
                agent_messages = [
                    t.get("content", "") for t in conversations if t.get("role") == "assistant"
                ]

                if agent_messages:
                    first_message = agent_messages[0] if agent_messages else ""
                    if len(first_message) > 20:
                        signals.append(
                            PersonalitySignal(
                                session_id=session_id,
                                trait_category="successful_patterns",
                                trait_name="opening_style",
                                signal_type="success_correlation",
                                value=first_message[:100],
                                confidence=0.6,
                                context="conversation_opening",
                                evidence="Used in successful session",
                                session_outcome=session_outcome,
                            )
                        )

        elif session_outcome == "failure":
            if decisions:
                failed_decisions = [
                    d for d in decisions if not d.get("outcome", {}).get("success", True)
                ]

                for decision in failed_decisions[:3]:
                    intent = decision.get("intent", "unknown")
                    chosen = decision.get("chosen_option_id", "")

                    signals.append(
                        PersonalitySignal(
                            session_id=session_id,
                            trait_category="avoided_patterns",
                            trait_name=f"decision.{intent[:30]}",
                            signal_type="failure_correlation",
                            value=chosen,
                            confidence=0.5,
                            context=intent,
                            evidence="Decision led to failure",
                            session_outcome=session_outcome,
                        )
                    )

        return signals

    def _count_patterns(self, text: str, patterns: list[str]) -> int:
        """Count pattern matches in text."""
        count = 0
        for pattern in patterns:
            count += len(re.findall(pattern, text, re.IGNORECASE))
        return count

    async def extract_from_file(
        self,
        agent_id: str,
        session_state_path: Path,
        runtime_log_path: Path | None = None,
    ) -> list[PersonalitySignal]:
        """
        Extract signals from session files.

        Convenience method for extracting from persisted session data.
        """
        with open(session_state_path, encoding="utf-8") as f:
            session_state = json.load(f)

        session_id = session_state.get("session_id", session_state_path.parent.name)

        runtime_log = None
        if runtime_log_path and runtime_log_path.exists():
            with open(runtime_log_path, encoding="utf-8") as f:
                runtime_log = json.load(f)

        decisions = session_state.get("decisions", [])

        return await self.extract_from_session(
            agent_id=agent_id,
            session_id=session_id,
            session_state=session_state,
            session_log=runtime_log,
            decisions=decisions,
        )
