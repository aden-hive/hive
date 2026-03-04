"""
Budget Control System for Document Intake Agent

Implements intelligent cost management with model degradation:
- Tracks LLM usage costs in real-time
- Automatically switches to cheaper models when budget is constrained
- Maintains quality thresholds while optimizing costs
- Provides cost analytics and budget alerts
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum


class ModelTier(Enum):
    """Model tiers from highest to lowest quality/cost."""
    PREMIUM = "premium"      # Claude Sonnet 4+ (highest quality, highest cost)
    STANDARD = "standard"    # Claude 3.5 Sonnet (balanced quality/cost)
    EFFICIENT = "efficient"  # Claude 3 Haiku (fast, low cost)
    MINIMAL = "minimal"      # Cheapest available model


@dataclass
class ModelConfig:
    """Configuration for a specific model tier."""
    model_name: str
    cost_per_token: float
    max_tokens: int
    use_cases: List[str]
    quality_score: float  # 0.0 to 1.0


@dataclass
class BudgetAlert:
    """Budget alert notification."""
    alert_id: str
    timestamp: datetime
    alert_type: str  # warning, critical, limit_reached
    current_usage: float
    budget_limit: float
    message: str
    recommended_action: str


class BudgetController:
    """Intelligent budget management with automatic model degradation."""

    def __init__(self, storage_path: Path, daily_budget_limit: float = 10.0):
        self.storage_path = storage_path
        self.daily_budget_limit = daily_budget_limit
        self.usage_file = storage_path / "budget_usage.json"
        self.alerts_file = storage_path / "budget_alerts.json"

        # Model tier configurations
        self.model_configs = {
            ModelTier.PREMIUM: ModelConfig(
                model_name="claude-sonnet-4-5-20250929",
                cost_per_token=0.000015,  # Example pricing
                max_tokens=4096,
                use_cases=["complex_analysis", "high_accuracy_required"],
                quality_score=1.0
            ),
            ModelTier.STANDARD: ModelConfig(
                model_name="claude-3-5-sonnet-20241022",
                cost_per_token=0.000003,  # Example pricing
                max_tokens=4096,
                use_cases=["standard_processing", "classification", "extraction"],
                quality_score=0.85
            ),
            ModelTier.EFFICIENT: ModelConfig(
                model_name="claude-3-haiku-20240307",
                cost_per_token=0.00000025,  # Example pricing
                max_tokens=4096,
                use_cases=["simple_classification", "format_detection"],
                quality_score=0.65
            ),
            ModelTier.MINIMAL: ModelConfig(
                model_name="claude-3-haiku-20240307",  # Fallback to same model with constraints
                cost_per_token=0.00000025,
                max_tokens=2048,  # Reduced token limit
                use_cases=["emergency_only"],
                quality_score=0.45
            )
        }

        # Current state
        self.current_tier = ModelTier.STANDARD
        self.daily_usage = self._load_daily_usage()

        # Ensure storage directory exists
        storage_path.mkdir(parents=True, exist_ok=True)

    def select_optimal_model(self, task_type: str, required_quality: float = 0.7) -> Tuple[ModelConfig, str]:
        """Select the best model based on budget constraints and quality requirements."""

        # Check current budget status
        remaining_budget = self.daily_budget_limit - self.daily_usage

        # Calculate budget pressure (0.0 = plenty of budget, 1.0 = budget exhausted)
        budget_pressure = self.daily_usage / self.daily_budget_limit

        # Select tier based on budget pressure and quality requirements
        selected_tier = self._select_tier_by_budget(budget_pressure, required_quality, task_type)

        # Get model config
        model_config = self.model_configs[selected_tier]

        # Generate reasoning
        reasoning = self._generate_selection_reasoning(
            selected_tier, budget_pressure, required_quality, remaining_budget
        )

        # Update current tier
        self.current_tier = selected_tier

        return model_config, reasoning

    def record_usage(self, tokens_used: int, model_tier: ModelTier, task_type: str) -> float:
        """Record LLM usage and return the cost."""

        model_config = self.model_configs[model_tier]
        cost = tokens_used * model_config.cost_per_token

        # Update daily usage
        self.daily_usage += cost

        # Record detailed usage
        usage_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "model": model_config.model_name,
            "tokens": tokens_used,
            "cost": cost,
            "task_type": task_type,
            "tier": model_tier.value,
            "daily_total": self.daily_usage
        }

        self._save_usage_record(usage_record)

        # Check for budget alerts
        self._check_budget_alerts()

        return cost

    def get_budget_status(self) -> Dict[str, Any]:
        """Get current budget status and recommendations."""

        remaining = self.daily_budget_limit - self.daily_usage
        usage_percentage = (self.daily_usage / self.daily_budget_limit) * 100

        # Determine status
        if usage_percentage >= 95:
            status = "critical"
        elif usage_percentage >= 80:
            status = "warning"
        elif usage_percentage >= 60:
            status = "caution"
        else:
            status = "healthy"

        # Calculate projected usage
        hours_passed = datetime.now().hour + (datetime.now().minute / 60)
        if hours_passed > 0:
            hourly_rate = self.daily_usage / hours_passed
            projected_daily = hourly_rate * 24
        else:
            projected_daily = self.daily_usage

        return {
            "daily_budget": self.daily_budget_limit,
            "current_usage": self.daily_usage,
            "remaining_budget": remaining,
            "usage_percentage": usage_percentage,
            "status": status,
            "current_tier": self.current_tier.value,
            "projected_daily_usage": projected_daily,
            "recommended_tier": self._recommend_tier_for_remainder(),
            "cost_savings_vs_premium": self._calculate_savings(),
        }

    def get_cost_analytics(self) -> Dict[str, Any]:
        """Generate cost analytics and insights."""

        usage_records = self._load_usage_records()

        if not usage_records:
            return {"message": "No usage data available"}

        # Analyze usage patterns
        total_cost = sum(record["cost"] for record in usage_records)
        total_tokens = sum(record["tokens"] for record in usage_records)

        # Cost by task type
        task_costs = {}
        for record in usage_records:
            task = record["task_type"]
            task_costs[task] = task_costs.get(task, 0) + record["cost"]

        # Cost by model tier
        tier_costs = {}
        for record in usage_records:
            tier = record["tier"]
            tier_costs[tier] = tier_costs.get(tier, 0) + record["cost"]

        # Calculate efficiency metrics
        avg_cost_per_token = total_cost / total_tokens if total_tokens > 0 else 0

        return {
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "avg_cost_per_token": avg_cost_per_token,
            "cost_by_task": task_costs,
            "cost_by_tier": tier_costs,
            "most_expensive_task": max(task_costs.items(), key=lambda x: x[1])[0] if task_costs else None,
            "most_efficient_tier": min(tier_costs.items(), key=lambda x: x[1])[0] if tier_costs else None,
            "potential_savings": self._calculate_potential_savings(usage_records),
        }

    def _select_tier_by_budget(self, budget_pressure: float, required_quality: float, task_type: str) -> ModelTier:
        """Select the appropriate tier based on budget pressure and requirements."""

        # Critical budget situation - use minimal tier
        if budget_pressure >= 0.95:
            return ModelTier.MINIMAL

        # High budget pressure - prefer efficient models
        elif budget_pressure >= 0.8:
            if required_quality <= 0.65:
                return ModelTier.EFFICIENT
            else:
                return ModelTier.STANDARD

        # Moderate budget pressure - balance cost and quality
        elif budget_pressure >= 0.6:
            if required_quality >= 0.9:
                return ModelTier.PREMIUM
            elif required_quality >= 0.7:
                return ModelTier.STANDARD
            else:
                return ModelTier.EFFICIENT

        # Low budget pressure - optimize for quality
        else:
            if task_type in ["complex_analysis", "high_accuracy_required"]:
                return ModelTier.PREMIUM
            else:
                return ModelTier.STANDARD

    def _generate_selection_reasoning(self, tier: ModelTier, budget_pressure: float,
                                    required_quality: float, remaining_budget: float) -> str:
        """Generate human-readable reasoning for model selection."""

        config = self.model_configs[tier]

        reasons = []

        # Budget reasoning
        if budget_pressure >= 0.8:
            reasons.append(f"High budget usage ({budget_pressure:.1%}) - selecting cost-efficient model")
        elif budget_pressure <= 0.4:
            reasons.append(f"Healthy budget ({budget_pressure:.1%}) - can use higher quality model")
        else:
            reasons.append(f"Balanced budget usage ({budget_pressure:.1%})")

        # Quality reasoning
        if config.quality_score >= required_quality:
            reasons.append(f"Selected model meets quality requirement ({config.quality_score:.1%} >= {required_quality:.1%})")
        else:
            reasons.append(f"Quality trade-off: {config.quality_score:.1%} quality for cost savings")

        # Cost reasoning
        reasons.append(f"Cost: ${config.cost_per_token:.6f} per token")
        reasons.append(f"Remaining budget: ${remaining_budget:.2f}")

        return " • ".join(reasons)

    def _recommend_tier_for_remainder(self) -> str:
        """Recommend tier for rest of day based on current usage."""

        budget_pressure = self.daily_usage / self.daily_budget_limit

        if budget_pressure >= 0.9:
            return ModelTier.MINIMAL.value
        elif budget_pressure >= 0.7:
            return ModelTier.EFFICIENT.value
        else:
            return ModelTier.STANDARD.value

    def _calculate_savings(self) -> float:
        """Calculate cost savings vs always using premium model."""

        usage_records = self._load_usage_records()
        if not usage_records:
            return 0.0

        actual_cost = sum(record["cost"] for record in usage_records)
        premium_cost = sum(
            record["tokens"] * self.model_configs[ModelTier.PREMIUM].cost_per_token
            for record in usage_records
        )

        return premium_cost - actual_cost

    def _calculate_potential_savings(self, usage_records: List[Dict]) -> Dict[str, float]:
        """Calculate potential savings with different strategies."""

        actual_cost = sum(record["cost"] for record in usage_records)

        # All efficient tier
        efficient_cost = sum(
            record["tokens"] * self.model_configs[ModelTier.EFFICIENT].cost_per_token
            for record in usage_records
        )

        # All minimal tier
        minimal_cost = sum(
            record["tokens"] * self.model_configs[ModelTier.MINIMAL].cost_per_token
            for record in usage_records
        )

        return {
            "savings_with_efficient": actual_cost - efficient_cost,
            "savings_with_minimal": actual_cost - minimal_cost,
        }

    def _check_budget_alerts(self) -> None:
        """Check if budget alerts should be triggered."""

        usage_percentage = (self.daily_usage / self.daily_budget_limit) * 100

        alerts = []

        # 80% warning
        if usage_percentage >= 80 and not self._alert_exists("warning_80"):
            alerts.append(BudgetAlert(
                alert_id="warning_80",
                timestamp=datetime.utcnow(),
                alert_type="warning",
                current_usage=self.daily_usage,
                budget_limit=self.daily_budget_limit,
                message="Budget usage has reached 80%",
                recommended_action="Consider switching to efficient models"
            ))

        # 95% critical
        if usage_percentage >= 95 and not self._alert_exists("critical_95"):
            alerts.append(BudgetAlert(
                alert_id="critical_95",
                timestamp=datetime.utcnow(),
                alert_type="critical",
                current_usage=self.daily_usage,
                budget_limit=self.daily_budget_limit,
                message="Budget usage has reached 95%",
                recommended_action="Switch to minimal model tier immediately"
            ))

        # Save new alerts
        for alert in alerts:
            self._save_alert(alert)

    def _load_daily_usage(self) -> float:
        """Load today's usage from storage."""

        if not self.usage_file.exists():
            return 0.0

        try:
            usage_data = json.loads(self.usage_file.read_text())
            today = datetime.now().date().isoformat()
            return usage_data.get(today, 0.0)
        except:
            return 0.0

    def _save_usage_record(self, record: Dict[str, Any]) -> None:
        """Save usage record to persistent storage."""

        # Update daily totals
        usage_data = {}
        if self.usage_file.exists():
            try:
                usage_data = json.loads(self.usage_file.read_text())
            except:
                usage_data = {}

        today = datetime.now().date().isoformat()
        usage_data[today] = self.daily_usage

        self.usage_file.write_text(json.dumps(usage_data, indent=2))

        # Save detailed record
        records_file = self.storage_path / "detailed_usage.json"
        records = []
        if records_file.exists():
            try:
                records = json.loads(records_file.read_text())
            except:
                records = []

        records.append(record)
        records_file.write_text(json.dumps(records, indent=2))

    def _load_usage_records(self) -> List[Dict[str, Any]]:
        """Load detailed usage records."""

        records_file = self.storage_path / "detailed_usage.json"
        if not records_file.exists():
            return []

        try:
            return json.loads(records_file.read_text())
        except:
            return []

    def _alert_exists(self, alert_id: str) -> bool:
        """Check if an alert has already been triggered today."""

        if not self.alerts_file.exists():
            return False

        try:
            alerts = json.loads(self.alerts_file.read_text())
            today = datetime.now().date().isoformat()

            for alert in alerts:
                if (alert["alert_id"] == alert_id and
                    alert["timestamp"].startswith(today)):
                    return True
        except:
            pass

        return False

    def _save_alert(self, alert: BudgetAlert) -> None:
        """Save budget alert to storage."""

        alerts = []
        if self.alerts_file.exists():
            try:
                alerts = json.loads(self.alerts_file.read_text())
            except:
                alerts = []

        alerts.append({
            "alert_id": alert.alert_id,
            "timestamp": alert.timestamp.isoformat(),
            "alert_type": alert.alert_type,
            "current_usage": alert.current_usage,
            "budget_limit": alert.budget_limit,
            "message": alert.message,
            "recommended_action": alert.recommended_action
        })

        self.alerts_file.write_text(json.dumps(alerts, indent=2))


def get_budget_controller(storage_path: Path = None, daily_limit: float = 10.0) -> BudgetController:
    """Get the budget controller for the document intake agent."""

    if storage_path is None:
        storage_path = Path.home() / ".hive" / "agents" / "document_intake_agent" / "budget"

    return BudgetController(storage_path, daily_limit)