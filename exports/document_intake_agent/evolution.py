"""
Self-Evolution System for Document Intake Agent

Captures human corrections and feedback to improve future performance.
This implements Hive's self-evolution capability where human feedback
drives continuous improvement of agent accuracy.
"""

import json
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path

from .schemas import DocumentCategory, ExtractedEntity


class EvolutionTracker:
    """Tracks human corrections and feedback for continuous improvement."""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.feedback_file = storage_path / "evolution_feedback.json"
        self.corrections_file = storage_path / "field_corrections.json"
        self.patterns_file = storage_path / "learned_patterns.json"

        # Ensure storage directory exists
        storage_path.mkdir(parents=True, exist_ok=True)

    def capture_classification_correction(
        self,
        document_id: str,
        original_category: str,
        correct_category: str,
        confidence: float,
        document_text: str,
        human_reason: str
    ) -> None:
        """Capture a classification correction from human feedback."""
        correction = {
            "correction_id": f"class_{document_id}_{datetime.utcnow().isoformat()}",
            "timestamp": datetime.utcnow().isoformat(),
            "correction_type": "classification",
            "document_id": document_id,
            "original_prediction": {
                "category": original_category,
                "confidence": confidence,
            },
            "human_correction": {
                "category": correct_category,
                "reason": human_reason,
            },
            "document_context": {
                "text_sample": document_text[:500],  # First 500 chars for analysis
                "indicators": self._extract_indicators(document_text, correct_category),
            },
            "improvement_opportunity": {
                "failure_mode": self._analyze_failure_mode(original_category, correct_category),
                "suggested_patterns": self._suggest_new_patterns(document_text, correct_category),
            }
        }

        self._save_correction(correction, "classification")
        self._update_learned_patterns(correction)

    def capture_extraction_correction(
        self,
        document_id: str,
        field_name: str,
        original_value: str,
        correct_value: str,
        original_confidence: float,
        document_context: str,
        human_reason: str
    ) -> None:
        """Capture a field extraction correction from human feedback."""
        correction = {
            "correction_id": f"field_{document_id}_{field_name}_{datetime.utcnow().isoformat()}",
            "timestamp": datetime.utcnow().isoformat(),
            "correction_type": "extraction",
            "document_id": document_id,
            "field_details": {
                "field_name": field_name,
                "original_value": original_value,
                "correct_value": correct_value,
                "original_confidence": original_confidence,
            },
            "human_correction": {
                "reason": human_reason,
                "context": document_context,
            },
            "improvement_opportunity": {
                "pattern_analysis": self._analyze_extraction_pattern(
                    field_name, correct_value, document_context
                ),
                "suggested_regex": self._suggest_extraction_pattern(
                    field_name, correct_value, document_context
                ),
            }
        }

        self._save_correction(correction, "extraction")
        self._update_extraction_patterns(correction)

    def capture_routing_feedback(
        self,
        document_id: str,
        category: str,
        original_action: str,
        correct_action: str,
        human_reason: str
    ) -> None:
        """Capture routing decision feedback from human oversight."""
        feedback = {
            "feedback_id": f"route_{document_id}_{datetime.utcnow().isoformat()}",
            "timestamp": datetime.utcnow().isoformat(),
            "feedback_type": "routing",
            "document_id": document_id,
            "category": category,
            "routing_details": {
                "original_action": original_action,
                "correct_action": correct_action,
                "reason": human_reason,
            },
            "policy_implication": {
                "category_requires_review": correct_action == "human_review",
                "confidence_threshold_adjustment": self._suggest_threshold_adjustment(
                    category, original_action, correct_action
                ),
            }
        }

        self._save_correction(feedback, "routing")
        self._update_routing_policies(feedback)

    def get_improvement_suggestions(self) -> Dict[str, List[str]]:
        """Generate improvement suggestions based on collected feedback."""
        suggestions = {
            "classification_improvements": [],
            "extraction_improvements": [],
            "routing_improvements": [],
            "pattern_additions": [],
        }

        # Analyze classification patterns
        class_corrections = self._load_corrections("classification")
        if len(class_corrections) > 2:
            suggestions["classification_improvements"].extend([
                f"Consider adding indicators for {self._most_missed_category(class_corrections)}",
                f"Improve confidence calibration for {self._low_confidence_categories(class_corrections)}",
            ])

        # Analyze extraction patterns
        extract_corrections = self._load_corrections("extraction")
        if len(extract_corrections) > 2:
            field_issues = self._analyze_field_issues(extract_corrections)
            for field, issues in field_issues.items():
                suggestions["extraction_improvements"].append(
                    f"Improve {field} extraction: {issues['common_failure']}"
                )

        # Analyze routing patterns
        routing_feedback = self._load_corrections("routing")
        if len(routing_feedback) > 1:
            suggestions["routing_improvements"].extend([
                "Review confidence thresholds for auto-processing",
                "Consider category-specific routing rules",
            ])

        return suggestions

    def _extract_indicators(self, text: str, category: str) -> List[str]:
        """Extract key indicators that should have triggered correct classification."""
        # Simple implementation - could be enhanced with NLP
        indicators = []
        text_lower = text.lower()

        category_indicators = {
            "invoice": ["invoice", "bill", "payment due", "remit to", "net 30"],
            "receipt": ["receipt", "transaction", "thank you", "change", "total"],
            "contract": ["agreement", "contract", "party", "executed", "whereas"],
            "bank_statement": ["statement", "balance", "deposit", "withdrawal", "account"],
        }

        for indicator in category_indicators.get(category, []):
            if indicator in text_lower:
                indicators.append(indicator)

        return indicators

    def _analyze_failure_mode(self, original: str, correct: str) -> str:
        """Analyze why classification failed."""
        common_failures = {
            ("invoice", "receipt"): "missed_payment_direction",
            ("receipt", "invoice"): "confused_payment_status",
            ("contract", "general"): "missed_legal_language",
            ("general", "contract"): "over_general_classification",
        }

        return common_failures.get((original, correct), "unknown_failure_mode")

    def _suggest_new_patterns(self, text: str, category: str) -> List[str]:
        """Suggest new patterns to recognize this category."""
        # Basic pattern suggestions - could be enhanced
        patterns = []

        if category == "invoice":
            patterns.extend(["look for invoice numbers", "check for due dates"])
        elif category == "receipt":
            patterns.extend(["look for payment confirmation", "check for transaction IDs"])
        elif category == "contract":
            patterns.extend(["look for signature lines", "check for legal terms"])

        return patterns

    def _analyze_extraction_pattern(self, field: str, value: str, context: str) -> str:
        """Analyze extraction pattern for a corrected field."""
        return f"Field '{field}' with value '{value}' found in context: {context[:100]}..."

    def _suggest_extraction_pattern(self, field: str, value: str, context: str) -> str:
        """Suggest regex pattern for better extraction."""
        # Basic pattern generation - could be enhanced
        if field.endswith("_amount"):
            return r"\$[\d,]+\.?\d*"
        elif field.endswith("_date"):
            return r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
        elif field.endswith("_number"):
            return r"[A-Z0-9-]+\d+"
        else:
            return f"Pattern for {field}: enhance based on value '{value}'"

    def _suggest_threshold_adjustment(self, category: str, original: str, correct: str) -> Dict[str, float]:
        """Suggest confidence threshold adjustments."""
        if original == "auto_process" and correct == "human_review":
            return {"increase_threshold": 0.05}  # Be more conservative
        elif original == "human_review" and correct == "auto_process":
            return {"decrease_threshold": 0.05}  # Be less conservative
        return {}

    def _save_correction(self, correction: Dict[str, Any], correction_type: str) -> None:
        """Save correction to persistent storage."""
        filename = f"{correction_type}_corrections.json"
        filepath = self.storage_path / filename

        corrections = []
        if filepath.exists():
            corrections = json.loads(filepath.read_text())

        corrections.append(correction)
        filepath.write_text(json.dumps(corrections, indent=2))

    def _load_corrections(self, correction_type: str) -> List[Dict[str, Any]]:
        """Load corrections from persistent storage."""
        filename = f"{correction_type}_corrections.json"
        filepath = self.storage_path / filename

        if filepath.exists():
            return json.loads(filepath.read_text())
        return []

    def _update_learned_patterns(self, correction: Dict[str, Any]) -> None:
        """Update learned patterns based on correction."""
        # Implementation would update pattern recognition rules
        pass

    def _update_extraction_patterns(self, correction: Dict[str, Any]) -> None:
        """Update extraction patterns based on correction."""
        # Implementation would update extraction rules
        pass

    def _update_routing_policies(self, feedback: Dict[str, Any]) -> None:
        """Update routing policies based on feedback."""
        # Implementation would update routing rules
        pass

    def _most_missed_category(self, corrections: List[Dict[str, Any]]) -> str:
        """Find the most frequently missed category."""
        misses = {}
        for correction in corrections:
            correct_cat = correction["human_correction"]["category"]
            misses[correct_cat] = misses.get(correct_cat, 0) + 1

        return max(misses.items(), key=lambda x: x[1])[0] if misses else "unknown"

    def _low_confidence_categories(self, corrections: List[Dict[str, Any]]) -> str:
        """Find categories with consistently low confidence."""
        # Implementation would analyze confidence patterns
        return "various categories"

    def _analyze_field_issues(self, corrections: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
        """Analyze field-specific extraction issues."""
        issues = {}
        for correction in corrections:
            field = correction["field_details"]["field_name"]
            if field not in issues:
                issues[field] = {"common_failure": "pattern recognition needs improvement"}

        return issues


def get_evolution_tracker(storage_path: Path = None) -> EvolutionTracker:
    """Get the evolution tracker for the document intake agent."""
    if storage_path is None:
        storage_path = Path.home() / ".hive" / "agents" / "document_intake_agent" / "evolution"

    return EvolutionTracker(storage_path)