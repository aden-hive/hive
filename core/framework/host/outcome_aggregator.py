"""Stub — outcome aggregator removed in colony refactor."""

from framework.schemas.goal import Goal


class OutcomeAggregator:
    def __init__(self, goal: Goal, event_bus=None):
        self._goal = goal
        self._event_bus = event_bus

    def record_decision(self, **kwargs):
        pass

    def record_outcome(self, **kwargs):
        pass

    def evaluate_goal_progress(self):
        return {"progress": 0.0, "criteria_status": {}}

    def get_stats(self):
        return {"total_decisions": 0, "total_outcomes": 0}
