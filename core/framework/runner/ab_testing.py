"""A/B testing for agent versions"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.runner.versioning import AgentVersionManager
from framework.schemas.version import ABTestConfig, ABTestResult


class ABTestRouter:
    """Routes requests to different versions for A/B testing using consistent hashing"""
    def __init__(
        self,
        version_manager: AgentVersionManager,
        config: ABTestConfig,
    ):
        self.manager = version_manager
        self.config = config
        self.results = ABTestResult(config=config)
        self._results_path = self._get_results_path()
        self._load_results()

    def _get_results_path(self) -> Path:
        ab_tests_dir = self.manager._ab_tests_dir(self.config.agent_id)
        test_id = f"test_{self.config.start_time.strftime('%Y%m%d_%H%M%S')}"
        return ab_tests_dir / f"{test_id}_results.json"

    def _load_results(self) -> None:
        if self._results_path.exists():
            with open(self._results_path, "r") as f:
                data = json.load(f)
                self.results = ABTestResult(**data)

    def _save_results(self) -> None:
        self._results_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._results_path, "w") as f:
            json.dump(self.results.model_dump(), f, indent=2, default=str)

    def route(self, request_id: str) -> str:
        hash_value = int(hashlib.md5(request_id.encode()).hexdigest(), 16)
        normalized = (hash_value % 1000) / 1000.0

        if normalized < self.config.traffic_split:
            return self.config.version_a
        else:
            return self.config.version_b

    def record_execution(
        self,
        request_id: str,
        version: str,
        metrics: dict[str, float] | None = None,
    ) -> None:
        if version == self.config.version_a:
            self.results.executions_a += 1
            if metrics:
                for metric, value in metrics.items():
                    if metric in self.results.metrics_a:
                        old_avg = self.results.metrics_a[metric]
                        count = self.results.executions_a
                        self.results.metrics_a[metric] = (
                            old_avg * (count - 1) + value
                        ) / count
                    else:
                        self.results.metrics_a[metric] = value

        elif version == self.config.version_b:
            self.results.executions_b += 1
            if metrics:
                for metric, value in metrics.items():
                    if metric in self.results.metrics_b:
                        old_avg = self.results.metrics_b[metric]
                        count = self.results.executions_b
                        self.results.metrics_b[metric] = (
                            old_avg * (count - 1) + value
                        ) / count
                    else:
                        self.results.metrics_b[metric] = value

        self._save_results()

    def get_results(self) -> ABTestResult:
        return self.results

    def analyze_results(self, primary_metric: str | None = None) -> dict[str, Any]:
        analysis = {
            "executions": {
                "version_a": self.results.executions_a,
                "version_b": self.results.executions_b,
                "total": self.results.executions_a + self.results.executions_b,
            },
            "metrics_comparison": {},
            "winner": None,
            "confidence": None,
        }

        all_metrics = set(self.results.metrics_a.keys()) | set(
            self.results.metrics_b.keys()
        )

        for metric in all_metrics:
            val_a = self.results.metrics_a.get(metric, 0)
            val_b = self.results.metrics_b.get(metric, 0)

            comparison = {
                "version_a": val_a,
                "version_b": val_b,
                "difference": val_b - val_a,
                "percent_change": (
                    ((val_b - val_a) / val_a * 100) if val_a > 0 else 0
                ),
            }

            if val_b > val_a:
                comparison["better"] = "version_b"
            elif val_a > val_b:
                comparison["better"] = "version_a"
            else:
                comparison["better"] = "tie"

            analysis["metrics_comparison"][metric] = comparison

        if primary_metric and primary_metric in analysis["metrics_comparison"]:
            better = analysis["metrics_comparison"][primary_metric]["better"]
            if better != "tie":
                analysis["winner"] = better
                min_executions = min(
                    self.results.executions_a, self.results.executions_b
                )
                if min_executions >= 100:
                    analysis["confidence"] = 0.95
                elif min_executions >= 50:
                    analysis["confidence"] = 0.80
                elif min_executions >= 20:
                    analysis["confidence"] = 0.60
                else:
                    analysis["confidence"] = 0.30

        return analysis

    def end_test(
        self, winner: str | None = None, notes: str = ""
    ) -> ABTestResult:
        self.config.end_time = datetime.now()
        self.results.winner = winner
        self.results.notes = notes
        self._save_results()

        return self.results


def create_ab_test_session(
    agent_id: str,
    version_a: str,
    version_b: str,
    traffic_split: float = 0.5,
    metrics: list[str] | None = None,
    versions_dir: str | Path = ".aden/versions",
) -> ABTestRouter:
    manager = AgentVersionManager(Path(versions_dir))

    config = manager.create_ab_test(
        agent_id=agent_id,
        version_a=version_a,
        version_b=version_b,
        traffic_split=traffic_split,
        metrics=metrics,
    )

    return ABTestRouter(manager, config)
