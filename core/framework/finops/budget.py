"""Budget policy engine for cost guardrails.

Provides:
- Configurable thresholds per agent/node/tool/model
- Actions: warn, degrade, throttle, kill
- Real-time budget monitoring
- Alert emission when thresholds are exceeded
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from framework.finops.config import BudgetAction, BudgetPolicy, BudgetThreshold, FinOpsConfig
from framework.finops.metrics import FinOpsCollector, get_collector
from framework.finops.otel import record_budget_alert
from framework.finops.prometheus import get_metrics

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class BudgetAlert:
    """A budget alert that was triggered."""

    policy_name: str
    scope: str
    scope_id: str
    action: BudgetAction
    threshold: float
    current_value: float
    threshold_percentage: float
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    run_id: str = ""
    agent_id: str = ""


BudgetActionHandler = Callable[[BudgetAlert], None]


class BudgetPolicyEngine:
    """Engine for enforcing budget policies.

    Policies can be configured for different scopes:
    - agent: Apply to all runs of an agent
    - node: Apply to a specific node type
    - tool: Apply to a specific tool
    - model: Apply to a specific model

    Actions are triggered in order of severity:
    - WARN: Log a warning, continue execution
    - DEGRADE: Switch to cheaper model or reduced functionality
    - THROTTLE: Rate limit or pause execution
    - KILL: Terminate the run immediately
    """

    def __init__(
        self,
        config: FinOpsConfig | None = None,
        collector: FinOpsCollector | None = None,
    ):
        self.config = config or FinOpsConfig.from_env()
        self.collector = collector or get_collector()
        self._policies: dict[str, BudgetPolicy] = {}
        self._action_handlers: dict[BudgetAction, list[BudgetActionHandler]] = {
            BudgetAction.WARN: [],
            BudgetAction.DEGRADE: [],
            BudgetAction.THROTTLE: [],
            BudgetAction.KILL: [],
        }
        self._alerts: list[BudgetAlert] = []
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default action handlers."""
        self.register_handler(BudgetAction.WARN, self._default_warn_handler)
        self.register_handler(BudgetAction.DEGRADE, self._default_degrade_handler)
        self.register_handler(BudgetAction.THROTTLE, self._default_throttle_handler)
        self.register_handler(BudgetAction.KILL, self._default_kill_handler)

    def register_handler(self, action: BudgetAction, handler: BudgetActionHandler) -> None:
        """Register a handler for a budget action."""
        self._action_handlers[action].append(handler)

    def unregister_handler(self, action: BudgetAction, handler: BudgetActionHandler) -> None:
        """Unregister a handler for a budget action."""
        if handler in self._action_handlers[action]:
            self._action_handlers[action].remove(handler)

    def add_policy(self, policy: BudgetPolicy) -> None:
        """Add a budget policy."""
        key = f"{policy.scope}:{policy.scope_id}"
        self._policies[key] = policy
        logger.info(f"Added budget policy: {policy.name} for {key}")

    def remove_policy(self, scope: str, scope_id: str) -> bool:
        """Remove a budget policy."""
        key = f"{scope}:{scope_id}"
        if key in self._policies:
            del self._policies[key]
            return True
        return False

    def get_policy(self, scope: str, scope_id: str) -> BudgetPolicy | None:
        """Get a budget policy by scope."""
        return self._policies.get(f"{scope}:{scope_id}")

    def list_policies(self) -> list[BudgetPolicy]:
        """List all budget policies."""
        return list(self._policies.values())

    def check_run_budget(
        self,
        run_id: str,
        agent_id: str,
        tokens: int,
        cost_usd: float,
    ) -> list[BudgetAlert]:
        """Check budget for a run.

        Args:
            run_id: Run identifier
            agent_id: Agent identifier
            tokens: Total tokens used in this run
            cost_usd: Estimated cost in USD for this run

        Returns:
            List of alerts that were triggered
        """
        alerts = []

        policies_to_check = [
            self._policies.get(f"agent:{agent_id}"),
            self._policies.get("agent:*"),
        ]
        policies_to_check = [p for p in policies_to_check if p and p.enabled]

        for policy in policies_to_check:
            alert = self._check_policy(
                policy=policy,
                run_id=run_id,
                agent_id=agent_id,
                tokens=tokens,
                cost_usd=cost_usd,
            )
            if alert:
                alerts.append(alert)
                self._execute_action(alert)

        return alerts

    def check_node_budget(
        self,
        run_id: str,
        agent_id: str,
        node_id: str,
        tokens: int,
        cost_usd: float,
    ) -> list[BudgetAlert]:
        """Check budget for a node execution."""
        alerts = []

        policies_to_check = [
            self._policies.get(f"node:{node_id}"),
            self._policies.get("node:*"),
        ]
        policies_to_check = [p for p in policies_to_check if p and p.enabled]

        for policy in policies_to_check:
            alert = self._check_policy(
                policy=policy,
                run_id=run_id,
                agent_id=agent_id,
                node_id=node_id,
                tokens=tokens,
                cost_usd=cost_usd,
            )
            if alert:
                alerts.append(alert)
                self._execute_action(alert)

        return alerts

    def check_burn_rate(
        self,
        run_id: str,
        agent_id: str,
        burn_rate: float,
    ) -> list[BudgetAlert]:
        """Check burn rate against policies."""
        alerts = []

        for policy in self._policies.values():
            if not policy.enabled or policy.burn_rate_threshold is None:
                continue

            if burn_rate > policy.burn_rate_threshold:
                percentage = (burn_rate / policy.burn_rate_threshold) * 100
                action = self._determine_action(policy, percentage)

                alert = BudgetAlert(
                    policy_name=policy.name,
                    scope=policy.scope,
                    scope_id=policy.scope_id,
                    action=action,
                    threshold=policy.burn_rate_threshold,
                    current_value=burn_rate,
                    threshold_percentage=percentage,
                    message=f"Burn rate {burn_rate:.1f} tokens/min exceeds threshold {policy.burn_rate_threshold:.1f}",
                    run_id=run_id,
                    agent_id=agent_id,
                )
                alerts.append(alert)
                self._execute_action(alert)

        return alerts

    def _check_policy(
        self,
        policy: BudgetPolicy,
        run_id: str,
        agent_id: str,
        tokens: int,
        cost_usd: float,
        node_id: str = "",
    ) -> BudgetAlert | None:
        """Check a single policy against current values."""

        if policy.max_tokens_per_run is not None:
            percentage = (tokens / policy.max_tokens_per_run) * 100
            action = self._determine_action(policy, percentage)
            if action:
                return BudgetAlert(
                    policy_name=policy.name,
                    scope=policy.scope,
                    scope_id=policy.scope_id,
                    action=action,
                    threshold=policy.max_tokens_per_run,
                    current_value=tokens,
                    threshold_percentage=percentage,
                    message=f"Token usage {tokens} exceeds threshold {policy.max_tokens_per_run}",
                    run_id=run_id,
                    agent_id=agent_id,
                )

        if policy.max_cost_usd_per_run is not None:
            percentage = (cost_usd / policy.max_cost_usd_per_run) * 100
            action = self._determine_action(policy, percentage)
            if action:
                return BudgetAlert(
                    policy_name=policy.name,
                    scope=policy.scope,
                    scope_id=policy.scope_id,
                    action=action,
                    threshold=policy.max_cost_usd_per_run,
                    current_value=cost_usd,
                    threshold_percentage=percentage,
                    message=f"Cost ${cost_usd:.4f} exceeds threshold ${policy.max_cost_usd_per_run:.4f}",
                    run_id=run_id,
                    agent_id=agent_id,
                )

        return None

    def _determine_action(self, policy: BudgetPolicy, percentage: float) -> BudgetAction | None:
        """Determine the action to take based on threshold percentage."""
        sorted_thresholds = sorted(policy.thresholds, key=lambda t: t.threshold)
        action = None
        for threshold in sorted_thresholds:
            if percentage >= threshold.threshold:
                action = threshold.action
        return action

    def _execute_action(self, alert: BudgetAlert) -> None:
        """Execute the action for an alert."""
        self._alerts.append(alert)

        record_budget_alert(
            run_id=alert.run_id,
            policy_name=alert.policy_name,
            action=alert.action.value,
            threshold=alert.threshold,
            current_value=alert.current_value,
        )

        prometheus_metrics = get_metrics()
        if prometheus_metrics:
            prometheus_metrics.record_budget_alert(
                agent_id=alert.agent_id,
                policy_name=alert.policy_name,
                action=alert.action.value,
                threshold_percentage=alert.threshold_percentage,
            )

        handlers = self._action_handlers.get(alert.action, [])
        for handler in handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Error in budget action handler: {e}")

    def _default_warn_handler(self, alert: BudgetAlert) -> None:
        """Default handler for WARN action."""
        logger.warning(
            f"Budget Alert [{alert.policy_name}]: {alert.message}",
            extra={
                "run_id": alert.run_id,
                "agent_id": alert.agent_id,
                "action": alert.action.value,
                "threshold_percentage": alert.threshold_percentage,
            },
        )

    def _default_degrade_handler(self, alert: BudgetAlert) -> None:
        """Default handler for DEGRADE action."""
        logger.warning(
            f"Budget Alert [{alert.policy_name}]: Degrading - {alert.message}",
            extra={
                "run_id": alert.run_id,
                "agent_id": alert.agent_id,
                "action": alert.action.value,
            },
        )

    def _default_throttle_handler(self, alert: BudgetAlert) -> None:
        """Default handler for THROTTLE action."""
        logger.warning(
            f"Budget Alert [{alert.policy_name}]: Throttling - {alert.message}",
            extra={
                "run_id": alert.run_id,
                "agent_id": alert.agent_id,
                "action": alert.action.value,
            },
        )

    def _default_kill_handler(self, alert: BudgetAlert) -> None:
        """Default handler for KILL action."""
        logger.error(
            f"Budget Alert [{alert.policy_name}]: KILLING RUN - {alert.message}",
            extra={
                "run_id": alert.run_id,
                "agent_id": alert.agent_id,
                "action": alert.action.value,
            },
        )
        raise BudgetExceededError(
            f"Budget exceeded: {alert.message}",
            alert=alert,
        )

    def get_alerts(self, limit: int = 100) -> list[BudgetAlert]:
        """Get recent alerts."""
        return self._alerts[-limit:]

    def clear_alerts(self) -> None:
        """Clear all alerts."""
        self._alerts.clear()

    def load_policies_from_file(self, path: Path | str) -> int:
        """Load policies from a JSON file.

        Args:
            path: Path to the policies JSON file

        Returns:
            Number of policies loaded
        """
        path = Path(path)
        if not path.exists():
            logger.warning(f"Policies file not found: {path}")
            return 0

        with open(path) as f:
            data = json.load(f)

        count = 0
        for policy_data in data.get("policies", []):
            thresholds = [
                BudgetThreshold(
                    threshold=t["threshold"],
                    action=BudgetAction(t["action"]),
                    message=t.get("message", ""),
                )
                for t in policy_data.get("thresholds", [])
            ]

            policy = BudgetPolicy(
                name=policy_data["name"],
                scope=policy_data["scope"],
                scope_id=policy_data["scope_id"],
                max_tokens_per_run=policy_data.get("max_tokens_per_run"),
                max_cost_usd_per_run=policy_data.get("max_cost_usd_per_run"),
                max_tokens_per_minute=policy_data.get("max_tokens_per_minute"),
                burn_rate_threshold=policy_data.get("burn_rate_threshold"),
                thresholds=thresholds,
                enabled=policy_data.get("enabled", True),
            )
            self.add_policy(policy)
            count += 1

        logger.info(f"Loaded {count} budget policies from {path}")
        return count

    def save_policies_to_file(self, path: Path | str) -> None:
        """Save policies to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "policies": [p.to_dict() for p in self._policies.values()],
            "updated_at": datetime.now(UTC).isoformat(),
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved {len(self._policies)} budget policies to {path}")


class BudgetExceededError(Exception):
    """Exception raised when budget is exceeded and KILL action is triggered."""

    def __init__(self, message: str, alert: BudgetAlert):
        super().__init__(message)
        self.alert = alert


_policy_engine: BudgetPolicyEngine | None = None


def get_policy_engine() -> BudgetPolicyEngine:
    """Get the global budget policy engine."""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = BudgetPolicyEngine()
    return _policy_engine


def reset_policy_engine() -> None:
    """Reset the global policy engine (mainly for testing)."""
    global _policy_engine
    _policy_engine = None
