"""Agent health monitoring and metrics analysis."""

import json
import time
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

class HealthMonitor:
    def __init__(self, agent_name: str, storage_base: Path = None):
        self.agent_name = agent_name
        self.storage_base = storage_base or Path.home() / ".hive" / "storage"
        self.runs_dir = self.storage_base / agent_name / "runs"

    def get_runs(self, limit: int = 100, since: datetime = None) -> List[Dict[str, Any]]:
        """Fetch runs from storage."""
        if not self.runs_dir.exists():
            return []
            
        runs = []
        for run_file in self.runs_dir.glob("*.json"):
            try:
                # Fast metadata check using stat first?
                # For now just load generic info?
                # We need content to check success/failure
                with open(run_file, "r") as f:
                    data = json.load(f)
                    
                # Filter by time if requested
                started_at_str = data.get("started_at")
                if started_at_str and since:
                    started_at = datetime.fromisoformat(started_at_str)
                    if started_at < since:
                        continue
                        
                runs.append(data)
            except Exception:
                continue
                
        # Sort by date descending
        runs.sort(key=lambda x: x.get("started_at", ""), reverse=True)
        return runs[:limit]

    def analyze_metrics(self, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate aggregate metrics from run data."""
        if not runs:
            return {
                "total_runs": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "avg_tokens": 0.0,
                "error_rate": 0.0
            }
            
        total = len(runs)
        success = sum(1 for r in runs if r.get("status") == "completed")
        failed = sum(1 for r in runs if r.get("status") == "failed")
        
        latencies = [r.get("metrics", {}).get("total_latency_ms", 0) for r in runs]
        tokens = [r.get("metrics", {}).get("total_tokens", 0) for r in runs]
        
        # Filter out 0 latencies for valid average?
        latencies = [l for l in latencies if l]
        
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        avg_tokens = sum(tokens) / len(tokens) if tokens else 0
        
        return {
            "total_runs": total,
            "success_rate": (success / total) * 100,
            "error_rate": (failed / total) * 100,
            "avg_latency_ms": avg_latency,
            "avg_tokens": avg_tokens,
            "last_run_status": runs[0].get("status") if runs else "unknown",
            "last_run_time": runs[0].get("started_at") if runs else None
        }

    def print_dashboard(self, metrics: Dict[str, Any], live: bool = False):
        """Print health dashboard."""
        if live:
            # Clear screen
            print("\033[2J\033[H", end="")
            print(f"🔄 Watching Agent: {self.agent_name} (Ctrl+C to stop)")
        else:
            print(f"🛡️  Agent Health: {self.agent_name}")
            
        print("=" * 60)
        
        # Status Icon
        sr = metrics["success_rate"]
        if sr >= 90:
            status_icon = "🟢 HEALTHY"
        elif sr >= 70:
            status_icon = "🟡 DEGRADED"
        else:
            status_icon = "🔴 CRITICAL"
            
        print(f"Status: {status_icon}")
        print("-" * 60)
        
        print(f"Total Runs:      {metrics['total_runs']}")
        print(f"Success Rate:    {metrics['success_rate']:.1f}%")
        print(f"Error Rate:      {metrics['error_rate']:.1f}%")
        print(f"Avg Latency:     {metrics['avg_latency_ms']:.0f}ms")
        print(f"Avg Tokens:      {metrics['avg_tokens']:.0f}")
        
        if metrics.get("last_run_time"):
            print("-" * 60)
            print(f"Last Run:        {metrics['last_run_time']}")
            print(f"Last Status:     {metrics['last_run_status'].upper()}")
            
        print("=" * 60)
        if live:
            print(f"Last Updated: {datetime.now().strftime('%H:%M:%S')}")

    def watch(self, interval: int = 5):
        """Watch mode loop."""
        try:
            while True:
                runs = self.get_runs(limit=50)
                metrics = self.analyze_metrics(runs)
                self.print_dashboard(metrics, live=True)
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped watching.")

