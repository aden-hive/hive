"""Feature flag system."""

from typing import Dict, Any, Optional, List
import hashlib
from .models import FeatureFlag


class FeatureFlagEngine:
    """Feature flag evaluation engine."""

    def __init__(self):
        self.flags: Dict[str, FeatureFlag] = {}

    def add_flag(self, flag: FeatureFlag) -> None:
        """Add a feature flag."""
        self.flags[flag.name] = flag

    def evaluate(
        self,
        flag_name: str,
        user_attributes: Dict[str, Any] = None
    ) -> bool:
        """Evaluate feature flag for user."""
        flag = self.flags.get(flag_name)
        if not flag:
            return False

        # If disabled, return False
        if not flag.enabled:
            return False

        # If no rules, use rollout percentage
        if not flag.rules:
            return self._rollout_check(flag_name, flag.rollout_percentage, user_attributes)

        # Evaluate rules
        return self._evaluate_rules(flag, user_attributes or {})

    def _rollout_check(
        self,
        flag_name: str,
        percentage: int,
        user_attributes: Dict[str, Any]
    ) -> bool:
        """Check rollout percentage using consistent hashing."""
        if percentage >= 100:
            return True
        if percentage <= 0:
            return False

        # Create user key for consistent hashing
        user_key = user_attributes.get("user_id", "anonymous")
        hash_input = f"{flag_name}:{user_key}"
        hash_value = int(hashlib.sha256(hash_input.encode()).hexdigest(), 16)
        bucket = hash_value % 100

        return bucket < percentage

    def _evaluate_rules(self, flag: FeatureFlag, user_attributes: Dict[str, Any]) -> bool:
        """Evaluate targeting rules."""
        for rule in flag.rules:
            if self._evaluate_rule(rule, user_attributes):
                return True
        return False

    def _evaluate_rule(self, rule: Dict[str, Any], user_attributes: Dict[str, Any]) -> bool:
        """Evaluate a single rule."""
        rule_type = rule.get("type")

        if rule_type == "user_attribute":
            attribute = rule.get("attribute")
            operator = rule.get("operator")
            value = rule.get("value")

            user_value = user_attributes.get(attribute)

            if operator == "eq":
                return user_value == value
            elif operator == "neq":
                return user_value != value
            elif operator == "endsWith":
                return str(user_value).endswith(value) if user_value else False
            elif operator == "startsWith":
                return str(user_value).startswith(value) if user_value else False
            elif operator == "contains":
                return value in str(user_value) if user_value else False

        elif rule_type == "percentage":
            percentage = rule.get("percentage", 0)
            return self._rollout_check(f"rule_{rule}", percentage, user_attributes)

        elif rule_type == "custom":
            # Custom condition evaluation (extend as needed)
            condition = rule.get("condition", "")
            return self._evaluate_custom_condition(condition, user_attributes)

        return False

    def _evaluate_custom_condition(self, condition: str, attributes: Dict[str, Any]) -> bool:
        """Evaluate custom condition (simplified)."""
        # In production, use a safer evaluation method
        # This is a placeholder for demonstration
        try:
            # Very basic evaluation - DO NOT use in production without proper sanitization
            return eval(condition, {}, {"user": attributes})
        except:
            return False

    def get_all_flags(self) -> List[FeatureFlag]:
        """Get all feature flags."""
        return list(self.flags.values())

    def get_flag(self, name: str) -> Optional[FeatureFlag]:
        """Get feature flag by name."""
        return self.flags.get(name)
